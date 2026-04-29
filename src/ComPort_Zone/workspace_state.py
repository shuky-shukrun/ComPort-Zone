from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from .models import AppSettings, CommandFileTabState, SerialProfile, TerminalSessionState


class TerminalStateSource(Protocol):
    profile: SerialProfile

    def to_state(self) -> TerminalSessionState:
        ...


class CommandFileStateSource(Protocol):
    path: Path | None

    def text(self) -> str:
        ...

    def is_dirty(self) -> bool:
        ...


class WorkspaceRestoreTarget(Protocol):
    def add_session(
        self,
        state: TerminalSessionState | None = None,
        *,
        prompt_settings: bool = True,
    ) -> object:
        ...

    def add_command_file_tab(
        self,
        path: Path | None = None,
        state: CommandFileTabState | None = None,
    ) -> object:
        ...

    def prompt_current_session_settings(self) -> None:
        ...

    def workspace_tab_count(self) -> int:
        ...


def clone_serial_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


class WorkspaceStateService:
    def capture_into_settings(
        self,
        settings: AppSettings,
        *,
        active_session: TerminalStateSource | None,
        terminal_sessions: Iterable[TerminalStateSource],
        command_file_editors: Iterable[CommandFileStateSource],
        command_history: Iterable[str],
        window_width: int,
        window_height: int,
    ) -> AppSettings:
        if active_session is not None:
            settings.serial = clone_serial_profile(active_session.profile)
            settings.transport_kind = "serial"
            settings.transport_profile = settings.serial.to_dict()
        settings.command_history = [str(command) for command in command_history]
        settings.window_width = int(window_width)
        settings.window_height = int(window_height)
        settings.restored_tabs = [
            session.to_state()
            for session in terminal_sessions
        ]
        settings.restored_command_files = [
            self.command_file_state(editor)
            for editor in command_file_editors
        ]
        return settings

    def command_file_state(self, editor: CommandFileStateSource) -> CommandFileTabState:
        path = editor.path
        dirty = editor.is_dirty()
        return CommandFileTabState(
            path=str(path) if path else "",
            text=editor.text() if dirty or path is None else "",
            dirty=dirty,
        )

    def restore_from_settings(
        self,
        settings: AppSettings,
        target: WorkspaceRestoreTarget,
        *,
        prompt_first_settings: bool = True,
    ) -> None:
        terminal_states = list(settings.restored_tabs)
        if not terminal_states:
            target.add_session(
                TerminalSessionState(title="Terminal 1"),
                prompt_settings=False,
            )
            if prompt_first_settings:
                target.prompt_current_session_settings()
        else:
            for state in terminal_states:
                target.add_session(state, prompt_settings=False)
        for command_file_state in settings.restored_command_files:
            path = Path(command_file_state.path) if command_file_state.path else None
            target.add_command_file_tab(path=path, state=command_file_state)
        if target.workspace_tab_count() == 0:
            target.add_session(prompt_settings=False)
