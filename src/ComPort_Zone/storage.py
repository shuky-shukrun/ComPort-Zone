from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_config_path() -> Path:
    base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base_dir / "ComPortZone" / "settings.json"

class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()

    def load_payload(self) -> dict[str, Any] | None:
        load_path = self.path
        if not load_path.exists():
            return None
        try:
            payload = json.loads(load_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def save_payload(self, payload: dict[str, Any]) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            return False
        return True
