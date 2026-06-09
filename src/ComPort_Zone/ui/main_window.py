from __future__ import annotations

import subprocess
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import ClassVar, cast

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .. import quick_actions as _quick_actions
from ..quick_actions_panel import (
    item_ids_in_order,
    populate_quick_command_list,
    populate_quick_file_list,
    populate_quick_history_list,
    selected_item_id,
)
from ..quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions
from ..app_settings_controller import AppSettingsController
from ..command_editor import CommandEditorQuickActionCallbacks, CommandEditorSources, CommandFileEditorDialog
from ..command_registry import CommandPaletteEntry, CommandRegistry
from ..command_run_targets import CommandRunRequest, CommandRunTarget
from ..history import HistoryStore
from ..icons import retint_icons, set_icon_color, standard_icon
from ..models import (
    AppSettings,
    CommandFileTabState,
    LanProfile,
    QuickCommand,
    QuickFile,
    RECEIVE_DISPLAY_MODES,
    SerialProfile,
    TerminalSessionState,
    WorkspaceLayoutState,
    WorkspacePaneState,
    WorkspaceTabState,
)
from ..quick_action_controller import QuickActionController
from ..settings_service import SettingsService
from ..storage import SettingsStore, default_config_path
from ..themes import THEMES, ThemePalette
from ..version_check import (
    GITHUB_LATEST_RELEASE_API_URL,
    GITHUB_REPOSITORY_URL,
    VersionCheckResult,
    build_version_check_result,
    release_info_from_json,
)
from ..workspace_settings_controller import WorkspaceSettingsController
from ..workspace_state import WorkspaceStateService
from .command_file_targets import CommandFileRunCoordinator
from .command_palette_entries import workspace_tab_palette_entries
from .dialogs import CommandPaletteDialog, TerminalFontSettingsDialog, VersionUpdateDialog
from .fonts import TERMINAL_FONT_MAX, TERMINAL_FONT_MIN, pick_mono_font, pick_ui_font
from .main_window_menus import MainWindowMenuBuilder
from .split_workspace import SplitWorkspaceWidget
from .stylesheet import build_stylesheet
from .tab_workspace import TabWorkspaceController
from .title_bar import TitleBar, WindowResizeGrips, apply_rounded_corners
from .tokens import (
    DRAWER_COLLAPSE_AT,
    DRAWER_MAX_W,
    DRAWER_MIN_W,
    FONT_BTN_H,
    FONT_BTN_W,
    SPLITTER_HANDLE,
)
from .tab_context_menus import TabContextMenuBuilder
from .terminal_tab import DRAWER_COLLAPSED_WIDTH, TerminalSessionWidget
from .workspace_status import WorkspaceStatusPresenter, connection_state_color

APP_ICON_PATH = Path(__file__).resolve().parents[1] / "assets" / "comport-zone-icon.png"
QuickActionLibrary = _quick_actions.QuickActionLibrary
QuickCommandImportOptions = _quick_actions.QuickCommandImportOptions
QuickFileImportOptions = _quick_actions.QuickFileImportOptions


def clone_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def clone_lan_profile(profile: LanProfile) -> LanProfile:
    return LanProfile.from_dict(profile.to_dict())


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

    def __init__(self, *, defer_startup_actions: bool = False) -> None:
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
            workspace_layout_supplier=self.capture_workspace_layout,
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
        self.theme = THEMES.get(self.settings.theme, THEMES["ComPort Zone Dark"])
        self._session_counter = 0
        self._loading = True
        self._deferred_startup_actions_pending = defer_startup_actions
        self._deferred_startup_prompt_settings = (
            defer_startup_actions and self._should_prompt_first_session_settings()
        )
        self.version_check_network = QNetworkAccessManager(self)
        self._version_check_reply: QNetworkReply | None = None
        self._version_check_previous_status: str | None = None

        self.setWindowTitle("ComPort Zone")
        self.setWindowIcon(app_icon())
        self.setFont(pick_ui_font())
        # Frameless: the design ships a bespoke title bar; native drag/resize/snap is
        # re-delegated to the OS from ui/title_bar.py.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # Keep the floor low so the app fits small screens and a split workspace
        # (two panes) never forces the window past the screen edge. The tab strip no
        # longer pins a wide floor — a crowded strip collapses into the ⋯ overflow
        # menu (ui/tab_workspace.py) and the bar's minimum stays ≈ one tab — so the
        # window can shrink to where the command bar's controls run out of room.
        self.setMinimumSize(460, 440)
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
        self.restore_sessions(prompt_first_settings=not defer_startup_actions)
        self.refresh_shared_drawer()
        self._apply_shared_drawer_state()
        self._loading = False
        self.set_status("Ready")
        if not defer_startup_actions:
            self._schedule_launch_update_check()

    def _build_ui(self) -> None:
        # --- frameless window chrome: a single VS Code-style title row carrying the
        # logo, the application menu bar, a centred command palette box, and the
        # Minimize/Maximize/Close buttons (the separate menu row is gone). ---
        self._app_menu_bar = QMenuBar(self)
        self.title_bar = TitleBar(self, APP_ICON_PATH)
        self.title_bar.attach_menu_bar(self._app_menu_bar)
        self.title_bar.commandPaletteRequested.connect(self.show_command_palette)
        self.setMenuWidget(self.title_bar)

        self.tabs = SplitWorkspaceWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.newTabRequested.connect(lambda: self.add_session(prompt_settings=True))
        self.tabs.newTabMenuRequested.connect(self.show_new_tab_button_context_menu)
        self.tabs.currentChanged.connect(lambda _: self.sync_status_from_current_session())
        self.tabs.tabContextMenuRequested.connect(self.show_tab_context_menu)
        self.tabs.tabMovedBetweenPanes.connect(self._tab_moved_between_panes)
        # The drawer is one shared full-height side bar to the left of the tabs
        # (the mockup's app-body: rail | side panel | main column). Its actions
        # dispatch to the active tab; per-tab drawers are hidden.
        self.shared_drawer = self._build_shared_drawer()
        self.central_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.central_splitter.setObjectName("centralSplitter")
        self.central_splitter.setChildrenCollapsible(False)
        self.central_splitter.setHandleWidth(SPLITTER_HANDLE)
        self.central_splitter.addWidget(self.shared_drawer)
        self.central_splitter.addWidget(self.tabs)
        self.central_splitter.setStretchFactor(0, 0)
        self.central_splitter.setStretchFactor(1, 1)
        self.central_splitter.splitterMoved.connect(self._shared_drawer_resized)
        self.setCentralWidget(self.central_splitter)

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
        self.font_status_label = QLabel("Font", self)
        self.font_status_label.setObjectName("statusFontControlsLabel")
        self.font_status_label.setToolTip("Terminal and editor font size")
        self.font_decrease_button = QPushButton("-", self)
        self.font_decrease_button.setObjectName("statusFontSizeButton")
        self.font_decrease_button.setFixedSize(QSize(FONT_BTN_W, FONT_BTN_H))
        self.font_decrease_button.setToolTip("Decrease terminal and editor font size")
        self.font_decrease_button.setAccessibleName("Decrease terminal and editor font size")
        self.font_decrease_button.clicked.connect(lambda: self.change_font_size(-1))
        self.font_increase_button = QPushButton("+", self)
        self.font_increase_button.setObjectName("statusFontSizeButton")
        self.font_increase_button.setFixedSize(QSize(FONT_BTN_W, FONT_BTN_H))
        self.font_increase_button.setToolTip("Increase terminal and editor font size")
        self.font_increase_button.setAccessibleName("Increase terminal and editor font size")
        self.font_increase_button.clicked.connect(lambda: self.change_font_size(1))
        self.version_label = QLabel(f"ComPort Zone v{__version__}", self)
        self.version_label.setObjectName("versionInfo")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.statusBar().addWidget(self.footer, 1)
        self.statusBar().addPermanentWidget(self.connection_status_label)
        self.statusBar().addPermanentWidget(self.connection_action_button)
        self.statusBar().addPermanentWidget(self.font_status_label)
        self.statusBar().addPermanentWidget(self.font_decrease_button)
        self.statusBar().addPermanentWidget(self.font_increase_button)
        self.statusBar().addPermanentWidget(self.version_label)

        # Native edge/corner resize for the frameless window.
        self._resize_grips = WindowResizeGrips(self)

    def menuBar(self) -> QMenuBar:
        # The menu bar lives inside the custom title-bar chrome (see _build_ui), so
        # both the menu builder and the test-suite read it through this override.
        bar = getattr(self, "_app_menu_bar", None)
        return bar if bar is not None else super().menuBar()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Round the frameless shell's outer corners to the subtle Win11 radius.
        # Applied on show (the native window is guaranteed to exist by now) and
        # re-applied on every show so it survives a platform-window recreation.
        apply_rounded_corners(self)
        # Restore the favourites splitter sizes once the drawer has a real height
        # (pixel-based sizes can't be applied during construction).
        if not getattr(self, "_favorites_sizes_restored", False):
            self._favorites_sizes_restored = True
            QTimer.singleShot(0, self._apply_favorites_splitter_sizes)

    def _apply_favorites_splitter_sizes(self) -> None:
        drawer = getattr(self, "shared_drawer", None)
        if drawer is None or drawer.favorites_splitter is None:
            return
        # Splitter sizes only matter when both panels are expanded.
        if drawer.favorites_panel.is_collapsed() or drawer.favorite_files_panel.is_collapsed():
            return
        splitter = drawer.favorites_splitter
        sizes = [int(size) for size in self.settings.favorites_splitter_sizes]
        if len(sizes) == splitter.count() and sum(sizes) > 0:
            splitter.setSizes(sizes)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.refresh_maximize_glyph()

    def _refresh_title_subtitle(self) -> None:
        if not hasattr(self, "title_bar"):
            return
        session = self.current_session()
        if session is None:
            self.title_bar.set_subtitle("")
            self.title_bar.set_live(False)
            return
        state = session.connection_state()
        segments = [part.strip() for part in session.connection_status_text().split("|") if part.strip()]
        if state == "connected":
            self.title_bar.set_subtitle(" · ".join(segments[:3]))
            self.title_bar.set_live(True)
        else:
            self.title_bar.set_subtitle(segments[0] if segments else "Disconnected")
            self.title_bar.set_live(False)

    # ------------------------------------------------------------------ #
    # Shared full-height side bar (one drawer for the whole window; its    #
    # actions dispatch to the active tab via use_quick_command_id, etc.).  #
    # ------------------------------------------------------------------ #
    def _build_shared_drawer(self) -> QuickActionsSidebar:
        drawer = QuickActionsSidebar(
            actions=QuickActionsSidebarActions(
                command_primary=self._shared_use_command,
                file_primary=self._shared_run_file,
                add_command=self.add_quick_command,
                edit_command=lambda: self.edit_quick_command(self._shared_command_id()),
                delete_command=lambda: self.delete_quick_command(self._shared_command_id()),
                move_command_up=lambda: self.move_quick_command(self._shared_command_id(), -1),
                move_command_down=lambda: self.move_quick_command(self._shared_command_id(), 1),
                import_commands=self.import_quick_commands_csv,
                export_commands=self.export_quick_commands_csv,
                add_file=self.add_quick_file,
                edit_file=lambda: self.edit_quick_file(self._shared_file_id()),
                delete_file=lambda: self.delete_quick_file(self._shared_file_id()),
                move_file_up=lambda: self.move_quick_file(self._shared_file_id(), -1),
                move_file_down=lambda: self.move_quick_file(self._shared_file_id(), 1),
                import_files=self.import_quick_files_csv,
                export_files=self.export_quick_files_csv,
                command_use_by_id=self.use_quick_command_id,
                command_favorite_toggle=self.set_quick_command_favorite,
                command_edit_by_id=self.edit_quick_command,
                command_delete_by_id=self.delete_quick_command,
                file_use_by_id=self.run_quick_file_id,
                file_open_by_id=self.open_quick_file_in_editor_id,
                file_favorite_toggle=self.set_quick_file_favorite,
                file_edit_by_id=self.edit_quick_file,
                file_delete_by_id=self.delete_quick_file,
                history_favorite=lambda text: self.add_saved_command_from_text(text, favorite=True),
                history_save=lambda text: self.add_saved_command_from_text(text, favorite=False),
                history_remove=self.remove_command_from_history,
                run_file=self.run_command_file_dialog,
            ),
            command_primary_label="Send",
            file_primary_label="Run",
            command_double_clicked=self._shared_use_command,
            file_double_clicked=self._shared_open_file,
            command_sort_changed=self._shared_command_sort_changed,
            file_sort_changed=self._shared_file_sort_changed,
            command_order_changed=self._shared_persist_command_order,
            file_order_changed=self._shared_persist_file_order,
            favorite_command_sort_changed=self._shared_favorite_command_sort_changed,
            favorite_file_sort_changed=self._shared_favorite_file_sort_changed,
            favorite_command_order_changed=self._shared_persist_favorite_command_order,
            favorite_file_order_changed=self._shared_persist_favorite_file_order,
            include_history=True,
            history_primary=self._shared_resend_history,
            settings_callback=self.show_command_palette,
            group_menu_provider=self._populate_group_menu,
            on_page_requested=self.request_drawer_page,
            rail_width=DRAWER_COLLAPSED_WIDTH,
            parent=self,
        )
        for group_button in (drawer.quick_group_button, drawer.favorite_group_button):
            group_menu = QMenu(group_button)
            group_menu.aboutToShow.connect(lambda m=group_menu: self._populate_group_menu(m))
            group_button.setMenu(group_menu)
        # Favorites page layout: collapse toggles + resize splitter, persisted.
        drawer.favorites_panel.collapseToggled.connect(self._persist_favorites_layout)
        drawer.favorite_files_panel.collapseToggled.connect(self._persist_favorites_layout)
        if drawer.favorites_splitter is not None:
            drawer.favorites_splitter.splitterMoved.connect(
                lambda *_: QTimer.singleShot(0, self._persist_favorites_layout)
            )
        self._apply_favorites_layout(drawer)
        self.drawer_rail = drawer.rail
        self.drawer_panel = drawer.panel
        self.drawer_pages = drawer.pages
        return drawer

    def _apply_favorites_layout(self, drawer=None) -> None:
        """Restore the saved collapse state onto the Favorites page (splitter sizes
        are applied later, once the drawer has a real height — see showEvent)."""
        drawer = drawer or getattr(self, "shared_drawer", None)
        if drawer is None:
            return
        drawer.favorites_panel.set_collapsed(self.settings.favorite_command_collapsed)
        drawer.favorite_files_panel.set_collapsed(self.settings.favorite_file_collapsed)
        self._update_favorites_fill_cap(drawer)

    def _update_favorites_fill_cap(self, drawer) -> None:
        """When both favourites panels are collapsed, cap the splitter to its two
        headers so the wrapper's top spacer pushes them to the bottom of the dock;
        otherwise let the splitter fill."""
        splitter = drawer.favorites_splitter
        if splitter is None:
            return
        both_collapsed = (
            drawer.favorites_panel.is_collapsed() and drawer.favorite_files_panel.is_collapsed()
        )
        if both_collapsed:
            cap = (
                drawer.favorites_panel.maximumHeight()
                + drawer.favorite_files_panel.maximumHeight()
                + splitter.handleWidth()
                + 4
            )
            splitter.setMaximumHeight(cap)
        else:
            splitter.setMaximumHeight(16_777_215)

    def _persist_favorites_layout(self, *_args) -> None:
        drawer = getattr(self, "shared_drawer", None)
        if drawer is None:
            return
        self.settings.favorite_command_collapsed = drawer.favorites_panel.is_collapsed()
        self.settings.favorite_file_collapsed = drawer.favorite_files_panel.is_collapsed()
        self._update_favorites_fill_cap(drawer)
        splitter = drawer.favorites_splitter
        both_expanded = (
            not drawer.favorites_panel.is_collapsed()
            and not drawer.favorite_files_panel.is_collapsed()
        )
        # Only a both-expanded layout is a real resize worth persisting.
        if splitter is not None and splitter.isVisible() and both_expanded:
            sizes = [int(size) for size in splitter.sizes()]
            if len(sizes) == splitter.count() and all(size > 0 for size in sizes):
                self.settings.favorites_splitter_sizes = sizes
        self.save_settings()

    def _shared_command_id(self) -> str:
        return selected_item_id(self.shared_drawer.quick_command_list)

    def _shared_file_id(self) -> str:
        return selected_item_id(self.shared_drawer.quick_file_list)

    def _shared_use_command(self) -> None:
        self.use_quick_command_id(self._shared_command_id())

    def _shared_run_file(self) -> None:
        self.run_quick_file_id(self._shared_file_id())

    def _shared_open_file(self) -> None:
        self.open_quick_file_in_editor_id(self._shared_file_id())

    def _shared_resend_history(self, command: str) -> None:
        session = self.current_session()
        if session is not None:
            session.resend_command(command)

    def _shared_command_sort_changed(self) -> None:
        mode = self.shared_drawer.quick_sort_combo.currentData()
        if mode:
            self.set_quick_command_sort_mode(str(mode))

    def _shared_file_sort_changed(self) -> None:
        mode = self.shared_drawer.quick_file_sort_combo.currentData()
        if mode:
            self.set_quick_file_sort_mode(str(mode))

    def _shared_persist_command_order(self) -> None:
        self.reorder_quick_commands(
            item_ids_in_order(self.shared_drawer.quick_command_list),
            selected_id=self._shared_command_id(),
        )

    def _shared_persist_file_order(self) -> None:
        self.reorder_quick_files(
            item_ids_in_order(self.shared_drawer.quick_file_list),
            selected_id=self._shared_file_id(),
            force_custom=True,
        )

    def _shared_favorite_command_id(self) -> str:
        return selected_item_id(self.shared_drawer.favorite_command_list)

    def _shared_favorite_file_id(self) -> str:
        return selected_item_id(self.shared_drawer.favorite_file_list)

    def _shared_favorite_command_sort_changed(self) -> None:
        mode = self.shared_drawer.favorite_sort_combo.currentData()
        if mode:
            self.set_favorite_command_sort_mode(str(mode))

    def _shared_favorite_file_sort_changed(self) -> None:
        mode = self.shared_drawer.favorite_file_sort_combo.currentData()
        if mode:
            self.set_favorite_file_sort_mode(str(mode))

    def _shared_persist_favorite_command_order(self) -> None:
        self.reorder_favorite_commands(
            item_ids_in_order(self.shared_drawer.favorite_command_list),
            selected_id=self._shared_favorite_command_id(),
        )

    def _shared_persist_favorite_file_order(self) -> None:
        self.reorder_favorite_files(
            item_ids_in_order(self.shared_drawer.favorite_file_list),
            selected_id=self._shared_favorite_file_id(),
        )

    def _populate_group_menu(self, menu) -> None:
        menu.clear()
        hidden = set(self.quick_command_hidden_groups_snapshot())
        for group in self.quick_command_group_names():
            action = menu.addAction(group)
            action.setCheckable(True)
            action.setChecked(group not in hidden)
            action.toggled.connect(
                lambda checked, g=group: (
                    self.set_quick_command_group_visible(g, checked),
                    self.refresh_quick_commands_everywhere(),
                )
            )
        menu.addSeparator()
        menu.addAction("Show all", lambda: (self.show_all_quick_command_groups(), self.refresh_quick_commands_everywhere()))
        menu.addAction("Hide all", lambda: (self.hide_all_quick_command_groups(), self.refresh_quick_commands_everywhere()))

    def refresh_shared_drawer(self) -> None:
        if not hasattr(self, "shared_drawer"):
            return
        populate_quick_command_list(
            self.shared_drawer.quick_command_list,
            self.visible_quick_commands_snapshot(),
            selected_id=self._shared_command_id(),
            label_limit=30,
            group_limit=10,
            draggable=True,
        )
        populate_quick_command_list(
            self.shared_drawer.favorite_command_list,
            self.favorite_quick_commands_snapshot(),
            selected_id=self._shared_favorite_command_id(),
            label_limit=30,
            group_limit=10,
            draggable=True,
        )
        populate_quick_file_list(
            self.shared_drawer.quick_file_list,
            self.visible_quick_files_snapshot(),
            selected_id=self._shared_file_id(),
            label_limit=30,
            draggable=True,
        )
        populate_quick_file_list(
            self.shared_drawer.favorite_file_list,
            self.favorite_quick_files_snapshot(),
            selected_id=self._shared_favorite_file_id(),
            label_limit=30,
            draggable=True,
        )
        self.refresh_shared_drawer_history()
        self._sync_shared_sort_combos()

    def refresh_shared_drawer_history(self) -> None:
        """Rebuild only the history list.

        Sending a command changes *history* and nothing else, so re-populating the
        (potentially huge) saved-command, favorites and files lists on every Enter is
        pure waste — with hundreds of saved commands that rebuild dominates the send
        latency. The send path calls this focused refresh instead of the full one."""
        if not hasattr(self, "shared_drawer"):
            return
        populate_quick_history_list(
            self.shared_drawer.quick_history_list,
            list(reversed(self.history_catalog.all_commands()))[:80],
            favorite_commands={command.command.strip() for command in self.favorite_quick_commands_snapshot()},
        )

    def _sync_shared_sort_combos(self) -> None:
        for combo, mode in (
            (self.shared_drawer.quick_sort_combo, self.quick_command_sort_mode_snapshot()),
            (self.shared_drawer.quick_file_sort_combo, self.quick_file_sort_mode_snapshot()),
            (self.shared_drawer.favorite_sort_combo, self.favorite_command_sort_mode_snapshot()),
            (self.shared_drawer.favorite_file_sort_combo, self.favorite_file_sort_mode_snapshot()),
        ):
            combo.blockSignals(True)
            index = combo.findData(mode)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        groups = self.quick_command_group_names()
        hidden = set(self.quick_command_hidden_groups_snapshot())
        visible = [g for g in groups if g not in hidden]
        label = "All" if len(visible) == len(groups) else f"{len(visible)}/{len(groups)}"
        for group_button in (
            self.shared_drawer.quick_group_button,
            self.shared_drawer.favorite_group_button,
        ):
            group_button.setToolTip(f"Quick command groups — showing {label}")

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
            favorite_command_order=self.settings.favorite_command_order,
            favorite_file_order=self.settings.favorite_file_order,
            favorite_command_sort_mode=self.settings.favorite_command_sort_mode,
            favorite_file_sort_mode=self.settings.favorite_file_sort_mode,
        )

    def _sync_quick_actions_to_settings(self) -> None:
        self.settings.quick_commands = list(self.quick_actions.quick_commands)
        self.settings.quick_files = list(self.quick_actions.quick_files)
        self.settings.quick_command_sort_mode = self.quick_actions.command_sort_mode
        self.settings.quick_command_hidden_groups = list(self.quick_actions.command_hidden_groups)
        self.settings.quick_file_sort_mode = self.quick_actions.file_sort_mode
        self.settings.favorite_command_order = list(self.quick_actions.favorite_command_order)
        self.settings.favorite_file_order = list(self.quick_actions.favorite_file_order)
        self.settings.favorite_command_sort_mode = self.quick_actions.favorite_command_sort_mode
        self.settings.favorite_file_sort_mode = self.quick_actions.favorite_file_sort_mode

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
                "Command Files (*.cpz *.txt *.cmd *.scr);;ComPort Zone Files (*.cpz);;All Files (*)",
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
                dispatch_quick_command=self.use_quick_command_id,
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
                dispatch_quick_file=self.use_quick_file_id,
            ),
            run_target_service=self.command_file_runs.target_service,
            theme_palette=self.theme,
            workspace_drawer_page_callback=self.request_drawer_page,
            workspace_drawer_width_callback=lambda width, source: self.set_drawer_width(width, source=source),
            command_palette_callback=self.show_command_palette,
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
        editor.apply_editor_font(self.editor_font(), self.settings.terminal_line_spacing)
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
        self.update_workspace_split_chrome()
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

    def show_new_tab_button_context_menu(self, global_position) -> None:
        self.tab_context_menus.show_empty_at(global_position)

    def build_tab_context_menu(self, index: int) -> QMenu:
        return self.tab_context_menus.build(index)

    def restore_sessions(self, *, prompt_first_settings: bool = True) -> None:
        self.workspace_state_service.restore_from_settings(
            self.settings,
            self,
            prompt_first_settings=prompt_first_settings,
        )

    def _should_prompt_first_session_settings(self) -> bool:
        return not self.settings.workspace_layout.panes and not self.settings.restored_tabs

    def run_startup_actions(self) -> None:
        if not self._deferred_startup_actions_pending:
            return
        self._deferred_startup_actions_pending = False
        QTimer.singleShot(0, self._run_deferred_startup_actions)

    def _run_deferred_startup_actions(self) -> None:
        if self._deferred_startup_prompt_settings:
            self._deferred_startup_prompt_settings = False
            session = self.current_session()
            if session:
                self._open_prompted_session_settings(session)
        self._schedule_launch_update_check()
        # Land the caret in the active tab's terminal/editor so the app is ready to
        # type the moment it opens — after any first-run settings dialog has closed.
        self.focus_active_tab_input()

    def focus_active_tab_input(self) -> None:
        """Give keyboard focus to the active tab's terminal/editor, caret at the end."""
        focus_input = getattr(self.tabs.currentWidget(), "focus_input", None)
        if callable(focus_input):
            focus_input()

    def _schedule_launch_update_check(self) -> None:
        if self.settings.check_for_updates_on_launch:
            QTimer.singleShot(0, lambda: self.check_for_updates(automatic=True))

    def configure_workspace_layout(self, layout: WorkspaceLayoutState) -> None:
        if len(layout.panes) < 2:
            self.tabs.join_panes()
            return
        orientation = Qt.Orientation.Vertical if layout.orientation == "vertical" else Qt.Orientation.Horizontal
        self.tabs.configure_layout(
            orientation=orientation,
            active_pane=layout.active_pane,
            splitter_sizes=layout.splitter_sizes,
        )

    def select_workspace_pane(self, pane_index: int) -> None:
        self.tabs.set_active_pane_index(pane_index)

    def finish_workspace_layout_restore(self, layout: WorkspaceLayoutState) -> None:
        panes = self.tabs.panes()
        for pane_index, pane_state in enumerate(layout.panes[:len(panes)]):
            pane = panes[pane_index]
            if pane.count():
                pane.setCurrentIndex(max(0, min(pane_state.active_tab, pane.count() - 1)))
        self.select_workspace_pane(layout.active_pane)
        self.sync_status_from_current_session()

    def capture_workspace_layout(self) -> WorkspaceLayoutState:
        panes: list[WorkspacePaneState] = []
        for pane in self.tabs.panes():
            tab_states: list[WorkspaceTabState] = []
            for local_index in range(pane.count()):
                widget = pane.widget(local_index)
                if isinstance(widget, TerminalSessionWidget):
                    tab_states.append(WorkspaceTabState(kind="terminal", terminal=widget.to_state()))
                elif isinstance(widget, CommandFileEditorDialog):
                    tab_states.append(
                        WorkspaceTabState(
                            kind="command_file",
                            command_file=self.workspace_state_service.command_file_state(widget),
                        )
                    )
            panes.append(WorkspacePaneState(tabs=tab_states, active_tab=max(0, pane.currentIndex())))
        active_pane = max(0, self.tabs.pane_index(self.tabs.active_pane()))
        orientation = "vertical" if self.tabs.splitter.orientation() == Qt.Orientation.Vertical else "horizontal"
        return WorkspaceLayoutState(
            orientation=orientation,
            panes=panes,
            active_pane=active_pane,
            splitter_sizes=self.tabs.splitter.sizes(),
        )

    def split_current_tab_right(self) -> None:
        self.split_tab_right(self.tabs.currentIndex())

    def split_tab_right(self, index: int) -> None:
        if self.tabs.move_tab_to_other_pane(index, orientation=Qt.Orientation.Horizontal):
            self.update_tab_titles()
            self.update_workspace_split_chrome()
            self.save_settings()

    def split_current_tab_down(self) -> None:
        self.split_tab_down(self.tabs.currentIndex())

    def split_tab_down(self, index: int) -> None:
        if self.tabs.move_tab_to_other_pane(index, orientation=Qt.Orientation.Vertical):
            self.update_tab_titles()
            self.update_workspace_split_chrome()
            self.save_settings()

    def move_tab_to_other_pane(self, index: int | None = None) -> None:
        target_index = self.tabs.currentIndex() if index is None else index
        if self.tabs.move_tab_to_other_pane(target_index):
            self.update_tab_titles()
            self.update_workspace_split_chrome()
            self.save_settings()

    def join_workspace_panes(self) -> None:
        if self.tabs.join_panes():
            self.update_tab_titles()
            self.update_workspace_split_chrome()
            self.save_settings()

    def _tab_moved_between_panes(self, widget, index: int) -> None:
        self.tab_workspace.attach_tab_close_button(index, widget)
        self.update_tab_titles()
        self.update_workspace_split_chrome()
        self.save_settings()

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
        self.update_workspace_split_chrome()
        if state.connected_on_launch and session.connection_endpoint():
            QTimer.singleShot(0, lambda target=session: self.restore_session_connection(target))

    def restore_session_connection(self, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(session) < 0 or session.transport.is_connected:
            return
        if session.profile_port_missing():
            message = f"{session.connection_endpoint()} is not currently detected. Auto-connect skipped."
            session._append_status(message)
            session._update_connection_ui(False)
            if self.tabs.currentWidget() is session:
                self.set_status(message)
            return
        if self.tabs.currentWidget() is session:
            self.set_status(f"Connecting to {session.connection_endpoint()}...")
        session.transport.connect(session.profile)
        session._update_connection_ui(session.transport.is_connected)

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
        # The input prompt echoes the tab name, so refresh it whenever a title
        # changes (endpoint connects, rename, …).
        for session in self.iter_sessions():
            sync = getattr(session, "_sync_prompt_context", None)
            if callable(sync):
                sync()

    def _set_workspace_tab_active_property(self, widget: QWidget, active: bool) -> None:
        targets = [widget]
        for object_name in ("terminal", "commandFileEditor", "terminalColumn"):
            targets.extend(widget.findChildren(QWidget, object_name))
        for target in targets:
            target.setProperty("activeWorkspaceTab", active)
            target.style().unpolish(target)
            target.style().polish(target)
            target.update()

    def update_workspace_split_chrome(self, *, drawer_source=None) -> None:
        active_widget = self.tabs.currentWidget()
        # The full-width gradient edge above the active tab only earns its keep when
        # the workspace is split — it marks *which* pane is active. With a single pane
        # there is nothing to disambiguate, so it stays hidden.
        is_split = getattr(self.tabs, "pane_count", lambda: 1)() > 1
        for ref in self.tabs.iter_tab_refs():
            widget = ref.widget
            # The side bar is a single shared drawer to the left of the tabs; the
            # per-tab drawers stay hidden so the tabs sit only over the terminal.
            if hasattr(widget, "set_workspace_drawer_visible"):
                widget.set_workspace_drawer_visible(False)
            self._set_workspace_tab_active_property(widget, is_split and widget is active_widget)
        self._apply_shared_drawer_state()
        terminal_owns_status = isinstance(active_widget, TerminalSessionWidget)
        # The shared connection chip/button are terminal-specific: terminals show
        # their own in the command bar, and editors are connectionless (their status
        # lives in the footer). Hide the shared widgets for both so the status line
        # is not duplicated or cut off while an editor tab is active.
        is_editor = isinstance(active_widget, CommandFileEditorDialog)
        show_shared_connection = not terminal_owns_status and not is_editor
        self.connection_status_label.setVisible(show_shared_connection)
        self.connection_action_button.setVisible(show_shared_connection)

    def sync_status_from_current_session(self) -> None:
        self.workspace_status.sync_from_current(self.theme)
        self.update_workspace_split_chrome()
        self._refresh_title_subtitle()

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
        # The shared status bar belongs to the selected tab; background tab
        # updates should refresh shared targets without replacing it.
        self.workspace_status.sync_from_current(self.theme)
        self.update_workspace_split_chrome()
        self._refresh_title_subtitle()

    def set_status(self, text: str) -> None:
        self.workspace_status.set_status(text)

    def toggle_drawer(self) -> None:
        self.set_drawer_collapsed(not self.settings.drawer_collapsed)

    def normalized_drawer_page_index(self, index: int | None = None) -> int:
        # Rail modes: All (0), Quick Send (1), Command Files (2), History (3).
        page_index = self.settings.drawer_page_index if index is None else index
        return max(0, min(int(page_index), 3))

    def apply_drawer_state_to_current_tab(self) -> None:
        self.update_workspace_split_chrome()

    def apply_drawer_state_to_tabs(self, *, source=None) -> None:
        self.update_workspace_split_chrome(drawer_source=source)

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
        self.settings.drawer_width = max(DRAWER_MIN_W, min(width, DRAWER_MAX_W))
        self.apply_drawer_state_to_tabs(source=source)
        if not self._loading:
            self.save_settings()

    def _apply_shared_drawer_state(self) -> None:
        if not hasattr(self, "shared_drawer"):
            return
        collapsed = self.settings.drawer_collapsed
        self.shared_drawer.select_page(self.normalized_drawer_page_index())
        self.shared_drawer.panel.setVisible(not collapsed)
        if collapsed:
            self.shared_drawer.setMinimumWidth(DRAWER_COLLAPSED_WIDTH)
            self.shared_drawer.setMaximumWidth(DRAWER_COLLAPSED_WIDTH)
            self.central_splitter.setSizes([DRAWER_COLLAPSED_WIDTH, max(200, self.width() - DRAWER_COLLAPSED_WIDTH)])
        else:
            width = max(DRAWER_MIN_W, min(self.settings.drawer_width, DRAWER_MAX_W))
            self.shared_drawer.setMinimumWidth(DRAWER_MIN_W)
            self.shared_drawer.setMaximumWidth(DRAWER_MAX_W)
            self.central_splitter.setSizes([width, max(200, self.width() - width)])

    def _shared_drawer_resized(self, pos: int, index: int) -> None:
        # Persist a manual drag of the side bar; auto-collapse below the floor.
        if self.settings.drawer_collapsed or self._loading:
            return
        sizes = self.central_splitter.sizes()
        if not sizes:
            return
        if sizes[0] < DRAWER_COLLAPSE_AT:
            self.set_drawer_collapsed(True)
            return
        self.settings.drawer_width = max(DRAWER_MIN_W, min(sizes[0], DRAWER_MAX_W))
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
            self.settings.terminal_line_spacing,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.terminal_font_family = dialog.selected_family()
        self.settings.terminal_font_size = dialog.selected_size()
        self.settings.terminal_line_spacing = dialog.selected_line_spacing()
        self.apply_terminal_font_settings()
        self.save_settings()

    def apply_terminal_font_settings(self) -> None:
        for session in self.iter_sessions():
            session.apply_settings()
        for editor in self.iter_command_file_editors():
            editor.apply_editor_font(self.editor_font(), self.settings.terminal_line_spacing)

    def toggle_timestamps(self) -> None:
        self.set_timestamps_enabled(self.timestamps_action.isChecked())

    def set_timestamps_enabled(self, enabled: bool) -> None:
        self.settings.timestamps_enabled = bool(enabled)
        if hasattr(self, "timestamps_action"):
            self.timestamps_action.blockSignals(True)
            self.timestamps_action.setChecked(self.settings.timestamps_enabled)
            self.timestamps_action.blockSignals(False)
        # Re-sync each tab so the command-bar timestamp toggles track the setting,
        # then re-render history so the detached timestamp column toggles for all.
        for session in self.iter_sessions():
            session.apply_settings()
            if hasattr(session, "rerender_transcript"):
                session.rerender_transcript()
        self.save_settings()

    def toggle_line_wrap(self) -> None:
        self.set_line_wrap_enabled(self.wrap_action.isChecked())

    def set_line_wrap_enabled(self, enabled: bool) -> None:
        self.settings.line_wrap_enabled = bool(enabled)
        if hasattr(self, "wrap_action"):
            self.wrap_action.blockSignals(True)
            self.wrap_action.setChecked(self.settings.line_wrap_enabled)
            self.wrap_action.blockSignals(False)
        # Re-apply so terminals re-wrap and every command-bar wrap toggle tracks it.
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def toggle_check_for_updates_on_launch(self) -> None:
        action = getattr(self, "check_for_updates_on_launch_action", None)
        checked = (
            bool(action.isChecked())
            if action is not None
            else not self.settings.check_for_updates_on_launch
        )
        self.settings.check_for_updates_on_launch = checked
        self.save_settings()
        self.set_status(
            "Will check for updates on launch."
            if checked
            else "Launch update checks disabled."
        )

    def set_receive_display_mode(self, mode: str) -> None:
        if mode not in RECEIVE_DISPLAY_MODES:
            mode = "Text"
        if self.settings.receive_display_mode == mode:
            return
        self.settings.receive_display_mode = mode
        for session in self.iter_sessions():
            session.apply_settings()
            if hasattr(session, "rerender_transcript"):
                session.rerender_transcript()
        self.save_settings()

    def default_serial_profile(self) -> SerialProfile:
        return clone_profile(self.settings.serial)

    def default_lan_profile(self) -> LanProfile:
        return clone_lan_profile(self.settings.lan)

    def apply_settings_to_ui(self) -> None:
        self.apply_theme(self.settings.theme, save=False)
        if hasattr(self, "timestamps_action"):
            self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        if hasattr(self, "wrap_action"):
            self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        if hasattr(self, "check_for_updates_on_launch_action"):
            self.check_for_updates_on_launch_action.setChecked(
                self.settings.check_for_updates_on_launch
            )
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
            editor.apply_editor_font(self.editor_font(), self.settings.terminal_line_spacing)
            editor.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
                self.settings.drawer_page_index,
            )
        self.refresh_shared_drawer()
        self._apply_shared_drawer_state()
        self.update_tab_titles()
        self.sync_status_from_current_session()

    def quick_command_by_id(self, command_id: str) -> QuickCommand | None:
        return self.quick_action_controller.quick_command_by_id(command_id)

    def quick_file_by_id(self, quick_file_id: str) -> QuickFile | None:
        return self.quick_action_controller.quick_file_by_id(quick_file_id)

    def use_quick_command_from_sidebar(self, source) -> None:
        selected_id = getattr(source, "selected_quick_command_id", lambda: "")()
        self.use_quick_command_id(selected_id)

    def use_quick_command_id(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        editor = self.current_command_file_editor()
        if editor is not None:
            text = f"HEX {command.command}" if command.send_mode == "Hex Bytes" else command.command
            editor.insert_text_at_cursor(text)
            return
        session = self.current_session()
        if session is not None:
            session.send_quick_command(command)

    def use_quick_file_from_sidebar(self, source) -> None:
        selected_id = getattr(source, "selected_quick_file_id", lambda: "")()
        self.use_quick_file_id(selected_id)

    def use_quick_file_id(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        path = Path(quick_file.path)
        editor = self.current_command_file_editor()
        if editor is not None:
            if editor.confirm_save_or_discard_if_dirty():
                editor.load_path(path)
            return
        session = self.current_session()
        if session is not None:
            session.run_script_path(path)

    def run_quick_file_id(self, quick_file_id: str) -> None:
        """Run a quick file in a terminal (the row's play affordance). Falls back to
        the first terminal when the active tab is an editor."""
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        session = self.current_session() or next(iter(self.iter_sessions()), None)
        if session is not None:
            session.run_script_path(Path(quick_file.path))

    def open_quick_file_in_editor_id(self, quick_file_id: str) -> None:
        """Open a quick file in the active editor, or a new one when none is active
        (the row's double-click)."""
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        path = Path(quick_file.path)
        editor = self.current_command_file_editor()
        if editor is not None:
            if editor.confirm_save_or_discard_if_dirty():
                editor.load_path(path)
            return
        self.add_command_file_tab(path=path)

    def run_command_file_dialog(self) -> None:
        """Pick and run a command file in the active terminal without saving it as a
        quick file (the Quick Files ⋯ "Run file…" action)."""
        session = self.current_session() or next(iter(self.iter_sessions()), None)
        if session is not None:
            session.run_script()

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

    # --- Favorites (a subset of saved commands flagged ``favorite``) ----------
    def favorite_quick_commands_snapshot(self) -> list[QuickCommand]:
        return self.quick_action_controller.favorite_quick_commands_snapshot()

    def set_quick_command_favorite(self, command_id: str, favorite: bool) -> None:
        self.quick_action_controller.set_quick_command_favorite(command_id, favorite)

    def favorite_quick_files_snapshot(self) -> list[QuickFile]:
        return self.quick_action_controller.favorite_quick_files_snapshot()

    def set_quick_file_favorite(self, quick_file_id: str, favorite: bool) -> None:
        self.quick_action_controller.set_quick_file_favorite(quick_file_id, favorite)

    def favorite_command_sort_mode_snapshot(self) -> str:
        return self.quick_action_controller.favorite_command_sort_mode_snapshot()

    def favorite_file_sort_mode_snapshot(self) -> str:
        return self.quick_action_controller.favorite_file_sort_mode_snapshot()

    def set_favorite_command_sort_mode(self, mode: str) -> None:
        self.quick_action_controller.set_favorite_command_sort_mode(mode)

    def set_favorite_file_sort_mode(self, mode: str) -> None:
        self.quick_action_controller.set_favorite_file_sort_mode(mode)

    def reorder_favorite_commands(self, command_ids: list[str], *, selected_id: str = "") -> None:
        self.quick_action_controller.reorder_favorite_commands(command_ids, selected_id=selected_id)

    def reorder_favorite_files(self, quick_file_ids: list[str], *, selected_id: str = "") -> None:
        self.quick_action_controller.reorder_favorite_files(quick_file_ids, selected_id=selected_id)

    def add_saved_command_from_text(self, text: str, *, favorite: bool = False) -> None:
        # Saving/favouriting from history reuses a matching saved command (no dupes).
        self.quick_action_controller.add_command_from_text(text, favorite=favorite)

    def add_quick_file(self, quick_file: QuickFile | None = None) -> None:
        # Adding a quick file (the Files "+" / "Add File") starts at the file
        # explorer: pick a command file, then open the editor dialog pre-filled with
        # its name + path (both still editable). A QuickFile passed in (tests, command
        # files) is added directly, without the picker.
        if quick_file is None or isinstance(quick_file, bool):
            start_dir = self.settings.last_script_path or str(Path.cwd())
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Add Command File",
                start_dir,
                "Command Files (*.cpz *.txt *.cmd *.scr);;ComPort Zone Files (*.cpz);;All Files (*)",
            )
            if not path:
                return
            self.settings.last_script_path = str(Path(path).parent)
            self.quick_action_controller.add_quick_file(
                QuickFile(label=Path(path).name, path=path), prompt=True
            )
            return
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
        self.refresh_shared_drawer()

    def refresh_quick_files_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_files(selected_id)
        for editor in self.iter_command_file_editors():
            editor.refresh_workspace_side_panel()
        self.refresh_shared_drawer()

    def record_command(self, command: str) -> None:
        self.history_catalog.add(command)
        for session in self.iter_sessions():
            session.history_store.add(command)
            session._update_completion_model()
        # Only the history list changes on send — refresh just that, not the whole
        # side bar (rebuilding every saved-command row is what made sending slow with
        # hundreds of saved commands).
        self.refresh_shared_drawer_history()
        self.save_settings()

    def remove_command_from_history(self, command: str) -> bool:
        removed = self.history_catalog.remove(command)
        for session in self.iter_sessions():
            session.history_store.remove(command)
            session._update_completion_model()
        if removed:
            self.refresh_shared_drawer_history()
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
        self.tabs.join_panes()

    def _rebuild_runtime_state_from_settings(self, settings: AppSettings) -> None:
        self.quick_actions = self._quick_action_library_from_settings()
        self.history_catalog = HistoryStore(settings.command_history)
        self.theme = THEMES.get(settings.theme, THEMES["ComPort Zone Dark"])
        self.resize(settings.window_width, settings.window_height)

    def show_about(self) -> None:
        self.build_about_dialog().exec()

    def build_about_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("About ComPort Zone")
        dialog.setMinimumWidth(420)

        title = QLabel("ComPort Zone", dialog)
        title.setObjectName("dialogTitle")

        body = QLabel(
            f"Version {escape(__version__)}<br><br>"
            "COM-port terminal for Windows device workflows.<br><br>"
            f'Repository: <a href="{GITHUB_REPOSITORY_URL}">{GITHUB_REPOSITORY_URL}</a>',
            dialog,
        )
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        body.setOpenExternalLinks(True)
        body.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, dialog)
        buttons.accepted.connect(dialog.accept)

        layout = QVBoxLayout(dialog)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(buttons)
        return dialog

    def check_for_updates(self, *, automatic: bool = False) -> None:
        if self._version_check_reply is not None:
            if not automatic:
                self.set_status("Version check already in progress.")
            return
        request = QNetworkRequest(QUrl(GITHUB_LATEST_RELEASE_API_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(
            b"User-Agent",
            f"ComPort-Zone/{__version__}".encode("ascii", "ignore"),
        )
        reply = self.version_check_network.get(request)
        self._version_check_reply = reply
        self._version_check_previous_status = self.footer.text() if automatic else None
        reply.finished.connect(
            lambda target=reply, auto=automatic: self._finish_version_check(target, automatic=auto)
        )
        self.set_status("Checking for updates...")

    def _finish_version_check(self, reply: QNetworkReply, *, automatic: bool) -> None:
        if self._version_check_reply is reply:
            self._version_check_reply = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise RuntimeError(reply.errorString())
            release = release_info_from_json(bytes(reply.readAll()))
            result = build_version_check_result(__version__, release)
        except Exception as exc:
            self._show_version_check_error(str(exc), automatic=automatic)
        else:
            self._show_version_check_result(result, automatic=automatic)
        finally:
            reply.deleteLater()

    def _show_version_check_error(self, detail: str, *, automatic: bool) -> None:
        if automatic:
            self._restore_automatic_version_check_status()
            return
        self.set_status("Could not check for updates.")
        QMessageBox.warning(
            self,
            "Check for Updates",
            f"Could not check for updates:\n{detail}",
        )

    def _show_version_check_result(self, result: VersionCheckResult, *, automatic: bool) -> None:
        if result.update_available:
            self._version_check_previous_status = None
            self.set_status(f"ComPort Zone {result.latest_version} is available.")
            self._show_version_update_dialog(result)
            return
        if automatic:
            self._restore_automatic_version_check_status()
            return
        self.set_status(f"ComPort Zone is up to date ({result.current_version}).")
        self._show_version_update_dialog(result)

    def _restore_automatic_version_check_status(self) -> None:
        previous_status = self._version_check_previous_status
        self._version_check_previous_status = None
        if previous_status:
            self.set_status(previous_status)

    def _show_version_update_dialog(self, result: VersionCheckResult) -> None:
        dialog = VersionUpdateDialog(result, self.settings.check_for_updates_on_launch, self)
        dialog.exec()
        self._set_check_for_updates_on_launch(dialog.check_on_launch_enabled())

    def _set_check_for_updates_on_launch(self, enabled: bool) -> None:
        if self.settings.check_for_updates_on_launch == enabled:
            return
        self.settings.check_for_updates_on_launch = enabled
        if hasattr(self, "check_for_updates_on_launch_action"):
            self.check_for_updates_on_launch_action.setChecked(enabled)
        self.save_settings()

    def apply_theme(self, name: str, *, save: bool = True) -> None:
        self.theme = THEMES.get(name, THEMES["ComPort Zone Dark"])
        self.settings.theme = self.theme.name
        set_icon_color(self.theme.text)
        self.setStyleSheet(self._stylesheet(self.theme))
        for editor in self.iter_command_file_editors():
            editor.apply_theme_palette(self.theme)
        for session in self.iter_sessions():
            session.apply_theme_palette()
        # Qt caches QIcon pixmaps, so persistent buttons and menu icons do not
        # recolor on their own — re-tint them after the new color is in effect.
        retint_icons(self)
        for theme_name, action in getattr(self, "theme_actions", {}).items():
            action.setChecked(theme_name == self.theme.name)
        self.update_tab_titles()
        self.sync_status_from_current_session()
        if save:
            self.save_settings()

    def _stylesheet(self, theme: ThemePalette) -> str:
        return build_stylesheet(theme)

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
