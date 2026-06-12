"""Cross-platform "ding" for dashboard alerts (FR-58).

Loads ``assets/alert.wav`` through :class:`QSoundEffect` if QtMultimedia
is available in the wheel (it is, on the desktop builds we ship), falls
back to :meth:`QApplication.beep` otherwise. Debounced at 2 s so a
chatter of fail/error transitions can't machine-gun the user.

The interface is intentionally tiny and injectable so the tab can pass a
stub in unit tests — no QSoundEffect ever needs to be constructed under
``-m unittest``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QApplication

ALERT_DEBOUNCE_S = 2.0
ALERT_WAV_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "alert.wav"
)


class AlertSounder(Protocol):
    """Anything the tab can call ``play()`` on (kept thin for testing)."""

    def play(self) -> None:
        ...


class _BeepFallback:
    """Used when QtMultimedia is missing or the WAV cannot load.

    Not silent — the user still hears *something* — and not a crash."""

    def play(self) -> None:
        QApplication.beep()


class QtAlertSounder:
    """Default sounder: lazy QSoundEffect over the bundled WAV.

    Construction is lazy because importing QtMultimedia pays a one-off
    cost — most sessions never hit an alert. A failed import (or a
    missing WAV after a broken packaging run) downgrades to the OS beep.
    """

    def __init__(
        self,
        *,
        wav_path: Path | None = None,
        clock=time.monotonic,
        debounce_s: float = ALERT_DEBOUNCE_S,
    ) -> None:
        self._wav_path = wav_path or ALERT_WAV_PATH
        self._clock = clock
        self._debounce_s = float(debounce_s)
        self._effect = None
        self._fallback: AlertSounder | None = None
        self._last_played: float = -1e9
        self._initialized = False

    def play(self) -> None:
        now = self._clock()
        if now - self._last_played < self._debounce_s:
            return
        self._last_played = now
        if not self._initialized:
            self._initialize()
        if self._effect is not None:
            self._effect.play()
        elif self._fallback is not None:
            self._fallback.play()

    def _initialize(self) -> None:
        self._initialized = True
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError:
            self._fallback = _BeepFallback()
            return
        if not self._wav_path.exists():
            self._fallback = _BeepFallback()
            return
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(str(self._wav_path)))
        effect.setVolume(0.7)
        self._effect = effect
