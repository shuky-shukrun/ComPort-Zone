"""Alert detection and history for control_panel tiles (FR-57/FR-58).

An alert fires on a state transition *into* ``fail`` or ``error`` from
any other state; the matching recovery transition is recorded silently
(history only, no attention). Timeouts and staleness never alert: a dead
device must not generate a notification storm — its first send error
still alerts once.

Qt-free by design (enforced via ``core/control_panel.py`` re-exports); the
tab owns the UI surfaces (badge, panel, sound, taskbar attention).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

ALERT_STATES = ("fail", "error")
ALERT_HISTORY_LIMIT = 200

ALERT_KIND = "alert"
RECOVERY_KIND = "recovery"


def detect_transition(prev_state: str, new_state: str) -> str:
    """Classify a state edge: "alert", "recovery", or "" (nothing).

    Re-entering the same alerting state does not re-fire; moving between
    the two alerting states (fail <-> error) does not re-fire either —
    the tile is already alerting.
    """
    prev_alerting = prev_state in ALERT_STATES
    new_alerting = new_state in ALERT_STATES
    if new_alerting and not prev_alerting:
        return ALERT_KIND
    if prev_alerting and not new_alerting:
        return RECOVERY_KIND
    return ""


@dataclass(slots=True)
class AlertRecord:
    timestamp: str  # wall-clock "HH:MM:SS"
    entry_id: str
    entry_label: str
    old_state: str
    new_state: str
    value_text: str
    kind: str  # ALERT_KIND | RECOVERY_KIND


class AlertLog:
    """Bounded per-control_panel alert history with an unseen counter."""

    __slots__ = ("_records", "_unseen")

    def __init__(self, *, limit: int = ALERT_HISTORY_LIMIT) -> None:
        self._records: deque[AlertRecord] = deque(maxlen=limit)
        self._unseen = 0

    def append(self, record: AlertRecord) -> None:
        self._records.append(record)
        if record.kind == ALERT_KIND:
            self._unseen += 1

    def records(self) -> list[AlertRecord]:
        """Newest first (panel display order)."""
        return list(reversed(self._records))

    @property
    def unseen_count(self) -> int:
        return self._unseen

    def mark_seen(self) -> None:
        self._unseen = 0

    def clear(self) -> None:
        self._records.clear()
        self._unseen = 0

    def __len__(self) -> int:
        return len(self._records)
