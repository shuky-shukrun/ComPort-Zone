"""Tests for the dashboard catalog and JSON import/export."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ComPort_Zone.dashboard_catalog import (
    DASHBOARD_EXPORT_KEY,
    DASHBOARD_EXPORT_VERSION,
    DashboardCatalog,
    export_dashboards_payload,
    import_dashboards_payload,
    merge_imported,
    read_dashboards_json,
    write_dashboards_json,
)
from ComPort_Zone.dashboard_models import DashboardConfig, DashboardEntry


def make_config(name: str, config_id: str | None = None) -> DashboardConfig:
    config = DashboardConfig(name=name, entries=[DashboardEntry(label="V", command="MEAS:VOLT?")])
    if config_id is not None:
        config.id = config_id
    return config


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboards: list[DashboardConfig] = []
        self.catalog = DashboardCatalog(self.dashboards)

    def test_add_mutates_backing_list(self) -> None:
        self.catalog.add(make_config("PSU"))
        self.assertEqual(len(self.dashboards), 1)

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
        payload = export_dashboards_payload(configs)
        # v1-shaped dashboards export as payload version 1 so v1 builds can
        # still import them (FR-39).
        self.assertEqual(payload[DASHBOARD_EXPORT_KEY], 1)
        restored = import_dashboards_payload(json.loads(json.dumps(payload)))
        self.assertEqual([config.to_dict() for config in restored], [config.to_dict() for config in configs])

    def test_export_stamps_version_2_for_v2_features(self) -> None:
        config = make_config("PSU")
        config.entries[0].poll_mode = "on_connect"
        payload = export_dashboards_payload([config])
        self.assertEqual(payload[DASHBOARD_EXPORT_KEY], DASHBOARD_EXPORT_VERSION)
        restored = import_dashboards_payload(json.loads(json.dumps(payload)))
        self.assertEqual(restored[0].entries[0].poll_mode, "on_connect")

    def test_import_rejects_non_object(self) -> None:
        with self.assertRaises(ValueError):
            import_dashboards_payload([1, 2, 3])

    def test_import_rejects_foreign_json(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            import_dashboards_payload({"schema_version": 5})
        self.assertIn("Not a ComPort Zone dashboard file", str(ctx.exception))

    def test_import_rejects_newer_version(self) -> None:
        payload = {DASHBOARD_EXPORT_KEY: DASHBOARD_EXPORT_VERSION + 1, "dashboards": []}
        with self.assertRaises(ValueError) as ctx:
            import_dashboards_payload(payload)
        self.assertIn("newer", str(ctx.exception))

    def test_import_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            import_dashboards_payload({DASHBOARD_EXPORT_KEY: 1, "dashboards": []})

    def test_file_round_trip(self) -> None:
        path = Path(__file__).with_name("_tmp_dashboards_transfer.json")
        try:
            count = write_dashboards_json(path, [make_config("PSU")])
            self.assertEqual(count, 1)
            restored = read_dashboards_json(path)
            self.assertEqual(restored[0].name, "PSU")
        finally:
            path.unlink(missing_ok=True)


class MergeImportedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboards: list[DashboardConfig] = []
        self.catalog = DashboardCatalog(self.dashboards)

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
        self.assertEqual(sorted(config.name for config in self.dashboards), ["PSU", "PSU (2)"])

    def test_name_collision_replaces_when_requested(self) -> None:
        original = self.catalog.add(make_config("PSU"))
        result = merge_imported(self.catalog, [make_config("PSU")], replace_existing=True)
        self.assertEqual(result.replaced_count, 1)
        self.assertEqual(len(self.dashboards), 1)
        self.assertIsNone(self.catalog.by_id(original.id))

    def test_summary_text(self) -> None:
        self.catalog.add(make_config("PSU"))
        result = merge_imported(self.catalog, [make_config("PSU"), make_config("New")])
        self.assertIn("Imported 2 dashboard(s)", result.summary())
        self.assertIn("1 renamed", result.summary())


if __name__ == "__main__":
    unittest.main()
