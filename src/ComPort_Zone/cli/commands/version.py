"""`comport-zone version` - print app/python/pyserial versions."""

from __future__ import annotations

import platform
import sys

import click
import serial

from ... import __version__ as APP_VERSION
from ..output import CliOutput


@click.command("version")
@click.pass_context
def version_command(ctx: click.Context) -> None:
    """Print application, Python, and pyserial versions."""
    output: CliOutput = ctx.obj["output"]
    payload = {
        "comport_zone": APP_VERSION,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "pyserial": getattr(serial, "__version__", "unknown"),
        "platform": platform.platform(),
    }
    output.object(payload)
