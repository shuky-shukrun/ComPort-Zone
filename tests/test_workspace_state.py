import unittest
from pathlib import Path

from ComPort_Zone.models import AppSettings, CommandFileTabState, LanProfile, SerialProfile, TerminalSessionState
from ComPort_Zone.workspace_state import WorkspaceStateService


class FakeTerminalSession:
    def __init__(self, profile: SerialProfile, state: TerminalSessionState) -> None:
        self.profile = profile
        self._state = state

    def to_state(self) -> TerminalSessionState:
        return self._state


class FakeCommandFileEditor:
    def __init__(self, path: Path | None, text: str, dirty: bool) -> None:
        self.path = path
        self._text = text
        self._dirty = dirty

    def text(self) -> str:
        return self._text

    def is_dirty(self) -> bool:
        return self._dirty


class FakeRestoreTarget:
    def __init__(self, *, count_additions: bool = True) -> None:
        self.count_additions = count_additions
        self.sessions: list[tuple[TerminalSessionState | None, bool]] = []
        self.command_files: list[tuple[Path | None, CommandFileTabState | None]] = []
        self.prompt_count = 0

    def add_session(
        self,
        state: TerminalSessionState | None = None,
        *,
        prompt_settings: bool = True,
    ) -> object:
        self.sessions.append((state, prompt_settings))
        return object()

    def add_command_file_tab(
        self,
        path: Path | None = None,
        state: CommandFileTabState | None = None,
    ) -> object:
        self.command_files.append((path, state))
        return object()

    def prompt_current_session_settings(self) -> None:
        self.prompt_count += 1

    def workspace_tab_count(self) -> int:
        if not self.count_additions:
            return 0
        return len(self.sessions) + len(self.command_files)


class WorkspaceStateServiceTests(unittest.TestCase):
    def test_capture_into_settings_updates_runtime_workspace_state(self) -> None:
        service = WorkspaceStateService()
        settings = AppSettings(serial=SerialProfile(port="COM1"))
        active = FakeTerminalSession(
            SerialProfile(port="COM7", baudrate=57600, line_ending="LF"),
            TerminalSessionState(
                title="DUT",
                serial=SerialProfile(port="COM7", baudrate=57600, line_ending="LF"),
                terminal_text="boot ok",
            ),
        )
        second = FakeTerminalSession(
            SerialProfile(port="COM8"),
            TerminalSessionState(title="Monitor", serial=SerialProfile(port="COM8")),
        )
        saved_path = Path("C:/scripts/saved.txt")
        dirty_path = Path("C:/scripts/dirty.txt")
        saved_file = FakeCommandFileEditor(saved_path, "not persisted", False)
        dirty_file = FakeCommandFileEditor(dirty_path, "SEND *IDN?\n", True)
        untitled_file = FakeCommandFileEditor(None, "WAIT 100\n", False)

        result = service.capture_into_settings(
            settings,
            active_session=active,
            terminal_sessions=[active, second],
            command_file_editors=[saved_file, dirty_file, untitled_file],
            command_history=["status", "reset"],
            window_width=1440,
            window_height=900,
        )

        self.assertIs(result, settings)
        self.assertEqual(settings.serial.port, "COM7")
        self.assertEqual(settings.serial.baudrate, 57600)
        self.assertEqual(settings.transport_kind, "serial")
        self.assertEqual(settings.transport_profile["port"], "COM7")
        self.assertEqual(settings.command_history, ["status", "reset"])
        self.assertEqual(settings.window_width, 1440)
        self.assertEqual(settings.window_height, 900)
        self.assertEqual([tab.title for tab in settings.restored_tabs], ["DUT", "Monitor"])
        self.assertEqual(settings.restored_tabs[0].terminal_text, "boot ok")
        self.assertEqual(settings.restored_command_files[0].path, str(saved_path))
        self.assertEqual(settings.restored_command_files[0].text, "")
        self.assertFalse(settings.restored_command_files[0].dirty)
        self.assertEqual(settings.restored_command_files[1].path, str(dirty_path))
        self.assertEqual(settings.restored_command_files[1].text, "SEND *IDN?\n")
        self.assertTrue(settings.restored_command_files[1].dirty)
        self.assertEqual(settings.restored_command_files[2].path, "")
        self.assertEqual(settings.restored_command_files[2].text, "WAIT 100\n")
        self.assertFalse(settings.restored_command_files[2].dirty)

    def test_capture_without_active_session_preserves_default_transport(self) -> None:
        service = WorkspaceStateService()
        settings = AppSettings(serial=SerialProfile(port="COM5"))

        service.capture_into_settings(
            settings,
            active_session=None,
            terminal_sessions=[],
            command_file_editors=[],
            command_history=[],
            window_width=1000,
            window_height=700,
        )

        self.assertEqual(settings.serial.port, "COM5")
        self.assertEqual(settings.window_width, 1000)
        self.assertEqual(settings.window_height, 700)
        self.assertEqual(settings.restored_tabs, [])
        self.assertEqual(settings.restored_command_files, [])

    def test_capture_active_lan_session_updates_default_transport(self) -> None:
        service = WorkspaceStateService()
        settings = AppSettings(serial=SerialProfile(port="COM1"))
        active = FakeTerminalSession(
            LanProfile(host="dut.local", port=5025),
            TerminalSessionState(
                title="LAN DUT",
                transport_kind="lan",
                transport_profile={"host": "dut.local", "port": 5025},
                lan=LanProfile(host="dut.local", port=5025),
            ),
        )

        service.capture_into_settings(
            settings,
            active_session=active,
            terminal_sessions=[active],
            command_file_editors=[],
            command_history=[],
            window_width=1000,
            window_height=700,
        )

        self.assertEqual(settings.transport_kind, "lan")
        self.assertEqual(settings.transport_profile["host"], "dut.local")
        self.assertEqual(settings.lan.host, "dut.local")
        self.assertEqual(settings.restored_tabs[0].transport_kind, "lan")

    def test_restore_adds_default_terminal_and_prompt_when_no_terminal_state(self) -> None:
        service = WorkspaceStateService()
        settings = AppSettings()
        target = FakeRestoreTarget()

        service.restore_from_settings(settings, target, prompt_first_settings=True)

        self.assertEqual(len(target.sessions), 1)
        state, prompt_settings = target.sessions[0]
        self.assertEqual(state.title, "Terminal 1")
        self.assertFalse(prompt_settings)
        self.assertEqual(target.prompt_count, 1)
        self.assertEqual(target.command_files, [])

    def test_restore_recreates_terminal_and_command_file_tabs(self) -> None:
        service = WorkspaceStateService()
        command_file = CommandFileTabState(
            path="C:/scripts/bringup.txt",
            text="SEND *IDN?\n",
            dirty=True,
        )
        settings = AppSettings(
            restored_tabs=[
                TerminalSessionState(title="DUT", serial=SerialProfile(port="COM7")),
                TerminalSessionState(title="Monitor", serial=SerialProfile(port="COM8")),
            ],
            restored_command_files=[command_file],
        )
        target = FakeRestoreTarget()

        service.restore_from_settings(settings, target, prompt_first_settings=True)

        self.assertEqual([state.title for state, _ in target.sessions if state], ["DUT", "Monitor"])
        self.assertEqual([prompt for _, prompt in target.sessions], [False, False])
        self.assertEqual(target.prompt_count, 0)
        self.assertEqual(len(target.command_files), 1)
        path, state = target.command_files[0]
        self.assertEqual(path, Path(command_file.path))
        self.assertIs(state, command_file)

    def test_restore_can_suppress_default_prompt(self) -> None:
        service = WorkspaceStateService()
        target = FakeRestoreTarget()

        service.restore_from_settings(AppSettings(), target, prompt_first_settings=False)

        self.assertEqual(len(target.sessions), 1)
        self.assertEqual(target.prompt_count, 0)

    def test_restore_guarantees_at_least_one_tab(self) -> None:
        service = WorkspaceStateService()
        target = FakeRestoreTarget(count_additions=False)

        service.restore_from_settings(
            AppSettings(restored_tabs=[TerminalSessionState(title="Ignored by count")]),
            target,
            prompt_first_settings=False,
        )

        self.assertEqual(len(target.sessions), 2)
        self.assertEqual(target.sessions[-1], (None, False))


if __name__ == "__main__":
    unittest.main()
