from __future__ import annotations

from pathlib import Path

# ``.cpz`` is the native ComPort Zone command file; ``.txt``/``.cmd``/``.scr`` stay
# supported for opening/adding. Open shows every command file by default; Save As
# defaults to ``.cpz`` (the first filter) while still allowing other extensions.
COMMAND_FILE_FILTER = "Command Files (*.cpz *.txt *.cmd *.scr);;ComPort Zone Files (*.cpz);;All Files (*)"
COMMAND_FILE_SAVE_FILTER = "ComPort Zone Files (*.cpz);;Command Files (*.txt *.cmd *.scr);;All Files (*)"
DEFAULT_COMMAND_FILE_NAME = "command-file.cpz"

# The extensions the GUI opens as command-file editor tabs (the ``.cpz`` association,
# ``comport-zone path.cmd`` on the shell, and drag-drop into the tab area all agree on
# this set). Kept here as the single source of truth — import it rather than re-listing.
COMMAND_FILE_EXTENSIONS = (".cpz", ".cmd", ".txt", ".scr")


def looks_like_command_file(path: str | Path) -> bool:
    """True when ``path`` has a recognised command-file extension."""
    return Path(path).suffix.lower() in COMMAND_FILE_EXTENSIONS


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
