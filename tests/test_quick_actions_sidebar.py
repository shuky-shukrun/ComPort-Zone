import unittest

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

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


class QuickActionsSidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_sidebar_builds_shared_terminal_or_editor_action_shape(self) -> None:
        parent = QWidget()
        calls: list[str] = []

        def remember(name: str):
            return lambda: calls.append(name)

        sidebar = QuickActionsSidebar(
            actions=QuickActionsSidebarActions(
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
            ),
            command_primary_label="Insert",
            file_primary_label="Open",
            parent=parent,
        )
        try:
            self.assertEqual(sidebar.pages.count(), 2)
            self.assertEqual(sidebar.quick_sort_combo.count(), 3)
            self.assertEqual(sidebar.quick_file_sort_combo.count(), 3)
            self.assertEqual(
                action_rows(sidebar.pages.widget(0)),
                [
                    ["Insert", "Add Command"],
                    ["Edit", "Delete"],
                    ["Move Up", "Move Down"],
                    ["Import CSV", "Export CSV"],
                ],
            )
            self.assertEqual(
                action_rows(sidebar.pages.widget(1)),
                [
                    ["Open", "Add File"],
                    ["Edit", "Delete"],
                    ["Move Up", "Move Down"],
                    ["Import CSV", "Export CSV"],
                ],
            )

            sidebar.command_primary_button.click()
            sidebar.file_primary_button.click()

            self.assertEqual(calls, ["command-primary", "file-primary"])
        finally:
            sidebar.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
