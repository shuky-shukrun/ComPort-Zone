from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMenu, QStyle

from ..icons import standard_icon


class TabContextMenuBuilder:
    def __init__(self, host: Any) -> None:
        self.host = host

    def show(self, position) -> None:
        tab_bar = self.host.tabs.tabBar()
        index = tab_bar.tabAt(position)
        menu = self.build(index)
        menu.exec(tab_bar.mapToGlobal(position))

    def show_empty_at(self, global_position) -> None:
        self.build(-1).exec(global_position)

    def build(self, index: int) -> QMenu:
        host = self.host
        menu = QMenu(host)
        if index < 0:
            host._add_context_command_action(menu, "file.new_tab")
            host._add_context_command_action(menu, "command_file.new")
            return menu

        session = host.session_at(index)
        editor = host.command_file_editor_at(index)
        if editor:
            self._build_editor_menu(menu, index, editor)
            return menu

        self._build_terminal_menu(menu, index, session)
        return menu

    def _build_editor_menu(self, menu: QMenu, index: int, editor: Any) -> None:
        host = self.host
        menu.setTitle(editor.tab_title())
        host._add_context_command_action(menu, "command_file.new")
        host._add_context_action(
            menu,
            "Save",
            editor.save,
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            enabled=editor.is_dirty() or editor.path is None,
        )
        host._add_context_action(
            menu,
            "Save As",
            editor.save_as,
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        run_menu = menu.addMenu("Run in Terminal")
        run_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_ArrowForward))
        run_menu.aboutToShow.connect(lambda menu=run_menu, source=editor: host.populate_run_editor_menu(menu, source))
        if editor.path:
            host._add_context_action(
                menu,
                "Show in Explorer",
                lambda source=editor: host.show_path_in_explorer(Path(source.path)),
                icon=QStyle.StandardPixmap.SP_DirOpenIcon,
            )
        menu.addSeparator()
        host._add_context_command_action(
            menu,
            "file.close_tab",
            lambda tab_index=index: host.close_session(tab_index),
        )
        self._add_common_close_actions(menu, index)

    def _build_terminal_menu(self, menu: QMenu, index: int, session: Any | None) -> None:
        host = self.host
        is_connected = bool(session and session.serial_client.is_connected)
        is_reconnecting = bool(session and session.serial_client.is_reconnecting)
        menu.setTitle(session.tab_title if session else host.tabs.tabText(index))
        host._add_context_command_action(menu, "file.new_tab")
        host._add_context_command_action(
            menu,
            "file.duplicate_tab",
            lambda tab_index=index: host.duplicate_session(tab_index),
        )
        host._add_context_command_action(
            menu,
            "session.rename_tab",
            lambda tab_index=index: host.rename_session(tab_index),
        )
        menu.addSeparator()
        host._add_context_command_action(
            menu,
            "serial.settings",
            lambda tab_index=index: host.open_session_settings(tab_index),
            enabled=session is not None,
        )
        host._add_context_action(
            menu,
            "Disconnect" if is_connected else "Stop Retry" if is_reconnecting else "Connect",
            lambda tab_index=index: host.toggle_session_connection(tab_index),
            icon=QStyle.StandardPixmap.SP_ComputerIcon,
            enabled=session is not None,
        )
        host._add_context_command_action(
            menu,
            "edit.find",
            lambda tab_index=index: host.show_session_search(tab_index),
            text="Search",
            enabled=session is not None,
        )
        host._add_context_command_action(
            menu,
            "edit.clear_terminal",
            lambda tab_index=index: host.clear_session_terminal(tab_index),
            enabled=session is not None,
        )
        menu.addSeparator()
        host._add_context_command_action(
            menu,
            "file.close_tab",
            lambda tab_index=index: host.close_session(tab_index),
        )
        self._add_common_close_actions(menu, index)

    def _add_common_close_actions(self, menu: QMenu, index: int) -> None:
        host = self.host
        host._add_context_action(
            menu,
            "Close Other Tabs",
            lambda tab_index=index: host.close_other_sessions(tab_index),
            icon=QStyle.StandardPixmap.SP_TitleBarCloseButton,
            enabled=host.tabs.count() > 1,
        )
        host._add_context_action(
            menu,
            "Close Tabs to the Right",
            lambda tab_index=index: host.close_sessions_to_right(tab_index),
            icon=QStyle.StandardPixmap.SP_ArrowRight,
            enabled=index < host.tabs.count() - 1,
        )
