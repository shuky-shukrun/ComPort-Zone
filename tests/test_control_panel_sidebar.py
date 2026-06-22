"""Tests for the sidebar ControlPanels page and Favorite ControlPanels panel."""

from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.control_panel_models import ControlPanelConfig, ControlPanelEntry
from ComPort_Zone.quick_actions_panel import (
    ROLE_FAVORITE,
    ROLE_ID,
    ROLE_KIND,
    ROLE_SECONDARY,
    populate_control_panel_list,
    row_action_keys,
)
from ComPort_Zone.quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions


def make_config(name: str, *, favorite: bool = False, entries: int = 1) -> ControlPanelConfig:
    return ControlPanelConfig(
        name=name,
        favorite=favorite,
        entries=[ControlPanelEntry(label=f"e{i}", command=f"READ{i}?") for i in range(entries)],
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
        control_panel_open_by_id=remember("open"),
        control_panel_favorite_toggle=remember("favorite"),
        control_panel_rename_by_id=remember("rename"),
        control_panel_duplicate_by_id=remember("duplicate"),
        control_panel_delete_by_id=remember("delete"),
        new_control_panel=lambda: calls.append(("new",)),
        import_control_panels=lambda: calls.append(("import",)),
        export_control_panels=lambda: calls.append(("export",)),
        manage_control_panels=lambda: calls.append(("manage",)),
    )


class PopulateControlPanelListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_rows_carry_control_panel_roles(self) -> None:
        from ComPort_Zone.quick_actions_panel import create_control_panel_list

        parent = QWidget()
        quick_list = create_control_panel_list(parent, tooltip="t")
        config = make_config("PSU Bench", favorite=True, entries=2)
        populate_control_panel_list(quick_list, [config])
        item = quick_list.item(0)
        self.assertEqual(item.text(), "PSU Bench")
        self.assertEqual(item.data(ROLE_ID), config.id)
        self.assertEqual(item.data(ROLE_KIND), "control_panel")
        self.assertEqual(item.data(ROLE_SECONDARY), "2 entries")
        self.assertTrue(item.data(ROLE_FAVORITE))
        parent.deleteLater()

    def test_control_panel_rows_use_file_style_actions(self) -> None:
        self.assertEqual(row_action_keys("control_panel"), ["remove", "edit", "star", "play"])


class ControlPanelSidebarTests(unittest.TestCase):
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
            include_control_panels=True,
            parent=self.parent,
        )

    def tearDown(self) -> None:
        self.sidebar.deleteLater()
        self.parent.deleteLater()

    def test_rail_has_control_panels_mode(self) -> None:
        tooltips = [button.toolTip() for button in self.sidebar.rail_buttons]
        self.assertIn("Control Panels", tooltips)
        self.assertEqual(
            tooltips,
            ["Favorites", "Saved Commands", "Files", "Control Panels", "History"],
        )

    def test_inline_actions_dispatch_by_id(self) -> None:
        config = make_config("Bench")
        populate_control_panel_list(self.sidebar.control_panel_list, [config])
        item = self.sidebar.control_panel_list.item(0)

        self.sidebar.control_panel_list.actionTriggered.emit(item, "play")
        self.sidebar.control_panel_list.actionTriggered.emit(item, "star")
        self.sidebar.control_panel_list.actionTriggered.emit(item, "edit")
        self.sidebar.control_panel_list.actionTriggered.emit(item, "remove")

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
        populate_control_panel_list(self.sidebar.favorite_control_panel_list, [config])
        item = self.sidebar.favorite_control_panel_list.item(0)
        self.sidebar.favorite_control_panel_list.actionTriggered.emit(item, "star")
        self.assertEqual(self.calls, [("favorite", config.id, False)])

    def test_double_click_opens(self) -> None:
        config = make_config("Bench")
        populate_control_panel_list(self.sidebar.control_panel_list, [config])
        self.sidebar.control_panel_list.itemDoubleClicked.emit(self.sidebar.control_panel_list.item(0))
        self.assertEqual(self.calls, [("open", config.id)])

    def test_context_menu_lists_control_panel_actions(self) -> None:
        config = make_config("Bench")
        populate_control_panel_list(self.sidebar.control_panel_list, [config])
        item = self.sidebar.control_panel_list.item(0)
        menu = self.sidebar._build_control_panel_menu(
            self.sidebar.control_panel_list, item, is_favorites=False
        )
        titles = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual(
            titles,
            ["Open", "Add to Favorites", "Rename", "Duplicate", "Delete Control Panel"],
        )
        menu.deleteLater()

    def test_context_menu_duplicate_dispatches(self) -> None:
        config = make_config("Bench")
        populate_control_panel_list(self.sidebar.control_panel_list, [config])
        item = self.sidebar.control_panel_list.item(0)
        self.sidebar._on_control_panel_action(
            self.sidebar.control_panel_list, item, "duplicate"
        )
        self.assertIn(("duplicate", config.id), self.calls)

    def test_favorites_page_includes_control_panel_panel(self) -> None:
        self.assertIn("favorite_control_panel", self.sidebar.sections)
        favorites_mode = self.sidebar.rail_modes[0]
        self.assertIn("favorite_control_panel", favorites_mode.sections)
        splitter = self.sidebar.favorites_splitter
        self.assertIsNotNone(splitter)
        self.assertEqual(splitter.count(), 3)

    def test_control_panel_lists_are_draggable_with_sort_controls(self) -> None:
        # Both the saved and favourite control-panel lists reorder by drag.
        self.assertTrue(self.sidebar.control_panel_list.dragEnabled())
        self.assertTrue(self.sidebar.favorite_control_panel_list.dragEnabled())
        # A sort button + (hidden) combo back each list, like the file panels.
        for combo in (
            self.sidebar.control_panel_sort_combo,
            self.sidebar.favorite_control_panel_sort_combo,
        ):
            self.assertEqual(
                [combo.itemData(i) for i in range(combo.count())], ["Custom", "Name"]
            )
        self.assertIsNotNone(self.sidebar.control_panel_sort_button.menu())
        self.assertIsNotNone(self.sidebar.favorite_control_panel_sort_button.menu())

    def test_control_panel_sort_change_fires_callback(self) -> None:
        changes: list[str] = []
        sidebar = QuickActionsSidebar(
            actions=make_actions([]),
            command_primary_label="Send",
            file_primary_label="Run",
            include_control_panels=True,
            control_panel_sort_changed=lambda: changes.append("sort"),
            parent=self.parent,
        )
        try:
            combo = sidebar.control_panel_sort_combo
            combo.setCurrentIndex(combo.findData("Name"))
            self.assertEqual(changes, ["sort"])
        finally:
            sidebar.deleteLater()


if __name__ == "__main__":
    unittest.main()
