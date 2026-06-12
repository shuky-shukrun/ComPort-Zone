"""Dashboard tile widgets: shared chrome + value and LED variants.

Tiles are dumb renderers: the dashboard tab owns all polling state and
pushes :class:`TileRuntime` snapshots into ``update_runtime``; tiles only
repaint what actually changed (coalescing, NFR-1). All colors come from
the global QSS via the ``tileState`` dynamic property — the
state-to-palette mapping lives in :func:`tile_state_color`, shared by the
stylesheet and tests (NFR-6).

Requirements: docs/dashboard-view-requirements.md (FR-22, FR-31, FR-34,
FR-36).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..dashboard_history import Sample
from ..dashboard_models import MAX_TILE_SPAN, DashboardEntry
from ..themes import ThemePalette
from .dashboard_sparkline import SparklineWidget
from .tokens import LED_LAMP, SPACE_LG, SPACE_MD, SPACE_SM

DASHBOARD_TILE_MIME_TYPE = "application/x-comport-zone-dashboard-tile"

# Default state captions for LED tiles; a matching ColorRule ``label``
# overrides these (FR-29).
TILE_STATE_CAPTIONS = {
    "ok": "OK",
    "warn": "WARN",
    "fail": "FAIL",
    "neutral": "—",
    "stale": "STALE",
    "error": "ERROR",
}

SPAN_CHOICES = ((1, 1), (2, 1), (1, 2), (2, 2))


def tile_state_color(state: str, theme: ThemePalette) -> str:
    """Single source of the semantic state → theme color mapping."""
    if state == "ok":
        return theme.tx
    if state == "warn":
        return theme.status
    if state in ("fail", "error"):
        return theme.error
    return theme.muted


@dataclass(slots=True)
class TileRuntime:
    """GUI-side cache of one entry's latest poll outcome (never persisted)."""

    entry_id: str
    value_text: str = "—"
    state: str = "neutral"
    state_caption: str = ""
    color: str = ""  # custom rule color (FR-62); "" = theme state color
    timestamp_text: str = ""
    tooltip: str = ""
    last_success_at: float = 0.0
    last_result_at: float = 0.0
    consecutive_timeouts: int = 0


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _set_state_property(widget: QWidget, state: str) -> None:
    if widget.property("tileState") == state:
        return
    widget.setProperty("tileState", state)
    _repolish(widget)


def _apply_custom_style(widget: QWidget, template: str, color: str) -> bool:
    """Scoped inline override for a custom rule color (FR-62): set when a
    color is active, cleared back to the QSS cascade when not. Returns
    True when the stylesheet actually changed."""
    sheet = template.format(color=color) if color else ""
    if widget.styleSheet() == sheet:
        return False
    widget.setStyleSheet(sheet)
    return True


class TileFrame(QFrame):
    """Shared tile chrome: header, footer, context menu, edit-mode drag."""

    editRequested = Signal(str)
    removeRequested = Signal(str)
    enableToggled = Signal(str, bool)
    spanRequested = Signal(str, int, int)
    pollNowRequested = Signal(str)
    activateRequested = Signal(str)  # emitted by control tiles only (FR-59)

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        """Override on tile kinds that paint their own surfaces (sparkline)."""
        # Default tile chrome takes its colors from QSS via tileState; no
        # per-instance palette needed unless a subclass paints raw pixels.

    def __init__(self, entry: DashboardEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardTile")
        self.entry_id = entry.id
        self._entry = entry
        self._edit_mode = False
        self._press_pos: QPoint | None = None
        self._runtime: TileRuntime | None = None

        self.title_label = QLabel(entry.display_label())
        self.title_label.setObjectName("tileTitle")
        self.timestamp_label = QLabel("")
        self.timestamp_label.setObjectName("tileTimestamp")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(SPACE_SM)
        header.addWidget(self.title_label, 1)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(SPACE_SM)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.timestamp_label, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        root.setSpacing(SPACE_SM)
        root.addLayout(header)
        root.addLayout(self.body_layout, 1)
        root.addLayout(footer)

        _set_state_property(self, "neutral")
        self._apply_enabled_property()

    # ------------------------------------------------------------- updates

    def update_entry(self, entry: DashboardEntry) -> None:
        """Adopt edited entry settings (label, enabled, spans)."""
        self._entry = entry
        self.title_label.setText(entry.display_label())
        self._apply_enabled_property()

    def update_runtime(self, runtime: TileRuntime) -> bool:
        """Render the latest poll snapshot; returns True when anything
        visible changed (used to coalesce repaints)."""
        changed = self._render_runtime(runtime)
        if self.timestamp_label.text() != runtime.timestamp_text:
            self.timestamp_label.setText(runtime.timestamp_text)
            changed = True
        if self.toolTip() != runtime.tooltip:
            self.setToolTip(runtime.tooltip)
        if self.property("tileState") != runtime.state:
            _set_state_property(self, runtime.state)
            changed = True
        self._runtime = runtime
        return changed

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        raise NotImplementedError

    def _apply_enabled_property(self) -> None:
        value = "true" if self._entry.enabled else "false"
        if self.property("entryEnabled") != value:
            self.setProperty("entryEnabled", value)
            _repolish(self)

    # ----------------------------------------------------------- edit mode

    def set_edit_mode(self, enabled: bool) -> None:
        self._edit_mode = enabled
        value = "true" if enabled else "false"
        if self.property("editMode") != value:
            self.setProperty("editMode", value)
            _repolish(self)
        self.setCursor(Qt.CursorShape.OpenHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            not self._edit_mode
            or self._press_pos is None
            or not (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._press_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            return
        self._press_pos = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(DASHBOARD_TILE_MIME_TYPE, self.entry_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.DropAction.MoveAction)

    # -------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        menu = QMenu(self)
        if self._entry.is_polled():
            poll_now_action = menu.addAction("Poll Now")
            poll_now_action.setEnabled(self._entry.enabled)
            poll_now_action.triggered.connect(
                lambda: self.pollNowRequested.emit(self.entry_id)
            )
            menu.addSeparator()
        edit_action = menu.addAction("Edit Entry…")
        edit_action.triggered.connect(lambda: self.editRequested.emit(self.entry_id))
        enabled_action = menu.addAction("Enabled")
        enabled_action.setCheckable(True)
        enabled_action.setChecked(self._entry.enabled)
        enabled_action.toggled.connect(
            lambda checked: self.enableToggled.emit(self.entry_id, checked)
        )
        size_menu = menu.addMenu("Size")
        tile = self._entry.tile
        for span_w, span_h in SPAN_CHOICES:
            if span_w > MAX_TILE_SPAN or span_h > MAX_TILE_SPAN:
                continue
            action = size_menu.addAction(f"{span_w}×{span_h}")
            action.setCheckable(True)
            action.setChecked((tile.span_w, tile.span_h) == (span_w, span_h))
            action.triggered.connect(
                lambda _checked=False, w=span_w, h=span_h: self.spanRequested.emit(
                    self.entry_id, w, h
                )
            )
        menu.addSeparator()
        remove_action = menu.addAction("Remove Tile")
        remove_action.triggered.connect(lambda: self.removeRequested.emit(self.entry_id))
        menu.exec(event.globalPos())
        menu.deleteLater()


class ValueTileWidget(TileFrame):
    """Label + latest parsed value (+unit) + timestamp + sparkline (FR-31,
    FR-46/FR-47). The sparkline appears only when the entry produces
    numeric values and the user keeps it on; the tab calls
    :meth:`set_history` on every successful poll/derived update."""

    def __init__(self, entry: DashboardEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("tileValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setWordWrap(True)
        self.sparkline = SparklineWidget(self)
        self.body_layout.addWidget(self.value_label, 1)
        self.body_layout.addWidget(self.sparkline)
        self._sparkline_visible = self._wants_sparkline(entry)
        self.sparkline.setVisible(self._sparkline_visible)

    @staticmethod
    def _wants_sparkline(entry: DashboardEntry) -> bool:
        return entry.show_sparkline and entry.is_numeric()

    def update_entry(self, entry: DashboardEntry) -> None:
        super().update_entry(entry)
        wanted = self._wants_sparkline(entry)
        if wanted != self._sparkline_visible:
            self._sparkline_visible = wanted
            self.sparkline.setVisible(wanted)

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self.sparkline.apply_theme_palette(theme)

    def set_history(self, samples: list[Sample], color: str, *, now: float) -> bool:
        """Feed the sparkline; ignored when hidden (the data stays in the
        tab's history ring, so re-enabling repaints immediately)."""
        if not self._sparkline_visible:
            return False
        return self.sparkline.set_samples(samples, color, now=now)

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        changed = False
        if self.value_label.text() != runtime.value_text:
            self.value_label.setText(runtime.value_text)
            changed = True
        if self.value_label.property("tileState") != runtime.state:
            _set_state_property(self.value_label, runtime.state)
            changed = True
        if _apply_custom_style(self.value_label, "color: {color};", runtime.color):
            changed = True
        return changed


class LedTileWidget(TileFrame):
    """Large state lamp + state caption (FR-31)."""

    def __init__(self, entry: DashboardEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self.lamp = QLabel("")
        self.lamp.setObjectName("tileLamp")
        self.lamp.setFixedSize(LED_LAMP, LED_LAMP)
        self.caption_label = QLabel(TILE_STATE_CAPTIONS["neutral"])
        self.caption_label.setObjectName("tileStateCaption")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_LG)
        row.addStretch(1)
        row.addWidget(self.lamp)
        row.addWidget(self.caption_label)
        row.addStretch(1)
        self.body_layout.addStretch(1)
        self.body_layout.addLayout(row)
        self.body_layout.addStretch(1)

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        changed = False
        caption = runtime.state_caption or TILE_STATE_CAPTIONS.get(runtime.state, "—")
        if self.caption_label.text() != caption:
            self.caption_label.setText(caption)
            changed = True
        if self.lamp.property("tileState") != runtime.state:
            _set_state_property(self.lamp, runtime.state)
            changed = True
        if self.caption_label.property("tileState") != runtime.state:
            _set_state_property(self.caption_label, runtime.state)
            changed = True
        if _apply_custom_style(
            self.lamp, "background: {color}; border-color: {color};", runtime.color
        ):
            changed = True
        if _apply_custom_style(self.caption_label, "color: {color};", runtime.color):
            changed = True
        return changed


class ControlTileWidget(TileFrame):
    """One big action button that sends on click (FR-59/FR-60).

    Never polled, staled, or alerted: the tab gates and submits the send;
    this widget only renders pending/ON-OFF state. For toggles the visual
    follows the watch entry's verdict when one is set ("ok" renders ON),
    otherwise it flips optimistically on a successful send.
    """

    def __init__(self, entry: DashboardEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._is_on = False
        self._pending = False
        self.button = QPushButton("", self)
        self.button.setObjectName("tileControlButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: self.activateRequested.emit(self.entry_id))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.button, 2)
        row.addStretch(1)
        self.body_layout.addStretch(1)
        self.body_layout.addLayout(row)
        self.body_layout.addStretch(1)
        self._refresh_button()

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        return False  # state border/tooltip/timestamp come from TileFrame

    def update_entry(self, entry: DashboardEntry) -> None:
        super().update_entry(entry)
        self._refresh_button()

    @property
    def is_on(self) -> bool:
        return self._is_on

    def set_on(self, is_on: bool) -> None:
        if self._is_on != is_on:
            self._is_on = is_on
            self._refresh_button()

    @property
    def pending(self) -> bool:
        return self._pending

    def set_pending(self, pending: bool) -> None:
        if self._pending != pending:
            self._pending = pending
            self._refresh_button()

    def set_edit_mode(self, enabled: bool) -> None:
        super().set_edit_mode(enabled)
        # The button must not swallow press events while tiles are dragged.
        self.button.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self._refresh_button()

    def _refresh_button(self) -> None:
        control = self._entry.control
        if self._pending:
            text = "…"
        elif control.mode == "toggle":
            text = "ON" if self._is_on else "OFF"
        else:
            text = "Send"
        if self.button.text() != text:
            self.button.setText(text)
        self.button.setEnabled(self._entry.enabled and not self._pending and not self.edit_mode)
        state = "on" if control.mode == "toggle" and self._is_on else "off"
        if self.button.property("controlState") != state:
            self.button.setProperty("controlState", state)
            _repolish(self.button)


TILE_CLASSES: dict[str, type[TileFrame]] = {
    "value": ValueTileWidget,
    "led": LedTileWidget,
    "control": ControlTileWidget,
}


def tile_class_for(entry: DashboardEntry) -> type[TileFrame]:
    return TILE_CLASSES.get(entry.tile.kind, ValueTileWidget)


def create_tile(entry: DashboardEntry, parent: QWidget | None = None) -> TileFrame:
    """Factory keyed on the entry's tile kind."""
    return tile_class_for(entry)(entry, parent)
