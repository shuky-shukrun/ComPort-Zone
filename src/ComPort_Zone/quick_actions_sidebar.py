from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QPushButton, QStyle, QToolButton, QWidget

from .icons import set_button_icon
from .models import QUICK_COMMAND_SORT_MODES, QUICK_FILE_SORT_MODES
from .quick_actions_panel import (
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
        command_title: str = "Quick Send",
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
        command_selection_changed: Callable[[], None] | None = None,
        file_selection_changed: Callable[[], None] | None = None,
        include_history: bool = False,
        history_primary: Callable[[str], None] | None = None,
        history_context_menu_requested: Callable | None = None,
        settings_callback: Callable[[], None] | None = None,
        on_page_requested: Callable[[int], None] | None = None,
        rail_width: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        self.actions = actions

        self.quick_command_list = create_quick_command_list(
            parent,
            tooltip=command_tooltip,
            double_clicked=command_double_clicked,
            context_menu_requested=command_context_menu_requested,
            drag_drop=True,
        )
        self.quick_file_list = create_quick_file_list(
            parent,
            tooltip=file_tooltip,
            double_clicked=file_double_clicked,
            context_menu_requested=file_context_menu_requested,
            drag_drop=True,
        )
        self.quick_history_list = create_quick_history_list(
            parent,
            tooltip="Click the arrow to resend a previous command.",
            context_menu_requested=history_context_menu_requested,
        )

        # Inline row affordance: select the clicked row, then run the primary action.
        self.quick_command_list.actionTriggered.connect(
            lambda item: self._trigger_inline(self.quick_command_list, item, actions.command_primary)
        )
        self.quick_file_list.actionTriggered.connect(
            lambda item: self._trigger_inline(self.quick_file_list, item, actions.file_primary)
        )
        if history_primary is not None:
            self.quick_history_list.actionTriggered.connect(lambda item: history_primary(item.text()))
            self.quick_history_list.itemDoubleClicked.connect(lambda item: history_primary(item.text()))

        self.quick_sort_combo = self._command_sort_combo(parent)
        if command_sort_changed is not None:
            self.quick_sort_combo.currentIndexChanged.connect(command_sort_changed)
        self.quick_group_button = self._group_button(parent)
        command_controls = self._command_controls(parent)

        self.quick_file_sort_combo = self._file_sort_combo(parent)
        if file_sort_changed is not None:
            self.quick_file_sort_combo.currentIndexChanged.connect(file_sort_changed)

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
            header_icon=QStyle.StandardPixmap.SP_CommandLink,
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
                ]),
            ),
            controls=command_controls,
            parent=parent,
        )
        file_page = QuickActionsPanel(
            title=file_title,
            quick_list=self.quick_file_list,
            header_icon=QStyle.StandardPixmap.SP_DirOpenIcon,
            header_buttons=(
                self._header_button("+", "Add file", actions.add_file, parent),
                self._overflow_button(parent, [
                    ("Edit", actions.edit_file),
                    ("Delete", actions.delete_file),
                    None,
                    ("Move up", actions.move_file_up),
                    ("Move down", actions.move_file_down),
                    None,
                    ("Import CSV…", actions.import_files),
                    ("Export CSV…", actions.export_files),
                ]),
            ),
            controls=self.quick_file_sort_combo,
            parent=parent,
        )

        history_page = QuickActionsPanel(
            title="History",
            quick_list=self.quick_history_list,
            header_icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
            parent=parent,
        )
        sections = {"command": command_page, "file": file_page, "history": history_page}
        # Rail glyphs match the handoff RAIL map: all=terminal, qs=bolt, files=file, history=clock.
        rail_modes = [
            QuickActionsRailMode("all", QStyle.StandardPixmap.SP_ComputerIcon, "All quick actions", ("command", "file")),
            QuickActionsRailMode("commands", QStyle.StandardPixmap.SP_CommandLink, "Quick commands", ("command",)),
            QuickActionsRailMode("files", QStyle.StandardPixmap.SP_DirOpenIcon, "Quick files", ("file",)),
        ]
        if include_history:
            rail_modes.append(
                QuickActionsRailMode("history", QStyle.StandardPixmap.SP_FileDialogInfoView, "History", ("history",))
            )

        self._connect_list_signals(
            command_order_changed=command_order_changed,
            file_order_changed=file_order_changed,
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
        for quick_list in (self.quick_command_list, self.quick_file_list, self.quick_history_list):
            quick_list.apply_theme_palette(palette)

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

    def _overflow_button(self, parent: QWidget | None, items: list) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("quickPanelHeaderButton")
        button.setText("⋯")  # horizontal ellipsis
        button.setToolTip("More actions")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for entry in items:
            if entry is None:
                menu.addSeparator()
                continue
            label, callback = entry
            action = QAction(label, menu)
            action.triggered.connect(lambda _checked=False, cb=callback: cb())
            menu.addAction(action)
        button.setMenu(menu)
        button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
        return button

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

    def _group_button(self, parent: QWidget | None) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("drawerMenuButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setToolTip("Show or hide quick command groups")
        set_button_icon(button, QStyle.StandardPixmap.SP_FileDialogListView)
        return button

    def _command_controls(self, parent: QWidget | None) -> QWidget:
        from PySide6.QtWidgets import QHBoxLayout

        controls = QWidget(parent)
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.quick_sort_combo, 1)
        layout.addWidget(self.quick_group_button, 1)
        return controls

    def _connect_list_signals(
        self,
        *,
        command_order_changed: Callable[[], None] | None,
        file_order_changed: Callable[[], None] | None,
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
