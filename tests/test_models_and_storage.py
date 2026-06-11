import json
from pathlib import Path
import unittest

from ComPort_Zone.dashboard_models import DashboardConfig, DashboardEntry, DashboardTabState
from ComPort_Zone.models import (
    AppSettings,
    CommandFileTabState,
    DASHBOARD_SCHEMA_FLOOR,
    LAN_SCHEMA_FLOOR,
    LanProfile,
    MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION,
    QuickCommand,
    QuickFile,
    SerialProfile,
    SETTINGS_SCHEMA_VERSION,
    TerminalSessionState,
    WorkspaceLayoutState,
    WorkspacePaneState,
    WorkspaceTabState,
    apply_line_ending,
)
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore


def cleanup_settings_artifacts(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_name(f"{path.name}.bak").unlink(missing_ok=True)
    for temp_path in path.parent.glob(f".{path.name}.*.tmp"):
        temp_path.unlink(missing_ok=True)


class ModelsAndStorageTests(unittest.TestCase):
    def test_apply_line_ending_respects_profile_setting(self) -> None:
        self.assertEqual(apply_line_ending("ping", "CRLF"), b"ping\r\n")
        self.assertEqual(apply_line_ending("ping", "None"), b"ping")

    def test_quick_file_favorite_round_trips(self) -> None:
        quick_file = QuickFile(label="Self-Test", path="C:/self-test.cpz", favorite=True)
        restored = QuickFile.from_dict(quick_file.to_dict())
        self.assertTrue(restored.favorite)
        self.assertFalse(QuickFile.from_dict({"path": "C:/x.cpz"}).favorite)

    def test_favorites_order_and_sort_modes_round_trip(self) -> None:
        settings = AppSettings(
            favorite_command_order=["c2", "c1"],
            favorite_file_order=["f2", "f1"],
            favorite_command_sort_mode="Title",
            favorite_file_sort_mode="Path",
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(restored.favorite_command_order, ["c2", "c1"])
        self.assertEqual(restored.favorite_file_order, ["f2", "f1"])
        self.assertEqual(restored.favorite_command_sort_mode, "Title")
        self.assertEqual(restored.favorite_file_sort_mode, "Path")
        # An unknown sort mode falls back to Custom.
        bad = settings.to_dict()
        bad["libraries"]["favorite_command_sort_mode"] = "Nonsense"
        self.assertEqual(AppSettings.from_dict(bad).favorite_command_sort_mode, "Custom")

    def test_favorites_layout_round_trips(self) -> None:
        settings = AppSettings(
            favorite_command_collapsed=True,
            favorite_file_collapsed=False,
            favorites_splitter_sizes=[300, 120],
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertTrue(restored.favorite_command_collapsed)
        self.assertFalse(restored.favorite_file_collapsed)
        self.assertEqual(restored.favorites_splitter_sizes, [300, 120])

    def test_default_quick_commands_are_scpi_general_commands(self) -> None:
        settings = AppSettings()

        self.assertEqual(
            [command.command for command in settings.quick_commands],
            ["*IDN?", "SYST:ERR:ALL?", "SYST:FIRM?"],
        )
        self.assertEqual(
            [command.label for command in settings.quick_commands],
            ["*IDN?", "SYST:ERR:ALL?", "SYST:FIRM?"],
        )
        self.assertEqual([command.group for command in settings.quick_commands], ["General"] * 3)
        # Every default command has a description; *IDN? and SYST:ERR:ALL? ship favourited.
        self.assertTrue(all(command.description for command in settings.quick_commands))
        self.assertEqual(
            [command.command for command in settings.quick_commands if command.favorite],
            ["*IDN?", "SYST:ERR:ALL?"],
        )
        # The bundled example command files are seeded as default quick files —
        # only the basic one is favourited by default.
        from ComPort_Zone.models import (
            EXAMPLE_COMMAND_FILE,
            EXAMPLE_MEASUREMENT_FILE,
            EXAMPLE_SELF_TEST_FILE,
        )

        self.assertEqual(
            [qf.label for qf in settings.quick_files],
            ["Example Commands", "Self-Test (EXPECT)", "Measurement (parameters)"],
        )
        self.assertEqual(
            [qf.label for qf in settings.quick_files if qf.favorite],
            ["Example Commands"],
        )
        self.assertTrue(settings.quick_files[0].path.endswith(".cpz"))
        self.assertTrue(EXAMPLE_COMMAND_FILE.exists())
        self.assertTrue(EXAMPLE_SELF_TEST_FILE.exists())
        self.assertTrue(EXAMPLE_MEASUREMENT_FILE.exists())
        self.assertTrue(settings.check_for_updates_on_launch)

    def test_settings_store_round_trip(self) -> None:
        settings = AppSettings(
            serial=SerialProfile(port="COM7", baudrate=57600, line_ending="LF"),
            command_history=["status", "reset"],
            quick_commands=[
                QuickCommand(
                    id="cmd-1",
                    label="Read ID",
                    command="id?",
                    description="Read the factory identity string.",
                    send_mode="Text",
                    group="Factory",
                    line_ending_override="LF",
                )
            ],
            quick_files=[
                QuickFile(id="file-1", label="Bring-up", path="C:/scripts/bringup.txt")
            ],
            quick_command_sort_mode="Group",
            quick_command_hidden_groups=["Debug"],
            quick_file_sort_mode="Path",
            restored_tabs=[
                TerminalSessionState(
                    title="DUT A",
                    serial=SerialProfile(port="COM9", baudrate=921600, line_ending="None"),
                    connected_on_launch=True,
                    terminal_text="boot ok",
                    command_draft="55 AA",
                    send_mode="Hex Bytes",
                ),
                TerminalSessionState(title="DUT B"),
            ],
            restored_command_files=[
                CommandFileTabState(
                    path="C:/scripts/bringup.txt",
                    text="SEND *IDN?\n",
                    dirty=True,
                )
            ],
            workspace_layout=WorkspaceLayoutState(
                orientation="horizontal",
                active_pane=1,
                panes=[
                    WorkspacePaneState(
                        tabs=[
                            WorkspaceTabState(
                                kind="terminal",
                                terminal=TerminalSessionState(title="DUT A"),
                            )
                        ]
                    ),
                    WorkspacePaneState(
                        tabs=[
                            WorkspaceTabState(
                                kind="command_file",
                                command_file=CommandFileTabState(path="C:/scripts/bringup.txt"),
                            )
                        ],
                        active_tab=0,
                    ),
                ],
                splitter_sizes=[480, 720],
            ),
            theme="Scope Amber",
            timestamps_enabled=False,
            terminal_font_size=13,
            terminal_font_family="Cascadia Mono",
            terminal_line_spacing=140,
            line_wrap_enabled=True,
            scrollback_size=20000,
            receive_display_mode="Text + Hex",
            drawer_collapsed=False,
            drawer_width=340,
            drawer_page_index=1,
            check_for_updates_on_launch=True,
        )
        settings_path = Path(__file__).with_name("_tmp_settings_storage_round_trip.json")
        cleanup_settings_artifacts(settings_path)
        try:
            service = SettingsService(SettingsStore(settings_path))

            self.assertTrue(service.save(settings))
            saved_payload = json.loads(settings_path.read_text(encoding="utf-8"))
            loaded = service.load()
            self.assertFalse(any(settings_path.parent.glob("*.tmp")))
        finally:
            cleanup_settings_artifacts(settings_path)

        self.assertEqual(saved_payload["schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(
            saved_payload["minimum_compatible_schema_version"],
            MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION,
        )
        self.assertNotIn("serial", saved_payload)
        self.assertEqual(saved_payload["transport"]["profile"]["port"], "COM7")
        self.assertEqual(saved_payload["app"]["terminal_font"]["size"], 13)
        self.assertEqual(saved_payload["app"]["terminal_font"]["line_spacing"], 140)
        self.assertEqual(saved_payload["app"]["drawer"]["width"], 340)
        self.assertEqual(saved_payload["app"]["drawer"]["page_index"], 1)
        self.assertTrue(saved_payload["app"]["updates"]["check_on_launch"])
        self.assertEqual(saved_payload["libraries"]["quick_commands"][0]["label"], "Read ID")
        self.assertEqual(saved_payload["workspace"]["terminal_tabs"][0]["title"], "DUT A")
        self.assertEqual(saved_payload["workspace"]["layout"]["active_pane"], 1)
        self.assertEqual(saved_payload["workspace"]["layout"]["splitter_sizes"], [480, 720])
        self.assertEqual(loaded.serial.port, "COM7")
        self.assertEqual(loaded.serial.baudrate, 57600)
        self.assertEqual(loaded.serial.line_ending, "LF")
        self.assertEqual(loaded.command_history, ["status", "reset"])
        self.assertEqual(len(loaded.quick_commands), 1)
        self.assertEqual(loaded.quick_commands[0].label, "Read ID")
        self.assertEqual(loaded.quick_commands[0].description, "Read the factory identity string.")
        self.assertEqual(loaded.quick_commands[0].line_ending_override, "LF")
        self.assertEqual(len(loaded.quick_files), 1)
        self.assertEqual(loaded.quick_files[0].label, "Bring-up")
        self.assertEqual(loaded.quick_files[0].path, "C:/scripts/bringup.txt")
        self.assertEqual(loaded.quick_command_sort_mode, "Group")
        self.assertEqual(loaded.quick_command_hidden_groups, ["Debug"])
        self.assertEqual(loaded.quick_file_sort_mode, "Path")
        self.assertEqual([tab.title for tab in loaded.restored_tabs], ["DUT A", "DUT B"])
        self.assertEqual(loaded.restored_tabs[0].serial.port, "COM9")
        self.assertEqual(loaded.restored_tabs[0].serial.baudrate, 921600)
        self.assertEqual(loaded.restored_tabs[0].serial.line_ending, "None")
        self.assertTrue(loaded.restored_tabs[0].connected_on_launch)
        self.assertEqual(loaded.restored_tabs[0].terminal_text, "boot ok")
        self.assertEqual(loaded.restored_tabs[0].command_draft, "55 AA")
        self.assertEqual(loaded.restored_tabs[0].send_mode, "Hex Bytes")
        self.assertEqual(len(loaded.restored_command_files), 1)
        self.assertEqual(loaded.restored_command_files[0].path, "C:/scripts/bringup.txt")
        self.assertEqual(loaded.restored_command_files[0].text, "SEND *IDN?\n")
        self.assertTrue(loaded.restored_command_files[0].dirty)
        self.assertEqual(loaded.workspace_layout.active_pane, 1)
        self.assertEqual(loaded.workspace_layout.panes[0].tabs[0].terminal.title, "DUT A")
        self.assertEqual(loaded.workspace_layout.panes[1].tabs[0].command_file.path, "C:/scripts/bringup.txt")
        self.assertEqual(loaded.theme, "Scope Amber")
        self.assertFalse(loaded.timestamps_enabled)
        self.assertEqual(loaded.terminal_font_size, 13)
        self.assertEqual(loaded.terminal_font_family, "Cascadia Mono")
        self.assertEqual(loaded.terminal_line_spacing, 140)
        self.assertTrue(loaded.line_wrap_enabled)
        self.assertEqual(loaded.scrollback_size, 20000)
        self.assertEqual(loaded.receive_display_mode, "Text + Hex")
        self.assertFalse(loaded.drawer_collapsed)
        self.assertEqual(loaded.drawer_width, 340)
        self.assertEqual(loaded.drawer_page_index, 1)
        self.assertTrue(loaded.check_for_updates_on_launch)

    def test_settings_store_keeps_previous_payload_as_backup(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_storage_backup.json")
        cleanup_settings_artifacts(settings_path)
        try:
            store = SettingsStore(settings_path)
            service = SettingsService(store)
            first = AppSettings(serial=SerialProfile(port="COM1"))
            second = AppSettings(serial=SerialProfile(port="COM2"))

            self.assertTrue(service.save(first))
            self.assertFalse(store.backup_path.exists())
            self.assertTrue(service.save(second))

            current_payload = json.loads(settings_path.read_text(encoding="utf-8"))
            backup_payload = json.loads(store.backup_path.read_text(encoding="utf-8"))
        finally:
            cleanup_settings_artifacts(settings_path)

        self.assertEqual(current_payload["transport"]["profile"]["port"], "COM2")
        self.assertEqual(backup_payload["transport"]["profile"]["port"], "COM1")

    def test_settings_load_uses_backup_when_primary_is_corrupt(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_storage_corrupt.json")
        cleanup_settings_artifacts(settings_path)
        try:
            store = SettingsStore(settings_path)
            service = SettingsService(store)
            backup = AppSettings(serial=SerialProfile(port="COM8")).to_dict()
            settings_path.write_text("{not json", encoding="utf-8")
            store.backup_path.write_text(json.dumps(backup), encoding="utf-8")

            loaded = service.load()
        finally:
            cleanup_settings_artifacts(settings_path)

        self.assertEqual(loaded.serial.port, "COM8")

    def test_settings_load_uses_backup_when_primary_schema_is_invalid(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_storage_schema.json")
        cleanup_settings_artifacts(settings_path)
        try:
            store = SettingsStore(settings_path)
            service = SettingsService(store)
            backup = AppSettings(serial=SerialProfile(port="COM9")).to_dict()
            settings_path.write_text(json.dumps({"schema_version": -1}), encoding="utf-8")
            store.backup_path.write_text(json.dumps(backup), encoding="utf-8")

            loaded = service.load()
        finally:
            cleanup_settings_artifacts(settings_path)

        self.assertEqual(loaded.serial.port, "COM9")

    def test_settings_file_uses_nested_schema_sections(self) -> None:
        settings = AppSettings.from_dict(
            {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "transport": {
                    "kind": "serial",
                    "profile": {"port": "COM12", "baudrate": 9600},
                },
                "app": {
                    "theme": "Scope Amber",
                    "terminal_font": {"size": 15},
                    "receive_display_mode": "Hex",
                },
                "libraries": {
                    "quick_commands": [
                        {
                            "id": "cmd-2",
                            "label": "Version",
                            "command": "version",
                        }
                    ],
                },
            }
        )

        self.assertEqual(settings.theme, "Scope Amber")
        self.assertEqual(settings.terminal_font_size, 15)
        self.assertEqual(settings.receive_display_mode, "Hex")
        self.assertEqual(settings.serial.port, "COM12")
        self.assertEqual(settings.quick_commands[0].command, "version")
        self.assertTrue(settings.check_for_updates_on_launch)

    def test_settings_accept_generic_serial_transport_profile(self) -> None:
        settings = AppSettings.from_dict(
            {
                "schema_version": SETTINGS_SCHEMA_VERSION,
                "transport": {
                    "kind": "serial",
                    "profile": {"port": "COM33", "baudrate": 57600},
                },
            }
        )

        self.assertEqual(settings.transport_kind, "serial")
        self.assertEqual(settings.serial.port, "COM33")
        self.assertEqual(settings.serial.baudrate, 57600)
        self.assertEqual(settings.to_dict()["transport"]["profile"]["port"], "COM33")

    def test_settings_accept_lan_transport_profile_and_marks_lan_floor_required(self) -> None:
        settings = AppSettings(
            transport_kind="lan",
            lan=LanProfile(host="192.168.1.50", port=5025, line_ending="LF"),
        )

        payload = settings.to_dict()
        loaded = AppSettings.from_dict(payload)

        self.assertEqual(payload["schema_version"], SETTINGS_SCHEMA_VERSION)
        # LAN content pins the file to the LAN feature floor, not to the
        # current schema version — otherwise every later schema bump would
        # needlessly lock LAN users out of older builds.
        self.assertEqual(payload["minimum_compatible_schema_version"], LAN_SCHEMA_FLOOR)
        self.assertEqual(payload["transport"]["kind"], "lan")
        self.assertEqual(payload["transport"]["profile"]["host"], "192.168.1.50")
        self.assertEqual(payload["transport"]["profile"]["port"], 5025)
        self.assertEqual(loaded.transport_kind, "lan")
        self.assertEqual(loaded.lan.host, "192.168.1.50")
        self.assertEqual(loaded.lan.port, 5025)
        self.assertEqual(loaded.lan.line_ending, "LF")

    def test_restored_tab_accepts_generic_serial_transport_profile(self) -> None:
        state = TerminalSessionState.from_dict(
            {
                "title": "DUT",
                "transport": {
                    "kind": "serial",
                    "profile": {"port": "COM44", "baudrate": 230400},
                },
            }
        )

        self.assertEqual(state.transport_kind, "serial")
        self.assertEqual(state.serial.port, "COM44")
        self.assertEqual(state.serial.baudrate, 230400)
        self.assertEqual(state.to_dict()["transport"]["profile"]["port"], "COM44")

    def test_restored_tab_accepts_lan_transport_profile(self) -> None:
        state = TerminalSessionState.from_dict(
            {
                "title": "LAN DUT",
                "transport": {
                    "kind": "lan",
                    "profile": {"host": "dut.local", "port": 9000, "line_ending": "LF"},
                },
            }
        )

        self.assertEqual(state.transport_kind, "lan")
        self.assertIsNotNone(state.lan)
        self.assertEqual(state.lan.host, "dut.local")
        self.assertEqual(state.lan.port, 9000)
        self.assertEqual(state.lan.line_ending, "LF")
        self.assertEqual(state.to_dict()["transport"]["profile"]["host"], "dut.local")

    def test_settings_service_rejects_missing_schema(self) -> None:
        service = SettingsService()

        with self.assertRaises(ValueError):
            service.settings_from_payload({"serial": {"port": "COM1"}})

    def test_settings_service_loads_future_schema_when_declared_compatible(self) -> None:
        service = SettingsService()
        payload = AppSettings(
            serial=SerialProfile(port="COM15"),
            quick_commands=[QuickCommand(id="cmd-upgrade", label="Version", command="version")],
            quick_files=[QuickFile(id="file-upgrade", label="Bring-up", path="C:/scripts/bringup.txt")],
        ).to_dict()
        payload["schema_version"] = SETTINGS_SCHEMA_VERSION + 1
        payload["minimum_compatible_schema_version"] = SETTINGS_SCHEMA_VERSION
        payload["future_section"] = {"ignored": True}

        loaded = service.settings_from_payload(payload)

        self.assertEqual(loaded.serial.port, "COM15")
        self.assertEqual([command.command for command in loaded.quick_commands], ["version"])
        self.assertEqual(
            [quick_file.path for quick_file in loaded.quick_files],
            ["C:/scripts/bringup.txt"],
        )

    def test_settings_load_uses_backup_when_future_schema_declares_break(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_storage_future_schema.json")
        cleanup_settings_artifacts(settings_path)
        try:
            store = SettingsStore(settings_path)
            service = SettingsService(store)
            future_payload = AppSettings(
                quick_commands=[QuickCommand(label="Future", command="future")],
                quick_files=[QuickFile(label="Future File", path="C:/future.txt")],
            ).to_dict()
            future_payload["schema_version"] = SETTINGS_SCHEMA_VERSION + 1
            future_payload["minimum_compatible_schema_version"] = SETTINGS_SCHEMA_VERSION + 1
            backup = AppSettings(
                serial=SerialProfile(port="COM16"),
                quick_commands=[QuickCommand(label="Backup", command="backup")],
                quick_files=[QuickFile(label="Backup File", path="C:/backup.txt")],
            ).to_dict()
            settings_path.write_text(json.dumps(future_payload), encoding="utf-8")
            store.backup_path.write_text(json.dumps(backup), encoding="utf-8")

            loaded = service.load()
        finally:
            cleanup_settings_artifacts(settings_path)

        self.assertEqual(loaded.serial.port, "COM16")
        self.assertEqual([command.command for command in loaded.quick_commands], ["backup"])
        self.assertEqual([quick_file.path for quick_file in loaded.quick_files], ["C:/backup.txt"])

    def test_settings_bundle_captures_all_preferences(self) -> None:
        settings = AppSettings(
            serial=SerialProfile(port="COM4", baudrate=230400),
            theme="Bench Light",
            terminal_font_size=14,
            receive_display_mode="Text + Hex",
            quick_commands=[QuickCommand(label="Errors", command="ERRORS")],
            quick_files=[QuickFile(label="Factory", path="C:/scripts/factory.txt")],
            quick_command_sort_mode="Title",
            quick_command_hidden_groups=["Factory"],
            quick_file_sort_mode="Title",
        )
        restored = AppSettings.from_dict(settings.to_dict())

        self.assertEqual(restored.theme, "Bench Light")
        self.assertEqual(restored.terminal_font_size, 14)
        self.assertEqual(restored.receive_display_mode, "Text + Hex")
        self.assertEqual(restored.quick_commands[0].command, "ERRORS")
        self.assertEqual(restored.quick_files[0].path, "C:/scripts/factory.txt")
        self.assertEqual(restored.quick_command_sort_mode, "Title")
        self.assertEqual(restored.quick_command_hidden_groups, ["Factory"])
        self.assertEqual(restored.quick_file_sort_mode, "Title")
        self.assertEqual(restored.serial.port, "COM4")


class DashboardSchemaTests(unittest.TestCase):
    """Schema v5: dashboard persistence and minimum-compatible floors."""

    @staticmethod
    def make_dashboard() -> DashboardConfig:
        return DashboardConfig(
            name="PSU Bench",
            entries=[DashboardEntry(label="Volts", command="MEAS:VOLT?")],
        )

    def test_plain_settings_keep_base_min_compat(self) -> None:
        payload = AppSettings().to_dict()
        self.assertEqual(payload["schema_version"], SETTINGS_SCHEMA_VERSION)
        self.assertEqual(
            payload["minimum_compatible_schema_version"],
            MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION,
        )

    def test_dashboards_raise_min_compat_to_dashboard_floor(self) -> None:
        payload = AppSettings(dashboards=[self.make_dashboard()]).to_dict()
        self.assertEqual(payload["minimum_compatible_schema_version"], DASHBOARD_SCHEMA_FLOOR)

    def test_restored_dashboard_tab_raises_min_compat(self) -> None:
        payload = AppSettings(
            restored_dashboards=[DashboardTabState(dashboard_id="abc")]
        ).to_dict()
        self.assertEqual(payload["minimum_compatible_schema_version"], DASHBOARD_SCHEMA_FLOOR)

    def test_dashboard_workspace_tab_raises_min_compat(self) -> None:
        layout = WorkspaceLayoutState(
            panes=[
                WorkspacePaneState(
                    tabs=[
                        WorkspaceTabState(
                            kind="dashboard", dashboard=DashboardTabState(dashboard_id="abc")
                        )
                    ]
                )
            ]
        )
        payload = AppSettings(workspace_layout=layout).to_dict()
        self.assertEqual(payload["minimum_compatible_schema_version"], DASHBOARD_SCHEMA_FLOOR)

    def test_lan_and_dashboards_take_highest_floor(self) -> None:
        settings = AppSettings(
            transport_kind="lan",
            lan=LanProfile(host="dut.local"),
            dashboards=[self.make_dashboard()],
        )
        payload = settings.to_dict()
        self.assertEqual(
            payload["minimum_compatible_schema_version"],
            max(LAN_SCHEMA_FLOOR, DASHBOARD_SCHEMA_FLOOR),
        )

    def test_dashboards_round_trip_through_settings(self) -> None:
        settings = AppSettings(
            dashboards=[self.make_dashboard()],
            restored_dashboards=[DashboardTabState(dashboard_id="abc", target_endpoint="COM7")],
        )
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(len(restored.dashboards), 1)
        self.assertEqual(restored.dashboards[0].name, "PSU Bench")
        self.assertEqual(restored.dashboards[0].entries[0].command, "MEAS:VOLT?")
        self.assertEqual(restored.restored_dashboards[0].target_endpoint, "COM7")

    def test_v4_payload_loads_without_dashboards(self) -> None:
        payload = AppSettings(serial=SerialProfile(port="COM9")).to_dict()
        payload["schema_version"] = 4
        payload["minimum_compatible_schema_version"] = 2
        payload["libraries"].pop("dashboards", None)
        payload["workspace"].pop("dashboard_tabs", None)

        loaded = SettingsService().settings_from_payload(payload)

        self.assertEqual(loaded.serial.port, "COM9")
        self.assertEqual(loaded.dashboards, [])
        self.assertEqual(loaded.restored_dashboards, [])

    def test_dashboard_workspace_tab_state_round_trips(self) -> None:
        tab = WorkspaceTabState(
            kind="dashboard",
            dashboard=DashboardTabState(
                dashboard_id="abc",
                target_endpoint="COM7",
                target_title="Terminal 1",
                polling_enabled=False,
            ),
        )
        restored = WorkspaceTabState.from_dict(json.loads(json.dumps(tab.to_dict())))
        self.assertEqual(restored.kind, "dashboard")
        assert restored.dashboard is not None
        self.assertEqual(restored.dashboard.dashboard_id, "abc")
        self.assertFalse(restored.dashboard.polling_enabled)
        self.assertIsNone(restored.terminal)


if __name__ == "__main__":
    unittest.main()
