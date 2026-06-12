from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPoint
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


class FakeDashboardTab:
    def __init__(self, *, user_paused: bool = False) -> None:
        self.calls: list[object] = []
        reasons = frozenset({"user"}) if user_paused else frozenset()
        self.scheduler = SimpleNamespace(paused_reasons=reasons)
        self.edit_layout_button = SimpleNamespace(
            isChecked=lambda: False,
            toggle=lambda: self.calls.append("toggle_edit_layout"),
        )

    def tab_title(self) -> str:
        return "PSU Bench"

    def bind_to_session(self, session_id: int) -> None:
        self.calls.append(("bind", session_id))

    def add_entry_via_dialog(self) -> None:
        self.calls.append("add_entry")

    def set_polling_enabled(self, enabled: bool) -> None:
        self.calls.append(("set_polling_enabled", enabled))


class FakeContextMenuHost(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.tabs = FakeTabs()
        self.command_registry = CommandRegistry(self)
        self.menu_builder = MainWindowMenuBuilder(self, self.command_registry)
        self.session = FakeSession()
        self.editor: FakeEditor | None = None
        self.dashboard: FakeDashboardTab | None = None
        self.calls: list[object] = []

    def session_at(self, _index: int):
        return None if self.editor or self.dashboard else self.session

    def command_file_editor_at(self, _index: int):
        return self.editor

    def dashboard_at(self, _index: int):
        return self.dashboard

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

    def test_show_addresses_tab_by_global_index(self) -> None:
        # Regression for issue #11: show() must build the menu for the tab's global
        # index (via tabs.tab_index_at), not the pane-local index from tabBar().tabAt.
        host = FakeContextMenuHost()

        class FakeTabBar:
            def tabAt(self, _position) -> int:
                return 0  # pane-local index — would mis-target the second pane

            def mapToGlobal(self, position):
                return position

        class FakeSplitTabs(FakeTabs):
            def tabBar(self):
                return FakeTabBar()

            def tab_index_at(self, _position) -> int:
                return 1  # global index of the right pane's tab

        class FakeMenu:
            def exec(self, _global_position) -> None:
                return None

        host.tabs = FakeSplitTabs()
        builder = TabContextMenuBuilder(host)
        captured: list[int] = []
        builder.build = lambda index: captured.append(index) or FakeMenu()
        try:
            builder.show(QPoint(5, 5))
            self.assertEqual(captured, [1])
        finally:
            host.deleteLater()

    def test_builds_empty_tab_bar_context_menu(self) -> None:
        host = FakeContextMenuHost()
        try:
            menu = TabContextMenuBuilder(host).build(-1)

            self.assertEqual(
                action_titles(menu),
                [
                    "New Terminal",
                    "New Command File",
                    "New Control Panel",
                    "Control Panels...",
                ],
            )
        finally:
            host.deleteLater()

    def test_builds_dashboard_tab_context_menu(self) -> None:
        host = FakeContextMenuHost()
        host.dashboard = FakeDashboardTab()
        try:
            menu = TabContextMenuBuilder(host).build(1)

            self.assertEqual(menu.title(), "PSU Bench")
            self.assertEqual(
                action_titles(menu),
                [
                    "New Control Panel",
                    "Rename Control Panel",
                    "Bind to Terminal",
                    "Pause Polling",
                    "Add Entry...",
                    "Edit Layout",
                    "Control Panels...",
                    "Move to Other Pane",
                    "Split Right",
                    "Split Down",
                    "Join Tabs",
                    "Close Tab",
                    "Close Other Tabs",
                    "Close Tabs to the Right",
                ],
            )

            next(action for action in menu.actions() if action.text() == "Pause Polling").trigger()
            self.assertIn(("set_polling_enabled", False), host.dashboard.calls)
        finally:
            host.deleteLater()

    def test_dashboard_menu_offers_resume_when_user_paused(self) -> None:
        host = FakeContextMenuHost()
        host.dashboard = FakeDashboardTab(user_paused=True)
        try:
            menu = TabContextMenuBuilder(host).build(1)
            titles = action_titles(menu)
            self.assertIn("Resume Polling", titles)
            self.assertNotIn("Pause Polling", titles)
            next(action for action in menu.actions() if action.text() == "Resume Polling").trigger()
            self.assertIn(("set_polling_enabled", True), host.dashboard.calls)
        finally:
            host.deleteLater()


if __name__ == "__main__":
    unittest.main()
