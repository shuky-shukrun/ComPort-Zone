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
