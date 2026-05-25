"""`comport-zone ports list` and `comport-zone ports info <COM>`.

The serial-port list comes straight from ``pyserial`` so the CLI surfaces
the full set of metadata (manufacturer, vid/pid, serial number, location)
that pyserial knows about - the GUI's internal abstraction only forwards
device/description/hwid, which is too narrow for the CLI spec's columns.
"""

from __future__ import annotations

from typing import Any

import click
from serial.tools import list_ports

from ..exit_codes import ExitCode
from ..output import CliOutput


# Columns required by the CLI spec for the table view. JSON mode keeps the
# full dict (any extra fields pyserial provides are passed through).
_LIST_COLUMNS = ["port", "description", "manufacturer", "hwid"]


def _serialize_port(info: Any) -> dict[str, Any]:
    """Turn a ``ListPortInfo`` into a JSON-friendly dict."""
    return {
        "port": getattr(info, "device", "") or "",
        "name": getattr(info, "name", "") or "",
        "description": (getattr(info, "description", "") or "").strip(),
        "manufacturer": (getattr(info, "manufacturer", "") or "").strip(),
        "product": (getattr(info, "product", "") or "").strip(),
        "hwid": (getattr(info, "hwid", "") or "").strip(),
        "vid": _format_id(getattr(info, "vid", None)),
        "pid": _format_id(getattr(info, "pid", None)),
        "serial_number": (getattr(info, "serial_number", "") or "").strip(),
        "interface": (getattr(info, "interface", "") or "").strip(),
        "location": (getattr(info, "location", "") or "").strip(),
    }


def _format_id(value: int | None) -> str:
    if value is None:
        return ""
    return f"0x{value:04X}"


def _collect_ports() -> list[dict[str, Any]]:
    return sorted(
        (_serialize_port(info) for info in list_ports.comports()),
        key=lambda row: row["port"],
    )


@click.group("ports")
def ports_group() -> None:
    """List and inspect serial ports."""


@ports_group.command("list")
@click.pass_context
def ports_list(ctx: click.Context) -> None:
    """List available COM ports."""
    output: CliOutput = ctx.obj["output"]
    rows = _collect_ports()
    output.table(rows, columns=_LIST_COLUMNS)


@ports_group.command("info")
@click.argument("port_name", metavar="COM")
@click.pass_context
def ports_info(ctx: click.Context, port_name: str) -> None:
    """Detailed info for a single port. Exit 14 if not found."""
    output: CliOutput = ctx.obj["output"]
    needle = port_name.upper()
    for info in _collect_ports():
        if info["port"].upper() == needle:
            output.object(info)
            return
    output.error(
        f"Port {port_name!r} not found.",
        code=ExitCode.PORT_NOT_FOUND,
    )
    ctx.exit(int(ExitCode.PORT_NOT_FOUND))
