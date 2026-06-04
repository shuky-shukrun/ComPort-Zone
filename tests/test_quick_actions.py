import unittest
from pathlib import Path

from ComPort_Zone.models import QuickCommand, QuickFile
from ComPort_Zone.quick_actions import (
    QuickActionLibrary,
    QuickCommandImportOptions,
    QuickFileImportOptions,
)


class QuickActionLibraryTests(unittest.TestCase):
    def test_commands_sort_filter_and_reorder(self) -> None:
        library = QuickActionLibrary(
            quick_commands=[
                QuickCommand(id="a", label="Status", command="status", group="General"),
                QuickCommand(id="b", label="Boot", command="boot", group="Factory"),
                QuickCommand(id="c", label="Reset", command="reset", group="General"),
            ],
            command_sort_mode="Group",
            command_hidden_groups=["Factory"],
        )

        self.assertEqual([command.id for command in library.visible_commands()], ["c", "a"])
        self.assertFalse(library.can_manually_reorder_commands())

        library.command_hidden_groups = []
        library.command_sort_mode = "Custom"

        self.assertTrue(library.can_manually_reorder_commands())
        self.assertTrue(library.reorder_commands(["c", "a", "b"]))
        self.assertEqual([command.id for command in library.quick_commands], ["c", "a", "b"])

    def test_files_sort_and_force_custom_reorder(self) -> None:
        library = QuickActionLibrary(
            quick_files=[
                QuickFile(id="a", label="Factory", path="C:/z/factory.txt"),
                QuickFile(id="b", label="Bring-up", path="C:/a/bringup.txt"),
            ],
            file_sort_mode="Path",
        )

        self.assertEqual([quick_file.id for quick_file in library.visible_files()], ["b", "a"])
        self.assertTrue(library.reorder_files(["a", "b"], force_custom=True))
        self.assertEqual(library.file_sort_mode, "Custom")
        self.assertEqual([quick_file.id for quick_file in library.visible_files()], ["a", "b"])

    def test_favorite_commands_use_independent_order_and_respect_hidden_groups(self) -> None:
        library = QuickActionLibrary(
            quick_commands=[
                QuickCommand(id="a", label="A", command="a", favorite=True, group="General"),
                QuickCommand(id="b", label="B", command="b", favorite=False, group="General"),
                QuickCommand(id="c", label="C", command="c", favorite=True, group="Factory"),
            ],
        )
        # Favourites follow the saved order until the user drags them.
        self.assertEqual([c.id for c in library.favorite_commands()], ["a", "c"])

        # Drag-reorder writes an independent favourites order + forces Custom.
        self.assertTrue(library.reorder_favorite_commands(["c", "a"]))
        self.assertEqual(library.favorite_command_sort_mode, "Custom")
        self.assertEqual([c.id for c in library.favorite_commands()], ["c", "a"])
        # The full Saved list order is untouched by the favourites drag.
        self.assertEqual([c.id for c in library.quick_commands], ["a", "b", "c"])

        # Hiding a group folds its favourites away too (shared group control).
        library.command_hidden_groups = ["Factory"]
        self.assertEqual([c.id for c in library.favorite_commands()], ["a"])

    def test_favorite_order_sync_prunes_and_appends(self) -> None:
        library = QuickActionLibrary(
            quick_commands=[
                QuickCommand(id="a", label="A", command="a", favorite=True),
                QuickCommand(id="b", label="B", command="b", favorite=True),
            ],
            favorite_command_order=["b", "a", "ghost"],
        )
        # A stale id ("ghost") is pruned; present favourites keep the saved order.
        library.sync_favorite_command_order()
        self.assertEqual(library.favorite_command_order, ["b", "a"])

        # Newly favouriting a command appends it to the order.
        library.quick_commands.append(QuickCommand(id="c", label="C", command="c", favorite=True))
        library.sync_favorite_command_order()
        self.assertEqual(library.favorite_command_order, ["b", "a", "c"])

    def test_favorite_files_use_independent_order(self) -> None:
        library = QuickActionLibrary(
            quick_files=[
                QuickFile(id="a", label="A", path="C:/a.cpz", favorite=True),
                QuickFile(id="b", label="B", path="C:/b.cpz", favorite=False),
                QuickFile(id="c", label="C", path="C:/c.cpz", favorite=True),
            ],
        )
        self.assertEqual([f.id for f in library.favorite_files()], ["a", "c"])
        self.assertTrue(library.reorder_favorite_files(["c", "a"]))
        self.assertEqual(library.favorite_file_sort_mode, "Custom")
        self.assertEqual([f.id for f in library.favorite_files()], ["c", "a"])
        # Saved Files order is independent of the favourites drag.
        self.assertEqual([f.id for f in library.quick_files], ["a", "b", "c"])

    def test_command_csv_append_replace_and_duplicate_detection(self) -> None:
        csv_path = Path(__file__).with_name("_tmp_quick_commands.csv")
        csv_path.unlink(missing_ok=True)
        try:
            csv_path.write_text(
                "label,command,description,send_mode,group,line_ending_override\n"
                "Status,status,,Text,General,LF\n"
                "Reset,reset,,Text,General,\n",
                encoding="utf-8",
            )
            library = QuickActionLibrary(
                quick_commands=[QuickCommand(label="Status", command="status", group="General")]
            )

            append = library.import_commands_from_csv(
                csv_path,
                options=QuickCommandImportOptions(replace_existing=False, skip_duplicates=True),
            )
            self.assertEqual((append.imported_count, append.skipped_count), (1, 1))
            self.assertEqual([command.command for command in library.quick_commands], ["status", "reset"])

            replace = library.import_commands_from_csv(
                csv_path,
                options=QuickCommandImportOptions(replace_existing=True, skip_duplicates=True),
            )
            self.assertEqual((replace.imported_count, replace.skipped_count), (2, 0))
            self.assertEqual([command.command for command in library.quick_commands], ["status", "reset"])
        finally:
            csv_path.unlink(missing_ok=True)

    def test_file_csv_append_replace_and_duplicate_detection(self) -> None:
        csv_path = Path(__file__).with_name("_tmp_quick_files.csv")
        csv_path.unlink(missing_ok=True)
        try:
            csv_path.write_text(
                "label,path\n"
                "Bring-up,C:/scripts/bringup.txt\n"
                "Factory,C:/scripts/factory.txt\n",
                encoding="utf-8",
            )
            library = QuickActionLibrary(
                quick_files=[QuickFile(label="Existing", path="C:/scripts/bringup.txt")]
            )

            append = library.import_files_from_csv(
                csv_path,
                options=QuickFileImportOptions(replace_existing=False, skip_duplicates=True),
            )
            self.assertEqual((append.imported_count, append.skipped_count), (1, 1))
            self.assertEqual([quick_file.path for quick_file in library.quick_files], [
                "C:/scripts/bringup.txt",
                "C:/scripts/factory.txt",
            ])

            replace = library.import_files_from_csv(
                csv_path,
                options=QuickFileImportOptions(replace_existing=True, skip_duplicates=True),
            )
            self.assertEqual((replace.imported_count, replace.skipped_count), (2, 0))
            self.assertEqual([quick_file.label for quick_file in library.quick_files], ["Bring-up", "Factory"])
        finally:
            csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
