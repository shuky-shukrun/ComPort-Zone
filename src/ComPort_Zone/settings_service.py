from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AppSettings, SETTINGS_SCHEMA_VERSION
from .storage import SettingsStore, default_config_path


class SettingsService:
    def __init__(self, store: SettingsStore | None = None) -> None:
        self.store = store or SettingsStore(default_config_path())

    def load(self) -> AppSettings:
        for payload in self.store.load_payload_candidates():
            try:
                return self.settings_from_payload(payload)
            except (TypeError, ValueError):
                continue
        return AppSettings()

    def save(self, settings: AppSettings) -> bool:
        return self.store.save_payload(self.payload_from_settings(settings))

    def load_from_json(self, path: Path) -> AppSettings:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("App settings file must contain a JSON object.")
        return self.settings_from_payload(payload)

    def export_to_json(self, settings: AppSettings, path: Path) -> None:
        path.write_text(
            json.dumps(self.export_payload_from_settings(settings), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def payload_from_settings(self, settings: AppSettings) -> dict[str, Any]:
        return settings.to_dict()

    def export_payload_from_settings(self, settings: AppSettings) -> dict[str, Any]:
        return settings.to_app_settings_dict()

    def settings_from_payload(self, payload: dict[str, Any]) -> AppSettings:
        schema_version = payload.get("schema_version")
        if schema_version != SETTINGS_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported app settings schema {schema_version!r}; "
                f"expected {SETTINGS_SCHEMA_VERSION}."
            )
        return AppSettings.from_dict(payload)

    def preserve_quick_actions(
        self,
        imported: AppSettings,
        current: AppSettings,
    ) -> AppSettings:
        imported.quick_commands = list(current.quick_commands)
        imported.quick_files = list(current.quick_files)
        imported.quick_command_sort_mode = current.quick_command_sort_mode
        imported.quick_command_hidden_groups = list(current.quick_command_hidden_groups)
        imported.quick_file_sort_mode = current.quick_file_sort_mode
        return imported
