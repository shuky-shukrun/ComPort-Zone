"""Click root group and entry point for the CLI.

The dispatcher in :mod:`ComPort_Zone.__main__` decides whether to launch the
GUI (no args, or ``gui`` first arg) or hand off to this module. By keeping
the GUI bootstrap out of here, importing :mod:`ComPort_Zone.cli.main` stays
PySide-free, which the ``tests/test_core_no_pyside.py`` guard enforces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from .commands.files import files_group
from .commands.listen import listen_command
from .commands.ports import ports_group
from .commands.quick import quick_group
from .commands.run import run_command
from .commands.send import hex_command, send_command
from .commands.validate import validate_command
from .commands.version import version_command
from .output import CliOutput


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


@click.group(
    name="comport-zone",
    context_settings=CONTEXT_SETTINGS,
    help=(
        "ComPort Zone command-line interface.\n\n"
        "Run without arguments (or with `gui`) to launch the desktop app. "
        "Use a subcommand for headless workflows - listing ports, sending "
        "data, streaming RX, etc. Settings are shared with the GUI via "
        "%LOCALAPPDATA%\\ComPortZone\\settings.json."
    ),
)
@click.option("--json", "json_mode", is_flag=True, help="Emit machine-readable output.")
@click.option("--no-color", "no_color", is_flag=True, help="Disable ANSI colors.")
@click.option("--quiet", "quiet", is_flag=True, help="Suppress status messages.")
@click.option("--verbose", "verbose", is_flag=True, help="Include debug events.")
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    metavar="PATH",
    help="Override the settings.json location.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    json_mode: bool,
    no_color: bool,
    quiet: bool,
    verbose: bool,
    config_path: Path | None,
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["output"] = CliOutput(
        json_mode=json_mode,
        quiet=quiet,
        verbose=verbose,
        color=not no_color,
    )
    ctx.obj["config_path"] = config_path


cli.add_command(version_command)
cli.add_command(ports_group)
cli.add_command(send_command)
cli.add_command(hex_command)
cli.add_command(listen_command)
cli.add_command(run_command)
cli.add_command(validate_command)
cli.add_command(quick_group)
cli.add_command(files_group)


def run(argv: list[str] | None = None) -> int:
    """Invoke the CLI as if from the shell.

    Returns the exit code so callers can re-raise as ``SystemExit`` or
    forward to the OS. Click runs in standalone mode so its own exit
    handling (usage errors → 2, KeyboardInterrupt → 130) applies, which
    matches the documented exit-code table.
    """
    try:
        return cli.main(args=argv, prog_name="comport-zone", standalone_mode=True) or 0
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
