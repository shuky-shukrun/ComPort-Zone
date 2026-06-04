from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QStyle

from ..command_registry import CommandRegistry
from ..icons import build_icon, set_action_icon
from ..models import THEME_OPTIONS


@dataclass(slots=True)
class MainMenuHandles:
    file_menu: QMenu
    edit_menu: QMenu
    view_menu: QMenu
    timestamps_action: QAction
    wrap_action: QAction
    theme_menu: QMenu
    theme_group: QActionGroup
    theme_actions: dict[str, QAction]
    session_menu: QMenu
    serial_menu: QMenu
    tools_menu: QMenu
    command_files_menu: QMenu
    run_editor_menu: QMenu
    quick_commands_menu: QMenu
    quick_files_menu: QMenu
    help_menu: QMenu
    check_for_updates_on_launch_action: QAction

    def install_on(self, host: Any) -> None:
        for field in fields(self):
            setattr(host, field.name, getattr(self, field.name))


class MainWindowMenuBuilder:
    def __init__(self, host: Any, command_registry: CommandRegistry) -> None:
        self.host = host
        self.command_registry = command_registry

    def build(self) -> MainMenuHandles:
        menu_bar = self.host.menuBar()

        file_menu = menu_bar.addMenu("File")
        self.add_registered_menu_section(file_menu, "file")

        edit_menu = menu_bar.addMenu("Edit")
        self.add_registered_menu_section(edit_menu, "edit")

        view_menu = menu_bar.addMenu("View")
        view_actions = self.add_registered_menu_section(view_menu, "view")
        timestamps_action = view_actions["view.show_timestamps"]
        timestamps_action.setChecked(self.host.settings.timestamps_enabled)
        wrap_action = view_actions["view.line_wrap"]
        wrap_action.setChecked(self.host.settings.line_wrap_enabled)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self.host)
        theme_group.setExclusive(True)
        theme_actions: dict[str, QAction] = {}
        for theme_name in THEME_OPTIONS:
            action = QAction(theme_name, self.host)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, name=theme_name: self.host.apply_theme(name))
            theme_group.addAction(action)
            theme_menu.addAction(action)
            theme_actions[theme_name] = action

        session_menu = menu_bar.addMenu("Session")
        self.add_registered_menu_section(session_menu, "session")

        serial_menu = menu_bar.addMenu("Serial")
        self.add_registered_menu_section(serial_menu, "serial")

        tools_menu = menu_bar.addMenu("Tools")
        self.add_registered_action(tools_menu, "tools.command_palette")
        tools_menu.addSeparator()

        command_files_menu = tools_menu.addMenu("Command Files")
        set_action_icon(command_files_menu, QStyle.StandardPixmap.SP_MediaPlay)
        self.add_registered_action(command_files_menu, "command_file.new")
        self.add_registered_action(command_files_menu, "command_file.open_editor")
        run_editor_menu = command_files_menu.addMenu("Run in Terminal")
        set_action_icon(run_editor_menu, QStyle.StandardPixmap.SP_ArrowForward)
        run_editor_menu.aboutToShow.connect(lambda menu=run_editor_menu: self.host.populate_run_editor_menu(menu))
        command_files_menu.addSeparator()
        self.add_registered_action(command_files_menu, "command_file.run")
        self.add_registered_action(command_files_menu, "command_file.pause_resume")
        self.add_registered_action(command_files_menu, "command_file.stop")

        quick_commands_menu = tools_menu.addMenu("Quick Commands")
        set_action_icon(quick_commands_menu, QStyle.StandardPixmap.SP_CommandLink)
        self.add_registered_menu_section(quick_commands_menu, "quick_commands")

        quick_files_menu = tools_menu.addMenu("Quick Files")
        set_action_icon(quick_files_menu, QStyle.StandardPixmap.SP_DirOpenIcon)
        self.add_registered_menu_section(quick_files_menu, "quick_files")

        help_menu = menu_bar.addMenu("Help")
        help_actions = self.add_registered_menu_section(help_menu, "help")
        check_for_updates_on_launch_action = help_actions["help.check_for_updates_on_launch"]
        check_for_updates_on_launch_action.setChecked(
            self.host.settings.check_for_updates_on_launch
        )

        return MainMenuHandles(
            file_menu=file_menu,
            edit_menu=edit_menu,
            view_menu=view_menu,
            timestamps_action=timestamps_action,
            wrap_action=wrap_action,
            theme_menu=theme_menu,
            theme_group=theme_group,
            theme_actions=theme_actions,
            session_menu=session_menu,
            serial_menu=serial_menu,
            tools_menu=tools_menu,
            command_files_menu=command_files_menu,
            run_editor_menu=run_editor_menu,
            quick_commands_menu=quick_commands_menu,
            quick_files_menu=quick_files_menu,
            help_menu=help_menu,
            check_for_updates_on_launch_action=check_for_updates_on_launch_action,
        )

    def add_registered_menu_section(self, menu: QMenu, menu_key: str) -> dict[str, QAction]:
        actions: dict[str, QAction] = {}
        for command_id in self.command_registry.menu_items(menu_key):
            if command_id is None:
                menu.addSeparator()
                continue
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
