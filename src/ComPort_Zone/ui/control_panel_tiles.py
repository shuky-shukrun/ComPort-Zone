"""ControlPanel tile widgets: shared chrome + value and LED variants.

Tiles are dumb renderers: the control_panel tab owns all polling state and
pushes :class:`TileRuntime` snapshots into ``update_runtime``; tiles only
repaint what actually changed (coalescing, NFR-1). All colors come from
the global QSS via the ``tileState`` dynamic property — the
state-to-palette mapping lives in :func:`tile_state_color`, shared by the
stylesheet and tests (NFR-6).

Requirements: docs/control_panel-view-requirements.md (FR-22, FR-31, FR-34,
FR-36).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QMouseEvent, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..control_panel_history import Sample
from ..control_panel_models import (
    MAX_TILE_SPAN,
    BitDefinition,
    BitsSpec,
    ControlPanelEntry,
    format_setpoint_value,
)
from ..themes import ThemePalette
from .control_panel_sparkline import SparklineWidget
from .tokens import LED_LAMP, SPACE_LG, SPACE_MD, SPACE_SM

CONTROL_PANEL_TILE_MIME_TYPE = "application/x-comport-zone-control_panel-tile"

# Press-and-hold this long on a tile's chrome to flip the panel into
# layout-edit mode without hunting for the toolbar button.
LONG_PRESS_MS = 1000

# Size of the bottom-right resize grip (px) used in edit mode.
RESIZE_CORNER_PX = 18

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

SPAN_CHOICES = tuple(
    (w, h) for h in range(1, 6) for w in range(1, 6)
)  # 1×1 through 5×5

# Responsive font sizing: the measure (tileValue) and the LED caption
# (tileStateCaption) scale with the grid's per-cell width so the panel
# stays readable on split-screen / narrow layouts as well as fullscreen.
# Ratios are tuned so the legacy default cell width (~180px) reproduces
# the previous fixed sizes (21px / 15px).
VALUE_FONT_RATIO = 0.12
VALUE_FONT_MIN_PX = 12
VALUE_FONT_MAX_PX = 40

LED_CAPTION_FONT_RATIO = 0.085
LED_CAPTION_FONT_MIN_PX = 11
LED_CAPTION_FONT_MAX_PX = 24


def _scale_font_px(cell_w: float, ratio: float, lo: int, hi: int) -> int:
    """Map a cell width to a bounded font pixel size."""
    if cell_w <= 0:
        return lo
    return max(lo, min(hi, round(cell_w * ratio)))


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
    # Numeric component of the latest parse, when ``value_type=number``.
    # Carried alongside ``value_text`` so widgets that need the raw int
    # (bits/register tiles) don't have to re-parse the formatted string.
    value_number: float | None = None
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
    duplicateRequested = Signal(str)
    removeRequested = Signal(str)
    enableToggled = Signal(str, bool)
    spanRequested = Signal(str, int, int)
    pollNowRequested = Signal(str)
    activateRequested = Signal(str)  # emitted by control tiles only (FR-59)
    chartRequested = Signal(str)  # emitted by value tiles only (FR-48)
    editModeRequested = Signal()  # long-press on the tile chrome (FR: edit UX)

    def set_panel_armed(self, armed: bool) -> None:
        """Default: tiles are unaffected by master arm. Writing-tile
        subclasses override to render their disarmed visuals (FR-73)."""

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        """Override on tile kinds that paint their own surfaces (sparkline)."""
        # Default tile chrome takes its colors from QSS via tileState; no
        # per-instance palette needed unless a subclass paints raw pixels.

    def apply_cell_width(self, cell_w: float) -> None:
        """Hook for responsive font sizing — subclasses that own measure
        labels override to scale them with the grid's cell width."""

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("controlPanelTile")
        self.entry_id = entry.id
        self._entry = entry
        self._edit_mode = False
        self._press_pos: QPoint | None = None
        self._runtime: TileRuntime | None = None
        # Long-press-to-edit: a hold on the tile chrome (not over an
        # interactive child) enters edit mode after LONG_PRESS_MS.
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)
        # Corner-drag resize (edit mode). The grid injects a provider that
        # returns the per-cell stride so pixel drags map to whole spans.
        self.cell_metrics_provider: Callable[[], tuple[float, float, int]] | None = None
        self._resizing = False
        self._resize_start_global: QPoint | None = None
        self._resize_start_span: tuple[int, int] = (1, 1)
        self._resize_last_span: tuple[int, int] = (1, 1)

        self.title_label = QLabel(entry.display_label())
        self.title_label.setObjectName("tileTitle")
        # Long labels wrap to a second line instead of being clipped.
        self.title_label.setWordWrap(True)
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

    def update_entry(self, entry: ControlPanelEntry) -> None:
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
        # Mouse tracking so the corner shows a resize cursor on hover.
        self.setMouseTracking(enabled)
        self.setCursor(Qt.CursorShape.OpenHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        if not enabled:
            self._resizing = False
        self.update()  # paint / clear the resize grip

    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    def _in_resize_corner(self, pos: QPoint) -> bool:
        return (
            pos.x() >= self.width() - RESIZE_CORNER_PX
            and pos.y() >= self.height() - RESIZE_CORNER_PX
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._edit_mode and self._in_resize_corner(event.position().toPoint()):
                self._begin_resize(event)
                event.accept()
                return
            self._press_pos = event.position().toPoint()
            # Arm long-press-to-edit only when not already editing.
            if not self._edit_mode:
                self._long_press_timer.start(LONG_PRESS_MS)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._long_press_timer.stop()
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resizing:
            self._update_resize(event)
            event.accept()
            return
        # Hover feedback: resize cursor over the corner in edit mode.
        if self._edit_mode and not (event.buttons() & Qt.MouseButton.LeftButton):
            corner = self._in_resize_corner(event.position().toPoint())
            self.setCursor(
                Qt.CursorShape.SizeFDiagCursor if corner else Qt.CursorShape.OpenHandCursor
            )
        # Any real movement means this is a drag/scroll, not a hold —
        # cancel the pending long-press.
        if self._long_press_timer.isActive() and self._press_pos is not None:
            moved = (event.position().toPoint() - self._press_pos).manhattanLength()
            if moved >= QApplication.startDragDistance():
                self._long_press_timer.stop()
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
        mime.setData(CONTROL_PANEL_TILE_MIME_TYPE, self.entry_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.DropAction.MoveAction)

    def _begin_resize(self, event: QMouseEvent) -> None:
        self._long_press_timer.stop()
        self._press_pos = None
        self._resizing = True
        self._resize_start_global = event.globalPosition().toPoint()
        span = (self._entry.tile.span_w, self._entry.tile.span_h)
        self._resize_start_span = span
        self._resize_last_span = span

    def _update_resize(self, event: QMouseEvent) -> None:
        provider = self.cell_metrics_provider
        if provider is None or self._resize_start_global is None:
            return
        stride_x, stride_y, columns = provider()
        if stride_x <= 0 or stride_y <= 0:
            return
        delta = event.globalPosition().toPoint() - self._resize_start_global
        start_w, start_h = self._resize_start_span
        # Round so the span flips at the half-cell crossing — feels natural.
        new_w = start_w + round(delta.x() / stride_x)
        new_h = start_h + round(delta.y() / stride_y)
        new_w = max(1, min(MAX_TILE_SPAN, int(columns), new_w))
        new_h = max(1, min(MAX_TILE_SPAN, new_h))
        if (new_w, new_h) != self._resize_last_span:
            self._resize_last_span = (new_w, new_h)
            self.spanRequested.emit(self.entry_id, new_w, new_h)

    def _on_long_press(self) -> None:
        if not self._edit_mode:
            self.editModeRequested.emit()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().paintEvent(event)
        if not self._edit_mode:
            return
        painter = QPainter(self)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        color.setAlpha(110)
        pen = QPen(color)
        pen.setWidth(2)
        painter.setPen(pen)
        w, h, m = self.width(), self.height(), 4
        for off in (4, 9, 14):
            painter.drawLine(w - m - off, h - m, w - m, h - m - off)
        painter.end()

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
        if self._entry.is_numeric() and self._entry.tile.kind != "control":
            chart_action = menu.addAction("Open Chart…")
            chart_action.triggered.connect(
                lambda: self.chartRequested.emit(self.entry_id)
            )
            menu.addSeparator()
        edit_action = menu.addAction("Edit Entry…")
        edit_action.triggered.connect(lambda: self.editRequested.emit(self.entry_id))
        duplicate_action = menu.addAction("Duplicate Entry…")
        duplicate_action.triggered.connect(
            lambda: self.duplicateRequested.emit(self.entry_id)
        )
        enabled_action = menu.addAction("Enabled")
        enabled_action.setCheckable(True)
        enabled_action.setChecked(self._entry.enabled)
        enabled_action.toggled.connect(
            lambda checked: self.enableToggled.emit(self.entry_id, checked)
        )
        size_menu = menu.addMenu("Size")
        tile = self._entry.tile
        last_h: int | None = None
        for span_w, span_h in SPAN_CHOICES:
            if span_w > MAX_TILE_SPAN or span_h > MAX_TILE_SPAN:
                continue
            # SPAN_CHOICES is grouped by height — a separator between
            # groups breaks the 25-item list into scannable rows.
            if last_h is not None and span_h != last_h:
                size_menu.addSeparator()
            last_h = span_h
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

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
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
    def _wants_sparkline(entry: ControlPanelEntry) -> bool:
        return entry.show_sparkline and entry.is_numeric()

    def update_entry(self, entry: ControlPanelEntry) -> None:
        super().update_entry(entry)
        wanted = self._wants_sparkline(entry)
        if wanted != self._sparkline_visible:
            self._sparkline_visible = wanted
            self.sparkline.setVisible(wanted)

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self.sparkline.apply_theme_palette(theme)

    def apply_cell_width(self, cell_w: float) -> None:
        px = _scale_font_px(
            cell_w, VALUE_FONT_RATIO, VALUE_FONT_MIN_PX, VALUE_FONT_MAX_PX
        )
        font = self.value_label.font()
        if font.pixelSize() != px:
            font.setPixelSize(px)
            self.value_label.setFont(font)

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

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Double-click opens the chart (FR-48). Edit mode owns drag, so a
        # double-click there must not also blow the layout away.
        if (
            not self.edit_mode
            and self._entry.is_numeric()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.chartRequested.emit(self.entry_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LedTileWidget(TileFrame):
    """Large state lamp + state caption (FR-31)."""

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self.lamp = QLabel("")
        self.lamp.setObjectName("tileLamp")
        self.lamp.setFixedSize(LED_LAMP, LED_LAMP)
        self.caption_label = QLabel(TILE_STATE_CAPTIONS["neutral"])
        self.caption_label.setObjectName("tileStateCaption")
        self.caption_label.setWordWrap(True)
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

    def apply_cell_width(self, cell_w: float) -> None:
        px = _scale_font_px(
            cell_w,
            LED_CAPTION_FONT_RATIO,
            LED_CAPTION_FONT_MIN_PX,
            LED_CAPTION_FONT_MAX_PX,
        )
        font = self.caption_label.font()
        if font.pixelSize() != px:
            font.setPixelSize(px)
            self.caption_label.setFont(font)

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

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._is_on = False
        self._pending = False
        self._panel_armed = False
        self._commanded_on: bool | None = None  # last toggle direction sent
        self._mismatch = False
        self.setProperty("panelArmed", "false")
        self.button = QPushButton("", self)
        self.button.setObjectName("tileControlButton")
        self.button.setProperty("mismatch", "false")
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

    def update_entry(self, entry: ControlPanelEntry) -> None:
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
    def mismatch(self) -> bool:
        """True when the readback state differs from the commanded one."""
        return self._mismatch

    def set_commanded(self, on: bool | None) -> None:
        """Record the commanded ON/OFF direction (toggle only).

        Called by the tab on a successful Send so a later readback can
        flag a mismatch if the device ended up in the other state
        (FR-59). ``None`` clears tracking (e.g. momentary buttons).
        """
        self._commanded_on = on
        self._set_mismatch(False)

    def apply_readback(self, is_on: bool) -> None:
        """Reflect a device readback into the toggle visual + mismatch.

        Sets the ON/OFF state from the device and raises the warning when
        it disagrees with the last commanded direction.
        """
        self.set_on(is_on)
        if self._commanded_on is None:
            self._set_mismatch(False)
        else:
            self._set_mismatch(is_on != self._commanded_on)

    def _set_mismatch(self, on: bool) -> None:
        if self._mismatch == on:
            return
        self._mismatch = on
        self.button.setProperty("mismatch", "true" if on else "false")
        _repolish(self.button)

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

    def set_panel_armed(self, armed: bool) -> None:
        if self._panel_armed != armed:
            self._panel_armed = armed
            self.setProperty("panelArmed", "true" if armed else "false")
            _repolish(self)
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
        self.button.setEnabled(
            self._entry.enabled
            and not self._pending
            and not self.edit_mode
            and self._panel_armed
        )
        if not self._panel_armed:
            self.button.setToolTip("Panel is disarmed — click Arm in the header.")
        else:
            self.button.setToolTip("")
        state = "on" if control.mode == "toggle" and self._is_on else "off"
        if self.button.property("controlState") != state:
            self.button.setProperty("controlState", state)
            _repolish(self.button)


class _SelectOnFocusDoubleSpinBox(QDoubleSpinBox):
    """``QDoubleSpinBox`` that selects its entire numeric text on focus so
    typing replaces the current value instead of inserting at the cursor.

    Why: when the spinbox already shows ``"0.00 V"`` and the user clicks
    it, Qt parks the lineEdit cursor at the click position (typically 0).
    Typing ``"1"`` then makes the buffer ``"10.00 V"`` — Qt's validator
    accepts it as 10. Typing ``"2"`` makes ``"210.00 V"``, which exceeds
    ``max``, so the keystroke is silently rejected. Net result: the user
    types ``12.5`` and the value lands at ``10``. Selecting on focus
    sidesteps the whole class of bugs — the user's first keystroke now
    replaces the buffer with a clean value.

    ``on_focus_in`` / ``on_focus_out`` let the owning tile track whether
    the user is mid-edit, so readback reflection knows when to hold off
    (FR-66 "reflect except while editing").
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.on_focus_in: Callable[[], None] | None = None
        self.on_focus_out: Callable[[], None] | None = None

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().focusInEvent(event)
        if self.on_focus_in is not None:
            self.on_focus_in()
        # Defer selectAll until after Qt's own focusInEvent has run, which
        # otherwise clears the selection it just made.
        line = self.lineEdit()
        if line is not None:
            QTimer.singleShot(0, line.selectAll)

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().focusOutEvent(event)
        if self.on_focus_out is not None:
            self.on_focus_out()


class SetpointTileWidget(TileFrame):
    """Numeric setpoint whose spinbox is *also* its readback display
    (v3, FR-63..FR-67).

    The spinbox carries the commanded float value AND mirrors the latest
    readback (followed tile or direct query) — there is no separate
    readback field. Readback reflects into the spinbox whenever the user
    is not actively editing it; if a readback differs from the value the
    user last commanded, the spinbox shows a mismatch warning color so a
    device that clamped or rejected the command is obvious. Send (▶)
    stages the value on the tab and emits ``activateRequested`` — same
    funnel control tiles use, so the master-arm gate, the per-tile
    confirm, and the per-session FIFO dispatcher all fire for free.
    """

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._pending = False
        self._panel_armed = False
        self.setProperty("panelArmed", "false")
        self._setting_value = False  # re-entry guard for programmatic spinbox updates
        self._user_editing = False   # True between a user keystroke/step and focus-out/send
        self._commanded_value: float | None = None  # last value Send committed
        self._mismatch = False

        spec = entry.setpoint
        self._value: float = spec.clamp(spec.min_value)

        self.spin = _SelectOnFocusDoubleSpinBox(self)
        self.spin.setObjectName("tileSetpointSpin")
        self.spin.setKeyboardTracking(False)
        self.spin.setProperty("mismatch", "false")
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.spin.on_focus_in = self._on_spin_focus_in
        self.spin.on_focus_out = self._on_spin_focus_out

        self.send_button = QPushButton("▶", self)
        self.send_button.setObjectName("tileSetpointSend")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setFixedWidth(36)
        self.send_button.clicked.connect(
            lambda: self.activateRequested.emit(self.entry_id)
        )

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(SPACE_SM)
        input_row.addWidget(self.spin, 1)
        input_row.addWidget(self.send_button)

        self.body_layout.addLayout(input_row)

        self.spin.valueChanged.connect(self._spin_changed)
        # Enter in the spinbox sends the command — the keyboard-first
        # workflow operators expect. ``returnPressed`` fires only on
        # Enter (not Tab-out / focus loss), so leaving the field doesn't
        # accidentally write. The send button's own enable gating still
        # applies, so a disarmed panel or a tile already mid-send won't
        # double-trigger.
        line = self.spin.lineEdit()
        if line is not None:
            line.returnPressed.connect(self._submit_via_enter)
            # textEdited fires only on user keystrokes (never on
            # programmatic setValue), so it's the clean signal that the
            # user is editing and the prior command's comparison is moot.
            line.textEdited.connect(self._on_user_edit)
        self._apply_spec(spec)

    def _submit_via_enter(self) -> None:
        # Match what clicking Send does: respect the visible gate state
        # (armed + enabled + not pending) and route through the same
        # activateRequested signal funnel.
        if self.send_button.isEnabled():
            self.send_button.animateClick()

    # ------------------------------------------------------------- public

    def update_entry(self, entry: ControlPanelEntry) -> None:
        super().update_entry(entry)
        self._apply_spec(entry.setpoint)
        self._refresh_send_enabled()

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        return False  # state border / tooltip / timestamp come from TileFrame

    @property
    def value(self) -> float:
        """Float setpoint currently shown in the command spinbox."""
        return self._value

    @property
    def pending(self) -> bool:
        return self._pending

    def set_pending(self, pending: bool) -> None:
        if self._pending != pending:
            self._pending = pending
            self._refresh_send_enabled()
            if pending and self.send_button.text() != "…":
                self.send_button.setText("…")
            elif not pending and self.send_button.text() == "…":
                self.send_button.setText("▶")

    def set_value(self, value: float) -> None:
        """Seed the editable value without any mismatch bookkeeping.

        Used for connect-time seeding (FR-67), the dialog preview, and
        arm-change paths — i.e. "this is just the value to show", not a
        device readback to compare against a command.
        """
        clamped = self._entry.setpoint.clamp(value)
        if clamped != self._value:
            self._value = clamped
            self._sync_widgets()

    def mark_commanded(self) -> None:
        """Record the currently shown value as the commanded value.

        Called by the tab right after a Send is queued. Subsequent
        readbacks compare against this; a difference raises the mismatch
        warning (FR-66). Clears the editing flag so the post-send readback
        is allowed to reflect even though the spinbox may still hold focus.
        """
        self._commanded_value = self._value
        self._user_editing = False
        line = self.spin.lineEdit()
        if line is not None:
            line.setModified(False)
        self._set_mismatch(False)

    def apply_readback(self, value_number: float | None) -> None:
        """Reflect a device readback into the spinbox (FR-66).

        Writes the value unless the user is mid-edit, then flags a
        mismatch when it differs from the last commanded value. A
        non-numeric readback (``None``) leaves the field untouched.
        """
        if value_number is None:
            return
        try:
            readback = self._entry.setpoint.clamp(float(value_number))
        except (TypeError, ValueError):
            return
        if self._is_editing():
            return  # don't fight the user; a later readback will reflect
        self._value = readback
        self._sync_widgets()
        self._update_mismatch(readback)

    def set_edit_mode(self, enabled: bool) -> None:
        super().set_edit_mode(enabled)
        # Mouse-transparent so drag-to-place still works.
        for widget in (self.spin, self.send_button):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self._refresh_send_enabled()

    # ----------------------------------------------------------- internals

    def _apply_spec(self, spec) -> None:
        """Reconfigure the spinbox for a possibly edited spec."""
        self._setting_value = True
        try:
            self.spin.setRange(spec.min_value, spec.max_value)
            self.spin.setSingleStep(spec.step)
            self.spin.setDecimals(spec.effective_decimals())
            self.spin.setSuffix(f" {spec.unit}" if spec.unit else "")
            self._value = spec.clamp(self._value)
            self._sync_widgets()
        finally:
            self._setting_value = False
        self._refresh_send_enabled()

    def _spin_changed(self, value: float) -> None:
        if self._setting_value:
            return
        # A user-driven change (typing committed, step arrows) means the
        # user is entering a new value — invalidate the prior command's
        # comparison and treat this as an active edit.
        spec = self._entry.setpoint
        clamped = spec.clamp(value)
        self._value = clamped
        self._user_editing = True
        self._commanded_value = None
        self._set_mismatch(False)
        if clamped != value:
            # User typed out of range — clamp visually too.
            self._setting_value = True
            try:
                self.spin.setValue(clamped)
            finally:
                self._setting_value = False

    def _sync_widgets(self) -> None:
        prev = self._setting_value
        self._setting_value = True
        try:
            self.spin.setValue(self._value)
            line = self.spin.lineEdit()
            if line is not None:
                line.setModified(False)
        finally:
            self._setting_value = prev

    def _on_user_edit(self, _text: str = "") -> None:
        self._user_editing = True
        self._commanded_value = None
        self._set_mismatch(False)

    def _on_spin_focus_in(self) -> None:
        # Fresh focus: no edits yet, so readback may still reflect until
        # the first keystroke flips _user_editing back on.
        self._user_editing = False

    def _on_spin_focus_out(self) -> None:
        self._user_editing = False

    def _is_editing(self) -> bool:
        return self._user_editing

    def _update_mismatch(self, readback: float) -> None:
        commanded = self._commanded_value
        if commanded is None:
            self._set_mismatch(False)
            return
        decimals = self._entry.setpoint.effective_decimals()
        same = f"{readback:.{decimals}f}" == f"{commanded:.{decimals}f}"
        self._set_mismatch(not same)

    def _set_mismatch(self, on: bool) -> None:
        if self._mismatch == on:
            return
        self._mismatch = on
        self.spin.setProperty("mismatch", "true" if on else "false")
        _repolish(self.spin)

    @property
    def mismatch(self) -> bool:
        """True when the latest readback differs from the commanded value."""
        return self._mismatch

    def set_panel_armed(self, armed: bool) -> None:
        if self._panel_armed != armed:
            self._panel_armed = armed
            self.setProperty("panelArmed", "true" if armed else "false")
            _repolish(self)
            self._refresh_send_enabled()

    def _refresh_send_enabled(self) -> None:
        enabled = (
            self._entry.enabled
            and not self._pending
            and not self.edit_mode
            and self._panel_armed
        )
        self.send_button.setEnabled(enabled)
        if not self._panel_armed:
            self.send_button.setToolTip("Panel is disarmed — click Arm in the header.")
        else:
            self.send_button.setToolTip("")
        self.spin.setEnabled(self._entry.enabled and not self.edit_mode)

    def rendered_command(self) -> str:
        """The exact wire string a Send right now would produce. Used by
        the tab when staging the pending value AND by tests."""
        return self._entry.setpoint.render_command(self._value)


class EnumTileWidget(TileFrame):
    """Multi-position selector whose dropdown is *also* its readback display
    (v3, FR-68..FR-71).

    Internally a QComboBox plus a Send (▶) button. The user picks an
    option from the dropdown and clicks Send to fire that option's
    command — same FIFO dispatcher as control/setpoint. When a
    ``watch_entry_id`` readback is configured, the readback drives the
    combo's selection to the option whose ``match_value`` matches the
    device — except while the user is actively choosing (dropdown open /
    focused). If that reflected option differs from the option the user
    last sent, the combo shows a mismatch warning color (FR-66/FR-70).
    """

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._pending = False
        self._panel_armed = False
        self.setProperty("panelArmed", "false")
        self._indicated_index = -1     # option the latest readback matched
        self._commanded_index = -1     # option the last Send committed
        self._mismatch = False

        self.combo = QComboBox(self)
        self.combo.setObjectName("tileEnumCombo")
        self.combo.setProperty("mismatch", "false")
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # activated fires only on user selection (not programmatic
        # setCurrentIndex), so it's the signal that the user chose a new
        # option — clearing the prior command's mismatch comparison.
        self.combo.activated.connect(self._on_user_select)

        self.send_button = QPushButton("▶", self)
        self.send_button.setObjectName("tileEnumSend")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setFixedWidth(36)
        self.send_button.clicked.connect(
            lambda: self.activateRequested.emit(self.entry_id)
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE_SM)
        row.addWidget(self.combo, 1)
        row.addWidget(self.send_button)

        self.body_layout.addStretch(1)
        self.body_layout.addLayout(row)
        self.body_layout.addStretch(1)

        self._populate_options()
        self._refresh_send_enabled()

    # ----------------------------------------------------------- public

    def update_entry(self, entry: ControlPanelEntry) -> None:
        super().update_entry(entry)
        self._populate_options()
        self._refresh_send_enabled()

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        return False

    @property
    def pending(self) -> bool:
        return self._pending

    def set_pending(self, pending: bool) -> None:
        if self._pending != pending:
            self._pending = pending
            if pending and self.send_button.text() != "…":
                self.send_button.setText("…")
            elif not pending and self.send_button.text() == "…":
                self.send_button.setText("▶")
            self._refresh_send_enabled()

    @property
    def indicated_index(self) -> int:
        """The option index the latest readback matched (-1 if none)."""
        return self._indicated_index

    @property
    def mismatch(self) -> bool:
        """True when the readback option differs from the commanded one."""
        return self._mismatch

    def mark_commanded(self) -> None:
        """Record the currently selected option as the commanded one.

        Called by the tab right after a Send is queued; later readbacks
        compare against it to raise the mismatch warning (FR-66/FR-70).
        """
        self._commanded_index = self.combo.currentIndex()
        self._set_mismatch(False)

    def apply_readback(self, value_text: str) -> None:
        """Drive the combo's selection from a device readback (FR-70).

        Resolves ``value_text`` to an option via ``match_value`` and
        selects it unless the user is choosing right now; then flags a
        mismatch when it differs from the commanded option.
        """
        index = self._entry.enum_spec.indicated_index(value_text)
        self._indicated_index = index
        if index >= 0 and not self._is_editing():
            self.combo.blockSignals(True)
            try:
                self.combo.setCurrentIndex(index)
            finally:
                self.combo.blockSignals(False)
        self._update_mismatch(index)

    def selected_command(self) -> str:
        """Return the command for whatever option the user has picked."""
        index = self.combo.currentIndex()
        options = self._entry.enum_spec.options
        if 0 <= index < len(options):
            return options[index].command
        return ""

    def selected_label(self) -> str:
        index = self.combo.currentIndex()
        options = self._entry.enum_spec.options
        if 0 <= index < len(options):
            return options[index].label
        return ""

    def set_edit_mode(self, enabled: bool) -> None:
        super().set_edit_mode(enabled)
        for widget in (self.combo, self.send_button):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self._refresh_send_enabled()

    # ----------------------------------------------------------- internals

    def _populate_options(self) -> None:
        # Preserve the user's selection across config edits when possible.
        prior_label = self.selected_label()
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            for option in self._entry.enum_spec.options:
                self.combo.addItem(option.label or "(unnamed)")
            if prior_label:
                index = self.combo.findText(prior_label)
                if index >= 0:
                    self.combo.setCurrentIndex(index)
        finally:
            self.combo.blockSignals(False)
        self._indicated_index = -1   # caller re-applies via apply_readback
        self._commanded_index = -1
        self._set_mismatch(False)

    def _on_user_select(self, _index: int) -> None:
        # User picked a different option — the previous command's
        # comparison no longer applies.
        self._commanded_index = -1
        self._set_mismatch(False)

    def _is_editing(self) -> bool:
        view = self.combo.view()
        popup_open = bool(view is not None and view.isVisible())
        return popup_open or self.combo.hasFocus()

    def _update_mismatch(self, index: int) -> None:
        if self._commanded_index < 0:
            self._set_mismatch(False)
            return
        self._set_mismatch(index != self._commanded_index)

    def _set_mismatch(self, on: bool) -> None:
        if self._mismatch == on:
            return
        self._mismatch = on
        self.combo.setProperty("mismatch", "true" if on else "false")
        _repolish(self.combo)

    def set_panel_armed(self, armed: bool) -> None:
        if self._panel_armed != armed:
            self._panel_armed = armed
            self.setProperty("panelArmed", "true" if armed else "false")
            _repolish(self)
            self._refresh_send_enabled()

    def _refresh_send_enabled(self) -> None:
        enabled = (
            self._entry.enabled
            and not self._pending
            and not self.edit_mode
            and self.combo.count() > 0
            and self._panel_armed
        )
        self.send_button.setEnabled(enabled)
        if not self._panel_armed:
            self.send_button.setToolTip("Panel is disarmed — click Arm in the header.")
        else:
            self.send_button.setToolTip("")
        self.combo.setEnabled(self._entry.enabled and not self.edit_mode)


BITS_LAMP_SIZE = 12
BITS_GRID_COLUMNS = 2
BITS_LABEL_FONT_RATIO = 0.07
BITS_LABEL_FONT_MIN_PX = 10
BITS_LABEL_FONT_MAX_PX = 16


class BitsTileWidget(TileFrame):
    """Status / fault register tile.

    Each ``BitDefinition`` becomes a small lamp + label. The latest
    polled numeric value is coerced to int; any bit set in that int
    lights its lamp in its configured state color. Multiple bits can be
    active at once (typical for SCPI status registers like
    ``STAT:OPER:COND?`` or ``STAT:QUES:COND?``). Bits with no
    definition are simply not shown."""

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._spec = BitsSpec(bits=list(entry.bits_spec.bits))
        self._last_raw: int | None = None
        self._cell_width = 0.0

        self._bits_host = QWidget(self)
        self._bits_grid = QGridLayout(self._bits_host)
        self._bits_grid.setContentsMargins(0, 0, 0, 0)
        self._bits_grid.setHorizontalSpacing(SPACE_LG)
        self._bits_grid.setVerticalSpacing(SPACE_SM)

        self._empty_label = QLabel("No bits configured", self)
        self._empty_label.setObjectName("tileBitsEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)

        self.body_layout.addWidget(self._bits_host, 1)
        self.body_layout.addWidget(self._empty_label, 0, Qt.AlignmentFlag.AlignCenter)

        # bit position -> (lamp, label)
        self._indicators: dict[int, tuple[QLabel, QLabel]] = {}
        self._rebuild_indicators()

    # ---------------------------------------------------------- lifecycle

    def update_entry(self, entry: ControlPanelEntry) -> None:
        super().update_entry(entry)
        new_spec = BitsSpec(bits=list(entry.bits_spec.bits))
        if [(b.bit, b.label, b.state) for b in new_spec.bits] != [
            (b.bit, b.label, b.state) for b in self._spec.bits
        ]:
            self._spec = new_spec
            self._rebuild_indicators()
            if self._last_raw is not None:
                self._refresh_lamps(self._last_raw)

    def _rebuild_indicators(self) -> None:
        # Tear down old indicators.
        while self._bits_grid.count():
            item = self._bits_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._indicators.clear()

        bits = self._spec.bits
        if not bits:
            self._bits_host.setVisible(False)
            self._empty_label.setVisible(True)
            return
        self._bits_host.setVisible(True)
        self._empty_label.setVisible(False)

        for index, bit in enumerate(bits):
            lamp = QLabel("", self._bits_host)
            lamp.setObjectName("tileBitsLamp")
            lamp.setFixedSize(BITS_LAMP_SIZE, BITS_LAMP_SIZE)
            _set_state_property(lamp, "neutral")

            label = QLabel(bit.label or f"Bit {bit.bit}", self._bits_host)
            label.setObjectName("tileBitsLabel")
            label.setToolTip(bit.description or f"Bit {bit.bit}")
            label.setWordWrap(False)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )

            row, col = divmod(index, BITS_GRID_COLUMNS)
            cell = QHBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(SPACE_SM)
            cell.addWidget(lamp)
            cell.addWidget(label, 1)
            wrapper = QWidget(self._bits_host)
            wrapper.setLayout(cell)
            self._bits_grid.addWidget(wrapper, row, col)
            self._indicators[bit.bit] = (lamp, label)

        # Push the grid to the top so empty rows stay at the bottom.
        rows = (len(bits) + BITS_GRID_COLUMNS - 1) // BITS_GRID_COLUMNS
        self._bits_grid.setRowStretch(rows, 1)

        if self._cell_width > 0:
            self._apply_label_font(self._cell_width)

    # ----------------------------------------------------------- rendering

    @staticmethod
    def _coerce_int(runtime_value_number: float | None, value_text: str) -> int | None:
        """Best-effort: prefer the parsed float (rounded to int). Fall back
        to ``int(value_text, 0)`` so SCPI replies like ``0xFF`` or ``0b101``
        still light the right bits when the parse rule keeps them as text."""
        if runtime_value_number is not None:
            try:
                return int(runtime_value_number)
            except (TypeError, ValueError, OverflowError):
                return None
        if not value_text:
            return None
        try:
            return int(value_text.strip(), 0)
        except (TypeError, ValueError):
            return None

    def _refresh_lamps(self, raw: int) -> None:
        active = {bit.bit for bit in self._spec.active_bits(raw)}
        for bit in self._spec.bits:
            lamp, label = self._indicators.get(bit.bit, (None, None))
            if lamp is None or label is None:
                continue
            target_state = bit.state if bit.bit in active else "neutral"
            if lamp.property("tileState") != target_state:
                _set_state_property(lamp, target_state)
            label.setProperty("bitActive", "true" if bit.bit in active else "false")
            _repolish(label)

    def _render_runtime(self, runtime: "TileRuntime") -> bool:
        raw = self._coerce_int(runtime.value_number, runtime.value_text)
        changed = False
        if raw is None:
            # Unknown reading: clear all lamps.
            for bit in self._spec.bits:
                lamp = self._indicators.get(bit.bit, (None, None))[0]
                if lamp is None:
                    continue
                if lamp.property("tileState") != "neutral":
                    _set_state_property(lamp, "neutral")
                    changed = True
            self._last_raw = None
            return changed
        if raw != self._last_raw:
            self._refresh_lamps(raw)
            self._last_raw = raw
            changed = True
        return changed

    # ----------------------------------------------------- responsive font

    def apply_cell_width(self, cell_w: float) -> None:
        self._cell_width = cell_w
        self._apply_label_font(cell_w)

    def _apply_label_font(self, cell_w: float) -> None:
        px = _scale_font_px(
            cell_w,
            BITS_LABEL_FONT_RATIO,
            BITS_LABEL_FONT_MIN_PX,
            BITS_LABEL_FONT_MAX_PX,
        )
        for _lamp, label in self._indicators.values():
            font = label.font()
            if font.pixelSize() != px:
                font.setPixelSize(px)
                label.setFont(font)


TILE_CLASSES: dict[str, type[TileFrame]] = {
    "value": ValueTileWidget,
    "led": LedTileWidget,
    "control": ControlTileWidget,
    "setpoint": SetpointTileWidget,
    "enum": EnumTileWidget,
    "bits": BitsTileWidget,
}


def tile_class_for(entry: ControlPanelEntry) -> type[TileFrame]:
    return TILE_CLASSES.get(entry.tile.kind, ValueTileWidget)


def create_tile(entry: ControlPanelEntry, parent: QWidget | None = None) -> TileFrame:
    """Factory keyed on the entry's tile kind."""
    return tile_class_for(entry)(entry, parent)
