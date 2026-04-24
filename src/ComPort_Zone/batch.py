from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from time import monotonic, sleep

from .serial_core import SerialEvent

WAIT_PATTERN = re.compile(r"^WAIT\s+(\d+)$", re.IGNORECASE)
SEND_PATTERN = re.compile(r"^SEND\s+(.+)$", re.IGNORECASE)
HEX_PATTERN = re.compile(r"^HEX\s+([0-9A-Fa-f\s]+)$", re.IGNORECASE)


class BatchParseError(ValueError):
    def __init__(self, message: str, line_number: int) -> None:
        super().__init__(f"Line {line_number}: {message}")
        self.line_number = line_number


@dataclass(slots=True)
class BatchStep:
    kind: str
    payload: str | bytes | int
    line_number: int


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


def parse_batch_script(text: str) -> list[BatchStep]:
    steps: list[BatchStep] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        wait_match = WAIT_PATTERN.match(stripped)
        if wait_match:
            steps.append(BatchStep("wait", int(wait_match.group(1)), line_number))
            continue
        send_match = SEND_PATTERN.match(stripped)
        if send_match:
            steps.append(BatchStep("send", send_match.group(1), line_number))
            continue
        hex_match = HEX_PATTERN.match(stripped)
        if hex_match:
            try:
                payload = parse_hex_payload(hex_match.group(1))
            except ValueError as exc:
                raise BatchParseError(str(exc), line_number) from exc
            steps.append(BatchStep("hex", payload, line_number))
            continue
        steps.append(BatchStep("send", stripped, line_number))
    return steps


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
    ) -> None:
        self._event_queue = event_queue
        self._send_text = send_text
        self._send_bytes = send_bytes
        self._connected_supplier = connected_supplier
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._resume_event = Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, steps: list[BatchStep]) -> None:
        self.stop(emit_message=False)
        self._stop_event = Event()
        self._resume_event = Event()
        if self._connected_supplier():
            self._resume_event.set()
        self._thread = Thread(target=self._run_steps, args=(steps,), daemon=True, name="batch-runner")
        self._thread.start()

    def stop(self, emit_message: bool = True) -> None:
        thread = self._thread
        if thread and thread.is_alive():
            self._stop_event.set()
            self._resume_event.set()
            thread.join(timeout=1.5)
            if emit_message:
                self._emit("status", "Batch run stopped.")
        self._thread = None

    def notify_connection_state(self, connected: bool) -> None:
        if not self.is_running:
            return
        if connected:
            if not self._resume_event.is_set():
                self._emit("status", "Connection restored. Resuming batch run.")
            self._resume_event.set()
        else:
            if self._resume_event.is_set():
                self._emit("status", "Connection lost. Batch run paused.")
            self._resume_event.clear()

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
            if step.kind == "wait":
                if not self._sleep_interruptible(step.payload / 1000):
                    completed = False
                    break
                continue
            if not self._wait_for_connection():
                completed = False
                break
            try:
                if step.kind == "send":
                    self._send_text(step.payload)
                elif step.kind == "hex":
                    self._send_bytes(step.payload)
            except Exception as exc:
                self._emit("error", f"Batch step on line {step.line_number} failed: {exc}")
                completed = False
                break
        if completed:
            self._emit("status", "Batch run completed.")

    def _wait_for_connection(self) -> bool:
        while not self._resume_event.is_set():
            if self._stop_event.wait(0.1):
                return False
        return not self._stop_event.is_set()

    def _sleep_interruptible(self, seconds: float) -> bool:
        deadline = monotonic() + seconds
        while monotonic() < deadline:
            if self._stop_event.wait(0.05):
                return False
            sleep(0.01)
        return True

    def _emit(self, kind: str, message: str) -> None:
        self._event_queue.put(SerialEvent(kind=kind, message=message))
