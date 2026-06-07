"""A floating find / find+replace overlay, shared by the terminal and the editor.

The overlay is pure chrome: it owns the search/replace fields, the case toggle,
the match count and the nav buttons, and emits navigation signals. The host owns
the document + highlighting and drives the actual search, reading the overlay's
fields and pushing the match count back. It floats over an anchor widget (the
terminal / editor text area), top-right, and repositions on resize.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icons import set_button_icon


class SearchOverlay(QFrame):
    findNext = Signal()
    findPrevious = Signal()
    replaceOne = Signal()
    replaceAll = Signal()
    closeRequested = Signal()

    def __init__(
        self,
        anchor: QWidget,
        *,
        with_replace: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent or anchor.parentWidget() or anchor)
        self.setObjectName("searchOverlay")
        self._anchor = anchor
        self._with_replace = with_replace
        self._margin = 10

        self._replace_shown = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 7, 8, 7)
        outer.setSpacing(6)

        # --- find row: [>] [field] [Aa] [n/m] [^] [v] [x] ---
        find_row = QHBoxLayout()
        find_row.setSpacing(5)
        # A chevron that expands/collapses the replace row (in addition to Ctrl+H).
        self.toggle_button: QToolButton | None = None
        if with_replace:
            self.toggle_button = self._icon_button("chevron-right", "Toggle Replace (Ctrl+H)")
            self.toggle_button.clicked.connect(lambda: self.set_replace_visible(not self._replace_shown))
            find_row.addWidget(self.toggle_button)
        self.search_field = QLineEdit(self)
        self.search_field.setObjectName("searchOverlayField")
        self.search_field.setPlaceholderText("Find")
        self.search_field.installEventFilter(self)
        self.case_button = self._text_button("Aa", "Match case", checkable=True)
        self.count_label = QLabel("", self)
        self.count_label.setObjectName("searchOverlayCount")
        self.count_label.setMinimumWidth(36)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_button = self._icon_button("chevron-up", "Previous match (Shift+Enter)")
        self.next_button = self._icon_button("chevron-down", "Next match (Enter)")
        self.close_button = self._icon_button("x", "Close (Esc)")
        self.prev_button.clicked.connect(self.findPrevious)
        self.next_button.clicked.connect(self.findNext)
        self.close_button.clicked.connect(self._close)
        for widget in (
            self.search_field,
            self.case_button,
            self.count_label,
            self.prev_button,
            self.next_button,
            self.close_button,
        ):
            find_row.addWidget(widget, 1 if widget is self.search_field else 0)
        outer.addLayout(find_row)

        # --- replace row: [field] [replace] [all] ---
        self.replace_field = QLineEdit(self)
        self.replace_field.setObjectName("searchOverlayField")
        self.replace_field.setPlaceholderText("Replace")
        self.replace_field.installEventFilter(self)
        self.replace_one_button = self._icon_button("replace", "Replace")
        self.replace_all_button = self._text_button("all", "Replace all")
        self.replace_one_button.clicked.connect(self.replaceOne)
        self.replace_all_button.clicked.connect(self.replaceAll)
        replace_row = QHBoxLayout()
        replace_row.setSpacing(5)
        replace_row.addWidget(self.replace_field, 1)
        replace_row.addWidget(self.replace_one_button)
        replace_row.addWidget(self.replace_all_button)
        self._replace_holder = QWidget(self)
        self._replace_holder.setLayout(replace_row)
        outer.addWidget(self._replace_holder)

        self.set_replace_visible(with_replace)
        anchor.installEventFilter(self)
        self.hide()

    # ------------------------------------------------------------------ API ---
    def open_for(self, seed: str = "", *, replace: bool | None = None) -> None:
        if replace is not None:
            self.set_replace_visible(replace)
        if seed:
            self.search_field.setText(seed)
        self.show()
        self.reposition()
        self.raise_()
        self.search_field.setFocus()
        self.search_field.selectAll()

    def set_replace_visible(self, visible: bool) -> None:
        self._replace_shown = bool(visible) and self._with_replace
        self._replace_holder.setVisible(self._replace_shown)
        if self.toggle_button is not None:
            set_button_icon(
                self.toggle_button, "chevron-down" if self._replace_shown else "chevron-right", 13
            )
        self.adjustSize()
        self.reposition()

    def set_count(self, text: str) -> None:
        self.count_label.setText(text)

    def is_case_sensitive(self) -> bool:
        return self.case_button.isChecked()

    def reposition(self) -> None:
        if self._anchor is None:
            return
        self.adjustSize()
        geo = self._anchor.geometry()  # anchor rect in the shared parent's coords
        x = geo.right() - self.width() - self._margin
        y = geo.top() + self._margin
        self.move(max(geo.left() + self._margin, x), y)

    # ------------------------------------------------------------ internals ---
    def _close(self) -> None:
        self.hide()
        self.closeRequested.emit()

    def _text_button(self, text: str, tip: str, *, checkable: bool = False) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("searchOverlayButton")
        button.setText(text)
        button.setToolTip(tip)
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def _icon_button(self, icon: str, tip: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("searchOverlayIcon")
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        set_button_icon(button, icon, 13)
        return button

    def eventFilter(self, watched, event) -> bool:
        if watched is self._anchor:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show) and self.isVisible():
                self.reposition()
        elif watched in (self.search_field, self.replace_field) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._close()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.findPrevious.emit()
                else:
                    self.findNext.emit()
                return True
        return super().eventFilter(watched, event)
