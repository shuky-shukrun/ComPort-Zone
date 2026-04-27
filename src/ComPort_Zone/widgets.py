from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QLineEdit


class HistoryLineEdit(QLineEdit):
    historyRequested = Signal(int)
    autocompleteRequested = Signal()
    deleteHistoryRequested = Signal()

    def keyPressEvent(self, event) -> None:
        popup = self.completer().popup() if self.completer() else None
        popup_visible = bool(popup and popup.isVisible())
        if (
            event.key() == Qt.Key.Key_Delete
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.deleteHistoryRequested.emit()
            return
        if event.key() == Qt.Key.Key_Up and not popup_visible:
            self.historyRequested.emit(-1)
            return
        if event.key() == Qt.Key.Key_Down and not popup_visible:
            self.historyRequested.emit(1)
            return
        if (
            event.key() == Qt.Key.Key_Space
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.autocompleteRequested.emit()
            return
        super().keyPressEvent(event)


class ChevronComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(self.foregroundRole())
        if not self.isEnabled():
            color = color.darker(130)
        pen = QPen(QColor(color), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = self.width() - 18
        center_y = int(self.height() / 2)
        painter.drawLine(center_x - 4, center_y - 2, center_x, center_y + 2)
        painter.drawLine(center_x, center_y + 2, center_x + 4, center_y - 2)
        painter.end()
