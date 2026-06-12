"""Tests for the Qt-free dashboard domain models and grid layout math."""

from __future__ import annotations

import unittest

from ComPort_Zone.dashboard_models import (
    ColorRule,
    ControlSpec,
    DashboardConfig,
    DashboardEntry,
    DashboardTabState,
    MAX_TILE_SPAN,
    MIN_POLL_INTERVAL_MS,
    ParseRule,
    TilePlacement,
    dashboard_uses_v2_features,
    default_dashboards,
    entry_uses_v2_features,
    example_dashboard,
    grid_row_count,
    hex_payload_error,
    normalize_layout,
    place_tile,
    set_tile_span,
)
from ComPort_Zone.dashboard_parse import CompiledParseRule, ParseOutcome, evaluate_rules


def make_entry(entry_id: str, col: int = 0, row: int = 0, span_w: int = 1, span_h: int = 1) -> DashboardEntry:
    return DashboardEntry(
        id=entry_id,
        label=entry_id,
        command=f"MEAS:{entry_id}?",
        tile=TilePlacement(col=col, row=row, span_w=span_w, span_h=span_h),
    )


def placements(entries: list[DashboardEntry]) -> dict[str, tuple[int, int, int, int]]:
    return {
        entry.id: (entry.tile.col, entry.tile.row, entry.tile.span_w, entry.tile.span_h)
        for entry in entries
    }


class ParseRuleTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        rule = ParseRule(kind="regex", pattern=r"V=(\d+)", group=1, value_type="number")
        self.assertEqual(ParseRule.from_dict(rule.to_dict()), rule)

    def test_named_group_round_trip(self) -> None:
        rule = ParseRule(kind="regex", pattern=r"(?P<volts>\d+)", group="volts", value_type="number")
        restored = ParseRule.from_dict(rule.to_dict())
        self.assertEqual(restored.group, "volts")

    def test_from_dict_tolerates_junk(self) -> None:
        rule = ParseRule.from_dict({"kind": "bogus", "group": object(), "value_type": 42})
        self.assertEqual(rule.kind, "line")
        self.assertEqual(rule.group, 1)
        self.assertEqual(rule.value_type, "text")

    def test_from_dict_none(self) -> None:
        self.assertEqual(ParseRule.from_dict(None), ParseRule())

    def test_invalid_regex_reports_error(self) -> None:
        errors = ParseRule(kind="regex", pattern="(unclosed").validation_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("Invalid regex", errors[0])

    def test_empty_regex_pattern_reports_error(self) -> None:
        errors = ParseRule(kind="regex", pattern="").validation_errors()
        self.assertIn("requires a pattern", errors[0])

    def test_group_index_out_of_range(self) -> None:
        errors = ParseRule(kind="regex", pattern=r"(\d+)", group=2).validation_errors()
        self.assertIn("out of range", errors[0])

    def test_missing_named_group(self) -> None:
        errors = ParseRule(kind="regex", pattern=r"(\d+)", group="volts").validation_errors()
        self.assertIn("no capture group named", errors[0])

    def test_line_rule_needs_no_pattern(self) -> None:
        self.assertEqual(ParseRule(kind="line").validation_errors(), [])


class ColorRuleTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        rule = ColorRule(op="between", operand="1.0", operand2="2.0", state="warn", label="MID")
        self.assertEqual(ColorRule.from_dict(rule.to_dict()), rule)

    def test_from_dict_tolerates_junk(self) -> None:
        rule = ColorRule.from_dict({"op": "frobnicate", "state": "purple"})
        self.assertEqual(rule.op, "eq_text")
        self.assertEqual(rule.state, "ok")

    def test_numeric_operand_validation(self) -> None:
        errors = ColorRule(op="lt", operand="abc").validation_errors()
        self.assertIn("must be a number", errors[0])

    def test_between_requires_numeric_upper_bound(self) -> None:
        errors = ColorRule(op="between", operand="1", operand2="hi").validation_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("upper bound", errors[0])

    def test_matches_validates_regex(self) -> None:
        errors = ColorRule(op="matches", operand="(bad").validation_errors()
        self.assertIn("Invalid rule regex", errors[0])

    def test_text_rule_accepts_any_operand(self) -> None:
        self.assertEqual(ColorRule(op="eq_text", operand="FAULT").validation_errors(), [])


class TilePlacementTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        tile = TilePlacement(col=2, row=3, span_w=2, span_h=1, kind="led")
        self.assertEqual(TilePlacement.from_dict(tile.to_dict()), tile)

    def test_span_clamped_on_load(self) -> None:
        tile = TilePlacement.from_dict({"span_w": 3, "span_h": 9})
        self.assertEqual(tile.span_w, MAX_TILE_SPAN)
        self.assertEqual(tile.span_h, MAX_TILE_SPAN)

    def test_negative_position_clamped(self) -> None:
        tile = TilePlacement.from_dict({"col": -4, "row": -1})
        self.assertEqual((tile.col, tile.row), (0, 0))

    def test_unknown_kind_falls_back(self) -> None:
        self.assertEqual(TilePlacement.from_dict({"kind": "gauge"}).kind, "value")


class DashboardEntryTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        entry = DashboardEntry(
            label="Volts",
            unit="V",
            command="MEAS:VOLT?",
            interval_ms=250,
            timeout_ms=200,
            parse=ParseRule(kind="regex", pattern=r"([\d.]+)", group=1, value_type="number"),
            tile=TilePlacement(col=1, row=0, span_w=2, span_h=1),
            rules=[ColorRule(op="gt", operand="13.0", state="fail")],
        )
        self.assertEqual(DashboardEntry.from_dict(entry.to_dict()), entry)

    def test_from_dict_clamps_interval_floor(self) -> None:
        entry = DashboardEntry.from_dict({"command": "X?", "interval_ms": 50})
        self.assertEqual(entry.interval_ms, MIN_POLL_INTERVAL_MS)

    def test_from_dict_tolerates_unknown_keys(self) -> None:
        entry = DashboardEntry.from_dict({"command": "X?", "future_field": {"a": 1}})
        self.assertEqual(entry.command, "X?")

    def test_from_dict_sanitizes_enums(self) -> None:
        entry = DashboardEntry.from_dict(
            {"command": "X?", "send_mode": "Carrier Pigeon", "line_ending_override": "VT"}
        )
        self.assertEqual(entry.send_mode, "Text")
        self.assertEqual(entry.line_ending_override, "")

    def test_validation_empty_command(self) -> None:
        errors = DashboardEntry().validation_errors()
        self.assertIn("Command must not be empty.", errors)

    def test_validation_hex_odd_nibbles(self) -> None:
        entry = DashboardEntry(command="AB C", send_mode="Hex Bytes")
        self.assertTrue(any("even" in error for error in entry.validation_errors()))

    def test_validation_hex_invalid_chars(self) -> None:
        entry = DashboardEntry(command="ZZ", send_mode="Hex Bytes")
        self.assertTrue(any("invalid characters" in error for error in entry.validation_errors()))

    def test_validation_valid_hex_passes(self) -> None:
        entry = DashboardEntry(command="0xAB,0xCD", send_mode="Hex Bytes")
        self.assertEqual(entry.validation_errors(), [])

    def test_validation_interval_floor(self) -> None:
        entry = DashboardEntry(command="X?", interval_ms=10)
        self.assertTrue(any("at least" in error for error in entry.validation_errors()))

    def test_validation_collects_rule_errors_with_index(self) -> None:
        entry = DashboardEntry(
            command="X?",
            rules=[ColorRule(op="eq_text", operand="OK"), ColorRule(op="lt", operand="oops")],
        )
        errors = entry.validation_errors()
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("Rule 2:"))

    def test_effective_stale_after_auto(self) -> None:
        entry = DashboardEntry(command="X?", interval_ms=1000, timeout_ms=500)
        self.assertEqual(entry.effective_stale_after_ms(), 3000)
        fast = DashboardEntry(command="X?", interval_ms=100, timeout_ms=500)
        self.assertEqual(fast.effective_stale_after_ms(), 1600)

    def test_effective_stale_after_explicit(self) -> None:
        entry = DashboardEntry(command="X?", stale_after_ms=9000)
        self.assertEqual(entry.effective_stale_after_ms(), 9000)


class DashboardConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        config = DashboardConfig(
            name="PSU Bench",
            description="Bench supply",
            columns=3,
            entries=[make_entry("a"), make_entry("b", col=1)],
        )
        self.assertEqual(DashboardConfig.from_dict(config.to_dict()), config)

    def test_to_dict_orders_entries_by_position(self) -> None:
        config = DashboardConfig(
            entries=[make_entry("late", col=2, row=1), make_entry("first", col=0, row=0)]
        )
        payload = config.to_dict()
        self.assertEqual([item["id"] for item in payload["entries"]], ["first", "late"])

    def test_columns_clamped(self) -> None:
        self.assertEqual(DashboardConfig.from_dict({"columns": 99}).columns, 6)
        self.assertEqual(DashboardConfig.from_dict({"columns": 1}).columns, 2)

    def test_blank_name_falls_back(self) -> None:
        self.assertEqual(DashboardConfig.from_dict({"name": "   "}).name, "Dashboard")

    def test_from_dict_normalizes_overlaps(self) -> None:
        config = DashboardConfig.from_dict(
            {
                "columns": 4,
                "entries": [
                    make_entry("a", col=0, row=0).to_dict(),
                    make_entry("b", col=0, row=0).to_dict(),
                ],
            }
        )
        spots = placements(config.entries)
        self.assertNotEqual(spots["a"][:2], spots["b"][:2])

    def test_entry_by_id(self) -> None:
        config = DashboardConfig(entries=[make_entry("a")])
        self.assertIsNotNone(config.entry_by_id("a"))
        self.assertIsNone(config.entry_by_id("missing"))

    def test_favorite_round_trips(self) -> None:
        config = DashboardConfig(name="PSU", favorite=True)
        restored = DashboardConfig.from_dict(config.to_dict())
        self.assertTrue(restored.favorite)
        self.assertFalse(DashboardConfig.from_dict({"name": "X"}).favorite)


class DashboardTabStateTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        state = DashboardTabState(
            dashboard_id="abc",
            target_endpoint="COM7",
            target_title="Terminal 1",
            polling_enabled=False,
        )
        self.assertEqual(DashboardTabState.from_dict(state.to_dict()), state)

    def test_from_dict_none(self) -> None:
        state = DashboardTabState.from_dict(None)
        self.assertEqual(state.dashboard_id, "")
        self.assertTrue(state.polling_enabled)


class V2EntryFieldTests(unittest.TestCase):
    """v2 additive fields: round-trips, sparse serialization, validation."""

    def test_v1_shaped_entry_serializes_with_no_v2_keys(self) -> None:
        payload = DashboardEntry(command="X?").to_dict()
        for key in (
            "poll_mode",
            "target_endpoint",
            "source",
            "expression",
            "show_sparkline",
            "alerts_enabled",
            "control",
        ):
            self.assertNotIn(key, payload, msg=key)
        rule_payload = ColorRule(op="gt", operand="1").to_dict()
        self.assertNotIn("color", rule_payload)

    def test_v2_fields_round_trip(self) -> None:
        entry = DashboardEntry(
            command="OUTP?",
            poll_mode="on_connect",
            target_endpoint="COM9",
            show_sparkline=False,
            alerts_enabled=False,
            rules=[ColorRule(op="eq_num", operand="1", state="ok", color="#12ab34")],
        )
        restored = DashboardEntry.from_dict(entry.to_dict())
        self.assertEqual(restored, entry)

    def test_derived_entry_round_trips(self) -> None:
        entry = DashboardEntry(
            label="Power", source="derived", expression="{Volts} * {Amps}"
        )
        restored = DashboardEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.source, "derived")
        self.assertEqual(restored.expression, "{Volts} * {Amps}")

    def test_control_entry_round_trips(self) -> None:
        entry = DashboardEntry(
            label="Output",
            tile=TilePlacement(kind="control"),
            control=ControlSpec(
                mode="toggle",
                on_command="OUTP ON",
                off_command="OUTP OFF",
                confirm=True,
                watch_entry_id="watch-1",
            ),
        )
        restored = DashboardEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.control, entry.control)
        self.assertEqual(restored.tile.kind, "control")

    def test_from_dict_sanitizes_v2_enums_and_colors(self) -> None:
        entry = DashboardEntry.from_dict(
            {
                "command": "X?",
                "poll_mode": "hourly",
                "source": "telepathy",
                "rules": [{"op": "gt", "operand": "1", "color": "red"}],
            }
        )
        self.assertEqual(entry.poll_mode, "interval")
        self.assertEqual(entry.source, "poll")
        self.assertEqual(entry.rules[0].color, "")

    def test_control_validation_branches(self) -> None:
        button = DashboardEntry(tile=TilePlacement(kind="control"))
        self.assertTrue(any("Command" in error for error in button.validation_errors()))
        toggle = DashboardEntry(
            tile=TilePlacement(kind="control"),
            control=ControlSpec(mode="toggle", on_command="OUTP ON"),
        )
        self.assertTrue(any("OFF command" in error for error in toggle.validation_errors()))
        valid = DashboardEntry(
            tile=TilePlacement(kind="control"),
            control=ControlSpec(mode="toggle", on_command="OUTP ON", off_command="OUTP OFF"),
        )
        self.assertEqual(valid.validation_errors(), [])

    def test_control_hex_validation(self) -> None:
        entry = DashboardEntry(
            send_mode="Hex Bytes",
            tile=TilePlacement(kind="control"),
            control=ControlSpec(on_command="ABC"),
        )
        self.assertTrue(any("even" in error for error in entry.validation_errors()))

    def test_derived_validation_requires_expression(self) -> None:
        entry = DashboardEntry(source="derived")
        self.assertIn("Expression must not be empty.", entry.validation_errors())
        # Derived entries skip command/interval/parse checks entirely.
        entry.expression = "{Volts} * 2"
        self.assertEqual(entry.validation_errors(), [])

    def test_kind_predicates(self) -> None:
        self.assertTrue(DashboardEntry(command="X?").is_polled())
        self.assertTrue(DashboardEntry(source="derived", expression="1").is_derived())
        self.assertTrue(DashboardEntry(tile=TilePlacement(kind="control")).is_control())
        self.assertTrue(
            DashboardEntry(source="derived", expression="1").is_numeric()
        )
        self.assertFalse(DashboardEntry(tile=TilePlacement(kind="control")).is_numeric())

    def test_entry_uses_v2_features_matrix(self) -> None:
        self.assertFalse(entry_uses_v2_features(DashboardEntry(command="X?")))
        cases = {
            "poll_mode": DashboardEntry(command="X?", poll_mode="on_connect"),
            "target": DashboardEntry(command="X?", target_endpoint="COM9"),
            "derived": DashboardEntry(source="derived", expression="1"),
            "control": DashboardEntry(tile=TilePlacement(kind="control")),
            "rule color": DashboardEntry(
                command="X?", rules=[ColorRule(op="gt", operand="1", color="#112233")]
            ),
        }
        for name, entry in cases.items():
            with self.subTest(feature=name):
                self.assertTrue(entry_uses_v2_features(entry))
        # Cosmetic-only fields deliberately do not flip the predicate.
        self.assertFalse(
            entry_uses_v2_features(
                DashboardEntry(command="X?", show_sparkline=False, alerts_enabled=False)
            )
        )

    def test_dashboard_uses_v2_features(self) -> None:
        plain = DashboardConfig(entries=[DashboardEntry(command="X?")])
        self.assertFalse(dashboard_uses_v2_features(plain))
        self.assertTrue(
            dashboard_uses_v2_features(DashboardConfig(csv_log_enabled=True))
        )
        self.assertTrue(
            dashboard_uses_v2_features(DashboardConfig(csv_log_path="C:/log.csv"))
        )
        self.assertTrue(dashboard_uses_v2_features(example_dashboard()))

    def test_config_csv_fields_sparse_and_round_trip(self) -> None:
        plain_payload = DashboardConfig().to_dict()
        self.assertNotIn("csv_log_enabled", plain_payload)
        self.assertNotIn("csv_log_path", plain_payload)
        config = DashboardConfig(csv_log_enabled=True, csv_log_path="C:/bench.csv")
        restored = DashboardConfig.from_dict(config.to_dict())
        self.assertTrue(restored.csv_log_enabled)
        self.assertEqual(restored.csv_log_path, "C:/bench.csv")


class ExampleDashboardTests(unittest.TestCase):
    """The shipped example must stay valid — it is every user's first
    contact with the feature."""

    def test_default_library_is_the_example(self) -> None:
        configs = default_dashboards()
        self.assertEqual([config.name for config in configs], ["Example Dashboard"])
        self.assertTrue(configs[0].favorite)

    def test_entries_match_the_spec(self) -> None:
        example = example_dashboard()
        by_command = {entry.command: entry for entry in example.entries}
        self.assertEqual(
            set(by_command), {"*IDN?", "OUTP?", "SYST:FIRM?"}
        )

        identity = by_command["*IDN?"]
        self.assertEqual(identity.poll_mode, "on_connect")
        self.assertEqual((identity.tile.span_w, identity.tile.span_h), (2, 1))
        self.assertEqual(identity.tile.kind, "value")
        self.assertEqual(identity.parse.value_type, "text")

        firmware = by_command["SYST:FIRM?"]
        self.assertEqual(firmware.poll_mode, "on_connect")
        self.assertEqual((firmware.tile.span_w, firmware.tile.span_h), (2, 1))
        self.assertEqual(firmware.tile.kind, "value")

        output = by_command["OUTP?"]
        self.assertEqual(output.interval_ms, 300)
        self.assertEqual(output.tile.kind, "led")

    def test_output_rules_map_states_and_labels(self) -> None:
        output = next(
            entry for entry in example_dashboard().entries if entry.command == "OUTP?"
        )
        on = evaluate_rules(output.rules, ParseOutcome(True, "1", 1.0))
        off = evaluate_rules(output.rules, ParseOutcome(True, "0", 0.0))
        self.assertEqual((on.state, on.label), ("ok", "ON"))
        self.assertEqual((off.state, off.label), ("warn", "OFF"))

    def test_every_entry_is_valid_and_compilable(self) -> None:
        for entry in example_dashboard().entries:
            self.assertEqual(entry.validation_errors(), [], msg=entry.command)
            CompiledParseRule.compile(entry.parse)

    def test_layout_has_no_overlaps(self) -> None:
        example = example_dashboard()
        before = {
            entry.id: (entry.tile.col, entry.tile.row, entry.tile.span_w, entry.tile.span_h)
            for entry in example.entries
        }
        normalize_layout(example.entries, example.columns)
        after = {
            entry.id: (entry.tile.col, entry.tile.row, entry.tile.span_w, entry.tile.span_h)
            for entry in example.entries
        }
        self.assertEqual(before, after)

    def test_round_trips_through_dict(self) -> None:
        example = example_dashboard()
        self.assertEqual(DashboardConfig.from_dict(example.to_dict()), example)


class HexValidationTests(unittest.TestCase):
    def test_accepts_common_formats(self) -> None:
        for text in ("AB CD", "0xAB,0xCD", "AB-CD-EF", "abcd"):
            self.assertEqual(hex_payload_error(text), "", msg=text)

    def test_rejects_empty(self) -> None:
        self.assertIn("at least one byte", hex_payload_error("  "))

    def test_rejects_odd_count(self) -> None:
        self.assertIn("even", hex_payload_error("ABC"))

    def test_rejects_invalid_characters(self) -> None:
        self.assertIn("invalid characters", hex_payload_error("GG"))


class LayoutMathTests(unittest.TestCase):
    def test_normalize_is_deterministic(self) -> None:
        def build() -> list[DashboardEntry]:
            return [
                make_entry("a", col=0, row=0, span_w=2),
                make_entry("b", col=1, row=0),
                make_entry("c", col=0, row=0),
            ]

        first = build()
        second = build()
        normalize_layout(first, 4)
        normalize_layout(second, 4)
        self.assertEqual(placements(first), placements(second))

    def test_normalize_resolves_overlap_by_pushing_down(self) -> None:
        entries = [make_entry("a", col=0, row=0), make_entry("b", col=0, row=0)]
        normalize_layout(entries, 4)
        spots = placements(entries)
        self.assertEqual(spots["a"], (0, 0, 1, 1))
        self.assertEqual(spots["b"], (0, 1, 1, 1))

    def test_normalize_clamps_out_of_range_column(self) -> None:
        entries = [make_entry("a", col=7, row=0, span_w=2)]
        normalize_layout(entries, 4)
        self.assertEqual(entries[0].tile.col, 2)

    def test_normalize_repacks_after_column_shrink(self) -> None:
        entries = [make_entry("a", col=0, row=0), make_entry("b", col=4, row=0)]
        normalize_layout(entries, 2)
        spots = placements(entries)
        self.assertEqual(spots["a"][:2], (0, 0))
        self.assertEqual(spots["b"][:2], (1, 0))

    def test_normalize_respects_spans(self) -> None:
        entries = [
            make_entry("wide", col=0, row=0, span_w=2, span_h=2),
            make_entry("b", col=1, row=1),
        ]
        normalize_layout(entries, 4)
        spots = placements(entries)
        self.assertEqual(spots["wide"][:2], (0, 0))
        # "b" wanted (1,1) which the 2x2 tile occupies; it is pushed below.
        self.assertEqual(spots["b"][:2], (1, 2))

    def test_place_tile_moves_and_displaces(self) -> None:
        entries = [make_entry("a", col=0, row=0), make_entry("b", col=1, row=0)]
        moved = place_tile(entries, 4, "a", 1, 0)
        self.assertTrue(moved)
        spots = placements(entries)
        # The dragged tile wins the cell; the displaced tile is pushed down.
        self.assertEqual(spots["a"][:2], (1, 0))
        self.assertEqual(spots["b"][:2], (1, 1))

    def test_place_tile_unknown_id(self) -> None:
        self.assertFalse(place_tile([], 4, "ghost", 0, 0))

    def test_set_tile_span_grows_and_displaces(self) -> None:
        entries = [make_entry("a", col=0, row=0), make_entry("b", col=1, row=0)]
        changed = set_tile_span(entries, 4, "a", 2, 1)
        self.assertTrue(changed)
        spots = placements(entries)
        self.assertEqual(spots["a"], (0, 0, 2, 1))
        self.assertEqual(spots["b"][:2], (1, 1))

    def test_set_tile_span_clamps(self) -> None:
        entries = [make_entry("a")]
        set_tile_span(entries, 4, "a", 9, 9)
        self.assertEqual((entries[0].tile.span_w, entries[0].tile.span_h), (2, 2))

    def test_set_tile_span_unknown_id(self) -> None:
        self.assertFalse(set_tile_span([], 4, "ghost", 1, 1))

    def test_grid_row_count(self) -> None:
        self.assertEqual(grid_row_count([]), 0)
        entries = [make_entry("a", col=0, row=0), make_entry("b", col=0, row=2, span_h=2)]
        self.assertEqual(grid_row_count(entries), 4)


if __name__ == "__main__":
    unittest.main()
