from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import (
    LINE_ENDINGS,
    QUICK_COMMAND_SORT_MODES,
    QUICK_FILE_SORT_MODES,
    QuickCommand,
    QuickFile,
)

SEND_MODES = ("Text", "Hex Bytes")
QUICK_COMMAND_CSV_FIELDS = (
    "label",
    "command",
    "description",
    "send_mode",
    "group",
    "line_ending_override",
)
QUICK_FILE_CSV_FIELDS = ("label", "path")


def quick_group_name(group: str) -> str:
    return group.strip() or "General"


def quick_file_display_text(quick_file: QuickFile) -> str:
    label = quick_file.display_label()
    if label:
        return label
    return Path(quick_file.path).name or quick_file.path


def quick_command_csv_row(command: QuickCommand) -> dict[str, str]:
    return {
        "label": command.label,
        "command": command.command,
        "description": command.description,
        "send_mode": command.send_mode,
        "group": quick_group_name(command.group),
        "line_ending_override": command.line_ending_override,
    }


def quick_command_from_csv_row(row: dict[str, str]) -> QuickCommand | None:
    command_text = str(row.get("command") or row.get("text") or "").strip()
    if not command_text:
        return None
    send_mode = str(row.get("send_mode") or row.get("mode") or "Text").strip() or "Text"
    if send_mode not in SEND_MODES:
        send_mode = "Text"
    line_ending = str(row.get("line_ending_override") or row.get("line_ending") or "").strip()
    if line_ending and line_ending not in LINE_ENDINGS:
        line_ending = ""
    return QuickCommand(
        label=str(row.get("label") or row.get("title") or "").strip() or command_text,
        command=command_text,
        description=str(row.get("description") or row.get("notes") or "").strip(),
        send_mode=send_mode,
        group=quick_group_name(str(row.get("group", ""))),
        line_ending_override=line_ending,
    )


def quick_file_csv_row(quick_file: QuickFile) -> dict[str, str]:
    return {
        "label": quick_file.label,
        "path": quick_file.path,
    }


def quick_file_from_csv_row(row: dict[str, str]) -> QuickFile | None:
    path = str(
        row.get("path")
        or row.get("file")
        or row.get("command_file")
        or row.get("script")
        or ""
    ).strip()
    if not path:
        return None
    label = str(row.get("label") or row.get("title") or "").strip()
    return QuickFile(label=label or Path(path).name, path=path)


@dataclass(slots=True)
class QuickCommandImportOptions:
    replace_existing: bool = False
    skip_duplicates: bool = True


@dataclass(slots=True)
class QuickCommandImportResult:
    imported_count: int = 0
    skipped_count: int = 0

    def status_suffix(self) -> str:
        if self.skipped_count:
            return f", skipped {self.skipped_count} duplicate(s)"
        return ""


@dataclass(slots=True)
class QuickFileImportOptions:
    replace_existing: bool = False
    skip_duplicates: bool = True


@dataclass(slots=True)
class QuickFileImportResult:
    imported_count: int = 0
    skipped_count: int = 0

    def status_suffix(self) -> str:
        if self.skipped_count:
            return f", skipped {self.skipped_count} duplicate(s)"
        return ""


def quick_command_duplicate_key(command: QuickCommand) -> tuple[str, str, str, str]:
    return (
        quick_group_name(command.group).casefold(),
        command.display_label().strip().casefold(),
        command.command.strip(),
        command.send_mode.strip().casefold(),
    )


def quick_file_duplicate_key(quick_file: QuickFile) -> str:
    return quick_file.path.strip().replace("\\", "/").casefold()


def clone_quick_command(command: QuickCommand, *, preserve_id: bool) -> QuickCommand:
    fields = {
        "label": command.label,
        "command": command.command,
        "description": command.description,
        "send_mode": command.send_mode,
        "group": command.group,
        "line_ending_override": command.line_ending_override,
        "created_at": command.created_at,
        "updated_at": command.updated_at,
    }
    if preserve_id:
        fields["id"] = command.id
    return QuickCommand(**fields)


def clone_quick_file(quick_file: QuickFile, *, preserve_id: bool) -> QuickFile:
    fields = {
        "label": quick_file.label,
        "path": quick_file.path,
        "created_at": quick_file.created_at,
        "updated_at": quick_file.updated_at,
    }
    if preserve_id:
        fields["id"] = quick_file.id
    return QuickFile(**fields)


def merge_quick_commands(
    existing: list[QuickCommand],
    imported: list[QuickCommand],
    options: QuickCommandImportOptions,
) -> tuple[list[QuickCommand], QuickCommandImportResult]:
    merged = [] if options.replace_existing else [
        clone_quick_command(command, preserve_id=True)
        for command in existing
    ]
    seen = {quick_command_duplicate_key(command) for command in merged}
    result = QuickCommandImportResult()
    for command in imported:
        if not command.command.strip():
            continue
        key = quick_command_duplicate_key(command)
        if options.skip_duplicates and key in seen:
            result.skipped_count += 1
            continue
        merged.append(clone_quick_command(command, preserve_id=options.replace_existing))
        seen.add(key)
        result.imported_count += 1
    return merged, result


def merge_quick_files(
    existing: list[QuickFile],
    imported: list[QuickFile],
    options: QuickFileImportOptions,
) -> tuple[list[QuickFile], QuickFileImportResult]:
    merged = [] if options.replace_existing else [
        clone_quick_file(quick_file, preserve_id=True)
        for quick_file in existing
    ]
    seen = {quick_file_duplicate_key(quick_file) for quick_file in merged}
    result = QuickFileImportResult()
    for quick_file in imported:
        if not quick_file.path.strip():
            continue
        key = quick_file_duplicate_key(quick_file)
        if options.skip_duplicates and key in seen:
            result.skipped_count += 1
            continue
        merged.append(clone_quick_file(quick_file, preserve_id=options.replace_existing))
        seen.add(key)
        result.imported_count += 1
    return merged, result


class QuickActionLibrary:
    def __init__(
        self,
        *,
        quick_commands: list[QuickCommand] | None = None,
        quick_files: list[QuickFile] | None = None,
        command_sort_mode: str = "Custom",
        command_hidden_groups: list[str] | None = None,
        file_sort_mode: str = "Custom",
        favorite_command_order: list[str] | None = None,
        favorite_file_order: list[str] | None = None,
        favorite_command_sort_mode: str = "Custom",
        favorite_file_sort_mode: str = "Custom",
    ) -> None:
        self.quick_commands = list(quick_commands or [])
        self.quick_files = list(quick_files or [])
        self.command_sort_mode = (
            command_sort_mode
            if command_sort_mode in QUICK_COMMAND_SORT_MODES
            else "Custom"
        )
        self.command_hidden_groups = list(command_hidden_groups or [])
        self.file_sort_mode = file_sort_mode if file_sort_mode in QUICK_FILE_SORT_MODES else "Custom"
        # Favourites keep their own curated order + sort mode (the "independent
        # order" the user picked) — separate from the full Saved lists above.
        self.favorite_command_order = list(favorite_command_order or [])
        self.favorite_file_order = list(favorite_file_order or [])
        self.favorite_command_sort_mode = (
            favorite_command_sort_mode
            if favorite_command_sort_mode in QUICK_COMMAND_SORT_MODES
            else "Custom"
        )
        self.favorite_file_sort_mode = (
            favorite_file_sort_mode if favorite_file_sort_mode in QUICK_FILE_SORT_MODES else "Custom"
        )

    def command_by_id(self, command_id: str) -> QuickCommand | None:
        return next((command for command in self.quick_commands if command.id == command_id), None)

    def file_by_id(self, quick_file_id: str) -> QuickFile | None:
        return next((quick_file for quick_file in self.quick_files if quick_file.id == quick_file_id), None)

    def command_group_names(self) -> list[str]:
        groups: list[str] = []
        seen: set[str] = set()
        for command in self.quick_commands:
            group = quick_group_name(command.group)
            key = group.casefold()
            if key not in seen:
                groups.append(group)
                seen.add(key)
        return sorted(groups, key=str.casefold)

    @staticmethod
    def _sort_commands_with(commands: list[QuickCommand], mode: str) -> list[QuickCommand]:
        if mode == "Title":
            return sorted(
                commands,
                key=lambda command: (
                    command.display_label().casefold(),
                    quick_group_name(command.group).casefold(),
                    command.command.casefold(),
                ),
            )
        if mode == "Group":
            return sorted(
                commands,
                key=lambda command: (
                    quick_group_name(command.group).casefold(),
                    command.display_label().casefold(),
                    command.command.casefold(),
                ),
            )
        return list(commands)

    def _sort_commands(self, commands: list[QuickCommand]) -> list[QuickCommand]:
        return self._sort_commands_with(commands, self.command_sort_mode)

    @staticmethod
    def _apply_custom_order(items: list, order: list[str]) -> list:
        """Arrange ``items`` by the id sequence in ``order``; any ids not present
        keep their original relative order, appended at the end."""
        by_id = {item.id: item for item in items}
        seen: set[str] = set()
        result = []
        for item_id in order:
            item = by_id.get(item_id)
            if item is not None and item_id not in seen:
                result.append(item)
                seen.add(item_id)
        result.extend(item for item in items if item.id not in seen)
        return result

    @staticmethod
    def _synced_order(order_seed: list[str], member_ids: list[str]) -> list[str]:
        """An id order limited to current members: honour ``order_seed`` first,
        then append any members it is missing (in their natural order)."""
        members = set(member_ids)
        result = [item_id for item_id in order_seed if item_id in members]
        seen = set(result)
        result.extend(item_id for item_id in member_ids if item_id not in seen)
        return result

    def visible_commands(self) -> list[QuickCommand]:
        hidden = {group.casefold() for group in self.command_hidden_groups}
        return self._sort_commands(
            [
                command
                for command in self.quick_commands
                if quick_group_name(command.group).casefold() not in hidden
            ]
        )

    def favorite_commands(self) -> list[QuickCommand]:
        """Favourited saved commands (subset), in the favourites' own order/sort.

        Hidden groups apply here too, so the Favorites group control can fold a
        group away just like Saved Commands."""
        hidden = {group.casefold() for group in self.command_hidden_groups}
        favorites = [
            command
            for command in self.quick_commands
            if command.favorite and quick_group_name(command.group).casefold() not in hidden
        ]
        if self.favorite_command_sort_mode == "Custom":
            return self._apply_custom_order(favorites, self.favorite_command_order)
        return self._sort_commands_with(favorites, self.favorite_command_sort_mode)

    def sync_favorite_command_order(self) -> None:
        self.favorite_command_order = self._synced_order(
            self.favorite_command_order,
            [command.id for command in self.quick_commands if command.favorite],
        )

    def reorder_favorite_commands(self, command_ids: list[str]) -> bool:
        member_ids = [command.id for command in self.quick_commands if command.favorite]
        new_order = self._synced_order(command_ids, member_ids)
        changed = new_order != self.favorite_command_order or self.favorite_command_sort_mode != "Custom"
        self.favorite_command_order = new_order
        self.favorite_command_sort_mode = "Custom"
        return changed

    def set_favorite_command_sort_mode(self, mode: str) -> None:
        self.favorite_command_sort_mode = mode if mode in QUICK_COMMAND_SORT_MODES else "Custom"

    def set_favorite_file_sort_mode(self, mode: str) -> None:
        self.favorite_file_sort_mode = mode if mode in QUICK_FILE_SORT_MODES else "Custom"

    def command_by_text(self, text: str) -> QuickCommand | None:
        """First saved command whose command text matches (used to de-duplicate
        when saving/favouriting from history)."""
        text = text.strip()
        if not text:
            return None
        return next((command for command in self.quick_commands if command.command.strip() == text), None)

    @staticmethod
    def _sort_files_with(quick_files: list[QuickFile], mode: str) -> list[QuickFile]:
        if mode == "Title":
            return sorted(
                quick_files,
                key=lambda quick_file: (
                    quick_file_display_text(quick_file).casefold(),
                    quick_file.path.casefold(),
                ),
            )
        if mode == "Path":
            return sorted(
                quick_files,
                key=lambda quick_file: (
                    quick_file.path.casefold(),
                    quick_file_display_text(quick_file).casefold(),
                ),
            )
        return list(quick_files)

    def visible_files(self) -> list[QuickFile]:
        return self._sort_files_with(list(self.quick_files), self.file_sort_mode)

    def favorite_files(self) -> list[QuickFile]:
        """Favourited quick files (subset), in the favourites' own order/sort."""
        favorites = [quick_file for quick_file in self.quick_files if quick_file.favorite]
        if self.favorite_file_sort_mode == "Custom":
            return self._apply_custom_order(favorites, self.favorite_file_order)
        return self._sort_files_with(favorites, self.favorite_file_sort_mode)

    def sync_favorite_file_order(self) -> None:
        self.favorite_file_order = self._synced_order(
            self.favorite_file_order,
            [quick_file.id for quick_file in self.quick_files if quick_file.favorite],
        )

    def reorder_favorite_files(self, quick_file_ids: list[str]) -> bool:
        member_ids = [quick_file.id for quick_file in self.quick_files if quick_file.favorite]
        new_order = self._synced_order(quick_file_ids, member_ids)
        changed = new_order != self.favorite_file_order or self.favorite_file_sort_mode != "Custom"
        self.favorite_file_order = new_order
        self.favorite_file_sort_mode = "Custom"
        return changed

    def can_manually_reorder_commands(self) -> bool:
        groups = {group.casefold() for group in self.command_group_names()}
        hidden_active = any(
            group.casefold() in groups
            for group in self.command_hidden_groups
        )
        return self.command_sort_mode == "Custom" and not hidden_active

    def set_command_sort_mode(self, mode: str) -> None:
        self.command_sort_mode = mode if mode in QUICK_COMMAND_SORT_MODES else "Custom"

    def set_file_sort_mode(self, mode: str) -> None:
        self.file_sort_mode = mode if mode in QUICK_FILE_SORT_MODES else "Custom"

    def set_command_group_visible(self, group: str, visible: bool) -> None:
        group = quick_group_name(group)
        hidden = [
            hidden_group
            for hidden_group in self.command_hidden_groups
            if hidden_group.casefold() != group.casefold()
        ]
        if not visible:
            hidden.append(group)
        self.command_hidden_groups = hidden

    def reorder_commands(self, command_ids: list[str]) -> bool:
        existing_ids = [command.id for command in self.quick_commands]
        if command_ids == existing_ids:
            return False
        commands_by_id = {command.id: command for command in self.quick_commands}
        seen: set[str] = set()
        reordered: list[QuickCommand] = []
        for command_id in command_ids:
            command = commands_by_id.get(command_id)
            if command and command_id not in seen:
                reordered.append(command)
                seen.add(command_id)
        reordered.extend(command for command in self.quick_commands if command.id not in seen)
        if [command.id for command in reordered] == existing_ids:
            return False
        self.quick_commands = reordered
        return True

    def reorder_files(self, quick_file_ids: list[str], *, force_custom: bool = False) -> bool:
        existing_ids = [quick_file.id for quick_file in self.quick_files]
        mode_changed = force_custom and self.file_sort_mode != "Custom"
        if quick_file_ids == existing_ids and not mode_changed:
            return False
        quick_files_by_id = {quick_file.id: quick_file for quick_file in self.quick_files}
        seen: set[str] = set()
        reordered: list[QuickFile] = []
        for quick_file_id in quick_file_ids:
            quick_file = quick_files_by_id.get(quick_file_id)
            if quick_file and quick_file_id not in seen:
                reordered.append(quick_file)
                seen.add(quick_file_id)
        reordered.extend(quick_file for quick_file in self.quick_files if quick_file.id not in seen)
        order_changed = [quick_file.id for quick_file in reordered] != existing_ids
        if force_custom:
            self.file_sort_mode = "Custom"
        if order_changed:
            self.quick_files = reordered
        return order_changed or mode_changed

    def import_commands_from_csv(
        self,
        path: Path,
        *,
        options: QuickCommandImportOptions | None = None,
    ) -> QuickCommandImportResult:
        options = options or QuickCommandImportOptions()
        imported = read_quick_commands_csv(path)
        if not imported:
            return QuickCommandImportResult()
        self.quick_commands, result = merge_quick_commands(self.quick_commands, imported, options)
        return result

    def export_commands_to_csv(self, path: Path) -> int:
        write_quick_commands_csv(path, self.quick_commands)
        return len(self.quick_commands)

    def import_files_from_csv(
        self,
        path: Path,
        *,
        options: QuickFileImportOptions | None = None,
    ) -> QuickFileImportResult:
        options = options or QuickFileImportOptions()
        imported = read_quick_files_csv(path)
        if not imported:
            return QuickFileImportResult()
        self.quick_files, result = merge_quick_files(self.quick_files, imported, options)
        return result

    def export_files_to_csv(self, path: Path) -> int:
        write_quick_files_csv(path, self.quick_files)
        return len(self.quick_files)


def read_quick_commands_csv(path: Path) -> list[QuickCommand]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty.")
        normalized_names = {name.strip().casefold() for name in reader.fieldnames if name}
        if "command" not in normalized_names and "text" not in normalized_names:
            raise ValueError("CSV must include a 'command' column.")
        imported: list[QuickCommand] = []
        for row in reader:
            normalized_row = {
                str(key).strip().casefold(): str(value or "")
                for key, value in row.items()
                if key is not None
            }
            quick_command = quick_command_from_csv_row(normalized_row)
            if quick_command:
                imported.append(quick_command)
        return imported


def write_quick_commands_csv(path: Path, commands: list[QuickCommand]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=QUICK_COMMAND_CSV_FIELDS)
        writer.writeheader()
        for command in commands:
            writer.writerow(quick_command_csv_row(command))


def read_quick_files_csv(path: Path) -> list[QuickFile]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty.")
        normalized_names = {name.strip().casefold() for name in reader.fieldnames if name}
        if not normalized_names.intersection({"path", "file", "command_file", "script"}):
            raise ValueError("CSV must include a 'path' column.")
        imported: list[QuickFile] = []
        for row in reader:
            normalized_row = {
                str(key).strip().casefold(): str(value or "")
                for key, value in row.items()
                if key is not None
            }
            quick_file = quick_file_from_csv_row(normalized_row)
            if quick_file:
                imported.append(quick_file)
        return imported


def write_quick_files_csv(path: Path, quick_files: list[QuickFile]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=QUICK_FILE_CSV_FIELDS)
        writer.writeheader()
        for quick_file in quick_files:
            writer.writerow(quick_file_csv_row(quick_file))
