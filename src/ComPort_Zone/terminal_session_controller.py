from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .batch import (
    BatchRunner,
    find_batch_parameters,
    parse_batch_script,
    parse_batch_template,
    parse_hex_payload,
    substitute_batch_parameters,
)
from .history import HistoryStore
from .models import QuickCommand, SerialProfile
from .session_log import SessionLogger
from .transports import SerialTransportAdapter, TransportAdapter


ParameterSheet = tuple[dict[str, str], set[str]]
ParameterCollector = Callable[[Iterable[Any]], ParameterSheet | None]
ParameterPrompt = Callable[[str, int, str], str | None]


@dataclass(frozen=True, slots=True)
class ScriptRunResult:
    started: bool
    status_text: str = ""
    empty: bool = False


class TerminalSessionController:
    def __init__(
        self,
        profile: SerialProfile,
        *,
        history_commands: Iterable[str],
        parameter_prompt: ParameterPrompt,
        transport: TransportAdapter | None = None,
    ) -> None:
        self.profile = profile
        self.transport = transport or SerialTransportAdapter()
        self.serial_client = getattr(self.transport, "client", self.transport)
        self.history_store = HistoryStore(history_commands)
        self.logger = SessionLogger()
        self.batch_runner = BatchRunner(
            event_queue=self.transport.events,
            send_text=self.transport.send_text,
            send_bytes=self.transport.send_bytes,
            connected_supplier=lambda: self.transport.is_connected,
            event_queue_factory=self.transport.subscribe_events,
            event_queue_disposer=self.transport.unsubscribe_events,
        )

    def replace_history(self, commands: Iterable[str]) -> None:
        self.history_store = HistoryStore(commands)

    def toggle_connection(
        self,
        *,
        open_connection_settings: Callable[..., Any],
        set_status: Callable[[str], None],
        update_connection_ui: Callable[[bool], None],
        append_status: Callable[[str], None],
        save_settings: Callable[[], None],
    ) -> bool:
        retrying = self.transport.is_reconnecting
        if self.transport.is_connected or retrying:
            self.transport.disconnect()
            if retrying:
                append_status("Auto-reconnect stopped.")
            update_connection_ui(False)
            save_settings()
            return True
        if not self.profile.port:
            open_connection_settings(connect_after_accept=True)
            return False
        set_status(f"Connecting to {self.profile.port}...")
        self.transport.connect(self.profile)
        update_connection_ui(self.transport.is_connected)
        save_settings()
        return True

    def send_payload(self, raw: str, mode: str) -> None:
        if mode == "Hex Bytes":
            self.transport.send_bytes(parse_hex_payload(raw))
            return
        lines = raw.splitlines() if "\n" in raw or "\r" in raw else [raw]
        for line in lines:
            if line.strip():
                self.transport.send_text(line.strip())

    def send_input(
        self,
        raw: str,
        mode: str,
        *,
        record_command: Callable[[str], None],
    ) -> bool:
        cleaned = raw.strip()
        if not cleaned:
            return False
        self.send_payload(raw, mode)
        record_command(cleaned)
        return True

    def send_quick_command(
        self,
        command: QuickCommand,
        *,
        record_command: Callable[[str], None],
    ) -> None:
        if command.send_mode == "Hex Bytes":
            self.transport.send_bytes(parse_hex_payload(command.command))
        else:
            self.transport.send_text(
                command.command,
                command.line_ending_override or None,
            )
        record_command(command.command)

    def run_script_text(
        self,
        script_text: str,
        *,
        source_label: str = "Editor buffer",
        source_path: Path | None = None,
        collect_parameter_values: ParameterCollector,
        parameter_prompt: ParameterPrompt,
        set_last_script_path: Callable[[Path], None],
    ) -> ScriptRunResult:
        if not script_text.strip():
            return ScriptRunResult(started=False, empty=True)

        parameter_occurrences = find_batch_parameters(script_text)
        if parameter_occurrences:
            parameter_sheet = collect_parameter_values(parameter_occurrences)
            if parameter_sheet is None:
                return ScriptRunResult(started=False)
            parameter_values, ignored_defaults = parameter_sheet
            template_steps = parse_batch_template(script_text)

            def resolve_line(line: str, line_number: int) -> str | None:
                return substitute_batch_parameters(
                    line,
                    parameter_values,
                    parameter_prompt,
                    line_number,
                    ignored_defaults,
                )

            if source_path is not None:
                set_last_script_path(source_path.parent)
            self.batch_runner.start_template(template_steps, resolve_line)
            return ScriptRunResult(
                started=True,
                status_text=f"Running command file: {source_label}",
            )

        steps = parse_batch_script(script_text)
        if source_path is not None:
            set_last_script_path(source_path.parent)
        self.batch_runner.start(steps)
        return ScriptRunResult(
            started=True,
            status_text=f"Running command file: {source_label}",
        )

    def stop_script(self) -> None:
        self.batch_runner.stop()

    def start_logging(self, path: str | Path) -> None:
        self.logger.open(path)

    def stop_logging(self) -> Path | None:
        path = self.logger.path
        self.logger.close()
        return path
