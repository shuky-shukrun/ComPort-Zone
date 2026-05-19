"""`comport-zone settings ...` — read and write the schema-v2 payload.

Five subcommands:

* ``show [--section ...]``     dump everything (or one named section).
* ``get DOTTED.KEY``           print a single value (preserving JSON type).
* ``set DOTTED.KEY VALUE``     validate, coerce, save.
* ``export PATH``              schema-v2 JSON (libraries excluded — they
                               have CSV flows; matches the GUI's
                               File > App Settings Import / Export).
* ``import PATH [--dry-run]``  merge an exported payload back in; dry-run
                               parses but does not save.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from ...core.models import AppSettings, SETTINGS_SCHEMA_VERSION
from ..config_resolver import load_app_settings, save_app_settings
from ..exit_codes import ExitCode
from ..output import CliOutput
from ..settings_keys import (
    SECTION_NAMES,
    GuiOnlyKeyError,
    LibraryManagedKeyError,
    ReadOnlyKeyError,
    SettingsValueError,
    UnknownKeyError,
    get_value,
    set_value,
)


def _payload(ctx: click.Context) -> dict[str, Any]:
    settings = load_app_settings(ctx.obj.get("config_path"))
    return settings.to_dict()


def _stringify_for_plain_output(value: Any) -> str:
    """Render a leaf value in a way that round-trips through the eye —
    JSON for structured nodes, ``repr``-free for strings/bools/numbers.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, sort_keys=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# -------------------------------------------------------------------- group

@click.group("settings")
def settings_group() -> None:
    """Inspect and modify settings.json (schema-v2 payload)."""


@settings_group.command("show")
@click.option(
    "--section",
    "section",
    type=click.Choice(sorted(SECTION_NAMES), case_sensitive=False),
    help="Limit output to one top-level section.",
)
@click.pass_context
def settings_show(ctx: click.Context, section: str | None) -> None:
    """Print the entire settings payload (or one section)."""
    output: CliOutput = ctx.obj["output"]
    payload = _payload(ctx)
    if section is None:
        if output.json_mode:
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
            return
        # Plain mode: dump compact JSON so structured fields stay readable.
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    section = section.lower()
    if section not in payload:
        output.error(
            f"Section {section!r} is not present in this settings file.",
            code=ExitCode.SETTINGS_ERROR,
        )
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    click.echo(json.dumps({section: payload[section]}, indent=2, sort_keys=True))


@settings_group.command("get")
@click.argument("key", metavar="DOTTED.KEY")
@click.pass_context
def settings_get(ctx: click.Context, key: str) -> None:
    """Print a single settings value."""
    output: CliOutput = ctx.obj["output"]
    payload = _payload(ctx)
    try:
        value = get_value(payload, key)
    except UnknownKeyError as exc:
        output.error(str(exc), code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    if output.json_mode:
        click.echo(json.dumps({"key": key, "value": value}, indent=2, sort_keys=True))
    else:
        click.echo(_stringify_for_plain_output(value))


@settings_group.command("set")
@click.argument("key", metavar="DOTTED.KEY")
@click.argument("value", metavar="VALUE")
@click.pass_context
def settings_set(ctx: click.Context, key: str, value: str) -> None:
    """Update a single settings value (refuses GUI-only and library keys)."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    payload = settings.to_dict()
    try:
        coerced = set_value(payload, key, value)
    except (GuiOnlyKeyError, LibraryManagedKeyError, ReadOnlyKeyError) as exc:
        # Spec: refuse with exit 2 and a clear message.
        output.error(str(exc), code=ExitCode.USAGE_ERROR)
        ctx.exit(int(ExitCode.USAGE_ERROR))
        return
    except UnknownKeyError as exc:
        output.error(str(exc), code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    except SettingsValueError as exc:
        output.error(str(exc), code=ExitCode.USAGE_ERROR)
        ctx.exit(int(ExitCode.USAGE_ERROR))
        return

    # Round-trip through AppSettings so any schema-derived normalization
    # (e.g. clamping page_index, defaulting unknown enums) is applied.
    new_settings = AppSettings.from_dict(payload)
    if not save_app_settings(ctx.obj.get("config_path"), new_settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Set {key} = {_stringify_for_plain_output(coerced)}")


@settings_group.command("export")
@click.argument(
    "target_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    metavar="PATH",
)
@click.pass_context
def settings_export(ctx: click.Context, target_path: Path) -> None:
    """Export the schema-v2 payload (without libraries) to PATH.

    Matches the GUI's File > App Settings Import / Export flow — Quick
    Commands and Quick Files are excluded because they have dedicated CSV
    import/export commands.
    """
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    payload = settings.to_app_settings_dict()
    try:
        target_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        output.error(f"Failed to write {target_path}: {exc}", code=ExitCode.GENERIC_ERROR)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        return
    output.status(f"Exported app settings to {target_path}.")


@settings_group.command("import")
@click.argument(
    "source_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    metavar="PATH",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Validate the payload without saving.",
)
@click.pass_context
def settings_import(ctx: click.Context, source_path: Path, dry_run: bool) -> None:
    """Import an exported settings payload (libraries are preserved)."""
    output: CliOutput = ctx.obj["output"]

    try:
        text = source_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        output.error(f"Failed to parse {source_path}: {exc}", code=ExitCode.PARSE_ERROR)
        ctx.exit(int(ExitCode.PARSE_ERROR))
        return

    if not isinstance(payload, dict):
        output.error(
            f"{source_path} must contain a JSON object at top level.",
            code=ExitCode.PARSE_ERROR,
        )
        ctx.exit(int(ExitCode.PARSE_ERROR))
        return

    schema_version = payload.get("schema_version")
    if schema_version != SETTINGS_SCHEMA_VERSION:
        output.error(
            f"Unsupported schema_version {schema_version!r}; "
            f"expected {SETTINGS_SCHEMA_VERSION}.",
            code=ExitCode.SETTINGS_ERROR,
        )
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return

    # Parse into AppSettings (validates structure). Preserve existing
    # libraries — the spec excludes them from import/export.
    existing = load_app_settings(ctx.obj.get("config_path"))
    try:
        imported = AppSettings.from_dict(payload)
    except (TypeError, ValueError) as exc:
        output.error(f"Settings payload rejected: {exc}", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return

    imported.quick_commands = existing.quick_commands
    imported.quick_files = existing.quick_files
    imported.quick_command_sort_mode = existing.quick_command_sort_mode
    imported.quick_command_hidden_groups = existing.quick_command_hidden_groups
    imported.quick_file_sort_mode = existing.quick_file_sort_mode

    if dry_run:
        output.status(f"Validated {source_path} (--dry-run; no changes saved).")
        return

    if not save_app_settings(ctx.obj.get("config_path"), imported):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Imported app settings from {source_path}.")
