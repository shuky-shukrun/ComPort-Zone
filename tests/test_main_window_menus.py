from __future__ import annotations

import unittest
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QMainWindow

from ComPort_Zone.command_registry import CommandRegistry
from ComPort_Zone.ui.main_window_menus import MainWindowMenuBuilder


class FakeMenuHost(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = SimpleNamespace(
            timestamps_enabled=True,
            line_wrap_enabled=False,
        )
        self.calls: list[object] = []

    def apply_theme(self, name: str) -> None:
        self.calls.append(("apply_theme", name))

    def populate_run_editor_menu(self, _menu) -> None:
        self.calls.append("populate_run_editor_menu")

    def __getattr__(self, name: str):
        def callback(*_args, **_kwargs) -> None:
            self.calls.append(name)

        return callback


class MainWindowMenuBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_builds_main_menu_handles_and_registered_shortcuts(self) -> None:
        host = FakeMenuHost()
        try:
            registry = CommandRegistry(host)
            handles = MainWindowMenuBuilder(host, registry).build()
            handles.install_on(host)

            self.assertEqual(
                [action.text() for action in host.menuBar().actions()],
                ["File", "Edit", "View", "Session", "Serial", "Tools", "Help"],
            )
            self.assertIs(host.tools_menu, handles.tools_menu)
            self.assertTrue(host.timestamps_action.isChecked())
            self.assertFalse(host.wrap_action.isChecked())
            self.assertTrue(host.timestamps_action.isCheckable())
            self.assertTrue(host.timestamps_action.icon().isNull())
            self.assertTrue(host.wrap_action.isCheckable())
            self.assertTrue(host.wrap_action.icon().isNull())
            self.assertIn("VS Code Dark", host.theme_actions)

            palette_actions = [
                action
                for action in host.findChildren(type(host.tools_menu.actions()[0]))
                if action.text() == "Command Palette"
            ]
            self.assertEqual(len(palette_actions), 1)
            self.assertEqual(palette_actions[0].shortcut().toString(), "Ctrl+Shift+P")

            host.theme_actions["VS Code Dark"].trigger()

            self.assertEqual(host.calls, [("apply_theme", "VS Code Dark")])
        finally:
            host.deleteLater()

    def test_context_command_action_uses_registry_metadata_and_callback_override(self) -> None:
        host = FakeMenuHost()
        try:
            registry = CommandRegistry(host)
            builder = MainWindowMenuBuilder(host, registry)
            menu = host.menuBar().addMenu("Context")
            calls: list[str] = []

            action = builder.add_context_command_action(
                menu,
                "edit.find",
                callback=lambda: calls.append("find"),
                text="Search",
                enabled=False,
            )

            self.assertEqual(action.text(), "Search")
            self.assertFalse(action.isEnabled())
            action.setEnabled(True)
            action.trigger()

            self.assertEqual(calls, ["find"])
        finally:
            host.deleteLater()


if __name__ == "__main__":
    unittest.main()
