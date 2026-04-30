from __future__ import annotations

from collections.abc import Callable, Iterable
from .models import AppSettings
from .settings_service import SettingsService
from .workspace_state import CommandFileStateSource, TerminalStateSource, WorkspaceStateService


class WorkspaceSettingsController:
    def __init__(
        self,
        *,
        settings_service: SettingsService,
        workspace_state_service: WorkspaceStateService,
        settings_supplier: Callable[[], AppSettings],
        set_settings: Callable[[AppSettings], None],
        is_loading: Callable[[], bool],
        set_loading: Callable[[bool], None],
        refresh_quick_actions: Callable[[], None],
        sync_quick_actions: Callable[[], None],
        active_session_supplier: Callable[[], TerminalStateSource | None],
        terminal_sessions_supplier: Callable[[], Iterable[TerminalStateSource]],
        command_file_editors_supplier: Callable[[], Iterable[CommandFileStateSource]],
        command_history_supplier: Callable[[], Iterable[str]],
        window_size_supplier: Callable[[], tuple[int, int]],
        clear_workspace: Callable[[], None],
        rebuild_runtime_state: Callable[[AppSettings], None],
        restore_workspace: Callable[[], None],
        apply_settings_to_ui: Callable[[], None],
        set_status: Callable[[str], None],
    ) -> None:
        self.settings_service = settings_service
        self.workspace_state_service = workspace_state_service
        self._settings_supplier = settings_supplier
        self._set_settings = set_settings
        self._is_loading = is_loading
        self._set_loading = set_loading
        self._refresh_quick_actions = refresh_quick_actions
        self._sync_quick_actions = sync_quick_actions
        self._active_session_supplier = active_session_supplier
        self._terminal_sessions_supplier = terminal_sessions_supplier
        self._command_file_editors_supplier = command_file_editors_supplier
        self._command_history_supplier = command_history_supplier
        self._window_size_supplier = window_size_supplier
        self._clear_workspace = clear_workspace
        self._rebuild_runtime_state = rebuild_runtime_state
        self._restore_workspace = restore_workspace
        self._apply_settings_to_ui = apply_settings_to_ui
        self._set_status = set_status

    def save_settings(self) -> bool:
        if self._is_loading():
            return True
        self._refresh_quick_actions()
        self._sync_quick_actions()
        width, height = self._window_size_supplier()
        settings = self._settings_supplier()
        self.workspace_state_service.capture_into_settings(
            settings,
            active_session=self._active_session_supplier(),
            terminal_sessions=self._terminal_sessions_supplier(),
            command_file_editors=self._command_file_editors_supplier(),
            command_history=self._command_history_supplier(),
            window_width=width,
            window_height=height,
        )
        if not self.settings_service.save(settings):
            self._set_status("Could not save settings to disk.")
            return False
        return True

    def apply_imported_settings(self, imported_settings: AppSettings) -> None:
        self._refresh_quick_actions()
        self._sync_quick_actions()
        settings = self.settings_service.preserve_quick_actions(imported_settings, self._settings_supplier())
        self._clear_workspace()
        previous_loading = self._is_loading()
        self._set_loading(True)
        try:
            self._set_settings(settings)
            self._rebuild_runtime_state(settings)
            self._restore_workspace()
        finally:
            self._set_loading(previous_loading)
        self._apply_settings_to_ui()
