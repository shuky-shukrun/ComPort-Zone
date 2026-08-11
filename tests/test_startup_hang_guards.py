"""Startup must never block on a dialog the user cannot see.

Regression: a workspace whose command-file tab pointed at a file deleted since
the last run popped a modal "Open Command File" warning from inside
``MainWindow.__init__`` — before the window was shown and while the splash was
on top of it. The app looked frozen on the logo; the only clue was a stray
window under ComPortZone in Task Manager, and ending it released the launch.
"""

from __future__ import annotations

import faulthandler
import json
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from ComPort_Zone import app as app_module
from ComPort_Zone.command_editor import CommandFileEditorDialog
from ComPort_Zone.command_editor_core import CommandEditorSources
from ComPort_Zone.models import SETTINGS_SCHEMA_VERSION


def workspace_payload(command_file_paths: list[Path]) -> dict:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "app": {"check_for_updates_on_launch": False},
        "workspace": {
            "layout": {
                "panes": [
                    {
                        "tabs": [{"kind": "terminal", "terminal": {"title": "Terminal 1"}}]
                        + [
                            {"kind": "command_file", "command_file": {"path": str(path)}}
                            for path in command_file_paths
                        ]
                    }
                ]
            }
        },
    }


class StartupHangGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_restoring_a_deleted_command_file_opens_no_modal(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_missing_command_file.json")
        missing = Path(__file__).with_name("_tmp_deleted_command_file.cpz")
        missing.unlink(missing_ok=True)
        settings_path.write_text(json.dumps(workspace_payload([missing])), encoding="utf-8")
        old_config_path = app_module.default_config_path
        app_module.default_config_path = lambda: settings_path
        window = None
        modals: list[tuple] = []
        try:
            with mock.patch.object(QMessageBox, "warning", lambda *a, **k: modals.append(a)):
                window = app_module.MainWindow(defer_startup_actions=True)
            self.assertEqual(modals, [])  # the launch is never blocked by a dialog

            editors = window.iter_command_file_editors()
            self.assertEqual(len(editors), 1)  # the tab is kept, bound to its path
            editor = editors[0]
            self.assertEqual(editor.path, missing)
            self.assertEqual(editor.text(), "")
            self.assertIn("No such file", editor.load_error or "")
            # The reason is visible in the tab and survives the "Ready" reset.
            self.assertIn(missing.name, editor.status_label.text())
            self.assertIn(missing.name, window.footer.text())
        finally:
            app_module.default_config_path = old_config_path
            if window is not None:
                for session in window.iter_sessions():
                    session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            settings_path.unlink(missing_ok=True)
            settings_path.with_name(settings_path.name + ".bak").unlink(missing_ok=True)

    def test_restored_tab_still_loads_a_file_that_is_present(self) -> None:
        settings_path = Path(__file__).with_name("_tmp_settings_present_command_file.json")
        present = Path(__file__).with_name("_tmp_present_command_file.cpz")
        present.write_text("SEND *IDN?\n", encoding="utf-8")
        settings_path.write_text(json.dumps(workspace_payload([present])), encoding="utf-8")
        old_config_path = app_module.default_config_path
        app_module.default_config_path = lambda: settings_path
        window = None
        try:
            window = app_module.MainWindow(defer_startup_actions=True)
            editor = window.iter_command_file_editors()[0]
            self.assertEqual(editor.text(), "SEND *IDN?\n")
            self.assertIsNone(editor.load_error)
            self.assertEqual(window.footer.text(), "Ready")
        finally:
            app_module.default_config_path = old_config_path
            if window is not None:
                for session in window.iter_sessions():
                    session.shutdown()
                window.deleteLater()
            self.qt.processEvents()
            present.unlink(missing_ok=True)
            settings_path.unlink(missing_ok=True)
            settings_path.with_name(settings_path.name + ".bak").unlink(missing_ok=True)

    def test_editor_reports_load_failure_without_a_dialog_when_asked(self) -> None:
        missing = Path(__file__).with_name("_tmp_never_created.cpz")
        modals: list[tuple] = []
        with mock.patch.object(QMessageBox, "warning", lambda *a, **k: modals.append(a)):
            editor = CommandFileEditorDialog(
                sources=CommandEditorSources(),
                path=missing,
                notify_load_errors=False,
            )
        try:
            self.assertEqual(modals, [])
            self.assertEqual(editor.path, missing)
            self.assertEqual(editor.text(), "")
            self.assertFalse(editor.is_dirty())
            self.assertIn("No such file", editor.load_error or "")
            self.assertIn(missing.name, editor.status_label.text())
        finally:
            editor.deleteLater()
            self.qt.processEvents()

    def test_editor_still_warns_by_default(self) -> None:
        """Direct callers (Open..., quick files) keep the visible error dialog."""
        missing = Path(__file__).with_name("_tmp_never_created.cpz")
        modals: list[tuple] = []
        with mock.patch.object(QMessageBox, "warning", lambda *a, **k: modals.append(a)):
            editor = CommandFileEditorDialog(sources=CommandEditorSources(), path=missing)
        try:
            self.assertEqual(len(modals), 1)
            self.assertEqual(modals[0][1], "Open Command File")
        finally:
            editor.deleteLater()
            self.qt.processEvents()

    def test_startup_splash_is_not_always_on_top(self) -> None:
        """A topmost splash hides whatever startup puts on screen behind it."""
        splash = app_module.create_startup_splash("Loading...")
        try:
            self.assertFalse(
                bool(splash.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            )
        finally:
            splash.close()
            splash.deleteLater()
            self.qt.processEvents()

    def test_startup_freeze_dump_is_armed_before_the_window_is_built(self) -> None:
        tmp_dir = Path(__file__).with_name("_tmp_startup_freeze_dump")
        dump_path = tmp_dir / "freeze-dump.txt"
        try:
            with mock.patch.object(app_module, "freeze_dump_path", lambda: dump_path):
                self.assertTrue(app_module.arm_startup_freeze_dump())
            self.assertTrue(faulthandler.is_enabled())
            self.assertTrue(dump_path.exists())
        finally:
            faulthandler.cancel_dump_traceback_later()
            try:
                faulthandler.disable()
            except Exception:
                pass
            if app_module._freeze_dump_file is not None:
                try:
                    app_module._freeze_dump_file.close()
                except Exception:
                    pass
                app_module._freeze_dump_file = None
                app_module._freeze_dump_file_path = None
            try:
                dump_path.unlink(missing_ok=True)
                tmp_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
