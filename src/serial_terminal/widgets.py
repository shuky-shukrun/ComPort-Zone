from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit


class HistoryLineEdit(QLineEdit):
    historyRequested = Signal(int)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Up:
            self.historyRequested.emit(-1)
            return
        if event.key() == Qt.Key.Key_Down:
            self.historyRequested.emit(1)
            return
        super().keyPressEvent(event)
