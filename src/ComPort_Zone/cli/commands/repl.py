"""`comport-zone repl` — interactive prompt against a serial port.

Wires :class:`ReplDispatcher` (pure routing logic) to a prompt_toolkit
``PromptSession`` and a background printer thread. The printer prints RX
events live using ``patch_stdout`` so they appear above the user's
in-progress prompt line.
"""

from __future__ import annotations

import threading
from pathlib import Path
from queue import Empty
from typing import Any

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

from ...core.serial_core import decode_serial_bytes, format_hex_bytes
from ..config_resolver import load_app_settings
from ..endpoint_session import EndpointOpenError, open_cli_endpoint, require_cli_endpoint
from ..options import endpoint_flags
from ..output import CliOutput
from ..repl_dispatcher import ReplDispatcher, ReplState
from ..transports import make_lan_transport, make_serial_transport


_PROMPT_TEXT = "TX> "
_META_COMMANDS = (
    "/help",
    "/quit",
    "/exit",
    "/connect",
    "/disconnect",
    "/reconnect",
    "/set",
    "/show",
    "/hex",
    "/quick",
    "/run",
    "/log",
    "/timestamps",
    "/clear",
)


def _printer_loop(
    state: ReplState,
    event_queue,
    stop_event: threading.Event,
) -> None:
    """Drain RX/status/error events from the transport and render them.

    Runs in a daemon thread. ``patch_stdout`` is established in the main
    thread's prompt loop; plain ``click.echo`` from here is intercepted
    and printed cleanly above the prompt.
    """
    while not stop_event.is_set():
        try:
            event = event_queue.get(timeout=0.1)
        except Empty:
            continue
        if event.kind == "rx":
            text = decode_serial_bytes(event.raw) if event.raw else event.message
            if state.timestamps_enabled:
                # Local ISO; the JSON event API uses UTC, but humans
                # reading the REPL want their local clock.
                from datetime import datetime
                prefix = f"[{datetime.now().isoformat(timespec='milliseconds')}] "
            else:
                prefix = ""
            click.echo(f"{prefix}{text.rstrip()}")
            if state.log_handle is not None:
                state.log_handle.write(f"RX> {text}\n")
                state.log_handle.flush()
        elif event.kind == "error":
            click.echo(click.style(f"Error: {event.message}", fg="red"), err=True)
        elif event.kind in {"status", "progress", "connection"}:
            click.echo(click.style(event.message, fg="cyan"))


def _build_completer(history_entries: list[str]) -> WordCompleter:
    """Tab-complete against meta-commands + recent history entries.

    Quick Command labels would be a nice addition; deferred until the
    REPL grows a settings-watcher to keep the list fresh.
    """
    candidates = list(_META_COMMANDS) + list(history_entries[-50:])
    return WordCompleter(words=candidates, ignore_case=True)


@click.command("repl")
@endpoint_flags
@click.pass_context
def repl_command(ctx: click.Context, **endpoint_flag_values: Any) -> None:
    """Open an interactive prompt against the configured serial or TCP endpoint."""
    output: CliOutput = ctx.obj["output"]
    settings = load_app_settings(ctx.obj.get("config_path"))
    endpoint = require_cli_endpoint(ctx, settings, endpoint_flag_values)

    transport = make_lan_transport() if endpoint.kind == "lan" else make_serial_transport()
    state = ReplState(
        transport=transport,
        output=output,
        settings=settings,
        profile=endpoint.profile,
        config_path=ctx.obj.get("config_path"),
    )

    # Best-effort initial connect — failure isn't fatal, the user can
    # /set new params and /connect themselves.
    try:
        open_cli_endpoint(
            transport,
            endpoint,
            wait_seconds=endpoint_flag_values["wait_seconds"],
        )
        output.status(f"Connected to {endpoint.connection_summary}.")
    except EndpointOpenError as exc:
        output.error(str(exc), code=exc.exit_code)
        output.status("Type /set <key> <value> to change settings, then /connect.")

    event_queue = transport.subscribe_monitor()
    stop_event = threading.Event()
    printer = threading.Thread(
        target=_printer_loop,
        args=(state, event_queue, stop_event),
        daemon=True,
        name="comportzone-repl-printer",
    )
    printer.start()

    history = InMemoryHistory()
    for entry in settings.command_history[-200:]:
        history.append_string(entry)

    dispatcher = ReplDispatcher(state)
    session = PromptSession(history=history)

    output.status("ComPort Zone REPL. Type /help for commands, /quit to exit.")

    try:
        with patch_stdout():
            while True:
                completer = _build_completer(settings.command_history)
                try:
                    line = session.prompt(_PROMPT_TEXT, completer=completer)
                except (EOFError,):  # Ctrl-D
                    break
                except KeyboardInterrupt:  # Ctrl-C cancels current line
                    continue
                if not dispatcher.handle_line(line):
                    break
    finally:
        stop_event.set()
        transport.unsubscribe_monitor(event_queue)
        if state.log_handle is not None:
            state.log_handle.close()
            state.log_handle = None
        if transport.is_connected:
            transport.disconnect()
        output.status("REPL closed.")
