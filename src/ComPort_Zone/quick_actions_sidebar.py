from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QPushButton, QStyle, QToolButton, QWidget

from .icons import set_button_icon
from .models import QUICK_COMMAND_SORT_MODES, QUICK_FILE_SORT_MODES
from .quick_actions_panel import (
    ROLE_FAVORITE,
    ROLE_ID,
    QuickActionsDrawer,
    QuickActionsPanel,
    QuickActionsRailMode,
    create_quick_command_list,
    create_quick_file_list,
    create_quick_history_list,
)
from .widgets import ChevronComboBox


@dataclass(slots=True)
class QuickActionsSidebarActions:
    command_primary: Callable[[], None]
    file_primary: Callable[[], None]
    add_command: Callable[[], None]
    edit_command: Callable[[], None]
    delete_command: Callable[[], None]
    move_command_up: Callable[[], None]
    move_command_down: Callable[[], None]
    import_commands: Callable[[], None]
    export_commands: Callable[[], None]
    add_file: Callable[[], None]
    edit_file: Callable[[], None]
    delete_file: Callable[[], None]
    move_file_up: Callable[[], None]
    move_file_down: Callable[[], None]
    import_files: Callable[[], None]
    export_files: Callable[[], None]
    # Favorites / history actions (optional; wired by the shared drawer host).
    command_use_by_id: Callable[[str], None] | None = None        # inline send by command id
    command_favorite_toggle: Callable[[str, bool], None] | None = None  # (command_id, favorite)
    file_use_by_id: Callable[[str], None] | None = None           # inline run by file id
    file_open_by_id: Callable[[str], None] | None = None          # open-in-editor by file id (double-click)
    file_favorite_toggle: Callable[[str, bool], None] | None = None     # (quick_file_id, favorite)
    history_favorite: Callable[[str], None] | None = None         # add history text to favorites
    history_save: Callable[[str], None] | None = None             # add history text to saved
    history_remove: Callable[[str], None] | None = None           # remove history text
    run_file: Callable[[], None] | None = None                    # run an ad-hoc file (not saved)


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


class QuickActionsSidebar(QuickActionsDrawer):
    """Shared left dock: Quick Send / Command Files / History.

    Rows carry an inline send/run affordance (see :class:`QuickRowDelegate`); each
    panel header shows a live count plus a compact ``+`` (add) button and a ``⋯``
    overflow menu (edit / delete / move / import / export). The legacy per-action
    push buttons are still created — kept hidden — so existing terminal/editor
    enable-state wiring keeps working unchanged.
    """

    def __init__(
        self,
        *,
        actions: QuickActionsSidebarActions,
        command_primary_label: str,
        file_primary_label: str,
        command_title: str = "Saved Commands",
        file_title: str = "Quick Files",
        command_primary_icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_ArrowForward,
        file_primary_icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_ArrowForward,
        command_tooltip: str = "Click a command's arrow to send it. Right-click for more. Drag to reorder.",
        file_tooltip: str = "Click a file's play button to run it. Double-click to open. Drag to reorder.",
        command_double_clicked: Callable[[], None] | None = None,
        file_double_clicked: Callable[[], None] | None = None,
        command_context_menu_requested: Callable | None = None,
        file_context_menu_requested: Callable | None = None,
        command_sort_changed: Callable[[], None] | None = None,
        file_sort_changed: Callable[[], None] | None = None,
        command_order_changed: Callable[[], None] | None = None,
        file_order_changed: Callable[[], None] | None = None,
        favorite_command_sort_changed: Callable[[], None] | None = None,
        favorite_file_sort_changed: Callable[[], None] | None = None,
        favorite_command_order_changed: Callable[[], None] | None = None,
        favorite_file_order_changed: Callable[[], None] | None = None,
        command_selection_changed: Callable[[], None] | None = None,
        file_selection_changed: Callable[[], None] | None = None,
        include_history: bool = False,
        history_primary: Callable[[str], None] | None = None,
        history_context_menu_requested: Callable | None = None,
        settings_callback: Callable[[], None] | None = None,
        group_menu_provider: Callable | None = None,
        on_page_requested: Callable[[int], None] | None = None,
        rail_width: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        self.actions = actions
        # Populates a groups menu (used by both the group button and the ⋯ overflow
        # when the group button is collapsed). Host-supplied; None on hidden drawers.
        self._group_menu_provider = group_menu_provider

        self._history_primary = history_primary
        # Fallback no-arg double-click (used when no id-based callback is wired —
        # e.g. the editor / per-tab drawers that only drive a single file list).
        self._file_double_clicked = file_double_clicked
        self.quick_command_list = create_quick_command_list(
            parent,
            tooltip=command_tooltip,
            context_menu_requested=command_context_menu_requested,
            drag_drop=True,
        )
        # Favorites: a curated view of saved commands (star toggles membership);
        # drag-reorder writes an independent favourites order.
        self.favorite_command_list = create_quick_command_list(
            parent,
            tooltip="Send · star removes from favorites · drag to reorder favorites.",
            context_menu_requested=command_context_menu_requested,
            drag_drop=True,
        )
        self.quick_file_list = create_quick_file_list(
            parent,
            tooltip=file_tooltip,
            context_menu_requested=file_context_menu_requested,
            drag_drop=True,
        )
        # Favorite files: the star-filtered file view (mirrors favourite commands).
        self.favorite_file_list = create_quick_file_list(
            parent,
            tooltip="Run · star removes from favorites · drag to reorder favorites.",
            context_menu_requested=file_context_menu_requested,
            drag_drop=True,
        )
        self.quick_history_list = create_quick_history_list(
            parent,
            tooltip="Send · remove from history · add to favorites · add to saved.",
            context_menu_requested=history_context_menu_requested,
        )

        # Inline row affordances: select the clicked row, then run the chosen action.
        for command_list in (self.quick_command_list, self.favorite_command_list):
            command_list.actionTriggered.connect(
                lambda item, key, lst=command_list: self._on_command_action(lst, item, key)
            )
            command_list.itemDoubleClicked.connect(
                lambda item, lst=command_list: self._on_command_action(lst, item, "send")
            )
        for file_list in (self.quick_file_list, self.favorite_file_list):
            file_list.actionTriggered.connect(
                lambda item, key, lst=file_list: self._on_file_action(lst, item, key)
            )
            file_list.itemDoubleClicked.connect(
                lambda item, lst=file_list: self._on_file_double_clicked(lst, item)
            )
        self.quick_history_list.actionTriggered.connect(self._on_history_action)
        if history_primary is not None:
            self.quick_history_list.itemDoubleClicked.connect(lambda item: history_primary(item.text()))

        # Sort state lives in hidden combos; the header carries icon buttons whose
        # popup menus mirror them (Custom order / A–Z / …).
        self.quick_sort_combo = self._command_sort_combo(parent)
        self.quick_sort_combo.setVisible(False)
        if command_sort_changed is not None:
            self.quick_sort_combo.currentIndexChanged.connect(command_sort_changed)
        self.quick_file_sort_combo = self._file_sort_combo(parent)
        self.quick_file_sort_combo.setVisible(False)
        if file_sort_changed is not None:
            self.quick_file_sort_combo.currentIndexChanged.connect(file_sort_changed)

        self.quick_sort_button = self._sort_button(self.quick_sort_combo, "Sort quick commands", parent)
        self.quick_file_sort_button = self._sort_button(self.quick_file_sort_combo, "Sort quick files", parent)
        self.quick_group_button = self._group_button(parent, "Show or hide favourite + saved command groups")

        # Favourites carry their own sort + group controls (independent order).
        self.favorite_sort_combo = self._command_sort_combo(parent)
        self.favorite_sort_combo.setVisible(False)
        if favorite_command_sort_changed is not None:
            self.favorite_sort_combo.currentIndexChanged.connect(favorite_command_sort_changed)
        self.favorite_file_sort_combo = self._file_sort_combo(parent)
        self.favorite_file_sort_combo.setVisible(False)
        if favorite_file_sort_changed is not None:
            self.favorite_file_sort_combo.currentIndexChanged.connect(favorite_file_sort_changed)
        self.favorite_sort_button = self._sort_button(self.favorite_sort_combo, "Sort favorites", parent)
        self.favorite_file_sort_button = self._sort_button(self.favorite_file_sort_combo, "Sort favorite files", parent)
        self.favorite_group_button = self._group_button(parent, "Show or hide favourite command groups")

        # Legacy action buttons — kept (hidden) for existing enable-state wiring.
        self.command_primary_button = self._drawer_action(command_primary_label, command_primary_icon, actions.command_primary, parent, role="drawerPrimary")
        self.add_command_button = self._drawer_action("Add Command", QStyle.StandardPixmap.SP_FileDialogNewFolder, actions.add_command, parent)
        self.edit_command_button = self._drawer_action("Edit", QStyle.StandardPixmap.SP_FileDialogDetailedView, actions.edit_command, parent)
        self.delete_command_button = self._drawer_action("Delete", QStyle.StandardPixmap.SP_TrashIcon, actions.delete_command, parent, role="drawerDanger")
        self.quick_command_move_up_button = self._drawer_action("Move Up", QStyle.StandardPixmap.SP_ArrowUp, actions.move_command_up, parent)
        self.quick_command_move_down_button = self._drawer_action("Move Down", QStyle.StandardPixmap.SP_ArrowDown, actions.move_command_down, parent)
        self.import_quick_commands_button = self._drawer_action("Import CSV", QStyle.StandardPixmap.SP_DialogOpenButton, actions.import_commands, parent)
        self.export_quick_commands_button = self._drawer_action("Export CSV", QStyle.StandardPixmap.SP_DialogSaveButton, actions.export_commands, parent)

        self.file_primary_button = self._drawer_action(file_primary_label, file_primary_icon, actions.file_primary, parent, role="drawerPrimary")
        self.add_file_button = self._drawer_action("Add File", QStyle.StandardPixmap.SP_FileDialogNewFolder, actions.add_file, parent)
        self.edit_file_button = self._drawer_action("Edit", QStyle.StandardPixmap.SP_FileDialogDetailedView, actions.edit_file, parent)
        self.delete_file_button = self._drawer_action("Delete", QStyle.StandardPixmap.SP_TrashIcon, actions.delete_file, parent, role="drawerDanger")
        self.quick_file_move_up_button = self._drawer_action("Move Up", QStyle.StandardPixmap.SP_ArrowUp, actions.move_file_up, parent)
        self.quick_file_move_down_button = self._drawer_action("Move Down", QStyle.StandardPixmap.SP_ArrowDown, actions.move_file_down, parent)
        self.import_quick_files_button = self._drawer_action("Import CSV", QStyle.StandardPixmap.SP_DialogOpenButton, actions.import_files, parent)
        self.export_quick_files_button = self._drawer_action("Export CSV", QStyle.StandardPixmap.SP_DialogSaveButton, actions.export_files, parent)
        for button in self._legacy_buttons():
            button.setVisible(False)

        command_page = QuickActionsPanel(
            title=command_title,
            quick_list=self.quick_command_list,
            header_icon="term",
            collapsible_buttons=(self.quick_sort_button, self.quick_group_button),
            header_buttons=(
                self._header_button("+", "Add command", actions.add_command, parent),
                self._overflow_button(parent, [
                    ("Edit", actions.edit_command),
                    ("Delete", actions.delete_command),
                    None,
                    ("Move up", actions.move_command_up),
                    ("Move down", actions.move_command_down),
                    None,
                    ("Import CSV…", actions.import_commands),
                    ("Export CSV…", actions.export_commands),
                ], extra_provider=self._command_overflow_extras),
            ),
            parent=parent,
        )
        file_page = QuickActionsPanel(
            title=file_title,
            quick_list=self.quick_file_list,
            header_icon="file",
            collapsible_buttons=(self.quick_file_sort_button,),
            header_buttons=(
                self._header_button("+", "Add file", actions.add_file, parent),
                self._overflow_button(parent, [
                    ("Run file…", actions.run_file),
                    None,
                    ("Edit", actions.edit_file),
                    ("Delete", actions.delete_file),
                    None,
                    ("Move up", actions.move_file_up),
                    ("Move down", actions.move_file_down),
                    None,
                    ("Import CSV…", actions.import_files),
                    ("Export CSV…", actions.export_files),
                ], extra_provider=self._file_overflow_extras),
            ),
            parent=parent,
        )

        # Favorites rail surfaces two curated panels: favourite commands + files.
        favorites_page = QuickActionsPanel(
            title="Favorite Commands",
            quick_list=self.favorite_command_list,
            header_icon="star",
            collapsible_buttons=(self.favorite_sort_button, self.favorite_group_button),
            parent=parent,
        )
        favorite_files_page = QuickActionsPanel(
            title="Favorite Files",
            quick_list=self.favorite_file_list,
            header_icon="star",
            collapsible_buttons=(self.favorite_file_sort_button,),
            parent=parent,
        )
        history_page = QuickActionsPanel(
            title="History",
            quick_list=self.quick_history_list,
            header_icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
            parent=parent,
        )
        sections = {
            "favorites": favorites_page,
            "favorite_file": favorite_files_page,
            "command": command_page,
            "file": file_page,
            "history": history_page,
        }
        # Favorites surfaces starred commands + files; the other rails hold the
        # full Saved Commands / Files lists (where you star items).
        rail_modes = [
            QuickActionsRailMode("all", "star", "Favorites", ("favorites", "favorite_file")),
            QuickActionsRailMode("commands", "term", "Saved Commands", ("command",)),
            QuickActionsRailMode("files", "file", "Files", ("file",)),
        ]
        if include_history:
            rail_modes.append(
                QuickActionsRailMode("history", QStyle.StandardPixmap.SP_FileDialogInfoView, "History", ("history",))
            )

        self._connect_list_signals(
            command_order_changed=command_order_changed,
            file_order_changed=file_order_changed,
            favorite_command_order_changed=favorite_command_order_changed,
            favorite_file_order_changed=favorite_file_order_changed,
            command_selection_changed=command_selection_changed,
            file_selection_changed=file_selection_changed,
        )

        super().__init__(
            sections=sections,
            rail_modes=rail_modes,
            on_page_requested=on_page_requested,
            settings_callback=settings_callback,
            rail_width=rail_width,
            parent=parent,
        )

    def apply_theme_palette(self, palette) -> None:
        for quick_list in (
            self.quick_command_list,
            self.favorite_command_list,
            self.quick_file_list,
            self.favorite_file_list,
            self.quick_history_list,
        ):
            quick_list.apply_theme_palette(palette)

    def _on_command_action(self, quick_list, item, key: str) -> None:
        quick_list.setCurrentItem(item)
        command_id = str(item.data(ROLE_ID) or "")
        if key == "star":
            toggle = self.actions.command_favorite_toggle
            if toggle is not None and command_id:
                toggle(command_id, not bool(item.data(ROLE_FAVORITE)))
            return
        if self.actions.command_use_by_id is not None and command_id:
            self.actions.command_use_by_id(command_id)
        else:
            self.actions.command_primary()

    def _on_file_action(self, quick_list, item, key: str) -> None:
        quick_list.setCurrentItem(item)
        file_id = str(item.data(ROLE_ID) or "")
        if key == "star":
            toggle = self.actions.file_favorite_toggle
            if toggle is not None and file_id:
                toggle(file_id, not bool(item.data(ROLE_FAVORITE)))
            return
        # play -> run by id (works from either file list); fall back to the
        # selection-based primary for drawers that only drive one list.
        if self.actions.file_use_by_id is not None and file_id:
            self.actions.file_use_by_id(file_id)
        else:
            self.actions.file_primary()

    def _on_file_double_clicked(self, quick_list, item) -> None:
        quick_list.setCurrentItem(item)
        file_id = str(item.data(ROLE_ID) or "")
        if self.actions.file_open_by_id is not None and file_id:
            self.actions.file_open_by_id(file_id)
        elif self._file_double_clicked is not None:
            self._file_double_clicked()

    def _on_history_action(self, item, key: str) -> None:
        text = item.text()
        callback = {
            "send": self._history_primary,
            "favorite": self.actions.history_favorite,
            "save": self.actions.history_save,
            "remove": self.actions.history_remove,
        }.get(key)
        if callback is not None:
            callback(text)

    @staticmethod
    def _trigger_inline(quick_list, item, primary: Callable[[], None]) -> None:
        quick_list.setCurrentItem(item)
        primary()

    def _legacy_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.command_primary_button, self.add_command_button, self.edit_command_button,
            self.delete_command_button, self.quick_command_move_up_button, self.quick_command_move_down_button,
            self.import_quick_commands_button, self.export_quick_commands_button,
            self.file_primary_button, self.add_file_button, self.edit_file_button, self.delete_file_button,
            self.quick_file_move_up_button, self.quick_file_move_down_button,
            self.import_quick_files_button, self.export_quick_files_button,
        )

    def _header_button(self, text: str, tooltip: str, callback: Callable[[], None], parent: QWidget | None) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("quickPanelHeaderButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def _overflow_button(self, parent: QWidget | None, items: list, *, extra_provider=None) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("quickPanelHeaderButton")
        button.setText("⋯")  # horizontal ellipsis
        button.setToolTip("More actions")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        # Rebuilt on open so collapsed sort/group controls can fold in (see extras).
        menu.aboutToShow.connect(lambda m=menu, it=items, ep=extra_provider: self._populate_overflow(m, it, ep))
        button.setMenu(menu)
        button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        return button

    def _populate_overflow(self, menu: QMenu, items: list, extra_provider) -> None:
        menu.clear()
        if extra_provider is not None:
            extra_provider(menu)
        for entry in items:
            if entry is None:
                menu.addSeparator()
                continue
            label, callback = entry
            if callback is None:  # optional action not wired on this drawer
                continue
            action = QAction(label, menu)
            action.triggered.connect(lambda _checked=False, cb=callback: cb())
            menu.addAction(action)

    def _command_overflow_extras(self, menu: QMenu) -> None:
        added = False
        if self.quick_sort_button.isHidden():
            self._populate_sort_menu(menu.addMenu("Sort"), self.quick_sort_combo)
            added = True
        if self.quick_group_button.isHidden() and self._group_menu_provider is not None:
            self._group_menu_provider(menu.addMenu("Groups"))
            added = True
        if added:
            menu.addSeparator()

    def _file_overflow_extras(self, menu: QMenu) -> None:
        if self.quick_file_sort_button.isHidden():
            self._populate_sort_menu(menu.addMenu("Sort"), self.quick_file_sort_combo)
            menu.addSeparator()

    def _drawer_action(
        self,
        text: str,
        icon: QStyle.StandardPixmap,
        callback: Callable[[], None],
        parent: QWidget | None,
        *,
        role: str = "drawerAction",
    ) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("drawerActionButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_icon(button, icon)
        set_button_role(button, role)
        button.clicked.connect(callback)
        return button

    def _command_sort_combo(self, parent: QWidget | None) -> ChevronComboBox:
        combo = ChevronComboBox(parent)
        combo.setObjectName("quickSortCombo")
        for mode in QUICK_COMMAND_SORT_MODES:
            label = "Custom order" if mode == "Custom" else mode
            combo.addItem(label, mode)
        combo.setToolTip("Sort quick commands")
        return combo

    def _file_sort_combo(self, parent: QWidget | None) -> ChevronComboBox:
        combo = ChevronComboBox(parent)
        combo.setObjectName("quickFileSortCombo")
        for mode in QUICK_FILE_SORT_MODES:
            label = "Custom order" if mode == "Custom" else mode
            combo.addItem(label, mode)
        combo.setToolTip("Sort quick files")
        return combo

    def _group_button(self, parent: QWidget | None, tooltip: str = "Show or hide quick command groups") -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("quickPanelHeaderButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tooltip)
        set_button_icon(button, "list", 14)
        button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        return button

    def _sort_button(self, combo: ChevronComboBox, tooltip: str, parent: QWidget | None) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("quickPanelHeaderButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolTip(tooltip)
        set_button_icon(button, "sort", 14)
        menu = QMenu(button)
        menu.aboutToShow.connect(lambda m=menu, c=combo: self._populate_sort_menu(m, c))
        button.setMenu(menu)
        button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        return button

    def _populate_sort_menu(self, menu: QMenu, combo: ChevronComboBox) -> None:
        menu.clear()
        for index in range(combo.count()):
            action = menu.addAction(combo.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == combo.currentIndex())
            action.triggered.connect(lambda _checked=False, idx=index, c=combo: c.setCurrentIndex(idx))

    def _connect_list_signals(
        self,
        *,
        command_order_changed: Callable[[], None] | None,
        file_order_changed: Callable[[], None] | None,
        favorite_command_order_changed: Callable[[], None] | None,
        favorite_file_order_changed: Callable[[], None] | None,
        command_selection_changed: Callable[[], None] | None,
        file_selection_changed: Callable[[], None] | None,
    ) -> None:
        if command_selection_changed is not None:
            self.quick_command_list.currentItemChanged.connect(lambda *_: command_selection_changed())
        if file_selection_changed is not None:
            self.quick_file_list.currentItemChanged.connect(lambda *_: file_selection_changed())
        if command_order_changed is not None:
            self.quick_command_list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, command_order_changed))
            self.quick_command_list.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, command_order_changed))
            self.quick_command_list.model().rowsRemoved.connect(lambda *_: QTimer.singleShot(0, command_order_changed))
        if file_order_changed is not None:
            self.quick_file_list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, file_order_changed))
        # Favourites persist on an actual drag (rowsMoved) only — a programmatic
        # repopulate (rowsInserted/Removed) must not flip the sort to Custom.
        if favorite_command_order_changed is not None:
            self.favorite_command_list.model().rowsMoved.connect(
                lambda *_: QTimer.singleShot(0, favorite_command_order_changed)
            )
        if favorite_file_order_changed is not None:
            self.favorite_file_list.model().rowsMoved.connect(
                lambda *_: QTimer.singleShot(0, favorite_file_order_changed)
            )
