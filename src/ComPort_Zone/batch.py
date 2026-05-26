from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import perf_counter

from .serial_core import SerialEvent

WAIT_PATTERN = re.compile(r"^WAIT\s+(\d+)$", re.IGNORECASE)
SEND_PATTERN = re.compile(r"^SEND\s+(.+)$", re.IGNORECASE)
HEX_PATTERN = re.compile(r"^HEX\s+([0-9A-Fa-f\s]+)$", re.IGNORECASE)
EXPECT_PATTERN = re.compile(r"^EXPECT\s+(.+)$", re.IGNORECASE)
PARAMETER_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:=([^{}]*?))?\s*\}\}")
HIGH_RES_WAIT_THRESHOLD_SECONDS = 0.020
COARSE_WAIT_CHUNK_SECONDS = 0.050
DEFAULT_EXPECT_TIMEOUT_MS = 1000


class BatchParseError(ValueError):
    def __init__(self, message: str, line_number: int) -> None:
        super().__init__(f"Line {line_number}: {message}")
        self.line_number = line_number


@dataclass(slots=True)
class BatchStep:
    kind: str
    payload: str | bytes | int
    line_number: int


@dataclass(slots=True)
class BatchTemplateStep:
    line: str
    line_number: int


@dataclass(slots=True)
class BatchParameterOccurrence:
    name: str
    default: str | None
    line_number: int
    line_text: str


@dataclass(slots=True)
class BatchParameterInputLine:
    line_number: int
    line_text: str
    parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchRunSnapshot:
    is_running: bool
    is_paused: bool = False
    is_stopping: bool = False
    pause_reason: str = ""
    can_resume: bool = False


BatchLineResolver = Callable[[str, int], str | None]
BatchParameterPrompt = Callable[[str, int, str], str | None]
EventQueueFactory = Callable[[], Queue[SerialEvent]]
EventQueueDisposer = Callable[[Queue[SerialEvent]], None]


def parse_hex_payload(text: str) -> bytes:
    normalized = text.replace(",", " ").replace("-", " ")
    parts = [part.removeprefix("0x").removeprefix("0X") for part in normalized.split()]
    compact = "".join(parts)
    if not compact:
        raise ValueError("Provide at least one byte.")
    if len(compact) % 2 != 0:
        raise ValueError("HEX byte count must be even.")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("HEX payload contains invalid characters.") from exc


def strip_c_style_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


def _batch_command_lines(text: str) -> list[BatchTemplateStep]:
    steps: list[BatchTemplateStep] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = strip_c_style_comment(raw_line)
        if not stripped or stripped.startswith("#"):
            continue
        steps.append(BatchTemplateStep(stripped, line_number))
    return steps


def parse_batch_line(line: str, line_number: int) -> BatchStep:
    stripped = line.strip()
    if not stripped:
        raise BatchParseError("Line became empty after parameter substitution.", line_number)
    wait_match = WAIT_PATTERN.match(stripped)
    if wait_match:
        return BatchStep("wait", int(wait_match.group(1)), line_number)
    expect_match = EXPECT_PATTERN.match(stripped)
    if expect_match:
        expected = expect_match.group(1).strip()
        if not expected:
            raise BatchParseError("EXPECT requires text to match.", line_number)
        return BatchStep("expect", expected, line_number)
    send_match = SEND_PATTERN.match(stripped)
    if send_match:
        return BatchStep("send", send_match.group(1), line_number)
    hex_match = HEX_PATTERN.match(stripped)
    if hex_match:
        try:
            payload = parse_hex_payload(hex_match.group(1))
        except ValueError as exc:
            raise BatchParseError(str(exc), line_number) from exc
        return BatchStep("hex", payload, line_number)
    return BatchStep("send", stripped, line_number)


def parse_batch_script(text: str) -> list[BatchStep]:
    return [parse_batch_line(step.line, step.line_number) for step in _batch_command_lines(text)]


def parse_batch_template(text: str) -> list[BatchTemplateStep]:
    return _batch_command_lines(text)


def find_batch_parameters(text: str) -> list[BatchParameterOccurrence]:
    occurrences: list[BatchParameterOccurrence] = []
    for step in _batch_command_lines(text):
        for match in PARAMETER_PATTERN.finditer(step.line):
            default = match.group(2)
            occurrences.append(
                BatchParameterOccurrence(
                    name=match.group(1),
                    default=default.strip() if default is not None else None,
                    line_number=step.line_number,
                    line_text=step.line,
                )
            )
    return occurrences


def batch_parameter_input_lines(text: str) -> list[BatchParameterInputLine]:
    values: dict[str, str] = {}
    prompt_names: set[str] = set()
    lines: list[BatchParameterInputLine] = []
    for step in _batch_command_lines(text):
        line_parameters: list[str] = []
        seen_on_line: set[str] = set()
        for match in PARAMETER_PATTERN.finditer(step.line):
            name = match.group(1)
            default = match.group(2)
            default_value = default.strip() if default is not None else None
            if name in values:
                continue
            if default_value:
                values[name] = default_value
                continue
            if name not in prompt_names and name not in seen_on_line:
                line_parameters.append(name)
                prompt_names.add(name)
                seen_on_line.add(name)
        if line_parameters:
            lines.append(BatchParameterInputLine(step.line_number, step.line, tuple(line_parameters)))
    return lines


def substitute_batch_parameters(
    line: str,
    values: dict[str, str],
    prompt: BatchParameterPrompt,
    line_number: int,
    ignored_defaults: set[str] | None = None,
) -> str | None:
    cancelled = False
    ignored_defaults = ignored_defaults or set()

    def replace(match: re.Match[str]) -> str:
        nonlocal cancelled
        name = match.group(1)
        default = match.group(2)
        default_value = default.strip() if default is not None else None
        if name in values:
            return values[name]
        if default_value and name not in ignored_defaults:
            values[name] = default_value
            return default_value
        value = prompt(name, line_number, line)
        if value is None:
            cancelled = True
            return ""
        values[name] = value
        return value

    substituted = PARAMETER_PATTERN.sub(replace, line)
    if cancelled:
        return None
    return substituted


def load_batch_file(path: str | Path) -> list[BatchStep]:
    return parse_batch_script(Path(path).read_text(encoding="utf-8"))


class BatchRunner:
    def __init__(
        self,
        *,
        event_queue: Queue[SerialEvent],
        send_text,
        send_bytes,
        connected_supplier,
        event_queue_factory: EventQueueFactory | None = None,
        event_queue_disposer: EventQueueDisposer | None = None,
        expect_timeout_ms: int = DEFAULT_EXPECT_TIMEOUT_MS,
    ) -> None:
        self._event_queue = event_queue
        self._send_text = send_text
        self._send_bytes = send_bytes
        self._connected_supplier = connected_supplier
        self._event_queue_factory = event_queue_factory
        self._event_queue_disposer = event_queue_disposer
        self._expect_timeout_ms = max(expect_timeout_ms, 1)
        self._rx_event_queue: Queue[SerialEvent] | None = None
        self._rx_buffer = ""
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._resume_event = Event()
        self._state_lock = Lock()
        self._user_paused = False
        self._connection_paused = False
        self._stopping = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, steps: list[BatchStep]) -> None:
        self.stop(emit_message=False)
        self._stop_event = Event()
        self._resume_event = Event()
        with self._state_lock:
            self._user_paused = False
            self._connection_paused = not self._connected_supplier()
            self._stopping = False
            self._refresh_resume_state_locked()
        self._thread = Thread(
            target=self._run_with_event_subscription,
            args=(self._run_steps, steps),
            daemon=True,
            name="batch-runner",
        )
        self._thread.start()

    def start_template(self, steps: list[BatchTemplateStep], resolve_line: BatchLineResolver) -> None:
        self.stop(emit_message=False)
        self._stop_event = Event()
        self._resume_event = Event()
        with self._state_lock:
            self._user_paused = False
            self._connection_paused = not self._connected_supplier()
            self._stopping = False
            self._refresh_resume_state_locked()
        self._thread = Thread(
            target=self._run_with_event_subscription,
            args=(self._run_template_steps, steps, resolve_line),
            daemon=True,
            name="batch-runner",
        )
        self._thread.start()

    def stop(self, emit_message: bool = True) -> None:
        thread = self._thread
        if thread and thread.is_alive():
            with self._state_lock:
                self._stopping = True
                self._stop_event.set()
                self._resume_event.set()
            thread.join(timeout=1.5)
            if emit_message:
                self._emit("status", "Batch run stopped.")
            if thread.is_alive():
                return
        self._thread = None
        with self._state_lock:
            self._stopping = False
            self._user_paused = False
            self._connection_paused = False
            self._refresh_resume_state_locked()

    def pause(self, reason: str = "user", emit_message: bool = True) -> bool:
        if not self.is_running:
            return False
        reason = "connection" if reason == "connection" else "user"
        with self._state_lock:
            was_paused = self._user_paused or self._connection_paused
            if reason == "connection":
                self._connection_paused = True
            else:
                self._user_paused = True
            self._refresh_resume_state_locked()
        if emit_message and not was_paused:
            self._emit("status", "Batch run paused.")
        return True

    def resume(self, emit_message: bool = True) -> bool:
        if not self.is_running:
            return False
        if not self._connected_supplier():
            with self._state_lock:
                self._connection_paused = True
                self._refresh_resume_state_locked()
            if emit_message:
                self._emit("status", "Connect before resuming batch run.")
            return False
        with self._state_lock:
            was_paused = self._user_paused or self._connection_paused
            self._user_paused = False
            self._connection_paused = False
            self._refresh_resume_state_locked()
        if emit_message and was_paused:
            self._emit("status", "Batch run resumed.")
        return True

    def snapshot(self) -> BatchRunSnapshot:
        running = self.is_running
        with self._state_lock:
            paused = running and (self._user_paused or self._connection_paused)
            reason = self._pause_reason_locked() if paused else ""
            can_resume = paused and self._connected_supplier() and not self._stopping
            return BatchRunSnapshot(
                is_running=running,
                is_paused=paused,
                is_stopping=running and self._stopping,
                pause_reason=reason,
                can_resume=can_resume,
            )

    def notify_connection_state(self, connected: bool) -> None:
        if not self.is_running:
            return
        if connected:
            with self._state_lock:
                was_connection_paused = self._connection_paused
                self._refresh_resume_state_locked()
            if was_connection_paused:
                self._emit("status", "Connection restored. Batch run waiting for Resume.")
            return
        with self._state_lock:
            was_paused = self._user_paused or self._connection_paused
            self._connection_paused = True
            self._refresh_resume_state_locked()
        if not was_paused:
            self._emit("status", "Connection lost. Batch run paused.")

    def _refresh_resume_state_locked(self) -> None:
        if self._stop_event.is_set():
            self._resume_event.set()
            return
        if self._user_paused or self._connection_paused:
            self._resume_event.clear()
            return
        self._resume_event.set()

    def _pause_reason_locked(self) -> str:
        if self._user_paused and self._connection_paused:
            return "user+connection"
        if self._connection_paused:
            return "connection"
        if self._user_paused:
            return "user"
        return ""

    def _run_with_event_subscription(self, target, *args) -> None:
        self._rx_buffer = ""
        if self._event_queue_factory is not None:
            self._rx_event_queue = self._event_queue_factory()
        try:
            target(*args)
        finally:
            queue = self._rx_event_queue
            self._rx_event_queue = None
            self._rx_buffer = ""
            if queue is not None and self._event_queue_disposer is not None:
                self._event_queue_disposer(queue)
            with self._state_lock:
                self._stopping = False
                self._user_paused = False
                self._connection_paused = False
                self._refresh_resume_state_locked()

    def _run_steps(self, steps: list[BatchStep]) -> None:
        self._emit("status", f"Batch run started with {len(steps)} step(s).")
        if not steps:
            self._emit("status", "Batch file had no runnable commands.")
            return
        completed = True
        for step in steps:
            if self._stop_event.is_set():
                completed = False
                break
            if not self._run_step(step):
                completed = False
                break
        if completed:
            self._emit("status", "Batch run completed.")

    def _run_template_steps(self, steps: list[BatchTemplateStep], resolve_line: BatchLineResolver) -> None:
        self._emit("status", f"Batch run started with {len(steps)} step(s).")
        if not steps:
            self._emit("status", "Batch file had no runnable commands.")
            return
        completed = True
        for template_step in steps:
            if self._stop_event.is_set():
                completed = False
                break
            try:
                resolved_line = resolve_line(template_step.line, template_step.line_number)
                if resolved_line is None:
                    self._emit("status", "Batch run cancelled.")
                    completed = False
                    break
                step = parse_batch_line(resolved_line, template_step.line_number)
            except BatchParseError as exc:
                self._emit("error", str(exc))
                completed = False
                break
            except Exception as exc:
                self._emit("error", f"Batch parameter on line {template_step.line_number} failed: {exc}")
                completed = False
                break
            if self._stop_event.is_set():
                completed = False
                break
            if not self._run_step(step):
                completed = False
                break
        if completed:
            self._emit("status", "Batch run completed.")

    def _run_step(self, step: BatchStep) -> bool:
        if step.kind == "wait":
            return self._sleep_interruptible(step.payload / 1000)
        if step.kind == "expect":
            if not self._wait_for_connection():
                return False
            return self._expect_text(str(step.payload), step.line_number)
        if not self._wait_for_connection():
            return False
        try:
            if step.kind == "send":
                self._reset_expectation_buffer()
                self._send_text(step.payload)
            elif step.kind == "hex":
                self._reset_expectation_buffer()
                self._send_bytes(step.payload)
        except Exception as exc:
            self._emit("error", f"Batch step on line {step.line_number} failed: {exc}")
            return False
        return True

    def _expect_text(self, expected: str, line_number: int) -> bool:
        if self._expected_text_available(expected):
            self._emit("status", f"EXPECT matched on line {line_number}: {expected}")
            return True
        queue = self._rx_event_queue
        if queue is None:
            self._emit("error", "EXPECT is not available because RX events are not connected to the batch runner.")
            return False
        remaining_timeout = self._expect_timeout_ms / 1000
        while not self._stop_event.is_set():
            if not self._wait_for_connection():
                return False
            if remaining_timeout <= 0:
                self._emit(
                    "error",
                    f"EXPECT timed out on line {line_number} after {self._expect_timeout_ms} ms: {expected}",
                )
                return False
            wait_time = min(remaining_timeout, 0.05)
            started_wait = perf_counter()
            try:
                event = queue.get(timeout=wait_time)
            except Empty:
                remaining_timeout -= perf_counter() - started_wait
                continue
            remaining_timeout -= perf_counter() - started_wait
            if event.kind == "rx":
                self._rx_buffer += event.message
                if self._expected_text_available(expected):
                    self._emit("status", f"EXPECT matched on line {line_number}: {expected}")
                    return True
        return False

    def _expected_text_available(self, expected: str) -> bool:
        index = self._rx_buffer.find(expected)
        if index < 0:
            return False
        self._rx_buffer = self._rx_buffer[index + len(expected):]
        return True

    def _reset_expectation_buffer(self) -> None:
        self._rx_buffer = ""
        queue = self._rx_event_queue
        if queue is None:
            return
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return

    def _wait_for_connection(self) -> bool:
        while not self._resume_event.is_set():
            if self._stop_event.wait(0.1):
                return False
        return not self._stop_event.is_set()

    def _sleep_interruptible(self, seconds: float) -> bool:
        if seconds <= 0:
            return not self._stop_event.is_set()
        remaining = seconds
        while remaining > 0:
            if not self._wait_for_connection():
                return False
            if remaining <= 0:
                return True
            if self._stop_event.is_set():
                return False
            if remaining <= HIGH_RES_WAIT_THRESHOLD_SECONDS:
                started_wait = perf_counter()
                slept = self._sleep_high_resolution(remaining)
                remaining -= perf_counter() - started_wait
                if not slept:
                    return False
                continue
            wait_time = min(remaining - HIGH_RES_WAIT_THRESHOLD_SECONDS, COARSE_WAIT_CHUNK_SECONDS)
            started_wait = perf_counter()
            if self._stop_event.wait(max(wait_time, 0)):
                return False
            remaining -= perf_counter() - started_wait
        return True

    def _sleep_high_resolution(self, seconds: float) -> bool:
        deadline = perf_counter() + seconds
        while True:
            if self._stop_event.is_set():
                return False
            if perf_counter() >= deadline:
                return True

    def _emit(self, kind: str, message: str) -> None:
        self._event_queue.put(SerialEvent(kind=kind, message=message))
