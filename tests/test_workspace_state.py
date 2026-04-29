import unittest
from pathlib import Path

from ComPort_Zone.models import AppSettings, SerialProfile, TerminalSessionState
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


if __name__ == "__main__":
    unittest.main()
