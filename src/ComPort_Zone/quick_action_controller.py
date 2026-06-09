from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QWidget

from .models import QUICK_COMMAND_SORT_MODES, QUICK_FILE_SORT_MODES, QuickCommand, QuickFile, utc_now_iso
from .quick_actions import (
    QuickActionLibrary,
    QuickCommandImportOptions,
    QuickCommandImportResult,
    QuickFileImportOptions,
    QuickFileImportResult,
)
from .ui.dialogs import QuickCommandDialog, QuickCommandImportDialog, QuickFileDialog


def _short_label(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


class QuickActionController:
    def __init__(
        self,
        *,
        parent: QWidget,
        library_supplier: Callable[[], QuickActionLibrary],
        refresh_from_settings: Callable[[], None],
        sync_to_settings: Callable[[], None],
        refresh_commands: Callable[[str | None], None],
        refresh_files: Callable[[str | None], None],
        save_settings: Callable[[], None],
        set_status: Callable[[str], None],
        confirm_bulk_delete: Callable[[str, str], bool],
    ) -> None:
        self.parent = parent
        self._library_supplier = library_supplier
        self._refresh_from_settings = refresh_from_settings
        self._sync_to_settings = sync_to_settings
        self._refresh_commands = refresh_commands
        self._refresh_files = refresh_files
        self._save_settings = save_settings
        self._set_status = set_status
        self._confirm_bulk_delete = confirm_bulk_delete

    @property
    def library(self) -> QuickActionLibrary:
        return self._library_supplier()

    def quick_commands_snapshot(self) -> list[QuickCommand]:
        self._refresh_from_settings()
        return list(self.library.quick_commands)

    def visible_quick_commands_snapshot(self) -> list[QuickCommand]:
        self._refresh_from_settings()
        return self.library.visible_commands()

    def quick_files_snapshot(self) -> list[QuickFile]:
        self._refresh_from_settings()
        return list(self.library.quick_files)

    def visible_quick_files_snapshot(self) -> list[QuickFile]:
        self._refresh_from_settings()
        return self.library.visible_files()

    def quick_command_hidden_groups_snapshot(self) -> list[str]:
        self._refresh_from_settings()
        return list(self.library.command_hidden_groups)

    def quick_command_sort_mode_snapshot(self) -> str:
        self._refresh_from_settings()
        return self.library.command_sort_mode

    def quick_file_sort_mode_snapshot(self) -> str:
        self._refresh_from_settings()
        return self.library.file_sort_mode

    def favorite_command_sort_mode_snapshot(self) -> str:
        self._refresh_from_settings()
        return self.library.favorite_command_sort_mode

    def favorite_file_sort_mode_snapshot(self) -> str:
        self._refresh_from_settings()
        return self.library.favorite_file_sort_mode

    def quick_command_by_id(self, command_id: str) -> QuickCommand | None:
        self._refresh_from_settings()
        return self.library.command_by_id(command_id)

    def quick_file_by_id(self, quick_file_id: str) -> QuickFile | None:
        self._refresh_from_settings()
        return self.library.file_by_id(quick_file_id)

    def quick_command_group_names(self) -> list[str]:
        self._refresh_from_settings()
        return self.library.command_group_names()

    def set_quick_command_sort_mode(self, mode: str) -> None:
        self._refresh_from_settings()
        if mode not in QUICK_COMMAND_SORT_MODES:
            mode = "Custom"
        if self.library.command_sort_mode == mode:
            return
        self.library.set_command_sort_mode(mode)
        self._commit_commands()

    def set_quick_file_sort_mode(self, mode: str) -> None:
        self._refresh_from_settings()
        if mode not in QUICK_FILE_SORT_MODES:
            mode = "Custom"
        if self.library.file_sort_mode == mode:
            return
        self.library.set_file_sort_mode(mode)
        self._commit_files()

    def set_favorite_command_sort_mode(self, mode: str) -> None:
        self._refresh_from_settings()
        if mode not in QUICK_COMMAND_SORT_MODES:
            mode = "Custom"
        if self.library.favorite_command_sort_mode == mode:
            return
        self.library.set_favorite_command_sort_mode(mode)
        self._commit_commands()

    def set_favorite_file_sort_mode(self, mode: str) -> None:
        self._refresh_from_settings()
        if mode not in QUICK_FILE_SORT_MODES:
            mode = "Custom"
        if self.library.favorite_file_sort_mode == mode:
            return
        self.library.set_favorite_file_sort_mode(mode)
        self._commit_files()

    def set_quick_command_group_visible(self, group: str, visible: bool) -> None:
        self._refresh_from_settings()
        before = [item.casefold() for item in self.library.command_hidden_groups]
        self.library.set_command_group_visible(group, visible)
        after = [item.casefold() for item in self.library.command_hidden_groups]
        if before == after:
            return
        self._commit_commands()

    def show_all_quick_command_groups(self) -> None:
        self._refresh_from_settings()
        if not self.library.command_hidden_groups:
            return
        self.library.command_hidden_groups = []
        self._commit_commands()

    def hide_all_quick_command_groups(self) -> None:
        self._refresh_from_settings()
        groups = self.library.command_group_names()
        if [group.casefold() for group in groups] == [
            group.casefold() for group in self.library.command_hidden_groups
        ]:
            return
        self.library.command_hidden_groups = groups
        self._commit_commands()

    def add_quick_command(self, command: QuickCommand | None = None) -> None:
        self._refresh_from_settings()
        if command is None or isinstance(command, bool):
            dialog = QuickCommandDialog(parent=self.parent)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            command = dialog.quick_command()
        if not command.command:
            return
        self.library.quick_commands.append(command)
        self._commit_commands()

    def favorite_quick_commands_snapshot(self) -> list[QuickCommand]:
        self._refresh_from_settings()
        return self.library.favorite_commands()

    def favorite_quick_files_snapshot(self) -> list[QuickFile]:
        self._refresh_from_settings()
        return self.library.favorite_files()

    def set_quick_command_favorite(self, command_id: str, favorite: bool) -> None:
        self._refresh_from_settings()
        command = self.library.command_by_id(command_id)
        if command is None or command.favorite == bool(favorite):
            return
        command.favorite = bool(favorite)
        command.updated_at = utc_now_iso()
        self._commit_commands(command_id)

    def set_quick_file_favorite(self, quick_file_id: str, favorite: bool) -> None:
        self._refresh_from_settings()
        quick_file = self.library.file_by_id(quick_file_id)
        if quick_file is None or quick_file.favorite == bool(favorite):
            return
        quick_file.favorite = bool(favorite)
        quick_file.updated_at = utc_now_iso()
        self._commit_files(quick_file_id)

    def add_command_from_text(self, text: str, *, favorite: bool = False) -> QuickCommand | None:
        """Save a raw command (from history). De-duplicates by command text: an
        existing match is reused (only flipped to favourite when needed)."""
        self._refresh_from_settings()
        text = text.strip()
        if not text:
            return None
        existing = self.library.command_by_text(text)
        if existing is not None:
            if favorite and not existing.favorite:
                existing.favorite = True
                existing.updated_at = utc_now_iso()
                self._commit_commands(existing.id)
            else:
                self._set_status(f"Already in saved commands: {_short_label(existing.display_label(), 32)}")
            return existing
        command = QuickCommand(label=text, command=text, favorite=favorite)
        self.library.quick_commands.append(command)
        self._commit_commands(command.id)
        self._set_status(
            f"{'Favourited' if favorite else 'Saved'} command: {_short_label(text, 32)}"
        )
        return command

    def edit_quick_command(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        dialog = QuickCommandDialog(command, self.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.quick_command()
        for index, existing in enumerate(self.library.quick_commands):
            if existing.id == updated.id:
                self.library.quick_commands[index] = updated
                break
        self._commit_commands()

    def duplicate_quick_command(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        now = utc_now_iso()
        duplicate = QuickCommand(
            label=f"{command.display_label()} Copy",
            command=command.command,
            description=command.description,
            send_mode=command.send_mode,
            group=command.group,
            line_ending_override=command.line_ending_override,
            created_at=now,
            updated_at=now,
        )
        source_index = next(
            (index for index, existing in enumerate(self.library.quick_commands) if existing.id == command_id),
            len(self.library.quick_commands) - 1,
        )
        self.library.quick_commands.insert(source_index + 1, duplicate)
        self._commit_commands(duplicate.id)

    def delete_quick_command(self, command_id: str) -> None:
        self._refresh_from_settings()
        if not command_id:
            return
        self.library.quick_commands = [
            command
            for command in self.library.quick_commands
            if command.id != command_id
        ]
        self._commit_commands()

    def copy_quick_command_text(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        QApplication.clipboard().setText(command.command)
        self._set_status(f"Copied quick command: {_short_label(command.display_label(), 32)}")

    def add_quick_file(self, quick_file: QuickFile | None = None, *, prompt: bool | None = None) -> None:
        self._refresh_from_settings()
        # ``prompt`` decides whether the editor dialog opens: by default it does when
        # no ready-made QuickFile is supplied. The host's "+" button picks a file
        # first and passes it with ``prompt=True`` to seed the dialog (label = the
        # file name, path = the chosen path), both still editable.
        if prompt is None:
            prompt = not isinstance(quick_file, QuickFile)
        if prompt:
            seed = quick_file if isinstance(quick_file, QuickFile) else None
            dialog = QuickFileDialog(seed, parent=self.parent)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            quick_file = dialog.quick_file()
        if not isinstance(quick_file, QuickFile) or not quick_file.path:
            return
        self.library.quick_files.append(quick_file)
        self._commit_files(quick_file.id)

    def edit_quick_file(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        dialog = QuickFileDialog(quick_file, self.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.quick_file()
        if not updated.path:
            return
        for index, existing in enumerate(self.library.quick_files):
            if existing.id == updated.id:
                self.library.quick_files[index] = updated
                break
        self._commit_files(updated.id)

    def delete_quick_file(self, quick_file_id: str) -> None:
        self._refresh_from_settings()
        if not quick_file_id:
            return
        self.library.quick_files = [
            quick_file
            for quick_file in self.library.quick_files
            if quick_file.id != quick_file_id
        ]
        self._commit_files()

    def import_quick_commands_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.parent,
            "Import Quick Commands",
            str(Path.cwd()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        dialog = QuickCommandImportDialog(
            title="Import Quick Commands",
            message="Choose whether this CSV adds to your current quick commands or replaces them.",
            default_replace=False,
            default_skip_duplicates=True,
            parent=self.parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = self.import_quick_commands_from_csv(Path(path), options=dialog.options())
        except (OSError, csv.Error, ValueError) as exc:
            QMessageBox.warning(self.parent, "Import Quick Commands", str(exc))
            return
        self._set_status(f"Imported {result.imported_count} quick command(s){result.status_suffix()}.")

    def export_quick_commands_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Export Quick Commands",
            str(Path.cwd() / "comport-zone-quick-commands.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            exported_count = self.export_quick_commands_to_csv(Path(path))
        except (OSError, csv.Error) as exc:
            QMessageBox.warning(self.parent, "Export Quick Commands", str(exc))
            return
        self._set_status(f"Exported {exported_count} quick command(s).")

    def import_quick_files_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.parent,
            "Import Quick Files",
            str(Path.cwd()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        dialog = QuickCommandImportDialog(
            title="Import Quick Files",
            message="Choose whether this CSV adds to your current quick files or replaces them.",
            default_replace=False,
            default_skip_duplicates=True,
            append_label="Append imported files",
            replace_label="Replace current quick files",
            duplicate_checkbox_text="Skip duplicate file paths",
            duplicate_hint_text="Duplicate detection uses the saved file path, ignoring label changes.",
            parent=self.parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        import_options = dialog.options()
        try:
            result = self.import_quick_files_from_csv(
                Path(path),
                options=QuickFileImportOptions(
                    replace_existing=import_options.replace_existing,
                    skip_duplicates=import_options.skip_duplicates,
                ),
            )
        except (OSError, csv.Error, ValueError) as exc:
            QMessageBox.warning(self.parent, "Import Quick Files", str(exc))
            return
        self._set_status(f"Imported {result.imported_count} quick file(s){result.status_suffix()}.")

    def export_quick_files_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Export Quick Files",
            str(Path.cwd() / "comport-zone-quick-files.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            exported_count = self.export_quick_files_to_csv(Path(path))
        except (OSError, csv.Error) as exc:
            QMessageBox.warning(self.parent, "Export Quick Files", str(exc))
            return
        self._set_status(f"Exported {exported_count} quick file(s).")

    def import_quick_commands_from_csv(
        self,
        path: Path,
        *,
        options: QuickCommandImportOptions | None = None,
    ) -> QuickCommandImportResult:
        self._refresh_from_settings()
        result = self.library.import_commands_from_csv(path, options=options)
        self._sync_to_settings()
        selected_id = self.library.quick_commands[-1].id if self.library.quick_commands else ""
        self._refresh_commands(selected_id)
        self._save_settings()
        return result

    def export_quick_commands_to_csv(self, path: Path) -> int:
        self._refresh_from_settings()
        return self.library.export_commands_to_csv(path)

    def import_quick_files_from_csv(
        self,
        path: Path,
        *,
        options: QuickFileImportOptions | None = None,
    ) -> QuickFileImportResult:
        self._refresh_from_settings()
        result = self.library.import_files_from_csv(path, options=options)
        self._sync_to_settings()
        selected_id = self.library.quick_files[-1].id if self.library.quick_files else ""
        self._refresh_files(selected_id)
        self._save_settings()
        return result

    def export_quick_files_to_csv(self, path: Path) -> int:
        self._refresh_from_settings()
        return self.library.export_files_to_csv(path)

    def move_quick_command(self, command_id: str, direction: int) -> None:
        self._refresh_from_settings()
        commands = self.library.quick_commands
        index = next((i for i, command in enumerate(commands) if command.id == command_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(commands):
            return
        commands[index], commands[target] = commands[target], commands[index]
        self._commit_commands(command_id)

    def move_quick_file(self, quick_file_id: str, direction: int) -> None:
        self._refresh_from_settings()
        quick_files = self.library.quick_files
        index = next((i for i, quick_file in enumerate(quick_files) if quick_file.id == quick_file_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(quick_files):
            return
        quick_files[index], quick_files[target] = quick_files[target], quick_files[index]
        self._commit_files(quick_file_id)

    def reorder_quick_commands(self, command_ids: list[str], *, selected_id: str = "") -> None:
        self._refresh_from_settings()
        if not self.library.reorder_commands(command_ids):
            return
        self._commit_commands(selected_id)

    def reorder_quick_files(
        self,
        quick_file_ids: list[str],
        *,
        selected_id: str = "",
        force_custom: bool = False,
    ) -> None:
        self._refresh_from_settings()
        if not self.library.reorder_files(quick_file_ids, force_custom=force_custom):
            return
        self._commit_files(selected_id)

    def reorder_favorite_commands(self, command_ids: list[str], *, selected_id: str = "") -> None:
        self._refresh_from_settings()
        if not self.library.reorder_favorite_commands(command_ids):
            return
        self._commit_commands(selected_id)

    def reorder_favorite_files(self, quick_file_ids: list[str], *, selected_id: str = "") -> None:
        self._refresh_from_settings()
        if not self.library.reorder_favorite_files(quick_file_ids):
            return
        self._commit_files(selected_id)

    def delete_all_quick_commands(self, *, confirm: bool = True) -> bool:
        self._refresh_from_settings()
        count = len(self.library.quick_commands)
        if count == 0:
            self._set_status("No quick commands to delete.")
            return False
        if confirm and not self._confirm_bulk_delete(
            "Delete All Quick Commands",
            f"Delete all {count} quick command{'s' if count != 1 else ''}?\n\n"
            "Command history is not affected.",
        ):
            return False
        self.library.quick_commands = []
        self.library.command_hidden_groups = []
        self._sync_to_settings()
        self._refresh_commands(None)
        self._save_settings()
        self._set_status(f"Deleted {count} quick command{'s' if count != 1 else ''}.")
        return True

    def delete_all_quick_files(self, *, confirm: bool = True) -> bool:
        self._refresh_from_settings()
        count = len(self.library.quick_files)
        if count == 0:
            self._set_status("No quick files to delete.")
            return False
        if confirm and not self._confirm_bulk_delete(
            "Delete All Quick Files",
            f"Delete all {count} saved quick file{'s' if count != 1 else ''}?",
        ):
            return False
        self.library.quick_files = []
        self._sync_to_settings()
        self._refresh_files(None)
        self._save_settings()
        self._set_status(f"Deleted {count} quick file{'s' if count != 1 else ''}.")
        return True

    def _commit_commands(self, selected_id: str | None = None) -> None:
        # Keep the favourites order in step with the live favourite set (prunes
        # un-favourited / deleted ids, appends newly-favourited ones).
        self.library.sync_favorite_command_order()
        self._sync_to_settings()
        self._refresh_commands(selected_id)
        self._save_settings()

    def _commit_files(self, selected_id: str | None = None) -> None:
        self.library.sync_favorite_file_order()
        self._sync_to_settings()
        self._refresh_files(selected_id)
        self._save_settings()
