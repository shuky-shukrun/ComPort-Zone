"""Coverage for the restructured menu bar and its new features."""

from __future__ import annotations

import contextlib
import unittest
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMenu

from ComPort_Zone import app as app_module
from ComPort_Zone.command_registry import CommandRegistry
from ComPort_Zone.models import (
    AppSettings,
    QuickCommand,
    QuickFile,
    RECENT_FILES_LIMIT,
    SerialProfile,
)
from ComPort_Zone.serial_core import SerialClient
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore


class FakePort:
    """Minimal stand-in for a live ``serial.Serial`` (DTR/RTS/break only)."""

    def __init__(self) -> None:
        self.is_open = True
        self.dtr = True
        self.rts = True
        self.breaks = 0

    def send_break(self, duration: float) -> None:
        self.breaks += 1


@contextlib.contextmanager
def make_window(tmp_name: str, settings: AppSettings | None = None):
    settings_path = Path(__file__).with_name(tmp_name)
    settings_path.unlink(missing_ok=True)
    SettingsService(SettingsStore(settings_path)).save(
        settings or AppSettings(check_for_updates_on_launch=False)
    )
    old_config = app_module.default_config_path
    old_prompt_current = app_module.MainWindow.prompt_current_session_settings
    old_prompt_session = app_module.MainWindow.prompt_session_settings
    app_module.default_config_path = lambda: settings_path
    app_module.MainWindow.prompt_current_session_settings = lambda self: None
    app_module.MainWindow.prompt_session_settings = lambda self, session: None
    window = None
    try:
        window = app_module.MainWindow()
        yield window
    finally:
        app_module.default_config_path = old_config
        app_module.MainWindow.prompt_current_session_settings = old_prompt_current
        app_module.MainWindow.prompt_session_settings = old_prompt_session
        if window is not None:
            for session in window.iter_sessions():
                with contextlib.suppress(Exception):
                    session.shutdown()
            window.deleteLater()
        QApplication.instance().processEvents()
        for suffix in ("", ".bak", ".lock"):
            with contextlib.suppress(OSError):
                settings_path.with_name(settings_path.name + suffix).unlink(missing_ok=True)


class SerialSignalTests(unittest.TestCase):
    def test_set_dtr_rts_and_send_break_drive_the_live_port(self) -> None:
        from ComPort_Zone.raw_transport import SerialRawTransport

        client = SerialClient()
        port = FakePort()
        raw = SerialRawTransport(SerialProfile())
        raw._port = port  # stand in for the live pyserial handle
        client._raw = raw
        client._profile = SerialProfile()
        client._desired_profile = client._profile

        self.assertEqual(client.current_signal_state(), (True, True))
        self.assertTrue(client.set_dtr(False))
        self.assertFalse(port.dtr)
        self.assertFalse(client._profile.dtr)
        self.assertTrue(client.set_rts(False))
        self.assertFalse(port.rts)
        self.assertEqual(client.current_signal_state(), (False, False))
        self.assertTrue(client.send_break())
        self.assertEqual(port.breaks, 1)

    def test_signal_calls_are_noops_when_disconnected(self) -> None:
        client = SerialClient()
        self.assertIsNone(client.current_signal_state())
        self.assertFalse(client.set_dtr(False))
        self.assertFalse(client.set_rts(True))
        self.assertFalse(client.send_break())

    def test_reconnect_loop_uses_profile_interval(self) -> None:
        from threading import Event

        client = SerialClient()
        monitor = client.subscribe_monitor()
        client._desired_profile = SerialProfile(reconnect_initial_delay_ms=250)
        stop = Event()
        stop.set()  # exit the loop right after the initial "armed" status emit
        client._reconnect_loop(stop)
        messages = []
        while not monitor.empty():
            messages.append(monitor.get_nowait().message)
        self.assertTrue(any("250 ms" in message for message in messages))


class ShortcutEntriesTests(unittest.TestCase):
    def test_shortcut_entries_include_bound_shortcuts_only(self) -> None:
        registry = CommandRegistry(object())
        entries = dict(registry.shortcut_entries())
        self.assertEqual(entries.get("Reset Zoom"), "Ctrl+0")
        self.assertEqual(entries.get("New Terminal"), "Ctrl+T")
        self.assertTrue(all(shortcut for shortcut in entries.values()))


class RecentFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_record_recent_file_dedupes_and_caps(self) -> None:
        with make_window("_tmp_settings_menu_recent.json") as window:
            for index in range(RECENT_FILES_LIMIT + 5):
                window.record_recent_file(f"C:/scripts/file{index}.cpz")
            window.record_recent_file("C:/scripts/file0.cpz")  # re-open moves to front

            self.assertEqual(len(window.settings.recent_files), RECENT_FILES_LIMIT)
            self.assertEqual(window.settings.recent_files[0], "C:/scripts/file0.cpz")

            menu = QMenu()
            window.populate_open_recent_menu(menu)
            self.assertEqual(menu.actions()[-1].text(), "Clear Recent")

            window.clear_recent_files()
            self.assertEqual(window.settings.recent_files, [])

            empty_menu = QMenu()
            window.populate_open_recent_menu(empty_menu)
            self.assertEqual(empty_menu.actions()[0].text(), "No Recent Files")
            self.assertFalse(empty_menu.actions()[0].isEnabled())


class DataResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_clear_all_favorite_commands_keeps_saved_items(self) -> None:
        settings = AppSettings(
            check_for_updates_on_launch=False,
            quick_commands=[
                QuickCommand(label="A", command="A", favorite=True),
                QuickCommand(label="B", command="B", favorite=False),
            ],
        )
        with make_window("_tmp_settings_menu_fav.json", settings) as window:
            self.assertTrue(window.clear_all_favorite_commands(confirm=False))
            saved = window.quick_commands_snapshot()
            self.assertEqual(len(saved), 2)  # saved items kept
            self.assertTrue(all(not command.favorite for command in saved))

    def test_factory_reset_empties_libraries_and_restores_defaults(self) -> None:
        settings = AppSettings(
            check_for_updates_on_launch=False,
            theme="VS Code Dark",
            scrollback_size=99999,
            command_history=["alpha", "beta"],
            quick_commands=[QuickCommand(label="A", command="A", favorite=True)],
            quick_files=[QuickFile(label="F", path="C:/x.cpz")],
            recent_files=["C:/x.cpz"],
        )
        with make_window("_tmp_settings_menu_factory.json", settings) as window:
            self.assertTrue(window.factory_reset(confirm=False))
            self.assertEqual(window.settings.quick_commands, [])
            self.assertEqual(window.settings.quick_files, [])
            self.assertEqual(window.settings.command_history, [])
            self.assertEqual(window.settings.recent_files, [])
            self.assertEqual(window.settings.theme, "ComPort Zone Dark")
            self.assertEqual(window.settings.scrollback_size, 10000)

    def test_close_event_clears_history_only_when_opted_in(self) -> None:
        kept = AppSettings(check_for_updates_on_launch=False, command_history=["keep-me"])
        with make_window("_tmp_settings_menu_hist_keep.json", kept) as window:
            window.closeEvent(QCloseEvent())
            self.assertEqual(window.history_catalog.all_commands(), ["keep-me"])

        cleared = AppSettings(
            check_for_updates_on_launch=False,
            clear_history_on_exit=True,
            command_history=["wipe-me"],
        )
        with make_window("_tmp_settings_menu_hist_clear.json", cleared) as window:
            window.closeEvent(QCloseEvent())
            self.assertEqual(window.history_catalog.all_commands(), [])


class MenuGatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_tools_run_controls_gated_on_script_state(self) -> None:
        with make_window("_tmp_settings_menu_gating.json") as window:
            window.tools_menu.aboutToShow.emit()
            builder = window.menu_builder
            # Idle session: Run is available, Pause/Stop are not.
            self.assertTrue(builder._run_action.isEnabled())
            self.assertFalse(builder._pause_action.isEnabled())
            self.assertFalse(builder._stop_action.isEnabled())

    def test_signals_are_noops_until_connected(self) -> None:
        with make_window("_tmp_settings_menu_signals.json") as window:
            session = window.current_session()
            self.assertTrue(session.supports_signals())  # serial transport
            self.assertIsNone(session.signal_state())  # not connected
            before = session.profile.dtr
            session.toggle_dtr()  # disconnected -> no change
            self.assertEqual(session.profile.dtr, before)

    def test_file_menu_gating_for_single_disconnected_tab(self) -> None:
        with make_window("_tmp_settings_menu_filegate.json") as window:
            window.file_menu.aboutToShow.emit()
            builder = window.menu_builder
            self.assertFalse(builder._send_file_action.isEnabled())  # not connected
            self.assertFalse(builder._close_other_action.isEnabled())  # only one tab
            self.assertFalse(builder._save_action.isEnabled())  # no editor tab
            self.assertFalse(builder._save_as_action.isEnabled())

    def test_view_join_panes_gated_on_split(self) -> None:
        with make_window("_tmp_settings_menu_viewgate.json") as window:
            window.view_menu.aboutToShow.emit()
            # Single pane -> nothing to join.
            self.assertFalse(window.menu_builder._join_panes_action.isEnabled())

    def test_run_in_terminal_gated_on_connection(self) -> None:
        with make_window("_tmp_settings_menu_runterm.json") as window:
            window.tools_menu.aboutToShow.emit()
            # No port connected -> Run in Terminal disabled.
            self.assertFalse(window.run_in_terminal_menu.menuAction().isEnabled())


class PreferencesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_apply_to_writes_back_edited_fields(self) -> None:
        from ComPort_Zone.ui.dialogs import PreferencesDialog

        dialog = PreferencesDialog(AppSettings(theme="VS Code Dark"))
        try:
            dialog.scrollback_input.setValue(7777)
            dialog.reconnect_interval_input.setValue(5000)
            dialog.clear_history_checkbox.setChecked(True)
            target = AppSettings()
            dialog.apply_to(target)
            self.assertEqual(target.scrollback_size, 7777)
            self.assertEqual(target.theme, "VS Code Dark")
            self.assertTrue(target.clear_history_on_exit)
            self.assertEqual(target.serial.reconnect_initial_delay_ms, 5000)
            self.assertEqual(target.lan.reconnect_initial_delay_ms, 5000)
            self.assertFalse(hasattr(dialog, "reconnect_max_input"))  # removed field
        finally:
            dialog.deleteLater()

    def test_font_preview_tracks_size(self) -> None:
        from ComPort_Zone.ui.dialogs import PreferencesDialog

        dialog = PreferencesDialog(AppSettings())
        try:
            dialog.size_input.setValue(20)
            self.assertEqual(dialog.font_preview.font().pointSize(), 20)
        finally:
            dialog.deleteLater()


class ThemePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_hover_previews_without_saving_then_reverts(self) -> None:
        with make_window("_tmp_settings_menu_theme_preview.json") as window:
            builder = window.menu_builder
            original = window.settings.theme
            self.assertNotEqual(original, "VS Code Dark")
            builder._begin_theme_preview()
            builder._queue_theme_preview("VS Code Dark")
            builder._apply_theme_preview()  # the dwell timer fires this
            self.assertEqual(window.settings.theme, "VS Code Dark")  # previewed live
            builder._end_theme_preview()  # left the menu without choosing
            self.assertEqual(window.settings.theme, original)  # reverted

    def test_click_commits_theme(self) -> None:
        with make_window("_tmp_settings_menu_theme_commit.json") as window:
            builder = window.menu_builder
            builder._begin_theme_preview()
            builder._queue_theme_preview("VS Code Dark")
            builder._apply_theme_preview()
            builder._commit_theme("VS Code Dark")
            builder._end_theme_preview()  # committed -> no revert
            self.assertEqual(window.settings.theme, "VS Code Dark")


if __name__ == "__main__":
    unittest.main()
