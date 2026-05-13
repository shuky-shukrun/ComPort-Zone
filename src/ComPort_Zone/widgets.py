from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QTextEdit, QWidget


TERMINAL_COMPLETION_TOKEN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:*?.-")
TERMINAL_COMPLETION_NAVIGATION_KEYS = {
    Qt.Key.Key_Down,
    Qt.Key.Key_Up,
    Qt.Key.Key_PageDown,
    Qt.Key.Key_PageUp,
    Qt.Key.Key_Home,
    Qt.Key.Key_End,
}


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


class IntegratedTerminalEdit(QTextEdit):
    returnPressed = Signal()
    historyRequested = Signal(int)
    autocompleteRequested = Signal()
    deleteHistoryRequested = Signal()
    textEdited = Signal(str)

    prompt = "TX> "

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._completer = None
        self._prompt_start = 0
        self._draft_start = 0
        self._prompt_color = "#4fc1ff"
        self._draft_color = "#4fc1ff"
        self._transcript_color = "#d4d4d4"
        self.font_zoom_callback: Callable[[int], None] | None = None
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self.setAcceptDrops(False)
        self._replace_document("", "", 0)

    def set_terminal_colors(self, *, prompt: str, draft: str) -> None:
        self._prompt_color = prompt
        self._draft_color = prompt
        self._transcript_color = draft
        self._reformat_prompt_and_draft()

    def setCompleter(self, completer) -> None:
        self._completer = completer
        completer.setWidget(self)
        completer.popup().installEventFilter(self)

    def set_font_zoom_callback(self, callback: Callable[[int], None]) -> None:
        self.font_zoom_callback = callback

    def completer(self):
        return self._completer

    def setPlaceholderText(self, _text: str) -> None:
        return

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
        popup_index = self._completer.popup().currentIndex()
        completion = str(popup_index.data() or "") if popup_index.isValid() else ""
        if not completion:
            completion = self._completer.currentCompletion()
        if not completion:
            index = self._completer.completionModel().index(0, 0)
            completion = str(index.data() or "") if index.isValid() else ""
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
        if not self._completer:
            return
        model = self._completer.completionModel()
        row_count = model.rowCount()
        if row_count <= 0:
            return
        popup = self._completer.popup()
        current_row = popup.currentIndex().row()
        if current_row < 0:
            current_row = max(self._completer.currentRow(), 0)
        if key == Qt.Key.Key_Down:
            target_row = min(current_row + 1, row_count - 1)
        elif key == Qt.Key.Key_Up:
            target_row = max(current_row - 1, 0)
        elif key == Qt.Key.Key_PageDown:
            target_row = min(current_row + 8, row_count - 1)
        elif key == Qt.Key.Key_PageUp:
            target_row = max(current_row - 8, 0)
        elif key == Qt.Key.Key_End:
            target_row = row_count - 1
        else:
            target_row = 0
        self._completer.setCurrentRow(target_row)
        index = model.index(target_row, 0)
        if index.isValid():
            popup.setCurrentIndex(index)

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
        first_index = self._completer.completionModel().index(0, 0)
        if first_index.isValid():
            self._completer.setCurrentRow(0)
            popup.setCurrentIndex(first_index)
        rect = self.cursorRect()
        width = popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width()
        rect.setWidth(max(width, self.fontMetrics().horizontalAdvance(token) + 96))
        self._completer.complete(rect)

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

    def cut(self) -> None:
        if not self.selection_within_draft():
            self.copy()
            return
        before = self.text()
        super().cut()
        if self.text() != before:
            self.textEdited.emit(self.text())

    def paste(self) -> None:
        clipboard = QApplication.clipboard()
        self._insert_draft_text(clipboard.text())

    def undo(self) -> None:
        return

    def redo(self) -> None:
        return

    def insertFromMimeData(self, source) -> None:
        if source.hasText():
            self._insert_draft_text(source.text())

    def eventFilter(self, watched, event) -> bool:
        popup = self._completer.popup() if self._completer else None
        if (
            popup is not None
            and watched is popup
            and event.type() == QEvent.Type.KeyPress
            and popup.isVisible()
        ):
            if event.key() in TERMINAL_COMPLETION_NAVIGATION_KEYS:
                self.navigate_completion(event.key())
                return True
            if event.key() in {Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
                self.accept_current_completion()
                return True
            if event.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return}:
                self._handle_return_key(event.modifiers())
                return True
            if event.key() == Qt.Key.Key_Escape:
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
            if event.key() in TERMINAL_COMPLETION_NAVIGATION_KEYS:
                self.navigate_completion(event.key())
                event.accept()
                return
            if event.key() in {Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
                self.accept_current_completion()
                event.accept()
                return
            if event.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return}:
                self._handle_return_key(event.modifiers())
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
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
        if self._is_editing_key(event):
            self._ensure_cursor_in_draft()
        super().keyPressEvent(event)
        after = self.text()
        if after != before:
            self.textEdited.emit(after)
            if event.text() and event.text()[-1] in TERMINAL_COMPLETION_TOKEN_CHARS:
                self.show_completions()
            elif self._completer:
                self._completer.popup().hide()

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
        self._ensure_cursor_in_draft()
        cursor = self.textCursor()
        cursor.insertText(text, self._format(self._draft_color))
        self.setTextCursor(cursor)
        if self.text() != before:
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

    def _format(self, color: str) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt


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
