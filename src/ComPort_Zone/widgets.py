from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTextEdit,
    QWidget,
)

from .command_completion import (
    ACCEPT,
    CANCEL,
    DISMISS,
    NAVIGATE,
    classify_completion_key,
    move_completion_selection,
    resolve_completion_text,
)
from .themes import VS_CODE_DARK


TERMINAL_COMPLETION_TOKEN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:*?.-")


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


def set_widget_state(widget: QWidget, state: str) -> None:
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def fit_overflow_groups(bar, fixed, groups, overflow_button, *, reserve: int = 16) -> list:
    """Hide trailing groups so a command bar's optional widgets fit its width.

    Shared by the terminal and editor command bars so both collapse the same way.

    - ``fixed``: widgets that always stay visible (e.g. Connect / Run).
    - ``groups``: lists of widgets ordered from FIRST-to-collapse to LAST. As the bar
      narrows, whole groups move into ``overflow_button``'s menu, highest priority
      (last group) kept visible longest.
    - ``overflow_button`` is shown whenever anything is collapsed.

    Widths come from each widget's ``sizeHint`` (valid even while hidden), so the bar
    expands again — un-hiding groups — as it widens. Returns the collapsed groups so
    the caller can populate the overflow menu accordingly.
    """
    layout = bar.layout()
    spacing = layout.spacing()
    margins = layout.contentsMargins()

    def width_of(widget) -> int:
        return widget.sizeHint().width() + spacing

    base = margins.left() + margins.right() + reserve + sum(width_of(w) for w in fixed)
    overflow_width = width_of(overflow_button)
    available = bar.width()

    collapsed = 0
    while collapsed < len(groups):
        remaining = [w for group in groups[collapsed:] for w in group]
        needed = base + sum(width_of(w) for w in remaining)
        if collapsed:
            needed += overflow_width
        if needed <= available:
            break
        collapsed += 1

    hidden = {w for group in groups[:collapsed] for w in group}
    for group in groups:
        for widget in group:
            widget.setVisible(widget not in hidden)
    overflow_button.setVisible(collapsed > 0)
    return groups[:collapsed]


def _line_height_format(percent: int) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setLineHeight(float(percent), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    return fmt


def apply_line_spacing(text_edit, percent: int) -> None:
    """Set a proportional line height (100 = the font's own leading) on the whole doc."""
    cursor = QTextCursor(text_edit.document())
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.mergeBlockFormat(_line_height_format(max(100, int(percent))))


class LineSpacingController:
    """Holds a QTextEdit/QPlainTextEdit at a chosen proportional line height.

    ``reactive`` keeps blocks that appear *programmatically* in sync via the
    document's ``contentsChange`` signal — the terminal streams new transcript
    lines that way. The editor passes ``reactive=False``: re-formatting a block
    inside ``contentsChange`` pushes a stray entry onto the undo stack (and
    re-enters during an undo), which silently breaks Ctrl+Z. New lines the user
    types inherit the previous block's height anyway, so the editor only needs a
    one-shot apply on load / spacing change."""

    def __init__(self, text_edit, *, reactive: bool = True) -> None:
        self._edit = text_edit
        self._percent = 100
        self._applying = False
        self._reactive = reactive
        if reactive:
            text_edit.document().contentsChange.connect(self._on_contents_change)

    def set_percent(self, percent: int) -> None:
        self._percent = max(100, int(percent))
        self._guarded(lambda: apply_line_spacing(self._edit, self._percent))

    def reapply(self) -> None:
        """Re-apply the current spacing to the whole document — call after a
        programmatic ``setPlainText``, which resets every block to default height."""
        if self._percent > 100:
            self._guarded(lambda: apply_line_spacing(self._edit, self._percent))

    def _on_contents_change(self, position: int, _removed: int, added: int) -> None:
        if self._applying or self._percent <= 100:
            return

        def run() -> None:
            document = self._edit.document()
            last = max(0, document.characterCount() - 1)
            cursor = QTextCursor(document)
            cursor.setPosition(min(position, last))
            cursor.setPosition(min(position + max(added, 0), last), QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeBlockFormat(_line_height_format(self._percent))

        self._guarded(run)

    def _guarded(self, work) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            work()
        finally:
            self._applying = False


# Cap the terminal's draft undo history so a long editing session can't grow it
# without bound (each entry is just a short command line + caret offset).
DRAFT_UNDO_LIMIT = 200


class HistoryLineEdit(QLineEdit):
    historyRequested = Signal(int)
    autocompleteRequested = Signal()
    deleteHistoryRequested = Signal()

    def keyPressEvent(self, event) -> None:
        popup = self.completer().popup() if self.completer() else None
        popup_visible = bool(popup and popup.isVisible())
        if (
            event.key() == Qt.Key.Key_Delete
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.deleteHistoryRequested.emit()
            return
        if event.key() == Qt.Key.Key_Up and not popup_visible:
            self.historyRequested.emit(-1)
            return
        if event.key() == Qt.Key.Key_Down and not popup_visible:
            self.historyRequested.emit(1)
            return
        if (
            event.key() == Qt.Key.Key_Space
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.autocompleteRequested.emit()
            return
        super().keyPressEvent(event)


class CompletionPopupDelegate(QStyledItemDelegate):
    """Renders autocomplete rows as ``command   description`` — the command in the
    terminal ink, the (optional) description muted gray — mirroring the side-panel
    rows. It paints with the popup's font, which tracks the terminal font size."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._descriptions: dict[str, str] = {}
        self._text_color = VS_CODE_DARK.text
        self._description_color = "#6b7689"
        self._selection_color = "#264f78"
        self._hover_color = "#2a2d2e"

    def set_descriptions(self, mapping) -> None:
        self._descriptions = {str(k): str(v) for k, v in dict(mapping or {}).items()}

    def set_colors(self, *, text: str, description: str, selection: str, hover: str) -> None:
        self._text_color = text
        self._description_color = description
        self._selection_color = selection
        self._hover_color = hover

    def _command(self, index) -> str:
        return str(index.data(Qt.ItemDataRole.DisplayRole) or "")

    def _description(self, index) -> str:
        return self._descriptions.get(self._command(index), "")

    def sizeHint(self, option, index) -> QSize:
        fm = QFontMetrics(option.font)
        # Tight: left margin + right margin (no description) / + gap + right (with).
        width = fm.horizontalAdvance(self._command(index)) + 18
        description = self._description(index)
        if description:
            width += fm.horizontalAdvance(description) + 16
        return QSize(min(width, 560), max(20, fm.height() + 4))

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._selection_color if selected else self._hover_color))
            painter.drawRoundedRect(rect.adjusted(3, 1, -3, -1), 5, 5)

        font = option.font
        painter.setFont(font)
        fm = QFontMetrics(font)
        left = rect.left() + 10
        right = rect.right() - 8
        avail = max(10, right - left)
        command = self._command(index)
        shown = fm.elidedText(command, Qt.TextElideMode.ElideRight, avail)
        painter.setPen(QColor(self._text_color))
        painter.drawText(
            QRect(left, rect.top(), avail, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            shown,
        )
        description = self._description(index)
        # Only show the description when the command itself wasn't elided away.
        if description and fm.horizontalAdvance(shown) >= fm.horizontalAdvance(command):
            dx = left + fm.horizontalAdvance(command) + 12
            if dx < right - 16:
                shown_desc = fm.elidedText(description, Qt.TextElideMode.ElideRight, right - dx)
                painter.setPen(QColor(self._description_color))
                painter.drawText(
                    QRect(dx, rect.top(), right - dx, rect.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    shown_desc,
                )
        painter.restore()


def style_completion_popup(popup, *, background: str, border: str, radius: int = 8) -> None:
    """Style an autocomplete popup's frame to match the project's panels (the
    rows themselves are painted by :class:`CompletionPopupDelegate`). Applied
    directly to the popup because the window-level stylesheet doesn't cascade to
    the completer's top-level popup."""
    popup.setObjectName("completionPopup")
    # No QSS padding: QCompleter sizes the popup from the delegate's row hints and
    # doesn't account for frame padding, so any padding overflows the viewport and
    # forces a scrollbar (which then clips the description column). The rows carry
    # their own inset via the delegate instead.
    popup.setStyleSheet(
        f"QListView#completionPopup {{ background: {background};"
        f" border: 1px solid {border}; border-radius: {radius}px; padding: 0px; outline: none; }}"
        "QListView#completionPopup::item { border: none; padding: 0px; }"
        "QListView#completionPopup QScrollBar:vertical { width: 9px; background: transparent; margin: 2px; }"
        f"QListView#completionPopup QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 20px; }}"
        "QListView#completionPopup QScrollBar::add-line, QListView#completionPopup QScrollBar::sub-line { height: 0; }"
    )


class IntegratedTerminalEdit(QTextEdit):
    returnPressed = Signal()
    historyRequested = Signal(int)
    autocompleteRequested = Signal()
    deleteHistoryRequested = Signal()
    textEdited = Signal(str)

    # Bare chevron until a tab supplies its name + timestamp state via
    # ``set_prompt_text`` — see ``terminal_view.prompt_leader_text``.
    DEFAULT_PROMPT = "> "

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._completer = None
        self._prompt_start = 0
        self._draft_start = 0
        self.prompt = self.DEFAULT_PROMPT
        self._placeholder = ""
        self._prompt_color = VS_CODE_DARK.tx
        self._draft_color = VS_CODE_DARK.tx
        self._transcript_color = VS_CODE_DARK.text
        # Muted ink for the placeholder hint + the inline completion ghost.
        self._hint_color = "#6b7689"
        self._ghost_color = "#6b7689"
        # Autocomplete popup: a delegate that paints command + grey description,
        # plus the command->description map / colours it draws with.
        self._completion_delegate: CompletionPopupDelegate | None = None
        self._completion_descriptions: dict[str, str] = {}
        self._completion_palette: dict[str, str] | None = None
        self.font_zoom_callback: Callable[[int], None] | None = None
        self.setAcceptRichText(False)
        # Native undo is unusable here: the transcript, prompt and draft share one
        # document, so QTextEdit's undo would rewind committed output. We keep a
        # small draft-only history instead (see undo/redo below).
        self.setUndoRedoEnabled(False)
        self._draft_undo: list[tuple[str, int]] = []
        self._draft_redo: list[tuple[str, int]] = []
        self._draft_undo_kind: str | None = None
        self.setAcceptDrops(False)
        self._line_spacing = LineSpacingController(self)
        self._replace_document("", "", 0)

    def set_line_spacing(self, percent: int) -> None:
        """Set the line spacing as a percentage of the font's natural line height."""
        self._line_spacing.set_percent(percent)

    def set_terminal_colors(self, *, prompt: str, draft: str, hint: str | None = None) -> None:
        self._prompt_color = prompt
        self._draft_color = prompt
        self._transcript_color = draft
        if hint is not None:
            self._hint_color = hint
            self._ghost_color = hint
        self._reformat_prompt_and_draft()
        self.viewport().update()

    def set_prompt_color(self, color: str) -> None:
        """Recolor only the prompt leader (the ``<tab>  >`` run), leaving the typed
        draft and committed transcript untouched — used to flag auto-reconnect amber
        at the cursor without tinting whatever the user is mid-typing."""
        if color == self._prompt_color:
            return
        self._prompt_color = color
        self._reformat_prompt_and_draft()
        self.viewport().update()

    def set_prompt_text(self, text: str) -> None:
        """Swap the prompt leader (e.g. ``COM3   >``) in place, keeping the
        committed transcript's colours, the draft text, and the caret offset —
        unlike a full re-render, which would flatten the transcript to one ink."""
        text = str(text)
        if text == self.prompt:
            return
        draft_offset = self.cursorPosition()
        self.prompt = text
        prompt_start = self._safe_prompt_start()
        cursor = QTextCursor(self.document())
        cursor.setPosition(prompt_start)
        cursor.setPosition(self._safe_draft_start(), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text, self._format(self._prompt_color))
        self._draft_start = prompt_start + len(text)
        self.setCursorPosition(draft_offset)
        self.viewport().update()

    def setCompleter(self, completer) -> None:
        self._completer = completer
        completer.setWidget(self)
        popup = completer.popup()
        self._completion_delegate = CompletionPopupDelegate(popup)
        self._completion_delegate.set_descriptions(self._completion_descriptions)
        if self._completion_palette is not None:
            self._completion_delegate.set_colors(**self._completion_palette)
        popup.setItemDelegate(self._completion_delegate)
        popup.setFont(self.font())
        popup.setObjectName("completionPopup")
        self._apply_completion_popup_style()
        popup.installEventFilter(self)
        completer.highlighted.connect(self._refresh_inline_overlay)

    def set_completion_descriptions(self, mapping) -> None:
        """Map command text -> description for the popup's grey secondary column."""
        self._completion_descriptions = {str(k): str(v) for k, v in dict(mapping or {}).items()}
        if self._completion_delegate is not None:
            self._completion_delegate.set_descriptions(self._completion_descriptions)
            if self._completer is not None:
                self._completer.popup().viewport().update()

    def set_completion_colors(
        self,
        *,
        text: str,
        description: str,
        selection: str,
        hover: str,
        background: str,
        border: str,
    ) -> None:
        """Theme the popup: row ink (delegate) + the popup frame (direct QSS)."""
        self._completion_palette = {
            "text": text,
            "description": description,
            "selection": selection,
            "hover": hover,
            "background": background,
            "border": border,
        }
        if self._completion_delegate is not None:
            self._completion_delegate.set_colors(
                text=text, description=description, selection=selection, hover=hover
            )
        self._apply_completion_popup_style()

    def _apply_completion_popup_style(self) -> None:
        if self._completer is None or self._completion_palette is None:
            return
        palette = self._completion_palette
        style_completion_popup(
            self._completer.popup(),
            background=palette["background"],
            border=palette["border"],
        )

    def set_font_zoom_callback(self, callback: Callable[[int], None]) -> None:
        self.font_zoom_callback = callback

    def completer(self):
        return self._completer

    def setPlaceholderText(self, text: str) -> None:
        # The document always holds the prompt, so Qt's native placeholder never
        # fires — we store the hint and paint it ourselves (see ``paintEvent``).
        self._placeholder = str(text or "")
        self.viewport().update()

    def placeholderText(self) -> str:
        return self._placeholder

    def toPlainText(self) -> str:
        return super().toPlainText()[: self._safe_prompt_start()]

    def display_text(self) -> str:
        return super().toPlainText()

    def setPlainText(self, text: str) -> None:
        draft = self.text() if self._has_prompt() else ""
        self._replace_document(str(text), draft, min(self.cursorPosition(), len(draft)))

    def append_committed_text(self, text: str, color: str) -> None:
        if not text:
            return
        draft = self.text()
        cursor_offset = self.cursorPosition()
        self._remove_prompt()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, self._format(color))
        self._insert_prompt(draft, cursor_offset)
        self.ensureCursorVisible()

    def append_committed_runs(self, runs, *, hang_indent: float = 0.0) -> None:
        """Append colored runs ``(text, color[, italic])`` to the committed
        transcript (before the prompt). When ``hang_indent`` (px) is set, the block
        where insertion begins gets a hanging indent so soft-wrapped lines align
        under the message column — the mockup's timestamp/direction layout."""
        runs = [run for run in runs if run and run[0]]
        if not runs:
            return
        draft = self.text()
        cursor_offset = self.cursorPosition()
        self._remove_prompt()
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if hang_indent > 0:
            block_format = QTextBlockFormat()
            block_format.setLeftMargin(hang_indent)
            block_format.setTextIndent(-hang_indent)
            cursor.mergeBlockFormat(block_format)
        for run in runs:
            color = run[1]
            italic = run[2] if len(run) > 2 else False
            cursor.insertText(run[0], self._format(color, italic=italic))
        self._insert_prompt(draft, cursor_offset)
        self.ensureCursorVisible()

    def clear_transcript(self, *, clear_draft: bool = False) -> None:
        draft = "" if clear_draft else self.text()
        self._replace_document("", draft, len(draft))

    def clear(self) -> None:
        self.setText("")

    def text(self) -> str:
        full_text = super().toPlainText()
        start = self._safe_draft_start()
        return full_text[start:]

    def setText(self, text: str) -> None:
        # Programmatic draft swaps (history recall, clearing after send) start a fresh
        # context — drop the per-keystroke undo history so Ctrl+Z can't cross them.
        self._reset_draft_history()
        self._replace_draft(str(text), len(str(text)))

    def cursorPosition(self) -> int:
        cursor = self.textCursor()
        return max(0, min(cursor.position() - self._safe_draft_start(), len(self.text())))

    def setCursorPosition(self, position: int) -> None:
        position = max(0, min(position, len(self.text())))
        cursor = self.textCursor()
        cursor.setPosition(self._safe_draft_start() + position)
        self.setTextCursor(cursor)

    def token_under_cursor(self) -> str:
        draft = self.text()
        position = self.cursorPosition()
        start = position
        while start > 0 and draft[start - 1] in TERMINAL_COMPLETION_TOKEN_CHARS:
            start -= 1
        end = position
        while end < len(draft) and draft[end] in TERMINAL_COMPLETION_TOKEN_CHARS:
            end += 1
        return draft[start:end]

    def insert_completion(self, completion: str) -> None:
        completion = str(completion)
        if not completion:
            return
        self._ensure_cursor_in_draft()
        cursor = self.textCursor()
        token = self.token_under_cursor()
        if token:
            start = max(self._safe_draft_start(), cursor.position() - len(token))
            cursor.setPosition(start, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(completion, self._format(self._draft_color))
        self.setTextCursor(cursor)
        self.textEdited.emit(self.text())

    def accept_current_completion(self) -> None:
        if not self._completer:
            return
        completion = resolve_completion_text(self._completer)
        if completion:
            self.insert_completion(completion)
        self._completer.popup().hide()

    def _handle_return_key(self, modifiers: Qt.KeyboardModifiers) -> None:
        if self._completer:
            self._completer.popup().hide()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._insert_draft_text("\n")
            return
        self.returnPressed.emit()

    def navigate_completion(self, key: Qt.Key) -> None:
        move_completion_selection(self._completer, key)
        self._refresh_inline_overlay()

    def show_completions(self, *, forced: bool = False) -> None:
        if not self._completer:
            return
        token = self.token_under_cursor()
        if not forced and len(token) < 2:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(token)
        if self._completer.completionCount() <= 0:
            self._completer.popup().hide()
            return
        popup = self._completer.popup()
        # Match the popup (and its delegate) to the terminal's current font size.
        popup.setFont(self.font())
        first_index = self._completer.completionModel().index(0, 0)
        if first_index.isValid():
            self._completer.setCurrentRow(0)
            popup.setCurrentIndex(first_index)
        rect = self.cursorRect()
        # Widest row + the 1px frame border; reserve scrollbar width only if scrolling.
        width = popup.sizeHintForColumn(0) + 6
        if self._completer.completionModel().rowCount() > self._completer.maxVisibleItems():
            width += popup.verticalScrollBar().sizeHint().width()
        width = max(width, self.fontMetrics().horizontalAdvance(token) + 60)
        rect.setWidth(min(width, 560))
        rect.setHeight(rect.height() + 8)  # nudge the popup a little below the input line
        self._completer.complete(rect)
        self._refresh_inline_overlay()

    def selection_within_draft(self) -> bool:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return cursor.position() >= self._safe_draft_start()
        return min(cursor.position(), cursor.anchor()) >= self._safe_draft_start()

    def replace_selection_in_draft(self, replacement: str) -> bool:
        if not self.selection_within_draft():
            return False
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        cursor.insertText(replacement, self._format(self._draft_color))
        self.setTextCursor(cursor)
        self.textEdited.emit(self.text())
        return True

    def replace_selection_from_menu(self, replacement: str) -> bool:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        start = min(cursor.position(), cursor.anchor())
        end = max(cursor.position(), cursor.anchor())
        if start >= self._safe_draft_start():
            return self.replace_selection_in_draft(replacement)
        if end > self._safe_prompt_start():
            return False
        selected_length = end - start
        cursor.insertText(replacement, self._format(self._transcript_color))
        delta = len(replacement) - selected_length
        self._prompt_start += delta
        self._draft_start += delta
        self.setTextCursor(cursor)
        return True

    def copy(self) -> None:
        if self.textCursor().hasSelection():
            super().copy()
            return
        # No selection: copy the whole draft (the command line being typed) so Ctrl+C
        # grabs the line without first selecting it.
        if self.text():
            QApplication.clipboard().setText(self.text())

    def cut(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            if not self.selection_within_draft():
                self.copy()  # selection reaches into the read-only transcript — copy only
                return
            before = self.text()
            before_offset = self.cursorPosition()
            super().cut()
            if self.text() != before:
                self._record_draft_edit(before, before_offset, "cut")
                self.textEdited.emit(self.text())
            return
        # No selection: cut the whole draft line.
        if not self.text():
            return
        before = self.text()
        before_offset = self.cursorPosition()
        QApplication.clipboard().setText(self.text())
        self._replace_draft("", 0)
        self._record_draft_edit(before, before_offset, "cut")
        self.textEdited.emit(self.text())
        self._refresh_inline_overlay()

    def paste(self) -> None:
        clipboard = QApplication.clipboard()
        self._insert_draft_text(clipboard.text())

    def undo(self) -> None:
        if not self._draft_undo:
            return
        self._draft_redo.append((self.text(), self.cursorPosition()))
        text, offset = self._draft_undo.pop()
        self._draft_undo_kind = None
        self._replace_draft(text, offset)
        self.textEdited.emit(self.text())
        self._refresh_inline_overlay()

    def redo(self) -> None:
        if not self._draft_redo:
            return
        self._draft_undo.append((self.text(), self.cursorPosition()))
        text, offset = self._draft_redo.pop()
        self._draft_undo_kind = None
        self._replace_draft(text, offset)
        self.textEdited.emit(self.text())
        self._refresh_inline_overlay()

    def _record_draft_edit(self, before_text: str, before_offset: int, kind: str) -> None:
        """Snapshot the draft before an edit for Ctrl+Z. Consecutive same-kind
        typing/deleting coalesces into one step (like a native line edit); paste and
        cut always start a fresh step. Any new edit clears the redo history."""
        if kind in ("type", "delete") and kind == self._draft_undo_kind and self._draft_undo:
            self._draft_redo.clear()
            return
        self._draft_undo.append((before_text, before_offset))
        if len(self._draft_undo) > DRAFT_UNDO_LIMIT:
            self._draft_undo.pop(0)
        self._draft_redo.clear()
        self._draft_undo_kind = kind

    def _reset_draft_history(self) -> None:
        self._draft_undo.clear()
        self._draft_redo.clear()
        self._draft_undo_kind = None

    def insertFromMimeData(self, source) -> None:
        if source.hasText():
            self._insert_draft_text(source.text())

    def eventFilter(self, watched, event) -> bool:
        popup = self._completer.popup() if self._completer else None
        if (
            popup is not None
            and watched is popup
            and event.type() in (QEvent.Type.Show, QEvent.Type.Hide)
        ):
            # Repaint the terminal so the inline ghost preview appears with the
            # popup and clears the moment it dismisses.
            self._refresh_inline_overlay()
        if (
            popup is not None
            and watched is popup
            and event.type() == QEvent.Type.KeyPress
            and popup.isVisible()
        ):
            action = classify_completion_key(event.key())
            if action == NAVIGATE:
                self.navigate_completion(event.key())
                return True
            if action == ACCEPT:
                self.accept_current_completion()
                return True
            if action == DISMISS:
                # Enter submits the draft; it never accepts the highlighted suggestion.
                self._handle_return_key(event.modifiers())
                return True
            if action == CANCEL:
                popup.hide()
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event) -> None:
        if self.font_zoom_callback and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            self.font_zoom_callback(delta)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        popup = self._completer.popup() if self._completer else None
        popup_visible = bool(popup and popup.isVisible())
        if popup_visible:
            action = classify_completion_key(event.key())
            if action == NAVIGATE:
                self.navigate_completion(event.key())
                event.accept()
                return
            if action == ACCEPT:
                self.accept_current_completion()
                event.accept()
                return
            if action == DISMISS:
                # Enter submits the draft; it never accepts the highlighted suggestion.
                self._handle_return_key(event.modifiers())
                event.accept()
                return
            if action == CANCEL:
                popup.hide()
                event.accept()
                return

        if event.key() == Qt.Key.Key_Delete and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.deleteHistoryRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Up and not popup_visible:
            self.historyRequested.emit(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Down and not popup_visible:
            self.historyRequested.emit(1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.autocompleteRequested.emit()
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return}:
            self._handle_return_key(event.modifiers())
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.redo()
                else:
                    self.undo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_C:
                self.copy()
                event.accept()
                return
            if event.key() == Qt.Key.Key_A:
                self.selectAll()
                event.accept()
                return
            if event.key() == Qt.Key.Key_X:
                self.cut()
                event.accept()
                return
            if event.key() == Qt.Key.Key_V:
                self.paste()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Home:
            self._move_home(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            event.accept()
            return
        if event.key() == Qt.Key.Key_Backspace and not self.textCursor().hasSelection():
            if self.textCursor().position() <= self._safe_draft_start():
                event.accept()
                return
        if event.key() == Qt.Key.Key_Delete and not self.textCursor().hasSelection():
            if self.textCursor().position() < self._safe_draft_start():
                self.setCursorPosition(0)
                event.accept()
                return

        before = self.text()
        before_offset = self.cursorPosition()
        if self._is_editing_key(event):
            self._ensure_cursor_in_draft()
        super().keyPressEvent(event)
        after = self.text()
        if after != before:
            kind = "delete" if event.key() in {Qt.Key.Key_Backspace, Qt.Key.Key_Delete} else "type"
            self._record_draft_edit(before, before_offset, kind)
            self.textEdited.emit(after)
            if event.text() and event.text()[-1] in TERMINAL_COMPLETION_TOKEN_CHARS:
                self.show_completions()
            elif self._completer:
                self._completer.popup().hide()
            # Toggle the placeholder hint as the draft empties / fills.
            self._refresh_inline_overlay()

    def _replace_document(self, transcript: str, draft: str, cursor_offset: int) -> None:
        super().setPlainText("")
        if transcript:
            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(transcript, self._format(self._transcript_color))
        self._insert_prompt(draft, cursor_offset)

    def _replace_prompt_preserving_content(self) -> None:
        transcript = self.toPlainText()
        draft = self.text()
        cursor_offset = self.cursorPosition()
        self._replace_document(transcript, draft, cursor_offset)

    def _reformat_prompt_and_draft(self) -> None:
        current_cursor = self.textCursor()
        prompt_start = self._safe_prompt_start()
        draft_start = self._safe_draft_start()
        document_end = self._document_end_position()
        cursor = QTextCursor(self.document())
        if prompt_start < draft_start:
            cursor.setPosition(prompt_start)
            cursor.setPosition(draft_start, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(self._format(self._prompt_color))
        if draft_start < document_end:
            cursor.setPosition(draft_start)
            cursor.setPosition(document_end, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(self._format(self._draft_color))
        self.setTextCursor(current_cursor)

    def _insert_prompt(self, draft: str, cursor_offset: int) -> None:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._prompt_start = cursor.position()
        cursor.insertText(self.prompt, self._format(self._prompt_color))
        self._draft_start = cursor.position()
        cursor.insertText(draft, self._format(self._draft_color))
        cursor_offset = max(0, min(cursor_offset, len(draft)))
        cursor.setPosition(self._draft_start + cursor_offset)
        self.setTextCursor(cursor)

    def _remove_prompt(self) -> None:
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._safe_prompt_start())
        cursor.setPosition(self._document_end_position(), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()

    def _replace_draft(self, text: str, cursor_offset: int) -> None:
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._safe_draft_start())
        cursor.setPosition(self._document_end_position(), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(text, self._format(self._draft_color))
        cursor.setPosition(self._safe_draft_start() + max(0, min(cursor_offset, len(text))))
        self.setTextCursor(cursor)

    def _insert_draft_text(self, text: str) -> None:
        if not text:
            return
        before = self.text()
        before_offset = self.cursorPosition()
        self._ensure_cursor_in_draft()
        cursor = self.textCursor()
        cursor.insertText(text, self._format(self._draft_color))
        self.setTextCursor(cursor)
        if self.text() != before:
            self._record_draft_edit(before, before_offset, "paste")
            self.textEdited.emit(self.text())

    def _ensure_cursor_in_draft(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection() and not self.selection_within_draft():
            cursor.clearSelection()
            cursor.setPosition(self._document_end_position())
            self.setTextCursor(cursor)
            return
        if cursor.position() < self._safe_draft_start():
            cursor.setPosition(self._document_end_position())
            self.setTextCursor(cursor)

    def _move_home(self, keep_anchor: bool) -> None:
        cursor = self.textCursor()
        block_start = cursor.block().position()
        target = max(block_start, self._safe_draft_start())
        mode = QTextCursor.MoveMode.KeepAnchor if keep_anchor else QTextCursor.MoveMode.MoveAnchor
        cursor.setPosition(target, mode)
        self.setTextCursor(cursor)

    def _is_editing_key(self, event) -> bool:
        if event.text():
            return True
        if event.key() in {Qt.Key.Key_Backspace, Qt.Key.Key_Delete}:
            return True
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() in {
            Qt.Key.Key_V,
            Qt.Key.Key_X,
        }:
            return True
        return False

    def _document_end_position(self) -> int:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor.position()

    def _safe_prompt_start(self) -> int:
        return max(0, min(self._prompt_start, len(super().toPlainText())))

    def _safe_draft_start(self) -> int:
        return max(self._safe_prompt_start(), min(self._draft_start, len(super().toPlainText())))

    def _has_prompt(self) -> bool:
        return self._draft_start >= len(self.prompt)

    def _format(self, color: str, *, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if italic:
            fmt.setFontItalic(True)
        return fmt

    # -- inline overlays: placeholder hint + IDE-style completion ghost ---------

    def _refresh_inline_overlay(self, *_args) -> None:
        self.viewport().update()

    def _popup_visible(self) -> bool:
        return bool(self._completer and self._completer.popup().isVisible())

    def _active_completion(self) -> str:
        """The completion currently highlighted in the popup (falling back to the
        first match) while it is visible — otherwise an empty string."""
        if not self._popup_visible():
            return ""
        popup = self._completer.popup()
        index = popup.currentIndex()
        completion = str(index.data() or "") if index.isValid() else ""
        if not completion:
            completion = self._completer.currentCompletion()
        if not completion:
            first = self._completer.completionModel().index(0, 0)
            completion = str(first.data() or "") if first.isValid() else ""
        return completion

    def _ghost_suffix(self) -> str:
        """The not-yet-typed tail of the active completion, shown inline as a
        ghost. Only when the caret sits at the draft end (no selection) and the
        completion extends the token under the caret — so it appends cleanly."""
        completion = self._active_completion()
        if not completion or self.textCursor().hasSelection():
            return ""
        if self.cursorPosition() != len(self.text()):
            return ""
        token = self.token_under_cursor()
        if token and not completion.lower().startswith(token.lower()):
            return ""
        return completion[len(token):]

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        ghost = self._ghost_suffix()
        if ghost:
            self._paint_inline_overlay(
                self.cursorRect(),
                [
                    (ghost, self._ghost_color, True),
                    ("   ⇥ Tab to autocomplete", self._hint_color, True),
                ],
            )
            return
        if not self.text() and self._placeholder and not self._popup_visible():
            cursor = QTextCursor(self.document())
            cursor.setPosition(self._safe_draft_start())
            self._paint_inline_overlay(
                self.cursorRect(cursor),
                [(self._placeholder, self._hint_color, True)],
            )

    def _paint_inline_overlay(self, rect, segments) -> None:
        painter = QPainter(self.viewport())
        try:
            base_font = self.font()
            x = float(rect.left())
            top = rect.top()
            height = rect.height()
            align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for text, color, italic in segments:
                if not text:
                    continue
                font = QFont(base_font)
                font.setItalic(italic)
                painter.setFont(font)
                advance = QFontMetrics(font).horizontalAdvance(text)
                painter.setPen(QColor(color))
                painter.drawText(QRect(round(x), top, advance + 4, height), align, text)
                x += advance
        finally:
            painter.end()


class ChevronComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(self.foregroundRole())
        if not self.isEnabled():
            color = color.darker(130)
        pen = QPen(QColor(color), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        center_x = self.width() - 18
        center_y = int(self.height() / 2)
        painter.drawLine(center_x - 4, center_y - 2, center_x, center_y + 2)
        painter.drawLine(center_x, center_y + 2, center_x + 4, center_y - 2)
        painter.end()
