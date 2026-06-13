"""Tests for the Qt-free control_panel domain models and grid layout math."""

from __future__ import annotations

import unittest

from ComPort_Zone.control_panel_models import (
    ColorRule,
    ControlSpec,
    ControlPanelConfig,
    ControlPanelEntry,
    ControlPanelTabState,
    MAX_TILE_SPAN,
    MIN_POLL_INTERVAL_MS,
    ParseRule,
    TilePlacement,
    control_panel_uses_v2_features,
    default_control_panels,
    entry_uses_v2_features,
    example_control_panel,
    grid_row_count,
    hex_payload_error,
    normalize_layout,
    place_tile,
    set_tile_span,
)
from ComPort_Zone.control_panel_parse import CompiledParseRule, ParseOutcome, evaluate_rules


def make_entry(entry_id: str, col: int = 0, row: int = 0, span_w: int = 1, span_h: int = 1) -> ControlPanelEntry:
    return ControlPanelEntry(
        id=entry_id,
        label=entry_id,
        command=f"MEAS:{entry_id}?",
        tile=TilePlacement(col=col, row=row, span_w=span_w, span_h=span_h),
    )


def placements(entries: list[ControlPanelEntry]) -> dict[str, tuple[int, int, int, int]]:
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


class ControlPanelEntryTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        entry = ControlPanelEntry(
            label="Volts",
            unit="V",
            command="MEAS:VOLT?",
            interval_ms=250,
            timeout_ms=200,
            parse=ParseRule(kind="regex", pattern=r"([\d.]+)", group=1, value_type="number"),
            tile=TilePlacement(col=1, row=0, span_w=2, span_h=1),
            rules=[ColorRule(op="gt", operand="13.0", state="fail")],
        )
        self.assertEqual(ControlPanelEntry.from_dict(entry.to_dict()), entry)

    def test_from_dict_clamps_interval_floor(self) -> None:
        entry = ControlPanelEntry.from_dict({"command": "X?", "interval_ms": 50})
        self.assertEqual(entry.interval_ms, MIN_POLL_INTERVAL_MS)

    def test_from_dict_tolerates_unknown_keys(self) -> None:
        entry = ControlPanelEntry.from_dict({"command": "X?", "future_field": {"a": 1}})
        self.assertEqual(entry.command, "X?")

    def test_from_dict_sanitizes_enums(self) -> None:
        entry = ControlPanelEntry.from_dict(
            {"command": "X?", "send_mode": "Carrier Pigeon", "line_ending_override": "VT"}
        )
        self.assertEqual(entry.send_mode, "Text")
        self.assertEqual(entry.line_ending_override, "")

    def test_validation_empty_command(self) -> None:
        errors = ControlPanelEntry().validation_errors()
        self.assertIn("Command must not be empty.", errors)

    def test_validation_hex_odd_nibbles(self) -> None:
        entry = ControlPanelEntry(command="AB C", send_mode="Hex Bytes")
        self.assertTrue(any("even" in error for error in entry.validation_errors()))

    def test_validation_hex_invalid_chars(self) -> None:
        entry = ControlPanelEntry(command="ZZ", send_mode="Hex Bytes")
        self.assertTrue(any("invalid characters" in error for error in entry.validation_errors()))

    def test_validation_valid_hex_passes(self) -> None:
        entry = ControlPanelEntry(command="0xAB,0xCD", send_mode="Hex Bytes")
        self.assertEqual(entry.validation_errors(), [])

    def test_validation_interval_floor(self) -> None:
        entry = ControlPanelEntry(command="X?", interval_ms=10)
        self.assertTrue(any("at least" in error for error in entry.validation_errors()))

    def test_validation_collects_rule_errors_with_index(self) -> None:
        entry = ControlPanelEntry(
            command="X?",
            rules=[ColorRule(op="eq_text", operand="OK"), ColorRule(op="lt", operand="oops")],
        )
        errors = entry.validation_errors()
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("Rule 2:"))

    def test_effective_stale_after_auto(self) -> None:
        entry = ControlPanelEntry(command="X?", interval_ms=1000, timeout_ms=500)
        self.assertEqual(entry.effective_stale_after_ms(), 3000)
        fast = ControlPanelEntry(command="X?", interval_ms=100, timeout_ms=500)
        self.assertEqual(fast.effective_stale_after_ms(), 1600)

    def test_effective_stale_after_explicit(self) -> None:
        entry = ControlPanelEntry(command="X?", stale_after_ms=9000)
        self.assertEqual(entry.effective_stale_after_ms(), 9000)


class ControlPanelConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        config = ControlPanelConfig(
            name="PSU Bench",
            description="Bench supply",
            columns=3,
            entries=[make_entry("a"), make_entry("b", col=1)],
        )
        self.assertEqual(ControlPanelConfig.from_dict(config.to_dict()), config)

    def test_to_dict_orders_entries_by_position(self) -> None:
        config = ControlPanelConfig(
            entries=[make_entry("late", col=2, row=1), make_entry("first", col=0, row=0)]
        )
        payload = config.to_dict()
        self.assertEqual([item["id"] for item in payload["entries"]], ["first", "late"])

    def test_columns_clamped(self) -> None:
        self.assertEqual(ControlPanelConfig.from_dict({"columns": 99}).columns, 12)
        self.assertEqual(ControlPanelConfig.from_dict({"columns": 0}).columns, 1)

    def test_rows_clamped(self) -> None:
        self.assertEqual(ControlPanelConfig.from_dict({"rows": 999}).rows, 24)
        self.assertEqual(ControlPanelConfig.from_dict({"rows": 0}).rows, 1)
        self.assertEqual(ControlPanelConfig.from_dict({}).rows, 5)

    def test_blank_name_falls_back(self) -> None:
        self.assertEqual(ControlPanelConfig.from_dict({"name": "   "}).name, "ControlPanel")

    def test_from_dict_normalizes_overlaps(self) -> None:
        config = ControlPanelConfig.from_dict(
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
        config = ControlPanelConfig(entries=[make_entry("a")])
        self.assertIsNotNone(config.entry_by_id("a"))
        self.assertIsNone(config.entry_by_id("missing"))

    def test_favorite_round_trips(self) -> None:
        config = ControlPanelConfig(name="PSU", favorite=True)
        restored = ControlPanelConfig.from_dict(config.to_dict())
        self.assertTrue(restored.favorite)
        self.assertFalse(ControlPanelConfig.from_dict({"name": "X"}).favorite)


class ControlPanelTabStateTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        state = ControlPanelTabState(
            control_panel_id="abc",
            target_endpoint="COM7",
            target_title="Terminal 1",
            polling_enabled=False,
        )
        self.assertEqual(ControlPanelTabState.from_dict(state.to_dict()), state)

    def test_from_dict_none(self) -> None:
        state = ControlPanelTabState.from_dict(None)
        self.assertEqual(state.control_panel_id, "")
        self.assertTrue(state.polling_enabled)


class V2EntryFieldTests(unittest.TestCase):
    """v2 additive fields: round-trips, sparse serialization, validation."""

    def test_v1_shaped_entry_serializes_with_no_v2_keys(self) -> None:
        payload = ControlPanelEntry(command="X?").to_dict()
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
        entry = ControlPanelEntry(
            command="OUTP?",
            poll_mode="on_connect",
            target_endpoint="COM9",
            show_sparkline=False,
            alerts_enabled=False,
            rules=[ColorRule(op="eq_num", operand="1", state="ok", color="#12ab34")],
        )
        restored = ControlPanelEntry.from_dict(entry.to_dict())
        self.assertEqual(restored, entry)

    def test_derived_entry_round_trips(self) -> None:
        entry = ControlPanelEntry(
            label="Power", source="derived", expression="{Volts} * {Amps}"
        )
        restored = ControlPanelEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.source, "derived")
        self.assertEqual(restored.expression, "{Volts} * {Amps}")

    def test_control_entry_round_trips(self) -> None:
        entry = ControlPanelEntry(
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
        restored = ControlPanelEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.control, entry.control)
        self.assertEqual(restored.tile.kind, "control")

    def test_from_dict_sanitizes_v2_enums_and_colors(self) -> None:
        entry = ControlPanelEntry.from_dict(
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
        button = ControlPanelEntry(tile=TilePlacement(kind="control"))
        self.assertTrue(any("Command" in error for error in button.validation_errors()))
        toggle = ControlPanelEntry(
            tile=TilePlacement(kind="control"),
            control=ControlSpec(mode="toggle", on_command="OUTP ON"),
        )
        self.assertTrue(any("OFF command" in error for error in toggle.validation_errors()))
        valid = ControlPanelEntry(
            tile=TilePlacement(kind="control"),
            control=ControlSpec(mode="toggle", on_command="OUTP ON", off_command="OUTP OFF"),
        )
        self.assertEqual(valid.validation_errors(), [])

    def test_control_hex_validation(self) -> None:
        entry = ControlPanelEntry(
            send_mode="Hex Bytes",
            tile=TilePlacement(kind="control"),
            control=ControlSpec(on_command="ABC"),
        )
        self.assertTrue(any("even" in error for error in entry.validation_errors()))

    def test_derived_validation_requires_expression(self) -> None:
        entry = ControlPanelEntry(source="derived")
        self.assertIn("Expression must not be empty.", entry.validation_errors())
        # Derived entries skip command/interval/parse checks entirely.
        entry.expression = "{Volts} * 2"
        self.assertEqual(entry.validation_errors(), [])

    def test_kind_predicates(self) -> None:
        self.assertTrue(ControlPanelEntry(command="X?").is_polled())
        self.assertTrue(ControlPanelEntry(source="derived", expression="1").is_derived())
        self.assertTrue(ControlPanelEntry(tile=TilePlacement(kind="control")).is_control())
        self.assertTrue(
            ControlPanelEntry(source="derived", expression="1").is_numeric()
        )
        self.assertFalse(ControlPanelEntry(tile=TilePlacement(kind="control")).is_numeric())

    def test_entry_uses_v2_features_matrix(self) -> None:
        self.assertFalse(entry_uses_v2_features(ControlPanelEntry(command="X?")))
        cases = {
            "poll_mode": ControlPanelEntry(command="X?", poll_mode="on_connect"),
            "target": ControlPanelEntry(command="X?", target_endpoint="COM9"),
            "derived": ControlPanelEntry(source="derived", expression="1"),
            "control": ControlPanelEntry(tile=TilePlacement(kind="control")),
            "rule color": ControlPanelEntry(
                command="X?", rules=[ColorRule(op="gt", operand="1", color="#112233")]
            ),
        }
        for name, entry in cases.items():
            with self.subTest(feature=name):
                self.assertTrue(entry_uses_v2_features(entry))
        # Cosmetic-only fields deliberately do not flip the predicate.
        self.assertFalse(
            entry_uses_v2_features(
                ControlPanelEntry(command="X?", show_sparkline=False, alerts_enabled=False)
            )
        )

    def test_control_panel_uses_v2_features(self) -> None:
        plain = ControlPanelConfig(entries=[ControlPanelEntry(command="X?")])
        self.assertFalse(control_panel_uses_v2_features(plain))
        self.assertTrue(
            control_panel_uses_v2_features(ControlPanelConfig(csv_log_enabled=True))
        )
        self.assertTrue(
            control_panel_uses_v2_features(ControlPanelConfig(csv_log_path="C:/log.csv"))
        )
        self.assertTrue(control_panel_uses_v2_features(example_control_panel()))

    def test_config_csv_fields_sparse_and_round_trip(self) -> None:
        plain_payload = ControlPanelConfig().to_dict()
        self.assertNotIn("csv_log_enabled", plain_payload)
        self.assertNotIn("csv_log_path", plain_payload)
        config = ControlPanelConfig(csv_log_enabled=True, csv_log_path="C:/bench.csv")
        restored = ControlPanelConfig.from_dict(config.to_dict())
        self.assertTrue(restored.csv_log_enabled)
        self.assertEqual(restored.csv_log_path, "C:/bench.csv")


class V3EntryFieldTests(unittest.TestCase):
    """Setpoint + enum entries: sparse persistence, predicates, validation."""

    def test_v2_shaped_entry_serializes_with_no_v3_keys(self) -> None:
        """A panel that doesn't use v3 widgets keeps its v2 payload shape."""
        from ComPort_Zone.control_panel_models import (
            entry_uses_v3_features,
            control_panel_uses_v3_features,
        )

        v2_entry = ControlPanelEntry(
            command="X?",
            poll_mode="on_connect",
            rules=[ColorRule(op="gt", operand="1", color="#112233")],
        )
        payload = v2_entry.to_dict()
        # v3-only keys never written when defaults stand.
        self.assertNotIn("setpoint", payload)
        self.assertNotIn("enum_spec", payload)
        self.assertFalse(entry_uses_v3_features(v2_entry))
        self.assertFalse(
            control_panel_uses_v3_features(ControlPanelConfig(entries=[v2_entry]))
        )

    def test_setpoint_round_trip(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        entry = ControlPanelEntry(
            label="Output",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(
                min_value=0.0,
                max_value=30.0,
                step=0.1,
                decimals=2,
                unit="V",
                command_template="VOLT {value}",
                watch_entry_id="vmeas",
                confirm=True,
            ),
        )
        self.assertTrue(entry.is_setpoint())
        self.assertTrue(entry.is_writable())
        self.assertFalse(entry.is_polled())
        self.assertFalse(entry.is_numeric())
        restored = ControlPanelEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.tile.kind, "setpoint")
        self.assertEqual(restored.setpoint.min_value, 0.0)
        self.assertEqual(restored.setpoint.max_value, 30.0)
        self.assertEqual(restored.setpoint.step, 0.1)
        self.assertEqual(restored.setpoint.decimals, 2)
        self.assertEqual(restored.setpoint.unit, "V")
        self.assertEqual(restored.setpoint.command_template, "VOLT {value}")
        self.assertEqual(restored.setpoint.watch_entry_id, "vmeas")
        self.assertTrue(restored.setpoint.confirm)

    def test_setpoint_render_command_uses_decimals(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        spec = SetpointSpec(
            command_template="VOLT {value}", decimals=2, min_value=0.0, max_value=10.0
        )
        self.assertEqual(spec.render_command(3.14159), "VOLT 3.14")
        # decimals=0 drops the decimal point entirely.
        spec.decimals = 0
        self.assertEqual(spec.render_command(7.4), "VOLT 7")

    def test_setpoint_clamp_keeps_value_in_range(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        spec = SetpointSpec(min_value=0.0, max_value=10.0, step=0.5)
        self.assertEqual(spec.clamp(-5.0), 0.0)
        self.assertEqual(spec.clamp(99.0), 10.0)
        self.assertEqual(spec.clamp(4.2), 4.2)

    def test_setpoint_validation_errors(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        # Empty template
        self.assertIn(
            "Command template must not be empty.",
            SetpointSpec(command_template="").validation_errors("Text"),
        )
        # Missing {value}
        self.assertIn(
            "Command template must contain {value} exactly once.",
            SetpointSpec(command_template="VOLT").validation_errors("Text"),
        )
        # Duplicate {value}
        self.assertIn(
            "Command template must contain {value} exactly once.",
            SetpointSpec(command_template="V{value} {value}").validation_errors("Text"),
        )
        # Min >= max
        errors = SetpointSpec(
            command_template="V {value}", min_value=10, max_value=5
        ).validation_errors("Text")
        self.assertTrue(any("less than maximum" in e for e in errors))
        # Step <= 0
        errors = SetpointSpec(
            command_template="V {value}", step=0.0, min_value=0, max_value=10
        ).validation_errors("Text")
        self.assertTrue(any("Step must be a positive number" in e for e in errors))
        # Step > range
        errors = SetpointSpec(
            command_template="V {value}", step=20, min_value=0, max_value=10
        ).validation_errors("Text")
        self.assertTrue(any("Step must be smaller than the value range" in e for e in errors))
        # Valid spec: no errors.
        self.assertEqual(
            SetpointSpec(command_template="V {value}").validation_errors("Text"),
            [],
        )

    def test_setpoint_validation_in_hex_mode(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        # The template renders to a stringified number that is not valid
        # hex; the Hex Bytes branch catches it.
        errors = SetpointSpec(
            command_template="{value}", min_value=0, max_value=10, step=1, decimals=0
        ).validation_errors("Hex Bytes")
        self.assertTrue(any("Setpoint command" in e for e in errors))

    def test_enum_round_trip(self) -> None:
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec

        entry = ControlPanelEntry(
            label="Mode",
            tile=TilePlacement(kind="enum"),
            enum_spec=EnumSpec(
                options=[
                    EnumOption(label="CV", command="MODE CV", match_value="CV"),
                    EnumOption(label="CC", command="MODE CC", match_value="CC"),
                    EnumOption(label="OFF", command="OUTP OFF"),
                ],
                watch_entry_id="modepoll",
                confirm=False,
            ),
        )
        self.assertTrue(entry.is_enum())
        self.assertTrue(entry.is_writable())
        self.assertFalse(entry.is_polled())
        restored = ControlPanelEntry.from_dict(entry.to_dict())
        self.assertEqual(restored.tile.kind, "enum")
        self.assertEqual(len(restored.enum_spec.options), 3)
        self.assertEqual(restored.enum_spec.options[0].label, "CV")
        self.assertEqual(restored.enum_spec.options[0].command, "MODE CV")
        self.assertEqual(restored.enum_spec.options[0].match_value, "CV")
        self.assertEqual(restored.enum_spec.watch_entry_id, "modepoll")
        self.assertEqual(restored.enum_spec.options[2].match_value, "")

    def test_enum_indicated_index(self) -> None:
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec

        spec = EnumSpec(
            options=[
                EnumOption(label="CV", command="MODE CV", match_value="CV"),
                EnumOption(label="CC", command="MODE CC", match_value="CC"),
                EnumOption(label="OFF", command="OUTP OFF"),
            ]
        )
        self.assertEqual(spec.indicated_index("CV"), 0)
        self.assertEqual(spec.indicated_index("cc"), 1)  # case-insensitive
        self.assertEqual(spec.indicated_index(" CV "), 0)  # whitespace-tolerant
        self.assertEqual(spec.indicated_index("UNKNOWN"), -1)
        self.assertEqual(spec.indicated_index(""), -1)

    def test_enum_validation_errors(self) -> None:
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec

        # No options
        errors = EnumSpec().validation_errors("Text")
        self.assertEqual(errors, ["Enum tile needs at least one option."])
        # Missing label / command
        errors = EnumSpec(
            options=[
                EnumOption(label="", command="X"),
                EnumOption(label="Y", command=""),
            ]
        ).validation_errors("Text")
        self.assertTrue(any("Option 1: label" in e for e in errors))
        self.assertTrue(any("Option 2: command" in e for e in errors))
        # Hex mode: bad command in any option
        errors = EnumSpec(
            options=[EnumOption(label="Bad", command="NOTHEX")]
        ).validation_errors("Hex Bytes")
        self.assertTrue(any("Option 1:" in e for e in errors))

    def test_writable_predicate_covers_all_writing_tile_kinds(self) -> None:
        """is_writable() is the master-arm gate; every writing kind must
        answer True so v3-T5's gate fires uniformly (FR-72)."""
        self.assertTrue(ControlPanelEntry(tile=TilePlacement(kind="control")).is_writable())
        self.assertTrue(ControlPanelEntry(tile=TilePlacement(kind="setpoint")).is_writable())
        self.assertTrue(ControlPanelEntry(tile=TilePlacement(kind="enum")).is_writable())
        # Non-writing kinds answer False.
        self.assertFalse(ControlPanelEntry(tile=TilePlacement(kind="value")).is_writable())
        self.assertFalse(ControlPanelEntry(tile=TilePlacement(kind="led")).is_writable())

    def test_entry_uses_v3_features_matrix(self) -> None:
        from ComPort_Zone.control_panel_models import (
            EnumOption,
            EnumSpec,
            SetpointSpec,
            entry_uses_v3_features,
        )

        self.assertFalse(entry_uses_v3_features(ControlPanelEntry(command="X?")))
        # Even a v2-feature-loaded entry doesn't flip the v3 predicate.
        self.assertFalse(
            entry_uses_v3_features(
                ControlPanelEntry(command="X?", poll_mode="on_connect")
            )
        )
        cases = {
            "setpoint kind": ControlPanelEntry(tile=TilePlacement(kind="setpoint")),
            "enum kind": ControlPanelEntry(tile=TilePlacement(kind="enum")),
            "setpoint spec without matching kind": ControlPanelEntry(
                command="X?",
                setpoint=SetpointSpec(command_template="V {value}"),
            ),
            "enum spec without matching kind": ControlPanelEntry(
                command="X?",
                enum_spec=EnumSpec(options=[EnumOption(label="A", command="A")]),
            ),
        }
        for name, entry in cases.items():
            with self.subTest(feature=name):
                self.assertTrue(entry_uses_v3_features(entry))

    def test_validation_branches_for_writing_tiles(self) -> None:
        """A setpoint/enum entry validates its spec, not command/parse."""
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec, SetpointSpec

        setpoint = ControlPanelEntry(
            label="V",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(command_template="VOLT {value}"),
        )
        # No "Command must not be empty" — the spec carries it.
        self.assertEqual(setpoint.validation_errors(), [])

        bad_setpoint = ControlPanelEntry(
            label="V",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(command_template=""),
        )
        errors = bad_setpoint.validation_errors()
        self.assertTrue(any("Command template" in e for e in errors))

        good_enum = ControlPanelEntry(
            label="Mode",
            tile=TilePlacement(kind="enum"),
            enum_spec=EnumSpec(
                options=[EnumOption(label="X", command="MODE X")]
            ),
        )
        self.assertEqual(good_enum.validation_errors(), [])


class ExampleControlPanelTests(unittest.TestCase):
    """The shipped example must stay valid — it is every user's first
    contact with the feature."""

    def test_default_library_is_the_example(self) -> None:
        configs = default_control_panels()
        self.assertEqual([config.name for config in configs], ["Example Control Panel"])
        self.assertTrue(configs[0].favorite)

    def test_entries_match_the_spec(self) -> None:
        example = example_control_panel()
        polled_by_command = {
            entry.command: entry for entry in example.entries if entry.command
        }
        # v3 example also ships a setpoint + enum entry — those have no
        # poll command, so they don't appear in this map.
        self.assertEqual(
            set(polled_by_command),
            {"*IDN?", "OUTP?", "SYST:FIRM?", "SOUR:FUNC:MODE?"},
        )

        identity = polled_by_command["*IDN?"]
        self.assertEqual(identity.poll_mode, "on_connect")
        self.assertEqual((identity.tile.span_w, identity.tile.span_h), (2, 1))
        self.assertEqual(identity.tile.kind, "value")
        self.assertEqual(identity.parse.value_type, "text")

        firmware = polled_by_command["SYST:FIRM?"]
        self.assertEqual(firmware.poll_mode, "on_connect")
        self.assertEqual((firmware.tile.span_w, firmware.tile.span_h), (2, 1))
        self.assertEqual(firmware.tile.kind, "value")

        output = polled_by_command["OUTP?"]
        self.assertEqual(output.interval_ms, 300)
        self.assertEqual(output.tile.kind, "led")

        # v3 additions: a setpoint and an enum tile.
        setpoint_entries = [e for e in example.entries if e.is_setpoint()]
        self.assertEqual(len(setpoint_entries), 1)
        setpoint = setpoint_entries[0]
        self.assertEqual(setpoint.setpoint.command_template, "VOLT {value}")
        self.assertEqual(setpoint.setpoint.min_value, 0.0)
        self.assertEqual(setpoint.setpoint.max_value, 30.0)
        self.assertEqual(setpoint.setpoint.watch_entry_id, output.id)

        enum_entries = [e for e in example.entries if e.is_enum()]
        self.assertEqual(len(enum_entries), 1)
        enum_entry = enum_entries[0]
        self.assertEqual(
            [opt.label for opt in enum_entry.enum_spec.options],
            ["OFF", "CV", "CC"],
        )

    def test_output_rules_map_states_and_labels(self) -> None:
        output = next(
            entry for entry in example_control_panel().entries if entry.command == "OUTP?"
        )
        on = evaluate_rules(output.rules, ParseOutcome(True, "1", 1.0))
        off = evaluate_rules(output.rules, ParseOutcome(True, "0", 0.0))
        self.assertEqual((on.state, on.label), ("ok", "ON"))
        self.assertEqual((off.state, off.label), ("warn", "OFF"))

    def test_every_entry_is_valid_and_compilable(self) -> None:
        for entry in example_control_panel().entries:
            self.assertEqual(entry.validation_errors(), [], msg=entry.command)
            CompiledParseRule.compile(entry.parse)

    def test_layout_has_no_overlaps(self) -> None:
        example = example_control_panel()
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
        example = example_control_panel()
        self.assertEqual(ControlPanelConfig.from_dict(example.to_dict()), example)


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
        def build() -> list[ControlPanelEntry]:
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
