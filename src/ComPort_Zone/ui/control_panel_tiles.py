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

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..control_panel_history import Sample
from ..control_panel_models import (
    MAX_TILE_SPAN,
    ControlPanelEntry,
    format_setpoint_value,
)
from ..themes import ThemePalette
from .control_panel_sparkline import SparklineWidget
from .tokens import LED_LAMP, SPACE_LG, SPACE_MD, SPACE_SM

CONTROL_PANEL_TILE_MIME_TYPE = "application/x-comport-zone-control_panel-tile"

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
    chartRequested = Signal(str)  # emitted by value tiles only (FR-48)

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
        mime.setData(CONTROL_PANEL_TILE_MIME_TYPE, self.entry_id.encode("utf-8"))
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
        if self._entry.is_numeric() and self._entry.tile.kind != "control":
            chart_action = menu.addAction("Open Chart…")
            chart_action.triggered.connect(
                lambda: self.chartRequested.emit(self.entry_id)
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
        self.setProperty("panelArmed", "false")
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


class SetpointTileWidget(TileFrame):
    """Numeric setpoint with slider + typeable field + optional readback
    (v3, FR-63..FR-67).

    The slider drives an integer step index; the spinbox carries the
    actual float value. Both bind to ``_value`` and update each other
    through ``_setting_value`` to short-circuit any infinite recurse.
    Send (▶) stages the value on the tab and emits
    ``activateRequested`` — same funnel control tiles use, so the
    master-arm gate, the per-tile confirm, and the per-session FIFO
    dispatcher all fire for free.
    """

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._pending = False
        self._panel_armed = False
        self.setProperty("panelArmed", "false")
        self._setting_value = False  # re-entry guard for slider<->spinbox
        self._readback_text = ""
        self._readback_state = "neutral"
        self._readback_color = ""

        spec = entry.setpoint
        self._value: float = spec.clamp(spec.min_value)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setObjectName("tileSetpointSlider")
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.spin = QDoubleSpinBox(self)
        self.spin.setObjectName("tileSetpointSpin")
        self.spin.setKeyboardTracking(False)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.send_button = QPushButton("▶", self)
        self.send_button.setObjectName("tileSetpointSend")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setFixedWidth(36)
        self.send_button.clicked.connect(
            lambda: self.activateRequested.emit(self.entry_id)
        )

        self.readback_label = QLabel("", self)
        self.readback_label.setObjectName("tileSetpointReadback")
        self.readback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.readback_label.setWordWrap(False)
        self.readback_label.setVisible(False)

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(SPACE_SM)
        slider_row.addWidget(self.slider, 1)

        spin_row = QHBoxLayout()
        spin_row.setContentsMargins(0, 0, 0, 0)
        spin_row.setSpacing(SPACE_SM)
        spin_row.addWidget(self.spin, 1)
        spin_row.addWidget(self.send_button)

        self.body_layout.addLayout(slider_row)
        self.body_layout.addLayout(spin_row)
        self.body_layout.addWidget(self.readback_label)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        self._apply_spec(spec)

    # ------------------------------------------------------------- public

    def update_entry(self, entry: ControlPanelEntry) -> None:
        super().update_entry(entry)
        self._apply_spec(entry.setpoint)
        self._refresh_send_enabled()

    def _render_runtime(self, runtime: TileRuntime) -> bool:
        return False  # state border / tooltip / timestamp come from TileFrame

    @property
    def value(self) -> float:
        """Float setpoint currently shown (slider + spinbox)."""
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
        """External setter (used by the dialog preview + arm-change paths)."""
        clamped = self._entry.setpoint.clamp(value)
        if clamped != self._value:
            self._value = clamped
            self._sync_widgets()

    def set_readback(self, value_text: str, state: str, color: str) -> None:
        """Push the watched entry's latest value into the readback line."""
        self._readback_text = value_text
        self._readback_state = state
        self._readback_color = color
        self._refresh_readback()

    def clear_readback(self) -> None:
        self._readback_text = ""
        self._refresh_readback()

    def set_edit_mode(self, enabled: bool) -> None:
        super().set_edit_mode(enabled)
        # Mouse-transparent so drag-to-place still works.
        for widget in (self.slider, self.spin, self.send_button):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self._refresh_send_enabled()

    # ----------------------------------------------------------- internals

    def _apply_spec(self, spec) -> None:
        """Reconfigure slider/spinbox to match a (possibly edited) spec."""
        # Compute step count carefully — guard against degenerate specs.
        span = max(spec.max_value - spec.min_value, spec.step)
        steps = max(1, round(span / spec.step))
        self._setting_value = True
        try:
            self.slider.setRange(0, steps)
            self.spin.setRange(spec.min_value, spec.max_value)
            self.spin.setSingleStep(spec.step)
            self.spin.setDecimals(spec.decimals)
            self.spin.setSuffix(f" {spec.unit}" if spec.unit else "")
            self._value = spec.clamp(self._value)
            self._sync_widgets()
            self.readback_label.setVisible(bool(spec.watch_entry_id))
            if not spec.watch_entry_id:
                self.clear_readback()
        finally:
            self._setting_value = False
        self._refresh_send_enabled()

    def _slider_changed(self, step_index: int) -> None:
        if self._setting_value:
            return
        spec = self._entry.setpoint
        value = spec.clamp(spec.min_value + step_index * spec.step)
        self._value = value
        # Push to spinbox without re-entering this slot.
        self._setting_value = True
        try:
            self.spin.setValue(value)
        finally:
            self._setting_value = False

    def _spin_changed(self, value: float) -> None:
        if self._setting_value:
            return
        spec = self._entry.setpoint
        clamped = spec.clamp(value)
        self._value = clamped
        self._setting_value = True
        try:
            if clamped != value:
                # User typed out of range — clamp visually too.
                self.spin.setValue(clamped)
            self.slider.setValue(self._step_index_for(clamped))
        finally:
            self._setting_value = False

    def _step_index_for(self, value: float) -> int:
        spec = self._entry.setpoint
        if spec.step <= 0:
            return 0
        return max(0, min(self.slider.maximum(), round((value - spec.min_value) / spec.step)))

    def _sync_widgets(self) -> None:
        self.slider.setValue(self._step_index_for(self._value))
        self.spin.setValue(self._value)

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
        for widget in (self.slider, self.spin):
            widget.setEnabled(self._entry.enabled and not self.edit_mode)

    def _refresh_readback(self) -> None:
        spec = self._entry.setpoint
        if not spec.watch_entry_id:
            self.readback_label.setVisible(False)
            return
        unit = f" {spec.unit}" if spec.unit else ""
        if self._readback_text:
            text = f"→ {self._readback_text}{unit} measured"
        else:
            text = f"→ — {unit.strip()} measured".rstrip()
        self.readback_label.setText(text)
        self.readback_label.setVisible(True)
        # Borrow the state property surface so QSS picks the right color.
        _set_state_property(self.readback_label, self._readback_state)
        _apply_custom_style(self.readback_label, "color: {color};", self._readback_color)

    def rendered_command(self) -> str:
        """The exact wire string a Send right now would produce. Used by
        the tab when staging the pending value AND by tests."""
        return self._entry.setpoint.render_command(self._value)


class EnumTileWidget(TileFrame):
    """Multi-position selector with one command per option (v3, FR-68..FR-71).

    Internally a QComboBox plus a Send (▶) button. The user picks an
    option from the dropdown and clicks Send to fire that option's
    command — same FIFO dispatcher as control/setpoint. An optional
    watch_entry_id highlights the option whose ``match_value`` matches
    the watched polled tile (decoupled from the user's combo selection
    so they can still send a different option).
    """

    def __init__(self, entry: ControlPanelEntry, parent: QWidget | None = None) -> None:
        super().__init__(entry, parent)
        self._pending = False
        self._panel_armed = False
        self.setProperty("panelArmed", "false")
        self._indicated_index = -1

        self.combo = QComboBox(self)
        self.combo.setObjectName("tileEnumCombo")
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

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
        return self._indicated_index

    def set_indicated_index(self, index: int) -> None:
        """Highlight an option without changing the user's selection.

        Used by the funnel to mirror the watched polled tile's value
        — operators still keep their own choice in the combo (FR-70).
        """
        valid = -1 <= index < self.combo.count()
        if not valid or index == self._indicated_index:
            return
        prev = self._indicated_index
        self._indicated_index = index
        # Use a foreground-role tweak on the indicated row so QSS rules
        # apply uniformly regardless of theme.
        for row in (prev, index):
            if 0 <= row < self.combo.count():
                self.combo.setItemData(
                    row,
                    "on" if row == index else "off",
                    int(Qt.ItemDataRole.UserRole) + 1,
                )
        self.combo.update()

    def update_indicator(self, value_text: str) -> None:
        """Recompute the indicated option from the watched value."""
        self.set_indicated_index(self._entry.enum_spec.indicated_index(value_text))

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
        self._indicated_index = -1  # caller re-applies via update_indicator

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


TILE_CLASSES: dict[str, type[TileFrame]] = {
    "value": ValueTileWidget,
    "led": LedTileWidget,
    "control": ControlTileWidget,
    "setpoint": SetpointTileWidget,
    "enum": EnumTileWidget,
}


def tile_class_for(entry: ControlPanelEntry) -> type[TileFrame]:
    return TILE_CLASSES.get(entry.tile.kind, ValueTileWidget)


def create_tile(entry: ControlPanelEntry, parent: QWidget | None = None) -> TileFrame:
    """Factory keyed on the entry's tile kind."""
    return tile_class_for(entry)(entry, parent)
