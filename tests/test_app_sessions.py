import json
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeyEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QMenu, QToolButton

from ComPort_Zone import app as app_module
from ComPort_Zone.batch import BatchRunSnapshot
from ComPort_Zone.lan_core import LanClient
from ComPort_Zone.models import (
    AppSettings,
    LanProfile,
    QuickCommand,
    QuickFile,
    SETTINGS_SCHEMA_VERSION,
    SerialProfile,
    TerminalSessionState,
)
from ComPort_Zone.serial_core import SerialClient, SerialEvent
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore
from ComPort_Zone.ui import main_window as main_window_module
from ComPort_Zone.version_check import VersionCheckResult


def drawer_action_rows(page) -> list[list[str]]:
    rows: list[list[str]] = []
    layout = page.layout()
    for index in range(layout.count()):
        row_layout = layout.itemAt(index).layout()
        if row_layout is None:
            continue
        row_texts = [
            row_layout.itemAt(item_index).widget().text()
            for item_index in range(row_layout.count())
            if isinstance(row_layout.itemAt(item_index).widget(), QPushButton)
        ]
        if row_texts:
            rows.append(row_texts)
    return rows


def cleanup_tmp_settings_artifacts() -> None:
    tests_dir = Path(__file__).parent
    for pattern in ("_tmp_settings*.json", "_tmp_settings*.json.bak", "._tmp_settings*.json.*.tmp"):
        for path in tests_dir.glob(pattern):
            path.unlink(missing_ok=True)


class AppSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        cleanup_tmp_settings_artifacts()

    def tearDown(self) -> None:
        cleanup_tmp_settings_artifacts()

    def test_restored_tab_loads_saved_session_state_without_prompt(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
                        check_for_updates_on_launch=False,
                        restored_tabs=[
                            TerminalSessionState(
                                title="DUT",
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
                cursor = QTextCursor(session.terminal.document())
                cursor.setPosition(session.terminal.display_text().index("previous"))
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                self.assertEqual(
                    cursor.charFormat().foreground().color().name().lower(),
                    window.theme.text.lower(),
                )
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

    def test_launch_focuses_terminal_command_line_at_draft_end(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_focus_terminal.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
                        check_for_updates_on_launch=False,
                        restored_tabs=[
                            TerminalSessionState(
                                title="DUT",
                                serial=SerialProfile(port="COM77", baudrate=57600, line_ending="LF"),
                                connected_on_launch=False,
                                command_draft="status",
                            )
                        ],
                    )
                )
            )
            old_config_path = app_module.default_config_path
            app_module.default_config_path = lambda: settings_path
            window = None
            try:
                window = app_module.MainWindow(defer_startup_actions=True)
                self.qt.processEvents()
                session = window.current_session()

                # Park the caret elsewhere; focusing the active tab must land it after
                # the restored draft ("status") so the user can type immediately.
                session.command_input.setCursorPosition(0)
                self.assertEqual(session.command_input.cursorPosition(), 0)

                window.focus_active_tab_input()
                self.assertEqual(session.command_input.cursorPosition(), len("status"))

                # The deferred launch sequence drives the same focus (no prompt fires
                # because a tab was restored).
                session.command_input.setCursorPosition(0)
                window.run_startup_actions()
                self.qt.processEvents()
                QTest.qWait(1)
                self.qt.processEvents()
                self.assertEqual(session.command_input.cursorPosition(), len("status"))
            finally:
                app_module.default_config_path = old_config_path
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_terminal_command_bar_collapses_to_connect_when_narrow(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_term_collapse.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=False)
                )
            )
            old_config_path = app_module.default_config_path
            app_module.default_config_path = lambda: settings_path
            window = None
            try:
                window = app_module.MainWindow(defer_startup_actions=True)
                window.setMinimumSize(260, 400)
                window.resize(1100, 700)
                window.show()
                self.qt.processEvents()
                window.set_drawer_collapsed(True)
                if window.workspace_tab_count() == 0:
                    window.add_session(prompt_settings=False)
                self.qt.processEvents()
                session = window.current_session()

                window.resize(1100, 700)
                for _ in range(4):
                    self.qt.processEvents()
                self.assertFalse(session.command_overflow_button.isVisible())
                self.assertTrue(session.wrap_toggle.isVisible())

                window.resize(300, 700)
                for _ in range(6):
                    self.qt.processEvents()
                # Only the connection button (plus ⋯) survives.
                self.assertTrue(session.connection_button.isVisible())
                self.assertTrue(session.command_overflow_button.isVisible())
                self.assertFalse(session.mode_combo.isVisible())
                self.assertFalse(session.wrap_toggle.isVisible())
                self.assertFalse(session.status_label.isVisible())

                session._build_command_overflow_menu()
                labels = [action.text() for action in session._command_overflow_menu.actions()]
                self.assertIn("Timestamps", labels)
            finally:
                app_module.default_config_path = old_config_path
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_launch_focus_targets_command_file_editor_caret_end(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_focus_editor.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=False)
                )
            )
            old_config_path = app_module.default_config_path
            app_module.default_config_path = lambda: settings_path
            window = None
            try:
                window = app_module.MainWindow(defer_startup_actions=True)
                self.qt.processEvents()
                editor = window.add_command_file_tab()
                editor.restore_text("LINE one\nLINE two", dirty=False)
                window.tabs.setCurrentWidget(editor)
                self.qt.processEvents()

                cursor = editor.editor.textCursor()
                cursor.setPosition(0)
                editor.editor.setTextCursor(cursor)
                self.assertEqual(editor.editor.textCursor().position(), 0)

                window.focus_active_tab_input()
                self.assertEqual(
                    editor.editor.textCursor().position(),
                    len("LINE one\nLINE two"),
                )
            finally:
                app_module.default_config_path = old_config_path
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_restored_connected_missing_port_skips_auto_connect(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore_missing_port.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
                        check_for_updates_on_launch=False,
                        restored_tabs=[
                            TerminalSessionState(
                                title="DUT",
                                serial=SerialProfile(port="COM77", auto_reconnect=True),
                                connected_on_launch=True,
                            )
                        ]
                    )
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            old_list_ports_snapshot = main_window_module.TerminalSessionWidget.list_ports_snapshot
            old_connect = SerialClient.connect
            connect_calls: list[str] = []
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            main_window_module.TerminalSessionWidget.list_ports_snapshot = lambda self: []
            SerialClient.connect = lambda self, profile: connect_calls.append(profile.port) or False
            try:
                window = app_module.MainWindow()
                self.qt.processEvents()
                QTest.qWait(1)
                self.qt.processEvents()
                session = window.current_session()

                self.assertEqual(connect_calls, [])
                self.assertEqual(session.connection_state(), "missing")
                self.assertIn("Auto-connect skipped", session.terminal.toPlainText())
                self.assertIn("Auto-connect skipped", window.footer.text())
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                main_window_module.TerminalSessionWidget.list_ports_snapshot = old_list_ports_snapshot
                SerialClient.connect = old_connect
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_restored_lan_tab_loads_and_auto_connects(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore_lan.json")
        settings_path.unlink(missing_ok=True)

        class FakeSocket:
            def close(self) -> None:
                pass

        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
                        check_for_updates_on_launch=False,
                        restored_tabs=[
                            TerminalSessionState(
                                title="Terminal 1",
                                transport_kind="lan",
                                transport_profile={
                                    "host": "192.168.1.50",
                                    "port": 5025,
                                    "line_ending": "LF",
                                },
                                lan=LanProfile(
                                    host="192.168.1.50",
                                    port=5025,
                                    line_ending="LF",
                                ),
                                connected_on_launch=True,
                            )
                        ],
                    )
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            old_lan_connect = LanClient.connect
            connect_calls: list[str] = []
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None

            def fake_lan_connect(client: LanClient, profile: LanProfile) -> bool:
                connect_calls.append(profile.endpoint())
                client._desired_profile = profile
                client._profile = profile
                client._socket = FakeSocket()
                return True

            LanClient.connect = fake_lan_connect
            try:
                window = app_module.MainWindow()
                self.qt.processEvents()
                QTest.qWait(1)
                self.qt.processEvents()
                session = window.current_session()

                self.assertEqual(connect_calls, ["192.168.1.50:5025"])
                self.assertEqual(session.transport_kind, "lan")
                self.assertEqual(session.profile.host, "192.168.1.50")
                self.assertEqual(session.profile.port, 5025)
                self.assertEqual(window.tabs.tabText(window.tabs.currentIndex()), "192.168.1.50:5025")
                self.assertEqual(
                    window.connection_status_label.text(),
                    "Connected | LAN 192.168.1.50:5025 | LF | Log off",
                )
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                LanClient.connect = old_lan_connect
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_background_restore_does_not_replace_active_connection_status(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore_background_status.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
                        check_for_updates_on_launch=False,
                        restored_tabs=[
                            TerminalSessionState(
                                title="Connected DUT",
                                serial=SerialProfile(port="COM11"),
                                connected_on_launch=True,
                            ),
                            TerminalSessionState(
                                title="Idle DUT",
                                serial=SerialProfile(port="COM22"),
                                connected_on_launch=False,
                            ),
                        ]
                    )
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            old_restore_connection = app_module.MainWindow.restore_session_connection
            old_list_ports_snapshot = main_window_module.TerminalSessionWidget.list_ports_snapshot
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            main_window_module.TerminalSessionWidget.list_ports_snapshot = lambda self: [
                {"device": "COM11", "description": "Connected", "hwid": ""},
                {"device": "COM22", "description": "Idle", "hwid": ""},
            ]
            app_module.MainWindow.restore_session_connection = (
                lambda self, session: session._update_connection_ui(True)
            )
            try:
                window = app_module.MainWindow()
                self.qt.processEvents()
                QTest.qWait(1)
                self.qt.processEvents()

                self.assertEqual(window.current_session().profile.port, "COM22")
                self.assertEqual(
                    window.connection_status_label.text(),
                    "Closed | COM22 | 115200 8N1 | CRLF | Log off",
                )
                self.assertEqual(window.connection_action_button.text(), "Connect")
                self.assertEqual(window.footer.text(), "Ready")
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                app_module.MainWindow.restore_session_connection = old_restore_connection
                main_window_module.TerminalSessionWidget.list_ports_snapshot = old_list_ports_snapshot
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_update_check_on_launch_setting_triggers_version_check(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_update_check_launch.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=True)
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            old_check_for_updates = app_module.MainWindow.check_for_updates
            calls: list[bool] = []
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            app_module.MainWindow.check_for_updates = (
                lambda self, *, automatic=False: calls.append(automatic)
            )
            try:
                window = app_module.MainWindow()
                self.qt.processEvents()
                QTest.qWait(1)
                self.qt.processEvents()

                self.assertEqual(calls, [True])
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                app_module.MainWindow.check_for_updates = old_check_for_updates
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_deferred_startup_actions_prompt_before_update_check(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_deferred_startup.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=True)
                )
            )
            old_config_path = app_module.default_config_path
            old_open_prompted_settings = app_module.MainWindow._open_prompted_session_settings
            old_check_for_updates = app_module.MainWindow.check_for_updates
            calls: list[str] = []
            window = None
            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow._open_prompted_session_settings = (
                lambda self, session: calls.append("settings")
            )
            app_module.MainWindow.check_for_updates = (
                lambda self, *, automatic=False: calls.append(f"update:{automatic}")
            )
            try:
                window = app_module.MainWindow(defer_startup_actions=True)
                self.qt.processEvents()

                self.assertEqual(calls, [])

                window.run_startup_actions()
                self.qt.processEvents()
                QTest.qWait(1)
                self.qt.processEvents()

                self.assertEqual(calls, ["settings", "update:True"])
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow._open_prompted_session_settings = old_open_prompted_settings
                app_module.MainWindow.check_for_updates = old_check_for_updates
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_manual_update_check_suggests_enabling_startup_checks(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_update_check_suggest.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=False)
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            old_version_update_dialog = main_window_module.VersionUpdateDialog
            dialog_calls: list[tuple[bool, bool]] = []
            window = None

            class FakeVersionUpdateDialog:
                def __init__(self, result, check_on_launch: bool, parent=None) -> None:
                    dialog_calls.append((result.update_available, check_on_launch))
                    self._check_on_launch = True

                def exec(self) -> int:
                    return 1

                def check_on_launch_enabled(self) -> bool:
                    return self._check_on_launch

            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            main_window_module.VersionUpdateDialog = FakeVersionUpdateDialog
            try:
                window = app_module.MainWindow()
                result = VersionCheckResult(
                    current_version="0.2.5",
                    latest_version="0.2.5",
                    release_name="ComPort Zone v0.2.5",
                    release_url="https://github.com/shuky-shukrun/ComPort-Zone/releases/tag/v0.2.5",
                    update_available=False,
                )

                window._show_version_check_result(result, automatic=False)
                saved = SettingsService(SettingsStore(settings_path)).load()

                self.assertEqual(dialog_calls, [(False, False)])
                self.assertTrue(window.settings.check_for_updates_on_launch)
                self.assertTrue(window.check_for_updates_on_launch_action.isChecked())
                self.assertTrue(saved.check_for_updates_on_launch)
            finally:
                app_module.default_config_path = old_config_path
                app_module.MainWindow.prompt_current_session_settings = old_prompt_current
                app_module.MainWindow.prompt_session_settings = old_prompt_session
                main_window_module.VersionUpdateDialog = old_version_update_dialog
                if window is not None:
                    for active_session in window.iter_sessions():
                        active_session.shutdown()
                    window.deleteLater()
                self.qt.processEvents()
        finally:
            settings_path.unlink(missing_ok=True)

    def test_automatic_update_check_sets_checking_status(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_update_check_status.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=False)
                )
            )
            old_config_path = app_module.default_config_path
            old_prompt_current = app_module.MainWindow.prompt_current_session_settings
            old_prompt_session = app_module.MainWindow.prompt_session_settings
            window = None

            class FakeSignal:
                def connect(self, _callback) -> None:
                    return None

            class FakeReply:
                finished = FakeSignal()

            class FakeNetwork:
                def __init__(self) -> None:
                    self.reply = FakeReply()

                def get(self, _request):
                    return self.reply

            app_module.default_config_path = lambda: settings_path
            app_module.MainWindow.prompt_current_session_settings = lambda self: None
            app_module.MainWindow.prompt_session_settings = lambda self, session: None
            try:
                window = app_module.MainWindow()
                fake_network = FakeNetwork()
                window.version_check_network = fake_network

                window.check_for_updates(automatic=True)

                self.assertEqual(window.footer.text(), "Checking for updates...")
                self.assertIs(window._version_check_reply, fake_network.reply)
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

    def test_split_right_shows_two_visible_workspace_panes(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_split_tabs.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
                        check_for_updates_on_launch=False,
                        restored_tabs=[
                            TerminalSessionState(title="Left", serial=SerialProfile(port="COM1")),
                            TerminalSessionState(title="Right", serial=SerialProfile(port="COM2")),
                        ],
                    )
                )
            )
            window = app_module.MainWindow()
            # Wide enough that neither split pane's command bar collapses its status
            # into the ⋯ overflow (that progressive collapse is covered elsewhere).
            window.resize(1500, 700)
            window.show()
            self.qt.processEvents()
            sessions = window.iter_sessions()
            window.set_drawer_collapsed(False)

            # Single pane: the gradient active-split-side edge stays hidden — with one
            # pane there is nothing to disambiguate.
            self.assertEqual(window.tabs.pane_count(), 1)
            self.assertFalse(sessions[0].property("activeWorkspaceTab"))
            self.assertFalse(sessions[1].property("activeWorkspaceTab"))

            window.split_tab_right(window.tabs.indexOf(sessions[1]))
            self.qt.processEvents()

            self.assertEqual(window.tabs.pane_count(), 2)
            self.assertEqual([pane.count() for pane in window.tabs.panes()], [1, 1])
            self.assertIs(window.tabs.currentWidget(), sessions[1])
            # The drawer is now one shared full-height side bar; per-tab drawers hidden.
            self.assertTrue(window.shared_drawer.isVisible())
            self.assertTrue(sessions[0].drawer.isHidden())
            self.assertTrue(sessions[1].drawer.isHidden())
            self.assertTrue(sessions[1].status_label.isVisible())
            self.assertTrue(sessions[1].connection_button.isVisible())
            self.assertFalse(window.connection_status_label.isVisible())
            self.assertTrue(window.tabs.panes()[1].property("activePane"))
            self.assertTrue(sessions[1].property("activeWorkspaceTab"))
            sizes = window.tabs.splitter.sizes()
            self.assertEqual(len(sizes), 2)
            self.assertGreater(sizes[0], 0)
            self.assertGreater(sizes[1], 0)

            sent_commands: list[str] = []

            def record_send(command: QuickCommand, *, record_command) -> None:
                sent_commands.append(command.command)

            sessions[1].controller.send_quick_command = record_send
            sessions[0].quick_list.setCurrentRow(0)
            window.tabs.setCurrentWidget(sessions[1])
            # The Send affordance is now the inline row action (clickable arrow).
            sessions[0].quick_list.actionTriggered.emit(sessions[0].quick_list.item(0), "send")
            self.qt.processEvents()

            self.assertEqual(sent_commands, [sessions[0].visible_quick_commands()[0].command])
            self.assertIs(window.current_session(), sessions[1])

            QTest.mouseClick(
                sessions[0].terminal.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                sessions[0].terminal.viewport().rect().center(),
            )
            self.qt.processEvents()

            self.assertIs(window.current_session(), sessions[0])
            self.assertTrue(window.tabs.panes()[0].property("activePane"))
            self.assertTrue(sessions[0].property("activeWorkspaceTab"))
            self.assertFalse(sessions[1].property("activeWorkspaceTab"))
            self.assertEqual(
                window.connection_status_label.text(),
                sessions[0].connection_status_text(),
            )

            # Re-joining back to one pane hides the edge again on both tabs.
            window.join_workspace_panes()
            self.qt.processEvents()
            self.assertEqual(window.tabs.pane_count(), 1)
            self.assertFalse(sessions[0].property("activeWorkspaceTab"))
            self.assertFalse(sessions[1].property("activeWorkspaceTab"))
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_terminal_status_chip_is_compact_clickable_and_replaces_status_bar(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_terminal_status_chip.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        old_open_settings = main_window_module.TerminalSessionWidget.open_connection_settings
        window = None
        opened: list[tuple[object, bool]] = []
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None

        def fake_open_settings(session, *, connect_after_accept: bool = True) -> bool:
            opened.append((session, connect_after_accept))
            return True

        main_window_module.TerminalSessionWidget.open_connection_settings = fake_open_settings
        try:
            window = app_module.MainWindow()
            window.show()
            self.qt.processEvents()
            session = window.current_session()

            self.assertTrue(window.connection_status_label.isHidden())
            self.assertTrue(window.connection_action_button.isHidden())
            self.assertTrue(session.status_label.isVisible())
            self.assertEqual(session.status_label.maximumWidth(), 220)
            self.assertIn("Click to open Connection Settings.", session.status_label.toolTip())

            QTest.mouseClick(
                session.status_label,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                session.status_label.rect().center(),
            )
            self.qt.processEvents()

            self.assertEqual(opened, [(session, True)])
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            main_window_module.TerminalSessionWidget.open_connection_settings = old_open_settings
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_terminal_command_file_controls_follow_runner_state(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_command_file_controls.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None

        class FakePort:
            is_open = True

            def close(self) -> None:
                self.is_open = False

        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            session = window.current_session()
            session.serial_client._serial = FakePort()
            session._update_connection_ui(True)

            self.assertTrue(session.script_pause_button.isHidden())
            self.assertTrue(session.script_resume_button.isHidden())
            self.assertTrue(session.script_stop_button.isHidden())
            # The "File idle/running/paused" status label is gone — run state is
            # narrated in the terminal as SYS messages instead.
            self.assertFalse(hasattr(session, "script_status_label"))

            session.toggle_pause()
            self.assertEqual(session.pause_label.text(), "RX paused")
            session._handle_event(SerialEvent(kind="rx", message="OK", raw=b"OK"))
            self.assertEqual(session.pause_label.text(), "RX paused (1)")
            session.toggle_pause()
            self.assertEqual(session.pause_label.text(), "")

            session.controller.script_snapshot = lambda: BatchRunSnapshot(is_running=True)  # type: ignore[method-assign]
            session._refresh_script_controls()
            self.assertFalse(session.script_pause_button.isHidden())
            self.assertTrue(session.script_pause_button.isEnabled())
            self.assertTrue(session.script_resume_button.isHidden())
            self.assertFalse(session.script_stop_button.isHidden())

            session.controller.script_snapshot = lambda: BatchRunSnapshot(  # type: ignore[method-assign]
                is_running=True,
                is_paused=True,
                pause_reason="connection",
                can_resume=False,
            )
            session._refresh_script_controls()
            self.assertTrue(session.script_pause_button.isHidden())
            self.assertFalse(session.script_resume_button.isHidden())
            self.assertFalse(session.script_resume_button.isEnabled())
            # The reconnect hint moved from the removed status label to the Resume button.
            self.assertIn("reconnect", session.script_resume_button.toolTip().lower())

            session.controller.script_snapshot = lambda: BatchRunSnapshot(  # type: ignore[method-assign]
                is_running=True,
                is_paused=True,
                pause_reason="connection",
                can_resume=True,
            )
            session._refresh_script_controls()
            self.assertTrue(session.script_resume_button.isEnabled())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_first_launch_opens_side_bar_on_favorites(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_first_launch.json")
        settings_path.unlink(missing_ok=True)
        settings_path.with_name(settings_path.name + ".bak").unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            # No settings file yet → genuine first launch: the side bar greets the
            # user open on the Favorites rail (page 0) rather than collapsed.
            window = app_module.MainWindow()
            window.resize(1180, 720)
            window.show()
            self.qt.processEvents()
            self.assertFalse(window.settings.drawer_collapsed)
            self.assertEqual(window.settings.drawer_page_index, 0)
            self.assertFalse(window.shared_drawer.panel.isHidden())
            self.assertEqual(window.shared_drawer.pages.currentIndex(), 0)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_returning_launch_keeps_saved_collapsed_side_bar(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_returning_drawer.json")
        settings_path.unlink(missing_ok=True)
        self.assertTrue(
            SettingsService(SettingsStore(settings_path)).save(
                AppSettings(check_for_updates_on_launch=False, drawer_collapsed=True)
            )
        )
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            # A settings file already exists → not a first launch, so the saved
            # collapsed state is honored (the first-run open does not fire).
            window = app_module.MainWindow()
            window.resize(1180, 720)
            window.show()
            self.qt.processEvents()
            self.assertTrue(window.settings.drawer_collapsed)
            self.assertTrue(window.shared_drawer.panel.isHidden())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_send_refreshes_history_only_not_the_saved_command_list(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_send_perf.json")
        settings_path.unlink(missing_ok=True)
        self.assertTrue(
            SettingsService(SettingsStore(settings_path)).save(
                AppSettings(
                    check_for_updates_on_launch=False,
                    quick_commands=[
                        QuickCommand(command=f"CMD{i}?", description=f"d{i}") for i in range(5)
                    ],
                )
            )
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
            window.resize(1180, 720)
            window.show()
            self.qt.processEvents()

            # Recording a sent command must refresh *only* the history list — rebuilding
            # the whole side bar (every saved-command row) on each Enter was a real
            # performance regression with hundreds of saved commands.
            full_calls: list[int] = []
            history_calls: list[int] = []
            real_full = window.refresh_shared_drawer
            real_history = window.refresh_shared_drawer_history

            def spy_full(*args, **kwargs):
                full_calls.append(1)
                return real_full(*args, **kwargs)

            def spy_history(*args, **kwargs):
                history_calls.append(1)
                return real_history(*args, **kwargs)

            window.refresh_shared_drawer = spy_full
            window.refresh_shared_drawer_history = spy_history

            window.record_command("PINGUNIQUE?")
            self.qt.processEvents()

            self.assertEqual(full_calls, [])  # no expensive full side-bar rebuild
            self.assertTrue(history_calls)  # history-only refresh ran
            history_list = window.shared_drawer.quick_history_list
            self.assertTrue(
                any("PINGUNIQUE?" in history_list.item(i).text() for i in range(history_list.count()))
            )
            # Saved-command list is untouched (still the five seeded commands).
            self.assertEqual(window.shared_drawer.quick_command_list.count(), 5)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_input_clears_after_enter_send_even_if_completion_reapplies(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_input_clear.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.timestamps_enabled = False
            session = window.current_session()
            sent: list[str] = []
            session.serial_client.send_text = lambda text, *_: sent.append(text)

            session.command_input.setText("status")
            session.send_from_input()
            session._apply_completion("status")
            self.qt.processEvents()
            self.qt.processEvents()

            self.assertEqual(sent, ["status"])
            self.assertEqual(session.command_input.text(), "")
            self.assertEqual(session.terminal.toPlainText(), "TX  status\n")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_integrated_send_suppresses_echo_and_marks_partial_failure(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_integrated_send.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.timestamps_enabled = False
            session = window.current_session()
            sent: list[str] = []

            def fake_send_text(text: str, *_args) -> None:
                sent.append(text)
                if text == "bad":
                    raise RuntimeError("write failed")
                session.serial_client.events.put(app_module.SerialEvent(kind="tx", message=text))

            session.serial_client.send_text = fake_send_text
            session.command_input.setText("ok\nbad\nlater")

            session.send_from_input()
            session._drain_events()
            self.qt.processEvents()

            self.assertEqual(sent, ["ok", "bad"])
            self.assertEqual(session.command_input.text(), "")
            self.assertEqual(session.terminal.toPlainText(), "TX  ok\nTX  bad\nTX  later\n")
            display_text = session.terminal.display_text()

            def color_for(fragment: str) -> str:
                cursor = QTextCursor(session.terminal.document())
                cursor.setPosition(display_text.index(fragment))
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                return cursor.charFormat().foreground().color().name().lower()

            from ComPort_Zone.themes import mix_hex

            # TX body is softened toward the terminal ink (mockup data tone).
            self.assertEqual(color_for("ok"), mix_hex(window.theme.tx, window.theme.text, 0.58).lower())
            self.assertEqual(color_for("bad"), window.theme.error.lower())
            self.assertEqual(color_for("later"), window.theme.error.lower())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_rename_tab_updates_title(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_rename.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        old_input_dialog = main_window_module.QInputDialog
        window = None
        calls: list[tuple[str, str, str]] = []

        class FakeInputDialog:
            @staticmethod
            def getText(parent, title, label, *, text=""):
                calls.append((title, label, text))
                return "Renamed DUT", True

        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        main_window_module.QInputDialog = FakeInputDialog
        try:
            window = app_module.MainWindow()
            session = window.current_session()
            self.assertIsNotNone(session)
            session.profile = SerialProfile(port="COM22")
            session.title = "Terminal 1"
            session.title_is_custom = False
            window.update_tab_titles()
            visible_title = window.tabs.tabText(window.tabs.currentIndex())

            window.rename_current_session()

            self.assertEqual(visible_title, "COM22")
            self.assertEqual(calls, [("Rename Tab", "Tab name", visible_title)])
            self.assertEqual(session.title, "Renamed DUT")
            self.assertTrue(session.title_is_custom)
            self.assertEqual(window.tabs.tabText(window.tabs.currentIndex()), "Renamed DUT")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            main_window_module.QInputDialog = old_input_dialog
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_new_tab_button_context_menu_uses_empty_tab_actions(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_new_tab_context.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            self.qt.processEvents()
            calls: list[QPoint] = []
            window.tab_context_menus.show_empty_at = lambda global_position: calls.append(global_position)
            position = QPoint(5, 6)

            window.tabs.new_tab_button.customContextMenuRequested.emit(position)

            self.assertEqual(calls, [window.tabs.new_tab_button.mapToGlobal(position)])
            menu = window.build_tab_context_menu(-1)
            titles = [action.text() for action in menu.actions() if not action.isSeparator()]
            self.assertEqual(
                titles,
                [
                    "New Terminal",
                    "New Command File",
                    "New Control Panel",
                    "Control Panels...",
                ],
            )
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_input_clears_after_quick_command_send(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_command_clear.json")
        settings_path.unlink(missing_ok=True)
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
            sent: list[tuple[str, str | None]] = []
            quick_command = QuickCommand(id="status-command", label="Status", command="status", line_ending_override="LF")
            window.settings.quick_commands = [quick_command]
            session.refresh_quick_commands(quick_command.id)
            session.quick_list.setCurrentRow(0)
            session.serial_client.send_text = lambda text, ending=None: sent.append((text, ending))

            session.command_input.setText("draft")
            session.send_selected_quick_command()
            self.qt.processEvents()
            self.qt.processEvents()

            self.assertEqual(sent, [("status", "LF")])
            self.assertEqual(session.command_input.text(), "")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_quick_file_play_runs_and_double_click_opens_editor(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_file_actions.json")
        script_path = Path(__file__).with_name("_tmp_actions_script.cmd")
        settings_path.unlink(missing_ok=True)
        script_path.write_text("*IDN?\n", encoding="utf-8")
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.delete_all_quick_files(confirm=False)  # drop the seeded example file
            window.add_quick_file(QuickFile(label="Script", path=str(script_path)))
            drawer = window.shared_drawer
            runs: list[str] = []
            for active_session in window.iter_sessions():
                active_session.run_script_path = lambda p, _runs=runs: _runs.append(str(p))

            editors_before = len(list(window.iter_command_file_editors()))
            # Double-clicking a quick file opens it in an editor (new tab when none active).
            drawer.quick_file_list.setCurrentRow(0)
            window._shared_open_file()
            self.assertEqual(len(list(window.iter_command_file_editors())), editors_before + 1)
            self.assertIsNotNone(window.current_command_file_editor())
            self.assertEqual(runs, [])

            # The play affordance runs the file in a terminal, even with the editor active.
            drawer.quick_file_list.setCurrentRow(0)
            window._shared_run_file()
            self.assertEqual(runs, [str(script_path)])
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            script_path.unlink(missing_ok=True)

    def test_favorites_are_a_starred_subset_of_saved_commands(self) -> None:
        from ComPort_Zone.models import QuickCommand
        from ComPort_Zone.quick_actions_panel import ROLE_ID

        settings_path = Path(__file__).with_name("_tmp_settings_favorites.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None

        def item_named(quick_list, text):
            return next(
                quick_list.item(i) for i in range(quick_list.count()) if quick_list.item(i).text() == text
            )

        try:
            window = app_module.MainWindow()
            drawer = window.shared_drawer
            # Count deltas (the app may ship seeded sample commands).
            saved0 = drawer.quick_command_list.count()
            fav0 = drawer.favorite_command_list.count()

            window.add_quick_command(QuickCommand(command="FAVT:A", favorite=True))
            window.add_quick_command(QuickCommand(command="FAVT:B"))

            # Favorites is the starred subset of saved commands.
            self.assertEqual(drawer.quick_command_list.count(), saved0 + 2)
            self.assertEqual(drawer.favorite_command_list.count(), fav0 + 1)

            # The star on a saved row toggles favorite membership.
            drawer.quick_command_list.actionTriggered.emit(item_named(drawer.quick_command_list, "FAVT:B"), "star")
            self.assertEqual(drawer.favorite_command_list.count(), fav0 + 2)

            # Favoriting from history adds the command to saved *and* favorites.
            window.record_command("FAVT:C")
            drawer.quick_history_list.actionTriggered.emit(item_named(drawer.quick_history_list, "FAVT:C"), "favorite")
            self.assertEqual(drawer.quick_command_list.count(), saved0 + 3)
            self.assertEqual(drawer.favorite_command_list.count(), fav0 + 3)
            # The history row's star shows filled (favourite) right after adding it.
            from ComPort_Zone.quick_actions_panel import ROLE_FAVORITE

            self.assertTrue(bool(item_named(drawer.quick_history_list, "FAVT:C").data(ROLE_FAVORITE)))

            # Saving an already-saved command from history does not duplicate it.
            window.record_command("FAVT:B")
            drawer.quick_history_list.actionTriggered.emit(item_named(drawer.quick_history_list, "FAVT:B"), "save")
            self.assertEqual(drawer.quick_command_list.count(), saved0 + 3)

            # Removing a favorited command from saved also removes it from favorites.
            window.delete_quick_command(str(item_named(drawer.quick_command_list, "FAVT:A").data(ROLE_ID)))
            self.assertEqual(drawer.quick_command_list.count(), saved0 + 2)
            self.assertEqual(drawer.favorite_command_list.count(), fav0 + 2)
            self.assertNotIn(
                "FAVT:A",
                [drawer.favorite_command_list.item(i).text() for i in range(drawer.favorite_command_list.count())],
            )

            # Removing from history drops the row.
            history_before = drawer.quick_history_list.count()
            drawer.quick_history_list.actionTriggered.emit(item_named(drawer.quick_history_list, "FAVT:C"), "remove")
            self.assertEqual(drawer.quick_history_list.count(), history_before - 1)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_favorite_row_remove_deletes_from_saved_but_star_only_unfavorites(self) -> None:
        # The inline ✕ on a favourite row removes the command from *saved* (and so
        # from favourites), while the star only drops it from favourites — and both
        # outcomes are mirrored across the saved and favourites lists.
        from ComPort_Zone.models import QuickCommand

        settings_path = Path(__file__).with_name("_tmp_settings_fav_row_remove.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None

        def texts(quick_list):
            return [quick_list.item(i).text() for i in range(quick_list.count())]

        def item_named(quick_list, text):
            return next(
                quick_list.item(i) for i in range(quick_list.count()) if quick_list.item(i).text() == text
            )

        try:
            window = app_module.MainWindow()
            drawer = window.shared_drawer
            window.add_quick_command(QuickCommand(command="FAVR:KEEP", favorite=True))
            window.add_quick_command(QuickCommand(command="FAVR:GONE", favorite=True))

            # The star on a favourite row only unfavourites it (stays in saved).
            drawer.favorite_command_list.actionTriggered.emit(
                item_named(drawer.favorite_command_list, "FAVR:KEEP"), "star"
            )
            self.assertNotIn("FAVR:KEEP", texts(drawer.favorite_command_list))
            self.assertIn("FAVR:KEEP", texts(drawer.quick_command_list))

            # The ✕ on a favourite row deletes it from saved (and so favourites).
            drawer.favorite_command_list.actionTriggered.emit(
                item_named(drawer.favorite_command_list, "FAVR:GONE"), "remove"
            )
            self.assertNotIn("FAVR:GONE", texts(drawer.favorite_command_list))
            self.assertNotIn("FAVR:GONE", texts(drawer.quick_command_list))
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_add_quick_file_opens_picker_then_prefills_dialog(self) -> None:
        # The Files "+" opens the file explorer first, then the editor dialog
        # pre-filled with the chosen file's name + path (both still editable).
        from PySide6.QtWidgets import QDialog, QFileDialog
        from ComPort_Zone.ui.dialogs import QuickFileDialog

        settings_path = Path(__file__).with_name("_tmp_settings_add_file_picker.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None

        chosen = str(Path(__file__).with_name("picked_bringup.txt"))
        try:
            window = app_module.MainWindow()
            window.delete_all_quick_files(confirm=False)  # drop any seeded sample file

            # Picker returns a file; the seeded editor dialog auto-accepts.
            with mock.patch.object(
                QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (chosen, ""))
            ), mock.patch.object(QuickFileDialog, "exec", lambda self: QDialog.DialogCode.Accepted):
                window.add_quick_file()  # the "+" entry point (no QuickFile passed)

            files = window.quick_files_snapshot()
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].label, Path(chosen).name)  # name defaults to the file name
            self.assertEqual(files[0].path, chosen)
            # The picker's directory is remembered for next time.
            self.assertEqual(window.settings.last_script_path, str(Path(chosen).parent))

            # Cancelling the picker adds nothing (no dialog, no row).
            with mock.patch.object(
                QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", ""))
            ):
                window.add_quick_file()
            self.assertEqual(len(window.quick_files_snapshot()), 1)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_quick_command_sidebar_has_csv_import_export_actions(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_command_sidebar_csv.json")
        settings_path.unlink(missing_ok=True)
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
            # Page 0 is Favorites (favourite commands + files); the Saved Commands
            # page (with the CSV import/export overflow) is page 1.
            quick_page = session.drawer_pages.widget(1)
            # CSV import/export moved off the button grid into the header overflow (⋯)
            # menu, which is now built lazily (aboutToShow) so it can fold in the
            # sort/group controls when collapsed.
            overflow_actions = []
            for button in quick_page.findChildren(QToolButton, "quickPanelHeaderButton"):
                menu = button.menu()
                if menu is None:
                    continue
                menu.aboutToShow.emit()
                overflow_actions.extend(action.text() for action in menu.actions())
            self.assertIn("Import CSV…", overflow_actions)
            self.assertIn("Export CSV…", overflow_actions)
            # The legacy 8-button grid is gone; primary actions are inline now.
            self.assertEqual(drawer_action_rows(quick_page), [])
            # The per-tab terminal drawer stays control_panel-free (the visible
            # shared drawer carries the ControlPanels page).
            self.assertEqual(session.drawer_pages.count(), 4)
            self.assertEqual(
                [button.toolTip() for button in session.drawer.rail_buttons],
                ["Favorites", "Saved Commands", "Files", "History"],
            )
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_drawer_width_and_page_are_shared_across_tabs(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_shared_drawer.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            # Give the window real width so the shared-drawer splitter math is not
            # squeezed below the drawer's minimum width.
            window.resize(1180, 720)
            first_session = window.current_session()
            window.add_session(prompt_settings=False)
            second_session = window.current_session()
            editor = window.add_command_file_tab()
            self.qt.processEvents()

            window.set_drawer_collapsed(False)
            first_session._select_drawer_page(1)
            self.qt.processEvents()

            # A single, shared, full-height side bar serves every tab; the page
            # selected from one tab is the page shown for all of them.
            self.assertIs(window.central_splitter.widget(0), window.shared_drawer)
            self.assertEqual(window.settings.drawer_page_index, 1)
            self.assertEqual(window.shared_drawer.pages.currentIndex(), 1)
            self.assertFalse(window.shared_drawer.panel.isHidden())

            # Width changes from one tab persist and resize the one shared drawer.
            window.set_drawer_width(360, source=first_session)
            window.tabs.setCurrentWidget(second_session)
            self.qt.processEvents()
            self.assertEqual(window.settings.drawer_width, 360)
            self.assertEqual(window.shared_drawer.maximumWidth(), 520)
            self.assertEqual(window.shared_drawer.pages.currentIndex(), 1)

            # Switching to the editor keeps the same shared drawer; per-tab docks
            # stay hidden so they never compete with it.
            window.tabs.setCurrentWidget(editor)
            self.qt.processEvents()
            self.assertFalse(window.shared_drawer.panel.isHidden())
            self.assertTrue(first_session.drawer.isHidden())
            self.assertTrue(second_session.drawer.isHidden())
            self.assertTrue(editor.workspace_drawer.isHidden())

            # Collapsing from any tab collapses the shared drawer everywhere.
            window.set_drawer_collapsed(True)
            self.qt.processEvents()
            self.assertTrue(window.settings.drawer_collapsed)
            self.assertTrue(window.shared_drawer.panel.isHidden())

            # Re-opening, then re-selecting the active page, toggles it shut again.
            window.set_drawer_collapsed(False)
            second_session._select_drawer_page(1)
            self.qt.processEvents()
            self.assertTrue(window.settings.drawer_collapsed)
            self.assertTrue(window.shared_drawer.panel.isHidden())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_file_menu_unifies_app_settings_import_export_dialog(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_file_menu_settings_dialog.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            file_titles = [action.text() for action in window.file_menu.actions()]
            self.assertIn("Import / Export", file_titles)

            import_export_titles = [
                action.text() for action in window.import_export_menu.actions()
            ]
            self.assertIn("App Settings Import / Export...", import_export_titles)
            self.assertNotIn("Import App Settings", import_export_titles)
            self.assertNotIn("Export App Settings", import_export_titles)

            dialog = app_module.AppSettingsTransferDialog(parent=window)
            label_text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
            self.assertIn("Quick Commands and Quick Files are not included", label_text)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_shift_delete_removes_input_text_from_history_only(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_shift_delete_history.json")
        settings_path.unlink(missing_ok=True)
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
            window.settings.quick_commands = [QuickCommand(id="quick-status", label="Status", command="status")]
            window.record_command("status")
            session.command_input.setText("status")

            event = QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_Delete,
                Qt.KeyboardModifier.ShiftModifier,
            )
            QApplication.sendEvent(session.command_input, event)
            self.qt.processEvents()

            self.assertEqual(window.history_catalog.all_commands(), [])
            self.assertEqual(session.history_store.all_commands(), [])
            self.assertEqual([command.command for command in window.settings.quick_commands], ["status"])
            self.assertEqual(session.command_input.text(), "")
            self.assertIn("status", session.completion_model.stringList())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_closed_connection_state_is_visible_and_actionable(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_connection_closed.json")
        settings_path.unlink(missing_ok=True)
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
            session.profile = SerialProfile(port="COM22", baudrate=115200, auto_reconnect=False)
            session._ports = [{"device": "COM22", "description": "Test port", "hwid": ""}]
            session._update_connection_ui(False)

            connect_calls: list[str] = []
            session.serial_client.connect = lambda profile: connect_calls.append(profile.port) or False

            self.assertEqual(window.tabs.tabText(window.tabs.currentIndex()), "COM22")
            self.assertEqual(
                window.tabs.tabBar().tabTextColor(window.tabs.currentIndex()).name().lower(),
                window.theme.muted.lower(),
            )
            # The prompt chevron and the typed draft gray out while disconnected, so
            # it reads as "nothing can be sent".
            self.assertEqual(session.command_input._prompt_color.lower(), window.theme.muted.lower())
            self.assertEqual(session.command_input._draft_color.lower(), window.theme.muted.lower())
            self.assertEqual(window.connection_status_label.text(), "Closed | COM22 | 115200 8N1 | CRLF | Log off")
            self.assertEqual(window.connection_action_button.text(), "Connect")

            window.connection_action_button.click()

            self.assertEqual(connect_calls, ["COM22"])
            self.assertEqual(window.connection_status_label.text(), "Closed | COM22 | 115200 8N1 | CRLF | Log off")
            self.assertEqual(window.connection_action_button.text(), "Connect")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_prompt_and_draft_ungray_when_the_port_connects(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_connection_ungray.json")
        settings_path.unlink(missing_ok=True)
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
            session.profile = SerialProfile(port="COM22", baudrate=115200, auto_reconnect=False)
            session._ports = [{"device": "COM22", "description": "Test port", "hwid": ""}]
            theme = window.theme
            command_input = session.command_input

            session._update_connection_ui(False)
            self.assertEqual(command_input._prompt_color.lower(), theme.muted.lower())
            self.assertEqual(command_input._draft_color.lower(), theme.muted.lower())

            # Connecting restores the live prompt + draft ink.
            session._connected = True
            session._update_connection_ui(True)
            self.assertEqual(command_input._prompt_color.lower(), theme.tx.lower())
            self.assertEqual(command_input._draft_color.lower(), theme.tx.lower())

            # Disconnecting grays it again.
            session._connected = False
            session._update_connection_ui(False)
            self.assertEqual(command_input._prompt_color.lower(), theme.muted.lower())
            self.assertEqual(command_input._draft_color.lower(), theme.muted.lower())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_retrying_connection_can_be_stopped_from_command_bar(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_connection_retry.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None

        class AliveThread:
            def is_alive(self) -> bool:
                return True

        try:
            window = app_module.MainWindow()
            session = window.current_session()
            session.profile = SerialProfile(port="COM99", baudrate=115200, auto_reconnect=True)
            session._ports = []
            session.serial_client._reconnect_thread = AliveThread()
            disconnect_calls: list[bool] = []

            def fake_disconnect() -> None:
                disconnect_calls.append(True)
                session.serial_client._reconnect_thread = None

            session.serial_client.disconnect = fake_disconnect
            session._update_connection_ui(False)

            self.assertEqual(window.tabs.tabText(window.tabs.currentIndex()), "COM99")
            self.assertEqual(
                window.tabs.tabBar().tabTextColor(window.tabs.currentIndex()).name().lower(),
                window.theme.status.lower(),
            )
            self.assertEqual(window.connection_action_button.text(), "Stop Retry")
            self.assertTrue(window.connection_status_label.text().startswith("Retrying | COM99"))
            # The prompt chevron spins instead of spamming "." into the transcript:
            # the ">" is swapped for an animated glyph at the cursor.
            self.assertTrue(session._retrying)
            self.assertTrue(session._retry_spinner_timer.isActive())
            self.assertNotIn(">", session.command_input.prompt)

            window.connection_action_button.click()

            self.assertEqual(disconnect_calls, [True])
            self.assertEqual(window.connection_action_button.text(), "Connect")
            self.assertTrue(window.connection_status_label.text().startswith("Missing | COM99"))
            # Leaving the retry state stops the spinner and restores the ">" prompt.
            self.assertFalse(session._retrying)
            self.assertFalse(session._retry_spinner_timer.isActive())
            self.assertIn(">", session.command_input.prompt)
            self.assertEqual(
                window.tabs.tabBar().tabTextColor(window.tabs.currentIndex()).name().lower(),
                window.theme.error.lower(),
            )
            self.assertIn("Auto-reconnect stopped.", session.terminal.toPlainText())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_lan_status_duplicate_and_command_file_target(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_lan_session.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None

        class FakeSocket:
            def close(self) -> None:
                pass

        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            session = window.current_session()
            session._replace_controller(
                LanProfile(host="dut.local", port=5555, line_ending="LF"),
                "lan",
            )
            session._update_connection_ui(False)

            self.assertEqual(window.tabs.tabText(window.tabs.currentIndex()), "dut.local:5555")
            self.assertEqual(
                window.connection_status_label.text(),
                "Closed | LAN dut.local:5555 | LF | Log off",
            )

            window.duplicate_current_session()
            duplicate = window.current_session()
            self.assertEqual(duplicate.transport_kind, "lan")
            self.assertEqual(duplicate.profile.host, "dut.local")
            self.assertEqual(duplicate.profile.port, 5555)
            self.assertFalse(duplicate.transport.is_connected)

            window.tabs.setCurrentWidget(session)
            session.serial_client._socket = FakeSocket()
            session._update_connection_ui(True)
            started: list[tuple[str, object, object]] = []
            session.run_script_text = lambda text, source_label="Editor buffer", source_path=None: (
                started.append((text, source_label, source_path)) or True
            )
            editor = window.add_command_file_tab()
            editor.setPlainText("SEND *IDN?\n")

            menu = QMenu(window)
            window.populate_run_editor_menu(menu, editor)
            actions = menu.actions()

            self.assertEqual(len(actions), 1)
            self.assertIn("LAN dut.local:5555", actions[0].text())
            actions[0].trigger()
            self.assertEqual(started, [("SEND *IDN?\n", "Untitled", None)])
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_double_click_connection_status_opens_serial_settings(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_connection_settings.json")
        settings_path.unlink(missing_ok=True)
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
            settings_calls: list[bool] = []
            session.open_connection_settings = (
                lambda *, connect_after_accept=True: settings_calls.append(connect_after_accept) or True
            )

            window.connection_status_label.doubleClicked.emit()

            self.assertEqual(settings_calls, [True])
            self.assertIn("Double-click to open Connection Settings.", window.connection_status_label.toolTip())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_command_file_opens_as_dirty_editor_tab(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_editor_tab.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            start_count = window.tabs.count()

            editor = window.add_command_file_tab()
            editor.setPlainText("SEND *IDN?\n")
            self.qt.processEvents()

            self.assertEqual(window.tabs.count(), start_count + 1)
            self.assertIs(window.current_command_file_editor(), editor)
            self.assertIn("Untitled", window.tabs.tabText(window.tabs.indexOf(editor)))
            self.assertIn("*", window.tabs.tabText(window.tabs.indexOf(editor)))
            # Editor tabs are connectionless: the shared connection chip/button are
            # hidden (no duplicated/cut-off status line); the editor pane shows its
            # own status. (Footer routing is covered by test_workspace_status.)
            self.assertTrue(window.connection_status_label.isHidden())
            self.assertTrue(window.connection_action_button.isHidden())
            self.assertTrue(hasattr(editor, "quick_command_list"))
            self.assertTrue(hasattr(editor, "quick_file_list"))
            self.assertEqual(editor.workspace_drawer_pages.count(), 3)
            self.assertEqual(editor.workspace_drawer_pages.currentIndex(), 0)
            rail_tooltips = [
                button.toolTip()
                for button in editor.workspace_drawer_rail.findChildren(QToolButton)
            ]
            # The editor rail now includes the settings/command-palette cog too.
            self.assertEqual(
                rail_tooltips,
                ["Favorites", "Saved Commands", "Files", "Settings & commands"],
            )
            # Editor primaries are inline now (insert command / open file); grid removed.
            self.assertEqual(drawer_action_rows(editor.workspace_drawer_pages.widget(0)), [])
            self.assertEqual(drawer_action_rows(editor.workspace_drawer_pages.widget(1)), [])
            self.assertEqual(editor.insert_quick_command_button.text(), "Insert")
            self.assertEqual(editor.open_quick_file_button.text(), "Open")
            self.assertNotIn("Validate", [button.text() for button in editor.findChildren(QPushButton)])
            self.assertNotIn("Quick command suggestions", [label.text() for label in editor.findChildren(QLabel)])
            editor._select_workspace_drawer_page(1)
            self.assertEqual(window.shared_drawer.pages.currentIndex(), 1)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_command_editor_line_number_and_current_line_colors_follow_light_theme(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_editor_light_theme.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            editor = window.add_command_file_tab()
            editor.setPlainText("SEND *IDN?\n")
            window.apply_theme("Bench Light")
            self.qt.processEvents()

            self.assertEqual(editor.editor.line_number_background.name().lower(), window.theme.surface_alt.lower())
            self.assertEqual(editor.editor.line_number_foreground.name().lower(), window.theme.muted.lower())
            self.assertEqual(editor.editor.current_line_background.name().lower(), window.theme.chip.lower())
            self.assertNotEqual(editor.editor.current_line_background.name().lower(), "#202020")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_command_file_run_menu_targets_connected_terminal(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_editor_run.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None

        class FakePort:
            is_open = True

            def close(self) -> None:
                self.is_open = False

        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            session = window.current_session()
            session.profile.port = "COM88"
            session.serial_client._serial = FakePort()
            started: list[tuple[str, object, object]] = []
            session.run_script_text = lambda text, source_label="Editor buffer", source_path=None: (
                started.append((text, source_label, source_path)) or True
            )
            editor = window.add_command_file_tab()
            editor.setPlainText("SEND *IDN?\n")

            menu = QMenu(window)
            window.populate_run_editor_menu(menu, editor)
            actions = menu.actions()
            editor.refresh_run_targets()

            self.assertEqual(len(actions), 1)
            self.assertIn("COM88", actions[0].text())
            self.assertIn("COM88", editor.run_target_combo.currentText())
            actions[0].trigger()
            self.assertEqual(started, [("SEND *IDN?\n", "Untitled", None)])
            self.assertIs(window.tabs.currentWidget(), session)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_ctrl_f_routes_to_editor_find_bar_when_editor_tab_active(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_editor_find.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.show()
            self.qt.processEvents()
            editor = window.add_command_file_tab()
            editor.setPlainText("SEND *IDN?\n")
            editor.search_overlay.hide()
            editor.editor.setFocus()
            self.qt.processEvents()

            QTest.keyClick(editor.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            self.qt.processEvents()

            self.assertTrue(editor.search_overlay.isVisible())
            self.assertFalse(editor.replace_input.isVisible())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_ctrl_h_routes_to_editor_replace_bar_when_editor_tab_active(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_editor_replace.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.show()
            self.qt.processEvents()
            editor = window.add_command_file_tab()
            editor.setPlainText("SEND *IDN?\n")
            editor.search_overlay.hide()
            editor.editor.setFocus()
            self.qt.processEvents()

            QTest.keyClick(editor.editor, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
            self.qt.processEvents()

            self.assertTrue(editor.search_overlay.isVisible())
            self.assertTrue(editor.replace_input.isVisible())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_connection_settings_refreshes_ports_while_open(self) -> None:
        ports = [
            [{"device": "COM1", "description": "USB Serial A"}],
        ]

        def list_ports() -> list[dict[str, str]]:
            return [dict(port) for port in ports[-1]]

        dialog = app_module.ConnectionSettingsDialog(
            SerialProfile(port="COM1"),
            list_ports(),
            ports_supplier=list_ports,
        )
        try:
            self.assertTrue(dialog.port_refresh_timer.isActive())
            self.assertEqual(dialog.port_refresh_timer.interval(), 1000)
            self.assertEqual(
                [dialog.port_combo.itemData(index) for index in range(dialog.port_combo.count())],
                ["COM1"],
            )

            ports.append(
                [
                    {"device": "COM1", "description": "USB Serial A"},
                    {"device": "COM2", "description": "USB Serial B"},
                ]
            )
            self.assertTrue(dialog.refresh_ports())
            self.assertEqual(
                [dialog.port_combo.itemData(index) for index in range(dialog.port_combo.count())],
                ["COM1", "COM2"],
            )
            self.assertEqual(dialog.profile().port, "COM1")

            dialog.port_combo.setEditText("COM99")
            ports.append(
                [
                    {"device": "COM1", "description": "USB Serial A"},
                    {"device": "COM2", "description": "USB Serial B"},
                    {"device": "COM3", "description": "USB Serial C"},
                ]
            )
            self.assertTrue(dialog.refresh_ports())
            self.assertEqual(dialog.port_combo.currentText(), "COM99")
            self.assertEqual(dialog.profile().port, "COM99")
        finally:
            dialog.reject()
            dialog.deleteLater()
            self.qt.processEvents()

    def test_rx_text_chunks_stream_without_extra_line_breaks(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_rx_stream.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.timestamps_enabled = False
            window.settings.receive_display_mode = "Text"
            session = window.current_session()

            session._render_event(app_module.SerialEvent(kind="tx", message="SINK:CURR?"))
            session._render_event(app_module.SerialEvent(kind="rx", message="1", raw=b"1"))
            session._render_event(app_module.SerialEvent(kind="rx", message="67.00\r\n", raw=b"67.00\r\n"))

            self.assertEqual(session.terminal.toPlainText(), "TX  SINK:CURR?\nRX  167.00\n")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
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
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(settings)
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

    def test_quick_commands_sort_and_group_visibility(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_sort.json")
        settings_path.unlink(missing_ok=True)
        try:
            settings = AppSettings(
                quick_commands=[
                    QuickCommand(id="zebra", label="Zebra", command="z", group="Beta"),
                    QuickCommand(id="alpha", label="Alpha", command="a", group="Beta"),
                    QuickCommand(id="cable", label="Cable", command="c", group="Alpha"),
                    QuickCommand(id="hidden", label="Hidden", command="h", group="Hidden"),
                ],
                quick_command_sort_mode="Group",
                quick_command_hidden_groups=["Hidden"],
            )
            self.assertTrue(SettingsService(SettingsStore(settings_path)).save(settings))
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

                def visible_ids() -> list[str]:
                    return [
                        str(session.quick_list.item(row).data(Qt.ItemDataRole.UserRole))
                        for row in range(session.quick_list.count())
                    ]

                self.assertEqual(visible_ids(), ["cable", "alpha", "zebra"])
                self.assertEqual(session.quick_sort_combo.currentData(), "Group")

                window.set_quick_command_sort_mode("Title")
                self.assertEqual(visible_ids(), ["alpha", "cable", "zebra"])
                self.assertFalse(session.quick_list.dragEnabled())

                window.set_quick_command_group_visible("Hidden", True)
                self.assertEqual(visible_ids(), ["alpha", "cable", "hidden", "zebra"])
                self.assertEqual(window.settings.quick_command_hidden_groups, [])
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

    def test_command_palette_entries_and_shortcut(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_command_palette.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.add_session(TerminalSessionState(title="Second"), prompt_settings=False)
            entries = window.command_palette_entries()
            titles = [entry.title for entry in entries]

            self.assertIn("Connect / Disconnect", titles)
            self.assertIn("Connection Settings", titles)
            self.assertIn("Run Command File", titles)
            self.assertIn("Pause / Resume Command File", titles)
            self.assertIn("New Command File", titles)
            self.assertIn("Open Command File Editor", titles)
            self.assertIn("Stop Command File", titles)
            self.assertIn("Run Selected Quick File", titles)
            self.assertIn("Edit Selected Quick File", titles)
            self.assertIn("Add Quick File", titles)
            self.assertIn("Clear Terminal", titles)
            self.assertIn("Clear Command History", titles)
            self.assertIn("Find / Search", titles)
            self.assertIn("Replace in Editor", titles)
            self.assertIn("Terminal Font Settings", titles)
            self.assertIn("Save Current Input as Quick Command", titles)
            self.assertIn("App Settings Import / Export", titles)
            self.assertNotIn("Import App Settings", titles)
            self.assertNotIn("Export App Settings", titles)
            self.assertIn("Import Quick Commands from CSV", titles)
            self.assertIn("Export Quick Commands to CSV", titles)
            self.assertIn("Delete All Quick Commands", titles)
            self.assertIn("Import Quick Files from CSV", titles)
            self.assertIn("Export Quick Files to CSV", titles)
            self.assertIn("Delete All Quick Files", titles)
            self.assertIn("Check for Updates", titles)
            self.assertTrue(any(title.startswith("Switch to Tab 1:") for title in titles))
            self.assertTrue(any(title == "Switch to Tab 2: Second" for title in titles))

            switch_first = next(entry for entry in entries if entry.title.startswith("Switch to Tab 1:"))
            self.assertEqual(window.tabs.currentIndex(), 1)
            switch_first.callback()
            self.assertEqual(window.tabs.currentIndex(), 0)

            palette_actions = [
                action
                for action in window.findChildren(QAction)
                if action.text() == "Command Palette"
            ]
            self.assertEqual(len(palette_actions), 1)
            self.assertEqual(palette_actions[0].shortcut().toString(), "Ctrl+Shift+P")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_connection_state_icons_map_to_themed_glyphs(self) -> None:
        from ComPort_Zone.icons import connection_state_icon

        self.assertEqual(connection_state_icon("connected"), "plug")
        self.assertEqual(connection_state_icon("closed"), "plug")
        self.assertEqual(connection_state_icon("retrying"), "stop")
        self.assertEqual(connection_state_icon("missing"), "refresh")
        self.assertEqual(connection_state_icon("no-port"), "cog")

    def test_command_bar_status_toggles_drive_timestamps_hex_and_log(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_status_toggles.json")
        log_path = settings_path.with_name("_tmp_status_toggles.log")
        settings_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.timestamps_enabled = False
            window.settings.receive_display_mode = "Text"
            window.apply_settings_to_ui()
            session = window.current_session()

            # A fresh, text-mode session shows all three toggles off.
            self.assertFalse(session.timestamp_toggle.isChecked())
            self.assertFalse(session.hex_toggle.isChecked())
            self.assertFalse(session.log_toggle.isChecked())

            # The hex toggle flips the global receive-display mode and back.
            session.hex_toggle.click()
            self.qt.processEvents()
            self.assertEqual(window.settings.receive_display_mode, "Hex")
            self.assertTrue(session.hex_toggle.isChecked())
            session.hex_toggle.click()
            self.qt.processEvents()
            self.assertEqual(window.settings.receive_display_mode, "Text")
            self.assertFalse(session.hex_toggle.isChecked())

            # The timestamp toggle flips the setting and the menu action with it.
            session.timestamp_toggle.click()
            self.qt.processEvents()
            self.assertTrue(window.settings.timestamps_enabled)
            self.assertTrue(window.timestamps_action.isChecked())

            # A second tab mirrors the shared timestamp/hex state.
            window.add_session(prompt_settings=False)
            second = window.current_session()
            self.assertTrue(second.timestamp_toggle.isChecked())
            window.set_receive_display_mode("Hex")
            self.qt.processEvents()
            self.assertTrue(session.hex_toggle.isChecked())
            self.assertTrue(second.hex_toggle.isChecked())

            # The log toggle tracks the session logger (no file dialog needed).
            session.controller.start_logging(str(log_path))
            session._sync_status_toggles()
            self.assertTrue(session.log_toggle.isChecked())
            session.controller.stop_logging()
            session._sync_status_toggles()
            self.assertFalse(session.log_toggle.isChecked())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)

    def test_terminal_view_context_menu_includes_terminal_controls(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_terminal_context_menu.json")
        settings_path.unlink(missing_ok=True)
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
            self.assertIsNotNone(session)
            session.terminal.setPlainText("captured output")

            window.settings.line_wrap_enabled = False
            window.settings.timestamps_enabled = False
            window.apply_settings_to_ui()

            menu = session.build_terminal_context_menu(session.terminal.viewport().rect().center())
            titles = [action.text() for action in menu.actions() if not action.isSeparator()]
            self.assertIn("Clear Terminal", titles)
            self.assertIn("Line Wrap", titles)
            self.assertIn("Show Timestamps", titles)

            line_wrap_action = next(action for action in menu.actions() if action.text() == "Line Wrap")
            timestamps_action = next(action for action in menu.actions() if action.text() == "Show Timestamps")
            clear_action = next(action for action in menu.actions() if action.text() == "Clear Terminal")

            self.assertTrue(line_wrap_action.isCheckable())
            self.assertFalse(line_wrap_action.isChecked())
            self.assertTrue(line_wrap_action.icon().isNull())
            self.assertTrue(timestamps_action.isCheckable())
            self.assertFalse(timestamps_action.isChecked())
            self.assertTrue(timestamps_action.icon().isNull())

            line_wrap_action.trigger()
            self.qt.processEvents()
            self.assertTrue(window.settings.line_wrap_enabled)
            self.assertTrue(window.wrap_action.isChecked())
            self.assertEqual(
                session.terminal.lineWrapMode(),
                session.terminal.LineWrapMode.WidgetWidth,
            )

            timestamps_action.trigger()
            self.qt.processEvents()
            self.assertTrue(window.settings.timestamps_enabled)
            self.assertTrue(window.timestamps_action.isChecked())

            session.terminal.setPlainText("OK\n")
            cursor = QTextCursor(session.terminal.document())
            cursor.setPosition(0)
            cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
            session.terminal.setTextCursor(cursor)
            session.replace_terminal_selection(session.text_to_hex("OK"))
            self.assertEqual(session.terminal.toPlainText(), "4F 4B\n")

            clear_action.trigger()
            self.assertEqual(session.terminal.toPlainText(), "")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_top_menus_group_workflow_actions(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_top_menus.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            menu_bar = window.menuBar()
            top_level = [action.text() for action in menu_bar.actions()]
            self.assertEqual(
                top_level,
                ["File", "Edit", "View", "Connection", "Terminal", "Tools", "Help"],
            )

            tools_titles = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Command Palette", tools_titles)
            self.assertIn("Run Command File", tools_titles)
            self.assertIn("Pause / Resume Command File", tools_titles)
            self.assertIn("Stop Command File", tools_titles)
            self.assertIn("Run in Terminal", tools_titles)
            self.assertIn("Add Saved Command...", tools_titles)
            self.assertIn("Add Saved File...", tools_titles)
            self.assertIn("Open Config Folder", tools_titles)
            stop_file_actions = [
                action
                for action in window.findChildren(QAction)
                if action.text() == "Stop Command File"
            ]
            self.assertTrue(any(action.shortcut().toString() == "Ctrl+." for action in stop_file_actions))

            file_titles = [action.text() for action in window.file_menu.actions()]
            self.assertIn("New Command File", file_titles)
            self.assertIn("Open Command File Editor", file_titles)
            self.assertIn("Open Recent", file_titles)
            self.assertIn("Save Command File", file_titles)
            self.assertIn("Send File...", file_titles)
            self.assertIn("Close Other Tabs", file_titles)
            self.assertIn("Preferences...", file_titles)

            connection_titles = [action.text() for action in window.connection_menu.actions()]
            self.assertIn("Connect / Disconnect", connection_titles)
            self.assertIn("Send Mode", connection_titles)
            self.assertIn("Line Ending", connection_titles)
            self.assertIn("DTR", connection_titles)
            self.assertIn("RTS", connection_titles)
            self.assertIn("Send Break", connection_titles)

            terminal_titles = [action.text() for action in window.terminal_menu.actions()]
            self.assertIn("Rename Tab", terminal_titles)
            self.assertIn("Clear Terminal", terminal_titles)
            self.assertIn("Start / Stop Log", terminal_titles)
            self.assertIn("Open Log Folder", terminal_titles)

            edit_titles = [action.text() for action in window.edit_menu.actions()]
            self.assertIn("Find", edit_titles)
            self.assertIn("Replace", edit_titles)
            self.assertIn("Convert Selection", edit_titles)
            self.assertIn("Clear Command History", edit_titles)

            help_titles = [action.text() for action in window.help_menu.actions()]
            self.assertIn("Keyboard Shortcuts...", help_titles)
            self.assertIn("Report a Bug", help_titles)
            self.assertIn("Check for Updates", help_titles)
            self.assertIn("Check for Updates on Launch", help_titles)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_about_dialog_includes_clickable_repository_link(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_about_dialog.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(check_for_updates_on_launch=False)
                )
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
                dialog = window.build_about_dialog()
                try:
                    label_texts = [label.text() for label in dialog.findChildren(QLabel)]
                    link_labels = [
                        label
                        for label in dialog.findChildren(QLabel)
                        if "github.com/shuky-shukrun/ComPort-Zone" in label.text()
                    ]

                    self.assertIn("ComPort Zone", label_texts)
                    self.assertEqual(len(link_labels), 1)
                    self.assertTrue(link_labels[0].openExternalLinks())
                finally:
                    dialog.deleteLater()
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

    def test_bulk_cleanup_actions_clear_history_quick_commands_and_files(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_bulk_cleanup.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            settings = AppSettings(
                command_history=["status", "measure?"],
                quick_commands=[
                    QuickCommand(id="status-command", label="Status", command="status", group="General"),
                    QuickCommand(id="reset-command", label="Reset", command="reset", group="Factory"),
                ],
                quick_command_hidden_groups=["Factory"],
                quick_files=[
                    QuickFile(id="bringup-file", label="Bring-up", path="C:/scripts/bringup.txt"),
                ],
            )
            self.assertTrue(SettingsService(SettingsStore(settings_path)).save(settings))
            window = app_module.MainWindow()
            session = window.current_session()

            self.assertTrue(window.clear_command_history(confirm=False))
            self.assertEqual(window.history_catalog.all_commands(), [])
            self.assertEqual(session.history_store.all_commands(), [])

            self.assertTrue(window.delete_all_quick_commands(confirm=False))
            self.assertEqual(window.settings.quick_commands, [])
            self.assertEqual(window.settings.quick_command_hidden_groups, [])
            self.assertEqual(session.quick_list.count(), 0)

            self.assertTrue(window.delete_all_quick_files(confirm=False))
            self.assertEqual(window.settings.quick_files, [])
            self.assertEqual(session.quick_file_list.count(), 0)

            saved = SettingsService(SettingsStore(settings_path)).load()
            self.assertEqual(saved.command_history, [])
            self.assertEqual(saved.quick_commands, [])
            self.assertEqual(saved.quick_files, [])
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_terminal_font_settings_apply_to_active_terminal(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_terminal_font.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.timestamps_enabled = False
            session = window.current_session()
            session._render_event(app_module.SerialEvent(kind="tx", message="status"))
            session._render_event(app_module.SerialEvent(kind="rx", message="OK\r\n", raw=b"OK\r\n"))
            session._render_event(app_module.SerialEvent(kind="error", message="write failed"))
            window.settings.terminal_font_family = "Consolas"
            window.settings.terminal_font_size = 15

            window.apply_terminal_font_settings()

            self.assertEqual(session.terminal.font().pointSize(), 15)
            self.assertEqual(window.settings.terminal_font_family, "Consolas")
            display_text = session.terminal.display_text()

            def color_for(fragment: str) -> str:
                cursor = QTextCursor(session.terminal.document())
                cursor.setPosition(display_text.index(fragment))
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                return cursor.charFormat().foreground().color().name().lower()

            # Message bodies are softened toward the terminal ink (mockup data tone);
            # the TX/RX/ERR direction column carries the full role colour.
            from ComPort_Zone.themes import mix_hex

            self.assertEqual(color_for("status"), mix_hex(window.theme.tx, window.theme.text, 0.58).lower())
            self.assertEqual(color_for("OK"), mix_hex(window.theme.rx, window.theme.text, 0.5).lower())
            self.assertEqual(color_for("write failed"), window.theme.error.lower())
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_terminal_ctrl_wheel_changes_font_size(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_terminal_ctrl_wheel.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None

        class FakeWheelEvent:
            def __init__(self, y: int) -> None:
                self._angle_delta = QPoint(0, y)
                self.accepted = False

            def modifiers(self):
                return Qt.KeyboardModifier.ControlModifier

            def angleDelta(self) -> QPoint:
                return self._angle_delta

            def accept(self) -> None:
                self.accepted = True

        try:
            window = app_module.MainWindow()
            window.settings.terminal_font_size = 12
            session = window.current_session()

            increase = FakeWheelEvent(120)
            session.terminal.wheelEvent(increase)

            self.assertTrue(increase.accepted)
            self.assertEqual(window.settings.terminal_font_size, 13)
            self.assertEqual(session.terminal.font().pointSize(), 13)

            decrease = FakeWheelEvent(-120)
            session.terminal.wheelEvent(decrease)

            self.assertTrue(decrease.accepted)
            self.assertEqual(window.settings.terminal_font_size, 12)
            self.assertEqual(session.terminal.font().pointSize(), 12)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_terminal_font_controls_are_visible_and_described(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_terminal_font_controls.json")
        settings_path.unlink(missing_ok=True)
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
            labels = window.statusBar().findChildren(QLabel, "statusFontControlsLabel")
            buttons = window.statusBar().findChildren(QPushButton, "statusFontSizeButton")

            self.assertEqual([label.text() for label in labels], ["Font"])
            self.assertEqual([button.text() for button in buttons], ["-", "+"])
            self.assertTrue(all(button.width() >= 34 for button in buttons))
            self.assertEqual(buttons[0].toolTip(), "Decrease terminal and editor font size")
            self.assertEqual(buttons[1].toolTip(), "Increase terminal and editor font size")
            self.assertEqual(buttons[0].accessibleName(), "Decrease terminal and editor font size")
            self.assertEqual(buttons[1].accessibleName(), "Increase terminal and editor font size")
            self.assertEqual(session.command_bar.findChildren(QPushButton, "terminalFontSizeButton"), [])
            editor = window.add_command_file_tab()
            self.assertEqual(editor.findChildren(QPushButton, "editorFontSizeButton"), [])
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)

    def test_quick_file_list_runs_selected_file(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_files.json")
        script_path = Path(__file__).with_name("_tmp_quick_file.txt")
        settings_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        started_steps: list[object] = []
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            script_path.write_text("SEND status\n", encoding="utf-8")
            window = app_module.MainWindow()
            session = window.current_session()
            window.delete_all_quick_files(confirm=False)  # drop the seeded example file
            session.batch_runner.start = lambda steps: started_steps.append(steps)

            self.assertEqual(session.drawer_pages.count(), 4)
            session._select_drawer_page(2)  # Quick Files mode
            self.assertEqual(window.shared_drawer.pages.currentIndex(), 2)

            window.add_quick_file(QuickFile(label="Bring-up", path=str(script_path)))
            self.assertEqual(session.quick_file_list.count(), 1)
            self.assertEqual(session.quick_file_list.item(0).text(), "Bring-up")

            session.quick_file_list.setCurrentRow(0)
            menu = session.build_quick_file_context_menu(session.selected_quick_file_id())
            self.assertIn("Run", [action.text() for action in menu.actions()])
            self.assertNotIn("Send", [action.text() for action in menu.actions()])
            self.assertIn("Show in Explorer", [action.text() for action in menu.actions()])

            session.run_selected_quick_file()

            self.assertEqual(len(started_steps), 1)
            self.assertEqual([step.kind for step in started_steps[0]], ["send"])
            self.assertEqual([step.payload for step in started_steps[0]], ["status"])
            self.assertEqual(window.settings.last_script_path, str(script_path.parent))

            window.delete_quick_file(session.selected_quick_file_id())
            self.assertEqual(session.quick_file_list.count(), 0)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            script_path.unlink(missing_ok=True)

    def test_parameterized_command_file_uses_template_runner(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_parameterized_script.json")
        script_path = Path(__file__).with_name("_tmp_parameterized_script.txt")
        settings_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            script_path.write_text("SEND VOLT {{VOLT_VALUE}}\nWAIT {{DELAY=5}}\n", encoding="utf-8")
            window = app_module.MainWindow()
            session = window.current_session()
            collected_occurrences: list[object] = []
            started_templates: list[tuple[list[object], object]] = []
            session._collect_parameter_values = lambda occurrences: collected_occurrences.extend(occurrences) or ({"VOLT_VALUE": "3.3"}, set())
            session.parameter_prompt_bridge.prompt = lambda name, line_number, line_text: "3.3"
            session.batch_runner.start_template = lambda steps, resolver: started_templates.append((steps, resolver))

            session.run_script_path(script_path)

            self.assertEqual([occurrence.name for occurrence in collected_occurrences], ["VOLT_VALUE", "DELAY"])
            steps, resolver = started_templates[0]
            self.assertEqual(resolver(steps[0].line, steps[0].line_number), "SEND VOLT 3.3")
            self.assertEqual(resolver(steps[1].line, steps[1].line_number), "WAIT 5")
            self.assertEqual(window.settings.last_script_path, str(script_path.parent))
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            script_path.unlink(missing_ok=True)

    def test_quick_files_sort_modes(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_file_sort.json")
        settings_path.unlink(missing_ok=True)
        try:
            settings = AppSettings(
                quick_files=[
                    QuickFile(id="zebra", label="Zebra", path="C:/zeta/zebra.txt"),
                    QuickFile(id="alpha", label="Alpha", path="C:/omega/alpha.txt"),
                    QuickFile(id="cable", label="Cable", path="C:/alpha/cable.txt"),
                ],
                quick_file_sort_mode="Title",
            )
            self.assertTrue(SettingsService(SettingsStore(settings_path)).save(settings))
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

                def visible_ids() -> list[str]:
                    return [
                        str(session.quick_file_list.item(row).data(Qt.ItemDataRole.UserRole))
                        for row in range(session.quick_file_list.count())
                    ]

                self.assertEqual(visible_ids(), ["alpha", "cable", "zebra"])
                self.assertEqual(session.quick_file_sort_combo.currentData(), "Title")
                self.assertTrue(session.quick_file_list.dragEnabled())
                self.assertTrue(session.quick_file_move_up_button.isEnabled())
                session.quick_file_list.setCurrentRow(1)
                session.quick_file_move_up_button.click()
                self.assertEqual(window.settings.quick_file_sort_mode, "Custom")
                self.assertEqual([quick_file.id for quick_file in window.settings.quick_files], ["cable", "alpha", "zebra"])
                self.assertEqual(visible_ids(), ["cable", "alpha", "zebra"])

                window.set_quick_file_sort_mode("Path")
                self.assertEqual(visible_ids(), ["cable", "alpha", "zebra"])
                self.assertTrue(session.quick_file_list.dragEnabled())
                moved_item = session.quick_file_list.takeItem(2)
                session.quick_file_list.insertItem(0, moved_item)
                session.quick_file_list.setCurrentItem(moved_item)
                session.persist_quick_file_order()
                self.assertEqual(window.settings.quick_file_sort_mode, "Custom")
                self.assertEqual([quick_file.id for quick_file in window.settings.quick_files], ["zebra", "cable", "alpha"])
                self.assertEqual(visible_ids(), ["zebra", "cable", "alpha"])

                window.set_quick_file_sort_mode("Custom")
                self.assertEqual(visible_ids(), ["zebra", "cable", "alpha"])
                self.assertTrue(session.quick_file_list.dragEnabled())
                self.assertEqual(drawer_action_rows(session.drawer_pages.widget(1)), [])

                window.move_quick_file("cable", -1)
                self.assertEqual(visible_ids(), ["cable", "zebra", "alpha"])

                menu = session.build_quick_file_context_menu("cable")
                action_titles = [action.text() for action in menu.actions()]
                self.assertIn("Move Up", action_titles)
                self.assertIn("Move Down", action_titles)

                window.reorder_quick_files(["alpha", "zebra", "cable"], selected_id="alpha")
                self.assertEqual([quick_file.id for quick_file in window.settings.quick_files], ["alpha", "zebra", "cable"])
                self.assertEqual(visible_ids(), ["alpha", "zebra", "cable"])
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

    def test_quick_files_csv_export_import_round_trip(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_files_csv.json")
        csv_path = Path(__file__).with_name("_tmp_quick_files.csv")
        settings_path.unlink(missing_ok=True)
        csv_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.quick_files = [
                QuickFile(label="Bring-up", path="C:/scripts/bringup.txt"),
                QuickFile(label="Factory Check", path="C:/scripts/factory-check.scr"),
            ]

            self.assertEqual(window.export_quick_files_to_csv(csv_path), 2)
            self.assertTrue(csv_path.read_text(encoding="utf-8-sig").startswith("label,path"))

            window.settings.quick_files = []
            result = window.import_quick_files_from_csv(csv_path)

            self.assertEqual(result.imported_count, 2)
            self.assertEqual(result.skipped_count, 0)
            self.assertEqual([quick_file.label for quick_file in window.settings.quick_files], ["Bring-up", "Factory Check"])
            self.assertEqual(window.settings.quick_files[0].path, "C:/scripts/bringup.txt")
            self.assertEqual(window.settings.quick_files[1].path, "C:/scripts/factory-check.scr")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)

    def test_quick_file_csv_import_can_append_or_replace(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_file_import_mode.json")
        csv_path = Path(__file__).with_name("_tmp_quick_file_import_mode.csv")
        settings_path.unlink(missing_ok=True)
        csv_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            csv_path.write_text(
                "label,path\n"
                "Bring-up,C:/scripts/bringup.txt\n"
                "Factory,C:/scripts/factory.txt\n",
                encoding="utf-8",
            )
            window = app_module.MainWindow()
            window.settings.quick_files = [
                QuickFile(label="Local Bring-up", path="C:/scripts/bringup.txt"),
                QuickFile(label="Local Only", path="C:/scripts/local.txt"),
            ]

            append_result = window.import_quick_files_from_csv(
                csv_path,
                options=app_module.QuickFileImportOptions(
                    replace_existing=False,
                    skip_duplicates=True,
                ),
            )

            self.assertEqual(append_result.imported_count, 1)
            self.assertEqual(append_result.skipped_count, 1)
            self.assertEqual(
                [quick_file.label for quick_file in window.settings.quick_files],
                ["Local Bring-up", "Local Only", "Factory"],
            )

            replace_result = window.import_quick_files_from_csv(
                csv_path,
                options=app_module.QuickFileImportOptions(
                    replace_existing=True,
                    skip_duplicates=False,
                ),
            )

            self.assertEqual(replace_result.imported_count, 2)
            self.assertEqual(replace_result.skipped_count, 0)
            self.assertEqual([quick_file.label for quick_file in window.settings.quick_files], ["Bring-up", "Factory"])
            self.assertEqual(window.settings.quick_files[0].path, "C:/scripts/bringup.txt")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)

    def test_quick_commands_csv_export_import_round_trip(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_quick_csv.json")
        csv_path = Path(__file__).with_name("_tmp_quick_commands.csv")
        settings_path.unlink(missing_ok=True)
        csv_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.quick_commands = [
                QuickCommand(
                    label="Read ID",
                    command="id?",
                    description="Read factory identity",
                    send_mode="Text",
                    group="Factory",
                    line_ending_override="LF",
                ),
                QuickCommand(
                    label="Wake Bytes",
                    command="55 AA 00",
                    send_mode="Hex Bytes",
                    group="Boot",
                ),
            ]

            self.assertEqual(window.export_quick_commands_to_csv(csv_path), 2)
            self.assertTrue(csv_path.read_text(encoding="utf-8-sig").startswith("label,command,description"))

            window.settings.quick_commands = []
            result = window.import_quick_commands_from_csv(csv_path)

            self.assertEqual(result.imported_count, 2)
            self.assertEqual(result.skipped_count, 0)
            self.assertEqual([command.label for command in window.settings.quick_commands], ["Read ID", "Wake Bytes"])
            self.assertEqual(window.settings.quick_commands[0].description, "Read factory identity")
            self.assertEqual(window.settings.quick_commands[0].line_ending_override, "LF")
            self.assertEqual(window.settings.quick_commands[1].send_mode, "Hex Bytes")
            self.assertEqual(window.settings.quick_commands[1].group, "Boot")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)

    def test_quick_command_csv_import_can_append_or_replace(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_import_mode.json")
        csv_path = Path(__file__).with_name("_tmp_quick_import_mode.csv")
        settings_path.unlink(missing_ok=True)
        csv_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            csv_path.write_text(
                "label,command,description,send_mode,group,line_ending_override\n"
                "Read ID,id?,Imported description,Text,Factory,LF\n"
                "Wake,wake,,Text,Factory,\n",
                encoding="utf-8",
            )
            window = app_module.MainWindow()
            window.settings.quick_commands = [
                QuickCommand(
                    label="Read ID",
                    command="id?",
                    description="Local note",
                    send_mode="Text",
                    group="Factory",
                ),
                QuickCommand(label="Local Only", command="local", send_mode="Text", group="General"),
            ]

            append_result = window.import_quick_commands_from_csv(
                csv_path,
                options=app_module.QuickCommandImportOptions(
                    replace_existing=False,
                    skip_duplicates=True,
                ),
            )

            self.assertEqual(append_result.imported_count, 1)
            self.assertEqual(append_result.skipped_count, 1)
            self.assertEqual(
                [command.label for command in window.settings.quick_commands],
                ["Read ID", "Local Only", "Wake"],
            )

            replace_result = window.import_quick_commands_from_csv(
                csv_path,
                options=app_module.QuickCommandImportOptions(
                    replace_existing=True,
                    skip_duplicates=False,
                ),
            )

            self.assertEqual(replace_result.imported_count, 2)
            self.assertEqual(replace_result.skipped_count, 0)
            self.assertEqual([command.label for command in window.settings.quick_commands], ["Read ID", "Wake"])
            self.assertEqual(window.settings.quick_commands[0].description, "Imported description")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)

    def test_app_settings_json_export_import_excludes_quick_actions(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_app_settings_bundle.json")
        export_path = Path(__file__).with_name("_tmp_exported_settings.json")
        settings_path.unlink(missing_ok=True)
        export_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            exported = AppSettings(
                serial=SerialProfile(port="COM44", baudrate=57600, line_ending="LF"),
                theme="Bench Light",
                terminal_font_size=14,
                quick_commands=[
                    QuickCommand(label="Version", command="version", group="General")
                ],
                quick_files=[
                    QuickFile(label="Imported file", path="C:/scripts/imported.txt")
                ],
                quick_command_sort_mode="Title",
                quick_command_hidden_groups=["Factory"],
                quick_file_sort_mode="Path",
                restored_tabs=[
                    TerminalSessionState(
                        title="Imported DUT",
                        serial=SerialProfile(port="COM55", baudrate=230400),
                        command_draft="status",
                    )
                ],
            )
            window.settings = exported
            window.export_settings_to_json(export_path)

            payload = json.loads(export_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], SETTINGS_SCHEMA_VERSION)
            self.assertNotIn("libraries", payload)
            self.assertEqual(payload["transport"]["profile"]["port"], "COM44")
            self.assertEqual(payload["workspace"]["terminal_tabs"][0]["title"], "Imported DUT")

            loaded = window.load_settings_from_json(export_path)
            self.assertEqual(loaded.serial.port, "COM44")

            window.settings = AppSettings(
                quick_commands=[QuickCommand(label="Local", command="local")],
                quick_files=[QuickFile(label="Local file", path="C:/scripts/local.txt")],
                quick_command_sort_mode="Group",
                quick_command_hidden_groups=["Hidden"],
                quick_file_sort_mode="Title",
            )
            window.apply_imported_settings(loaded)
            session = window.current_session()

            self.assertEqual(window.settings.theme, "Bench Light")
            self.assertEqual(window.settings.terminal_font_size, 14)
            self.assertEqual([command.command for command in window.settings.quick_commands], ["local"])
            self.assertEqual([quick_file.path for quick_file in window.settings.quick_files], ["C:/scripts/local.txt"])
            self.assertEqual(window.settings.quick_command_sort_mode, "Group")
            self.assertEqual(window.settings.quick_command_hidden_groups, ["Hidden"])
            self.assertEqual(window.settings.quick_file_sort_mode, "Title")
            self.assertEqual(session.title, "Imported DUT")
            self.assertEqual(session.profile.port, "COM55")
            self.assertEqual(session.command_input.text(), "status")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            export_path.unlink(missing_ok=True)

    def test_app_settings_import_ignores_incoming_quick_actions(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_app_settings_import_quick_actions.json")
        settings_path.unlink(missing_ok=True)
        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        try:
            window = app_module.MainWindow()
            window.settings.quick_commands = [
                QuickCommand(label="Local", command="local", send_mode="Text", group="General"),
                QuickCommand(label="Version", command="version", send_mode="Text", group="General"),
            ]
            window.settings.quick_files = [
                QuickFile(label="Local File", path="C:/scripts/local.txt")
            ]
            window.settings.quick_command_sort_mode = "Group"
            window.settings.quick_command_hidden_groups = ["Hidden"]
            window.settings.quick_file_sort_mode = "Path"
            imported = AppSettings(
                quick_commands=[
                    QuickCommand(label="Version", command="version", description="Imported note", group="General"),
                    QuickCommand(label="Reset", command="reset", group="General"),
                ],
                quick_files=[
                    QuickFile(label="Imported File", path="C:/scripts/imported.txt")
                ],
                quick_command_sort_mode="Title",
                quick_command_hidden_groups=["Imported"],
                quick_file_sort_mode="Title",
                restored_tabs=[
                    TerminalSessionState(title="Imported", serial=SerialProfile(port="COM12"))
                ],
            )

            window.apply_imported_settings(imported)

            self.assertEqual(
                [command.label for command in window.settings.quick_commands],
                ["Local", "Version"],
            )
            self.assertEqual([quick_file.label for quick_file in window.settings.quick_files], ["Local File"])
            self.assertEqual(window.settings.quick_command_sort_mode, "Group")
            self.assertEqual(window.settings.quick_command_hidden_groups, ["Hidden"])
            self.assertEqual(window.settings.quick_file_sort_mode, "Path")
            self.assertEqual(window.current_session().profile.port, "COM12")
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            if window is not None:
                for active_session in window.iter_sessions():
                    active_session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
