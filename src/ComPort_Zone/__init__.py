from __future__ import annotations

from pathlib import Path

__all__ = ["__version__"]


def _read_version() -> str:
    version_file = Path(__file__).with_name("VERSION")
    try:
        return version_file.read_text(encoding="utf-8").strip() or "0.0.1"
    except OSError:
        return "0.0.1"


__version__ = _read_version()
