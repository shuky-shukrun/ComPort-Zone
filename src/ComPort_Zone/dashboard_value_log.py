"""Per-dashboard CSV value logger (FR-49/FR-50/FR-51).

A small, Qt-free sibling of :class:`ComPort_Zone.session_log.SessionLogger`
for the durable record of dashboard polls. Each successful parse — poll
or derived — appends one row; the file uses the same encoding the rest
of the app exports CSVs in (``utf-8-sig`` so Excel picks UTF-8) and is
flushed after every row so a crashed app still leaves a readable log.

The header is written only when the file is empty: re-opening an
existing log appends, which is the right behavior for unattended capture
across restarts (FR-49). Configuration (toggle + path) lives on the
dashboard itself (:class:`DashboardConfig.csv_log_enabled` /
``csv_log_path``) so it survives both restarts and dashboard reloads.

Threading: :meth:`log` takes a :class:`threading.Lock` so the tab can
safely call from inside ``_apply_outcome`` even when a future patch
moves derived recomputation off the GUI thread.

Qt-free by design (enforced via ``core/dashboard.py`` re-exports).
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import TextIO

# Columns in fixed order so consumers (Excel, pandas) can rely on the
# header — never reordered without bumping the schema. v3 adds ``kind``
# (poll/derived/control) so monitoring data and control actions land in
# one auditable file (FR-50/FR-76/FR-77). Pre-v3 logs that lack the
# column read back fine because csv.DictReader treats missing columns
# as missing keys.
VALUE_LOG_FIELDS = (
    "timestamp",
    "dashboard",
    "entry_id",
    "label",
    "kind",
    "value_text",
    "value_number",
    "state",
)

# Accepted ``kind`` values; passed by the tab on every log() call.
LOG_KIND_POLL = "poll"
LOG_KIND_DERIVED = "derived"
LOG_KIND_CONTROL = "control"
LOG_KINDS = (LOG_KIND_POLL, LOG_KIND_DERIVED, LOG_KIND_CONTROL)


def _format_value_number(value: float | None) -> str:
    """Number → compact text; ``None`` → empty (so text-only rows stay clean)."""
    if value is None:
        return ""
    return f"{value:.6g}"


class DashboardValueLogger:
    """Append-only CSV sink for one dashboard's poll/derived parses."""

    def __init__(self) -> None:
        self._handle: TextIO | None = None
        self._writer: csv.DictWriter | None = None
        self._path: Path | None = None
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._handle is not None

    @property
    def path(self) -> Path | None:
        return self._path

    def open(self, path: str | Path) -> None:
        """Open ``path`` for append, writing the header iff the file is
        new or empty (so the schema is preserved across restarts).

        Raises :class:`OSError` on I/O problems; the caller is expected to
        catch and surface them via :meth:`UI status reporting`.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.close()
        existed_with_content = target.exists() and target.stat().st_size > 0
        self._handle = target.open("a", encoding="utf-8-sig", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=list(VALUE_LOG_FIELDS))
        self._path = target
        if not existed_with_content:
            self._writer.writeheader()
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
            self._handle = None
            self._writer = None
            self._path = None

    def log(
        self,
        *,
        dashboard: str,
        entry_id: str,
        label: str,
        kind: str,
        value_text: str,
        value_number: float | None,
        state: str,
        timestamp: datetime | None = None,
    ) -> bool:
        """Append one row. Returns False when logging is disabled (so the
        caller's hot path stays free of conditionals). ``kind`` is one
        of ``LOG_KINDS``; values outside that set still write through
        but consumers should treat them as future-version markers."""
        if self._handle is None or self._writer is None:
            return False
        when = timestamp or datetime.now().astimezone()
        row = {
            "timestamp": when.isoformat(timespec="milliseconds"),
            "dashboard": dashboard,
            "entry_id": entry_id,
            "label": label,
            "kind": kind,
            "value_text": value_text,
            "value_number": _format_value_number(value_number),
            "state": state,
        }
        with self._lock:
            if self._writer is None or self._handle is None:
                return False
            self._writer.writerow(row)
            self._handle.flush()
        return True
