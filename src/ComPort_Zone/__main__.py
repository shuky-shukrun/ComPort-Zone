from __future__ import annotations

import sys


def _is_gui_invocation(args: list[str]) -> bool:
    """Backwards-compatible: no args, or first arg is exactly ``gui``."""
    if not args:
        return True
    return args[0] == "gui"


def _run_gui() -> int:
    try:
        from .app import run
    except ImportError as exc:  # pragma: no cover - exercised only without Qt installed
        if exc.name and exc.name.startswith("PySide6"):
            print("PySide6 is not installed. Run `python -m pip install -e .` first.")
            return 1
        raise

    return run()


def _run_cli(args: list[str]) -> int:
    from .cli.main import run as run_cli

    return run_cli(args)


def main() -> int:
    args = sys.argv[1:]
    if _is_gui_invocation(args):
        return _run_gui()
    return _run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
