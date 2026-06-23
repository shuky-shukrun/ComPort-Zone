"""`comport-zone quick ...` — manage and run the Quick Commands library.

Subcommands mirror the GUI's Quick Commands flows:

* ``list``                — print the library (optionally filtered by group).
* ``send <label-or-id>``  — open the port and send a saved command.
* ``add``                 — create a new entry.
* ``edit <label-or-id>``  — update an existing entry's fields.
* ``remove <label-or-id>``— delete an entry.
* ``import <csv>``        — bulk-add from a CSV using the documented format.
* ``export <csv>``        — write the library as CSV.

All mutations save through :func:`save_app_settings`, which uses the
advisory lock + atomic write added in Stage 1, so a running GUI is safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from ...core.library_lookup import (
    AmbiguousIdentifierError,
    EntryNotFoundError,
    resolve_entry,
)
from ...core.models import LINE_ENDINGS, QuickCommand
from ...core.quick_actions import (
    QuickCommandImportOptions,
    merge_quick_commands,
    quick_command_csv_row,
    quick_group_name,
    read_quick_commands_csv,
    write_quick_commands_csv,
)
from ..config_resolver import load_app_settings, save_app_settings
from ..exit_codes import ExitCode
from ..options import endpoint_flags
from ..output import CliOutput
from .send import run_send_once


_VALID_MODES = {"text": "Text", "hex": "Hex Bytes"}
_VALID_LINE_ENDINGS = {key.lower(): key for key in LINE_ENDINGS.keys()}


# ----------------------------------------------------------- helpers / resolve

def _resolve_command(
    ctx: click.Context, identifier: str
) -> tuple[QuickCommand, int]:
    """Look the entry up. On miss / ambiguity, emit a CLI error and exit
    with the appropriate code — never return ``None``.
    """
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        command = resolve_entry(settings.quick_commands, identifier)
    except AmbiguousIdentifierError as exc:
        output.error(str(exc), code=ExitCode.USAGE_ERROR)
        ctx.exit(int(ExitCode.USAGE_ERROR))
        raise  # unreachable, but keeps the type narrow
    except EntryNotFoundError as exc:
        output.error(str(exc), code=ExitCode.GENERIC_ERROR)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        raise
    index = settings.quick_commands.index(command)
    return command, index


def _normalize_mode(value: str | None) -> str | None:
    if value is None:
        return None
    return _VALID_MODES[value.lower()]


def _normalize_line_ending(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "":
        return ""
    return _VALID_LINE_ENDINGS[value.lower()]


def _command_to_row(command: QuickCommand) -> dict[str, Any]:
    return {
        "id": command.id,
        "label": command.label,
        "command": command.command,
        "group": quick_group_name(command.group),
        "mode": command.send_mode,
        "line_ending": command.line_ending_override or "",
        "description": command.description,
    }


# ------------------------------------------------------------------- group/CLI


@click.group("quick")
def quick_group() -> None:
    """Manage and run the Quick Commands library."""


@quick_group.command("list")
@click.option("--group", "group_filter", metavar="NAME", help="Filter by group.")
@click.pass_context
def quick_list(ctx: click.Context, group_filter: str | None) -> None:
    """Print every saved Quick Command."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    rows = [_command_to_row(cmd) for cmd in settings.quick_commands]
    if group_filter:
        needle = group_filter.casefold()
        rows = [row for row in rows if str(row["group"]).casefold() == needle]
    output.table(rows, columns=["label", "group", "mode", "command"])


@quick_group.command("send")
@click.argument("identifier", metavar="LABEL_OR_ID")
@endpoint_flags
@click.pass_context
def quick_send(
    ctx: click.Context, identifier: str, **endpoint_flag_values: Any
) -> None:
    """Open a serial or TCP endpoint and send the saved command LABEL_OR_ID."""
    command, _ = _resolve_command(ctx, identifier)
    run_send_once(
        ctx,
        payload=command.command,
        as_hex=command.send_mode == "Hex Bytes",
        expect=None,
        expect_timeout_ms=0,
        read_after_ms=0,
        endpoint_flag_values=endpoint_flag_values,
        line_ending_override=command.line_ending_override or None,
    )


def _quick_command_shared_options(func):
    """Decorator stack for add / edit — both accept the same field flags."""
    decorators = [
        click.option("--label", "label", help="Display label (must be set on add)."),
        click.option("--command", "command_text", help="Command text to send."),
        click.option("--description", "description", help="Free-form notes."),
        click.option("--group", "group", help="Group name (defaults to 'General')."),
        click.option(
            "--mode",
            "mode",
            type=click.Choice(["text", "hex"], case_sensitive=False),
            help="Send mode.",
        ),
        click.option(
            "--line-ending",
            "line_ending",
            type=click.Choice(["none", "CR", "LF", "CRLF"], case_sensitive=False),
            help="Per-command line-ending override.",
        ),
    ]
    for decorator in reversed(decorators):
        func = decorator(func)
    return func


@quick_group.command("add")
@_quick_command_shared_options
@click.pass_context
def quick_add(
    ctx: click.Context,
    label: str | None,
    command_text: str | None,
    description: str | None,
    group: str | None,
    mode: str | None,
    line_ending: str | None,
) -> None:
    """Create a new Quick Command entry."""
    output: CliOutput = ctx.obj["output"]
    if not label or not command_text:
        output.error(
            "Both --label and --command are required.",
            code=ExitCode.USAGE_ERROR,
        )
        ctx.exit(int(ExitCode.USAGE_ERROR))
        return

    settings = load_app_settings(ctx.obj.get("config_path"))
    new_entry = QuickCommand(
        label=label.strip(),
        command=command_text,
        description=(description or "").strip(),
        send_mode=_normalize_mode(mode) or "Text",
        group=quick_group_name(group or ""),
        line_ending_override=_normalize_line_ending(line_ending) or "",
    )
    settings.quick_commands.append(new_entry)
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Added Quick Command {new_entry.label!r} (id={new_entry.id}).")


@quick_group.command("edit")
@click.argument("identifier", metavar="LABEL_OR_ID")
@_quick_command_shared_options
@click.pass_context
def quick_edit(
    ctx: click.Context,
    identifier: str,
    label: str | None,
    command_text: str | None,
    description: str | None,
    group: str | None,
    mode: str | None,
    line_ending: str | None,
) -> None:
    """Update fields on an existing Quick Command."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        target = resolve_entry(settings.quick_commands, identifier)
    except (AmbiguousIdentifierError, EntryNotFoundError) as exc:
        code = (
            ExitCode.USAGE_ERROR
            if isinstance(exc, AmbiguousIdentifierError)
            else ExitCode.GENERIC_ERROR
        )
        output.error(str(exc), code=code)
        ctx.exit(int(code))
        return

    if label is not None:
        target.label = label.strip()
    if command_text is not None:
        target.command = command_text
    if description is not None:
        target.description = description.strip()
    if group is not None:
        target.group = quick_group_name(group)
    if mode is not None:
        target.send_mode = _normalize_mode(mode) or target.send_mode
    if line_ending is not None:
        target.line_ending_override = _normalize_line_ending(line_ending) or ""

    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Updated Quick Command {target.label!r} (id={target.id}).")


@quick_group.command("remove")
@click.argument("identifier", metavar="LABEL_OR_ID")
@click.pass_context
def quick_remove(ctx: click.Context, identifier: str) -> None:
    """Delete a Quick Command."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        target = resolve_entry(settings.quick_commands, identifier)
    except (AmbiguousIdentifierError, EntryNotFoundError) as exc:
        code = (
            ExitCode.USAGE_ERROR
            if isinstance(exc, AmbiguousIdentifierError)
            else ExitCode.GENERIC_ERROR
        )
        output.error(str(exc), code=code)
        ctx.exit(int(code))
        return
    settings.quick_commands = [c for c in settings.quick_commands if c.id != target.id]
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Removed Quick Command {target.label!r} (id={target.id}).")


@quick_group.command("import")
@click.argument(
    "csv_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    metavar="CSV",
)
@click.option(
    "--mode",
    "import_mode",
    type=click.Choice(["append", "replace"], case_sensitive=False),
    default="append",
    show_default=True,
    help="Whether to merge with existing entries (append) or replace them.",
)
@click.option(
    "--skip-duplicates/--keep-duplicates",
    "skip_duplicates",
    default=True,
    show_default=True,
    help="Skip rows whose (group, label, command, mode) already exist.",
)
@click.pass_context
def quick_import(
    ctx: click.Context,
    csv_path: Path,
    import_mode: str,
    skip_duplicates: bool,
) -> None:
    """Import Quick Commands from a CSV (label,command,description,send_mode,group,line_ending_override)."""
    output: CliOutput = ctx.obj["output"]
    try:
        imported = read_quick_commands_csv(csv_path)
    except (OSError, ValueError) as exc:
        output.error(f"Failed to read {csv_path}: {exc}", code=ExitCode.PARSE_ERROR)
        ctx.exit(int(ExitCode.PARSE_ERROR))
        return

    settings = load_app_settings(ctx.obj.get("config_path"))
    merged, result = merge_quick_commands(
        settings.quick_commands,
        imported,
        QuickCommandImportOptions(
            replace_existing=import_mode.lower() == "replace",
            skip_duplicates=skip_duplicates,
        ),
    )
    settings.quick_commands = merged
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(
        f"Imported {result.imported_count} Quick Command(s){result.status_suffix()}."
    )


@quick_group.command("export")
@click.argument(
    "csv_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    metavar="CSV",
)
@click.pass_context
def quick_export(ctx: click.Context, csv_path: Path) -> None:
    """Export every Quick Command to a CSV."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        write_quick_commands_csv(csv_path, settings.quick_commands)
    except OSError as exc:
        output.error(f"Failed to write {csv_path}: {exc}", code=ExitCode.GENERIC_ERROR)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        return
    output.status(f"Exported {len(settings.quick_commands)} Quick Command(s) to {csv_path}.")
