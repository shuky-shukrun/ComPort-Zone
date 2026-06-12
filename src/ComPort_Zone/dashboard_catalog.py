"""Dashboard library management: CRUD over saved configs + JSON transfer.

The catalog operates on the live ``AppSettings.dashboards`` list so every
mutation is visible to the settings save path immediately (live-save,
FR-9). Import/export uses a small versioned JSON payload, mirroring the
quick-actions transfer precedent.

Requirements: docs/dashboard-view-requirements.md (FR-1..FR-4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .dashboard_models import DashboardConfig, dashboard_uses_v2_features

DASHBOARD_EXPORT_KEY = "comport_zone_dashboards"
DASHBOARD_EXPORT_VERSION = 2
# Payloads are stamped with the lowest version that can represent them, so
# v1 builds keep importing exports of v1-shaped dashboards (FR-39).
DASHBOARD_EXPORT_V1 = 1


class DashboardCatalog:
    """Name-unique collection of dashboard configs.

    Mutates the list passed to the constructor in place; callers persist
    by saving settings after each operation.
    """

    def __init__(self, dashboards: list[DashboardConfig]) -> None:
        self._dashboards = dashboards

    def all(self) -> list[DashboardConfig]:
        """Configs sorted by display name (case-insensitive)."""
        return sorted(self._dashboards, key=lambda config: config.name.casefold())

    def __len__(self) -> int:
        return len(self._dashboards)

    def by_id(self, dashboard_id: str) -> DashboardConfig | None:
        for config in self._dashboards:
            if config.id == dashboard_id:
                return config
        return None

    def by_name(self, name: str) -> DashboardConfig | None:
        folded = name.casefold()
        for config in self._dashboards:
            if config.name.casefold() == folded:
                return config
        return None

    def unique_name(self, base: str, *, exclude_id: str = "") -> str:
        """``base`` if free, else "base (2)", "base (3)", ... (FR-2)."""
        base = base.strip() or "Dashboard"
        taken = {
            config.name.casefold()
            for config in self._dashboards
            if config.id != exclude_id
        }
        if base.casefold() not in taken:
            return base
        counter = 2
        while f"{base} ({counter})".casefold() in taken:
            counter += 1
        return f"{base} ({counter})"

    def add(self, config: DashboardConfig) -> DashboardConfig:
        """Add a config, de-duplicating its name; returns it for chaining."""
        config.name = self.unique_name(config.name)
        self._dashboards.append(config)
        return config

    def duplicate(self, dashboard_id: str) -> DashboardConfig | None:
        """Deep-copy a config under a fresh id and "<name> Copy" name."""
        source = self.by_id(dashboard_id)
        if source is None:
            return None
        clone = DashboardConfig.from_dict(source.to_dict())
        clone.id = uuid4().hex
        for entry in clone.entries:
            entry.id = uuid4().hex
        clone.name = self.unique_name(f"{source.name} Copy")
        clone.touch()
        self._dashboards.append(clone)
        return clone

    def rename(self, dashboard_id: str, name: str) -> bool:
        config = self.by_id(dashboard_id)
        if config is None:
            return False
        cleaned = name.strip()
        if not cleaned:
            return False
        config.name = self.unique_name(cleaned, exclude_id=dashboard_id)
        config.touch()
        return True

    def remove(self, dashboard_id: str) -> bool:
        config = self.by_id(dashboard_id)
        if config is None:
            return False
        self._dashboards.remove(config)
        return True


@dataclass(slots=True)
class DashboardImportResult:
    imported_count: int = 0
    renamed_count: int = 0
    replaced_count: int = 0

    def summary(self) -> str:
        parts = [f"Imported {self.imported_count} dashboard(s)"]
        if self.renamed_count:
            parts.append(f"{self.renamed_count} renamed")
        if self.replaced_count:
            parts.append(f"{self.replaced_count} replaced")
        return ", ".join(parts) + "."


def export_dashboards_payload(configs: list[DashboardConfig]) -> dict[str, Any]:
    """Versioned JSON-serializable payload for one or more dashboards."""
    version = (
        DASHBOARD_EXPORT_VERSION
        if any(dashboard_uses_v2_features(config) for config in configs)
        else DASHBOARD_EXPORT_V1
    )
    return {
        DASHBOARD_EXPORT_KEY: version,
        "dashboards": [config.to_dict() for config in configs],
    }


def import_dashboards_payload(payload: Any) -> list[DashboardConfig]:
    """Parse a transfer payload; raises ValueError with a user-facing
    message when the file is not a dashboard export."""
    if not isinstance(payload, dict):
        raise ValueError("Dashboard file must contain a JSON object.")
    version = payload.get(DASHBOARD_EXPORT_KEY)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("Not a ComPort Zone dashboard file.")
    if version > DASHBOARD_EXPORT_VERSION:
        raise ValueError(
            f"Dashboard file version {version} is newer than this app supports "
            f"({DASHBOARD_EXPORT_VERSION})."
        )
    items = payload.get("dashboards")
    if not isinstance(items, list) or not items:
        raise ValueError("Dashboard file contains no dashboards.")
    configs: list[DashboardConfig] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Dashboard file entries must be JSON objects.")
        configs.append(DashboardConfig.from_dict(item))
    return configs


def merge_imported(
    catalog: DashboardCatalog,
    configs: list[DashboardConfig],
    *,
    replace_existing: bool = False,
) -> DashboardImportResult:
    """Merge imported configs into the catalog (FR-3).

    Id collisions always get a fresh id. A name collision either renames
    the incoming config (default) or replaces the existing one
    (``replace_existing=True``).
    """
    result = DashboardImportResult()
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


def read_dashboards_json(path: Path) -> list[DashboardConfig]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_dashboards_payload(payload)


def write_dashboards_json(path: Path, configs: list[DashboardConfig]) -> int:
    Path(path).write_text(
        json.dumps(export_dashboards_payload(configs), indent=2),
        encoding="utf-8",
    )
    return len(configs)
