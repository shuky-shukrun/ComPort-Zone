import unittest

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.quick_actions_panel import (
    QuickActionsPanel,
    create_quick_command_list,
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
        panel = QuickActionsPanel(
            command_action_text="Insert",
            command_action=lambda: None,
            file_action_text="Open",
            file_action=lambda: None,
            parent=parent,
        )
        try:
            populate_quick_command_list(standalone_commands, commands, selected_id="cmd-2")
            populate_quick_command_list(panel.quick_command_list, commands, selected_id="cmd-2")
            populate_quick_file_list(panel.quick_file_list, quick_files, selected_id="file-1")

            self.assertEqual(item_ids_in_order(standalone_commands), ["cmd-1", "cmd-2"])
            self.assertEqual(item_ids_in_order(panel.quick_command_list), ["cmd-1", "cmd-2"])
            self.assertEqual(standalone_commands.item(1).text(), "Boot: Wake")
            self.assertEqual(panel.quick_command_list.item(1).toolTip(), "Boot | 55 AA")
            self.assertEqual(selected_item_id(panel.quick_command_list), "cmd-2")
            self.assertEqual(selected_item_id(panel.quick_file_list), "file-1")
        finally:
            panel.deleteLater()
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
