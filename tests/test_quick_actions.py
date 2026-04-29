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
