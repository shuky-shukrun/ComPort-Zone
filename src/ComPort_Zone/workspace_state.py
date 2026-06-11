from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from .dashboard_models import DashboardTabState
from .models import (
    AppSettings,
    CommandFileTabState,
    LanProfile,
    SerialProfile,
    TerminalSessionState,
    WorkspaceLayoutState,
    WorkspacePaneState,
    WorkspaceTabState,
)


class TerminalStateSource(Protocol):
    profile: SerialProfile | LanProfile

    def to_state(self) -> TerminalSessionState:
        ...


class CommandFileStateSource(Protocol):
    path: Path | None

    def text(self) -> str:
        ...

    def is_dirty(self) -> bool:
        ...


class DashboardStateSource(Protocol):
    def to_tab_state(self) -> DashboardTabState:
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

    def add_dashboard_tab(self, state: DashboardTabState) -> object:
        ...

    def prompt_current_session_settings(self) -> None:
        ...

    def workspace_tab_count(self) -> int:
        ...

    def configure_workspace_layout(
        self,
        layout: WorkspaceLayoutState,
    ) -> None:
        ...


def clone_serial_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def clone_lan_profile(profile: LanProfile) -> LanProfile:
    return LanProfile.from_dict(profile.to_dict())


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
        workspace_layout: WorkspaceLayoutState | None = None,
        dashboard_tabs: Iterable[DashboardStateSource] = (),
    ) -> AppSettings:
        terminal_sessions = list(terminal_sessions)
        command_file_editors = list(command_file_editors)
        dashboard_tabs = list(dashboard_tabs)
        if active_session is not None:
            active_state = active_session.to_state()
            settings.transport_kind = active_state.transport_kind or "serial"
            settings.transport_profile = dict(active_state.transport_profile)
            if active_state.serial is not None:
                settings.serial = clone_serial_profile(active_state.serial)
                if not settings.transport_profile:
                    settings.transport_profile = settings.serial.to_dict()
            if active_state.lan is not None:
                settings.lan = clone_lan_profile(active_state.lan)
                if not settings.transport_profile:
                    settings.transport_profile = settings.lan.to_dict()
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
        settings.restored_dashboards = [
            dashboard.to_tab_state() for dashboard in dashboard_tabs
        ]
        if workspace_layout is not None:
            settings.workspace_layout = workspace_layout
        else:
            settings.workspace_layout = WorkspaceLayoutState(
                panes=[
                    WorkspacePaneState(
                        tabs=[
                            WorkspaceTabState(kind="terminal", terminal=session.to_state())
                            for session in terminal_sessions
                        ]
                        + [
                            WorkspaceTabState(kind="command_file", command_file=self.command_file_state(editor))
                            for editor in command_file_editors
                        ]
                        + [
                            WorkspaceTabState(kind="dashboard", dashboard=dashboard.to_tab_state())
                            for dashboard in dashboard_tabs
                        ],
                    )
                ]
            )
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
        if settings.workspace_layout.panes:
            self._restore_layout(settings.workspace_layout, target)
            if target.workspace_tab_count() == 0:
                target.add_session(prompt_settings=False)
            return

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
        for dashboard_state in settings.restored_dashboards:
            target.add_dashboard_tab(dashboard_state)
        if target.workspace_tab_count() == 0:
            target.add_session(prompt_settings=False)

    def _restore_layout(
        self,
        layout: WorkspaceLayoutState,
        target: WorkspaceRestoreTarget,
    ) -> None:
        configure = getattr(target, "configure_workspace_layout", None)
        select_pane = getattr(target, "select_workspace_pane", None)
        finish = getattr(target, "finish_workspace_layout_restore", None)
        if callable(configure):
            configure(layout)
        for pane_index, pane in enumerate(layout.panes[:2]):
            if callable(select_pane):
                select_pane(pane_index)
            for tab in pane.tabs:
                if tab.kind == "command_file":
                    state = tab.command_file or CommandFileTabState()
                    path = Path(state.path) if state.path else None
                    target.add_command_file_tab(path=path, state=state)
                elif tab.kind == "dashboard":
                    target.add_dashboard_tab(tab.dashboard or DashboardTabState())
                else:
                    target.add_session(tab.terminal or TerminalSessionState(), prompt_settings=False)
        if callable(finish):
            finish(layout)
