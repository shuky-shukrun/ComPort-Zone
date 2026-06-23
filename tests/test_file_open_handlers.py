"""Unit tests for MainWindow's file-open / quick-file-drop handlers.

These drive the methods with a lightweight stand-in ``self`` (SimpleNamespace + Mocks)
rather than constructing a full MainWindow, so the dedup and single-vs-multiple
behaviours are covered without bringing up the whole app.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from ComPort_Zone.ui.main_window import MainWindow


class FileOpenHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    # ---- dedup -----------------------------------------------------------------
    def test_existing_editor_matches_same_path(self) -> None:
        editor = SimpleNamespace(path=Path("C:/scripts/a.cpz"))
        other = SimpleNamespace(path=Path("C:/scripts/b.cpz"))
        host = SimpleNamespace(iter_command_file_editors=lambda: [editor, other])

        found = MainWindow._existing_command_file_editor(host, Path("C:/scripts/a.cpz"))
        self.assertIs(found, editor)

    def test_existing_editor_returns_none_for_new_path(self) -> None:
        editor = SimpleNamespace(path=Path("C:/scripts/a.cpz"))
        host = SimpleNamespace(iter_command_file_editors=lambda: [editor])

        self.assertIsNone(
            MainWindow._existing_command_file_editor(host, Path("C:/scripts/new.cpz"))
        )

    def test_open_in_tab_focuses_existing_instead_of_adding(self) -> None:
        existing = SimpleNamespace(path=Path("C:/scripts/a.cpz"))
        host = SimpleNamespace(
            _existing_command_file_editor=lambda path: existing,
            tabs=Mock(),
            add_command_file_tab=Mock(),
            record_recent_file=Mock(),
        )

        result = MainWindow.open_command_file_in_tab(host, "C:/scripts/a.cpz")

        self.assertIs(result, existing)
        host.tabs.setCurrentWidget.assert_called_once_with(existing)
        host.add_command_file_tab.assert_not_called()
        host.record_recent_file.assert_called_once()

    def test_open_in_tab_adds_when_not_open(self) -> None:
        host = SimpleNamespace(
            _existing_command_file_editor=lambda path: None,
            tabs=Mock(),
            add_command_file_tab=Mock(return_value="new-editor"),
            record_recent_file=Mock(),
        )

        result = MainWindow.open_command_file_in_tab(host, "C:/scripts/a.cpz")

        self.assertEqual(result, "new-editor")
        host.add_command_file_tab.assert_called_once_with(path=Path("C:/scripts/a.cpz"))
        host.tabs.setCurrentWidget.assert_not_called()

    # ---- filtering -------------------------------------------------------------
    def test_open_files_skips_unsupported_types(self) -> None:
        opened: list[str] = []
        host = SimpleNamespace(
            open_command_file_in_tab=lambda path: opened.append(path),
            set_status=Mock(),
        )

        MainWindow.open_command_files_in_tabs(
            host, ["C:/a.cpz", "C:/image.png", "C:/b.cmd"]
        )

        self.assertEqual(opened, ["C:/a.cpz", "C:/b.cmd"])
        host.set_status.assert_called_once()  # reports the one skipped file

    # ---- quick-file drops ------------------------------------------------------
    def _drop_host(self):
        return SimpleNamespace(
            settings=SimpleNamespace(last_script_path=""),
            quick_action_controller=Mock(),
            set_status=Mock(),
        )

    def test_single_dropped_file_prompts_for_name(self) -> None:
        host = self._drop_host()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "only.cpz")
            Path(path).write_text("", encoding="utf-8")

            MainWindow.add_quick_files_from_paths(host, [path])

        host.quick_action_controller.add_quick_file.assert_called_once()
        call = host.quick_action_controller.add_quick_file.call_args
        self.assertIs(call.kwargs["prompt"], True)
        self.assertEqual(call.args[0].path, path)
        self.assertEqual(call.args[0].label, "only.cpz")

    def test_multiple_dropped_files_added_without_prompt(self) -> None:
        host = self._drop_host()
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in ("a.cpz", "b.txt"):
                path = os.path.join(tmp, name)
                Path(path).write_text("", encoding="utf-8")
                paths.append(path)

            MainWindow.add_quick_files_from_paths(host, paths)

        self.assertEqual(host.quick_action_controller.add_quick_file.call_count, 2)
        for call in host.quick_action_controller.add_quick_file.call_args_list:
            self.assertIs(call.kwargs["prompt"], False)
        host.set_status.assert_called_once()

    def test_dropping_only_missing_paths_is_noop(self) -> None:
        host = self._drop_host()
        MainWindow.add_quick_files_from_paths(host, ["C:/does/not/exist.cpz"])
        host.quick_action_controller.add_quick_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
