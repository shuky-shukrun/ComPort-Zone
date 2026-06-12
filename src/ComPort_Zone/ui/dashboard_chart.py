"""Large-format chart page for one dashboard entry (FR-48/FR-49).

Painted with QPainter against the same Qt-free history helpers the
sparkline already uses (``downsample_minmax``, ``nice_ticks``,
``nearest_sample``) — no plotting dependency. Lives as stack page 2 of
:class:`DashboardTabWidget`; the tab opens it on tile double-click or
the tile's "Open Chart…" menu, hands a fresh sample list in via
:meth:`DashboardChartPage.set_history` at ~10 Hz while it is visible,
and pops back to the grid when the entry is deleted or the user hits
Back.

Colors come from a forwarded :class:`ThemePalette` plus the active
verdict color — no hex literals — so the widget hex-scan test keeps
passing across every theme.

Requirements: docs/dashboard-view-requirements.md (FR-48, FR-49, FR-62).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..dashboard_history import (
    Sample,
    downsample_minmax,
    nearest_sample,
    nice_ticks,
)
from ..dashboard_models import DashboardEntry
from ..themes import THEMES, ThemePalette
from ..widgets import ChevronComboBox
from .tokens import RADIUS_MD, SPACE_LG, SPACE_MD, SPACE_SM

# (label, window seconds). Single source so the combo and the default
# stay in lockstep across UI and tests (FR-49).
CHART_SPANS: tuple[tuple[str, int], ...] = (
    ("Last 1 minute", 60),
    ("Last 5 minutes", 300),
    ("Last 30 minutes", 1800),
    ("Last 1 hour", 3600),
)
DEFAULT_SPAN_S = 300

# Paint tuning — kept here (not QSS) so the chart math stays a pure
# Qt-free shell over dashboard_history.
PAD_LEFT = 56
PAD_RIGHT = 16
PAD_TOP = 16
PAD_BOTTOM = 36
TICK_LEN = 4
LINE_WIDTH = 1.6
GRID_PEN_WIDTH = 1.0
CROSSHAIR_PEN_WIDTH = 1.0
HOVER_DOT_RADIUS = 4
MIN_Y_RANGE = 1e-6  # avoids divide-by-zero on flat traces


def format_value(value: float) -> str:
    """Compact numeric label for axis ticks and readouts."""
    return f"{value:.6g}"


def format_time_offset(seconds_ago: float) -> str:
    """Right edge of the chart is "now"; left edges are negative offsets."""
    if seconds_ago == 0:
        return "now"
    if seconds_ago < 60:
        return f"-{seconds_ago:.0f}s"
    if seconds_ago < 3600:
        return f"-{seconds_ago / 60:.0f}m"
    return f"-{seconds_ago / 3600:.1f}h"


@dataclass(slots=True)
class ChartReadout:
    """Min/max/last summary string the page shows in its header."""

    last: str = "—"
    minimum: str = "—"
    maximum: str = "—"
    sample_count: int = 0


def readout_for(samples: list[Sample]) -> ChartReadout:
    if not samples:
        return ChartReadout()
    values = [v for _t, v in samples]
    return ChartReadout(
        last=format_value(samples[-1][1]),
        minimum=format_value(min(values)),
        maximum=format_value(max(values)),
        sample_count=len(samples),
    )


class ChartView(QWidget):
    """The plot area: axes, grid, polyline, hover crosshair."""

    hoverChanged = Signal(object)  # ChartReadout | None for nearest sample

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardChartView")
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._theme: ThemePalette = THEMES["ComPort Zone Dark"]
        self._samples: list[Sample] = []
        self._color: str = ""
        self._now: float = 0.0
        self._window_s: float = float(DEFAULT_SPAN_S)
        self._hover_x: float | None = None

    # ------------------------------------------------------------- API

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self._theme = theme
        self.update()

    def set_window(self, window_s: float) -> None:
        window_s = max(1.0, float(window_s))
        if window_s != self._window_s:
            self._window_s = window_s
            self.update()

    @property
    def window_s(self) -> float:
        return self._window_s

    def set_history(self, samples: list[Sample], color: str, *, now: float) -> bool:
        changed = False
        if self._samples != samples:
            self._samples = list(samples)
            changed = True
        if self._color != color:
            self._color = color
            changed = True
        if self._now != now:
            self._now = now
            changed = True
        if changed:
            self.update()
        return changed

    def visible_samples(self) -> list[Sample]:
        start = self._now - self._window_s
        return [sample for sample in self._samples if sample[0] >= start]

    # ----------------------------------------------------------- hover

    def hovered_sample(self) -> Sample | None:
        if self._hover_x is None:
            return None
        plot = self._plot_rect()
        if plot.width() <= 0:
            return None
        visible = self.visible_samples()
        if not visible:
            return None
        start = self._now - self._window_s
        # Map cursor x back to time space (clamped to the visible window).
        ratio = max(0.0, min(1.0, (self._hover_x - plot.left()) / plot.width()))
        t = start + ratio * self._window_s
        return nearest_sample(visible, t)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        plot = self._plot_rect()
        x = event.position().x()
        if plot.left() <= x <= plot.right():
            self._hover_x = x
        else:
            self._hover_x = None
        self.update()
        self.hoverChanged.emit(self._hover_readout())

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._hover_x = None
        self.update()
        self.hoverChanged.emit(None)

    def _hover_readout(self) -> ChartReadout | None:
        sample = self.hovered_sample()
        if sample is None:
            return None
        t, value = sample
        return ChartReadout(
            last=format_value(value),
            minimum=format_time_offset(self._now - t),
            maximum="",
            sample_count=0,
        )

    # ----------------------------------------------------------- paint

    def _plot_rect(self) -> QRect:
        return QRect(
            PAD_LEFT,
            PAD_TOP,
            max(0, self.width() - PAD_LEFT - PAD_RIGHT),
            max(0, self.height() - PAD_TOP - PAD_BOTTOM),
        )

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        plot = self._plot_rect()
        if plot.width() <= 1 or plot.height() <= 1:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self._theme.surface))

        ink = QColor(self._theme.text)
        muted = QColor(self._theme.muted)
        grid_color = QColor(muted)
        grid_color.setAlpha(80)
        font_metrics = QFontMetrics(self.font())

        visible = self.visible_samples()
        if len(visible) >= 2:
            values = [v for _t, v in visible]
            lo, hi = min(values), max(values)
        else:
            lo, hi = 0.0, 1.0
        if hi - lo < MIN_Y_RANGE:
            pad = max(abs(lo) * 0.1, 1.0)
            lo, hi = lo - pad, hi + pad
        ticks = nice_ticks(lo, hi, 5)
        if ticks:
            lo = min(lo, ticks[0])
            hi = max(hi, ticks[-1])
        span = hi - lo
        if span < MIN_Y_RANGE:
            span = MIN_Y_RANGE

        # --- grid + Y tick labels
        grid_pen = QPen(grid_color, GRID_PEN_WIDTH, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        for tick in ticks:
            y = plot.bottom() - plot.height() * (tick - lo) / span
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QPen(muted))
            label = format_value(tick)
            painter.drawText(
                QRect(0, int(y) - 8, PAD_LEFT - TICK_LEN - 2, 16),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
            painter.setPen(grid_pen)

        # --- X tick labels (relative offsets — "right edge is now").
        # Offsets are picked with nice_ticks so the steps land on round
        # values (-5m, -4m, -3m, …) instead of arithmetic fractions of
        # the window.
        painter.setPen(QPen(muted))
        offset_ticks = nice_ticks(0.0, float(self._window_s), 5)
        for offset in offset_ticks:
            if offset < 0 or offset > self._window_s:
                continue
            ratio = 1.0 - offset / self._window_s
            x = plot.left() + plot.width() * ratio
            label = format_time_offset(offset)
            text_w = font_metrics.horizontalAdvance(label)
            painter.drawText(
                int(x - text_w / 2),
                plot.bottom() + 18,
                label,
            )

        # --- frame around the plot
        painter.setPen(QPen(muted))
        painter.drawRect(plot)

        # --- polyline
        if len(visible) >= 2:
            buckets = max(8, plot.width() // 2)
            decimated = downsample_minmax(visible, buckets)
            start = self._now - self._window_s
            stroke = QColor(self._color) if self._color else QColor(self._theme.tx)
            if not stroke.isValid():
                stroke = QColor(self._theme.tx)
            fill = QColor(stroke)
            fill.setAlpha(40)

            def to_xy(sample: Sample) -> QPointF:
                tx = plot.left() + plot.width() * (sample[0] - start) / self._window_s
                ty = plot.bottom() - plot.height() * (sample[1] - lo) / span
                return QPointF(tx, ty)

            xy = [to_xy(sample) for sample in decimated]

            fill_path = QPainterPath()
            fill_path.moveTo(xy[0].x(), plot.bottom())
            for point in xy:
                fill_path.lineTo(point)
            fill_path.lineTo(xy[-1].x(), plot.bottom())
            fill_path.closeSubpath()
            painter.fillPath(fill_path, fill)

            pen = QPen(stroke, LINE_WIDTH)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath(xy[0])
            for point in xy[1:]:
                path.lineTo(point)
            painter.drawPath(path)

            # --- hover crosshair (FR-49)
            sample = self.hovered_sample()
            if sample is not None:
                px = to_xy(sample)
                cross_pen = QPen(muted, CROSSHAIR_PEN_WIDTH, Qt.PenStyle.DashLine)
                painter.setPen(cross_pen)
                painter.drawLine(
                    QPointF(px.x(), plot.top()),
                    QPointF(px.x(), plot.bottom()),
                )
                painter.setPen(QPen(stroke, LINE_WIDTH))
                painter.setBrush(stroke)
                painter.drawEllipse(px, HOVER_DOT_RADIUS, HOVER_DOT_RADIUS)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                # Floating readout near the dot.
                label = (
                    f"{format_value(sample[1])}  "
                    f"({format_time_offset(self._now - sample[0])})"
                )
                text_w = font_metrics.horizontalAdvance(label) + 12
                text_h = font_metrics.height() + 6
                box_x = min(plot.right() - text_w, max(plot.left(), px.x() + 8))
                box_y = max(plot.top(), px.y() - text_h - 8)
                box = QRect(int(box_x), int(box_y), text_w, text_h)
                bg = QColor(self._theme.surface_alt or self._theme.surface)
                bg.setAlpha(220)
                painter.setPen(QPen(muted))
                painter.setBrush(bg)
                painter.drawRoundedRect(box, RADIUS_MD, RADIUS_MD)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(ink))
                painter.drawText(
                    box,
                    int(Qt.AlignmentFlag.AlignCenter),
                    label,
                )
        else:
            painter.setPen(QPen(muted))
            painter.drawText(
                plot,
                int(Qt.AlignmentFlag.AlignCenter),
                "Waiting for samples…",
            )

        painter.end()


class DashboardChartPage(QWidget):
    """Header (back + title + span combo + readout) over a ChartView."""

    backRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardChartPage")
        self._entry_id: str = ""

        self.back_button = QPushButton("← Back", self)
        self.back_button.setObjectName("dashboardChartBack")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.backRequested)

        self.title_label = QLabel("", self)
        self.title_label.setObjectName("dashboardChartTitle")

        self.span_combo = ChevronComboBox(self)
        for label, seconds in CHART_SPANS:
            self.span_combo.addItem(label, seconds)
        self._select_data(self.span_combo, DEFAULT_SPAN_S)
        self.span_combo.currentIndexChanged.connect(self._span_changed)

        self.follow_check = QCheckBox("Follow live", self)
        self.follow_check.setChecked(True)
        # Cosmetic-only in v2 (chart always trails ``now``); the toggle
        # lives here so V2-T11's test surface covers the wire-up and a
        # later patch can pin the window to a fixed end-time.

        self.readout_label = QLabel("—", self)
        self.readout_label.setObjectName("dashboardChartReadout")

        header = QHBoxLayout()
        header.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        header.setSpacing(SPACE_LG)
        header.addWidget(self.back_button)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.span_combo)
        header.addWidget(self.follow_check)
        header.addWidget(self.readout_label)

        self.chart_view = ChartView(self)
        self.chart_view.hoverChanged.connect(self._on_hover_changed)
        self._readout_text = "—"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE_SM)
        root.addLayout(header)
        root.addWidget(self.chart_view, 1)

    # ------------------------------------------------------------- API

    @property
    def entry_id(self) -> str:
        return self._entry_id

    def set_entry(self, entry: DashboardEntry) -> None:
        self._entry_id = entry.id
        label = entry.display_label()
        if entry.unit:
            label = f"{label}  ({entry.unit})"
        self.title_label.setText(label)

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self.chart_view.apply_theme_palette(theme)

    def set_history(self, samples: list[Sample], color: str, *, now: float) -> None:
        self.chart_view.set_history(samples, color, now=now)
        readout = readout_for(samples)
        self._readout_text = (
            "—"
            if readout.sample_count == 0
            else f"last {readout.last} · min {readout.minimum} · max {readout.maximum} "
            f"· {readout.sample_count} sample(s)"
        )
        # Mouse-out and live updates both restore the summary readout.
        if self.chart_view.hovered_sample() is None:
            self.readout_label.setText(self._readout_text)

    @property
    def window_s(self) -> int:
        return int(self.chart_view.window_s)

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _select_data(combo: ChevronComboBox, data) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == data:
                combo.setCurrentIndex(index)
                return

    def _span_changed(self) -> None:
        seconds = self.span_combo.currentData()
        if seconds is not None:
            self.chart_view.set_window(float(seconds))

    def _on_hover_changed(self, readout) -> None:
        if readout is None:
            self.readout_label.setText(self._readout_text)
        else:
            self.readout_label.setText(
                f"hover {readout.last}  ({readout.minimum})"
            )
