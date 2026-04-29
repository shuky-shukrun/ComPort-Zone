from __future__ import annotations

import json
from pathlib import Path

from .models import AppSettings
from .storage import SettingsStore, default_config_path


class SettingsService:
    def __init__(self, store: SettingsStore | None = None) -> None:
        self.store = store or SettingsStore(default_config_path())

    def load(self) -> AppSettings:
        return self.store.load()

    def save(self, settings: AppSettings) -> bool:
        return self.store.save(settings)

    def load_from_json(self, path: Path) -> AppSettings:
        return AppSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def export_to_json(self, settings: AppSettings, path: Path) -> None:
        path.write_text(
            json.dumps(settings.to_app_settings_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def preserve_quick_actions(
        self,
        imported: AppSettings,
        current: AppSettings,
    ) -> AppSettings:
        imported.quick_snippets = list(current.quick_snippets)
        imported.quick_commands = list(current.quick_commands)
        imported.quick_files = list(current.quick_files)
        imported.quick_command_sort_mode = current.quick_command_sort_mode
        imported.quick_command_hidden_groups = list(current.quick_command_hidden_groups)
        imported.quick_file_sort_mode = current.quick_file_sort_mode
        return imported
