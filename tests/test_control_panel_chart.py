"""Tests for the control_panel chart page (FR-48/FR-49)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from ComPort_Zone.control_panel_models import (
    ControlPanelEntry,
    ParseRule,
    TilePlacement,
)
from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.control_panel_chart import (
    CHART_SPANS,
    DEFAULT_SPAN_S,
    ChartView,
    ControlPanelChartPage,
    format_time_offset,
    readout_for,
)


def _value_entry() -> ControlPanelEntry:
    return ControlPanelEntry(
        id="volts",
        label="Rail A",
        unit="V",
        command="MEAS:VOLT?",
        parse=ParseRule(kind="line", value_type="number"),
        tile=TilePlacement(col=0, row=0, kind="value"),
    )


class FormattingTests(unittest.TestCase):
    def test_format_time_offset_boundaries(self) -> None:
        self.assertEqual(format_time_offset(0), "now")
        self.assertEqual(format_time_offset(30), "-30s")
        self.assertEqual(format_time_offset(120), "-2m")
        self.assertEqual(format_time_offset(3600), "-1.0h")

    def test_readout_for_empty_and_populated(self) -> None:
        self.assertEqual(readout_for([]).sample_count, 0)
        readout = readout_for([(0.0, 1.0), (1.0, 2.5), (2.0, -0.5)])
        self.assertEqual(readout.minimum, "-0.5")
        self.assertEqual(readout.maximum, "2.5")
        self.assertEqual(readout.last, "-0.5")
        self.assertEqual(readout.sample_count, 3)


class ChartViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_view(self) -> ChartView:
        view = ChartView()
        view.resize(400, 240)
        view.apply_theme_palette(THEMES["ComPort Zone Dark"])
        return view

    def test_set_history_coalesces(self) -> None:
        view = self.make_view()
        samples = [(float(i), float(i)) for i in range(10)]
        self.assertTrue(view.set_history(samples, "#abcdef", now=10.0))
        self.assertFalse(view.set_history(samples, "#abcdef", now=10.0))
        self.assertTrue(view.set_history(samples, "#fedcba", now=10.0))
        view.deleteLater()

    def test_visible_samples_filters_by_window(self) -> None:
        view = self.make_view()
        view.set_window(60.0)
        samples = [(0.0, 1.0), (50.0, 2.0), (90.0, 3.0), (110.0, 4.0)]
        view.set_history(samples, "", now=120.0)
        visible = view.visible_samples()
        # Window is [now - 60, now] = [60, 120] -> 90 and 110 only.
        self.assertEqual(visible, [(90.0, 3.0), (110.0, 4.0)])
        view.deleteLater()

    def test_set_window_clamps_to_minimum(self) -> None:
        view = self.make_view()
        view.set_window(-5)
        self.assertGreaterEqual(view.window_s, 1.0)
        view.deleteLater()

    def test_paint_empty_does_not_raise(self) -> None:
        view = self.make_view()
        view.show()
        view.repaint()  # waiting-for-samples branch
        view.deleteLater()

    def test_grab_smoke_across_all_themes(self) -> None:
        samples = [(float(i), 12.0 + (i % 7) * 0.5) for i in range(180)]
        for theme_name, theme in THEMES.items():
            with self.subTest(theme=theme_name):
                view = ChartView()
                view.resize(400, 240)
                view.apply_theme_palette(theme)
                view.set_history(samples, "", now=180.0)
                view.show()
                view.grab()
                view.deleteLater()

    def test_hover_picks_nearest_visible_sample(self) -> None:
        view = self.make_view()
        view.set_window(100.0)
        samples = [(float(i) * 10.0, float(i)) for i in range(10)]
        view.set_history(samples, "", now=100.0)
        view.show()
        # Simulate cursor near the middle of the plot -> middle sample.
        plot = view._plot_rect()
        mid_x = plot.left() + plot.width() / 2
        mid_y = plot.center().y()
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(mid_x, mid_y),
            QPointF(mid_x, mid_y),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.mouseMoveEvent(event)
        sample = view.hovered_sample()
        assert sample is not None
        # Mid-window time ~50 -> sample value ~5.
        self.assertAlmostEqual(sample[1], 5.0, delta=1.0)
        view.deleteLater()

    def test_hover_outside_plot_clears(self) -> None:
        view = self.make_view()
        samples = [(0.0, 1.0), (1.0, 2.0)]
        view.set_history(samples, "", now=2.0)
        view.show()
        far_left = QPointF(-50, view.height() / 2)
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            far_left,
            far_left,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.mouseMoveEvent(event)
        self.assertIsNone(view.hovered_sample())
        view.deleteLater()


class ControlPanelChartPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_set_entry_updates_title_and_id(self) -> None:
        page = ControlPanelChartPage()
        page.set_entry(_value_entry())
        self.assertEqual(page.entry_id, "volts")
        self.assertIn("Rail A", page.title_label.text())
        self.assertIn("(V)", page.title_label.text())
        page.deleteLater()

    def test_default_span_is_five_minutes(self) -> None:
        page = ControlPanelChartPage()
        self.assertEqual(page.window_s, DEFAULT_SPAN_S)
        self.assertEqual(page.chart_view.window_s, float(DEFAULT_SPAN_S))
        page.deleteLater()

    def test_changing_span_updates_chart_window(self) -> None:
        page = ControlPanelChartPage()
        # Pick a span that isn't the default.
        non_default = [s for _label, s in CHART_SPANS if s != DEFAULT_SPAN_S][0]
        for index in range(page.span_combo.count()):
            if page.span_combo.itemData(index) == non_default:
                page.span_combo.setCurrentIndex(index)
                break
        self.assertEqual(page.window_s, non_default)
        self.assertEqual(page.chart_view.window_s, float(non_default))
        page.deleteLater()

    def test_readout_reflects_samples(self) -> None:
        page = ControlPanelChartPage()
        page.set_entry(_value_entry())
        page.set_history(
            [(0.0, 1.0), (1.0, 2.5), (2.0, -0.5)], "", now=2.0
        )
        text = page.readout_label.text()
        self.assertIn("last -0.5", text)
        self.assertIn("min -0.5", text)
        self.assertIn("max 2.5", text)
        self.assertIn("3 sample(s)", text)
        page.deleteLater()

    def test_back_button_emits_signal(self) -> None:
        page = ControlPanelChartPage()
        seen: list[bool] = []
        page.backRequested.connect(lambda: seen.append(True))
        page.back_button.click()
        self.assertEqual(seen, [True])
        page.deleteLater()


class WidgetHexScanTests(unittest.TestCase):
    """The chart module must not hardcode hex colors (NFR-6)."""

    def test_no_hex_in_chart_module(self) -> None:
        hex_literal = re.compile(r"#[0-9a-fA-F]{6}\b")
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ComPort_Zone"
            / "ui"
            / "control_panel_chart.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            hex_literal.findall(source),
            [],
            msg="control_panel_chart.py must take colors from ThemePalette",
        )


if __name__ == "__main__":
    unittest.main()
