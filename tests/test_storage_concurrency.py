"""Verifies that concurrent SettingsStore writes never corrupt settings.json.

Two processes hammer ``save_payload`` against the same target file while the
parent process repeatedly reads the file and asserts it parses as valid
JSON. With the Windows advisory lock + atomic temp-rename in
:mod:`ComPort_Zone.storage`, every read sees a fully-written payload from
one writer or the other — never a torn write.

Skipped on non-Windows because the lock is a no-op there (the GUI and CLI
are Windows-only); the test still exercises the atomic-rename code path on
those platforms when run manually.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"

WORKER_SCRIPT = textwrap.dedent(
    """
    import json, sys, traceback
    from pathlib import Path
    from ComPort_Zone.storage import SettingsStore

    target = Path(sys.argv[1])
    writer_id = sys.argv[2]
    iterations = int(sys.argv[3])

    store = SettingsStore(target)
    for index in range(iterations):
        payload = {
            "writer": writer_id,
            "iteration": index,
            "schema_version": 2,
            "noise": "x" * 256,
        }
        try:
            ok = store.save_payload(payload)
        except Exception:
            sys.stderr.write(f"writer {writer_id} EXCEPTION at iteration {index}:\\n")
            traceback.print_exc()
            sys.exit(2)
        if not ok:
            sys.stderr.write(f"writer {writer_id} save returned False at iteration {index}\\n")
            sys.exit(1)
    """
)


def _env_with_src() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    sep = os.pathsep
    env["PYTHONPATH"] = (
        f"{SRC_PATH}{sep}{existing}" if existing else str(SRC_PATH)
    )
    return env


class SettingsStoreConcurrencyTests(unittest.TestCase):
    def test_concurrent_writers_never_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "settings.json"

            env = _env_with_src()
            iterations = 15
            writers = [
                subprocess.Popen(
                    [sys.executable, "-c", WORKER_SCRIPT, str(target), writer_id, str(iterations)],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                for writer_id in ("alpha", "beta")
            ]

            torn_reads: list[str] = []
            start = time.monotonic()
            # Poll-read while writers run. The deadline guards against a hung
            # writer; in practice the writers finish in well under a second.
            while any(proc.poll() is None for proc in writers) and time.monotonic() - start < 30:
                try:
                    text = target.read_text(encoding="utf-8")
                except (FileNotFoundError, PermissionError):
                    continue
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    torn_reads.append(f"{exc}: {text[:120]!r}")

            writer_stderr: list[str] = []
            for proc in writers:
                stderr_bytes = proc.communicate(timeout=30)[1]
                if stderr_bytes:
                    writer_stderr.append(stderr_bytes.decode(errors="replace"))
            for proc in writers:
                self.assertEqual(
                    proc.returncode,
                    0,
                    msg=(
                        "A writer subprocess failed (rc="
                        f"{proc.returncode}). stderr:\n"
                        + "\n---\n".join(writer_stderr)
                    ),
                )

            self.assertEqual(torn_reads, [], msg="Detected torn JSON reads during concurrent writes.")

            # Final state must be valid and from one of the two writers.
            final = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn(final["writer"], {"alpha", "beta"})
            self.assertEqual(final["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
