"""Tests for the control_panel catalog and JSON import/export."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ComPort_Zone.control_panel_catalog import (
    CONTROL_PANEL_EXPORT_KEY,
    CONTROL_PANEL_EXPORT_V2,
    CONTROL_PANEL_EXPORT_V3,
    CONTROL_PANEL_EXPORT_VERSION,
    ControlPanelCatalog,
    export_control_panels_payload,
    import_control_panels_payload,
    merge_imported,
    read_control_panels_json,
    write_control_panels_json,
)
from ComPort_Zone.control_panel_models import ControlPanelConfig, ControlPanelEntry


def make_config(name: str, config_id: str | None = None) -> ControlPanelConfig:
    config = ControlPanelConfig(name=name, entries=[ControlPanelEntry(label="V", command="MEAS:VOLT?")])
    if config_id is not None:
        config.id = config_id
    return config


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.control_panels: list[ControlPanelConfig] = []
        self.catalog = ControlPanelCatalog(self.control_panels)

    def test_add_mutates_backing_list(self) -> None:
        self.catalog.add(make_config("PSU"))
        self.assertEqual(len(self.control_panels), 1)

    def test_all_sorted_by_name_case_insensitive(self) -> None:
        self.catalog.add(make_config("zeta"))
        self.catalog.add(make_config("Alpha"))
        self.assertEqual([config.name for config in self.catalog.all()], ["Alpha", "zeta"])

    def test_add_dedupes_names(self) -> None:
        self.catalog.add(make_config("PSU"))
        second = self.catalog.add(make_config("PSU"))
        third = self.catalog.add(make_config("psu"))
        self.assertEqual(second.name, "PSU (2)")
        self.assertEqual(third.name, "psu (3)")

    def test_by_id_and_by_name(self) -> None:
        config = self.catalog.add(make_config("PSU"))
        self.assertIs(self.catalog.by_id(config.id), config)
        self.assertIs(self.catalog.by_name("psu"), config)
        self.assertIsNone(self.catalog.by_id("ghost"))
        self.assertIsNone(self.catalog.by_name("ghost"))

    def test_duplicate_creates_fresh_ids(self) -> None:
        source = self.catalog.add(make_config("PSU"))
        clone = self.catalog.duplicate(source.id)
        self.assertIsNotNone(clone)
        assert clone is not None
        self.assertEqual(clone.name, "PSU Copy")
        self.assertNotEqual(clone.id, source.id)
        self.assertEqual(len(clone.entries), 1)
        self.assertNotEqual(clone.entries[0].id, source.entries[0].id)
        self.assertEqual(clone.entries[0].command, source.entries[0].command)

    def test_duplicate_unknown_id(self) -> None:
        self.assertIsNone(self.catalog.duplicate("ghost"))

    def test_duplicate_remaps_follow_watch_ids(self) -> None:
        from ComPort_Zone.control_panel_models import (
            ParseRule,
            ReadbackSpec,
            SetpointSpec,
            TilePlacement,
        )

        watched = ControlPanelEntry(
            id="meas", label="Measured", command="MEAS:VOLT?",
            parse=ParseRule(kind="line", value_type="number"),
        )
        setpoint = ControlPanelEntry(
            id="sp", label="Set V",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(command_template="VOLT {value}"),
            readback=ReadbackSpec(source="entry", watch_entry_id="meas"),
        )
        source = self.catalog.add(
            ControlPanelConfig(name="PSU", entries=[watched, setpoint])
        )
        clone = self.catalog.duplicate(source.id)
        assert clone is not None
        new_watched, new_setpoint = clone.entries
        # The follow reference points at the COPY's watched id, not the original.
        self.assertNotEqual(new_watched.id, "meas")
        self.assertEqual(new_setpoint.readback.watch_entry_id, new_watched.id)

    def test_rename_dedupes_and_rejects_blank(self) -> None:
        first = self.catalog.add(make_config("PSU"))
        second = self.catalog.add(make_config("Scope"))
        self.assertTrue(self.catalog.rename(second.id, "PSU"))
        self.assertEqual(second.name, "PSU (2)")
        self.assertFalse(self.catalog.rename(first.id, "   "))
        self.assertFalse(self.catalog.rename("ghost", "Name"))

    def test_rename_to_own_name_is_stable(self) -> None:
        config = self.catalog.add(make_config("PSU"))
        self.assertTrue(self.catalog.rename(config.id, "PSU"))
        self.assertEqual(config.name, "PSU")

    def test_remove(self) -> None:
        config = self.catalog.add(make_config("PSU"))
        self.assertTrue(self.catalog.remove(config.id))
        self.assertEqual(len(self.catalog), 0)
        self.assertFalse(self.catalog.remove(config.id))


class TransferPayloadTests(unittest.TestCase):
    def test_export_import_round_trip(self) -> None:
        configs = [make_config("PSU"), make_config("Scope")]
        payload = export_control_panels_payload(configs)
        # v1-shaped control_panels export as payload version 1 so v1 builds can
        # still import them (FR-39).
        self.assertEqual(payload[CONTROL_PANEL_EXPORT_KEY], 1)
        restored = import_control_panels_payload(json.loads(json.dumps(payload)))
        self.assertEqual([config.to_dict() for config in restored], [config.to_dict() for config in configs])

    def test_export_stamps_version_2_for_v2_features(self) -> None:
        config = make_config("PSU")
        config.entries[0].poll_mode = "on_connect"
        payload = export_control_panels_payload([config])
        # A v2-shaped payload (no v3 widgets) stays at version 2 so v2
        # builds keep importing it. v3 builds keep reading it.
        self.assertEqual(payload[CONTROL_PANEL_EXPORT_KEY], CONTROL_PANEL_EXPORT_V2)
        # Also confirm CONTROL_PANEL_EXPORT_VERSION has moved to v4.
        self.assertEqual(CONTROL_PANEL_EXPORT_VERSION, 4)
        restored = import_control_panels_payload(json.loads(json.dumps(payload)))
        self.assertEqual(restored[0].entries[0].poll_mode, "on_connect")

    def test_export_stamps_version_3_for_v3_features(self) -> None:
        from ComPort_Zone.control_panel_models import (
            EnumOption,
            EnumSpec,
            SetpointSpec,
            TilePlacement,
        )

        config = make_config("Setpoint Bench")
        config.entries[0].tile = TilePlacement(kind="setpoint")
        config.entries[0].setpoint = SetpointSpec(
            command_template="VOLT {value}", max_value=30
        )
        payload = export_control_panels_payload([config])
        # v3 features (no v4 widget) stay at version 3 so v3 builds keep
        # importing them.
        self.assertEqual(payload[CONTROL_PANEL_EXPORT_KEY], CONTROL_PANEL_EXPORT_V3)

        # An enum-only panel also stamps version 3.
        enum_config = make_config("Mode Selector")
        enum_config.entries[0].tile = TilePlacement(kind="enum")
        enum_config.entries[0].enum_spec = EnumSpec(
            options=[EnumOption(label="CV", command="MODE CV")]
        )
        self.assertEqual(
            export_control_panels_payload([enum_config])[CONTROL_PANEL_EXPORT_KEY],
            CONTROL_PANEL_EXPORT_V3,
        )
        # Mixed v1 + v3 in one bundle stamps the highest version present.
        mixed_payload = export_control_panels_payload([make_config("V1"), enum_config])
        self.assertEqual(mixed_payload[CONTROL_PANEL_EXPORT_KEY], CONTROL_PANEL_EXPORT_V3)
        # A v3 payload round-trips losslessly.
        restored = import_control_panels_payload(json.loads(json.dumps(payload)))
        self.assertEqual(restored[0].entries[0].tile.kind, "setpoint")
        self.assertEqual(restored[0].entries[0].setpoint.command_template, "VOLT {value}")
        self.assertEqual(restored[0].entries[0].setpoint.max_value, 30)

    def test_export_stamps_version_4_for_static_tiles(self) -> None:
        from ComPort_Zone.control_panel_models import TilePlacement

        config = make_config("Docs")
        config.entries[0].tile = TilePlacement(kind="text")
        config.entries[0].body = "Bench notes"
        payload = export_control_panels_payload([config])
        # A static text/separator tile is a v4 feature -> highest stamp.
        self.assertEqual(payload[CONTROL_PANEL_EXPORT_KEY], CONTROL_PANEL_EXPORT_VERSION)
        self.assertEqual(CONTROL_PANEL_EXPORT_VERSION, 4)
        restored = import_control_panels_payload(json.loads(json.dumps(payload)))
        self.assertEqual(restored[0].entries[0].tile.kind, "text")
        self.assertEqual(restored[0].entries[0].body, "Bench notes")

    def test_import_rejects_non_object(self) -> None:
        with self.assertRaises(ValueError):
            import_control_panels_payload([1, 2, 3])

    def test_import_rejects_foreign_json(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            import_control_panels_payload({"schema_version": 5})
        self.assertIn("Not a ComPort Zone control_panel file", str(ctx.exception))

    def test_import_rejects_newer_version(self) -> None:
        payload = {CONTROL_PANEL_EXPORT_KEY: CONTROL_PANEL_EXPORT_VERSION + 1, "control_panels": []}
        with self.assertRaises(ValueError) as ctx:
            import_control_panels_payload(payload)
        self.assertIn("newer", str(ctx.exception))

    def test_import_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            import_control_panels_payload({CONTROL_PANEL_EXPORT_KEY: 1, "control_panels": []})

    def test_file_round_trip(self) -> None:
        path = Path(__file__).with_name("_tmp_control_panels_transfer.json")
        try:
            count = write_control_panels_json(path, [make_config("PSU")])
            self.assertEqual(count, 1)
            restored = read_control_panels_json(path)
            self.assertEqual(restored[0].name, "PSU")
        finally:
            path.unlink(missing_ok=True)


class MergeImportedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.control_panels: list[ControlPanelConfig] = []
        self.catalog = ControlPanelCatalog(self.control_panels)

    def test_id_collision_regenerates(self) -> None:
        existing = self.catalog.add(make_config("PSU", config_id="fixed"))
        incoming = make_config("Other", config_id="fixed")
        result = merge_imported(self.catalog, [incoming])
        self.assertEqual(result.imported_count, 1)
        self.assertNotEqual(incoming.id, existing.id)

    def test_name_collision_renames_by_default(self) -> None:
        self.catalog.add(make_config("PSU"))
        result = merge_imported(self.catalog, [make_config("PSU")])
        self.assertEqual(result.renamed_count, 1)
        self.assertEqual(result.replaced_count, 0)
        self.assertEqual(sorted(config.name for config in self.control_panels), ["PSU", "PSU (2)"])

    def test_name_collision_replaces_when_requested(self) -> None:
        original = self.catalog.add(make_config("PSU"))
        result = merge_imported(self.catalog, [make_config("PSU")], replace_existing=True)
        self.assertEqual(result.replaced_count, 1)
        self.assertEqual(len(self.control_panels), 1)
        self.assertIsNone(self.catalog.by_id(original.id))

    def test_summary_text(self) -> None:
        self.catalog.add(make_config("PSU"))
        result = merge_imported(self.catalog, [make_config("PSU"), make_config("New")])
        self.assertIn("Imported 2 control_panel(s)", result.summary())
        self.assertIn("1 renamed", result.summary())


if __name__ == "__main__":
    unittest.main()
