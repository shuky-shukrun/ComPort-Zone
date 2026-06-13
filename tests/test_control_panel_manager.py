"""Tests for the control_panel manager dialog."""

from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QMessageBox

import ComPort_Zone.ui.dialogs.control_panel_manager as manager_module
from ComPort_Zone.control_panel_catalog import ControlPanelCatalog
from ComPort_Zone.control_panel_models import ControlPanelConfig, ControlPanelEntry
from ComPort_Zone.ui.dialogs.control_panel_manager import ControlPanelManagerDialog


def make_config(name: str) -> ControlPanelConfig:
    return ControlPanelConfig(name=name, entries=[ControlPanelEntry(label="V", command="MEAS?")])


class ControlPanelManagerDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.control_panels: list[ControlPanelConfig] = []
        self.catalog = ControlPanelCatalog(self.control_panels)
        self.opened: list[str] = []
        self.closed_tabs: list[str] = []
        self.saves = 0
        self.statuses: list[str] = []

    def make_dialog(self) -> ControlPanelManagerDialog:
        def save() -> None:
            self.saves += 1

        return ControlPanelManagerDialog(
            catalog=self.catalog,
            open_control_panel=self.opened.append,
            close_control_panel_tab=self.closed_tabs.append,
            save_settings=save,
            set_status=self.statuses.append,
        )

    def test_lists_control_panels_sorted_with_entry_counts(self) -> None:
        self.catalog.add(make_config("Zeta"))
        self.catalog.add(make_config("Alpha"))
        dialog = self.make_dialog()
        labels = [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]
        self.assertEqual(labels, ["Alpha  ·  1 entry", "Zeta  ·  1 entry"])
        dialog.deleteLater()

    def test_buttons_disabled_when_empty(self) -> None:
        dialog = self.make_dialog()
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertFalse(dialog.delete_button.isEnabled())
        self.assertTrue(dialog.new_button.isEnabled())
        dialog.deleteLater()

    def test_open_selected_invokes_callback_and_accepts(self) -> None:
        config = self.catalog.add(make_config("Bench"))
        dialog = self.make_dialog()
        dialog._open_selected()
        self.assertEqual(self.opened, [config.id])
        self.assertEqual(dialog.result(), 1)
        dialog.deleteLater()

    def test_duplicate_selected_saves_and_refreshes(self) -> None:
        self.catalog.add(make_config("Bench"))
        dialog = self.make_dialog()
        dialog._duplicate_selected()
        self.assertEqual(len(self.control_panels), 2)
        self.assertEqual(self.saves, 1)
        self.assertEqual(dialog.list_widget.count(), 2)
        dialog.deleteLater()

    def test_delete_selected_confirms_and_closes_open_tab(self) -> None:
        config = self.catalog.add(make_config("Bench"))
        dialog = self.make_dialog()
        original_question = QMessageBox.question
        manager_module.QMessageBox.question = staticmethod(
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )
        try:
            dialog._delete_selected()
        finally:
            manager_module.QMessageBox.question = original_question
        self.assertEqual(self.control_panels, [])
        self.assertEqual(self.closed_tabs, [config.id])
        self.assertEqual(self.saves, 1)
        dialog.deleteLater()

    def test_delete_declined_keeps_control_panel(self) -> None:
        self.catalog.add(make_config("Bench"))
        dialog = self.make_dialog()
        original_question = QMessageBox.question
        manager_module.QMessageBox.question = staticmethod(
            lambda *args, **kwargs: QMessageBox.StandardButton.No
        )
        try:
            dialog._delete_selected()
        finally:
            manager_module.QMessageBox.question = original_question
        self.assertEqual(len(self.control_panels), 1)
        self.assertEqual(self.closed_tabs, [])
        dialog.deleteLater()

    def test_rename_selected_dedupes(self) -> None:
        self.catalog.add(make_config("Bench"))
        target = self.catalog.add(make_config("Scope"))
        dialog = self.make_dialog()
        for row in range(dialog.list_widget.count()):
            if str(dialog.list_widget.item(row).data(manager_module.ROLE_CONTROL_PANEL_ID)) == target.id:
                dialog.list_widget.setCurrentRow(row)
                break
        original_get_text = manager_module.QInputDialog.getText
        manager_module.QInputDialog.getText = staticmethod(
            lambda *args, **kwargs: ("Bench", True)
        )
        try:
            dialog._rename_selected()
        finally:
            manager_module.QInputDialog.getText = original_get_text
        self.assertEqual(target.name, "Bench (2)")
        self.assertEqual(self.saves, 1)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
