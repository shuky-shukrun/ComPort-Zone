"""In-tile sparkline: a thin trend strip painted under the value label.

Stateless from the tile's point of view — the tab feeds samples in via
:meth:`set_samples`, the widget hands them to ``downsample_minmax`` from
:mod:`control_panel_history`, and a short repaint draws an antialiased
polyline plus a soft fill. Colors come from the theme palette or the
current rule verdict; nothing here hardcodes a hex literal, so the
existing widget hex-scan test keeps passing.

Requirements: docs/control_panel-view-requirements.md (FR-46, FR-47, NFR-1).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..control_panel_history import Sample, downsample_minmax
from ..themes import THEMES, ThemePalette

# A 120-second window keeps the strip readable on dense polls while
# still showing minute-scale trends (FR-46).
SPARKLINE_WINDOW_S = 120.0
SPARKLINE_HEIGHT = 22
# Cap paint input so a tile with maxed-out history (~600 samples) still
# repaints cheaply (NFR-1).
SPARKLINE_BUCKETS = 64
FILL_ALPHA = 60


class SparklineWidget(QWidget):
    """Trend strip rendered from a list of (time, value) samples."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tileSparkline")
        self.setFixedHeight(SPARKLINE_HEIGHT)
        # Stretch horizontally to fill the tile body — without this the
        # default Preferred policy collapses the widget to its sizeHint
        # (~28 px) when laid out inside a tile, leaving the strip stuck
        # in the corner instead of spanning the bottom of the tile.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._theme: ThemePalette = THEMES["ComPort Zone Dark"]
        self._samples: list[Sample] = []
        self._color: str = ""
        self._now: float = 0.0

    # ------------------------------------------------------------- API

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self._theme = theme
        if self.isVisible():
            self.update()

    def set_samples(self, samples: list[Sample], color: str, *, now: float) -> bool:
        """Update what the strip should draw.

        Returns True when anything visible changed (the tile uses this to
        coalesce repaints, NFR-1). ``color`` is a hex string from the
        verdict pipeline; ``now`` is the control_panel's monotonic clock so
        the rolling window stays test-deterministic.
        """
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

    def has_data(self) -> bool:
        return len(self._samples) >= 2

    # ---------------------------------------------------------- painting

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if not self.has_data():
            return
        end_t = self._now
        start_t = end_t - SPARKLINE_WINDOW_S
        visible = [s for s in self._samples if s[0] >= start_t]
        if len(visible) < 2:
            return
        points = downsample_minmax(visible, SPARKLINE_BUCKETS)
        values = [v for _t, v in points]
        lo, hi = min(values), max(values)
        if hi == lo:
            hi = lo + 1.0  # flat line: keep it centered
        width = self.width()
        height = self.height()
        if width <= 1 or height <= 4:
            return
        # Time domain spans the rolling window so the strip "slides" left
        # as ``now`` advances even when no new samples have landed.
        time_span = SPARKLINE_WINDOW_S
        margin = 2.0
        plot_w = width - 1
        plot_h = height - 2 * margin

        def to_xy(sample: Sample) -> QPointF:
            x = plot_w * max(0.0, (sample[0] - start_t) / time_span)
            y = margin + plot_h - plot_h * (sample[1] - lo) / (hi - lo)
            return QPointF(x, y)

        xy = [to_xy(sample) for sample in points]

        stroke = QColor(self._color) if self._color else QColor(self._theme.tx)
        if not stroke.isValid():
            stroke = QColor(self._theme.tx)
        fill = QColor(stroke)
        fill.setAlpha(FILL_ALPHA)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Soft fill under the polyline first so the line sits on top.
        baseline = margin + plot_h
        area = QPainterPath()
        area.moveTo(xy[0].x(), baseline)
        for point in xy:
            area.lineTo(point)
        area.lineTo(xy[-1].x(), baseline)
        area.closeSubpath()
        painter.fillPath(area, fill)

        pen = QPen(stroke, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath(xy[0])
        for point in xy[1:]:
            path.lineTo(point)
        painter.drawPath(path)
        painter.end()
