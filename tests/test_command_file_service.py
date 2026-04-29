import unittest
from pathlib import Path

from ComPort_Zone.command_file_service import DEFAULT_COMMAND_FILE_NAME, CommandFileService


class CommandFileServiceTests(unittest.TestCase):
    def test_load_and_save_text_uses_utf8_and_creates_parent_directories(self) -> None:
        root = Path(__file__).with_name("_tmp_command_file_service")
        path = root / "nested" / "script.cmd"
        try:
            service = CommandFileService()

            service.save_text(path, "SEND *IDN?\n// cafe\n")

            self.assertTrue(path.exists())
            self.assertEqual(service.load_text(path), "SEND *IDN?\n// cafe\n")
        finally:
            path.unlink(missing_ok=True)
            nested = root / "nested"
            if nested.exists():
                nested.rmdir()
            if root.exists():
                root.rmdir()

    def test_default_paths_follow_current_document_or_workspace(self) -> None:
        service = CommandFileService()
        current = Path("C:/scripts/current.cmd")

        self.assertEqual(service.default_open_dir(current), Path("C:/scripts"))
        self.assertEqual(service.default_save_path(current), current)
        self.assertEqual(service.default_save_path(None).name, DEFAULT_COMMAND_FILE_NAME)


if __name__ == "__main__":
    unittest.main()
