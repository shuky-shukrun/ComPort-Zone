"""Floating alert history popup for one dashboard (FR-58).

Anchored top-right against the dashboard tab and shown when the user
clicks the bell button in the header. Lists the most recent alert /
recovery transitions newest first (already-reversed by ``AlertLog``);
opening the panel calls :meth:`AlertLog.mark_seen` so the unseen-count
badge resets. Clear discards the whole history.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..dashboard_alerts import ALERT_KIND, AlertLog, AlertRecord
from ..icons import set_button_icon


class AlertHistoryPanel(QFrame):
    """Lightweight floating list of one dashboard's alert events."""

    clearRequested = Signal()
    closeRequested = Signal()

    def __init__(self, anchor: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent or anchor.parentWidget() or anchor)
        self.setObjectName("dashboardAlertPanel")
        self._anchor = anchor
        self._margin = 10
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        self.title_label = QLabel("Alerts", self)
        self.title_label.setObjectName("dashboardAlertPanelTitle")
        self.subtitle_label = QLabel("", self)
        self.subtitle_label.setObjectName("dashboardAlertPanelSubtitle")
        self.clear_button = QToolButton(self)
        self.clear_button.setObjectName("dashboardAlertPanelButton")
        self.clear_button.setText("Clear")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self.clearRequested)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("dashboardAlertPanelButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_icon(self.close_button, "x", 12)
        self.close_button.clicked.connect(self._close)
        header_row.addWidget(self.title_label)
        header_row.addWidget(self.subtitle_label, 1)
        header_row.addWidget(self.clear_button)
        header_row.addWidget(self.close_button)
        outer.addLayout(header_row)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("dashboardAlertList")
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer.addWidget(self.list_widget, 1)

        self.setMinimumWidth(360)
        self.setMaximumWidth(520)
        self.setMinimumHeight(180)
        self.setMaximumHeight(360)
        anchor.installEventFilter(self)
        self.hide()

    # ------------------------------------------------------------------ API

    def set_records(self, records: list[AlertRecord]) -> None:
        """Replace the visible list. Records arrive newest-first."""
        self.list_widget.clear()
        if not records:
            placeholder = QListWidgetItem("No alerts yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
        else:
            for record in records:
                self.list_widget.addItem(self._make_item(record))
        alert_count = sum(1 for record in records if record.kind == ALERT_KIND)
        self.subtitle_label.setText(
            f"{alert_count} alert(s), {len(records) - alert_count} recovery(ies)"
        )

    def _make_item(self, record: AlertRecord) -> QListWidgetItem:
        # Color the row by kind via a dynamic property — QSS draws.
        text = (
            f"{record.timestamp}  {record.entry_label}  "
            f"{record.old_state.upper()} -> {record.new_state.upper()}"
        )
        if record.value_text:
            text += f"  ({record.value_text})"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, record.kind)
        return item

    def open_with(self, log: AlertLog) -> None:
        log.mark_seen()
        self.set_records(log.records())
        self.show()
        self.reposition()
        self.raise_()

    def reposition(self) -> None:
        if self._anchor is None:
            return
        self.adjustSize()
        geo = self._anchor.geometry()  # parent-relative
        x = geo.right() - self.width() - self._margin
        y = geo.top() + self._margin
        self.move(max(geo.left() + self._margin, x), y)

    def _close(self) -> None:
        self.hide()
        self.closeRequested.emit()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt naming)
        if watched is self._anchor and self.isVisible():
            if event.type() in (
                QEvent.Type.Resize,
                QEvent.Type.Move,
                QEvent.Type.Show,
            ):
                self.reposition()
        return False
