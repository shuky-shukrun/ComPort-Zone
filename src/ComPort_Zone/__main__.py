from __future__ import annotations

import os
import sys

# Extensions the GUI can open directly — e.g. when Windows launches a file via the
# ``.cpz`` association, or ``comport-zone path.cmd`` is run from a shell.
_COMMAND_FILE_EXTENSIONS = {".cpz", ".cmd", ".txt", ".scr"}


def _looks_like_command_file(arg: str) -> bool:
    return os.path.splitext(arg)[1].lower() in _COMMAND_FILE_EXTENSIONS or os.path.isfile(arg)


def _gui_initial_file(args: list[str]) -> str | None:
    candidates = args[1:] if (args and args[0] == "gui") else args
    for candidate in candidates:
        if not candidate.startswith("-") and _looks_like_command_file(candidate):
            return candidate
    return None


def _is_gui_invocation(args: list[str]) -> bool:
    """GUI when there are no args, the first arg is ``gui``, or a single file path is
    passed (the Windows ``.cpz`` association opens files this way)."""
    if not args or args[0] == "gui":
        return True
    return len(args) == 1 and _looks_like_command_file(args[0])


def _run_gui(initial_file: str | None = None) -> int:
    try:
        from .app import run
    except ImportError as exc:  # pragma: no cover - exercised only without Qt installed
        if exc.name and exc.name.startswith("PySide6"):
            print("PySide6 is not installed. Run `python -m pip install -e .` first.")
            return 1
        raise

    return run(initial_file)


def _run_cli(args: list[str]) -> int:
    from .cli.main import run as run_cli

    return run_cli(args)


def main() -> int:
    args = sys.argv[1:]
    if _is_gui_invocation(args):
        return _run_gui(_gui_initial_file(args))
    return _run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
