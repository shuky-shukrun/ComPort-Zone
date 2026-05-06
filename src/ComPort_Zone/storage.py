from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
import tempfile
from typing import Any


def default_config_path() -> Path:
    base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base_dir / "ComPortZone" / "settings.json"


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
            os.replace(temp_path, self.path)
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
            os.replace(self.path, self.backup_path)
        except OSError:
            self.backup_path.write_text(
                self.path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
