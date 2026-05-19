"""`comport-zone history list|clear` — manage the shared command history.

The same list the GUI maintains under ``AppSettings.command_history`` —
edits made here are visible to a running GUI on the next refresh.
"""

from __future__ import annotations

import click

from ..config_resolver import load_app_settings, save_app_settings
from ..exit_codes import ExitCode
from ..output import CliOutput


@click.group("history")
def history_group() -> None:
    """List and clear the shared command history."""


@history_group.command("list")
@click.option(
    "--limit",
    "limit",
    type=int,
    metavar="N",
    help="Show only the most recent N entries.",
)
@click.pass_context
def history_list(ctx: click.Context, limit: int | None) -> None:
    """Print the command history (most-recent last, matching the GUI)."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    entries = list(settings.command_history)
    if limit is not None and limit >= 0:
        entries = entries[-limit:]
    rows = [{"index": idx, "command": entry} for idx, entry in enumerate(entries, start=1)]
    output.table(rows, columns=["index", "command"])


@history_group.command("clear")
@click.pass_context
def history_clear(ctx: click.Context) -> None:
    """Erase the shared command history."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    previous = len(settings.command_history)
    settings.command_history = []
    if not save_app_settings(ctx.obj.get("config_path"), settings):
        output.error("Failed to persist settings.json.", code=ExitCode.SETTINGS_ERROR)
        ctx.exit(int(ExitCode.SETTINGS_ERROR))
        return
    output.status(f"Cleared command history ({previous} entries).")
