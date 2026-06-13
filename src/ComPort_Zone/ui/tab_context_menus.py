from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMenu, QStyle

from ..icons import standard_icon


class TabContextMenuBuilder:
    def __init__(self, host: Any) -> None:
        self.host = host

    def show(self, position) -> None:
        tabs = self.host.tabs
        tab_bar = tabs.tabBar()
        # In a split workspace the menu must address the tab by its global index;
        # tab_bar.tabAt() alone is pane-local and would target the wrong tab in the
        # second pane (issue #11). tab_index_at maps it to the global index.
        resolve_global = getattr(tabs, "tab_index_at", None)
        index = resolve_global(position) if callable(resolve_global) else tab_bar.tabAt(position)
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
            host._add_context_command_action(menu, "control_panel.new")
            host._add_context_command_action(menu, "control_panel.manage")
            return menu

        session = host.session_at(index)
        editor = host.command_file_editor_at(index)
        if editor:
            self._build_editor_menu(menu, index, editor)
            return menu
        control_panel = host.control_panel_at(index)
        if control_panel:
            self._build_control_panel_menu(menu, index, control_panel)
            return menu

        self._build_terminal_menu(menu, index, session)
        return menu

    def _build_control_panel_menu(self, menu: QMenu, index: int, control_panel: Any) -> None:
        host = self.host
        menu.setTitle(control_panel.tab_title())
        host._add_context_command_action(menu, "control_panel.new")
        host._add_context_action(
            menu,
            "Rename Control Panel",
            lambda tab_index=index: host.rename_control_panel(tab_index),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )
        bind_menu = menu.addMenu("Bind to Terminal")
        bind_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_ComputerIcon))
        bind_menu.aboutToShow.connect(
            lambda menu=bind_menu, target=control_panel: host.control_panel_runs.populate_bind_menu(
                menu, target.bind_to_session
            )
        )
        polling_enabled = "user" not in control_panel.scheduler.paused_reasons
        host._add_context_action(
            menu,
            "Pause Polling" if polling_enabled else "Resume Polling",
            lambda target=control_panel, enabled=polling_enabled: target.set_polling_enabled(
                not enabled
            ),
            icon=QStyle.StandardPixmap.SP_MediaPause
            if polling_enabled
            else QStyle.StandardPixmap.SP_MediaPlay,
        )
        host._add_context_action(
            menu,
            "Add Entry...",
            control_panel.add_entry_via_dialog,
            icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        )
        edit_layout_action = host._add_context_action(
            menu,
            "Edit Layout",
            lambda target=control_panel: target.edit_layout_button.toggle(),
        )
        edit_layout_action.setCheckable(True)
        edit_layout_action.setChecked(control_panel.edit_layout_button.isChecked())
        host._add_context_command_action(menu, "control_panel.manage")
        menu.addSeparator()
        self._add_split_actions(menu, index)
        menu.addSeparator()
        host._add_context_command_action(
            menu,
            "file.close_tab",
            lambda tab_index=index: host.close_session(tab_index),
        )
        self._add_common_close_actions(menu, index)

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
        self._add_split_actions(menu, index)
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
        self._add_split_actions(menu, index)
        menu.addSeparator()
        host._add_context_command_action(
            menu,
            "file.close_tab",
            lambda tab_index=index: host.close_session(tab_index),
        )
        self._add_common_close_actions(menu, index)

    def _add_common_close_actions(self, menu: QMenu, index: int) -> None:
        host = self.host
        tab_ref = getattr(host.tabs, "tab_ref", lambda _index: None)(index)
        has_tabs_to_right = (
            tab_ref.local_index < tab_ref.pane.count() - 1
            if tab_ref is not None
            else index < host.tabs.count() - 1
        )
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
            enabled=has_tabs_to_right,
        )

    def _add_split_actions(self, menu: QMenu, index: int) -> None:
        host = self.host
        host._add_context_action(
            menu,
            "Move to Other Pane",
            lambda tab_index=index: host.move_tab_to_other_pane(tab_index),
            icon=QStyle.StandardPixmap.SP_ArrowRight,
            enabled=host.tabs.count() > 1,
        )
        host._add_context_action(
            menu,
            "Split Right",
            lambda tab_index=index: host.split_tab_right(tab_index),
            icon=QStyle.StandardPixmap.SP_ArrowRight,
        )
        host._add_context_action(
            menu,
            "Split Down",
            lambda tab_index=index: host.split_tab_down(tab_index),
            icon=QStyle.StandardPixmap.SP_ArrowDown,
        )
        host._add_context_command_action(
            menu,
            "view.join_panes",
            enabled=getattr(host.tabs, "pane_count", lambda: 1)() > 1,
        )
