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
            sidebar.quick_command_list.actionTriggered.emit(item)
            self.assertEqual(calls, ["command-primary"])
            # The inline affordance acts on the clicked row, so it is selected.
            self.assertIs(sidebar.quick_command_list.currentItem(), item)
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
                ["All quick actions", "Quick commands", "Quick files", "History"],
            )
            populate_quick_history_list(sidebar.quick_history_list, ["*IDN?", "MEAS:VOLT?"])
            self.assertEqual(sidebar.quick_history_list.count(), 2)
            sidebar.quick_history_list.actionTriggered.emit(sidebar.quick_history_list.item(0))
            self.assertEqual(resends, ["*IDN?"])
        finally:
            sidebar.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
