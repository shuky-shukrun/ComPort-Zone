from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .lockfile import settings_advisory_lock


def default_config_path() -> Path:
    base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base_dir / "ComPortZone" / "settings.json"


def _lock_path_for(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


# Windows ``os.replace`` fails with PermissionError when another process has
# the target file briefly open for reading — e.g. the GUI snapshotting
# settings.json while the CLI saves. Reads are short, so retrying with a
# small backoff resolves the race. Budget covers ~3 seconds.
_REPLACE_RETRY_ATTEMPTS = 30
_REPLACE_RETRY_DELAY = 0.1


def _replace_with_retry(src: Path, dst: Path) -> None:
    last_error: OSError | None = None
    for _ in range(_REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(_REPLACE_RETRY_DELAY)
    assert last_error is not None
    raise last_error


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.bak")

    def load_payload(self) -> dict[str, Any] | None:
        return next(self.load_payload_candidates(), None)

    def load_payload_candidates(self) -> Iterator[dict[str, Any]]:
        for load_path in (self.path, self.backup_path):
            payload = self._read_payload(load_path)
            if payload is not None:
                yield payload

    def save_payload(self, payload: dict[str, Any]) -> bool:
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(payload, indent=2, sort_keys=True)
            with settings_advisory_lock(_lock_path_for(self.path)):
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temp_file:
                    temp_file.write(serialized)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                    temp_path = Path(temp_file.name)
                self._refresh_backup()
                _replace_with_retry(temp_path, self.path)
        except OSError:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return False
        return True

    def _read_payload(self, load_path: Path) -> dict[str, Any] | None:
        if not load_path.exists():
            return None
        try:
            payload = json.loads(load_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def _refresh_backup(self) -> None:
        if self._read_payload(self.path) is None:
            return
        try:
            _replace_with_retry(self.path, self.backup_path)
        except OSError:
            self.backup_path.write_text(
                self.path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
