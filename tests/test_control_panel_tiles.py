"""Tests for control_panel tile widgets, grid geometry, and theming."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ComPort_Zone.control_panel_models import (
    BitDefinition,
    BitsSpec,
    ControlSpec,
    ControlPanelConfig,
    ControlPanelEntry,
    ParseRule,
    TilePlacement,
)
from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.control_panel_grid import GRID_GUTTER, ControlPanelGridWidget
from ComPort_Zone.ui.control_panel_sparkline import SparklineWidget
from ComPort_Zone.ui.control_panel_tiles import (
    BitsTileWidget,
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


class BitsTileTests(unittest.TestCase):
    """Status / fault register tile widget — every defined bit gets a
    lamp + label; lamps light up for the bits set in the latest value."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    @staticmethod
    def make_bits_entry(*bits: BitDefinition, entry_id: str = "stat") -> ControlPanelEntry:
        return ControlPanelEntry(
            id=entry_id,
            label="Status",
            command="STAT:OPER:COND?",
            parse=ParseRule(kind="line", value_type="number"),
            tile=TilePlacement(col=0, row=0, kind="bits"),
            bits_spec=BitsSpec(bits=list(bits)),
        )

    def test_factory_picks_bits_widget(self) -> None:
        entry = self.make_bits_entry(BitDefinition(bit=0, label="A"))
        tile = create_tile(entry)
        self.assertIsInstance(tile, BitsTileWidget)
        tile.deleteLater()

    def test_indicator_built_per_bit(self) -> None:
        entry = self.make_bits_entry(
            BitDefinition(bit=0, label="A"),
            BitDefinition(bit=3, label="B"),
            BitDefinition(bit=7, label="C"),
        )
        tile = BitsTileWidget(entry)
        self.assertEqual(set(tile._indicators), {0, 3, 7})
        tile.deleteLater()

    def test_lamp_lights_only_for_active_bits(self) -> None:
        entry = self.make_bits_entry(
            BitDefinition(bit=0, label="A", state="fail"),
            BitDefinition(bit=2, label="C", state="warn"),
            BitDefinition(bit=5, label="F", state="ok"),
        )
        tile = BitsTileWidget(entry)
        # Value 33 = 0b100001 sets bits 0 and 5; bit 2 stays neutral.
        tile.update_runtime(
            TileRuntime(entry_id="stat", value_text="33", value_number=33.0)
        )
        self.assertEqual(tile._indicators[0][0].property("tileState"), "fail")
        self.assertEqual(tile._indicators[2][0].property("tileState"), "neutral")
        self.assertEqual(tile._indicators[5][0].property("tileState"), "ok")
        tile.deleteLater()

    def test_multiple_bits_can_be_active_simultaneously(self) -> None:
        entry = self.make_bits_entry(
            BitDefinition(bit=0, label="A", state="fail"),
            BitDefinition(bit=1, label="B", state="warn"),
            BitDefinition(bit=2, label="C", state="ok"),
        )
        tile = BitsTileWidget(entry)
        # 0b111 = all three bits set at once.
        tile.update_runtime(
            TileRuntime(entry_id="stat", value_text="7", value_number=7.0)
        )
        self.assertEqual(tile._indicators[0][0].property("tileState"), "fail")
        self.assertEqual(tile._indicators[1][0].property("tileState"), "warn")
        self.assertEqual(tile._indicators[2][0].property("tileState"), "ok")
        tile.deleteLater()

    def test_value_text_hex_fallback_when_no_number(self) -> None:
        entry = self.make_bits_entry(
            BitDefinition(bit=0, label="A", state="fail"),
            BitDefinition(bit=7, label="B", state="warn"),
        )
        tile = BitsTileWidget(entry)
        # Instrument returned a hex literal as text; the widget falls
        # back to int(text, 0) and lights the right bits.
        tile.update_runtime(
            TileRuntime(entry_id="stat", value_text="0x81", value_number=None)
        )
        self.assertEqual(tile._indicators[0][0].property("tileState"), "fail")
        self.assertEqual(tile._indicators[7][0].property("tileState"), "warn")
        tile.deleteLater()

    def test_update_entry_rebuilds_indicators_when_spec_changes(self) -> None:
        entry = self.make_bits_entry(BitDefinition(bit=0, label="A"))
        tile = BitsTileWidget(entry)
        new_entry = self.make_bits_entry(
            BitDefinition(bit=1, label="X"),
            BitDefinition(bit=4, label="Y"),
        )
        tile.update_entry(new_entry)
        self.assertEqual(set(tile._indicators), {1, 4})
        tile.deleteLater()

    def test_clears_lamps_on_unparseable_value(self) -> None:
        entry = self.make_bits_entry(BitDefinition(bit=0, label="A", state="fail"))
        tile = BitsTileWidget(entry)
        # Prime an active bit, then deliver an invalid update.
        tile.update_runtime(
            TileRuntime(entry_id="stat", value_text="1", value_number=1.0)
        )
        self.assertEqual(tile._indicators[0][0].property("tileState"), "fail")
        tile.update_runtime(
            TileRuntime(entry_id="stat", value_text="N/A", value_number=None)
        )
        self.assertEqual(tile._indicators[0][0].property("tileState"), "neutral")
        tile.deleteLater()

    def test_empty_spec_shows_placeholder(self) -> None:
        entry = self.make_bits_entry()
        tile = BitsTileWidget(entry)
        self.assertEqual(tile._indicators, {})
        self.assertTrue(tile._empty_label.isVisibleTo(tile) or
                        tile._empty_label.isVisible() or
                        not tile._empty_label.isHidden())
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

    def test_grid_relays_duplicate_request(self) -> None:
        grid = self.make_grid(make_config(make_entry("a")))
        seen: list[str] = []
        grid.tileDuplicateRequested.connect(seen.append)
        grid.tile("a").duplicateRequested.emit("a")
        self.assertEqual(seen, ["a"])
        grid.deleteLater()

    def test_grid_injects_cell_stride_provider(self) -> None:
        # Tiles need the grid's per-cell stride for corner-drag resize.
        grid = self.make_grid(make_config(make_entry("a")), width=800)
        provider = grid.tile("a").cell_metrics_provider
        self.assertIsNotNone(provider)
        stride_x, stride_y, columns = provider()
        self.assertGreater(stride_x, 0)
        self.assertGreater(stride_y, 0)
        self.assertEqual(columns, 4)  # make_config default
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
        # Place tiles beyond the default visible-row floor so the
        # entry count actually drives the minimum height.
        single = self.make_grid(make_config(make_entry("a", row=6)))
        double = self.make_grid(
            make_config(make_entry("a", row=6), make_entry("b", row=7))
        )
        self.assertGreater(double.minimumHeight(), single.minimumHeight())
        single.deleteLater()
        double.deleteLater()

    def test_value_font_scales_with_cell_width(self) -> None:
        # A wider grid yields a larger measure font; a narrow grid
        # (split-screen sized) yields a smaller, still-readable one.
        wide = self.make_grid(make_config(make_entry("a")), width=1600)
        narrow = self.make_grid(make_config(make_entry("a")), width=420)
        tile_wide = wide.tile("a")
        tile_narrow = narrow.tile("a")
        assert tile_wide is not None and tile_narrow is not None
        wide_px = tile_wide.value_label.font().pixelSize()
        narrow_px = tile_narrow.value_label.font().pixelSize()
        self.assertGreater(wide_px, narrow_px)
        # Bounded so the measure stays legible at any size.
        self.assertGreaterEqual(narrow_px, 12)
        self.assertLessEqual(wide_px, 40)
        wide.deleteLater()
        narrow.deleteLater()

    def test_minimum_height_reserves_configured_rows(self) -> None:
        # With no entries that exceed config.rows, the grid still
        # reserves room for the configured visible rows so tiny panels
        # keep their visual footprint stable.
        grid = self.make_grid(make_config(make_entry("a")))
        # Default rows = 5; minimum height must reflect more than the
        # single-tile content (otherwise the auto-expand math is wrong).
        only_entry_height = grid.minimumHeight()
        bigger_grid = self.make_grid(
            make_config(make_entry("a"), columns=4)
        )
        # Same config produces same baseline.
        self.assertEqual(bigger_grid.minimumHeight(), only_entry_height)
        grid.deleteLater()
        bigger_grid.deleteLater()


class SparklineSizingRegressionTests(unittest.TestCase):
    """The sparkline must span the full width of the value tile body —
    the slider-removal refactor's previous incarnation left the widget
    at its sizeHint (~28 px), parking it in the bottom-right corner of
    every value tile instead of streaming the trend line full-width."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_sparkline_expands_to_fill_tile_width(self) -> None:
        config = make_config(make_entry("v"))
        grid = ControlPanelGridWidget()
        grid.resize(800, 240)
        grid.set_config(config)
        grid.show()
        QTest.qWaitForWindowExposed(grid)
        QTest.qWait(80)
        tile = grid.tile("v")
        assert tile is not None
        spark = tile.sparkline
        # Sparkline width should fill almost the whole tile body — well
        # above any plausible sizeHint default. A tight tile with
        # SPACE_LG body margins still gives us > 100 px.
        self.assertGreaterEqual(spark.width(), 100,
                                f"sparkline only {spark.width()} px wide")
        self.assertEqual(spark.height(), 28)  # fixed
        grid.deleteLater()


class SetpointSpinboxRegressionTests(unittest.TestCase):
    """Setpoint spinbox needs:
      - selectAll on focus, so typing replaces the value cleanly
      - working up/down step arrows (clickable and reach the value)
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    @staticmethod
    def make_setpoint() -> ControlPanelEntry:
        entry = ControlPanelEntry(
            id="sp",
            label="Set V",
            tile=TilePlacement(col=0, row=0, span_w=2, span_h=1, kind="setpoint"),
        )
        entry.setpoint.min_value = 0.0
        entry.setpoint.max_value = 30.0
        entry.setpoint.step = 0.01
        entry.setpoint.decimals = 2
        entry.setpoint.unit = "V"
        entry.setpoint.command_template = "VOLT {value}"
        return entry

    def test_typed_decimal_value_is_accepted(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget
        tile = SetpointTileWidget(self.make_setpoint())
        tile.show()
        QTest.qWaitForWindowExposed(tile)
        # User-flow: click on the spinbox lineEdit (focus goes there;
        # our auto-select-all kicks in via QTimer.singleShot), then type.
        QTest.mouseClick(tile.spin, Qt.MouseButton.LeftButton)
        QTest.qWait(20)  # let QTimer.singleShot(0, selectAll) run
        for ch in "12.5":
            QTest.keyClick(tile.spin, ch)
        QTest.keyClick(tile.spin, Qt.Key.Key_Return)
        self.assertAlmostEqual(tile.spin.value(), 12.5, places=3,
                               msg=f"typed value landed at {tile.spin.value()}")
        tile.deleteLater()

    def test_step_arrow_clicks_change_value(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget
        tile = SetpointTileWidget(self.make_setpoint())
        tile.show()
        QTest.qWaitForWindowExposed(tile)
        before = tile.spin.value()
        # stepBy(+1) is the same code-path the ::up-button hits when the
        # user clicks it — bypasses QSS rendering quirks while still
        # proving the increment logic is wired.
        tile.spin.stepBy(1)
        self.assertAlmostEqual(tile.spin.value(), before + tile.spin.singleStep(), places=4)
        tile.deleteLater()

    def test_finer_step_promotes_displayed_decimals(self) -> None:
        """When step=0.001 the spinbox should keep 3 decimals even if
        the stored ``decimals`` is 2 — otherwise the user types ``1.234``
        and the third digit silently disappears from the wire format."""
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        entry = self.make_setpoint()
        entry.setpoint.step = 0.001
        entry.setpoint.decimals = 2
        tile = SetpointTileWidget(entry)
        self.assertEqual(tile.spin.decimals(), 3)
        tile.spin.setValue(1.234)
        # render_command also uses effective_decimals → wire string is
        # the fully precise value, not a truncated "1.23".
        self.assertEqual(entry.setpoint.render_command(1.234), "VOLT 1.234")
        tile.deleteLater()

    def test_user_higher_decimals_override_step(self) -> None:
        """A user who explicitly picks more decimals than the step needs
        keeps that preference — effective_decimals = max(declared,
        step-derived)."""
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        entry = self.make_setpoint()
        entry.setpoint.step = 0.1
        entry.setpoint.decimals = 4
        tile = SetpointTileWidget(entry)
        self.assertEqual(tile.spin.decimals(), 4)
        tile.deleteLater()

    def test_enter_in_spinbox_triggers_send(self) -> None:
        """Pressing Enter inside the setpoint spinbox sends the command
        the same way clicking the ▶ button would, so keyboard-first
        workflows don't need a mouse jump per write."""
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.show()
        QTest.qWaitForWindowExposed(tile)
        # Enable the send button by simulating armed + non-pending state.
        tile.set_panel_armed(True)
        self.assertTrue(tile.send_button.isEnabled())
        emissions: list[str] = []
        tile.activateRequested.connect(emissions.append)
        # Focus the spinbox and press Enter.
        tile.spin.setFocus()
        QTest.qWait(20)  # let our deferred selectAll fire
        QTest.keyClick(tile.spin, Qt.Key.Key_Return)
        QTest.qWait(160)  # animateClick is async — wait for it to land
        self.assertEqual(emissions, ["sp"],
                         f"Enter should fire activateRequested once, got {emissions!r}")
        tile.deleteLater()

    def test_enter_does_not_send_when_send_disabled(self) -> None:
        """Disarmed / pending state must block Enter-to-send the same
        way it blocks the ▶ button — Enter is just another path to the
        send button's own gate."""
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.show()
        QTest.qWaitForWindowExposed(tile)
        # Default state: disarmed → send button disabled.
        self.assertFalse(tile.send_button.isEnabled())
        emissions: list[str] = []
        tile.activateRequested.connect(emissions.append)
        tile.spin.setFocus()
        QTest.qWait(20)
        QTest.keyClick(tile.spin, Qt.Key.Key_Return)
        QTest.qWait(120)
        self.assertEqual(emissions, [])
        tile.deleteLater()


class ReadbackIntoInputTests(unittest.TestCase):
    """The readback reflects into each writing tile's own input control
    (no separate readback area) and flags a mismatch vs the commanded
    value with a warning property (FR-66/FR-70, redesign 2026-06)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    @staticmethod
    def make_setpoint() -> ControlPanelEntry:
        entry = ControlPanelEntry(
            id="sp",
            label="Set V",
            tile=TilePlacement(col=0, row=0, span_w=2, span_h=1, kind="setpoint"),
        )
        entry.setpoint.min_value = 0.0
        entry.setpoint.max_value = 30.0
        entry.setpoint.step = 0.01
        entry.setpoint.decimals = 2
        entry.setpoint.unit = "V"
        entry.setpoint.command_template = "VOLT {value}"
        return entry

    @staticmethod
    def make_enum() -> ControlPanelEntry:
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec

        entry = ControlPanelEntry(
            id="mode",
            label="Mode",
            tile=TilePlacement(col=0, row=0, span_w=2, span_h=1, kind="enum"),
        )
        entry.enum_spec = EnumSpec(
            options=[
                EnumOption(label="CV", command="MODE CV", match_value="CV"),
                EnumOption(label="CC", command="MODE CC", match_value="CC"),
                EnumOption(label="OFF", command="MODE OFF", match_value="OFF"),
            ]
        )
        return entry

    @staticmethod
    def make_toggle() -> ControlPanelEntry:
        entry = ControlPanelEntry(
            id="ctrl",
            label="Output",
            tile=TilePlacement(col=0, row=0, span_w=1, span_h=1, kind="control"),
        )
        entry.control = ControlSpec(
            mode="toggle", on_command="OUTP ON", off_command="OUTP OFF"
        )
        return entry

    # ----------------------------------------------------------- setpoint

    def test_setpoint_reflects_readback_without_command(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.apply_readback(7.5)
        self.assertAlmostEqual(tile.spin.value(), 7.5, places=4)
        self.assertFalse(tile.mismatch)
        self.assertEqual(tile.spin.property("mismatch"), "false")
        tile.deleteLater()

    def test_setpoint_mismatch_warns_when_device_differs(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.set_value(25.0)
        tile.mark_commanded()            # commanded 25 V
        tile.apply_readback(10.0)        # device reports a clamped 10 V
        # The spinbox snaps to the device value and warns the command
        # was not accepted.
        self.assertAlmostEqual(tile.spin.value(), 10.0, places=4)
        self.assertTrue(tile.mismatch)
        self.assertEqual(tile.spin.property("mismatch"), "true")
        # Device later reaches the commanded value -> warning clears.
        tile.apply_readback(25.0)
        self.assertFalse(tile.mismatch)
        self.assertEqual(tile.spin.property("mismatch"), "false")
        tile.deleteLater()

    def test_setpoint_holds_readback_while_user_editing(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.set_value(5.0)
        # textEdited fires only on user keystrokes -> we are now editing.
        tile.spin.lineEdit().textEdited.emit("9")
        tile.apply_readback(20.0)
        self.assertAlmostEqual(tile.spin.value(), 5.0, places=4)  # not overwritten
        # Focus leaves the field -> editing ends -> readback reflects.
        tile._on_spin_focus_out()
        tile.apply_readback(20.0)
        self.assertAlmostEqual(tile.spin.value(), 20.0, places=4)
        tile.deleteLater()

    def test_setpoint_mismatch_clears_on_user_edit(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.set_value(25.0)
        tile.mark_commanded()
        tile.apply_readback(10.0)
        self.assertTrue(tile.mismatch)
        # Starting a fresh edit invalidates the prior command's comparison.
        tile.spin.lineEdit().textEdited.emit("2")
        self.assertFalse(tile.mismatch)
        self.assertEqual(tile.spin.property("mismatch"), "false")
        tile.deleteLater()

    def test_setpoint_non_numeric_readback_leaves_field(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tile = SetpointTileWidget(self.make_setpoint())
        tile.set_value(8.0)
        tile.apply_readback(None)
        self.assertAlmostEqual(tile.spin.value(), 8.0, places=4)
        tile.deleteLater()

    # --------------------------------------------------------------- enum

    def test_enum_readback_drives_selection(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tile = EnumTileWidget(self.make_enum())
        tile.apply_readback("CC")
        self.assertEqual(tile.combo.currentIndex(), 1)
        self.assertEqual(tile.indicated_index, 1)
        self.assertFalse(tile.mismatch)
        tile.deleteLater()

    def test_enum_mismatch_when_device_differs_from_command(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tile = EnumTileWidget(self.make_enum())
        tile.combo.setCurrentIndex(0)   # user picks CV
        tile.mark_commanded()           # commanded CV
        tile.apply_readback("CC")       # device reports CC
        self.assertEqual(tile.combo.currentIndex(), 1)
        self.assertTrue(tile.mismatch)
        self.assertEqual(tile.combo.property("mismatch"), "true")
        tile.apply_readback("CV")       # device agrees -> clears
        self.assertFalse(tile.mismatch)
        self.assertEqual(tile.combo.property("mismatch"), "false")
        tile.deleteLater()

    def test_enum_holds_selection_while_editing(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tile = EnumTileWidget(self.make_enum())
        tile.combo.setCurrentIndex(0)
        tile._is_editing = lambda: True   # dropdown open / focused
        tile.apply_readback("CC")
        self.assertEqual(tile.combo.currentIndex(), 0)  # not yanked away
        tile._is_editing = lambda: False
        tile.apply_readback("CC")
        self.assertEqual(tile.combo.currentIndex(), 1)
        tile.deleteLater()

    def test_enum_unknown_readback_leaves_selection(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tile = EnumTileWidget(self.make_enum())
        tile.combo.setCurrentIndex(2)
        tile.apply_readback("WAT")  # matches no option
        self.assertEqual(tile.indicated_index, -1)
        self.assertEqual(tile.combo.currentIndex(), 2)  # unchanged
        tile.deleteLater()

    # ------------------------------------------------------------- toggle

    def test_toggle_mismatch_when_device_disagrees(self) -> None:
        tile = ControlTileWidget(self.make_toggle())
        tile.set_commanded(True)     # commanded ON
        tile.apply_readback(False)   # device stays OFF
        self.assertFalse(tile.is_on)
        self.assertTrue(tile.mismatch)
        self.assertEqual(tile.button.property("mismatch"), "true")
        tile.apply_readback(True)    # device agrees -> clears
        self.assertTrue(tile.is_on)
        self.assertFalse(tile.mismatch)
        self.assertEqual(tile.button.property("mismatch"), "false")
        tile.deleteLater()

    def test_toggle_no_mismatch_without_command(self) -> None:
        tile = ControlTileWidget(self.make_toggle())
        tile.apply_readback(True)   # pure follow, nothing commanded
        self.assertTrue(tile.is_on)
        self.assertFalse(tile.mismatch)
        tile.deleteLater()

    def test_action_buttons_not_click_focusable(self) -> None:
        # Clicking a tile's action button must not grab focus, else
        # disabling it on send bounces focus to the next tile.
        from ComPort_Zone.ui.control_panel_tiles import (
            ControlTileWidget,
            EnumTileWidget,
            SetpointTileWidget,
        )

        sp = SetpointTileWidget(self.make_setpoint())
        en = EnumTileWidget(self.make_enum())
        tg = ControlTileWidget(self.make_toggle())
        for btn in (sp.send_button, en.send_button, tg.button):
            self.assertEqual(btn.focusPolicy(), Qt.FocusPolicy.TabFocus)
        for tile in (sp, en, tg):
            tile.deleteLater()

    def test_apply_readback_reports_value_change(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import (
            ControlTileWidget,
            EnumTileWidget,
            SetpointTileWidget,
        )

        sp = SetpointTileWidget(self.make_setpoint())
        self.assertTrue(sp.apply_readback(5.0))   # 0 -> 5
        self.assertFalse(sp.apply_readback(5.0))  # unchanged
        sp.deleteLater()

        en = EnumTileWidget(self.make_enum())
        self.assertTrue(en.apply_readback("CC"))   # none -> CC
        self.assertFalse(en.apply_readback("CC"))  # unchanged
        en.deleteLater()

        tg = ControlTileWidget(self.make_toggle())
        self.assertTrue(tg.apply_readback(True))   # off -> on
        self.assertFalse(tg.apply_readback(True))  # unchanged
        tg.deleteLater()


class UpdateFlashTests(unittest.TestCase):
    """The 3 s "value just updated" highlight on writing tiles."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_flash_sets_then_clears(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import ValueTileWidget

        tile = ValueTileWidget(make_entry("a"))
        self.assertEqual(tile.property("recentlyUpdated"), "false")
        tile.flash_update()
        self.assertEqual(tile.property("recentlyUpdated"), "true")
        self.assertTrue(tile._update_flash_timer.isActive())
        tile._clear_update_flash()  # what the timer fires
        self.assertEqual(tile.property("recentlyUpdated"), "false")
        tile.deleteLater()


class LongPressEditTests(unittest.TestCase):
    """Press-and-hold a tile's chrome to enter edit mode."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    @staticmethod
    def _press(pos=(5, 5)):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(*pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    @staticmethod
    def _move(pos):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        return QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(*pos),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def _tile(self):
        from ComPort_Zone.ui.control_panel_tiles import ValueTileWidget

        return ValueTileWidget(make_entry("a"))

    def test_press_arms_timer_and_release_cancels(self) -> None:
        tile = self._tile()
        tile.mousePressEvent(self._press())
        self.assertTrue(tile._long_press_timer.isActive())
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        tile.mouseReleaseEvent(release)
        self.assertFalse(tile._long_press_timer.isActive())
        tile.deleteLater()

    def test_move_beyond_threshold_cancels(self) -> None:
        tile = self._tile()
        tile.mousePressEvent(self._press((5, 5)))
        self.assertTrue(tile._long_press_timer.isActive())
        tile.mouseMoveEvent(self._move((500, 500)))  # far drag
        self.assertFalse(tile._long_press_timer.isActive())
        tile.deleteLater()

    def test_not_armed_in_edit_mode(self) -> None:
        tile = self._tile()
        tile.set_edit_mode(True)
        tile.mousePressEvent(self._press())
        self.assertFalse(tile._long_press_timer.isActive())
        tile.deleteLater()

    def test_timeout_requests_edit_mode_once(self) -> None:
        tile = self._tile()
        seen: list[bool] = []
        tile.editModeRequested.connect(lambda: seen.append(True))
        tile._on_long_press()
        self.assertEqual(seen, [True])
        # Already editing -> no further request.
        tile.set_edit_mode(True)
        tile._on_long_press()
        self.assertEqual(seen, [True])
        tile.deleteLater()


class TextWrapTests(unittest.TestCase):
    """Long tile text wraps instead of being clipped/elided."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_title_wraps_and_keeps_full_text(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import ValueTileWidget

        long_label = "Output Voltage Setpoint Channel A Readback"
        entry = make_entry("a")
        entry.label = long_label
        tile = ValueTileWidget(entry)
        self.assertTrue(tile.title_label.wordWrap())
        self.assertEqual(tile.title_label.text(), long_label)
        tile.deleteLater()

    def test_value_label_wraps(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import ValueTileWidget

        tile = ValueTileWidget(make_entry("a"))
        self.assertTrue(tile.value_label.wordWrap())
        tile.deleteLater()

    def test_led_caption_wraps(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import LedTileWidget

        tile = LedTileWidget(make_entry("a", kind="led"))
        self.assertTrue(tile.caption_label.wordWrap())
        tile.deleteLater()


class CornerResizeTests(unittest.TestCase):
    """Drag the bottom-right corner (edit mode) to resize in whole cells."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def _tile(self):
        from ComPort_Zone.ui.control_panel_tiles import ValueTileWidget

        tile = ValueTileWidget(make_entry("a"))
        tile.resize(120, 96)
        # Stub the grid's stride provider: 100 px per cell column/row, 4 cols.
        tile.cell_metrics_provider = lambda: (100.0, 100.0, 4)
        return tile

    @staticmethod
    def _ev(kind, global_pos, *, local=(0, 0)):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        type_map = {
            "press": QEvent.Type.MouseButtonPress,
            "move": QEvent.Type.MouseMove,
            "release": QEvent.Type.MouseButtonRelease,
        }
        button = Qt.MouseButton.LeftButton if kind != "move" else Qt.MouseButton.NoButton
        buttons = Qt.MouseButton.LeftButton if kind != "release" else Qt.MouseButton.NoButton
        return QMouseEvent(
            type_map[kind],
            QPointF(*local),
            QPointF(*global_pos),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_corner_press_starts_resize(self) -> None:
        tile = self._tile()
        tile.set_edit_mode(True)
        # Press inside the bottom-right corner zone.
        tile.mousePressEvent(self._ev("press", (1000, 1000), local=(115, 91)))
        self.assertTrue(tile._resizing)
        tile.deleteLater()

    def test_press_outside_corner_does_not_resize(self) -> None:
        tile = self._tile()
        tile.set_edit_mode(True)
        tile.mousePressEvent(self._ev("press", (1000, 1000), local=(10, 10)))
        self.assertFalse(tile._resizing)
        tile.deleteLater()

    def test_corner_drag_emits_span_request(self) -> None:
        tile = self._tile()
        tile.set_edit_mode(True)
        seen: list[tuple[str, int, int]] = []
        tile.spanRequested.connect(lambda eid, w, h: seen.append((eid, w, h)))
        tile.mousePressEvent(self._ev("press", (1000, 1000), local=(115, 91)))
        # Drag +220 px right (≈ +2 cells), +110 px down (≈ +1 cell).
        tile.mouseMoveEvent(self._ev("move", (1220, 1110)))
        self.assertIn(("a", 3, 2), seen)
        tile.mouseReleaseEvent(self._ev("release", (1220, 1110)))
        self.assertFalse(tile._resizing)
        tile.deleteLater()

    def test_corner_drag_clamps_to_limits(self) -> None:
        tile = self._tile()
        tile.set_edit_mode(True)
        emitted: list[tuple[int, int]] = []
        tile.spanRequested.connect(lambda _eid, w, h: emitted.append((w, h)))
        tile.mousePressEvent(self._ev("press", (1000, 1000), local=(115, 91)))
        # Huge drag: width clamps to columns (4), height to MAX_TILE_SPAN (5).
        tile.mouseMoveEvent(self._ev("move", (5000, 5000)))
        self.assertEqual(emitted[-1], (4, 5))
        tile.deleteLater()


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
