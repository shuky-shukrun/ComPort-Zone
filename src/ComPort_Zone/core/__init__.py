"""GUI-free public surface shared by the desktop app and the upcoming CLI.

Every module in this subpackage is required to be import-clean of PySide / Qt
so that ``import ComPort_Zone.core`` (and any submodule) can run inside a
headless CLI process. The ``tests/test_core_no_pyside.py`` integration test
enforces this invariant.
"""

from __future__ import annotations

from . import (
    batch,
    command_file_service,
    history,
    lan_core,
    library_lookup,
    locking,
    models,
    quick_actions,
    serial_core,
    session_log,
    settings_service,
    storage,
    transports,
    version_check,
)

__all__ = [
    "batch",
    "command_file_service",
    "history",
    "lan_core",
    "library_lookup",
    "locking",
    "models",
    "quick_actions",
    "serial_core",
    "session_log",
    "settings_service",
    "storage",
    "transports",
    "version_check",
]
