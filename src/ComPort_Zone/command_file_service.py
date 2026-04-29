from __future__ import annotations

from pathlib import Path

COMMAND_FILE_FILTER = "Text Files (*.txt *.cmd *.scr);;All Files (*)"
DEFAULT_COMMAND_FILE_NAME = "command-file.txt"


class CommandFileService:
    def __init__(self, *, encoding: str = "utf-8") -> None:
        self.encoding = encoding

    def load_text(self, path: Path) -> str:
        return path.read_text(encoding=self.encoding)

    def save_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=self.encoding)

    def default_open_dir(self, current_path: Path | None) -> Path:
        return current_path.parent if current_path else Path.cwd()

    def default_save_path(self, current_path: Path | None) -> Path:
        return current_path or Path.cwd() / DEFAULT_COMMAND_FILE_NAME
