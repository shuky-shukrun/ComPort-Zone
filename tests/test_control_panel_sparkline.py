"""Tests for the in-tile sparkline widget (FR-46/FR-47)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.control_panel_sparkline import (
    SPARKLINE_HEIGHT,
    SPARKLINE_WINDOW_S,
    SparklineWidget,
)


class SparklineWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_widget(self) -> SparklineWidget:
        widget = SparklineWidget()
        widget.resize(160, SPARKLINE_HEIGHT)
        return widget

    def test_set_samples_coalesces_repaints(self) -> None:
        widget = self.make_widget()
        samples = [(1.0, 12.0), (2.0, 13.0), (3.0, 12.5)]
        self.assertTrue(widget.set_samples(samples, "#abcdef", now=3.0))
        # Same input -> no visible change.
        self.assertFalse(widget.set_samples(samples, "#abcdef", now=3.0))
        # New sample -> changed; same color/now still bundled into the diff.
        self.assertTrue(
            widget.set_samples(samples + [(4.0, 13.5)], "#abcdef", now=4.0)
        )
        widget.deleteLater()

    def test_has_data_requires_two_points(self) -> None:
        widget = self.make_widget()
        self.assertFalse(widget.has_data())
        widget.set_samples([(1.0, 5.0)], "", now=1.0)
        self.assertFalse(widget.has_data())
        widget.set_samples([(1.0, 5.0), (2.0, 6.0)], "", now=2.0)
        self.assertTrue(widget.has_data())
        widget.deleteLater()

    def test_paint_without_data_is_a_noop(self) -> None:
        widget = self.make_widget()
        widget.show()
        widget.repaint()  # must not raise
        widget.deleteLater()

    def test_grab_renders_when_samples_present(self) -> None:
        widget = self.make_widget()
        widget.apply_theme_palette(THEMES["ComPort Zone Dark"])
        samples = [(float(i), float(i % 5)) for i in range(60)]
        widget.set_samples(samples, "", now=60.0)
        widget.show()
        pixmap = widget.grab()
        self.assertIsInstance(pixmap, QPixmap)
        # Logical height fixed; pixmap height varies with display DPI.
        self.assertEqual(widget.height(), SPARKLINE_HEIGHT)
        self.assertGreater(pixmap.size().width(), 0)
        widget.deleteLater()

    def test_grab_smoke_across_all_themes(self) -> None:
        """Every shipped theme must paint without raising (NFR-6)."""
        samples = [(float(i), 12.0 + (i % 7) * 0.5) for i in range(120)]
        for theme_name, theme in THEMES.items():
            with self.subTest(theme=theme_name):
                widget = self.make_widget()
                widget.apply_theme_palette(theme)
                widget.set_samples(samples, "", now=120.0)
                widget.show()
                widget.grab()
                widget.deleteLater()

    def test_window_slide_drops_old_samples_from_paint_input(self) -> None:
        """``now`` advances the visible window even with no new samples."""
        widget = self.make_widget()
        old = [(0.0, 1.0), (1.0, 2.0)]
        # All samples inside the window: paints something.
        widget.set_samples(old, "#abcdef", now=2.0)
        widget.show()
        widget.grab()
        # Window slid far past the samples: paint becomes a no-op (no
        # exception, no leftover paint state).
        widget.set_samples(old, "#abcdef", now=SPARKLINE_WINDOW_S * 5)
        widget.grab()
        widget.deleteLater()

    def test_handles_invalid_color_gracefully(self) -> None:
        # An accidentally-empty or malformed color from a custom rule
        # must not crash paint — falls back to the theme tx color.
        widget = self.make_widget()
        widget.apply_theme_palette(THEMES["ComPort Zone Dark"])
        widget.set_samples([(0.0, 1.0), (1.0, 2.0)], "not-a-color", now=2.0)
        widget.show()
        widget.grab()
        widget.deleteLater()


class WidgetHexScanTests(unittest.TestCase):
    """The sparkline source must keep colors out of literals (NFR-6)."""

    def test_no_hardcoded_hex_in_sparkline_module(self) -> None:
        hex_literal = re.compile(r"#[0-9a-fA-F]{6}\b")
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "ComPort_Zone"
            / "ui"
            / "control_panel_sparkline.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            hex_literal.findall(source),
            [],
            msg="control_panel_sparkline.py must take colors from ThemePalette",
        )


if __name__ == "__main__":
    unittest.main()
