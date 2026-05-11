import json
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeyEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QMenu, QToolButton

from ComPort_Zone import app as app_module
from ComPort_Zone.models import AppSettings, QuickCommand, QuickFile, SETTINGS_SCHEMA_VERSION, SerialProfile, TerminalSessionState
from ComPort_Zone.serial_core import SerialClient
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore
from ComPort_Zone.ui import main_window as main_window_module


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

    def test_restored_connected_missing_port_skips_auto_connect(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore_missing_port.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
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

    def test_background_restore_does_not_replace_active_connection_status(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_restore_background_status.json")
        settings_path.unlink(missing_ok=True)
        try:
            self.assertTrue(
                SettingsService(SettingsStore(settings_path)).save(
                    AppSettings(
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
            self.assertEqual(session.terminal.toPlainText(), "TX> status\n")
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
            self.assertEqual(session.terminal.toPlainText(), "TX> ok\nTX> bad\nTX> later\n")
            display_text = session.terminal.display_text()

            def color_for(fragment: str) -> str:
                cursor = QTextCursor(session.terminal.document())
                cursor.setPosition(display_text.index(fragment))
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                return cursor.charFormat().foreground().color().name().lower()

            self.assertEqual(color_for("ok"), window.theme.tx.lower())
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
            self.assertEqual(titles, ["New Tab", "New Command File"])
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
            quick_page = session.drawer_pages.widget(0)
            button_texts = [button.text() for button in quick_page.findChildren(QPushButton)]

            self.assertIn("Import CSV", button_texts)
            self.assertIn("Export CSV", button_texts)
            self.assertEqual(
                drawer_action_rows(quick_page),
                [
                    ["Send", "Add Command"],
                    ["Edit", "Delete"],
                    ["Move Up", "Move Down"],
                    ["Import CSV", "Export CSV"],
                ],
            )
            self.assertEqual(session.drawer_pages.count(), 2)
            rail_tooltips = [
                button.toolTip()
                for button in session.drawer_rail.findChildren(QToolButton)
            ]
            self.assertEqual(rail_tooltips, ["Quick commands", "Quick files"])
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
            first_session = window.current_session()
            window.add_session(prompt_settings=False)
            second_session = window.current_session()
            editor = window.add_command_file_tab()

            window.set_drawer_collapsed(False)
            first_session._select_drawer_page(1)
            self.qt.processEvents()

            self.assertEqual(window.settings.drawer_page_index, 1)
            self.assertEqual(first_session.drawer_pages.currentIndex(), 1)
            self.assertEqual(second_session.drawer_pages.currentIndex(), 1)
            self.assertEqual(editor.workspace_drawer_pages.currentIndex(), 1)
            self.assertFalse(first_session.drawer_panel.isHidden())
            self.assertFalse(second_session.drawer_panel.isHidden())
            self.assertFalse(editor.workspace_drawer.panel.isHidden())

            second_drawer_updates: list[tuple[bool, int, int | None]] = []
            original_second_apply_drawer_state = second_session.apply_drawer_state

            def record_second_drawer_update(collapsed: bool, width: int, page_index: int | None = None) -> None:
                second_drawer_updates.append((collapsed, width, page_index))
                original_second_apply_drawer_state(collapsed, width, page_index)

            second_session.apply_drawer_state = record_second_drawer_update
            window.set_drawer_width(360, source=first_session)
            window.tabs.setCurrentWidget(second_session)
            self.qt.processEvents()

            self.assertEqual(window.settings.drawer_width, 360)
            self.assertIn((False, 360, 1), second_drawer_updates)
            window.tabs.setCurrentWidget(editor)
            self.qt.processEvents()
            self.assertGreater(editor.workspace_splitter.sizes()[0], 48)
            self.assertEqual(editor.workspace_drawer.maximumWidth(), 520)

            first_drawer_updates: list[tuple[bool, int, int | None]] = []
            original_first_apply_drawer_state = first_session.apply_drawer_state

            def record_first_drawer_update(collapsed: bool, width: int, page_index: int | None = None) -> None:
                first_drawer_updates.append((collapsed, width, page_index))
                original_first_apply_drawer_state(collapsed, width, page_index)

            first_session.apply_drawer_state = record_first_drawer_update
            editor.workspace_splitter.setSizes([420, 900])
            editor._workspace_drawer_resized(420, 0)
            editor_drawer_width = editor.workspace_splitter.sizes()[0]

            self.assertEqual(window.settings.drawer_width, editor_drawer_width)
            self.assertIn((False, editor_drawer_width, 1), first_drawer_updates)

            second_session._select_drawer_page(1)
            self.qt.processEvents()

            self.assertTrue(window.settings.drawer_collapsed)
            self.assertTrue(first_session.drawer_panel.isHidden())
            self.assertTrue(second_session.drawer_panel.isHidden())
            self.assertTrue(editor.workspace_drawer.panel.isHidden())
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

            self.assertIn("App Settings Import / Export...", file_titles)
            self.assertNotIn("Import App Settings", file_titles)
            self.assertNotIn("Export App Settings", file_titles)

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
                window.theme.text.lower(),
            )
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

            window.connection_action_button.click()

            self.assertEqual(disconnect_calls, [True])
            self.assertEqual(window.connection_action_button.text(), "Connect")
            self.assertTrue(window.connection_status_label.text().startswith("Missing | COM99"))
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
            self.assertIn("Double-click to open Serial Settings.", window.connection_status_label.toolTip())
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
            self.assertIn("Command file", window.connection_status_label.text())
            self.assertFalse(window.connection_action_button.isEnabled())
            self.assertTrue(hasattr(editor, "quick_command_list"))
            self.assertTrue(hasattr(editor, "quick_file_list"))
            self.assertEqual(editor.workspace_drawer_pages.count(), 2)
            self.assertEqual(editor.workspace_drawer_pages.currentIndex(), 0)
            rail_tooltips = [
                button.toolTip()
                for button in editor.workspace_drawer_rail.findChildren(QToolButton)
            ]
            self.assertEqual(rail_tooltips, ["Quick commands", "Quick files"])
            command_buttons = [
                button.text()
                for button in editor.workspace_drawer_pages.widget(0).findChildren(QPushButton)
            ]
            file_buttons = [
                button.text()
                for button in editor.workspace_drawer_pages.widget(1).findChildren(QPushButton)
            ]
            self.assertEqual(
                drawer_action_rows(editor.workspace_drawer_pages.widget(0)),
                [
                    ["Insert", "Add Command"],
                    ["Edit", "Delete"],
                    ["Move Up", "Move Down"],
                    ["Import CSV", "Export CSV"],
                ],
            )
            self.assertEqual(
                drawer_action_rows(editor.workspace_drawer_pages.widget(1)),
                [
                    ["Open", "Add File"],
                    ["Edit", "Delete"],
                    ["Move Up", "Move Down"],
                    ["Import CSV", "Export CSV"],
                ],
            )
            self.assertIn("Insert", command_buttons)
            self.assertIn("Open", file_buttons)
            self.assertNotIn("Validate", [button.text() for button in editor.findChildren(QPushButton)])
            self.assertNotIn("Quick command suggestions", [label.text() for label in editor.findChildren(QLabel)])
            editor._select_workspace_drawer_page(1)
            self.assertEqual(editor.workspace_drawer_pages.currentIndex(), 1)
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
            editor.find_replace_bar.hide()
            editor.editor.setFocus()
            self.qt.processEvents()

            QTest.keyClick(editor.editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
            self.qt.processEvents()

            self.assertTrue(editor.find_replace_bar.isVisible())
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
            editor.find_replace_bar.hide()
            editor.editor.setFocus()
            self.qt.processEvents()

            QTest.keyClick(editor.editor, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
            self.qt.processEvents()

            self.assertTrue(editor.find_replace_bar.isVisible())
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

            self.assertEqual(session.terminal.toPlainText(), "TX> SINK:CURR?\n167.00\n")
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
            self.assertIn("Serial Settings", titles)
            self.assertIn("Run Command File", titles)
            self.assertIn("New Command File", titles)
            self.assertIn("Open Command File Editor", titles)
            self.assertIn("Stop Command File", titles)
            self.assertIn("Send Selected Quick File", titles)
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
            self.assertEqual(top_level, ["File", "Edit", "View", "Session", "Serial", "Tools", "Help"])

            tools_titles = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Command Palette", tools_titles)
            self.assertIn("Command Files", tools_titles)
            self.assertIn("Quick Commands", tools_titles)
            self.assertIn("Quick Files", tools_titles)

            command_file_titles = [action.text() for action in window.command_files_menu.actions()]
            self.assertIn("New Command File", command_file_titles)
            self.assertIn("Open Command File Editor", command_file_titles)
            self.assertIn("Run in Terminal", command_file_titles)
            self.assertIn("Run Command File", command_file_titles)

            quick_command_titles = [action.text() for action in window.quick_commands_menu.actions()]
            self.assertIn("Save Current Input", quick_command_titles)
            self.assertIn("Delete All Quick Commands", quick_command_titles)
            self.assertIn("Import CSV", quick_command_titles)
            self.assertIn("Export CSV", quick_command_titles)

            quick_file_titles = [action.text() for action in window.quick_files_menu.actions()]
            self.assertIn("Run Selected", quick_file_titles)
            self.assertIn("Edit Selected File", quick_file_titles)
            self.assertIn("Delete All Quick Files", quick_file_titles)
            self.assertIn("Import CSV", quick_file_titles)
            self.assertIn("Export CSV", quick_file_titles)

            edit_titles = [action.text() for action in window.edit_menu.actions()]
            self.assertIn("Find", edit_titles)
            self.assertIn("Replace", edit_titles)
            self.assertIn("Clear Command History", edit_titles)
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

            self.assertEqual(color_for("status"), window.theme.tx.lower())
            self.assertEqual(color_for("OK"), window.theme.rx.lower())
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
            labels = session.command_bar.findChildren(QLabel, "terminalFontControlsLabel")
            buttons = session.command_bar.findChildren(QPushButton, "terminalFontSizeButton")

            self.assertEqual([label.text() for label in labels], ["Font"])
            self.assertEqual([button.text() for button in buttons], ["-", "+"])
            self.assertTrue(all(button.width() >= 38 for button in buttons))
            self.assertEqual(buttons[0].toolTip(), "Decrease terminal font size")
            self.assertEqual(buttons[1].toolTip(), "Increase terminal font size")
            self.assertEqual(buttons[0].accessibleName(), "Decrease terminal font size")
            self.assertEqual(buttons[1].accessibleName(), "Increase terminal font size")
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
            session.batch_runner.start = lambda steps: started_steps.append(steps)

            self.assertEqual(session.drawer_pages.count(), 2)
            session._select_drawer_page(1)
            self.assertEqual(session.drawer_pages.currentIndex(), 1)

            window.add_quick_file(QuickFile(label="Bring-up", path=str(script_path)))
            self.assertEqual(session.quick_file_list.count(), 1)
            self.assertEqual(session.quick_file_list.item(0).text(), "Bring-up")

            session.quick_file_list.setCurrentRow(0)
            menu = session.build_quick_file_context_menu(session.selected_quick_file_id())
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
                self.assertEqual(
                    drawer_action_rows(session.drawer_pages.widget(1)),
                    [
                        ["Run", "Add File"],
                        ["Edit", "Delete"],
                        ["Move Up", "Move Down"],
                        ["Import CSV", "Export CSV"],
                    ],
                )

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
