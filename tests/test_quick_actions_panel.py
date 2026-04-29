import unittest

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.quick_actions_panel import (
    QuickActionsPanel,
    create_quick_command_list,
    create_quick_file_list,
    item_ids_in_order,
    populate_quick_command_list,
    populate_quick_file_list,
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
            section_title="Saved Commands",
            quick_list=panel_commands,
            action_rows=((QPushButton("Insert", parent),),),
            parent=parent,
        )
        file_panel = QuickActionsPanel(
            title="Quick Files",
            section_title="Saved Files",
            quick_list=panel_files,
            action_rows=((QPushButton("Open", parent),),),
            parent=parent,
        )
        try:
            populate_quick_command_list(standalone_commands, commands, selected_id="cmd-2")
            populate_quick_command_list(panel.quick_list, commands, selected_id="cmd-2")
            populate_quick_file_list(file_panel.quick_list, quick_files, selected_id="file-1")

            self.assertEqual(item_ids_in_order(standalone_commands), ["cmd-1", "cmd-2"])
            self.assertEqual(item_ids_in_order(panel.quick_list), ["cmd-1", "cmd-2"])
            self.assertEqual(standalone_commands.item(1).text(), "Boot: Wake")
            self.assertEqual(panel.quick_list.item(1).toolTip(), "Boot | 55 AA")
            self.assertEqual(selected_item_id(panel.quick_list), "cmd-2")
            self.assertEqual(selected_item_id(file_panel.quick_list), "file-1")
        finally:
            file_panel.deleteLater()
            panel.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
