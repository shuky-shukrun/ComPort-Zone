from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QSplitter, QVBoxLayout, QWidget

from .tab_workspace import TerminalTabWidget
from .tokens import SPLITTER_HANDLE


TAB_MIME_TYPE = "application/x-comport-zone-tab"


@dataclass(frozen=True, slots=True)
class WorkspaceTabRef:
    pane: TerminalTabWidget
    local_index: int
    global_index: int
    widget: QWidget


class SplitWorkspaceWidget(QWidget):
    newTabRequested = Signal()
    newTabMenuRequested = Signal(QPoint)
    currentChanged = Signal(int)
    tabContextMenuRequested = Signal(QPoint)
    tabMovedBetweenPanes = Signal(QWidget, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(SPLITTER_HANDLE)
        self._panes: list[TerminalTabWidget] = []
        self._active_pane: TerminalTabWidget | None = None
        # While a new-tab / tab context menu is open this pins the pane that asked
        # for it, so addTab targets that pane even if a focus event flips the active
        # pane while the modal menu is up (otherwise a new tab opened from the right
        # pane's + can land in the left pane). See _tab_creation_pinned_to.
        self._pending_tab_pane: TerminalTabWidget | None = None
        self._drag_start: dict[TerminalTabWidget, QPoint] = {}
        self.drop_preview = QLabel(self)
        self.drop_preview.setObjectName("splitDropPreview")
        self.drop_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_preview.setText("Release to move tab into the other pane")
        self.drop_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.drop_preview.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self._create_pane()

    def panes(self) -> list[TerminalTabWidget]:
        return list(self._panes)

    def active_pane(self) -> TerminalTabWidget:
        if self._active_pane in self._panes:
            return self._active_pane
        return self._panes[0]

    @property
    def new_tab_button(self):
        return self.active_pane().new_tab_button

    def pane_count(self) -> int:
        return len(self._panes)

    def setDocumentMode(self, enabled: bool) -> None:
        for pane in self._panes:
            pane.setDocumentMode(enabled)

    def setMovable(self, enabled: bool) -> None:
        for pane in self._panes:
            pane.setMovable(enabled)

    def setTabsClosable(self, enabled: bool) -> None:
        for pane in self._panes:
            pane.setTabsClosable(enabled)

    def setUsesScrollButtons(self, enabled: bool) -> None:
        for pane in self._panes:
            pane.setUsesScrollButtons(enabled)

    def tabBar(self):
        return self.active_pane().tabBar()

    def count(self) -> int:
        return sum(pane.count() for pane in self._panes)

    def currentIndex(self) -> int:
        pane = self.active_pane()
        local_index = pane.currentIndex()
        if local_index < 0:
            return -1
        return self._global_index(pane, local_index)

    def currentWidget(self) -> QWidget | None:
        return self.active_pane().currentWidget()

    def setCurrentIndex(self, index: int) -> None:
        ref = self.tab_ref(index)
        if ref is None:
            return
        self._set_active_pane(ref.pane)
        ref.pane.setCurrentIndex(ref.local_index)
        self.currentChanged.emit(index)

    def setCurrentWidget(self, widget: QWidget) -> None:
        index = self.indexOf(widget)
        if index >= 0:
            self.setCurrentIndex(index)

    def widget(self, index: int) -> QWidget | None:
        ref = self.tab_ref(index)
        return ref.widget if ref else None

    def indexOf(self, widget: QWidget) -> int:
        for ref in self.iter_tab_refs():
            if ref.widget is widget:
                return ref.global_index
        return -1

    def addTab(self, widget: QWidget, *args) -> int:
        # Honor a pane pinned by an in-flight new-tab menu; fall back to the active
        # pane for every other caller (restore, duplicate, programmatic adds).
        pane = self._pending_tab_pane if self._pending_tab_pane in self._panes else self.active_pane()
        self._pending_tab_pane = None
        index = pane.addTab(widget, *args)
        self._watch_tab_content(widget)
        self._set_active_pane(pane)
        return self._global_index(pane, index)

    def removeTab(self, index: int) -> None:
        ref = self.tab_ref(index)
        if ref is None:
            return
        ref.pane.removeTab(ref.local_index)
        self._remove_empty_secondary_panes()

    def tabText(self, index: int) -> str:
        ref = self.tab_ref(index)
        return ref.pane.tabText(ref.local_index) if ref else ""

    def setTabText(self, index: int, text: str) -> None:
        ref = self.tab_ref(index)
        if ref:
            ref.pane.setTabText(ref.local_index, text)

    def setTabIcon(self, index: int, icon) -> None:
        ref = self.tab_ref(index)
        if ref:
            ref.pane.setTabIcon(ref.local_index, icon)

    def setTabToolTip(self, index: int, text: str) -> None:
        ref = self.tab_ref(index)
        if ref:
            ref.pane.setTabToolTip(ref.local_index, text)

    def split_current_right(self) -> bool:
        return self.move_tab_to_other_pane(self.currentIndex(), orientation=Qt.Orientation.Horizontal)

    def split_current_down(self) -> bool:
        return self.move_tab_to_other_pane(self.currentIndex(), orientation=Qt.Orientation.Vertical)

    def move_tab_to_other_pane(self, index: int, *, orientation: Qt.Orientation = Qt.Orientation.Horizontal) -> bool:
        ref = self.tab_ref(index)
        if ref is None:
            return False
        target = self._ensure_other_pane(ref.pane, orientation)
        return self._move_ref_to_pane(ref, target, collapse_empty_source=False)

    def join_panes(self) -> bool:
        if len(self._panes) < 2:
            return False
        primary = self._panes[0]
        for pane in list(self._panes[1:]):
            while pane.count():
                widget = pane.widget(0)
                text = pane.tabText(0)
                icon = pane.tabIcon(0)
                tooltip = pane.tabToolTip(0)
                pane.removeTab(0)
                index = primary.addTab(widget, icon, text)
                primary.setTabToolTip(index, tooltip)
                self.tabMovedBetweenPanes.emit(widget, self._global_index(primary, index))
            self._remove_pane(pane)
        self._set_active_pane(primary)
        if primary.count():
            primary.setCurrentIndex(min(primary.currentIndex(), primary.count() - 1))
        self.currentChanged.emit(self.currentIndex())
        return True

    def configure_layout(
        self,
        *,
        orientation: Qt.Orientation,
        active_pane: int = 0,
        splitter_sizes: list[int] | None = None,
    ) -> None:
        self.splitter.setOrientation(orientation)
        while len(self._panes) < 2:
            self._create_pane()
        if splitter_sizes:
            self.splitter.setSizes(splitter_sizes)
        self._set_active_pane(self._panes[max(0, min(active_pane, len(self._panes) - 1))])

    def iter_tab_refs(self) -> list[WorkspaceTabRef]:
        refs: list[WorkspaceTabRef] = []
        global_index = 0
        for pane in self._panes:
            for local_index in range(pane.count()):
                widget = pane.widget(local_index)
                if widget is not None:
                    refs.append(WorkspaceTabRef(pane, local_index, global_index, widget))
                global_index += 1
        return refs

    def tab_ref(self, index: int) -> WorkspaceTabRef | None:
        if index < 0:
            return None
        for ref in self.iter_tab_refs():
            if ref.global_index == index:
                return ref
        return None

    def pane_index(self, pane: TerminalTabWidget) -> int:
        try:
            return self._panes.index(pane)
        except ValueError:
            return -1

    def set_active_pane_index(self, pane_index: int) -> None:
        if not self._panes:
            return
        self._set_active_pane(self._panes[max(0, min(pane_index, len(self._panes) - 1))])

    def _create_pane(self) -> TerminalTabWidget:
        pane = TerminalTabWidget(self)
        pane.setDocumentMode(True)
        pane.setMovable(True)
        pane.setTabsClosable(False)
        pane.setUsesScrollButtons(True)
        pane.newTabRequested.connect(lambda source=pane: self._new_tab_requested(source))
        pane.newTabMenuRequested.connect(
            lambda position, source=pane: self._new_tab_menu_requested(source, position)
        )
        pane.currentChanged.connect(lambda _index, source=pane: self._pane_current_changed(source))
        pane.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        pane.tabBar().customContextMenuRequested.connect(
            lambda position, source=pane: self._tab_context_requested(source, position)
        )
        pane.tabBar().installEventFilter(self)
        self._panes.append(pane)
        self.splitter.addWidget(pane)
        if self._active_pane is None:
            self._active_pane = pane
        return pane

    def _set_active_pane(self, pane: TerminalTabWidget) -> None:
        if pane in self._panes:
            self._active_pane = pane
            self._refresh_active_pane_styles()

    def _activate_pane(self, pane: TerminalTabWidget) -> None:
        if pane not in self._panes:
            return
        was_active = self._active_pane is pane
        self._active_pane = pane
        self._refresh_active_pane_styles()
        if not was_active:
            self.currentChanged.emit(self.currentIndex())

    def _refresh_active_pane_styles(self) -> None:
        for pane in self._panes:
            pane.setProperty("activePane", pane is self._active_pane)
            pane.style().unpolish(pane)
            pane.style().polish(pane)
            pane.update()

    def _pane_current_changed(self, pane: TerminalTabWidget) -> None:
        self._set_active_pane(pane)
        self.currentChanged.emit(self.currentIndex())

    @contextmanager
    def _tab_creation_pinned_to(self, pane: TerminalTabWidget) -> Iterator[None]:
        """Pin ``pane`` as the addTab target while a (modal) tab menu is open.

        The menu signals below are emitted synchronously and run their menu's
        ``exec`` inline, so any new tab the user chooses is created before the
        context exits — restoring the previous pin even if the menu is dismissed.
        """
        previous = self._pending_tab_pane
        self._pending_tab_pane = pane
        try:
            yield
        finally:
            self._pending_tab_pane = previous

    def _new_tab_requested(self, pane: TerminalTabWidget) -> None:
        self._set_active_pane(pane)
        with self._tab_creation_pinned_to(pane):
            self.newTabRequested.emit()

    def _new_tab_menu_requested(self, pane: TerminalTabWidget, position: QPoint) -> None:
        self._set_active_pane(pane)
        with self._tab_creation_pinned_to(pane):
            self.newTabMenuRequested.emit(position)

    def _tab_context_requested(self, pane: TerminalTabWidget, position: QPoint) -> None:
        self._set_active_pane(pane)
        with self._tab_creation_pinned_to(pane):
            self.tabContextMenuRequested.emit(position)

    def _global_index(self, pane: TerminalTabWidget, local_index: int) -> int:
        global_index = 0
        for candidate in self._panes:
            if candidate is pane:
                return global_index + local_index
            global_index += candidate.count()
        return -1

    def _ensure_other_pane(
        self,
        source: TerminalTabWidget,
        orientation: Qt.Orientation,
    ) -> TerminalTabWidget:
        self.splitter.setOrientation(orientation)
        if len(self._panes) == 1:
            pane = self._create_pane()
            self._balance_splitter_sizes()
            return pane
        return self._panes[1] if self._panes[0] is source else self._panes[0]

    def _balance_splitter_sizes(self) -> None:
        if len(self._panes) != 2:
            return
        total = sum(size for size in self.splitter.sizes() if size > 0)
        if total <= 0:
            total = self.width() if self.splitter.orientation() == Qt.Orientation.Horizontal else self.height()
        total = max(total, 2)
        first = max(1, total // 2)
        self.splitter.setSizes([first, max(1, total - first)])

    def _move_ref_to_pane(
        self,
        ref: WorkspaceTabRef,
        target: TerminalTabWidget,
        *,
        collapse_empty_source: bool = True,
    ) -> bool:
        if ref.pane is target:
            return False
        widget = ref.widget
        text = ref.pane.tabText(ref.local_index)
        icon = ref.pane.tabIcon(ref.local_index)
        tooltip = ref.pane.tabToolTip(ref.local_index)
        ref.pane.removeTab(ref.local_index)
        new_index = target.addTab(widget, icon, text)
        self._watch_tab_content(widget)
        target.setTabToolTip(new_index, tooltip)
        self.tabMovedBetweenPanes.emit(widget, self._global_index(target, new_index))
        target.setCurrentIndex(new_index)
        self._set_active_pane(target)
        if collapse_empty_source:
            self._remove_empty_secondary_panes()
        self.currentChanged.emit(self.currentIndex())
        return True

    def _remove_empty_secondary_panes(self) -> None:
        for pane in list(self._panes):
            if len(self._panes) > 1 and pane.count() == 0:
                self._remove_pane(pane)
        if not self._panes:
            self._create_pane()
        if self._active_pane not in self._panes:
            self._active_pane = self._panes[0]
        self._refresh_active_pane_styles()

    def _remove_pane(self, pane: TerminalTabWidget) -> None:
        if pane not in self._panes:
            return
        self._panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()

    def _watch_tab_content(self, widget: QWidget) -> None:
        for child in [widget, *widget.findChildren(QWidget)]:
            child.installEventFilter(self)

    def _pane_for_widget(self, widget: QWidget) -> TerminalTabWidget | None:
        current: QWidget | None = widget
        while current is not None:
            if current in self._panes:
                return current
            current = current.parentWidget()
        return None

    def _is_drawer_chrome(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        drawer_object_names = {"drawer", "drawerRail", "drawerPanel"}
        while current is not None:
            if current.objectName() in drawer_object_names:
                return True
            if current in self._panes:
                return False
            current = current.parentWidget()
        return False

    def eventFilter(self, watched, event) -> bool:
        if isinstance(watched, QWidget) and event.type() in {
            QEvent.Type.FocusIn,
            QEvent.Type.MouseButtonPress,
        } and not self._is_drawer_chrome(watched):
            pane = self._pane_for_widget(watched)
            if pane is not None:
                self._activate_pane(pane)
        for pane in self._panes:
            if watched is pane.tabBar():
                if event.type() == QEvent.Type.MouseButtonPress:
                    mouse_event = event
                    if isinstance(mouse_event, QMouseEvent) and mouse_event.button() == Qt.MouseButton.LeftButton:
                        self._activate_pane(pane)
                        self._drag_start[pane] = mouse_event.pos()
                elif event.type() == QEvent.Type.MouseMove:
                    mouse_event = event
                    if isinstance(mouse_event, QMouseEvent):
                        start = self._drag_start.get(pane)
                        if start is not None and (mouse_event.pos() - start).manhattanLength() >= QApplication.startDragDistance():
                            if pane.tabBar().rect().contains(mouse_event.pos()):
                                continue
                            index = pane.tabBar().tabAt(start)
                            if index >= 0:
                                self._start_tab_drag(pane, index)
                break
        return super().eventFilter(watched, event)

    def _start_tab_drag(self, pane: TerminalTabWidget, local_index: int) -> None:
        global_index = self._global_index(pane, local_index)
        if global_index < 0:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(TAB_MIME_TYPE, QByteArray(str(global_index).encode("ascii")))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(TAB_MIME_TYPE):
            self._show_drop_preview(event)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(TAB_MIME_TYPE):
            self._show_drop_preview(event)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.drop_preview.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.drop_preview.hide()
        if not event.mimeData().hasFormat(TAB_MIME_TYPE):
            super().dropEvent(event)
            return
        try:
            index = int(bytes(event.mimeData().data(TAB_MIME_TYPE)).decode("ascii"))
        except ValueError:
            return
        if self.move_tab_to_other_pane(index, orientation=Qt.Orientation.Horizontal):
            event.acceptProposedAction()

    def _event_position(self, event) -> QPoint:
        position = event.position() if hasattr(event, "position") else event.pos()
        return position.toPoint() if hasattr(position, "toPoint") else position

    def _dragged_ref_from_event(self, event) -> WorkspaceTabRef | None:
        try:
            index = int(bytes(event.mimeData().data(TAB_MIME_TYPE)).decode("ascii"))
        except (AttributeError, ValueError):
            return None
        return self.tab_ref(index)

    def _drop_preview_geometry(self, event) -> tuple[QRect, str]:
        dragged_ref = self._dragged_ref_from_event(event)
        if dragged_ref is not None:
            if len(self._panes) == 1:
                rect = self.rect()
                midpoint = max(1, rect.width() // 2)
                return QRect(midpoint, rect.top(), max(1, rect.width() - midpoint), rect.height()), "Release to split right"
            target = self._panes[1] if self._panes[0] is dragged_ref.pane else self._panes[0]
            return target.geometry(), "Release to move tab here"
        position = self._event_position(event)
        for pane in self._panes:
            if pane.geometry().contains(position):
                return pane.geometry(), "Release to move tab here"
        return self.rect(), "Release to move tab into the other pane"

    def _show_drop_preview(self, event) -> None:
        geometry, message = self._drop_preview_geometry(event)
        self.drop_preview.setText(message)
        self.drop_preview.setGeometry(geometry.adjusted(8, 8, -8, -8))
        self.drop_preview.raise_()
        self.drop_preview.show()
