from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QStyle

from ..command_registry import (
    CommandRegistry,
    SUBMENU_CONVERT_SELECTION,
    SUBMENU_IMPORT_EXPORT,
    SUBMENU_LINE_ENDING,
    SUBMENU_OPEN_RECENT,
    SUBMENU_RUN_IN_TERMINAL,
    SUBMENU_RX_DISPLAY,
    SUBMENU_SEND_MODE,
    SUBMENU_TERMINAL_FONT,
    SUBMENU_THEME,
)
from ..icons import build_icon, set_action_icon
from ..models import LINE_ENDINGS, RECEIVE_DISPLAY_MODES, THEME_OPTIONS
from ..quick_actions import SEND_MODES

HARDWARE_FLOW_CONTROL = ("RTS/CTS", "DSR/DTR")

# Dwell time before hovering a theme in the menu applies it as a live preview.
THEME_PREVIEW_DELAY_MS = 1000


@dataclass(slots=True)
class MainMenuHandles:
    file_menu: QMenu
    edit_menu: QMenu
    view_menu: QMenu
    connection_menu: QMenu
    terminal_menu: QMenu
    tools_menu: QMenu
    help_menu: QMenu
    open_recent_menu: QMenu
    import_export_menu: QMenu
    theme_menu: QMenu
    theme_group: QActionGroup
    theme_actions: dict[str, QAction]
    terminal_font_menu: QMenu
    rx_display_menu: QMenu
    rx_display_group: QActionGroup
    rx_display_actions: dict[str, QAction]
    send_mode_menu: QMenu
    send_mode_group: QActionGroup
    send_mode_actions: dict[str, QAction]
    line_ending_menu: QMenu
    line_ending_group: QActionGroup
    line_ending_actions: dict[str, QAction]
    convert_selection_menu: QMenu
    run_in_terminal_menu: QMenu
    timestamps_action: QAction
    wrap_action: QAction
    dtr_action: QAction
    rts_action: QAction
    auto_reconnect_action: QAction
    check_for_updates_on_launch_action: QAction

    def install_on(self, host: Any) -> None:
        for field in fields(self):
            setattr(host, field.name, getattr(self, field.name))


class MainWindowMenuBuilder:
    def __init__(self, host: Any, command_registry: CommandRegistry) -> None:
        self.host = host
        self.command_registry = command_registry
        self._sub: dict[str, Any] = {}

    def build(self) -> MainMenuHandles:
        menu_bar = self.host.menuBar()

        file_menu = menu_bar.addMenu("File")
        edit_menu = menu_bar.addMenu("Edit")
        view_menu = menu_bar.addMenu("View")
        connection_menu = menu_bar.addMenu("Connection")
        terminal_menu = menu_bar.addMenu("Terminal")
        tools_menu = menu_bar.addMenu("Tools")
        help_menu = menu_bar.addMenu("Help")

        file_actions = self._populate(file_menu, "file")
        self._populate(edit_menu, "edit")
        view_actions = self._populate(view_menu, "view")
        connection_actions = self._populate(connection_menu, "connection")
        self._populate(terminal_menu, "terminal")
        tools_actions = self._populate(tools_menu, "tools")
        help_actions = self._populate(help_menu, "help")

        timestamps_action = view_actions["view.show_timestamps"]
        timestamps_action.setChecked(self.host.settings.timestamps_enabled)
        wrap_action = view_actions["view.line_wrap"]
        wrap_action.setChecked(self.host.settings.line_wrap_enabled)
        check_for_updates_on_launch_action = help_actions["help.check_for_updates_on_launch"]
        check_for_updates_on_launch_action.setChecked(
            self.host.settings.check_for_updates_on_launch
        )

        # Stash the actions the aboutToShow gating handlers toggle.
        self._dtr_action = connection_actions["connection.dtr"]
        self._rts_action = connection_actions["connection.rts"]
        self._auto_reconnect_action = connection_actions["connection.auto_reconnect"]
        self._send_break_action = connection_actions["connection.send_break"]
        self._run_action = tools_actions["command_file.run"]
        self._pause_action = tools_actions["command_file.pause_resume"]
        self._stop_action = tools_actions["command_file.stop"]
        self._send_file_action = file_actions["command_file.send_file"]
        self._close_other_action = file_actions["file.close_other_tabs"]
        self._save_action = file_actions["command_file.save"]
        self._save_as_action = file_actions["command_file.save_as"]
        self._join_panes_action = view_actions["view.join_panes"]

        # State that only makes sense relative to the active tab is refreshed
        # whenever the menu opens (never at build time — there is no session yet,
        # and the menu unit test's fake host only carries a few settings).
        file_menu.aboutToShow.connect(self._sync_file_menu)
        edit_menu.aboutToShow.connect(self._sync_edit_menu)
        view_menu.aboutToShow.connect(self._sync_view_menu)
        connection_menu.aboutToShow.connect(self._sync_connection_menu)
        tools_menu.aboutToShow.connect(self._sync_tools_menu)

        return MainMenuHandles(
            file_menu=file_menu,
            edit_menu=edit_menu,
            view_menu=view_menu,
            connection_menu=connection_menu,
            terminal_menu=terminal_menu,
            tools_menu=tools_menu,
            help_menu=help_menu,
            open_recent_menu=self._sub["open_recent"],
            import_export_menu=self._sub["import_export"],
            theme_menu=self._sub["theme_menu"],
            theme_group=self._sub["theme_group"],
            theme_actions=self._sub["theme_actions"],
            terminal_font_menu=self._sub["terminal_font"],
            rx_display_menu=self._sub["rx_display_menu"],
            rx_display_group=self._sub["rx_display_group"],
            rx_display_actions=self._sub["rx_display_actions"],
            send_mode_menu=self._sub["send_mode_menu"],
            send_mode_group=self._sub["send_mode_group"],
            send_mode_actions=self._sub["send_mode_actions"],
            line_ending_menu=self._sub["line_ending_menu"],
            line_ending_group=self._sub["line_ending_group"],
            line_ending_actions=self._sub["line_ending_actions"],
            convert_selection_menu=self._sub["convert_selection"],
            run_in_terminal_menu=self._sub["run_in_terminal"],
            timestamps_action=timestamps_action,
            wrap_action=wrap_action,
            dtr_action=self._dtr_action,
            rts_action=self._rts_action,
            auto_reconnect_action=self._auto_reconnect_action,
            check_for_updates_on_launch_action=check_for_updates_on_launch_action,
        )

    # ------------------------------------------------------------- population

    def _populate(self, menu: QMenu, menu_key: str) -> dict[str, QAction]:
        actions: dict[str, QAction] = {}
        for item in self.command_registry.menu_items(menu_key):
            if item is None:
                menu.addSeparator()
            elif item.startswith("@"):
                self._add_submenu(menu, item)
            else:
                actions[item] = self.add_registered_action(menu, item)
        return actions

    def _add_submenu(self, menu: QMenu, token: str) -> None:
        {
            SUBMENU_OPEN_RECENT: self._build_open_recent,
            SUBMENU_IMPORT_EXPORT: self._build_import_export,
            SUBMENU_THEME: self._build_theme,
            SUBMENU_TERMINAL_FONT: self._build_terminal_font,
            SUBMENU_RX_DISPLAY: self._build_rx_display,
            SUBMENU_SEND_MODE: self._build_send_mode,
            SUBMENU_LINE_ENDING: self._build_line_ending,
            SUBMENU_CONVERT_SELECTION: self._build_convert_selection,
            SUBMENU_RUN_IN_TERMINAL: self._build_run_in_terminal,
        }[token](menu)

    # ------------------------------------------------------------- submenus

    def _build_open_recent(self, parent: QMenu) -> None:
        submenu = parent.addMenu("Open Recent")
        set_action_icon(submenu, QStyle.StandardPixmap.SP_DirOpenIcon)
        submenu.aboutToShow.connect(
            lambda menu=submenu: self.host.populate_open_recent_menu(menu)
        )
        self._sub["open_recent"] = submenu

    def _build_import_export(self, parent: QMenu) -> None:
        submenu = parent.addMenu("Import / Export")
        set_action_icon(submenu, QStyle.StandardPixmap.SP_DialogSaveButton)
        for item in self.command_registry.menu_items("import_export"):
            if item is None:
                submenu.addSeparator()
            else:
                self.add_registered_action(submenu, item)
        self._sub["import_export"] = submenu

    def _build_theme(self, parent: QMenu) -> None:
        submenu = parent.addMenu("Theme")
        group = QActionGroup(self.host)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}

        # Live preview: dwelling on a theme for ~1s applies it without saving so
        # the user can see it; clicking commits, leaving the menu reverts.
        self._theme_preview_timer = QTimer(self.host)
        self._theme_preview_timer.setSingleShot(True)
        self._theme_preview_timer.setInterval(THEME_PREVIEW_DELAY_MS)
        self._theme_preview_timer.timeout.connect(self._apply_theme_preview)
        self._theme_preview_pending: str | None = None
        self._theme_preview_original: str | None = None
        self._theme_committed = False

        for theme_name in THEME_OPTIONS:
            action = QAction(theme_name, self.host)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, name=theme_name: self._commit_theme(name)
            )
            action.hovered.connect(
                lambda name=theme_name: self._queue_theme_preview(name)
            )
            group.addAction(action)
            submenu.addAction(action)
            actions[theme_name] = action

        submenu.aboutToShow.connect(self._begin_theme_preview)
        submenu.aboutToHide.connect(self._end_theme_preview)

        self._sub["theme_menu"] = submenu
        self._sub["theme_group"] = group
        self._sub["theme_actions"] = actions

    def _begin_theme_preview(self) -> None:
        self._theme_preview_original = getattr(self.host.settings, "theme", None)
        self._theme_committed = False

    def _queue_theme_preview(self, name: str) -> None:
        self._theme_preview_pending = name
        self._theme_preview_timer.start()  # restart the dwell countdown

    def _apply_theme_preview(self) -> None:
        if self._theme_preview_pending and not self._theme_committed:
            self.host.apply_theme(self._theme_preview_pending, save=False)

    def _commit_theme(self, name: str) -> None:
        self._theme_preview_timer.stop()
        self._theme_committed = True
        self.host.apply_theme(name)

    def _end_theme_preview(self) -> None:
        # Qt emits triggered() before aboutToHide() when an item is clicked, so
        # _theme_committed is already set for a real selection by the time we get
        # here; otherwise restore the theme that was active before previewing.
        self._theme_preview_timer.stop()
        if not self._theme_committed and self._theme_preview_original:
            self.host.apply_theme(self._theme_preview_original, save=False)
        self._theme_preview_pending = None

    def _build_terminal_font(self, parent: QMenu) -> None:
        # Zoom controls only — full font configuration lives in Preferences
        # (the standalone Terminal Font Settings dialog stays in the palette).
        submenu = parent.addMenu("Terminal Font")
        set_action_icon(submenu, "cog")
        for command_id in ("view.increase_font", "view.decrease_font", "view.reset_font"):
            self.add_registered_action(submenu, command_id)
        self._sub["terminal_font"] = submenu

    def _build_rx_display(self, parent: QMenu) -> None:
        submenu, group, actions = self._build_radio(
            parent,
            "RX Display",
            RECEIVE_DISPLAY_MODES,
            lambda value: self.host.set_receive_display_mode(value),
            icon="hex",
        )
        submenu.aboutToShow.connect(
            lambda a=actions: self._sync_radio(a, self.host.settings.receive_display_mode)
        )
        self._sub["rx_display_menu"] = submenu
        self._sub["rx_display_group"] = group
        self._sub["rx_display_actions"] = actions

    def _build_send_mode(self, parent: QMenu) -> None:
        submenu, group, actions = self._build_radio(
            parent,
            "Send Mode",
            SEND_MODES,
            lambda value: self.host.with_session(lambda session: session.set_send_mode(value)),
            icon="send",
        )
        submenu.aboutToShow.connect(lambda a=actions: self._sync_send_mode(a))
        self._sub["send_mode_menu"] = submenu
        self._sub["send_mode_group"] = group
        self._sub["send_mode_actions"] = actions

    def _build_line_ending(self, parent: QMenu) -> None:
        submenu, group, actions = self._build_radio(
            parent,
            "Line Ending",
            tuple(LINE_ENDINGS.keys()),
            lambda value: self.host.with_session(lambda session: session.set_line_ending(value)),
        )
        submenu.aboutToShow.connect(lambda a=actions: self._sync_line_ending(a))
        self._sub["line_ending_menu"] = submenu
        self._sub["line_ending_group"] = group
        self._sub["line_ending_actions"] = actions

    def _build_radio(self, parent, title, values, on_select, *, icon=None):
        submenu = parent.addMenu(title)
        if icon is not None:
            set_action_icon(submenu, icon)
        group = QActionGroup(self.host)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for value in values:
            action = QAction(value, self.host)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, chosen=value: on_select(chosen)
            )
            group.addAction(action)
            submenu.addAction(action)
            actions[value] = action
        return submenu, group, actions

    def _build_convert_selection(self, parent: QMenu) -> None:
        submenu = parent.addMenu("Convert Selection")
        set_action_icon(submenu, "hex")
        entries = (
            ("Show Selection as Hex", "show_hex"),
            ("Show Hex Selection as Text", "show_text"),
            None,
            ("Replace Selection with Hex", "replace_hex"),
            ("Replace Hex Selection with Text", "replace_text"),
        )
        for entry in entries:
            if entry is None:
                submenu.addSeparator()
                continue
            text, kind = entry
            action = QAction(text, self.host)
            action.triggered.connect(
                lambda _checked=False, mode=kind: self._convert_selection(mode)
            )
            submenu.addAction(action)
        self._sub["convert_selection"] = submenu

    def _build_run_in_terminal(self, parent: QMenu) -> None:
        submenu = parent.addMenu("Run in Terminal")
        set_action_icon(submenu, QStyle.StandardPixmap.SP_ArrowForward)
        submenu.aboutToShow.connect(
            lambda menu=submenu: self.host.populate_run_editor_menu(menu)
        )
        self._sub["run_in_terminal"] = submenu

    # ------------------------------------------------- aboutToShow gating

    def _sync_radio(self, actions: dict[str, QAction], current) -> None:
        for value, action in actions.items():
            action.setChecked(value == current)

    def _sync_send_mode(self, actions: dict[str, QAction]) -> None:
        session = self.host.current_session()
        current = session.mode_combo.currentText() if session is not None else None
        self._sync_radio(actions, current)

    def _sync_line_ending(self, actions: dict[str, QAction]) -> None:
        session = self.host.current_session()
        current = session.profile.line_ending if session is not None else None
        self._sync_radio(actions, current)

    def _convert_selection(self, kind: str) -> None:
        def run(session) -> None:
            text = session.selected_terminal_text()
            if not text:
                return
            if kind == "show_hex":
                session.show_converted_selection("Selection as Hex", session.text_to_hex(text))
            elif kind == "show_text":
                session.show_hex_selection_as_text(text)
            elif kind == "replace_hex":
                session.replace_terminal_selection(session.text_to_hex(text))
            elif kind == "replace_text":
                session.replace_hex_selection_with_text(text)

        self.host.with_session(run)

    def _any_session_connected(self) -> bool:
        return any(
            getattr(session, "transport", None) is not None
            and session.transport.is_connected
            for session in self.host.iter_sessions()
        )

    def _sync_file_menu(self) -> None:
        session = self.host.current_session()
        connected = bool(
            session is not None and getattr(session.transport, "is_connected", False)
        )
        self._send_file_action.setEnabled(connected)
        self._close_other_action.setEnabled(self.host.workspace_tab_count() > 1)
        has_editor = self.host.current_command_file_editor() is not None
        self._save_action.setEnabled(has_editor)
        self._save_as_action.setEnabled(has_editor)

    def _sync_view_menu(self) -> None:
        self._join_panes_action.setEnabled(self.host.tabs.pane_count() > 1)

    def _sync_edit_menu(self) -> None:
        session = self.host.current_session()
        has_selection = bool(session is not None and session.selected_terminal_text())
        self._sub["convert_selection"].menuAction().setEnabled(has_selection)

    def _sync_connection_menu(self) -> None:
        session = self.host.current_session()
        has_session = session is not None
        signals_live = bool(
            has_session
            and session.supports_signals()
            and getattr(session.transport, "is_connected", False)
        )
        hardware_flow = bool(
            signals_live
            and getattr(session.profile, "flow_control", "None") in HARDWARE_FLOW_CONTROL
        )
        self._dtr_action.setEnabled(signals_live and not hardware_flow)
        self._rts_action.setEnabled(signals_live and not hardware_flow)
        self._send_break_action.setEnabled(signals_live)
        state = session.signal_state() if signals_live else None
        if state is not None:
            self._dtr_action.setChecked(state[0])
            self._rts_action.setChecked(state[1])
        self._auto_reconnect_action.setEnabled(has_session)
        self._auto_reconnect_action.setChecked(
            bool(has_session and getattr(session.profile, "auto_reconnect", False))
        )
        self._sub["send_mode_menu"].menuAction().setEnabled(has_session)
        self._sub["line_ending_menu"].menuAction().setEnabled(has_session)

    def _sync_tools_menu(self) -> None:
        session = self.host.current_session()
        active = bool(session is not None and session.is_script_active())
        self._run_action.setEnabled(session is not None and not active)
        self._pause_action.setEnabled(active)
        self._stop_action.setEnabled(active)
        # Running a script needs a live connection to send to.
        self._sub["run_in_terminal"].menuAction().setEnabled(self._any_session_connected())

    # --------------------------------------- shared helpers (host-delegated)

    def add_registered_menu_section(self, menu: QMenu, menu_key: str) -> dict[str, QAction]:
        actions: dict[str, QAction] = {}
        for command_id in self.command_registry.menu_items(menu_key):
            if command_id is None:
                menu.addSeparator()
            elif command_id.startswith("@"):
                # Builder-special submenu tokens have no meaning in a plain
                # registered section (e.g. a context menu) — skip them.
                continue
            else:
                actions[command_id] = self.add_registered_action(menu, command_id)
        return actions

    def add_registered_action(self, menu: QMenu, command_id: str) -> QAction:
        spec = self.command_registry.spec(command_id)
        return self.add_action(
            menu,
            spec.menu_label(),
            spec.shortcut,
            spec.callback(self.host),
            checkable=spec.checkable,
            icon=None if spec.checkable else spec.icon,
        )

    def add_action(
        self,
        menu: QMenu,
        text: str,
        shortcut: str,
        callback,
        *,
        checkable: bool = False,
        icon: QStyle.StandardPixmap | None = None,
    ) -> QAction:
        action = QAction(text, self.host)
        if icon is not None:
            set_action_icon(action, icon)
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(lambda _checked=False: callback())
        menu.addAction(action)
        return action

    def add_context_action(
        self,
        menu: QMenu,
        text: str,
        callback,
        *,
        icon: QStyle.StandardPixmap | None = None,
        enabled: bool = True,
    ) -> QAction:
        action = QAction(text, self.host)
        if icon is not None:
            action.setIcon(build_icon(icon))
        action.setEnabled(enabled)
        action.triggered.connect(lambda _checked=False: callback())
        menu.addAction(action)
        return action

    def add_context_command_action(
        self,
        menu: QMenu,
        command_id: str,
        callback=None,
        *,
        text: str | None = None,
        enabled: bool = True,
    ) -> QAction:
        spec = self.command_registry.spec(command_id)
        return self.add_context_action(
            menu,
            text or spec.menu_label(),
            callback or spec.callback(self.host),
            icon=spec.icon,
            enabled=enabled,
        )
