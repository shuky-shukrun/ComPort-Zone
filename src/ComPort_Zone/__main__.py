from __future__ import annotations

import os
import sys

# The GUI can open these directly — e.g. when Windows launches a file via the ``.cpz``
# association, or ``comport-zone path.cmd`` is run from a shell. The extension set is
# shared with the editor / drag-drop via command_file_service.
from .command_file_service import COMMAND_FILE_EXTENSIONS


def _looks_like_command_file(arg: str) -> bool:
    return os.path.splitext(arg)[1].lower() in COMMAND_FILE_EXTENSIONS or os.path.isfile(arg)


def _gui_initial_files(args: list[str]) -> list[str]:
    candidates = args[1:] if (args and args[0] == "gui") else args
    return [c for c in candidates if not c.startswith("-") and _looks_like_command_file(c)]


def _is_gui_invocation(args: list[str]) -> bool:
    """GUI when there are no args, the first arg is ``gui``, or every arg is a file path
    (the Windows ``.cpz`` association opens files this way; several files dragged onto the
    exe arrive as multiple paths)."""
    if not args or args[0] == "gui":
        return True
    return all(not arg.startswith("-") and _looks_like_command_file(arg) for arg in args)


def _run_gui(initial_files: list[str] | None = None) -> int:
    try:
        from .app import run
    except ImportError as exc:  # pragma: no cover - exercised only without Qt installed
        if exc.name and exc.name.startswith("PySide6"):
            print("PySide6 is not installed. Run `python -m pip install -e .` first.")
            return 1
        raise

    return run(initial_files=initial_files)


def _run_cli(args: list[str]) -> int:
    from .cli.main import run as run_cli

    return run_cli(args)


def main() -> int:
    args = sys.argv[1:]
    if _is_gui_invocation(args):
        return _run_gui(_gui_initial_files(args))
    return _run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
