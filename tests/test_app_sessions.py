import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from ComPort_Zone import app as app_module
from ComPort_Zone.models import AppSettings, QuickCommand, QuickFile, SerialProfile, TerminalSessionState
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
            self.assertTrue(SettingsStore(settings_path).save(settings))
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
            self.assertIn("Send Selected Quick File", titles)
            self.assertIn("Add Quick File", titles)
            self.assertIn("Clear Terminal", titles)
            self.assertIn("Search Terminal", titles)
            self.assertIn("Terminal Font Settings", titles)
            self.assertIn("Save Current Input as Quick Command", titles)
            self.assertIn("Import Settings", titles)
            self.assertIn("Export Settings", titles)
            self.assertIn("Import Quick Commands from CSV", titles)
            self.assertIn("Export Quick Commands to CSV", titles)
            self.assertIn("Import Quick Files from CSV", titles)
            self.assertIn("Export Quick Files to CSV", titles)
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
            session = window.current_session()
            window.settings.terminal_font_family = "Consolas"
            window.settings.terminal_font_size = 15

            window.apply_terminal_font_settings()

            self.assertEqual(session.terminal.font().pointSize(), 15)
            self.assertEqual(window.settings.terminal_font_family, "Consolas")
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
        old_load_batch_file = app_module.load_batch_file
        loaded_paths: list[Path] = []
        started_steps: list[object] = []
        window = None
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        app_module.load_batch_file = lambda path: loaded_paths.append(Path(path)) or ["step"]
        try:
            script_path.write_text("SEND status\n", encoding="utf-8")
            window = app_module.MainWindow()
            session = window.current_session()
            session.batch_runner.start = lambda steps: started_steps.append(steps)

            self.assertEqual(session.drawer_pages.count(), 4)
            session._select_drawer_page(1)
            self.assertEqual(session.drawer_pages.currentIndex(), 1)

            window.add_quick_file(QuickFile(label="Bring-up", path=str(script_path)))
            self.assertEqual(session.quick_file_list.count(), 1)
            self.assertEqual(session.quick_file_list.item(0).text(), "Bring-up")

            session.quick_file_list.setCurrentRow(0)
            menu = session.build_quick_file_context_menu(session.selected_quick_file_id())
            self.assertIn("Show in Explorer", [action.text() for action in menu.actions()])

            session.run_selected_quick_file()

            self.assertEqual(loaded_paths, [script_path])
            self.assertEqual(started_steps, [["step"]])
            self.assertEqual(window.settings.last_script_path, str(script_path.parent))

            window.delete_quick_file(session.selected_quick_file_id())
            self.assertEqual(session.quick_file_list.count(), 0)
        finally:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            app_module.load_batch_file = old_load_batch_file
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
            self.assertTrue(SettingsStore(settings_path).save(settings))
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

                window.set_quick_file_sort_mode("Path")
                self.assertEqual(visible_ids(), ["cable", "alpha", "zebra"])

                window.set_quick_file_sort_mode("Custom")
                self.assertEqual(visible_ids(), ["zebra", "alpha", "cable"])
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

    def test_settings_json_export_import_applies_full_settings(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_bundle.json")
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

            loaded = window.load_settings_from_json(export_path)
            self.assertEqual(loaded.serial.port, "COM44")
            self.assertEqual(loaded.quick_commands[0].command, "version")

            result = window.apply_imported_settings(loaded)
            session = window.current_session()

            self.assertEqual(result.imported_count, 1)
            self.assertEqual(result.skipped_count, 0)
            self.assertEqual(window.settings.theme, "Bench Light")
            self.assertEqual(window.settings.terminal_font_size, 14)
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

    def test_settings_import_can_append_quick_commands_and_skip_duplicates(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_import_append.json")
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
            imported = AppSettings(
                quick_commands=[
                    QuickCommand(label="Version", command="version", description="Imported note", group="General"),
                    QuickCommand(label="Reset", command="reset", group="General"),
                ],
                restored_tabs=[
                    TerminalSessionState(title="Imported", serial=SerialProfile(port="COM12"))
                ],
            )

            result = window.apply_imported_settings(
                imported,
                quick_command_options=app_module.QuickCommandImportOptions(
                    replace_existing=False,
                    skip_duplicates=True,
                ),
            )

            self.assertEqual(result.imported_count, 1)
            self.assertEqual(result.skipped_count, 1)
            self.assertEqual(
                [command.label for command in window.settings.quick_commands],
                ["Local", "Version", "Reset"],
            )
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
