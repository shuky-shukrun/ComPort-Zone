import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ComPort_Zone import app as app_module
from ComPort_Zone.models import AppSettings, QuickCommand, SerialProfile, TerminalSessionState
from ComPort_Zone.storage import SettingsStore


class AppSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_restored_tab_loads_saved_session_state_without_prompt(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsStore(settings_path).save(
                    AppSettings(
                        restored_tabs=[
                            TerminalSessionState(
                                title="DUT",
                                profile_name="Default",
                                serial=SerialProfile(port="COM77", baudrate=57600, line_ending="LF"),
                                connected_on_launch=True,
                                terminal_text="previous output",
                                command_draft="status",
                                send_mode="Hex Bytes",
                            )
                        ]
                    )
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            old_restore_connection = app_module.MainWindow.restore_session_connection
            prompt_calls: list[str] = []
            reconnect_ports: list[str] = []
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: prompt_calls.append("current")
            app_module.MainWindow.prompt_session_settings = lambda self, session: prompt_calls.append("session")
            app_module.MainWindow.restore_session_connection = (
                lambda self, session: reconnect_ports.append(session.profile.port)
            )
            try:
                window = app_module.MainWindow()
                self.qt.processEvents()
                session = window.current_session()

                self.assertEqual(prompt_calls, [])
                self.assertEqual(reconnect_ports, ["COM77"])
                self.assertEqual(session.title, "DUT")
                self.assertEqual(session.profile.port, "COM77")
                self.assertEqual(session.profile.baudrate, 57600)
                self.assertEqual(session.profile.line_ending, "LF")
                self.assertEqual(session.terminal.toPlainText(), "previous output")
                self.assertEqual(session.command_input.text(), "status")
                self.assertEqual(session.mode_combo.currentText(), "Hex Bytes")
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                app_module.MainWindow.restore_session_connection = old_restore_connection
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_duplicate_tab_copies_live_session_state(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_duplicate.json")
        settings_path.unlink(missing_ok=True)
        try:
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            try:
                window = app_module.MainWindow()
                session = window.current_session()
                session.profile = SerialProfile(port="COM22", baudrate=230400, line_ending="None")
                session.terminal.setPlainText("captured output")
                session.command_input.setText("55 AA")
                session.mode_combo.setCurrentText("Hex Bytes")

                window.duplicate_session(window.tabs.currentIndex())
                duplicate = window.current_session()

                self.assertNotEqual(duplicate, session)
                self.assertEqual(duplicate.profile.port, "COM22")
                self.assertEqual(duplicate.profile.baudrate, 230400)
                self.assertEqual(duplicate.profile.line_ending, "None")
                self.assertEqual(duplicate.terminal.toPlainText(), "captured output")
                self.assertEqual(duplicate.command_input.text(), "55 AA")
                self.assertEqual(duplicate.mode_combo.currentText(), "Hex Bytes")
                self.assertFalse(duplicate.serial_client.is_connected)
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_quick_command_description_controls_tooltip(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_tooltip.json")
        settings_path.unlink(missing_ok=True)
        try:
            settings = AppSettings(
                quick_commands=[
                    QuickCommand(
                        id="with-description",
                        label="Read ID",
                        command="id?",
                        description="Reads the board identity from EEPROM.",
                        group="Factory",
                    ),
                    QuickCommand(
                        id="without-description",
                        label="Reset",
                        command="reset",
                        group="General",
                    ),
                ]
            )
            settings.profiles["Default"] = settings.capture_user_profile()
            self.assertTrue(
                SettingsStore(settings_path).save(settings)
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            try:
                window = app_module.MainWindow()
                session = window.current_session()

                self.assertEqual(
                    session.quick_list.item(0).toolTip(),
                    "Reads the board identity from EEPROM.",
                )
                self.assertEqual(session.quick_list.item(1).toolTip(), "General | reset")
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
