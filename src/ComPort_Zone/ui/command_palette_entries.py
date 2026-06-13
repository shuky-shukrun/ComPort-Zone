from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtWidgets import QStyle

from ..command_registry import CommandPaletteEntry


class _ProfileLike(Protocol):
    port: str


class TerminalPaletteTab(Protocol):
    title: str
    profile: _ProfileLike

    @property
    def tab_title(self) -> str: ...

    def connection_endpoint(self) -> str: ...

    def connection_status_text(self) -> str: ...


class CommandFilePaletteTab(Protocol):
    def tab_title(self) -> str: ...

    def status_summary(self) -> str: ...


class ControlPanelPaletteTab(Protocol):
    def tab_title(self) -> str: ...

    def status_summary(self) -> str: ...


def workspace_tab_palette_entries(
    *,
    tab_count: int,
    session_at: Callable[[int], TerminalPaletteTab | None],
    command_file_editor_at: Callable[[int], CommandFilePaletteTab | None],
    tab_text: Callable[[int], str],
    activate_tab: Callable[[int], None],
    control_panel_at: Callable[[int], ControlPanelPaletteTab | None] = lambda _index: None,
) -> list[CommandPaletteEntry]:
    entries: list[CommandPaletteEntry] = []
    for index in range(tab_count):
        session = session_at(index)
        editor = command_file_editor_at(index)
        control_panel = control_panel_at(index)
        if session:
            title = session.tab_title
        elif editor:
            title = editor.tab_title()
        elif control_panel:
            title = control_panel.tab_title()
        else:
            title = tab_text(index)
        if session:
            endpoint_getter = getattr(session, "connection_endpoint", None)
            endpoint = str(endpoint_getter()) if callable(endpoint_getter) else str(session.profile.port or "No port")
        else:
            endpoint = "No port"
        if session:
            subtitle = session.connection_status_text()
            icon = QStyle.StandardPixmap.SP_ComputerIcon
            keywords = f"switch tab terminal session {index + 1} {title} {endpoint} {session.title}"
        elif control_panel:
            subtitle = control_panel.status_summary()
            icon = QStyle.StandardPixmap.SP_FileDialogListView
            keywords = f"switch tab control_panel tiles poll {index + 1} {title}"
        elif editor:
            subtitle = editor.status_summary()
            icon = QStyle.StandardPixmap.SP_FileIcon
            keywords = f"switch tab command file editor script {index + 1} {title}"
        else:
            subtitle = endpoint
            icon = QStyle.StandardPixmap.SP_FileIcon
            keywords = f"switch tab {index + 1} {title}"
        entries.append(
            CommandPaletteEntry(
                title=f"Switch to Tab {index + 1}: {title}",
                subtitle=subtitle,
                callback=lambda tab_index=index: activate_tab(tab_index),
                icon=icon,
                keywords=keywords,
            )
        )
    return entries
