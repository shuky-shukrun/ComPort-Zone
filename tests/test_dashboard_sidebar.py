"""Tests for the sidebar Dashboards page and Favorite Dashboards panel."""

from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.dashboard_models import DashboardConfig, DashboardEntry
from ComPort_Zone.quick_actions_panel import (
    ROLE_FAVORITE,
    ROLE_ID,
    ROLE_KIND,
    ROLE_SECONDARY,
    populate_dashboard_list,
    row_action_keys,
)
from ComPort_Zone.quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions


def make_config(name: str, *, favorite: bool = False, entries: int = 1) -> DashboardConfig:
    return DashboardConfig(
        name=name,
        favorite=favorite,
        entries=[DashboardEntry(label=f"e{i}", command=f"READ{i}?") for i in range(entries)],
    )


def make_actions(calls: list) -> QuickActionsSidebarActions:
    def remember(name: str):
        return lambda *args: calls.append((name, *args))

    return QuickActionsSidebarActions(
        command_primary=lambda: calls.append(("command-primary",)),
        file_primary=lambda: calls.append(("file-primary",)),
        add_command=lambda: None,
        edit_command=lambda: None,
        delete_command=lambda: None,
        move_command_up=lambda: None,
        move_command_down=lambda: None,
        import_commands=lambda: None,
        export_commands=lambda: None,
        add_file=lambda: None,
        edit_file=lambda: None,
        delete_file=lambda: None,
        move_file_up=lambda: None,
        move_file_down=lambda: None,
        import_files=lambda: None,
        export_files=lambda: None,
        dashboard_open_by_id=remember("open"),
        dashboard_favorite_toggle=remember("favorite"),
        dashboard_rename_by_id=remember("rename"),
        dashboard_delete_by_id=remember("delete"),
        new_dashboard=lambda: calls.append(("new",)),
        import_dashboards=lambda: calls.append(("import",)),
        export_dashboards=lambda: calls.append(("export",)),
        manage_dashboards=lambda: calls.append(("manage",)),
    )


class PopulateDashboardListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_rows_carry_dashboard_roles(self) -> None:
        from ComPort_Zone.quick_actions_panel import create_dashboard_list

        parent = QWidget()
        quick_list = create_dashboard_list(parent, tooltip="t")
        config = make_config("PSU Bench", favorite=True, entries=2)
        populate_dashboard_list(quick_list, [config])
        item = quick_list.item(0)
        self.assertEqual(item.text(), "PSU Bench")
        self.assertEqual(item.data(ROLE_ID), config.id)
        self.assertEqual(item.data(ROLE_KIND), "dashboard")
        self.assertEqual(item.data(ROLE_SECONDARY), "2 entries")
        self.assertTrue(item.data(ROLE_FAVORITE))
        parent.deleteLater()

    def test_dashboard_rows_use_file_style_actions(self) -> None:
        self.assertEqual(row_action_keys("dashboard"), ["remove", "edit", "star", "play"])


class DashboardSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.parent = QWidget()
        self.calls: list = []
        self.sidebar = QuickActionsSidebar(
            actions=make_actions(self.calls),
            command_primary_label="Send",
            file_primary_label="Run",
            include_history=True,
            include_dashboards=True,
            parent=self.parent,
        )

    def tearDown(self) -> None:
        self.sidebar.deleteLater()
        self.parent.deleteLater()

    def test_rail_has_dashboards_mode(self) -> None:
        tooltips = [button.toolTip() for button in self.sidebar.rail_buttons]
        self.assertIn("Dashboards", tooltips)
        self.assertEqual(
            tooltips, ["Favorites", "Saved Commands", "Files", "Dashboards", "History"]
        )

    def test_inline_actions_dispatch_by_id(self) -> None:
        config = make_config("Bench")
        populate_dashboard_list(self.sidebar.dashboard_list, [config])
        item = self.sidebar.dashboard_list.item(0)

        self.sidebar.dashboard_list.actionTriggered.emit(item, "play")
        self.sidebar.dashboard_list.actionTriggered.emit(item, "star")
        self.sidebar.dashboard_list.actionTriggered.emit(item, "edit")
        self.sidebar.dashboard_list.actionTriggered.emit(item, "remove")

        self.assertEqual(
            self.calls,
            [
                ("open", config.id),
                ("favorite", config.id, True),
                ("rename", config.id),
                ("delete", config.id),
            ],
        )

    def test_star_on_favorited_row_unfavorites(self) -> None:
        config = make_config("Bench", favorite=True)
        populate_dashboard_list(self.sidebar.favorite_dashboard_list, [config])
        item = self.sidebar.favorite_dashboard_list.item(0)
        self.sidebar.favorite_dashboard_list.actionTriggered.emit(item, "star")
        self.assertEqual(self.calls, [("favorite", config.id, False)])

    def test_double_click_opens(self) -> None:
        config = make_config("Bench")
        populate_dashboard_list(self.sidebar.dashboard_list, [config])
        self.sidebar.dashboard_list.itemDoubleClicked.emit(self.sidebar.dashboard_list.item(0))
        self.assertEqual(self.calls, [("open", config.id)])

    def test_context_menu_lists_dashboard_actions(self) -> None:
        config = make_config("Bench")
        populate_dashboard_list(self.sidebar.dashboard_list, [config])
        item = self.sidebar.dashboard_list.item(0)
        menu = self.sidebar._build_dashboard_menu(
            self.sidebar.dashboard_list, item, is_favorites=False
        )
        titles = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual(titles, ["Open", "Add to Favorites", "Rename", "Delete Dashboard"])
        menu.deleteLater()

    def test_favorites_page_includes_dashboard_panel(self) -> None:
        self.assertIn("favorite_dashboard", self.sidebar.sections)
        favorites_mode = self.sidebar.rail_modes[0]
        self.assertIn("favorite_dashboard", favorites_mode.sections)
        splitter = self.sidebar.favorites_splitter
        self.assertIsNotNone(splitter)
        self.assertEqual(splitter.count(), 3)


if __name__ == "__main__":
    unittest.main()
