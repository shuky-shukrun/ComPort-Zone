from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, cast

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
)

from .. import __version__
from .. import quick_actions as _quick_actions
from ..app_settings_controller import AppSettingsController
from ..command_editor import CommandEditorQuickActionCallbacks, CommandEditorSources, CommandFileEditorDialog
from ..command_registry import CommandPaletteEntry, CommandRegistry
from ..command_run_targets import CommandRunRequest, CommandRunTarget
from ..history import HistoryStore
from ..icons import standard_icon
from ..models import (
    AppSettings,
    CommandFileTabState,
    QuickCommand,
    QuickFile,
    RECEIVE_DISPLAY_MODES,
    SerialProfile,
    TerminalSessionState,
)
from ..quick_action_controller import QuickActionController
from ..settings_service import SettingsService
from ..storage import SettingsStore, default_config_path
from ..themes import THEMES, ThemePalette
from ..workspace_settings_controller import WorkspaceSettingsController
from ..workspace_state import WorkspaceStateService
from .command_file_targets import CommandFileRunCoordinator
from .command_palette_entries import workspace_tab_palette_entries
from .dialogs import CommandPaletteDialog, TerminalFontSettingsDialog
from .fonts import TERMINAL_FONT_MAX, TERMINAL_FONT_MIN, pick_mono_font, pick_ui_font
from .main_window_menus import MainWindowMenuBuilder
from .tab_workspace import TabWorkspaceController, TerminalTabWidget
from .tab_context_menus import TabContextMenuBuilder
from .terminal_tab import TerminalSessionWidget
from .workspace_status import WorkspaceStatusPresenter, connection_state_color

APP_ICON_PATH = Path(__file__).resolve().parents[1] / "assets" / "comport-zone-icon.png"
QuickActionLibrary = _quick_actions.QuickActionLibrary
QuickCommandImportOptions = _quick_actions.QuickCommandImportOptions
QuickFileImportOptions = _quick_actions.QuickFileImportOptions


def clone_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def app_icon() -> QIcon:
    icon = QIcon(str(APP_ICON_PATH))
    return icon if not icon.isNull() else standard_icon(QStyle.StandardPixmap.SP_ComputerIcon, 32)


class ConnectionStatusLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    config_path_supplier: ClassVar[Callable[[], Path]] = staticmethod(default_config_path)

    def __init__(self) -> None:
        super().__init__()
        self.settings_store = SettingsStore(self.config_path_supplier())
        self.settings_service = SettingsService(self.settings_store)
        self.settings = self.settings_service.load()
        self.workspace_state_service = WorkspaceStateService()
        self.workspace_settings_controller = WorkspaceSettingsController(
            settings_service=self.settings_service,
            workspace_state_service=self.workspace_state_service,
            settings_supplier=lambda: self.settings,
            set_settings=self._set_settings,
            is_loading=lambda: self._loading,
            set_loading=self._set_loading,
            refresh_quick_actions=self._refresh_quick_actions_from_settings,
            sync_quick_actions=self._sync_quick_actions_to_settings,
            active_session_supplier=self.current_session,
            terminal_sessions_supplier=self.iter_sessions,
            command_file_editors_supplier=self.iter_command_file_editors,
            command_history_supplier=lambda: self.history_catalog.all_commands(),
            window_size_supplier=lambda: (self.width(), self.height()),
            clear_workspace=self._clear_workspace_for_settings_apply,
            rebuild_runtime_state=self._rebuild_runtime_state_from_settings,
            restore_workspace=lambda: self.restore_sessions(prompt_first_settings=False),
            apply_settings_to_ui=self.apply_settings_to_ui,
            set_status=self.set_status,
        )
        self.app_settings_controller = AppSettingsController(
            parent=self,
            settings_service=self.settings_service,
            settings_supplier=lambda: self.settings,
            save_runtime_settings=self.save_settings,
            apply_imported_settings=self.apply_imported_settings,
            set_status=self.set_status,
        )
        self.command_registry = CommandRegistry(self)
        self.menu_builder = MainWindowMenuBuilder(self, self.command_registry)
        self.tab_context_menus = TabContextMenuBuilder(self)
        self.quick_actions = self._quick_action_library_from_settings()
        self.quick_action_controller = QuickActionController(
            parent=self,
            library_supplier=lambda: self.quick_actions,
            refresh_from_settings=self._refresh_quick_actions_from_settings,
            sync_to_settings=self._sync_quick_actions_to_settings,
            refresh_commands=self.refresh_quick_commands_everywhere,
            refresh_files=self.refresh_quick_files_everywhere,
            save_settings=self.save_settings,
            set_status=self.set_status,
            confirm_bulk_delete=lambda title, message: self._confirm_bulk_delete(title, message),
        )
        self.history_catalog = HistoryStore(self.settings.command_history)
        self.theme = THEMES.get(self.settings.theme, THEMES["VS Code Dark"])
        self._session_counter = 0
        self._loading = True

        self.setWindowTitle("ComPort Zone")
        self.setWindowIcon(app_icon())
        self.setFont(pick_ui_font())
        self.resize(self.settings.window_width, self.settings.window_height)
        self._build_ui()
        self.tab_workspace = TabWorkspaceController(
            self.tabs,
            terminal_type=TerminalSessionWidget,
            command_file_type=CommandFileEditorDialog,
            add_session=self.add_session,
            confirm_close_command_file_tab=self.confirm_close_command_file_tab,
            save_settings=self.save_settings,
        )
        self.workspace_status = WorkspaceStatusPresenter(
            self.tabs,
            terminal_type=TerminalSessionWidget,
            command_file_type=CommandFileEditorDialog,
            connection_status_label=self.connection_status_label,
            connection_action_button=self.connection_action_button,
            footer=self.footer,
        )
        self.command_file_runs = CommandFileRunCoordinator(
            sessions_supplier=self.iter_sessions,
            editors_supplier=self.iter_command_file_editors,
            current_editor_supplier=self.current_command_file_editor,
            is_widget_open=lambda widget: self.tabs.indexOf(widget) >= 0,
            set_status=self.set_status,
            target_icon_color=lambda: self.theme.rx,
            focus_session=self._focus_session_tab,
        )
        self._build_menus()
        self.apply_theme(self.theme.name)
        self.restore_sessions()
        self._loading = False
        self.set_status("Ready")

    def _build_ui(self) -> None:
        self.tabs = TerminalTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.newTabRequested.connect(lambda: self.add_session(prompt_settings=True))
        self.tabs.currentChanged.connect(lambda _: self.sync_status_from_current_session())
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        self.setCentralWidget(self.tabs)

        self.footer = QLabel("Ready", self)
        self.footer.setObjectName("footer")
        self.connection_status_label = ConnectionStatusLabel("No port selected", self)
        self.connection_status_label.setObjectName("connectionStatus")
        self.connection_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.connection_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connection_status_label.doubleClicked.connect(self.open_current_connection_settings)
        self.connection_action_button = QPushButton("Set Port", self)
        self.connection_action_button.setObjectName("statusActionButton")
        self.connection_action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connection_action_button.clicked.connect(self.connection_status_action_clicked)
        self.version_label = QLabel(f"ComPort Zone v{__version__}", self)
        self.version_label.setObjectName("versionInfo")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.statusBar().addWidget(self.footer, 1)
        self.statusBar().addPermanentWidget(self.connection_status_label)
        self.statusBar().addPermanentWidget(self.connection_action_button)
        self.statusBar().addPermanentWidget(self.version_label)

    def _build_menus(self) -> None:
        self.menu_builder.build().install_on(self)

    def _add_registered_menu_section(self, menu, menu_key: str) -> dict[str, QAction]:
        return self.menu_builder.add_registered_menu_section(menu, menu_key)

    def _add_registered_action(self, menu, command_id: str) -> QAction:
        return self.menu_builder.add_registered_action(menu, command_id)

    def _add_action(
        self,
        menu,
        text: str,
        shortcut: str,
        callback,
        *,
        checkable: bool = False,
        icon: QStyle.StandardPixmap | None = None,
    ) -> QAction:
        return self.menu_builder.add_action(
            menu,
            text,
            shortcut,
            callback,
            checkable=checkable,
            icon=icon,
        )

    def _add_context_action(
        self,
        menu: QMenu,
        text: str,
        callback,
        *,
        icon: QStyle.StandardPixmap | None = None,
        enabled: bool = True,
    ) -> QAction:
        return self.menu_builder.add_context_action(
            menu,
            text,
            callback,
            icon=icon,
            enabled=enabled,
        )

    def _add_context_command_action(
        self,
        menu: QMenu,
        command_id: str,
        callback=None,
        *,
        text: str | None = None,
        enabled: bool = True,
    ) -> QAction:
        return self.menu_builder.add_context_command_action(
            menu,
            command_id,
            callback,
            text=text,
            enabled=enabled,
        )

    def _quick_action_library_from_settings(self) -> QuickActionLibrary:
        return QuickActionLibrary(
            quick_commands=self.settings.quick_commands,
            quick_files=self.settings.quick_files,
            command_sort_mode=self.settings.quick_command_sort_mode,
            command_hidden_groups=self.settings.quick_command_hidden_groups,
            file_sort_mode=self.settings.quick_file_sort_mode,
        )

    def _sync_quick_actions_to_settings(self) -> None:
        self.settings.quick_commands = list(self.quick_actions.quick_commands)
        self.settings.quick_files = list(self.quick_actions.quick_files)
        self.settings.quick_command_sort_mode = self.quick_actions.command_sort_mode
        self.settings.quick_command_hidden_groups = list(self.quick_actions.command_hidden_groups)
        self.settings.quick_file_sort_mode = self.quick_actions.file_sort_mode

    def _refresh_quick_actions_from_settings(self) -> None:
        self.quick_actions = self._quick_action_library_from_settings()

    def show_command_palette(self) -> None:
        CommandPaletteDialog(self).exec()

    def command_editor_sources(self) -> CommandEditorSources:
        self._refresh_quick_actions_from_settings()
        return CommandEditorSources(
            history_commands=self.history_catalog.all_commands(),
            quick_commands=list(self.quick_actions.quick_commands),
            quick_command_hidden_groups=list(self.quick_actions.command_hidden_groups),
        )

    def quick_commands_snapshot(self) -> list[QuickCommand]:
        return self.quick_action_controller.quick_commands_snapshot()

    def visible_quick_commands_snapshot(self) -> list[QuickCommand]:
        return self.quick_action_controller.visible_quick_commands_snapshot()

    def quick_files_snapshot(self) -> list[QuickFile]:
        return self.quick_action_controller.quick_files_snapshot()

    def visible_quick_files_snapshot(self) -> list[QuickFile]:
        return self.quick_action_controller.visible_quick_files_snapshot()

    def quick_command_hidden_groups_snapshot(self) -> list[str]:
        return self.quick_action_controller.quick_command_hidden_groups_snapshot()

    def quick_command_sort_mode_snapshot(self) -> str:
        return self.quick_action_controller.quick_command_sort_mode_snapshot()

    def quick_file_sort_mode_snapshot(self) -> str:
        return self.quick_action_controller.quick_file_sort_mode_snapshot()

    def editor_font(self) -> QFont:
        return pick_mono_font(
            max(TERMINAL_FONT_MIN, min(self.settings.terminal_font_size, TERMINAL_FONT_MAX)),
            self.settings.terminal_font_family,
        )

    def new_command_file_editor(self) -> None:
        self.add_command_file_tab()

    def open_command_file_editor(self, path: Path | str | None = None) -> None:
        if path is None:
            start_dir = self.settings.last_script_path or str(Path.cwd())
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Open Command File Editor",
                start_dir,
                "Text Files (*.txt *.cmd *.scr);;All Files (*)",
            )
            if not selected:
                return
            path = Path(selected)
        elif isinstance(path, str):
            path = Path(path)
        self.add_command_file_tab(path=path)

    def add_command_file_tab(self, path: Path | None = None, state: CommandFileTabState | None = None) -> CommandFileEditorDialog:
        editor = CommandFileEditorDialog(
            sources=self.command_editor_sources(),
            path=path,
            run_callback=None,
            font_change_callback=self.change_font_size,
            quick_files_supplier=self.quick_files_snapshot,
            quick_action_callbacks=CommandEditorQuickActionCallbacks(
                quick_commands_supplier=self.quick_commands_snapshot,
                visible_quick_commands_supplier=self.visible_quick_commands_snapshot,
                quick_command_groups_supplier=self.quick_command_group_names,
                quick_command_hidden_groups_supplier=self.quick_command_hidden_groups_snapshot,
                quick_command_sort_mode_supplier=self.quick_command_sort_mode_snapshot,
                set_quick_command_sort_mode=self.set_quick_command_sort_mode,
                set_quick_command_group_visible=self.set_quick_command_group_visible,
                show_all_quick_command_groups=self.show_all_quick_command_groups,
                hide_all_quick_command_groups=self.hide_all_quick_command_groups,
                add_quick_command=self.add_quick_command,
                edit_quick_command=self.edit_quick_command,
                delete_quick_command=self.delete_quick_command,
                move_quick_command=self.move_quick_command,
                reorder_quick_commands=lambda command_ids, selected_id="": self.reorder_quick_commands(
                    command_ids,
                    selected_id=selected_id,
                ),
                import_quick_commands_csv=self.import_quick_commands_csv,
                export_quick_commands_csv=self.export_quick_commands_csv,
                quick_files_supplier=self.quick_files_snapshot,
                visible_quick_files_supplier=self.visible_quick_files_snapshot,
                quick_file_sort_mode_supplier=self.quick_file_sort_mode_snapshot,
                set_quick_file_sort_mode=self.set_quick_file_sort_mode,
                add_quick_file=self.add_quick_file,
                edit_quick_file=self.edit_quick_file,
                delete_quick_file=self.delete_quick_file,
                move_quick_file=self.move_quick_file,
                reorder_quick_files=lambda quick_file_ids, selected_id="", force_custom=False: self.reorder_quick_files(
                    quick_file_ids,
                    selected_id=selected_id,
                    force_custom=force_custom,
                ),
                import_quick_files_csv=self.import_quick_files_csv,
                export_quick_files_csv=self.export_quick_files_csv,
            ),
            run_target_service=self.command_file_runs.target_service,
            theme_palette=self.theme,
            workspace_drawer_page_callback=self.request_drawer_page,
            workspace_drawer_width_callback=lambda width, source: self.set_drawer_width(width, source=source),
            embedded=True,
            show_run_button=False,
            show_workspace_side_panel=True,
            parent=self.tabs,
        )
        editor.apply_drawer_state(
            self.settings.drawer_collapsed,
            self.settings.drawer_width,
            self.settings.drawer_page_index,
        )
        editor.apply_editor_font(self.editor_font())
        if state is not None:
            if state.text or state.dirty or not state.path:
                editor.restore_text(state.text, dirty=state.dirty)
            if state.path:
                editor.path = Path(state.path)
                editor.update_window_state()
                editor.update_validation_status()
        editor.stateChanged.connect(self.update_tab_titles)
        editor.stateChanged.connect(self.sync_status_from_current_session)
        index = self.tabs.addTab(
            editor,
            standard_icon(QStyle.StandardPixmap.SP_FileIcon),
            editor.tab_title(),
        )
        self.tab_workspace.attach_tab_close_button(index, editor)
        self.tabs.setCurrentIndex(index)
        self.update_tab_titles()
        self.refresh_command_file_targets()
        self.save_settings()
        return editor

    def run_command_editor_buffer(self, text: str, path: Path | None) -> None:
        session = self.current_session()
        if not session:
            self.set_status("No active session to run command file.")
            return
        label = str(path) if path is not None else "editor buffer"
        session.run_script_text(text, source_label=label, source_path=path)

    def connected_terminal_sessions(self) -> list[TerminalSessionWidget]:
        return cast(list[TerminalSessionWidget], self.command_file_runs.connected_sessions())

    def command_file_run_targets(self) -> list[CommandRunTarget]:
        return self.command_file_runs.run_targets()

    def session_by_id(self, session_id: int) -> TerminalSessionWidget | None:
        return cast(TerminalSessionWidget | None, self.command_file_runs.session_by_id(session_id))

    def run_command_file_request_in_terminal_by_id(self, request: CommandRunRequest, session_id: int) -> bool:
        return self.command_file_runs.run_request_in_target(request, session_id)

    def run_editor_in_terminal_by_id(self, editor: CommandFileEditorDialog, session_id: int) -> None:
        self.command_file_runs.run_editor_in_target_by_id(editor, session_id)

    def refresh_command_file_targets(self) -> None:
        self.command_file_runs.refresh_editor_targets()

    def populate_run_editor_menu(self, menu: QMenu, editor: CommandFileEditorDialog | None = None) -> None:
        self.command_file_runs.populate_run_menu(menu, editor)

    def run_editor_in_terminal(self, editor: CommandFileEditorDialog, session: TerminalSessionWidget) -> None:
        self.command_file_runs.run_editor_in_target(editor, session)

    def _focus_session_tab(self, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(session) < 0:
            return
        self.tabs.setCurrentWidget(session)

    def show_find_in_current_tab(self) -> None:
        editor = self.current_command_file_editor()
        if editor:
            editor.show_find_bar()
            return
        session = self.current_session()
        if session:
            session.show_search()
            return
        self.set_status("No active tab to search.")

    def show_replace_in_current_tab(self) -> None:
        editor = self.current_command_file_editor()
        if editor:
            editor.show_replace_bar()
            return
        self.set_status("Replace is available in command-file editor tabs.")

    def command_palette_entries(self) -> list[CommandPaletteEntry]:
        return [
            *self.command_registry.palette_entries(),
            *workspace_tab_palette_entries(
                tab_count=self.tabs.count(),
                session_at=self.session_at,
                command_file_editor_at=self.command_file_editor_at,
                tab_text=self.tabs.tabText,
                activate_tab=self.tabs.setCurrentIndex,
            ),
        ]

    def show_tab_context_menu(self, position) -> None:
        self.tab_context_menus.show(position)

    def build_tab_context_menu(self, index: int) -> QMenu:
        return self.tab_context_menus.build(index)

    def restore_sessions(self, *, prompt_first_settings: bool = True) -> None:
        self.workspace_state_service.restore_from_settings(
            self.settings,
            self,
            prompt_first_settings=prompt_first_settings,
        )

    def add_session(self, state: TerminalSessionState | None = None, *, prompt_settings: bool = True) -> None:
        self._session_counter += 1
        state = state or TerminalSessionState(title=f"Terminal {self._session_counter}")
        session = TerminalSessionWidget(self, self._session_counter, state)
        index = self.tabs.addTab(
            session,
            standard_icon(QStyle.StandardPixmap.SP_ComputerIcon),
            session.tab_title,
        )
        self.tab_workspace.attach_tab_close_button(index, session)
        self.tabs.setCurrentIndex(index)
        self.update_tab_titles()
        if prompt_settings:
            self.prompt_session_settings(session)
        if state.connected_on_launch and session.profile.port:
            QTimer.singleShot(0, lambda target=session: self.restore_session_connection(target))

    def restore_session_connection(self, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(session) < 0 or session.serial_client.is_connected:
            return
        if session.profile_port_missing():
            message = f"{session.profile.port} is not currently detected. Auto-connect skipped."
            session._append_status(message)
            session._update_connection_ui(False)
            self.set_status(message)
            return
        self.set_status(f"Connecting to {session.profile.port}...")
        session.serial_client.connect(session.profile)
        session._update_connection_ui(session.serial_client.is_connected)

    def prompt_current_session_settings(self) -> None:
        session = self.current_session()
        if session:
            self.prompt_session_settings(session)

    def prompt_session_settings(self, session: TerminalSessionWidget) -> None:
        QTimer.singleShot(0, lambda: self._open_prompted_session_settings(session))

    def _open_prompted_session_settings(self, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(session) < 0:
            return
        self.tabs.setCurrentWidget(session)
        session.open_connection_settings(connect_after_accept=True)

    def duplicate_current_session(self) -> None:
        self.tab_workspace.duplicate_current_session()

    def duplicate_session(self, index: int) -> None:
        self.tab_workspace.duplicate_session(index)

    def close_current_session(self) -> None:
        self.tab_workspace.close_current_session()

    def close_session(self, index: int) -> bool:
        return self.tab_workspace.close_session(index)

    def confirm_close_command_file_tab(self, editor: CommandFileEditorDialog) -> bool:
        if not editor.is_dirty():
            return True
        message = QMessageBox(self)
        message.setWindowTitle("Close Command File")
        message.setText(f"Save changes to {editor.display_name()} before closing?")
        message.setIcon(QMessageBox.Icon.Warning)
        save_button = message.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = message.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        message.setDefaultButton(save_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is save_button:
            return editor.save()
        if clicked is discard_button:
            editor._dirty = False
            editor.update_window_state()
            return True
        return clicked is not cancel_button and False

    def close_other_sessions(self, index: int) -> None:
        self.tab_workspace.close_other_sessions(index)

    def close_sessions_to_right(self, index: int) -> None:
        self.tab_workspace.close_sessions_to_right(index)

    def rename_current_session(self) -> None:
        self.rename_session(self.tabs.currentIndex())

    def rename_session(self, index: int) -> None:
        session = self.session_at(index)
        if not session:
            return
        self.tabs.setCurrentIndex(index)
        current_title = self.tabs.tabText(index).strip() or session.tab_title
        title, accepted = QInputDialog.getText(self, "Rename Tab", "Tab name", text=current_title)
        if accepted and title.strip():
            session.title = title.strip()
            session.title_is_custom = True
            self.update_tab_titles()
            self.save_settings()

    def current_session(self) -> TerminalSessionWidget | None:
        return cast(TerminalSessionWidget | None, self.tab_workspace.current_session())

    def current_command_file_editor(self) -> CommandFileEditorDialog | None:
        return cast(CommandFileEditorDialog | None, self.tab_workspace.current_command_file_editor())

    def session_at(self, index: int) -> TerminalSessionWidget | None:
        return cast(TerminalSessionWidget | None, self.tab_workspace.session_at(index))

    def command_file_editor_at(self, index: int) -> CommandFileEditorDialog | None:
        return cast(CommandFileEditorDialog | None, self.tab_workspace.command_file_editor_at(index))

    def open_session_settings(self, index: int) -> None:
        self.tab_workspace.activate_session(
            index,
            lambda session: session.open_connection_settings(connect_after_accept=True),
        )

    def toggle_session_connection(self, index: int) -> None:
        self.tab_workspace.activate_session(index, lambda session: session.toggle_connection())

    def show_session_search(self, index: int) -> None:
        self.tab_workspace.activate_session(index, lambda session: session.show_search())

    def clear_session_terminal(self, index: int) -> None:
        self.tab_workspace.activate_session(index, lambda session: session.clear_terminal())

    def iter_sessions(self) -> list[TerminalSessionWidget]:
        return cast(list[TerminalSessionWidget], self.tab_workspace.iter_sessions())

    def iter_command_file_editors(self) -> list[CommandFileEditorDialog]:
        return cast(list[CommandFileEditorDialog], self.tab_workspace.iter_command_file_editors())

    def workspace_tab_count(self) -> int:
        return self.tab_workspace.workspace_tab_count()

    def with_session(self, callback) -> None:
        self.tab_workspace.with_current_session(callback)

    def update_tab_titles(self) -> None:
        self.workspace_status.update_tab_titles(self.theme)

    def sync_status_from_current_session(self) -> None:
        self.apply_drawer_state_to_current_tab()
        self.workspace_status.sync_from_current(self.theme)

    def connection_state_color(self, state: str) -> str:
        return connection_state_color(state, self.theme)

    def connection_status_action_clicked(self) -> None:
        session = self.current_session()
        if session:
            session.toggle_connection()

    def open_current_connection_settings(self) -> None:
        session = self.current_session()
        if session:
            session.open_connection_settings(connect_after_accept=True)

    def update_connection_status(self, session: TerminalSessionWidget | None = None) -> None:
        self.refresh_command_file_targets()
        self.workspace_status.update_connection_status(session or self.current_session(), self.theme)

    def set_status(self, text: str) -> None:
        self.workspace_status.set_status(text)

    def toggle_drawer(self) -> None:
        self.set_drawer_collapsed(not self.settings.drawer_collapsed)

    def normalized_drawer_page_index(self, index: int | None = None) -> int:
        page_index = self.settings.drawer_page_index if index is None else index
        return max(0, min(int(page_index), 1))

    def apply_drawer_state_to_current_tab(self) -> None:
        widget = self.tabs.currentWidget()
        if hasattr(widget, "apply_drawer_state"):
            widget.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
                self.normalized_drawer_page_index(),
            )

    def apply_drawer_state_to_tabs(self, *, source=None) -> None:
        page_index = self.normalized_drawer_page_index()
        for session in self.iter_sessions():
            if session is not source:
                session.apply_drawer_state(
                    self.settings.drawer_collapsed,
                    self.settings.drawer_width,
                    page_index,
                )
        for editor in self.iter_command_file_editors():
            if editor is not source:
                editor.apply_drawer_state(
                    self.settings.drawer_collapsed,
                    self.settings.drawer_width,
                    page_index,
                )

    def request_drawer_page(self, index: int) -> None:
        index = self.normalized_drawer_page_index(index)
        if not self.settings.drawer_collapsed and self.normalized_drawer_page_index() == index:
            self.set_drawer_collapsed(True)
            return
        self.set_drawer_page(index)
        if self.settings.drawer_collapsed:
            self.set_drawer_collapsed(False)

    def set_drawer_page(self, index: int) -> None:
        self.settings.drawer_page_index = self.normalized_drawer_page_index(index)
        self.apply_drawer_state_to_tabs()
        self.save_settings()

    def set_drawer_collapsed(self, collapsed: bool) -> None:
        self.settings.drawer_collapsed = collapsed
        self.apply_drawer_state_to_tabs()
        self.save_settings()

    def set_drawer_width(self, width: int, *, source=None) -> None:
        self.settings.drawer_width = max(220, min(width, 520))
        self.apply_drawer_state_to_tabs(source=source)
        if not self._loading:
            self.save_settings()

    def change_font_size(self, delta: int) -> None:
        self.settings.terminal_font_size = max(
            TERMINAL_FONT_MIN,
            min(self.settings.terminal_font_size + delta, TERMINAL_FONT_MAX),
        )
        self.apply_terminal_font_settings()
        self.save_settings()

    def show_terminal_font_settings(self) -> None:
        dialog = TerminalFontSettingsDialog(
            self.settings.terminal_font_family,
            self.settings.terminal_font_size,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.terminal_font_family = dialog.selected_family()
        self.settings.terminal_font_size = dialog.selected_size()
        self.apply_terminal_font_settings()
        self.save_settings()

    def apply_terminal_font_settings(self) -> None:
        for session in self.iter_sessions():
            session.apply_settings()
        for editor in self.iter_command_file_editors():
            editor.apply_editor_font(self.editor_font())

    def toggle_timestamps(self) -> None:
        self.settings.timestamps_enabled = self.timestamps_action.isChecked()
        self.save_settings()

    def toggle_line_wrap(self) -> None:
        self.settings.line_wrap_enabled = self.wrap_action.isChecked()
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def set_receive_display_mode(self, mode: str) -> None:
        if mode not in RECEIVE_DISPLAY_MODES:
            mode = "Text"
        if self.settings.receive_display_mode == mode:
            return
        self.settings.receive_display_mode = mode
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def default_serial_profile(self) -> SerialProfile:
        return clone_profile(self.settings.serial)

    def apply_settings_to_ui(self) -> None:
        self.apply_theme(self.settings.theme, save=False)
        if hasattr(self, "timestamps_action"):
            self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        if hasattr(self, "wrap_action"):
            self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        for session in self.iter_sessions():
            session.controller.replace_history(self.history_catalog.all_commands())
            session.history_store = session.controller.history_store
            session.apply_settings()
            session.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
                self.settings.drawer_page_index,
            )
            session.refresh_quick_commands()
            session.refresh_quick_files()
        for editor in self.iter_command_file_editors():
            editor.apply_editor_font(self.editor_font())
            editor.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
                self.settings.drawer_page_index,
            )
        self.update_tab_titles()
        self.sync_status_from_current_session()

    def quick_command_by_id(self, command_id: str) -> QuickCommand | None:
        return self.quick_action_controller.quick_command_by_id(command_id)

    def quick_file_by_id(self, quick_file_id: str) -> QuickFile | None:
        return self.quick_action_controller.quick_file_by_id(quick_file_id)

    def quick_command_group_names(self) -> list[str]:
        return self.quick_action_controller.quick_command_group_names()

    def set_quick_command_sort_mode(self, mode: str) -> None:
        self.quick_action_controller.set_quick_command_sort_mode(mode)

    def set_quick_file_sort_mode(self, mode: str) -> None:
        self.quick_action_controller.set_quick_file_sort_mode(mode)

    def set_quick_command_group_visible(self, group: str, visible: bool) -> None:
        self.quick_action_controller.set_quick_command_group_visible(group, visible)

    def show_all_quick_command_groups(self) -> None:
        self.quick_action_controller.show_all_quick_command_groups()

    def hide_all_quick_command_groups(self) -> None:
        self.quick_action_controller.hide_all_quick_command_groups()

    def add_quick_command(self, command: QuickCommand | None = None) -> None:
        self.quick_action_controller.add_quick_command(command)

    def edit_quick_command(self, command_id: str) -> None:
        self.quick_action_controller.edit_quick_command(command_id)

    def duplicate_quick_command(self, command_id: str) -> None:
        self.quick_action_controller.duplicate_quick_command(command_id)

    def delete_quick_command(self, command_id: str) -> None:
        self.quick_action_controller.delete_quick_command(command_id)

    def copy_quick_command_text(self, command_id: str) -> None:
        self.quick_action_controller.copy_quick_command_text(command_id)

    def add_quick_file(self, quick_file: QuickFile | None = None) -> None:
        self.quick_action_controller.add_quick_file(quick_file)

    def edit_quick_file(self, quick_file_id: str) -> None:
        self.quick_action_controller.edit_quick_file(quick_file_id)

    def delete_quick_file(self, quick_file_id: str) -> None:
        self.quick_action_controller.delete_quick_file(quick_file_id)

    def show_quick_file_in_explorer(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        path = Path(quick_file.path)
        self.show_path_in_explorer(path)

    def show_path_in_explorer(self, path: Path | None) -> None:
        if path is None:
            return
        if not path.exists():
            QMessageBox.warning(self, "Quick File", f"File not found:\n{path}")
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as exc:
            QMessageBox.warning(self, "Quick File", str(exc))

    def open_quick_file_editor(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        self.open_command_file_editor(Path(quick_file.path))

    def edit_selected_quick_file_content(self) -> None:
        session = self.current_session()
        if not session:
            return
        self.open_quick_file_editor(session.selected_quick_file_id())

    def import_quick_commands_csv(self) -> None:
        self.quick_action_controller.import_quick_commands_csv()

    def export_quick_commands_csv(self) -> None:
        self.quick_action_controller.export_quick_commands_csv()

    def import_quick_files_csv(self) -> None:
        self.quick_action_controller.import_quick_files_csv()

    def export_quick_files_csv(self) -> None:
        self.quick_action_controller.export_quick_files_csv()

    def import_quick_commands_from_csv(
        self,
        path: Path,
        *,
        options: QuickCommandImportOptions | None = None,
    ) -> QuickCommandImportResult:
        return self.quick_action_controller.import_quick_commands_from_csv(path, options=options)

    def export_quick_commands_to_csv(self, path: Path) -> int:
        return self.quick_action_controller.export_quick_commands_to_csv(path)

    def import_quick_files_from_csv(
        self,
        path: Path,
        *,
        options: QuickFileImportOptions | None = None,
    ) -> QuickFileImportResult:
        return self.quick_action_controller.import_quick_files_from_csv(path, options=options)

    def export_quick_files_to_csv(self, path: Path) -> int:
        return self.quick_action_controller.export_quick_files_to_csv(path)

    def move_quick_command(self, command_id: str, direction: int) -> None:
        self.quick_action_controller.move_quick_command(command_id, direction)

    def move_quick_file(self, quick_file_id: str, direction: int) -> None:
        self.quick_action_controller.move_quick_file(quick_file_id, direction)

    def reorder_quick_commands(self, command_ids: list[str], *, selected_id: str = "") -> None:
        self.quick_action_controller.reorder_quick_commands(command_ids, selected_id=selected_id)

    def reorder_quick_files(
        self,
        quick_file_ids: list[str],
        *,
        selected_id: str = "",
        force_custom: bool = False,
    ) -> None:
        self.quick_action_controller.reorder_quick_files(
            quick_file_ids,
            selected_id=selected_id,
            force_custom=force_custom,
        )

    def refresh_quick_commands_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_commands(selected_id)
        for editor in self.iter_command_file_editors():
            editor.sources = self.command_editor_sources()
            editor.highlighter.sources = editor.sources
            editor._refresh_completion_model()
            editor.highlighter.rehighlight()
            editor.update_validation_status()
            editor.refresh_workspace_side_panel()

    def refresh_quick_files_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_files(selected_id)
        for editor in self.iter_command_file_editors():
            editor.refresh_workspace_side_panel()

    def record_command(self, command: str) -> None:
        self.history_catalog.add(command)
        for session in self.iter_sessions():
            session.history_store.add(command)
            session._update_completion_model()
        self.save_settings()

    def remove_command_from_history(self, command: str) -> bool:
        removed = self.history_catalog.remove(command)
        for session in self.iter_sessions():
            session.history_store.remove(command)
            session._update_completion_model()
        if removed:
            self.save_settings()
        return removed

    def _confirm_bulk_delete(self, title: str, message: str, *, confirm: bool = True) -> bool:
        if not confirm:
            return True
        return (
            QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def clear_command_history(self, *, confirm: bool = True) -> bool:
        count = len(self.history_catalog.all_commands())
        if count == 0:
            self.set_status("Command history is already empty.")
            return False
        if not self._confirm_bulk_delete(
            "Clear Command History",
            f"Delete all {count} command history entr{'y' if count == 1 else 'ies'}?\n\n"
            "Quick Commands are not affected.",
            confirm=confirm,
        ):
            return False
        self.history_catalog.clear()
        for session in self.iter_sessions():
            session.history_store.clear()
            session._update_completion_model()
        self.save_settings()
        self.set_status(f"Cleared {count} command history entr{'y' if count == 1 else 'ies'}.")
        return True

    def delete_all_quick_commands(self, *, confirm: bool = True) -> bool:
        return self.quick_action_controller.delete_all_quick_commands(confirm=confirm)

    def delete_all_quick_files(self, *, confirm: bool = True) -> bool:
        return self.quick_action_controller.delete_all_quick_files(confirm=confirm)

    def show_app_settings_transfer_dialog(self) -> None:
        self.app_settings_controller.show_transfer_dialog()

    def confirm_app_settings_transfer(self, mode: str) -> bool:
        return self.app_settings_controller.confirm_transfer(mode)

    def import_settings(self, *, show_explanation: bool = True) -> None:
        self.app_settings_controller.import_settings(show_explanation=show_explanation)

    def export_settings(self, *, show_explanation: bool = True) -> None:
        self.app_settings_controller.export_settings(show_explanation=show_explanation)

    def load_settings_from_json(self, path: Path) -> AppSettings:
        return self.app_settings_controller.load_settings_from_json(path)

    def export_settings_to_json(self, path: Path) -> None:
        self.app_settings_controller.export_settings_to_json(path)

    def apply_imported_settings(
        self,
        settings: AppSettings,
    ) -> None:
        self.workspace_settings_controller.apply_imported_settings(settings)

    def _set_settings(self, settings: AppSettings) -> None:
        self.settings = settings

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading

    def _clear_workspace_for_settings_apply(self) -> None:
        for index in range(self.tabs.count() - 1, -1, -1):
            session = self.session_at(index)
            if session:
                session.shutdown()
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            if widget:
                widget.deleteLater()

    def _rebuild_runtime_state_from_settings(self, settings: AppSettings) -> None:
        self.quick_actions = self._quick_action_library_from_settings()
        self.history_catalog = HistoryStore(settings.command_history)
        self.theme = THEMES.get(settings.theme, THEMES["VS Code Dark"])
        self.resize(settings.window_width, settings.window_height)

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "About ComPort Zone",
            f"ComPort Zone\nVersion {__version__}\n\nCOM-port terminal for Windows device workflows.",
        )

    def apply_theme(self, name: str, *, save: bool = True) -> None:
        self.theme = THEMES.get(name, THEMES["VS Code Dark"])
        self.settings.theme = self.theme.name
        self.setStyleSheet(self._stylesheet(self.theme))
        for editor in self.iter_command_file_editors():
            editor.apply_theme_palette(self.theme)
        for session in self.iter_sessions():
            session.apply_theme_palette()
        for theme_name, action in getattr(self, "theme_actions", {}).items():
            action.setChecked(theme_name == self.theme.name)
        self.update_tab_titles()
        self.sync_status_from_current_session()
        if save:
            self.save_settings()

    def _stylesheet(self, theme: ThemePalette) -> str:
        terminal_background = "#0c0c0c" if theme.name in {"VS Code Dark", "Windows Terminal"} else theme.field
        return f"""
        QMainWindow, QWidget {{
            background: {theme.window};
            color: {theme.text};
        }}
        QMenuBar {{
            background: {theme.window};
            color: {theme.text};
            border-bottom: 1px solid {theme.border};
            padding-left: 4px;
        }}
        QMenuBar::item {{
            padding: 6px 11px;
            border-radius: 6px;
        }}
        QMenuBar::item:selected, QMenu {{
            background: {theme.surface_alt};
        }}
        QMenu {{
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 30px 7px 24px;
            border-radius: 6px;
        }}
        QMenu::item:selected {{
            background: {theme.accent_soft};
        }}
        QTabWidget::pane {{
            border: none;
        }}
        QTabBar::tab {{
            background: {theme.surface_alt};
            color: {theme.text};
            padding: 8px 8px 8px 16px;
            min-width: 130px;
            border: 1px solid transparent;
            border-top-left-radius: 9px;
            border-top-right-radius: 9px;
            margin: 5px 2px 0 2px;
        }}
        QTabBar::tab:selected {{
            background: {theme.window};
            border-top: 2px solid {theme.accent};
            border-left: 1px solid {theme.border};
            border-right: 1px solid {theme.border};
        }}
        QTabBar::tab:hover:!selected {{
            background: {theme.surface};
        }}
        QToolButton#newTabButton {{
            background: {theme.surface_alt};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            font-size: 13pt;
            padding: 0;
        }}
        QToolButton#newTabButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QToolButton#tabCloseButton {{
            background: transparent;
            color: {theme.muted};
            border: 1px solid transparent;
            border-radius: 7px;
            padding: 0;
            margin-right: 2px;
        }}
        QToolButton#tabCloseButton:hover {{
            background: {theme.surface};
            border-color: {theme.border};
        }}
        QToolButton#tabCloseButton:pressed {{
            background: {theme.accent_soft};
            border-color: {theme.accent};
        }}
        QFrame#drawer {{
            background: {theme.window_alt};
            border-right: 1px solid {theme.border};
        }}
        QFrame#drawerRail {{
            background: {theme.surface_alt};
            border-right: 1px solid {theme.border};
        }}
        QToolButton#railButton {{
            background: transparent;
            color: {theme.text};
            border: 1px solid transparent;
            border-radius: 10px;
        }}
        QToolButton#railButton:hover {{
            background: {theme.surface};
            border-color: {theme.border};
        }}
        QToolButton#railButton:pressed {{
            background: {theme.accent_soft};
            border-color: {theme.accent};
        }}
        QFrame#drawerPanel {{
            background: {theme.window_alt};
        }}
        QFrame#editorSidePanel {{
            background: {theme.window_alt};
            border-right: 1px solid {theme.border};
        }}
        QLabel#drawerTitle {{
            font-weight: 650;
            color: {theme.text};
            padding: 1px 2px 4px 2px;
        }}
        QLabel#drawerSection {{
            color: {theme.muted};
            font-size: 8pt;
            font-weight: 700;
            padding: 9px 3px 1px 3px;
        }}
        QLabel#drawerHelpText {{
            color: {theme.muted};
            line-height: 1.3;
            padding: 2px 3px 6px 3px;
        }}
        QFrame#terminalColumn, QTextEdit#terminal {{
            background: {terminal_background};
            color: {theme.text};
            border: none;
        }}
        QFrame#commandBar, QFrame#searchBar {{
            background: {theme.window};
            border-top: 1px solid {theme.border};
        }}
        QLabel#connectionStatus {{
            background: {theme.chip};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 7px;
            padding: 3px 9px;
        }}
        QLabel#connectionStatus[state="connected"] {{
            color: {theme.rx};
            border-color: {theme.rx};
        }}
        QLabel#connectionStatus[state="retrying"] {{
            color: {theme.status};
            border-color: {theme.status};
        }}
        QLabel#connectionStatus[state="missing"] {{
            color: {theme.error};
            border-color: {theme.error};
        }}
        QLabel#connectionStatus[state="no-port"] {{
            color: {theme.muted};
            border-color: {theme.border};
        }}
        QLineEdit, QComboBox, QListWidget {{
            background: {theme.field};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 9px;
            selection-background-color: {theme.search_highlight};
        }}
        QPlainTextEdit#commandFileEditor {{
            background: {terminal_background};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 0px;
            selection-background-color: {theme.search_highlight};
        }}
        QLabel#editorPathLabel, QLabel#editorStatusLabel {{
            color: {theme.muted};
            padding: 4px 2px;
        }}
        QLineEdit:focus, QComboBox:focus, QListWidget:focus {{
            border-color: {theme.accent};
        }}
        QListWidget {{
            outline: none;
        }}
        QListWidget::item {{
            border-radius: 7px;
            padding: 7px 8px;
            margin: 2px;
        }}
        QListWidget::item:hover {{
            background: {theme.surface};
        }}
        QListWidget::item:selected {{
            background: {theme.accent_soft};
            color: {theme.text};
        }}
        QListWidget#quickCommandList,
        QListWidget#quickFileList {{
            padding: 4px;
        }}
        QListWidget#quickCommandList::item,
        QListWidget#quickFileList::item {{
            border-radius: 5px;
            padding: 3px 6px;
            margin: 1px 0;
        }}
        QDialog {{
            background: {theme.window};
            color: {theme.text};
        }}
        QLabel#dialogTitle {{
            font-size: 13pt;
            font-weight: 700;
            color: {theme.text};
        }}
        QLabel#dialogHint {{
            background: {theme.surface_alt};
            color: {theme.muted};
            border: 1px solid {theme.border};
            border-radius: 10px;
            padding: 10px;
        }}
        QDialog#commandPalette {{
            background: {theme.window};
            color: {theme.text};
        }}
        QLineEdit#commandPaletteSearch {{
            font-size: 11pt;
            padding: 10px 12px;
            border-radius: 10px;
        }}
        QListWidget#commandPaletteList {{
            padding: 6px;
            border-radius: 10px;
        }}
        QListWidget#commandPaletteList::item {{
            border-radius: 8px;
            padding: 7px 10px;
            margin: 2px;
        }}
        QLabel#commandPaletteHint {{
            color: {theme.muted};
            padding: 0 4px;
        }}
        QComboBox {{
            padding-right: 28px;
        }}
        QComboBox::drop-down {{
            width: 26px;
            border-left: 1px solid {theme.border};
            background: {theme.surface_alt};
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
        }}
        QPushButton {{
            background: {theme.surface_alt};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 11px;
        }}
        QPushButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QPushButton:pressed {{
            background: {theme.accent_soft};
        }}
        QPushButton[role="accent"] {{
            background: {theme.accent};
            color: #ffffff;
            border-color: {theme.accent};
        }}
        QPushButton#drawerActionButton {{
            text-align: left;
            border-radius: 9px;
            padding: 8px 10px;
        }}
        QPushButton#drawerActionButton[role="drawerPrimary"] {{
            background: {theme.chip};
            border-color: {theme.accent_soft};
        }}
        QPushButton#drawerActionButton[role="drawerPrimary"]:hover {{
            background: {theme.accent_soft};
            border-color: {theme.accent};
        }}
        QPushButton#drawerActionButton[role="drawerDanger"]:hover {{
            background: {theme.surface};
            border-color: {theme.error};
        }}
        QToolButton#drawerMenuButton {{
            background: {theme.field};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 9px;
        }}
        QToolButton#drawerMenuButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QToolButton#drawerMenuButton::menu-indicator {{
            image: none;
            width: 0px;
        }}
        QSplitter::handle {{
            background: {theme.border};
        }}
        QSplitter::handle:hover {{
            background: {theme.accent};
        }}
        QSplashScreen {{
            color: {theme.text};
        }}
        QStatusBar {{
            background: {theme.window_alt};
            color: {theme.text};
            border-top: 1px solid {theme.border};
        }}
        QLabel#footer {{
            color: {theme.muted};
            padding-left: 4px;
        }}
        QPushButton#statusActionButton {{
            min-width: 92px;
            padding: 3px 10px;
            border-radius: 7px;
            background: {theme.surface_alt};
        }}
        QPushButton#statusActionButton[role="connected"] {{
            color: {theme.rx};
            border-color: {theme.rx};
        }}
        QPushButton#statusActionButton[role="retrying"] {{
            color: {theme.error};
            border-color: {theme.error};
        }}
        QPushButton#statusActionButton[role="missing"] {{
            color: {theme.error};
            border-color: {theme.error};
        }}
        QPushButton#statusActionButton[role="no-port"] {{
            color: {theme.muted};
        }}
        QPushButton#statusActionButton:hover {{
            border-color: {theme.accent};
        }}
        QLabel#versionInfo {{
            color: {theme.muted};
            padding: 0 8px;
        }}
        """

    def save_settings(self) -> None:
        self.workspace_settings_controller.save_settings()

    def closeEvent(self, event) -> None:
        for editor in self.iter_command_file_editors():
            if not self.confirm_close_command_file_tab(editor):
                event.ignore()
                return
        self.save_settings()
        for session in self.iter_sessions():
            session.shutdown()
        super().closeEvent(event)
