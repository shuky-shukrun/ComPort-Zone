import unittest

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ComPort_Zone.models import QuickCommand
from ComPort_Zone.quick_actions_panel import (
    populate_quick_command_list,
    populate_quick_history_list,
)
from ComPort_Zone.quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions


def action_rows(page) -> list[list[str]]:
    rows: list[list[str]] = []
    layout = page.layout()
    for index in range(layout.count()):
        row_layout = layout.itemAt(index).layout()
        if row_layout is None:
            continue
        row = [
            row_layout.itemAt(item_index).widget().text()
            for item_index in range(row_layout.count())
            if isinstance(row_layout.itemAt(item_index).widget(), QPushButton)
        ]
        if row:
            rows.append(row)
    return rows


def make_actions(calls: list[str]) -> QuickActionsSidebarActions:
    def remember(name: str):
        return lambda: calls.append(name)

    return QuickActionsSidebarActions(
        command_primary=remember("command-primary"),
        file_primary=remember("file-primary"),
        add_command=remember("add-command"),
        edit_command=remember("edit-command"),
        delete_command=remember("delete-command"),
        move_command_up=remember("move-command-up"),
        move_command_down=remember("move-command-down"),
        import_commands=remember("import-commands"),
        export_commands=remember("export-commands"),
        add_file=remember("add-file"),
        edit_file=remember("edit-file"),
        delete_file=remember("delete-file"),
        move_file_up=remember("move-file-up"),
        move_file_down=remember("move-file-down"),
        import_files=remember("import-files"),
        export_files=remember("export-files"),
    )


class QuickActionsSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_sidebar_drops_the_action_button_grid(self) -> None:
        parent = QWidget()
        calls: list[str] = []
        sidebar = QuickActionsSidebar(
            actions=make_actions(calls),
            command_primary_label="Insert",
            file_primary_label="Open",
            parent=parent,
        )
        try:
            # Rail modes: All, Quick Send, Quick Files (no History without include_history).
            self.assertEqual(sidebar.pages.count(), 3)
            self.assertEqual(sidebar.quick_sort_combo.count(), 3)
            self.assertEqual(sidebar.quick_file_sort_combo.count(), 3)
            # The legacy 8-button grid is gone; primary actions are inline now.
            self.assertEqual(action_rows(sidebar.pages.widget(0)), [])
            self.assertEqual(action_rows(sidebar.pages.widget(1)), [])
            # Legacy buttons are retained (hidden) for existing enable-state wiring.
            self.assertFalse(sidebar.command_primary_button.isVisible())
            sidebar.command_primary_button.click()
            sidebar.file_primary_button.click()
            self.assertEqual(calls, ["command-primary", "file-primary"])
        finally:
            sidebar.deleteLater()
            parent.deleteLater()

    def test_sort_and_group_are_header_icons_that_collapse_into_overflow(self) -> None:
        from PySide6.QtWidgets import QToolButton

        parent = QWidget()
        calls: list[str] = []
        sidebar = QuickActionsSidebar(
            actions=make_actions(calls),
            command_primary_label="Insert",
            file_primary_label="Open",
            group_menu_provider=lambda menu: menu.addAction("Boot"),
            parent=parent,
        )
        try:
            # Sort/group are compact header icon buttons; the combos persist hidden.
            # (The group button's menu is host-supplied, so it is not asserted here.)
            self.assertIsNotNone(sidebar.quick_sort_button.menu())
            self.assertTrue(sidebar.quick_sort_combo.isHidden())
            self.assertTrue(sidebar.quick_file_sort_combo.isHidden())

            # The sort popup mirrors the hidden combo's modes.
            sort_menu = sidebar.quick_sort_button.menu()
            sort_menu.aboutToShow.emit()
            self.assertEqual(
                [action.text() for action in sort_menu.actions()],
                [sidebar.quick_sort_combo.itemText(i) for i in range(sidebar.quick_sort_combo.count())],
            )

            command_header = sidebar.sections["command"]._header
            overflow = next(b for b in command_header.findChildren(QToolButton) if b.text() == "⋯")

            # Visible icons -> overflow has no Sort/Groups submenus.
            sidebar.quick_sort_button.setVisible(True)
            sidebar.quick_group_button.setVisible(True)
            overflow.menu().aboutToShow.emit()
            wide = [a.text() for a in overflow.menu().actions()]
            self.assertNotIn("Sort", wide)
            self.assertNotIn("Groups", wide)

            # Collapsed icons -> overflow folds in Sort + Groups submenus.
            sidebar.quick_sort_button.setVisible(False)
            sidebar.quick_group_button.setVisible(False)
            overflow.menu().aboutToShow.emit()
            collapsed = [a.text() for a in overflow.menu().actions()]
            self.assertIn("Sort", collapsed)
            self.assertIn("Groups", collapsed)
        finally:
            sidebar.deleteLater()
            parent.deleteLater()

    def test_inline_row_action_selects_then_dispatches_primary(self) -> None:
        parent = QWidget()
        calls: list[str] = []
        sidebar = QuickActionsSidebar(
            actions=make_actions(calls),
            command_primary_label="Send",
            file_primary_label="Run",
            parent=parent,
        )
        try:
            populate_quick_command_list(
                sidebar.quick_command_list,
                [QuickCommand(id="a", command="*RST"), QuickCommand(id="b", command="*IDN?")],
            )
            item = sidebar.quick_command_list.item(1)
            sidebar.quick_command_list.actionTriggered.emit(item, "send")
            self.assertEqual(calls, ["command-primary"])
            # The inline affordance acts on the clicked row, so it is selected.
            self.assertIs(sidebar.quick_command_list.currentItem(), item)
        finally:
            sidebar.deleteLater()
            parent.deleteLater()

    def test_file_star_toggles_favorite_and_play_runs_by_id(self) -> None:
        from ComPort_Zone.models import QuickFile
        from ComPort_Zone.quick_actions_panel import populate_quick_file_list

        parent = QWidget()
        calls: list[str] = []
        toggles: list[tuple[str, bool]] = []
        runs: list[str] = []
        actions = make_actions(calls)
        actions.file_favorite_toggle = lambda fid, fav: toggles.append((fid, fav))
        actions.file_use_by_id = lambda fid: runs.append(fid)
        sidebar = QuickActionsSidebar(
            actions=actions,
            command_primary_label="Send",
            file_primary_label="Run",
            parent=parent,
        )
        try:
            populate_quick_file_list(
                sidebar.quick_file_list,
                [QuickFile(id="f1", label="Bring-up", path="C:/bringup.cpz", favorite=False)],
            )
            item = sidebar.quick_file_list.item(0)
            # The star is the favourite toggle (file was not a favourite).
            sidebar.quick_file_list.actionTriggered.emit(item, "star")
            self.assertEqual(toggles, [("f1", True)])
            # Play runs the file by id (works for the favourites list too).
            sidebar.quick_file_list.actionTriggered.emit(item, "play")
            self.assertEqual(runs, ["f1"])
            # Favorites surfaces its own command + file panels.
            self.assertEqual(sidebar.rail_buttons[0].toolTip(), "Favorites")
            self.assertTrue(sidebar.favorite_file_list.dragEnabled())
            self.assertTrue(sidebar.favorite_command_list.dragEnabled())
        finally:
            sidebar.deleteLater()
            parent.deleteLater()

    def test_favorites_panels_are_collapsible_and_share_a_splitter(self) -> None:
        parent = QWidget()
        sidebar = QuickActionsSidebar(
            actions=make_actions([]),
            command_primary_label="Send",
            file_primary_label="Run",
            parent=parent,
        )
        try:
            # The two favourites panels live in one vertical splitter (resizable).
            self.assertIsNotNone(sidebar.favorites_splitter)
            self.assertEqual(sidebar.favorites_splitter.count(), 2)
            # Both favourites panels are collapsible (carry a header chevron).
            self.assertIsNotNone(sidebar.favorites_panel._collapse_button)
            self.assertIsNotNone(sidebar.favorite_files_panel._collapse_button)
            self.assertFalse(sidebar.favorites_panel.is_collapsed())
            sidebar.favorites_panel.set_collapsed(True)
            self.assertTrue(sidebar.favorites_panel.is_collapsed())
        finally:
            sidebar.deleteLater()
            parent.deleteLater()

    def test_history_page_is_added_and_resends(self) -> None:
        parent = QWidget()
        calls: list[str] = []
        resends: list[str] = []
        sidebar = QuickActionsSidebar(
            actions=make_actions(calls),
            command_primary_label="Send",
            file_primary_label="Run",
            include_history=True,
            history_primary=resends.append,
            parent=parent,
        )
        try:
            self.assertEqual(sidebar.pages.count(), 4)
            self.assertEqual(
                [button.toolTip() for button in sidebar.rail_buttons],
                ["Favorites", "Saved Commands", "Files", "History"],
            )
            populate_quick_history_list(sidebar.quick_history_list, ["*IDN?", "MEAS:VOLT?"])
            self.assertEqual(sidebar.quick_history_list.count(), 2)
            sidebar.quick_history_list.actionTriggered.emit(sidebar.quick_history_list.item(0), "send")
            self.assertEqual(resends, ["*IDN?"])
        finally:
            sidebar.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
