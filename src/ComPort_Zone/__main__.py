from __future__ import annotations

import sys


def main() -> int:
    try:
        from .app import run
    except ImportError as exc:  # pragma: no cover - exercised only without Qt installed
        if exc.name and exc.name.startswith("PySide6"):
            print("PySide6 is not installed. Run `python -m pip install -e .` first.")
            return 1
        raise

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
