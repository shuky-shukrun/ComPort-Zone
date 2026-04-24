from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from .serial_core import SerialEvent


class SessionLogger:
    def __init__(self) -> None:
        self._handle = None
        self._path: Path | None = None
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._handle is not None

    @property
    def path(self) -> Path | None:
        return self._path

    def open(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.close()
        self._handle = target.open("a", encoding="utf-8")
        self._path = target

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._handle.close()
            self._handle = None
            self._path = None

    def log_event(self, event: SerialEvent) -> None:
        if not self._handle:
            return
        timestamp = event.timestamp.astimezone().isoformat(timespec="milliseconds")
        lines = event.message.splitlines() or [event.message]
        with self._lock:
            for line in lines:
                self._handle.write(f"{timestamp} {event.kind.upper():<10} {line}\n")
            self._handle.flush()
