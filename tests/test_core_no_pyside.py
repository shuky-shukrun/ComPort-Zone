"""Guards the GUI/core boundary.

The CLI process must never trigger a PySide6 import. This test spawns a
fresh Python interpreter, imports every public submodule of
``ComPort_Zone.core``, and asserts that no PySide6 modules ended up in
``sys.modules``. Running in a subprocess matters: the surrounding test
suite imports PySide6 transitively for the GUI widget tests, which would
contaminate ``sys.modules`` for an in-process check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"


CORE_SUBMODULES = (
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
)


def _run_isolation_check(import_statements: str) -> dict:
    """Run ``import_statements`` in a fresh Python process and return a dict
    summarising whether any PySide6 module showed up in ``sys.modules``.
    """
    script = textwrap.dedent(
        f"""
        import json, sys
        {import_statements}
        offenders = sorted(
            name for name in sys.modules
            if name == "PySide6" or name.startswith("PySide6.")
        )
        json.dump(
            {{"offenders": offenders, "module_count": len(sys.modules)}},
            sys.stdout,
        )
        """
    )

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    sep = os.pathsep
    env["PYTHONPATH"] = (
        f"{SRC_PATH}{sep}{existing}" if existing else str(SRC_PATH)
    )

    # Note: do NOT pass ``-I`` here — isolated mode drops PYTHONPATH, which we
    # need to point the subprocess at the in-source ComPort_Zone package.
    # ``-E`` is also off for the same reason. The fresh subprocess is enough
    # to give us a clean ``sys.modules`` for the assertion.
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"Isolation subprocess failed (exit {completed.returncode}).\n"
            f"--- stdout ---\n{completed.stdout}\n"
            f"--- stderr ---\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


class CoreNoPySideTests(unittest.TestCase):
    def test_importing_core_package_does_not_load_pyside(self) -> None:
        result = _run_isolation_check("import ComPort_Zone.core")

        self.assertEqual(
            result["offenders"],
            [],
            msg=(
                "Importing ComPort_Zone.core loaded PySide6 modules: "
                f"{result['offenders']!r}. The core package must remain "
                "GUI-free so the CLI can use it."
            ),
        )

    def test_importing_each_core_submodule_does_not_load_pyside(self) -> None:
        # One subprocess per submodule so a regression in any single module
        # is easy to pinpoint from the failure message.
        for name in CORE_SUBMODULES:
            with self.subTest(submodule=name):
                result = _run_isolation_check(
                    f"import ComPort_Zone.core.{name}"
                )
                self.assertEqual(
                    result["offenders"],
                    [],
                    msg=(
                        f"Importing ComPort_Zone.core.{name} loaded PySide6: "
                        f"{result['offenders']!r}."
                    ),
                )


if __name__ == "__main__":
    unittest.main()
