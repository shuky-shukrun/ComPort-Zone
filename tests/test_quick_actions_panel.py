import unittest

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.quick_actions_panel import (
    QUICK_ACTION_ITEM_HEIGHT,
    FAVORITES_EMPTY_HINT,
    QUICK_FILE_EMPTY_HINT,
    ROLE_BADGE,
    ROLE_FAVORITE,
    EmptyHintListWidget,
    QuickActionsDrawer,
    QuickActionsRailMode,
    QuickActionsPanel,
    create_quick_command_list,
    create_quick_file_list,
    item_ids_in_order,
    populate_quick_command_list,
    populate_quick_file_list,
    row_action_keys,
    selected_item_id,
)


class QuickActionsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_panel_and_standalone_lists_render_same_quick_action_data(self) -> None:
        commands = [
            QuickCommand(id="cmd-1", label="Identity", command="*IDN?", group="General"),
            QuickCommand(id="cmd-2", label="Wake", command="55 AA", send_mode="Hex Bytes", group="Boot"),
        ]
        quick_files = [
            QuickFile(id="file-1", label="Bring-up", path="C:/scripts/bringup.txt"),
        ]
        parent = QWidget()
        standalone_commands = create_quick_command_list(parent, tooltip="Commands")
        panel_commands = create_quick_command_list(parent, tooltip="Commands")
        panel_files = create_quick_file_list(parent, tooltip="Files")
        panel = QuickActionsPanel(
            title="Quick Commands",
            quick_list=panel_commands,
            parent=parent,
        )
        file_panel = QuickActionsPanel(
            title="Quick Files",
            quick_list=panel_files,
            parent=parent,
        )
        try:
            populate_quick_command_list(standalone_commands, commands, selected_id="cmd-2")
            populate_quick_command_list(panel.quick_list, commands, selected_id="cmd-2")
            populate_quick_file_list(file_panel.quick_list, quick_files, selected_id="file-1")

            self.assertEqual(item_ids_in_order(standalone_commands), ["cmd-1", "cmd-2"])
            self.assertEqual(item_ids_in_order(panel.quick_list), ["cmd-1", "cmd-2"])
            self.assertEqual(standalone_commands.item(1).text(), "Wake")
            self.assertEqual(standalone_commands.item(1).data(ROLE_BADGE), "Boot")
            self.assertEqual(panel.quick_list.item(1).toolTip(), "Boot | 55 AA")
            self.assertEqual(panel.quick_list.item(0).sizeHint().height(), QUICK_ACTION_ITEM_HEIGHT)
            self.assertEqual(file_panel.quick_list.item(0).sizeHint().height(), QUICK_ACTION_ITEM_HEIGHT)
            self.assertEqual(selected_item_id(panel.quick_list), "cmd-2")
            self.assertEqual(selected_item_id(file_panel.quick_list), "file-1")
        finally:
            file_panel.deleteLater()
            panel.deleteLater()
            parent.deleteLater()

    def test_file_rows_expose_star_then_play_and_carry_favorite_state(self) -> None:
        # Files are favouritable now: a star (toggle) sits left of the play glyph.
        self.assertEqual(row_action_keys("file"), ["star", "play"])
        self.assertEqual(row_action_keys("command"), ["star", "send"])

        parent = QWidget()
        try:
            quick_list = create_quick_file_list(parent, tooltip="")
            populate_quick_file_list(
                quick_list,
                [
                    QuickFile(id="a", label="Fav", path="C:/a.cpz", favorite=True),
                    QuickFile(id="b", label="Plain", path="C:/b.cpz", favorite=False),
                ],
            )
            self.assertTrue(bool(quick_list.item(0).data(ROLE_FAVORITE)))
            self.assertFalse(bool(quick_list.item(1).data(ROLE_FAVORITE)))
        finally:
            parent.deleteLater()

    def test_empty_quick_lists_expose_hint_without_adding_rows(self) -> None:
        parent = QWidget()
        command_list = create_quick_command_list(parent, tooltip="Commands")
        file_list = create_quick_file_list(parent, tooltip="Files")
        try:
            # The hint is painted on the viewport, not inserted as a sentinel
            # item, so an empty list still reports zero rows and the id helpers
            # stay clean.
            self.assertIsInstance(command_list, EmptyHintListWidget)
            self.assertIsInstance(file_list, EmptyHintListWidget)
            self.assertEqual(command_list.count(), 0)
            self.assertEqual(file_list.count(), 0)
            self.assertEqual(item_ids_in_order(command_list), [])
            self.assertEqual(item_ids_in_order(file_list), [])
            self.assertEqual(command_list.placeholderText(), FAVORITES_EMPTY_HINT)
            self.assertEqual(file_list.placeholderText(), QUICK_FILE_EMPTY_HINT)

            # Real rows are the only rows: populating yields exactly the ids fed in.
            populate_quick_command_list(
                command_list,
                [QuickCommand(id="cmd-1", label="Identity", command="*IDN?", group="General")],
            )
            self.assertEqual(command_list.count(), 1)
            self.assertEqual(item_ids_in_order(command_list), ["cmd-1"])
        finally:
            parent.deleteLater()

    def test_drawer_modes_toggle_section_visibility(self) -> None:
        parent = QWidget()
        command_page = QuickActionsPanel(
            title="Quick Commands",
            quick_list=create_quick_command_list(parent, tooltip="Commands"),
            parent=parent,
        )
        file_page = QuickActionsPanel(
            title="Quick Files",
            quick_list=create_quick_file_list(parent, tooltip="Files"),
            parent=parent,
        )
        drawer = QuickActionsDrawer(
            sections={"command": command_page, "file": file_page},
            rail_modes=[
                QuickActionsRailMode("all", QStyle.StandardPixmap.SP_FileDialogListView, "All", ("command", "file")),
                QuickActionsRailMode("commands", QStyle.StandardPixmap.SP_CommandLink, "Quick commands", ("command",)),
                QuickActionsRailMode("files", QStyle.StandardPixmap.SP_DirOpenIcon, "Quick files", ("file",)),
            ],
            parent=parent,
        )
        try:
            self.assertEqual(drawer.pages.count(), 3)
            self.assertEqual([button.toolTip() for button in drawer.rail_buttons], ["All", "Quick commands", "Quick files"])
            # Default 'All' shows both sections.
            self.assertEqual(drawer.pages.currentIndex(), 0)
            self.assertFalse(command_page.isHidden())
            self.assertFalse(file_page.isHidden())
            # 'Quick commands' hides the file section.
            drawer.rail_buttons[1].click()
            self.assertEqual(drawer.pages.currentIndex(), 1)
            self.assertFalse(command_page.isHidden())
            self.assertTrue(file_page.isHidden())
            # 'Quick files' hides the command section.
            drawer.rail_buttons[2].click()
            self.assertTrue(command_page.isHidden())
            self.assertFalse(file_page.isHidden())
            drawer.select_page(99)
            self.assertEqual(drawer.pages.currentIndex(), 2)
            drawer.select_page(-1)
            self.assertEqual(drawer.pages.currentIndex(), 0)
        finally:
            drawer.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
