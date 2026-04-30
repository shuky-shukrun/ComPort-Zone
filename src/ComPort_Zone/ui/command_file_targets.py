from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QStyle

from ..command_run_targets import CommandRunRequest, CommandRunTarget, CommandRunTargetService
from ..icons import standard_icon


class SerialClientLike(Protocol):
    is_connected: bool


class TerminalSessionLike(Protocol):
    session_id: int
    tab_title: str
    serial_client: SerialClientLike

    def connection_status_text(self) -> str:
        ...

    def run_script_text(
        self,
        text: str,
        source_label: str = "Editor buffer",
        source_path: Path | None = None,
    ) -> None:
        ...


class CommandFileEditorLike(Protocol):
    path: Path | None

    def display_name(self) -> str:
        ...

    def refresh_run_targets(self) -> None:
        ...

    def text(self) -> str:
        ...

    def update_validation_status(self) -> None:
        ...

    def validation_errors(self) -> list[str]:
        ...


class CommandFileRunCoordinator:
    def __init__(
        self,
        *,
        sessions_supplier: Callable[[], Iterable[TerminalSessionLike]],
        editors_supplier: Callable[[], Iterable[CommandFileEditorLike]],
        current_editor_supplier: Callable[[], CommandFileEditorLike | None],
        is_widget_open: Callable[[object], bool],
        set_status: Callable[[str], None],
        target_icon_color: Callable[[], str],
    ) -> None:
        self._sessions_supplier = sessions_supplier
        self._editors_supplier = editors_supplier
        self._current_editor_supplier = current_editor_supplier
        self._is_widget_open = is_widget_open
        self._set_status = set_status
        self._target_icon_color = target_icon_color
        self.target_service = CommandRunTargetService(
            targets_supplier=self.run_targets,
            run_callback=self.run_request_in_target,
        )

    def connected_sessions(self) -> list[TerminalSessionLike]:
        return [
            session
            for session in self._sessions_supplier()
            if session.serial_client.is_connected
        ]

    def run_targets(self) -> list[CommandRunTarget]:
        return [
            CommandRunTarget(session.session_id, session.connection_status_text())
            for session in self.connected_sessions()
        ]

    def session_by_id(self, session_id: int) -> TerminalSessionLike | None:
        return next(
            (session for session in self._sessions_supplier() if session.session_id == session_id),
            None,
        )

    def refresh_editor_targets(self) -> None:
        for editor in self._editors_supplier():
            editor.refresh_run_targets()

    def populate_run_menu(self, menu: QMenu, editor: CommandFileEditorLike | None = None) -> None:
        menu.clear()
        editor = editor or self._current_editor_supplier()
        if editor is None:
            self._add_disabled_action(menu, "Open a command-file tab first")
            return
        if editor.validation_errors():
            self._add_disabled_action(menu, "Fix syntax errors before running")
            return
        sessions = self.connected_sessions()
        if not sessions:
            self._add_disabled_action(menu, "No connected terminals")
            return
        for session in sessions:
            action = QAction(session.connection_status_text(), menu)
            action.setIcon(standard_icon(QStyle.StandardPixmap.SP_ComputerIcon, 16, self._target_icon_color()))
            action.triggered.connect(
                lambda _checked=False, source=editor, target_id=session.session_id: self.run_editor_in_target_by_id(
                    source,
                    target_id,
                )
            )
            menu.addAction(action)

    def run_request_in_target(self, request: CommandRunRequest, session_id: int) -> bool:
        session = self.session_by_id(session_id)
        if not session:
            self._set_status("Selected terminal is no longer available.")
            return False
        if not session.serial_client.is_connected:
            self._set_status(f"{session.tab_title} is not connected.")
            return False
        session.run_script_text(request.text, source_label=request.source_label, source_path=request.path)
        self._set_status(f"Running {request.display_name} in {session.tab_title}.")
        return True

    def run_editor_in_target_by_id(self, editor: CommandFileEditorLike, session_id: int) -> None:
        session = self.session_by_id(session_id)
        if not session:
            self._set_status("Selected terminal is no longer available.")
            return
        self.run_editor_in_target(editor, session)

    def run_editor_in_target(self, editor: CommandFileEditorLike, session: TerminalSessionLike) -> None:
        if not self._is_widget_open(editor) or not self._is_widget_open(session):
            self._set_status("Command-file tab or terminal tab is no longer available.")
            return
        if not session.serial_client.is_connected:
            self._set_status(f"{session.tab_title} is not connected.")
            return
        if editor.validation_errors():
            editor.update_validation_status()
            self._set_status("Fix command-file syntax errors before running.")
            return
        label = str(editor.path) if editor.path else editor.display_name()
        session.run_script_text(editor.text(), source_label=label, source_path=editor.path)
        self._set_status(f"Running {editor.display_name()} in {session.tab_title}.")

    def _add_disabled_action(self, menu: QMenu, text: str) -> None:
        action = menu.addAction(text)
        action.setEnabled(False)
