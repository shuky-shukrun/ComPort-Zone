"""`comport-zone listen` - stream RX from a serial port to stdout.

Runs until Ctrl+C or until ``--duration`` elapses. ``--filter`` drops
events that don't match the regex; ``--hex`` switches the display to
hex bytes; ``--timestamps`` prefixes each line with the local time;
``--log`` mirrors the rendered output to a file.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty
from typing import Any, TextIO

import click

from ...core.serial_core import SerialEvent, decode_serial_bytes, format_hex_bytes
from ..config_resolver import load_app_settings
from ..endpoint_session import EndpointOpenError, open_cli_endpoint, require_cli_endpoint
from ..options import endpoint_flags
from ..output import CliOutput
from ..transports import make_lan_transport, make_serial_transport


def _local_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _format_rx_for_display(event: SerialEvent, *, as_hex: bool, timestamps: bool) -> tuple[str, str]:
    """Return ``(display_line, text_for_filter)``.

    ``text_for_filter`` is always the decoded text - the filter regex
    applies to characters even when the display mode is hex, so users get
    consistent matching irrespective of mode.
    """
    text = decode_serial_bytes(event.raw)
    if as_hex:
        body = format_hex_bytes(event.raw)
    else:
        body = text.rstrip("\r\n") if text.endswith(("\r", "\n")) else text
    line = f"[{_local_timestamp()}] {body}" if timestamps else body
    return line, text


@click.command("listen")
@click.option("--timestamps", "timestamps", is_flag=True, help="Prefix each line with the local time.")
@click.option("--hex", "as_hex", is_flag=True, help="Render RX as hex bytes.")
@click.option(
    "--text",
    "as_text",
    is_flag=True,
    help="Render RX as decoded text (default; explicit flag for spec compatibility).",
)
@click.option(
    "--filter",
    "filter_pattern",
    metavar="REGEX",
    help="Only emit events whose decoded text matches REGEX.",
)
@click.option(
    "--log",
    "log_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Append each rendered line to this file.",
)
@click.option(
    "--duration",
    "duration_seconds",
    type=float,
    metavar="SECONDS",
    help="Stop listening after this many seconds (default: run until Ctrl+C).",
)
@endpoint_flags
@click.pass_context
def listen_command(
    ctx: click.Context,
    timestamps: bool,
    as_hex: bool,
    as_text: bool,
    filter_pattern: str | None,
    log_path: Path | None,
    duration_seconds: float | None,
    **endpoint_flag_values: Any,
) -> None:
    """Open a serial or TCP endpoint and stream RX to stdout."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    endpoint = require_cli_endpoint(ctx, settings, endpoint_flag_values)

    transport = make_lan_transport() if endpoint.kind == "lan" else make_serial_transport()
    try:
        open_cli_endpoint(
            transport,
            endpoint,
            wait_seconds=endpoint_flag_values["wait_seconds"],
        )
    except EndpointOpenError as exc:
        output.error(str(exc), code=exc.exit_code)
        ctx.exit(int(exc.exit_code))
        return

    pattern = re.compile(filter_pattern) if filter_pattern else None
    log_handle: TextIO | None = None
    if log_path is not None:
        log_handle = open(log_path, "a", encoding="utf-8")
    event_queue = transport.subscribe_monitor()
    deadline = (
        time.monotonic() + duration_seconds
        if duration_seconds is not None
        else None
    )

    try:
        output.status(
            f"Listening on {endpoint.connection_summary}. "
            "Press Ctrl+C to stop."
        )
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            poll_timeout = 0.2
            if deadline is not None:
                poll_timeout = min(poll_timeout, max(0.0, deadline - time.monotonic()))
            try:
                event = event_queue.get(timeout=poll_timeout)
            except Empty:
                continue

            if event.kind == "rx":
                line, text_for_filter = _format_rx_for_display(
                    event, as_hex=as_hex, timestamps=timestamps
                )
                if pattern and not pattern.search(text_for_filter):
                    continue
                if output.json_mode:
                    output.event(
                        "rx",
                        data=text_for_filter,
                        hex=format_hex_bytes(event.raw),
                        **endpoint.rx_fields(),
                    )
                else:
                    click.echo(line)
                if log_handle is not None:
                    log_handle.write(line + "\n")
                    log_handle.flush()
            elif event.kind == "error":
                output.error(event.message)
            elif event.kind in {"status", "progress", "connection"}:
                output.status(event.message)
    except KeyboardInterrupt:
        # Click will translate to exit 130 in standalone mode; we surface
        # a clean status before bubbling out.
        output.status("Interrupted.")
        raise
    finally:
        if log_handle is not None:
            log_handle.close()
        try:
            transport.unsubscribe_monitor(event_queue)
        finally:
            transport.disconnect()
            output.status("Disconnected.")
