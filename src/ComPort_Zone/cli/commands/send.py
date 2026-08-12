"""`comport-zone send <text>` and `comport-zone hex <bytes...>`.

Opens the configured port, sends one message, optionally waits for an
EXPECT match or a fixed RX window, then closes. Exit codes follow the
documented CLI contract.
"""

from __future__ import annotations

import re
import time
from queue import Empty, Queue
from typing import Any

import click

from ...core.serial_core import SerialEvent, decode_serial_bytes, format_hex_bytes
from ..config_resolver import load_app_settings
from ..endpoint_session import EndpointOpenError, open_cli_endpoint, require_cli_endpoint
from ..exit_codes import ExitCode
from ..options import endpoint_flags
from ..output import CliOutput
from ..transports import make_transport


_DEFAULT_EXPECT_TIMEOUT_MS = 1000


def _parse_hex_payload(text: str) -> bytes:
    """Accept space-separated bytes (``"55 AA"``), continuous hex
    (``"55AA"``), or 0x-prefixed bytes (``"0x55 0xAA"``).
    """
    cleaned = text.replace(",", " ").strip()
    if not cleaned:
        raise click.BadParameter("Empty hex payload.")

    tokens: list[str] = []
    for piece in cleaned.split():
        if piece.lower().startswith("0x"):
            tokens.append(piece[2:])
        else:
            tokens.append(piece)

    joined = "".join(tokens)
    if len(joined) % 2 != 0:
        raise click.BadParameter(
            f"Hex payload must have an even number of nibbles, got {joined!r}."
        )
    try:
        return bytes.fromhex(joined)
    except ValueError as exc:
        raise click.BadParameter(f"Invalid hex bytes: {exc}") from exc


def run_send_once(
    ctx: click.Context,
    *,
    payload: str,
    as_hex: bool,
    expect: str | None,
    expect_timeout_ms: int,
    read_after_ms: int,
    endpoint_flag_values: dict[str, Any],
    line_ending_override: str | None = None,
) -> None:
    """Open the configured serial, TCP, or UDP endpoint, send a single message,
    optionally wait for a response, then close. Shared between ``send`` /
    ``hex`` / ``quick send`` so the per-command code only assembles the inputs.
    """
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    endpoint = require_cli_endpoint(ctx, settings, endpoint_flag_values)

    transport = make_transport(endpoint.kind)
    try:
        open_cli_endpoint(
            transport,
            endpoint,
            wait_seconds=endpoint_flag_values["wait_seconds"],
        )
    except EndpointOpenError as exc:
        output.error(str(exc), code=exc.exit_code)
        ctx.exit(int(exc.exit_code))
        return  # for mypy

    event_queue = transport.subscribe_monitor()
    try:
        output.status(f"Connected to {endpoint.connection_summary}")

        if as_hex:
            data = _parse_hex_payload(payload)
            transport.send_bytes(data)
            output.event("tx", mode="hex", data=payload, display=f"HEX {format_hex_bytes(data)}")
        else:
            transport.send_text(payload, line_ending_override)
            output.event("tx", mode="text", data=payload, display=payload)

        rx_buffer = bytearray()
        deadline_ms = max(
            expect_timeout_ms if expect is not None else 0,
            read_after_ms,
        )
        if deadline_ms <= 0 and expect is None:
            # Nothing to wait for - just give the reader a moment to flush
            # whatever was already in flight. A datagram device answers once,
            # in its own time, so UDP holds the window open longer.
            deadline_ms = endpoint.default_read_window_ms

        pattern = re.compile(expect) if expect else None
        matched = False
        match_after_ms: int | None = None

        deadline = time.monotonic() + deadline_ms / 1000.0
        start = time.monotonic()

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                event = event_queue.get(timeout=min(remaining, 0.1))
            except Empty:
                continue
            _emit_event_through_output(output, event)
            if event.kind == "rx":
                rx_buffer.extend(event.raw)
                if pattern and not matched:
                    if pattern.search(decode_serial_bytes(bytes(rx_buffer))):
                        matched = True
                        match_after_ms = int((time.monotonic() - start) * 1000)
                        if read_after_ms <= 0:
                            break

        if pattern is not None:
            output.event(
                "expect",
                pattern=expect,
                matched=matched,
                after_ms=match_after_ms,
            )
            if not matched:
                output.error(
                    f"EXPECT pattern {expect!r} not seen within "
                    f"{expect_timeout_ms} ms.",
                    code=ExitCode.EXPECT_FAILED,
                )
                ctx.exit(int(ExitCode.EXPECT_FAILED))
                return

    finally:
        try:
            transport.unsubscribe_monitor(event_queue)
        finally:
            transport.disconnect()
            output.status("Disconnected.")


def _emit_event_through_output(output: CliOutput, event: SerialEvent) -> None:
    if event.kind == "rx":
        text = decode_serial_bytes(event.raw)
        output.event(
            "rx",
            data=text,
            hex=format_hex_bytes(event.raw) if event.raw else "",
            display=text.rstrip("\r\n") or text,
        )
    elif event.kind == "tx":
        output.event("tx", display=event.message, data=event.message)
    elif event.kind == "error":
        output.error(event.message)
    elif event.kind in {"status", "progress", "connection"}:
        output.status(event.message)


@click.command("send")
@click.argument("text")
@click.option("--hex", "as_hex", is_flag=True, help="Interpret TEXT as space-separated bytes.")
@click.option(
    "--expect",
    "expect",
    metavar="REGEX",
    help="Require RX to match REGEX within --expect-timeout. Exit 11 on timeout.",
)
@click.option(
    "--expect-timeout",
    "expect_timeout_ms",
    type=int,
    default=_DEFAULT_EXPECT_TIMEOUT_MS,
    show_default=True,
    metavar="MS",
    help="Timeout for --expect in milliseconds.",
)
@click.option(
    "--read-after",
    "read_after_ms",
    type=int,
    default=0,
    show_default=True,
    metavar="MS",
    help="Capture RX for N ms after send and print.",
)
@endpoint_flags
@click.pass_context
def send_command(
    ctx: click.Context,
    text: str,
    as_hex: bool,
    expect: str | None,
    expect_timeout_ms: int,
    read_after_ms: int,
    **endpoint_flag_values: Any,
) -> None:
    """Open a serial, TCP, or UDP endpoint, send TEXT once, optionally wait, close."""
    run_send_once(
        ctx,
        payload=text,
        as_hex=as_hex,
        expect=expect,
        expect_timeout_ms=expect_timeout_ms,
        read_after_ms=read_after_ms,
        endpoint_flag_values=endpoint_flag_values,
    )


@click.command("hex")
@click.argument("bytes_text", nargs=-1, required=True)
@click.option(
    "--expect",
    "expect",
    metavar="REGEX",
    help="Require RX to match REGEX within --expect-timeout. Exit 11 on timeout.",
)
@click.option(
    "--expect-timeout",
    "expect_timeout_ms",
    type=int,
    default=_DEFAULT_EXPECT_TIMEOUT_MS,
    show_default=True,
    metavar="MS",
    help="Timeout for --expect in milliseconds.",
)
@click.option(
    "--read-after",
    "read_after_ms",
    type=int,
    default=0,
    show_default=True,
    metavar="MS",
    help="Capture RX for N ms after send and print.",
)
@endpoint_flags
@click.pass_context
def hex_command(
    ctx: click.Context,
    bytes_text: tuple[str, ...],
    expect: str | None,
    expect_timeout_ms: int,
    read_after_ms: int,
    **endpoint_flag_values: Any,
) -> None:
    """Convenience alias for ``send --hex`` - accepts BYTES... as positional args."""
    payload = " ".join(bytes_text)
    run_send_once(
        ctx,
        payload=payload,
        as_hex=True,
        expect=expect,
        expect_timeout_ms=expect_timeout_ms,
        read_after_ms=read_after_ms,
        endpoint_flag_values=endpoint_flag_values,
    )
