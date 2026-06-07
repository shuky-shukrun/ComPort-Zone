import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.quick_action_controller import QuickActionController
from ComPort_Zone.quick_actions import QuickActionLibrary, QuickCommandImportOptions


class QuickActionControllerHarness:
    def __init__(self, parent: QWidget, library: QuickActionLibrary) -> None:
        self.library = library
        self.refresh_from_settings_count = 0
        self.sync_count = 0
        self.command_refreshes: list[str | None] = []
        self.file_refreshes: list[str | None] = []
        self.save_count = 0
        self.statuses: list[str] = []
        self.confirm_calls: list[tuple[str, str]] = []
        self.controller = QuickActionController(
            parent=parent,
            library_supplier=lambda: self.library,
            refresh_from_settings=self.refresh_from_settings,
            sync_to_settings=self.sync_to_settings,
            refresh_commands=self.command_refreshes.append,
            refresh_files=self.file_refreshes.append,
            save_settings=self.save_settings,
            set_status=self.statuses.append,
            confirm_bulk_delete=self.confirm_bulk_delete,
        )

    def refresh_from_settings(self) -> None:
        self.refresh_from_settings_count += 1

    def sync_to_settings(self) -> None:
        self.sync_count += 1

    def save_settings(self) -> None:
        self.save_count += 1

    def confirm_bulk_delete(self, title: str, message: str) -> bool:
        self.confirm_calls.append((title, message))
        return True


class QuickActionControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_sort_mode_changes_sync_refresh_and_save(self) -> None:
        parent = QWidget()
        try:
            harness = QuickActionControllerHarness(parent, QuickActionLibrary())

            harness.controller.set_quick_command_sort_mode("Title")

            self.assertEqual(harness.library.command_sort_mode, "Title")
            self.assertEqual(harness.sync_count, 1)
            self.assertEqual(harness.command_refreshes, [None])
            self.assertEqual(harness.save_count, 1)
        finally:
            parent.deleteLater()

    def test_duplicate_quick_command_inserts_after_source_and_selects_duplicate(self) -> None:
        parent = QWidget()
        try:
            library = QuickActionLibrary(
                quick_commands=[
                    QuickCommand(id="first", label="First", command="one"),
                    QuickCommand(id="second", label="Second", command="two", group="Factory"),
                ]
            )
            harness = QuickActionControllerHarness(parent, library)

            harness.controller.duplicate_quick_command("first")

            self.assertEqual([command.display_label() for command in library.quick_commands], ["First", "First Copy", "Second"])
            duplicate = library.quick_commands[1]
            self.assertNotEqual(duplicate.id, "first")
            self.assertEqual(duplicate.command, "one")
            self.assertEqual(harness.command_refreshes, [duplicate.id])
            self.assertEqual(harness.save_count, 1)
        finally:
            parent.deleteLater()

    def test_delete_all_quick_commands_clears_hidden_groups_without_confirmation(self) -> None:
        parent = QWidget()
        try:
            library = QuickActionLibrary(
                quick_commands=[QuickCommand(id="cmd", label="Status", command="status")],
                command_hidden_groups=["Factory"],
            )
            harness = QuickActionControllerHarness(parent, library)

            self.assertTrue(harness.controller.delete_all_quick_commands(confirm=False))

            self.assertEqual(library.quick_commands, [])
            self.assertEqual(library.command_hidden_groups, [])
            self.assertEqual(harness.confirm_calls, [])
            self.assertEqual(harness.command_refreshes, [None])
            self.assertEqual(harness.statuses, ["Deleted 1 quick command."])
        finally:
            parent.deleteLater()

    def test_import_quick_commands_from_csv_uses_library_and_refreshes_selected_row(self) -> None:
        parent = QWidget()
        csv_path = Path(__file__).with_name("_tmp_controller_quick_commands.csv")
        csv_path.write_text(
            "label,command,description,send_mode,group,line_ending_override\n"
            "Read ID,*IDN?,,Text,General,\n",
            encoding="utf-8",
        )
        try:
            library = QuickActionLibrary()
            harness = QuickActionControllerHarness(parent, library)

            result = harness.controller.import_quick_commands_from_csv(
                csv_path,
                options=QuickCommandImportOptions(replace_existing=False, skip_duplicates=True),
            )

            self.assertEqual(result.imported_count, 1)
            self.assertEqual([command.command for command in library.quick_commands], ["*IDN?"])
            self.assertEqual(harness.command_refreshes, [library.quick_commands[0].id])
            self.assertEqual(harness.save_count, 1)
        finally:
            csv_path.unlink(missing_ok=True)
            parent.deleteLater()

    def test_set_quick_file_favorite_toggles_and_tracks_favorites_order(self) -> None:
        parent = QWidget()
        try:
            library = QuickActionLibrary(
                quick_files=[
                    QuickFile(id="alpha", label="Alpha", path="C:/alpha.cpz"),
                    QuickFile(id="beta", label="Beta", path="C:/beta.cpz"),
                ]
            )
            harness = QuickActionControllerHarness(parent, library)

            harness.controller.set_quick_file_favorite("beta", True)
            self.assertTrue(library.file_by_id("beta").favorite)
            self.assertEqual(
                [f.id for f in harness.controller.favorite_quick_files_snapshot()], ["beta"]
            )
            # The favourite-file order picked up the newly-starred file.
            self.assertEqual(library.favorite_file_order, ["beta"])
            self.assertEqual(harness.file_refreshes, ["beta"])
            self.assertEqual(harness.save_count, 1)

            # Un-starring prunes it from the favourites order.
            harness.controller.set_quick_file_favorite("beta", False)
            self.assertFalse(library.file_by_id("beta").favorite)
            self.assertEqual(library.favorite_file_order, [])
            self.assertEqual(harness.controller.favorite_quick_files_snapshot(), [])
        finally:
            parent.deleteLater()

    def test_reorder_favorite_commands_keeps_saved_order_intact(self) -> None:
        parent = QWidget()
        try:
            library = QuickActionLibrary(
                quick_commands=[
                    QuickCommand(id="a", label="A", command="a", favorite=True),
                    QuickCommand(id="b", label="B", command="b", favorite=False),
                    QuickCommand(id="c", label="C", command="c", favorite=True),
                ]
            )
            harness = QuickActionControllerHarness(parent, library)

            harness.controller.reorder_favorite_commands(["c", "a"], selected_id="c")

            self.assertEqual(library.favorite_command_order, ["c", "a"])
            self.assertEqual(library.favorite_command_sort_mode, "Custom")
            # Saved Commands order is unaffected (independent favourites order).
            self.assertEqual([c.id for c in library.quick_commands], ["a", "b", "c"])
            self.assertEqual(harness.command_refreshes, ["c"])
            self.assertEqual(harness.save_count, 1)
        finally:
            parent.deleteLater()

    def test_move_quick_file_persists_new_order(self) -> None:
        parent = QWidget()
        try:
            library = QuickActionLibrary(
                quick_files=[
                    QuickFile(id="alpha", label="Alpha", path="C:/alpha.txt"),
                    QuickFile(id="beta", label="Beta", path="C:/beta.txt"),
                ]
            )
            harness = QuickActionControllerHarness(parent, library)

            harness.controller.move_quick_file("beta", -1)

            self.assertEqual([quick_file.id for quick_file in library.quick_files], ["beta", "alpha"])
            self.assertEqual(harness.file_refreshes, ["beta"])
            self.assertEqual(harness.save_count, 1)
        finally:
            parent.deleteLater()


if __name__ == "__main__":
    unittest.main()
