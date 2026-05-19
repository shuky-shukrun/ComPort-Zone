"""Pure logic for the REPL — no prompt_toolkit, no threading.

The Click ``repl`` subcommand glues this to a :class:`PromptSession` and a
background printer thread; the actual command routing lives here so it
can be unit-tested with a fake transport and ordinary string input.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from ..core.batch import parse_batch_template, find_batch_parameters
from ..core.library_lookup import (
    AmbiguousIdentifierError,
    EntryNotFoundError,
    resolve_entry,
)
from ..core.models import AppSettings, SerialProfile
from ..core.serial_core import decode_serial_bytes, format_hex_bytes
from ..core.transports import SerialTransportAdapter
from .command_file_runner import RunOutcome, run_command_file
from .commands.send import _parse_hex_payload
from .config_resolver import save_app_settings
from .output import CliOutput
from .serial_session import SerialSessionError, open_serial


# CLI shortcut → dotted SerialProfile key for ``/set``. Kept narrow on
# purpose: this is the set users plausibly tweak between connects.
_SET_SHORTCUTS: dict[str, str] = {
    "port": "port",
    "baud": "baudrate",
    "data-bits": "bytesize",
    "parity": "parity",
    "stop-bits": "stopbits",
    "flow-control": "flow_control",
    "line-ending": "line_ending",
    "dtr": "dtr",
    "rts": "rts",
}


@dataclass(slots=True)
class ReplState:
    """Mutable per-session state.

    Held by :class:`ReplDispatcher` so meta commands and tests share the
    same view. The transport is a real :class:`SerialTransportAdapter`
    in production and a fake in tests.
    """

    transport: SerialTransportAdapter
    output: CliOutput
    settings: AppSettings
    profile: SerialProfile
    config_path: Path | None = None
    timestamps_enabled: bool = False
    log_handle: TextIO | None = None
    quit_requested: bool = False
    history_buffer: list[str] = field(default_factory=list)


class ReplDispatcher:
    """Route one user-entered line — meta command vs serial send."""

    def __init__(self, state: ReplState) -> None:
        self.state = state
        self._handlers: dict[str, Callable[[list[str]], None]] = {
            "/help": self._cmd_help,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/connect": self._cmd_connect,
            "/disconnect": self._cmd_disconnect,
            "/reconnect": self._cmd_reconnect,
            "/set": self._cmd_set,
            "/show": self._cmd_show,
            "/hex": self._cmd_hex,
            "/quick": self._cmd_quick,
            "/run": self._cmd_run,
            "/log": self._cmd_log,
            "/timestamps": self._cmd_timestamps,
            "/clear": self._cmd_clear,
        }

    # ----------------------------------------------------------- main entry

    def handle_line(self, line: str) -> bool:
        """Process one input line. Returns ``False`` if the REPL should exit."""
        if line is None:
            return False
        stripped = line.strip()
        if not stripped:
            return True
        if stripped.startswith("/"):
            self._dispatch_meta(stripped)
        else:
            self._send_text(line)
        return not self.state.quit_requested

    def _dispatch_meta(self, line: str) -> None:
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            self.state.output.error(f"Unparseable meta command: {exc}")
            return
        if not tokens:
            return
        cmd = tokens[0].lower()
        args = tokens[1:]
        handler = self._handlers.get(cmd)
        if handler is None:
            self.state.output.error(
                f"Unknown meta command {cmd!r}. Try /help for the list."
            )
            return
        try:
            handler(args)
        except Exception as exc:  # surface but don't crash the REPL
            self.state.output.error(f"{cmd}: {exc}")

    # ----------------------------------------------------------- send path

    def _send_text(self, text: str) -> None:
        if not self.state.transport.is_connected:
            self.state.output.error("Not connected. Use /connect first.")
            return
        try:
            self.state.transport.send_text(text)
        except Exception as exc:
            self.state.output.error(f"Send failed: {exc}")
            return
        self.state.output.event("tx", display=text, mode="text")
        self._record_log("TX", text)
        self._append_history(text)

    def _record_log(self, kind: str, body: str) -> None:
        handle = self.state.log_handle
        if handle is None:
            return
        handle.write(f"{kind}> {body}\n")
        handle.flush()

    def _append_history(self, entry: str) -> None:
        entry = entry.rstrip("\r\n")
        if not entry:
            return
        # Avoid logging the same command twice in a row, matching the GUI.
        history = self.state.settings.command_history
        if not history or history[-1] != entry:
            history.append(entry)
        if entry not in self.state.history_buffer or self.state.history_buffer[-1] != entry:
            self.state.history_buffer.append(entry)
        # Persist asynchronously? Synchronous keeps the GUI in sync, and
        # the Stage 1 advisory lock makes this safe.
        save_app_settings(self.state.config_path, self.state.settings)

    # -------------------------------------------------------- meta-commands

    def _cmd_help(self, args: list[str]) -> None:
        lines = [
            "Meta commands:",
            "  /help                          show this list",
            "  /quit, /exit                   exit the REPL (Ctrl-D also works)",
            "  /connect                       open the configured port",
            "  /disconnect                    close the port",
            "  /reconnect                     close then re-open",
            "  /set <key> <value>             change a serial setting",
            "                                 (port|baud|data-bits|parity|stop-bits|",
            "                                  flow-control|line-ending|dtr|rts)",
            "  /show settings | /show port    inspect current state",
            "  /hex <bytes>                   send hex bytes",
            "  /quick <label-or-id>           send a saved Quick Command",
            "  /run <file> [--param K=V ...]  run a command file",
            "  /log start <path> | /log stop  mirror RX/TX to a file",
            "  /timestamps on|off             toggle timestamp prefix on RX lines",
            "  /clear                         print a separator line",
            "Anything not starting with / is sent over the serial port.",
        ]
        for line in lines:
            self.state.output.status(line)

    def _cmd_quit(self, args: list[str]) -> None:
        self.state.quit_requested = True

    def _cmd_connect(self, args: list[str]) -> None:
        try:
            open_serial(self.state.transport, self.state.profile, wait_seconds=0.0)
        except SerialSessionError as exc:
            self.state.output.error(str(exc), code=exc.exit_code)
            return
        self.state.output.status(
            f"Connected to {self.state.profile.port} @ {self.state.profile.baudrate}."
        )

    def _cmd_disconnect(self, args: list[str]) -> None:
        if not self.state.transport.is_connected:
            self.state.output.status("Already disconnected.")
            return
        self.state.transport.disconnect()
        self.state.output.status("Disconnected.")

    def _cmd_reconnect(self, args: list[str]) -> None:
        if self.state.transport.is_connected:
            self.state.transport.disconnect()
        self._cmd_connect(args)

    def _cmd_set(self, args: list[str]) -> None:
        if len(args) != 2:
            self.state.output.error("Usage: /set <key> <value>")
            return
        raw_key, raw_value = args
        key = raw_key.lower()
        attr = _SET_SHORTCUTS.get(key)
        if attr is None:
            self.state.output.error(
                f"Unknown /set key {raw_key!r}. "
                f"Valid keys: {', '.join(sorted(_SET_SHORTCUTS))}."
            )
            return
        coerced = self._coerce_profile_value(attr, raw_value)
        if coerced is None:
            return  # error already emitted
        setattr(self.state.profile, attr, coerced)
        # Mirror the change into the persisted SerialProfile.
        setattr(self.state.settings.serial, attr, coerced)
        if not save_app_settings(self.state.config_path, self.state.settings):
            self.state.output.error("Failed to persist settings.json.")
            return
        self.state.output.status(f"Set {key} = {coerced}")

    def _coerce_profile_value(self, attr: str, raw: str) -> Any:
        """Map a CLI value string to the SerialProfile attribute's type.

        Returns ``None`` after emitting an error if the value is invalid;
        the caller checks for ``None`` rather than catching.
        """
        if attr in {"bytesize"}:
            try:
                return int(raw)
            except ValueError:
                self.state.output.error(f"/set {attr} expects an integer (got {raw!r}).")
                return None
        if attr == "baudrate":
            try:
                return int(raw)
            except ValueError:
                self.state.output.error(f"/set baud expects an integer (got {raw!r}).")
                return None
        if attr == "stopbits":
            try:
                return float(raw)
            except ValueError:
                self.state.output.error(f"/set stop-bits expects a number (got {raw!r}).")
                return None
        if attr in {"dtr", "rts"}:
            lowered = raw.strip().lower()
            if lowered in {"on", "true", "1", "yes"}:
                return True
            if lowered in {"off", "false", "0", "no"}:
                return False
            self.state.output.error(f"/set {attr} expects on/off (got {raw!r}).")
            return None
        if attr == "parity":
            value = raw.strip().upper()
            if value not in {"N", "E", "O", "M", "S"}:
                self.state.output.error(
                    "/set parity expects one of N/E/O/M/S."
                )
                return None
            return value
        if attr == "flow_control":
            mapping = {
                "none": "None",
                "rtscts": "RTS/CTS",
                "xonxoff": "XON/XOFF",
                "dsrdtr": "DSR/DTR",
            }
            normalized = mapping.get(raw.strip().lower())
            if normalized is None:
                self.state.output.error(
                    "/set flow-control expects none/rtscts/xonxoff/dsrdtr."
                )
                return None
            return normalized
        if attr == "line_ending":
            mapping = {"none": "None", "cr": "CR", "lf": "LF", "crlf": "CRLF"}
            normalized = mapping.get(raw.strip().lower())
            if normalized is None:
                self.state.output.error(
                    "/set line-ending expects none/CR/LF/CRLF."
                )
                return None
            return normalized
        return raw  # plain string fields (port)

    def _cmd_show(self, args: list[str]) -> None:
        if not args:
            self.state.output.error("Usage: /show settings|port")
            return
        what = args[0].lower()
        if what == "settings":
            self.state.output.object(self.state.profile.to_dict())
            return
        if what == "port":
            payload = {
                "connected": self.state.transport.is_connected,
                "reconnecting": self.state.transport.is_reconnecting,
                "port": self.state.profile.port,
                "baud": self.state.profile.baudrate,
            }
            self.state.output.object(payload)
            return
        self.state.output.error(f"Unknown /show target {args[0]!r}.")

    def _cmd_hex(self, args: list[str]) -> None:
        if not self.state.transport.is_connected:
            self.state.output.error("Not connected. Use /connect first.")
            return
        if not args:
            self.state.output.error("Usage: /hex <bytes>")
            return
        try:
            data = _parse_hex_payload(" ".join(args))
        except Exception as exc:
            self.state.output.error(f"/hex: {exc}")
            return
        try:
            self.state.transport.send_bytes(data)
        except Exception as exc:
            self.state.output.error(f"/hex send failed: {exc}")
            return
        rendered = f"HEX {format_hex_bytes(data)}"
        self.state.output.event("tx", display=rendered, mode="hex")
        self._record_log("TX", rendered)
        self._append_history(" ".join(args))

    def _cmd_quick(self, args: list[str]) -> None:
        if not args:
            self.state.output.error("Usage: /quick <label-or-id>")
            return
        try:
            command = resolve_entry(self.state.settings.quick_commands, args[0])
        except AmbiguousIdentifierError as exc:
            self.state.output.error(str(exc))
            return
        except EntryNotFoundError as exc:
            self.state.output.error(str(exc))
            return
        if not self.state.transport.is_connected:
            self.state.output.error("Not connected. Use /connect first.")
            return
        try:
            if command.send_mode == "Hex Bytes":
                data = _parse_hex_payload(command.command)
                self.state.transport.send_bytes(data)
                self.state.output.event(
                    "tx", display=f"HEX {format_hex_bytes(data)}", mode="hex"
                )
            else:
                line_ending = command.line_ending_override or None
                self.state.transport.send_text(command.command, line_ending)
                self.state.output.event(
                    "tx", display=command.command, mode="text"
                )
        except Exception as exc:
            self.state.output.error(f"/quick send failed: {exc}")
            return
        self._record_log("TX", command.command)
        self._append_history(command.command)

    def _cmd_run(self, args: list[str]) -> None:
        if not args:
            self.state.output.error("Usage: /run <file> [--param K=V ...]")
            return
        path = Path(args[0])
        if not path.is_file():
            self.state.output.error(f"/run: file not found: {path}")
            return
        if not self.state.transport.is_connected:
            self.state.output.error("/run: not connected. Use /connect first.")
            return

        params: dict[str, str] = {}
        idx = 1
        while idx < len(args):
            token = args[idx]
            if token == "--param" and idx + 1 < len(args):
                key, _, value = args[idx + 1].partition("=")
                if key:
                    params[key] = value
                idx += 2
                continue
            self.state.output.error(f"/run: unexpected argument {token!r}")
            return

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.state.output.error(f"/run: could not read {path}: {exc}")
            return

        template = parse_batch_template(text)
        occurrences = find_batch_parameters(text)
        # Fill in defaults; missing required-no-default params abort.
        for occurrence in occurrences:
            if occurrence.name in params:
                continue
            if occurrence.default is not None:
                params.setdefault(occurrence.name, occurrence.default)
                continue
            self.state.output.error(
                f"/run: missing --param {occurrence.name}= (line {occurrence.line_number})"
            )
            return

        def on_event(kind: str, fields: dict[str, Any]) -> None:
            if kind == "tx":
                self.state.output.event("tx", **fields)
            elif kind == "rx":
                self.state.output.event("rx", display=fields.get("data", ""), **fields)
            elif kind == "expect":
                self.state.output.event("expect", **fields)
            elif kind == "status":
                self.state.output.status(fields.get("message", ""))
            elif kind == "error":
                self.state.output.error(fields.get("message", ""))

        outcome: RunOutcome = run_command_file(
            self.state.transport,
            template,
            params,
            on_event=on_event,
        )
        if outcome.success:
            self.state.output.status(
                f"/run done: {outcome.steps_run} step(s), "
                f"{outcome.expect_failures} EXPECT failure(s)."
            )
        else:
            self.state.output.error(
                f"/run failed: {outcome.failure_message}"
                if outcome.failure_message
                else "/run failed."
            )

    def _cmd_log(self, args: list[str]) -> None:
        if not args:
            self.state.output.error("Usage: /log start <path> | /log stop")
            return
        sub = args[0].lower()
        if sub == "start":
            if len(args) < 2:
                self.state.output.error("Usage: /log start <path>")
                return
            if self.state.log_handle is not None:
                self.state.log_handle.close()
            try:
                self.state.log_handle = open(args[1], "a", encoding="utf-8")
            except OSError as exc:
                self.state.output.error(f"/log: cannot open {args[1]}: {exc}")
                return
            self.state.output.status(f"Logging to {args[1]}.")
            return
        if sub == "stop":
            if self.state.log_handle is None:
                self.state.output.status("Logging was not active.")
                return
            self.state.log_handle.close()
            self.state.log_handle = None
            self.state.output.status("Logging stopped.")
            return
        self.state.output.error(f"Unknown /log subcommand {args[0]!r}.")

    def _cmd_timestamps(self, args: list[str]) -> None:
        if not args or args[0].lower() not in {"on", "off"}:
            self.state.output.error("Usage: /timestamps on|off")
            return
        self.state.timestamps_enabled = args[0].lower() == "on"
        self.state.output.status(
            f"Timestamps {'enabled' if self.state.timestamps_enabled else 'disabled'}."
        )

    def _cmd_clear(self, args: list[str]) -> None:
        # CLI scrollback isn't ours to clear; print a separator the user
        # can grep for / scroll to.
        self.state.output.status("---")
