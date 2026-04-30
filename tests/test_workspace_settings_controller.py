import unittest
from pathlib import Path

from ComPort_Zone.models import AppSettings, QuickCommand, QuickFile, SerialProfile, TerminalSessionState
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore
from ComPort_Zone.workspace_settings_controller import WorkspaceSettingsController
from ComPort_Zone.workspace_state import WorkspaceStateService


class FakeTerminal:
    def __init__(self, port: str = "COM7") -> None:
        self.profile = SerialProfile(port=port, baudrate=57600)

    def to_state(self) -> TerminalSessionState:
        return TerminalSessionState(title="DUT", serial=self.profile)


class FakeCommandEditor:
    path = None

    def text(self) -> str:
        return "SEND *IDN?\n"

    def is_dirty(self) -> bool:
        return True


class WorkspaceSettingsControllerTests(unittest.TestCase):
    def test_save_settings_captures_workspace_state_and_persists(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_workspace_settings_save.json")
        settings_path.unlink(missing_ok=True)
        settings = AppSettings()
        terminal = FakeTerminal()
        refresh_calls: list[str] = []
        sync_calls: list[str] = []
        statuses: list[str] = []
        controller = WorkspaceSettingsController(
            settings_service=SettingsService(SettingsStore(settings_path)),
            workspace_state_service=WorkspaceStateService(),
            settings_supplier=lambda: settings,
            set_settings=lambda value: None,
            is_loading=lambda: False,
            set_loading=lambda value: None,
            refresh_quick_actions=lambda: refresh_calls.append("refresh"),
            sync_quick_actions=lambda: sync_calls.append("sync"),
            active_session_supplier=lambda: terminal,
            terminal_sessions_supplier=lambda: [terminal],
            command_file_editors_supplier=lambda: [FakeCommandEditor()],
            command_history_supplier=lambda: ["status"],
            window_size_supplier=lambda: (900, 640),
            clear_workspace=lambda: None,
            rebuild_runtime_state=lambda value: None,
            restore_workspace=lambda: None,
            apply_settings_to_ui=lambda: None,
            set_status=statuses.append,
        )
        try:
            self.assertTrue(controller.save_settings())

            saved = SettingsService(SettingsStore(settings_path)).load()
            self.assertEqual(refresh_calls, ["refresh"])
            self.assertEqual(sync_calls, ["sync"])
            self.assertEqual(statuses, [])
            self.assertEqual(settings.serial.port, "COM7")
            self.assertEqual(settings.command_history, ["status"])
            self.assertEqual(settings.window_width, 900)
            self.assertEqual(settings.restored_tabs[0].title, "DUT")
            self.assertEqual(settings.restored_command_files[0].text, "SEND *IDN?\n")
            self.assertEqual(saved.serial.port, "COM7")
            self.assertEqual(saved.command_history, ["status"])
        finally:
            settings_path.unlink(missing_ok=True)

    def test_save_settings_noops_while_loading(self) -> None:
        settings = AppSettings()
        calls: list[str] = []
        controller = WorkspaceSettingsController(
            settings_service=SettingsService(SettingsStore(Path(__file__).with_name("_tmp_unused.json"))),
            workspace_state_service=WorkspaceStateService(),
            settings_supplier=lambda: settings,
            set_settings=lambda value: calls.append("set"),
            is_loading=lambda: True,
            set_loading=lambda value: calls.append("loading"),
            refresh_quick_actions=lambda: calls.append("refresh"),
            sync_quick_actions=lambda: calls.append("sync"),
            active_session_supplier=lambda: None,
            terminal_sessions_supplier=lambda: [],
            command_file_editors_supplier=lambda: [],
            command_history_supplier=lambda: [],
            window_size_supplier=lambda: (1, 1),
            clear_workspace=lambda: calls.append("clear"),
            rebuild_runtime_state=lambda value: calls.append("rebuild"),
            restore_workspace=lambda: calls.append("restore"),
            apply_settings_to_ui=lambda: calls.append("apply"),
            set_status=lambda value: calls.append(value),
        )

        self.assertTrue(controller.save_settings())
        self.assertEqual(calls, [])

    def test_apply_imported_settings_preserves_quick_actions_and_restores_workspace(self) -> None:
        current = AppSettings(
            quick_commands=[QuickCommand(label="Local", command="local")],
            quick_files=[QuickFile(label="Local File", path="C:/scripts/local.txt")],
            quick_command_sort_mode="Group",
            quick_command_hidden_groups=["Hidden"],
            quick_file_sort_mode="Path",
        )
        imported = AppSettings(
            theme="Bench Light",
            quick_commands=[QuickCommand(label="Imported", command="imported")],
            quick_files=[QuickFile(label="Imported File", path="C:/scripts/imported.txt")],
            restored_tabs=[TerminalSessionState(title="Imported DUT", serial=SerialProfile(port="COM12"))],
        )
        loading = False
        calls: list[str] = []

        def set_settings(value: AppSettings) -> None:
            nonlocal current
            current = value
            calls.append("set-settings")

        def set_loading(value: bool) -> None:
            nonlocal loading
            loading = value
            calls.append(f"loading:{value}")

        controller = WorkspaceSettingsController(
            settings_service=SettingsService(SettingsStore(Path(__file__).with_name("_tmp_unused_apply.json"))),
            workspace_state_service=WorkspaceStateService(),
            settings_supplier=lambda: current,
            set_settings=set_settings,
            is_loading=lambda: loading,
            set_loading=set_loading,
            refresh_quick_actions=lambda: calls.append("refresh"),
            sync_quick_actions=lambda: calls.append("sync"),
            active_session_supplier=lambda: None,
            terminal_sessions_supplier=lambda: [],
            command_file_editors_supplier=lambda: [],
            command_history_supplier=lambda: [],
            window_size_supplier=lambda: (1, 1),
            clear_workspace=lambda: calls.append("clear"),
            rebuild_runtime_state=lambda value: calls.append(f"rebuild:{value.theme}"),
            restore_workspace=lambda: calls.append("restore"),
            apply_settings_to_ui=lambda: calls.append("apply-ui"),
            set_status=lambda value: calls.append(value),
        )

        controller.apply_imported_settings(imported)

        self.assertEqual(current.theme, "Bench Light")
        self.assertEqual([command.command for command in current.quick_commands], ["local"])
        self.assertEqual([quick_file.path for quick_file in current.quick_files], ["C:/scripts/local.txt"])
        self.assertEqual(current.quick_command_sort_mode, "Group")
        self.assertEqual(current.quick_command_hidden_groups, ["Hidden"])
        self.assertEqual(current.quick_file_sort_mode, "Path")
        self.assertFalse(loading)
        self.assertEqual(
            calls,
            [
                "refresh",
                "sync",
                "clear",
                "loading:True",
                "set-settings",
                "rebuild:Bench Light",
                "restore",
                "loading:False",
                "apply-ui",
            ],
        )


if __name__ == "__main__":
    unittest.main()
