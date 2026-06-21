"""ControlPanel library management: CRUD over saved configs + JSON transfer.

The catalog operates on the live ``AppSettings.control_panels`` list so every
mutation is visible to the settings save path immediately (live-save,
FR-9). Import/export uses a small versioned JSON payload, mirroring the
quick-actions transfer precedent.

Requirements: docs/control_panel-view-requirements.md (FR-1..FR-4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .control_panel_models import (
    ControlPanelConfig,
    control_panel_uses_v2_features,
    control_panel_uses_v3_features,
    control_panel_uses_v4_features,
    remap_watch_ids,
)

CONTROL_PANEL_EXPORT_KEY = "comport_zone_control_panels"
CONTROL_PANEL_EXPORT_VERSION = 4
# Payloads are stamped with the lowest version that can represent them, so
# v1/v2/v3 builds keep importing exports they can fully represent (FR-39).
CONTROL_PANEL_EXPORT_V1 = 1
CONTROL_PANEL_EXPORT_V2 = 2
CONTROL_PANEL_EXPORT_V3 = 3


class ControlPanelCatalog:
    """Name-unique collection of control_panel configs.

    Mutates the list passed to the constructor in place; callers persist
    by saving settings after each operation.
    """

    def __init__(self, control_panels: list[ControlPanelConfig]) -> None:
        self._control_panels = control_panels

    def all(self) -> list[ControlPanelConfig]:
        """Configs sorted by display name (case-insensitive)."""
        return sorted(self._control_panels, key=lambda config: config.name.casefold())

    def __len__(self) -> int:
        return len(self._control_panels)

    def by_id(self, control_panel_id: str) -> ControlPanelConfig | None:
        for config in self._control_panels:
            if config.id == control_panel_id:
                return config
        return None

    def by_name(self, name: str) -> ControlPanelConfig | None:
        folded = name.casefold()
        for config in self._control_panels:
            if config.name.casefold() == folded:
                return config
        return None

    def unique_name(self, base: str, *, exclude_id: str = "") -> str:
        """``base`` if free, else "base (2)", "base (3)", ... (FR-2)."""
        base = base.strip() or "ControlPanel"
        taken = {
            config.name.casefold()
            for config in self._control_panels
            if config.id != exclude_id
        }
        if base.casefold() not in taken:
            return base
        counter = 2
        while f"{base} ({counter})".casefold() in taken:
            counter += 1
        return f"{base} ({counter})"

    def add(self, config: ControlPanelConfig) -> ControlPanelConfig:
        """Add a config, de-duplicating its name; returns it for chaining."""
        config.name = self.unique_name(config.name)
        self._control_panels.append(config)
        return config

    def duplicate(self, control_panel_id: str) -> ControlPanelConfig | None:
        """Deep-copy a config under a fresh id and "<name> Copy" name.

        Entry ids are regenerated, and follow-mode ``watch_entry_id``
        references are remapped to the new ids so a duplicated panel's
        readbacks keep pointing at the copies (not the originals).
        """
        source = self.by_id(control_panel_id)
        if source is None:
            return None
        clone = ControlPanelConfig.from_dict(source.to_dict())
        clone.id = uuid4().hex
        id_map: dict[str, str] = {}
        for entry in clone.entries:
            new_id = uuid4().hex
            id_map[entry.id] = new_id
            entry.id = new_id
        for entry in clone.entries:
            remap_watch_ids(entry, id_map)
        clone.name = self.unique_name(f"{source.name} Copy")
        clone.touch()
        self._control_panels.append(clone)
        return clone

    def rename(self, control_panel_id: str, name: str) -> bool:
        config = self.by_id(control_panel_id)
        if config is None:
            return False
        cleaned = name.strip()
        if not cleaned:
            return False
        config.name = self.unique_name(cleaned, exclude_id=control_panel_id)
        config.touch()
        return True

    def remove(self, control_panel_id: str) -> bool:
        config = self.by_id(control_panel_id)
        if config is None:
            return False
        self._control_panels.remove(config)
        return True


@dataclass(slots=True)
class ControlPanelImportResult:
    imported_count: int = 0
    renamed_count: int = 0
    replaced_count: int = 0

    def summary(self) -> str:
        parts = [f"Imported {self.imported_count} control_panel(s)"]
        if self.renamed_count:
            parts.append(f"{self.renamed_count} renamed")
        if self.replaced_count:
            parts.append(f"{self.replaced_count} replaced")
        return ", ".join(parts) + "."


def export_control_panels_payload(configs: list[ControlPanelConfig]) -> dict[str, Any]:
    """Versioned JSON-serializable payload for one or more control_panels.

    Stamped with the lowest version that can fully represent the payload,
    so older builds keep importing exports they can fully model: a
    v1-shaped collection stays at version 1; a v2-shaped collection
    stays at version 2; a v3-shaped collection stays at version 3; only
    collections that actually use a v4 widget (static text/separator)
    stamp version 4.
    """
    if any(control_panel_uses_v4_features(config) for config in configs):
        version = CONTROL_PANEL_EXPORT_VERSION
    elif any(control_panel_uses_v3_features(config) for config in configs):
        version = CONTROL_PANEL_EXPORT_V3
    elif any(control_panel_uses_v2_features(config) for config in configs):
        version = CONTROL_PANEL_EXPORT_V2
    else:
        version = CONTROL_PANEL_EXPORT_V1
    return {
        CONTROL_PANEL_EXPORT_KEY: version,
        "control_panels": [config.to_dict() for config in configs],
    }


def import_control_panels_payload(payload: Any) -> list[ControlPanelConfig]:
    """Parse a transfer payload; raises ValueError with a user-facing
    message when the file is not a control_panel export."""
    if not isinstance(payload, dict):
        raise ValueError("ControlPanel file must contain a JSON object.")
    version = payload.get(CONTROL_PANEL_EXPORT_KEY)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("Not a ComPort Zone control_panel file.")
    if version > CONTROL_PANEL_EXPORT_VERSION:
        raise ValueError(
            f"ControlPanel file version {version} is newer than this app supports "
            f"({CONTROL_PANEL_EXPORT_VERSION})."
        )
    items = payload.get("control_panels")
    if not isinstance(items, list) or not items:
        raise ValueError("ControlPanel file contains no control_panels.")
    configs: list[ControlPanelConfig] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("ControlPanel file entries must be JSON objects.")
        configs.append(ControlPanelConfig.from_dict(item))
    return configs


def merge_imported(
    catalog: ControlPanelCatalog,
    configs: list[ControlPanelConfig],
    *,
    replace_existing: bool = False,
) -> ControlPanelImportResult:
    """Merge imported configs into the catalog (FR-3).

    Id collisions always get a fresh id. A name collision either renames
    the incoming config (default) or replaces the existing one
    (``replace_existing=True``).
    """
    result = ControlPanelImportResult()
    for config in configs:
        if catalog.by_id(config.id) is not None:
            config.id = uuid4().hex
        existing = catalog.by_name(config.name)
        if existing is not None:
            if replace_existing:
                catalog.remove(existing.id)
                result.replaced_count += 1
            else:
                result.renamed_count += 1
        catalog.add(config)
        result.imported_count += 1
    return result


def read_control_panels_json(path: Path) -> list[ControlPanelConfig]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_control_panels_payload(payload)


def write_control_panels_json(path: Path, configs: list[ControlPanelConfig]) -> int:
    Path(path).write_text(
        json.dumps(export_control_panels_payload(configs), indent=2),
        encoding="utf-8",
    )
    return len(configs)
