from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QPushButton, QStyle, QToolButton, QWidget

from .icons import set_action_icon, set_button_icon
from .models import CONTROL_PANEL_SORT_MODES, QUICK_COMMAND_SORT_MODES, QUICK_FILE_SORT_MODES
from .quick_actions_panel import (
    FAVORITE_CONTROL_PANEL_EMPTY_HINT,
    ROLE_FAVORITE,
    ROLE_ID,
    QuickActionsDrawer,
    QuickActionsPanel,
    QuickActionsRailMode,
    create_control_panel_list,
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
    command_edit_by_id: Callable[[str], None] | None = None       # inline edit by command id
    command_delete_by_id: Callable[[str], None] | None = None     # inline remove (from saved) by command id
    file_use_by_id: Callable[[str], None] | None = None           # inline run by file id
    file_open_by_id: Callable[[str], None] | None = None          # open-in-editor by file id (double-click)
    file_favorite_toggle: Callable[[str, bool], None] | None = None     # (quick_file_id, favorite)
    file_edit_by_id: Callable[[str], None] | None = None          # inline edit by file id
    file_delete_by_id: Callable[[str], None] | None = None        # inline remove (from saved) by file id
    files_dropped: Callable[[list[str]], None] | None = None       # external files dropped on the Files list
    history_favorite: Callable[[str], None] | None = None         # add history text to favorites
    history_save: Callable[[str], None] | None = None             # add history text to saved
    history_remove: Callable[[str], None] | None = None           # remove history text
    run_file: Callable[[], None] | None = None                    # run an ad-hoc file (not saved)
    # ControlPanel actions (wired by the shared drawer host; None hides the page).
    control_panel_open_by_id: Callable[[str], None] | None = None
    control_panel_favorite_toggle: Callable[[str, bool], None] | None = None
    control_panel_rename_by_id: Callable[[str], None] | None = None
    control_panel_duplicate_by_id: Callable[[str], None] | None = None
    control_panel_delete_by_id: Callable[[str], None] | None = None
    new_control_panel: Callable[[], None] | None = None
    import_control_panels: Callable[[], None] | None = None
    export_control_panels: Callable[[], None] | None = None
    manage_control_panels: Callable[[], None] | None = None


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
        control_panel_sort_changed: Callable[[], None] | None = None,
        favorite_control_panel_sort_changed: Callable[[], None] | None = None,
        control_panel_order_changed: Callable[[], None] | None = None,
        favorite_control_panel_order_changed: Callable[[], None] | None = None,
        command_selection_changed: Callable[[], None] | None = None,
        file_selection_changed: Callable[[], None] | None = None,
        include_history: bool = False,
        include_control_panels: bool = False,
        history_primary: Callable[[str], None] | None = None,
        history_context_menu_requested: Callable | None = None,
        settings_callback: Callable[[], None] | None = None,
        group_menu_provider: Callable | None = None,
        on_page_requested: Callable[[int], None] | None = None,
        rail_width: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        self.actions = actions
        # Labels for the built-in right-click menu's primary entry (Send / Run, or
        # Insert / Open in the editor) so it matches the inline send/play glyph.
        self._command_primary_label = command_primary_label
        self._file_primary_label = file_primary_label
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
        # drag-reorder writes an independent favourites order. The favourite lists
        # always use the built-in, list-aware menu (their ✕ removes from saved,
        # which the host's saved-list menu callback does not distinguish).
        self.favorite_command_list = create_quick_command_list(
            parent,
            tooltip="Send · star removes from favorites · ✕ removes from saved · drag to reorder.",
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
            tooltip="Run · star removes from favorites · ✕ removes from saved · drag to reorder.",
            drag_drop=True,
        )
        # Flag the favourites lists so their inline glyphs / tooltips / menu spell
        # out that ✕ deletes from saved while the star only drops from favourites.
        self.favorite_command_list.is_favorites = True
        self.favorite_file_list.is_favorites = True
        # Built-in right-click menu (Send/Run · favourite toggle · Edit · Remove).
        # The saved lists defer to a host-supplied menu when one is given (the
        # legacy terminal/editor drawers); otherwise — and always for favourites —
        # the sidebar shows its own menu.
        if command_context_menu_requested is None:
            self._enable_context_menu(
                self.quick_command_list,
                lambda pos: self._show_command_menu(self.quick_command_list, pos, is_favorites=False),
            )
        self._enable_context_menu(
            self.favorite_command_list,
            lambda pos: self._show_command_menu(self.favorite_command_list, pos, is_favorites=True),
        )
        if file_context_menu_requested is None:
            self._enable_context_menu(
                self.quick_file_list,
                lambda pos: self._show_file_menu(self.quick_file_list, pos, is_favorites=False),
            )
        self._enable_context_menu(
            self.favorite_file_list,
            lambda pos: self._show_file_menu(self.favorite_file_list, pos, is_favorites=True),
        )
        self.quick_history_list = create_quick_history_list(
            parent,
            tooltip="Send · remove from history · add to favorites · add to saved.",
            context_menu_requested=history_context_menu_requested,
        )
        # ControlPanels: the saved-control_panel library plus its starred subset.
        self.control_panel_list = create_control_panel_list(
            parent,
            tooltip="Click ▶ to open. Star to favorite. Drag to reorder.",
            drag_drop=True,
        )
        self.favorite_control_panel_list = create_control_panel_list(
            parent,
            tooltip="Open · star removes from favorites · ✕ deletes · drag to reorder.",
            placeholder_text=FAVORITE_CONTROL_PANEL_EMPTY_HINT,
            drag_drop=True,
        )
        self.favorite_control_panel_list.is_favorites = True
        for control_panel_list in (self.control_panel_list, self.favorite_control_panel_list):
            control_panel_list.actionTriggered.connect(
                lambda item, key, lst=control_panel_list: self._on_control_panel_action(lst, item, key)
            )
            control_panel_list.itemDoubleClicked.connect(
                lambda item, lst=control_panel_list: self._on_control_panel_action(lst, item, "play")
            )
        self._enable_context_menu(
            self.control_panel_list,
            lambda pos: self._show_control_panel_menu(self.control_panel_list, pos, is_favorites=False),
        )
        self._enable_context_menu(
            self.favorite_control_panel_list,
            lambda pos: self._show_control_panel_menu(
                self.favorite_control_panel_list, pos, is_favorites=True
            ),
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
        # Files dropped from Explorer onto the saved Files list are added as quick files
        # by the host. Enabled only on the saved list (not the favourites view) so a
        # dropped file is never silently absent just because it isn't starred yet.
        self.quick_file_list.set_accepts_file_drops(True)
        self.quick_file_list.filesDropped.connect(self._on_files_dropped)
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

        # Control Panels carry their own sort (Custom order / Name) for the saved
        # list and its favourites, mirroring the file panels.
        self.control_panel_sort_combo = self._control_panel_sort_combo(parent)
        self.control_panel_sort_combo.setVisible(False)
        if control_panel_sort_changed is not None:
            self.control_panel_sort_combo.currentIndexChanged.connect(control_panel_sort_changed)
        self.favorite_control_panel_sort_combo = self._control_panel_sort_combo(parent)
        self.favorite_control_panel_sort_combo.setVisible(False)
        if favorite_control_panel_sort_changed is not None:
            self.favorite_control_panel_sort_combo.currentIndexChanged.connect(
                favorite_control_panel_sort_changed
            )
        self.control_panel_sort_button = self._sort_button(
            self.control_panel_sort_combo, "Sort control panels", parent
        )
        self.favorite_control_panel_sort_button = self._sort_button(
            self.favorite_control_panel_sort_combo, "Sort favorite control panels", parent
        )

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

        # Control Panels rail: the saved-panel library with open/star/rename/
        # delete row actions; the ⋯ menu carries the library-wide operations.
        control_panel_page = QuickActionsPanel(
            title="Control Panels",
            quick_list=self.control_panel_list,
            header_icon="list",
            collapsible_buttons=(self.control_panel_sort_button,),
            header_buttons=(
                self._header_button(
                    "+", "New control panel", lambda: self._control_panel_action(actions.new_control_panel), parent
                ),
                self._overflow_button(parent, [
                    ("Manage…", actions.manage_control_panels),
                    None,
                    ("Import JSON…", actions.import_control_panels),
                    ("Export JSON…", actions.export_control_panels),
                ]),
            ),
            parent=parent,
        )

        # Favorites rail surfaces three curated panels: favourite commands,
        # files and control_panels. They are collapsible and share a draggable
        # splitter (see splitter_groups).
        self.favorites_panel = QuickActionsPanel(
            title="Favorite Commands",
            quick_list=self.favorite_command_list,
            header_icon="star",
            collapsible_buttons=(self.favorite_sort_button, self.favorite_group_button),
            collapsible=True,
            parent=parent,
        )
        self.favorite_files_panel = QuickActionsPanel(
            title="Favorite Files",
            quick_list=self.favorite_file_list,
            header_icon="star",
            collapsible_buttons=(self.favorite_file_sort_button,),
            collapsible=True,
            parent=parent,
        )
        self.favorite_control_panels_panel = QuickActionsPanel(
            title="Favorite Control Panels",
            quick_list=self.favorite_control_panel_list,
            header_icon="star",
            collapsible_buttons=(self.favorite_control_panel_sort_button,),
            collapsible=True,
            parent=parent,
        )
        favorites_page = self.favorites_panel
        favorite_files_page = self.favorite_files_panel
        history_page = QuickActionsPanel(
            title="History",
            quick_list=self.quick_history_list,
            header_icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
            parent=parent,
        )
        # The ControlPanels page only belongs to the shared app drawer — the
        # editor's embedded drawer keeps its insert/open-focused pages and
        # leaves the (unwired) control_panel actions out entirely.
        favorites_sections: tuple[str, ...] = ("favorites", "favorite_file")
        sections = {
            "favorites": favorites_page,
            "favorite_file": favorite_files_page,
            "command": command_page,
            "file": file_page,
            "history": history_page,
        }
        if include_control_panels:
            sections["favorite_control_panel"] = self.favorite_control_panels_panel
            sections["control_panel"] = control_panel_page
            favorites_sections = ("favorites", "favorite_file", "favorite_control_panel")
        else:
            self.favorite_control_panels_panel.setVisible(False)
            control_panel_page.setVisible(False)
        # Favorites surfaces starred commands + files (+ control_panels in the
        # shared drawer); the other rails hold the full Saved Commands /
        # Files / ControlPanels lists (where you star items).
        rail_modes = [
            QuickActionsRailMode("all", "star", "Favorites", favorites_sections),
            QuickActionsRailMode("commands", "term", "Saved Commands", ("command",)),
            QuickActionsRailMode("files", "file", "Files", ("file",)),
        ]
        if include_control_panels:
            rail_modes.append(
                QuickActionsRailMode(
                    "control_panels", "list", "Control Panels", ("control_panel",)
                )
            )
        if include_history:
            rail_modes.append(
                QuickActionsRailMode("history", QStyle.StandardPixmap.SP_FileDialogInfoView, "History", ("history",))
            )

        self._connect_list_signals(
            command_order_changed=command_order_changed,
            file_order_changed=file_order_changed,
            favorite_command_order_changed=favorite_command_order_changed,
            favorite_file_order_changed=favorite_file_order_changed,
            control_panel_order_changed=control_panel_order_changed,
            favorite_control_panel_order_changed=favorite_control_panel_order_changed,
            command_selection_changed=command_selection_changed,
            file_selection_changed=file_selection_changed,
        )

        super().__init__(
            sections=sections,
            rail_modes=rail_modes,
            on_page_requested=on_page_requested,
            settings_callback=settings_callback,
            splitter_groups=[favorites_sections],
            rail_width=rail_width,
            parent=parent,
        )

    @property
    def favorites_splitter(self):
        """The QSplitter wrapping the two favourites panels (None if absent)."""
        return self.section_splitters[0] if self.section_splitters else None

    def apply_theme_palette(self, palette) -> None:
        for quick_list in (
            self.quick_command_list,
            self.favorite_command_list,
            self.quick_file_list,
            self.favorite_file_list,
            self.control_panel_list,
            self.favorite_control_panel_list,
            self.quick_history_list,
        ):
            quick_list.apply_theme_palette(palette)

    def _on_command_action(self, quick_list, item, key: str) -> None:
        if item is None:
            return
        quick_list.setCurrentItem(item)
        command_id = str(item.data(ROLE_ID) or "")
        if key == "star":
            toggle = self.actions.command_favorite_toggle
            if toggle is not None and command_id:
                toggle(command_id, not bool(item.data(ROLE_FAVORITE)))
            return
        if key == "edit":
            self._dispatch_by_id(command_id, self.actions.command_edit_by_id, self.actions.edit_command)
            return
        if key == "remove":
            self._dispatch_by_id(command_id, self.actions.command_delete_by_id, self.actions.delete_command)
            return
        if self.actions.command_use_by_id is not None and command_id:
            self.actions.command_use_by_id(command_id)
        else:
            self.actions.command_primary()

    def _on_file_action(self, quick_list, item, key: str) -> None:
        if item is None:
            return
        quick_list.setCurrentItem(item)
        file_id = str(item.data(ROLE_ID) or "")
        if key == "star":
            toggle = self.actions.file_favorite_toggle
            if toggle is not None and file_id:
                toggle(file_id, not bool(item.data(ROLE_FAVORITE)))
            return
        if key == "edit":
            self._dispatch_by_id(file_id, self.actions.file_edit_by_id, self.actions.edit_file)
            return
        if key == "remove":
            self._dispatch_by_id(file_id, self.actions.file_delete_by_id, self.actions.delete_file)
            return
        # play -> run by id (works from either file list); fall back to the
        # selection-based primary for drawers that only drive one list.
        if self.actions.file_use_by_id is not None and file_id:
            self.actions.file_use_by_id(file_id)
        else:
            self.actions.file_primary()

    @staticmethod
    def _dispatch_by_id(
        item_id: str,
        by_id: Callable[[str], None] | None,
        fallback: Callable[[], None],
    ) -> None:
        """Run the id-based callback when wired (correct from either the saved or the
        favourites list), else the selection-based one — the caller has already
        selected the clicked row, so the fallback acts on it."""
        if by_id is not None and item_id:
            by_id(item_id)
        else:
            fallback()

    def _on_file_double_clicked(self, quick_list, item) -> None:
        quick_list.setCurrentItem(item)
        file_id = str(item.data(ROLE_ID) or "")
        if self.actions.file_open_by_id is not None and file_id:
            self.actions.file_open_by_id(file_id)
        elif self._file_double_clicked is not None:
            self._file_double_clicked()

    def _on_files_dropped(self, paths) -> None:
        if self.actions.files_dropped is not None and paths:
            self.actions.files_dropped(list(paths))

    @staticmethod
    def _control_panel_action(callback: Callable[[], None] | None) -> None:
        if callback is not None:
            callback()

    def _on_control_panel_action(self, quick_list, item, key: str) -> None:
        if item is None:
            return
        quick_list.setCurrentItem(item)
        control_panel_id = str(item.data(ROLE_ID) or "")
        if not control_panel_id:
            return
        if key == "star":
            toggle = self.actions.control_panel_favorite_toggle
            if toggle is not None:
                toggle(control_panel_id, not bool(item.data(ROLE_FAVORITE)))
            return
        if key == "edit":
            if self.actions.control_panel_rename_by_id is not None:
                self.actions.control_panel_rename_by_id(control_panel_id)
            return
        if key == "duplicate":
            if self.actions.control_panel_duplicate_by_id is not None:
                self.actions.control_panel_duplicate_by_id(control_panel_id)
            return
        if key == "remove":
            if self.actions.control_panel_delete_by_id is not None:
                self.actions.control_panel_delete_by_id(control_panel_id)
            return
        if self.actions.control_panel_open_by_id is not None:
            self.actions.control_panel_open_by_id(control_panel_id)

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

    # ---- Built-in right-click menu (mirrors the inline row glyphs) ------------
    @staticmethod
    def _enable_context_menu(quick_list, handler: Callable) -> None:
        quick_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        quick_list.customContextMenuRequested.connect(handler)

    def _menu_action(self, menu: QMenu, label: str, icon: str, callback: Callable[[], None]) -> QAction:
        action = QAction(label, menu)
        set_action_icon(action, icon, 14)
        action.triggered.connect(lambda _checked=False, cb=callback: cb())
        menu.addAction(action)
        return action

    def _show_command_menu(self, quick_list, pos, *, is_favorites: bool) -> None:
        item = quick_list.itemAt(pos)
        if item is None:
            return
        quick_list.setCurrentItem(item)
        self._build_command_menu(quick_list, item, is_favorites=is_favorites).exec(
            quick_list.mapToGlobal(pos)
        )

    def _build_command_menu(self, quick_list, item, *, is_favorites: bool) -> QMenu:
        command_id = str(item.data(ROLE_ID) or "")
        starred = bool(item.data(ROLE_FAVORITE)) or is_favorites
        menu = QMenu(quick_list)
        self._menu_action(
            menu, self._command_primary_label, "send",
            lambda it=item: self._on_command_action(quick_list, it, "send"),
        )
        menu.addSeparator()
        if self.actions.command_favorite_toggle is not None and command_id:
            self._menu_action(
                menu,
                "Remove from Favorites" if starred else "Add to Favorites",
                "star-fill" if starred else "star",
                lambda it=item: self._on_command_action(quick_list, it, "star"),
            )
        self._menu_action(
            menu, "Edit", "edit",
            lambda it=item: self._on_command_action(quick_list, it, "edit"),
        )
        # On a favourite row, ✕ deletes from saved (not just favourites) — say so.
        self._menu_action(
            menu, "Remove from Saved" if is_favorites else "Remove", "x",
            lambda it=item: self._on_command_action(quick_list, it, "remove"),
        )
        return menu

    def _show_file_menu(self, quick_list, pos, *, is_favorites: bool) -> None:
        item = quick_list.itemAt(pos)
        if item is None:
            return
        quick_list.setCurrentItem(item)
        self._build_file_menu(quick_list, item, is_favorites=is_favorites).exec(
            quick_list.mapToGlobal(pos)
        )

    def _build_file_menu(self, quick_list, item, *, is_favorites: bool) -> QMenu:
        file_id = str(item.data(ROLE_ID) or "")
        starred = bool(item.data(ROLE_FAVORITE)) or is_favorites
        menu = QMenu(quick_list)
        self._menu_action(
            menu, self._file_primary_label, "play",
            lambda it=item: self._on_file_action(quick_list, it, "play"),
        )
        menu.addSeparator()
        if self.actions.file_favorite_toggle is not None and file_id:
            self._menu_action(
                menu,
                "Remove from Favorites" if starred else "Add to Favorites",
                "star-fill" if starred else "star",
                lambda it=item: self._on_file_action(quick_list, it, "star"),
            )
        self._menu_action(
            menu, "Edit", "edit",
            lambda it=item: self._on_file_action(quick_list, it, "edit"),
        )
        self._menu_action(
            menu, "Remove from Saved" if is_favorites else "Remove", "x",
            lambda it=item: self._on_file_action(quick_list, it, "remove"),
        )
        return menu

    def _show_control_panel_menu(self, quick_list, pos, *, is_favorites: bool) -> None:
        item = quick_list.itemAt(pos)
        if item is None:
            return
        quick_list.setCurrentItem(item)
        self._build_control_panel_menu(quick_list, item, is_favorites=is_favorites).exec(
            quick_list.mapToGlobal(pos)
        )

    def _build_control_panel_menu(self, quick_list, item, *, is_favorites: bool) -> QMenu:
        control_panel_id = str(item.data(ROLE_ID) or "")
        starred = bool(item.data(ROLE_FAVORITE)) or is_favorites
        menu = QMenu(quick_list)
        self._menu_action(
            menu, "Open", "play",
            lambda it=item: self._on_control_panel_action(quick_list, it, "play"),
        )
        menu.addSeparator()
        if self.actions.control_panel_favorite_toggle is not None and control_panel_id:
            self._menu_action(
                menu,
                "Remove from Favorites" if starred else "Add to Favorites",
                "star-fill" if starred else "star",
                lambda it=item: self._on_control_panel_action(quick_list, it, "star"),
            )
        self._menu_action(
            menu, "Rename", "edit",
            lambda it=item: self._on_control_panel_action(quick_list, it, "edit"),
        )
        if self.actions.control_panel_duplicate_by_id is not None:
            self._menu_action(
                menu, "Duplicate", "copy",
                lambda it=item: self._on_control_panel_action(quick_list, it, "duplicate"),
            )
        self._menu_action(
            menu, "Delete Control Panel", "x",
            lambda it=item: self._on_control_panel_action(quick_list, it, "remove"),
        )
        return menu

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

    def _control_panel_sort_combo(self, parent: QWidget | None) -> ChevronComboBox:
        combo = ChevronComboBox(parent)
        combo.setObjectName("controlPanelSortCombo")
        for mode in CONTROL_PANEL_SORT_MODES:
            label = "Custom order" if mode == "Custom" else mode
            combo.addItem(label, mode)
        combo.setToolTip("Sort control panels")
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
        control_panel_order_changed: Callable[[], None] | None,
        favorite_control_panel_order_changed: Callable[[], None] | None,
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
        if control_panel_order_changed is not None:
            self.control_panel_list.model().rowsMoved.connect(
                lambda *_: QTimer.singleShot(0, control_panel_order_changed)
            )
        if favorite_control_panel_order_changed is not None:
            self.favorite_control_panel_list.model().rowsMoved.connect(
                lambda *_: QTimer.singleShot(0, favorite_control_panel_order_changed)
            )
