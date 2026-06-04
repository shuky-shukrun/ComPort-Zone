from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QMainWindow

from ComPort_Zone.command_registry import CommandRegistry
from ComPort_Zone.ui.main_window_menus import MainWindowMenuBuilder
from ComPort_Zone.ui.tab_context_menus import TabContextMenuBuilder


def action_titles(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


class FakeTabs:
    def __init__(self, count: int = 3) -> None:
        self._count = count

    def count(self) -> int:
        return self._count

    def tabText(self, index: int) -> str:
        return f"Tab {index + 1}"


class FakeSession:
    tab_title = "COM7"

    def __init__(self, *, connected: bool = False, reconnecting: bool = False) -> None:
        self.serial_client = SimpleNamespace(
            is_connected=connected,
            is_reconnecting=reconnecting,
        )


class FakeEditor:
    path = Path("C:/scripts/startup.cmd")

    def __init__(self) -> None:
        self.calls: list[str] = []

    def tab_title(self) -> str:
        return "startup.cmd"

    def is_dirty(self) -> bool:
        return True

    def save(self) -> None:
        self.calls.append("save")

    def save_as(self) -> None:
        self.calls.append("save_as")


class FakeContextMenuHost(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.tabs = FakeTabs()
        self.command_registry = CommandRegistry(self)
        self.menu_builder = MainWindowMenuBuilder(self, self.command_registry)
        self.session = FakeSession()
        self.editor: FakeEditor | None = None
        self.calls: list[object] = []

    def session_at(self, _index: int):
        return None if self.editor else self.session

    def command_file_editor_at(self, _index: int):
        return self.editor

    def _add_context_action(self, *args, **kwargs):
        return self.menu_builder.add_context_action(*args, **kwargs)

    def _add_context_command_action(self, *args, **kwargs):
        return self.menu_builder.add_context_command_action(*args, **kwargs)

    def __getattr__(self, name: str):
        def callback(*args, **_kwargs) -> None:
            self.calls.append((name, args))

        return callback


class TabContextMenuBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_builds_terminal_tab_context_menu(self) -> None:
        host = FakeContextMenuHost()
        try:
            menu = TabContextMenuBuilder(host).build(1)

            self.assertEqual(menu.title(), "COM7")
            self.assertEqual(
                action_titles(menu),
                [
                    "New Terminal",
                    "Duplicate Tab",
                    "Rename Tab",
                    "Connection Settings",
                    "Connect",
                    "Search",
                    "Clear Terminal",
                    "Move to Other Pane",
                    "Split Right",
                    "Split Down",
                    "Join Tabs",
                    "Close Tab",
                    "Close Other Tabs",
                    "Close Tabs to the Right",
                ],
            )

            next(action for action in menu.actions() if action.text() == "Connect").trigger()

            self.assertIn(("toggle_session_connection", (1,)), host.calls)
        finally:
            host.deleteLater()

    def test_builds_editor_tab_context_menu(self) -> None:
        host = FakeContextMenuHost()
        host.editor = FakeEditor()
        try:
            menu = TabContextMenuBuilder(host).build(0)

            self.assertEqual(menu.title(), "startup.cmd")
            self.assertEqual(
                action_titles(menu),
                [
                    "New Command File",
                    "Save",
                    "Save As",
                    "Run in Terminal",
                    "Show in Explorer",
                    "Move to Other Pane",
                    "Split Right",
                    "Split Down",
                    "Join Tabs",
                    "Close Tab",
                    "Close Other Tabs",
                    "Close Tabs to the Right",
                ],
            )

            next(action for action in menu.actions() if action.text() == "Save").trigger()

            self.assertEqual(host.editor.calls, ["save"])
        finally:
            host.deleteLater()

    def test_builds_empty_tab_bar_context_menu(self) -> None:
        host = FakeContextMenuHost()
        try:
            menu = TabContextMenuBuilder(host).build(-1)

            self.assertEqual(action_titles(menu), ["New Terminal", "New Command File"])
        finally:
            host.deleteLater()


if __name__ == "__main__":
    unittest.main()
