"""Freeze-watchdog install must survive a windowed (no-console) build."""

from __future__ import annotations

import faulthandler
import sys
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone import app as app_module


class FreezeWatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_install_survives_when_stderr_is_none(self) -> None:
        # Regression: a windowed PyInstaller build has no console, so
        # sys.stderr is None. A bare faulthandler.enable() raised
        # "RuntimeError: sys.stderr is None" and crashed the packaged app
        # on launch (v0.5.0). The watchdog must point faulthandler at its
        # own dump file and never block startup.
        tmp_dir = Path(__file__).with_name("_tmp_freeze_watchdog")
        dump_path = tmp_dir / "freeze-dump.txt"
        parent = QWidget()
        timer = None
        original_stderr = sys.stderr
        try:
            sys.stderr = None  # simulate the no-console frozen app
            with mock.patch.object(app_module, "freeze_dump_path", lambda: dump_path):
                timer = app_module.install_freeze_watchdog(parent)
            self.assertIsNotNone(timer)  # installed without raising
            self.assertTrue(faulthandler.is_enabled())
            self.assertTrue(dump_path.exists())
        finally:
            sys.stderr = original_stderr
            faulthandler.cancel_dump_traceback_later()
            try:
                faulthandler.disable()
            except Exception:
                pass
            if timer is not None:
                timer.stop()
            parent.deleteLater()
            self.qt.processEvents()
            if app_module._freeze_dump_file is not None:
                try:
                    app_module._freeze_dump_file.close()
                except Exception:
                    pass
                app_module._freeze_dump_file = None
            try:
                dump_path.unlink(missing_ok=True)
                tmp_dir.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
