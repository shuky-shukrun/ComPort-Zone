"""`comport-zone files ...` — manage and run the Quick Files library.

Mirrors :mod:`commands.quick` for the QuickFile dataset. The extra wrinkle
is ``files run`` which accepts a label, an id, or a path — if the
identifier doesn't resolve to a saved entry it's treated as a direct path
to a command file.
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
from ...core.models import QuickFile
from ...core.quick_actions import (
    QuickFileImportOptions,
    merge_quick_files,
    read_quick_files_csv,
    write_quick_files_csv,
)
from ..config_resolver import load_app_settings, save_app_settings
from ..exit_codes import ExitCode
from ..options import serial_flags
from ..output import CliOutput
from .run import execute_run


def _file_to_row(quick_file: QuickFile) -> dict[str, Any]:
    return {
        "id": quick_file.id,
        "label": quick_file.label,
        "path": quick_file.path,
    }


def _resolve_to_path(ctx: click.Context, identifier: str) -> Path:
    """Return a usable file path for ``identifier``.

    Resolution order: saved label/id (case-insensitive), then a direct
    filesystem path. Unresolvable identifiers exit with PORT_NOT_FOUND...
    no, with GENERIC_ERROR — there's no spec-mandated code for "file not
    found in library nor on disk" so we use generic.
    """
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        entry = resolve_entry(settings.quick_files, identifier)
    except AmbiguousIdentifierError as exc:
        output.error(str(exc), code=ExitCode.USAGE_ERROR)
        ctx.exit(int(ExitCode.USAGE_ERROR))
        raise
    except EntryNotFoundError:
        candidate = Path(identifier)
        if candidate.exists() and candidate.is_file():
            return candidate
        output.error(
            f"{identifier!r} is not a saved Quick File label/id and is not "
            "an existing path.",
            code=ExitCode.GENERIC_ERROR,
        )
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        raise
    return Path(entry.path)


# ----------------------------------------------------------------- click group


@click.group("files")
def files_group() -> None:
    """Manage and run the Quick Files library."""


@files_group.command("list")
@click.pass_context
def files_list(ctx: click.Context) -> None:
    """Print every saved Quick File."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    rows = [_file_to_row(qf) for qf in settings.quick_files]
    output.table(rows, columns=["label", "path"])


@files_group.command("run")
@click.argument("identifier", metavar="LABEL_OR_ID_OR_PATH")
@click.option(
    "--param",
    "param_specs",
    multiple=True,
    metavar="KEY=VALUE",
    help="Supply a value for a {{PARAM}} placeholder. Repeatable.",
)
@click.option("--non-interactive", "non_interactive", is_flag=True)
@click.option(
    "--log",
    "log_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Append rendered TX/RX/EXPECT lines to this file.",
)
@click.option(
    "--stop-on-expect-fail/--continue-on-expect-fail",
    "stop_on_expect_fail",
    default=True,
    show_default=True,
)
@click.option(
    "--expect-timeout",
    "expect_timeout_ms",
    type=int,
    default=1000,
    show_default=True,
    metavar="MS",
)
@serial_flags
@click.pass_context
def files_run(
    ctx: click.Context,
    identifier: str,
    param_specs: tuple[str, ...],
    non_interactive: bool,
    log_path: Path | None,
    stop_on_expect_fail: bool,
    expect_timeout_ms: int,
    **serial_flag_values: Any,
) -> None:
    """Run a Quick File by label/id, falling back to a path on disk."""
    file_path = _resolve_to_path(ctx, identifier)
    execute_run(
        ctx,
        file_path=file_path,
        param_specs=param_specs,
        non_interactive=non_interactive,
        log_path=log_path,
        stop_on_expect_fail=stop_on_expect_fail,
        expect_timeout_ms=expect_timeout_ms,
        serial_flag_values=serial_flag_values,
    )


@files_group.command("add")
@click.option("--label", "label", help="Display label (defaults to the filename).")
@click.option(
    "--path",
    "file_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the command file.",
)
@click.pass_context
def files_add(ctx: click.Context, label: str | None, file_path: Path) -> None:
    """Create a new Quick File entry."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    resolved_label = (label or "").strip() or file_path.name
    new_entry = QuickFile(label=resolved_label, path=str(file_path))
    settings.quick_files.append(new_entry)
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Added Quick File {new_entry.label!r} (id={new_entry.id}).")


@files_group.command("edit")
@click.argument("identifier", metavar="LABEL_OR_ID")
@click.option("--label", "label")
@click.option(
    "--path",
    "file_path",
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.pass_context
def files_edit(
    ctx: click.Context,
    identifier: str,
    label: str | None,
    file_path: Path | None,
) -> None:
    """Update a Quick File entry's label and/or path."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        target = resolve_entry(settings.quick_files, identifier)
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
    if file_path is not None:
        target.path = str(file_path)

    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Updated Quick File {target.label!r} (id={target.id}).")


@files_group.command("remove")
@click.argument("identifier", metavar="LABEL_OR_ID")
@click.pass_context
def files_remove(ctx: click.Context, identifier: str) -> None:
    """Delete a Quick File entry."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        target = resolve_entry(settings.quick_files, identifier)
    except (AmbiguousIdentifierError, EntryNotFoundError) as exc:
        code = (
            ExitCode.USAGE_ERROR
            if isinstance(exc, AmbiguousIdentifierError)
            else ExitCode.GENERIC_ERROR
        )
        output.error(str(exc), code=code)
        ctx.exit(int(code))
        return
    settings.quick_files = [qf for qf in settings.quick_files if qf.id != target.id]
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Removed Quick File {target.label!r} (id={target.id}).")


@files_group.command("import")
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
)
@click.option(
    "--skip-duplicates/--keep-duplicates",
    "skip_duplicates",
    default=True,
    show_default=True,
)
@click.pass_context
def files_import(
    ctx: click.Context,
    csv_path: Path,
    import_mode: str,
    skip_duplicates: bool,
) -> None:
    """Import Quick Files from a CSV (label,path; aliases title/file/command_file/script)."""
    output: CliOutput = ctx.obj["output"]
    try:
        imported = read_quick_files_csv(csv_path)
    except (OSError, ValueError) as exc:
        output.error(f"Failed to read {csv_path}: {exc}", code=ExitCode.PARSE_ERROR)
        ctx.exit(int(ExitCode.PARSE_ERROR))
        return

    settings = load_app_settings(ctx.obj.get("config_path"))
    merged, result = merge_quick_files(
        settings.quick_files,
        imported,
        QuickFileImportOptions(
            replace_existing=import_mode.lower() == "replace",
            skip_duplicates=skip_duplicates,
        ),
    )
    settings.quick_files = merged
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(
        f"Imported {result.imported_count} Quick File(s){result.status_suffix()}."
    )


@files_group.command("export")
@click.argument(
    "csv_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    metavar="CSV",
)
@click.pass_context
def files_export(ctx: click.Context, csv_path: Path) -> None:
    """Export every Quick File to a CSV."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    try:
        write_quick_files_csv(csv_path, settings.quick_files)
    except OSError as exc:
        output.error(f"Failed to write {csv_path}: {exc}", code=ExitCode.GENERIC_ERROR)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        return
    output.status(f"Exported {len(settings.quick_files)} Quick File(s) to {csv_path}.")
