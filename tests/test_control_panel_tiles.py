"""Tests for control_panel tile widgets, grid geometry, and theming."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ComPort_Zone.control_panel_models import (
    ControlSpec,
    ControlPanelConfig,
    ControlPanelEntry,
    TilePlacement,
)
from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.control_panel_grid import GRID_GUTTER, ControlPanelGridWidget
from ComPort_Zone.ui.control_panel_sparkline import SparklineWidget
from ComPort_Zone.ui.control_panel_tiles import (
    ControlTileWidget,
    LedTileWidget,
    TileRuntime,
    ValueTileWidget,
    create_tile,
    tile_state_color,
)
from ComPort_Zone.ui.stylesheet import build_stylesheet

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "ComPort_Zone"


def make_entry(
    entry_id: str,
    *,
    col: int = 0,
    row: int = 0,
    span_w: int = 1,
    span_h: int = 1,
    kind: str = "value",
    enabled: bool = True,
) -> ControlPanelEntry:
    return ControlPanelEntry(
        id=entry_id,
        label=entry_id.upper(),
        command=f"READ:{entry_id}?",
        unit="V",
        enabled=enabled,
        tile=TilePlacement(col=col, row=row, span_w=span_w, span_h=span_h, kind=kind),
    )


def make_config(*entries: ControlPanelEntry, columns: int = 4) -> ControlPanelConfig:
    return ControlPanelConfig(name="Test", columns=columns, entries=list(entries))


class TileWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_factory_picks_widget_kind(self) -> None:
        value_tile = create_tile(make_entry("a", kind="value"))
        led_tile = create_tile(make_entry("b", kind="led"))
        control_tile = create_tile(make_entry("c", kind="control"))
        self.assertIsInstance(value_tile, ValueTileWidget)
        self.assertIsInstance(led_tile, LedTileWidget)
        self.assertIsInstance(control_tile, ControlTileWidget)
        value_tile.deleteLater()
        led_tile.deleteLater()
        control_tile.deleteLater()

    def test_value_tile_renders_runtime(self) -> None:
        tile = ValueTileWidget(make_entry("a"))
        runtime = TileRuntime(
            entry_id="a",
            value_text="13.2 V",
            state="warn",
            timestamp_text="12:00:01",
            tooltip="raw: 13.2",
        )
        changed = tile.update_runtime(runtime)
        self.assertTrue(changed)
        self.assertEqual(tile.value_label.text(), "13.2 V")
        self.assertEqual(tile.value_label.property("tileState"), "warn")
        self.assertEqual(tile.property("tileState"), "warn")
        self.assertEqual(tile.timestamp_label.text(), "12:00:01")
        self.assertEqual(tile.toolTip(), "raw: 13.2")
        tile.deleteLater()

    def test_value_tile_update_coalesces(self) -> None:
        tile = ValueTileWidget(make_entry("a"))
        runtime = TileRuntime(entry_id="a", value_text="5 V", state="ok", timestamp_text="t")
        self.assertTrue(tile.update_runtime(runtime))
        self.assertFalse(tile.update_runtime(runtime))
        tile.deleteLater()

    def test_led_tile_caption_and_lamp(self) -> None:
        tile = LedTileWidget(make_entry("a", kind="led"))
        self.assertTrue(
            tile.update_runtime(TileRuntime(entry_id="a", state="fail", state_caption="TRIPPED"))
        )
        self.assertEqual(tile.caption_label.text(), "TRIPPED")
        self.assertEqual(tile.lamp.property("tileState"), "fail")
        tile.update_runtime(TileRuntime(entry_id="a", state="stale"))
        self.assertEqual(tile.caption_label.text(), "STALE")
        tile.deleteLater()

    def test_edit_mode_property(self) -> None:
        tile = ValueTileWidget(make_entry("a"))
        tile.set_edit_mode(True)
        self.assertEqual(tile.property("editMode"), "true")
        tile.set_edit_mode(False)
        self.assertEqual(tile.property("editMode"), "false")
        tile.deleteLater()

    def test_disabled_entry_property(self) -> None:
        tile = ValueTileWidget(make_entry("a", enabled=False))
        self.assertEqual(tile.property("entryEnabled"), "false")
        enabled_entry = make_entry("a")
        tile.update_entry(enabled_entry)
        self.assertEqual(tile.property("entryEnabled"), "true")
        tile.deleteLater()

    def test_value_tile_custom_color_set_and_cleared(self) -> None:
        # FR-62: a rule's custom color overrides the theme state color via
        # a scoped inline style, and clears back to the QSS cascade.
        tile = ValueTileWidget(make_entry("a"))
        colored = TileRuntime(entry_id="a", value_text="5 V", state="ok", color="#12ab34")
        self.assertTrue(tile.update_runtime(colored))
        self.assertIn("#12ab34", tile.value_label.styleSheet())

        plain = TileRuntime(entry_id="a", value_text="5 V", state="ok")
        self.assertTrue(tile.update_runtime(plain))
        self.assertEqual(tile.value_label.styleSheet(), "")
        tile.deleteLater()

    def test_value_tile_hosts_sparkline_for_numeric_entries(self) -> None:
        entry = make_entry("a")  # default parse value_type is "number"
        from ComPort_Zone.control_panel_models import ParseRule

        entry.parse = ParseRule(kind="line", value_type="number")
        tile = ValueTileWidget(entry)
        self.assertIsInstance(tile.sparkline, SparklineWidget)
        self.assertTrue(tile.sparkline.isVisibleTo(tile))
        tile.deleteLater()

    def test_value_tile_hides_sparkline_for_text_entries(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="text")
        tile = ValueTileWidget(entry)
        self.assertFalse(tile.sparkline.isVisibleTo(tile))
        tile.deleteLater()

    def test_value_tile_hides_sparkline_when_show_sparkline_off(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="number")
        entry.show_sparkline = False
        tile = ValueTileWidget(entry)
        self.assertFalse(tile.sparkline.isVisibleTo(tile))
        # Re-enabling via update_entry shows it again.
        entry.show_sparkline = True
        tile.update_entry(entry)
        self.assertTrue(tile.sparkline.isVisibleTo(tile))
        tile.deleteLater()

    def test_set_history_ignored_when_sparkline_hidden(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="number")
        entry.show_sparkline = False
        tile = ValueTileWidget(entry)
        changed = tile.set_history([(0.0, 1.0), (1.0, 2.0)], "", now=1.0)
        self.assertFalse(changed)
        self.assertFalse(tile.sparkline.has_data())
        tile.deleteLater()

    def test_value_tile_double_click_requests_chart(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="number")
        tile = ValueTileWidget(entry)
        seen: list[str] = []
        tile.chartRequested.connect(seen.append)
        position = QPointF(20, 20)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            position,
            position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        tile.mouseDoubleClickEvent(event)
        self.assertEqual(seen, ["a"])
        tile.deleteLater()

    def test_value_tile_double_click_inert_in_edit_mode(self) -> None:
        # Drag-to-place is double-click adjacent; opening the chart from
        # under an active edit-mode would surprise the user (FR-48 says
        # open chart, but edit mode owns the gesture).
        from ComPort_Zone.control_panel_models import ParseRule
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="number")
        tile = ValueTileWidget(entry)
        tile.set_edit_mode(True)
        seen: list[str] = []
        tile.chartRequested.connect(seen.append)
        position = QPointF(20, 20)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            position,
            position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        tile.mouseDoubleClickEvent(event)
        self.assertEqual(seen, [])
        tile.deleteLater()

    def test_value_tile_double_click_ignored_when_text(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="text")
        tile = ValueTileWidget(entry)
        seen: list[str] = []
        tile.chartRequested.connect(seen.append)
        position = QPointF(20, 20)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            position,
            position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        tile.mouseDoubleClickEvent(event)
        self.assertEqual(seen, [])
        tile.deleteLater()

    def test_set_history_feeds_visible_sparkline(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule

        entry = make_entry("a")
        entry.parse = ParseRule(kind="line", value_type="number")
        tile = ValueTileWidget(entry)
        self.assertTrue(
            tile.set_history([(0.0, 1.0), (1.0, 2.0)], "#abcdef", now=1.0)
        )
        self.assertTrue(tile.sparkline.has_data())
        tile.deleteLater()

    def test_led_tile_custom_color_set_and_cleared(self) -> None:
        tile = LedTileWidget(make_entry("a", kind="led"))
        colored = TileRuntime(entry_id="a", state="warn", color="#ab1234")
        tile.update_runtime(colored)
        self.assertIn("#ab1234", tile.lamp.styleSheet())
        self.assertIn("#ab1234", tile.caption_label.styleSheet())

        tile.update_runtime(TileRuntime(entry_id="a", state="warn"))
        self.assertEqual(tile.lamp.styleSheet(), "")
        self.assertEqual(tile.caption_label.styleSheet(), "")
        tile.deleteLater()


class GridGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_grid(self, config: ControlPanelConfig, width: int = 800) -> ControlPanelGridWidget:
        grid = ControlPanelGridWidget()
        grid.resize(width, 600)
        grid.set_config(config)
        grid.relayout()
        return grid

    def test_tiles_created_for_config(self) -> None:
        grid = self.make_grid(make_config(make_entry("a"), make_entry("b", col=1)))
        self.assertIsNotNone(grid.tile("a"))
        self.assertIsNotNone(grid.tile("b"))
        self.assertEqual(len(grid.tiles()), 2)
        grid.deleteLater()

    def test_columns_position_tiles_left_to_right(self) -> None:
        grid = self.make_grid(make_config(make_entry("a", col=0), make_entry("b", col=1)))
        tile_a = grid.tile("a")
        tile_b = grid.tile("b")
        assert tile_a is not None and tile_b is not None
        self.assertEqual(tile_a.y(), tile_b.y())
        self.assertGreater(tile_b.x(), tile_a.x())
        self.assertEqual(tile_a.width(), tile_b.width())
        grid.deleteLater()

    def test_wide_span_doubles_width_plus_gutter(self) -> None:
        grid = self.make_grid(
            make_config(make_entry("small", col=0), make_entry("wide", col=0, row=1, span_w=2))
        )
        small = grid.tile("small")
        wide = grid.tile("wide")
        assert small is not None and wide is not None
        self.assertEqual(wide.width(), 2 * small.width() + GRID_GUTTER)
        grid.deleteLater()

    def test_tall_span_doubles_height_plus_gutter(self) -> None:
        grid = self.make_grid(
            make_config(make_entry("small", col=0), make_entry("tall", col=1, span_h=2))
        )
        small = grid.tile("small")
        tall = grid.tile("tall")
        assert small is not None and tall is not None
        self.assertEqual(tall.height(), 2 * small.height() + GRID_GUTTER)
        grid.deleteLater()

    def test_2x2_span_geometry(self) -> None:
        grid = self.make_grid(
            make_config(make_entry("small", col=3), make_entry("big", col=0, span_w=2, span_h=2))
        )
        small = grid.tile("small")
        big = grid.tile("big")
        assert small is not None and big is not None
        self.assertEqual(big.width(), 2 * small.width() + GRID_GUTTER)
        self.assertEqual(big.height(), 2 * small.height() + GRID_GUTTER)
        grid.deleteLater()

    def test_set_config_removes_orphan_tiles(self) -> None:
        config = make_config(make_entry("a"), make_entry("b", col=1))
        grid = self.make_grid(config)
        config.entries = [entry for entry in config.entries if entry.id == "a"]
        grid.set_config(config)
        self.assertIsNone(grid.tile("b"))
        self.assertIsNotNone(grid.tile("a"))
        grid.deleteLater()

    def test_set_config_recreates_tile_on_kind_change(self) -> None:
        config = make_config(make_entry("a", kind="value"))
        grid = self.make_grid(config)
        self.assertIsInstance(grid.tile("a"), ValueTileWidget)
        config.entries[0].tile.kind = "led"
        grid.set_config(config)
        self.assertIsInstance(grid.tile("a"), LedTileWidget)
        grid.deleteLater()

    def test_drop_moves_tile_and_emits_layout_changed(self) -> None:
        config = make_config(make_entry("a", col=0), make_entry("b", col=1))
        grid = self.make_grid(config)
        changes: list[bool] = []
        grid.layoutChanged.connect(lambda: changes.append(True))
        grid._handle_tile_drop("a", 1, 0)
        self.assertEqual(changes, [True])
        moved = config.entry_by_id("a")
        displaced = config.entry_by_id("b")
        assert moved is not None and displaced is not None
        self.assertEqual((moved.tile.col, moved.tile.row), (1, 0))
        self.assertEqual((displaced.tile.col, displaced.tile.row), (1, 1))
        grid.deleteLater()

    def test_span_request_updates_config(self) -> None:
        config = make_config(make_entry("a"))
        grid = self.make_grid(config)
        changes: list[bool] = []
        grid.layoutChanged.connect(lambda: changes.append(True))
        grid._handle_span_request("a", 2, 2)
        self.assertEqual(changes, [True])
        entry = config.entry_by_id("a")
        assert entry is not None
        self.assertEqual((entry.tile.span_w, entry.tile.span_h), (2, 2))
        grid.deleteLater()

    def test_cell_at_clamps_for_span(self) -> None:
        grid = self.make_grid(make_config(make_entry("a"), columns=4), width=800)
        far_right_col, _row = grid.cell_at(795, 10, span_w=2)
        self.assertEqual(far_right_col, 2)
        negative_col, negative_row = grid.cell_at(-50, -50)
        self.assertEqual((negative_col, negative_row), (0, 0))
        grid.deleteLater()

    def test_minimum_height_tracks_rows(self) -> None:
        single = self.make_grid(make_config(make_entry("a")))
        double = self.make_grid(make_config(make_entry("a"), make_entry("b", row=1)))
        self.assertGreater(double.minimumHeight(), single.minimumHeight())
        single.deleteLater()
        double.deleteLater()


class ThemingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_state_colors_distinct_in_every_theme(self) -> None:
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                ok = tile_state_color("ok", theme)
                warn = tile_state_color("warn", theme)
                fail = tile_state_color("fail", theme)
                stale = tile_state_color("stale", theme)
                self.assertEqual(len({ok, warn, fail, stale}), 4)
                self.assertEqual(tile_state_color("error", theme), fail)
                self.assertEqual(tile_state_color("neutral", theme), stale)

    def test_stylesheet_builds_with_control_panel_blocks_for_every_theme(self) -> None:
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                qss = build_stylesheet(theme)
                self.assertIn("QFrame#controlPanelTile", qss)
                self.assertIn('QLabel#tileLamp[tileState="ok"]', qss)
                self.assertIn('QLabel#controlPanelBindChip[state="polling"]', qss)

    def test_no_hardcoded_hex_colors_in_control_panel_widgets(self) -> None:
        hex_literal = re.compile(r"#[0-9a-fA-F]{6}\b")
        for module in ("ui/control_panel_tiles.py", "ui/control_panel_grid.py"):
            source = (SRC_ROOT / module).read_text(encoding="utf-8")
            self.assertEqual(
                hex_literal.findall(source),
                [],
                msg=f"{module} must take colors from ThemePalette/QSS only",
            )


if __name__ == "__main__":
    unittest.main()
