from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import re

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QStringListModel, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QLineEdit,
    QPushButton,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .batch import BatchParseError, parse_batch_line, strip_c_style_comment
from .icons import standard_icon
from .models import QUICK_COMMAND_SORT_MODES, QUICK_FILE_SORT_MODES, QuickCommand, QuickFile
from .quick_actions import quick_file_display_text, quick_group_name
from .quick_actions_panel import (
    item_ids_in_order,
    populate_quick_command_list,
    populate_quick_file_list,
    selected_item_id,
)
from .quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions
from .widgets import ChevronComboBox

BATCH_KEYWORDS = ("SEND", "WAIT", "HEX", "EXPECT")
COMMENT_SNIPPETS = ("// ", "# ")
COMPLETION_NAVIGATION_KEYS = {
    Qt.Key.Key_Down,
    Qt.Key.Key_Up,
    Qt.Key.Key_PageDown,
    Qt.Key.Key_PageUp,
    Qt.Key.Key_Home,
    Qt.Key.Key_End,
}
DEFAULT_KNOWN_COMMANDS = (
    "*IDN?",
    "SYST:FIRM?",
    "MEAS:CURR?",
    "MEAS:VOLT?",
    "CURR",
    "CURR?",
    "OUTP",
    "OUTP?",
    "POW",
    "POW?",
    "SINK:CURR",
    "SINK:CURR?",
    "SINK:POW",
    "SINK:POW?",
    "SYST:ERR?",
    "SYST:ERR:ALL?",
    "SYST:FIRM?",
    "VOLT",
    "VOLT?",
)
COMMAND_TOKEN_PATTERN = re.compile(r"^[^\s]+")
COMPLETION_TOKEN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:*?.-")


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


@dataclass(slots=True)
class CommandValidationIssue:
    line_number: int
    message: str
    start: int = 0
    length: int = 0
    severity: str = "warning"


def quick_command_group(command: QuickCommand) -> str:
    return quick_group_name(command.group)


def command_token(text: str) -> str:
    match = COMMAND_TOKEN_PATTERN.match(text.strip())
    return match.group(0).strip() if match else ""


def command_text_from_line(stripped_line: str) -> str:
    try:
        step = parse_batch_line(stripped_line, 1)
    except BatchParseError:
        if stripped_line.upper().startswith("SEND "):
            return stripped_line[5:].strip()
        return stripped_line
    if step.kind == "send":
        return str(step.payload).strip()
    return ""


def has_parameter(text: str) -> bool:
    return "{{" in text and "}}" in text


@dataclass(slots=True)
class CommandEditorSources:
    history_commands: list[str] = field(default_factory=list)
    quick_commands: list[QuickCommand] = field(default_factory=list)
    known_commands: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWN_COMMANDS))
    quick_group_filter: str = "All"
    quick_command_hidden_groups: list[str] = field(default_factory=list)

    def groups(self) -> list[str]:
        names = {quick_command_group(command) for command in self.quick_commands}
        return sorted(names, key=str.casefold)

    def quick_command_texts(self) -> list[str]:
        selected = self.quick_group_filter.casefold()
        hidden = {group.casefold() for group in self.quick_command_hidden_groups}
        return [
            command.command
            for command in self.quick_commands
            if command.command
            and (selected == "all" or quick_command_group(command).casefold() == selected)
            and quick_command_group(command).casefold() not in hidden
        ]

    def known_command_tokens(self) -> set[str]:
        tokens = {item.strip().casefold() for item in self.known_commands if item.strip()}
        for text in [*self.history_commands, *[command.command for command in self.quick_commands]]:
            token = command_token(command_text_from_line(text))
            if token:
                tokens.add(token.casefold())
        return tokens

    def document_words(self, text: str) -> list[str]:
        words: set[str] = set()
        for raw_line in text.splitlines():
            stripped = strip_c_style_comment(raw_line)
            if not stripped or stripped.startswith("#"):
                continue
            for token in re.findall(r"[A-Za-z0-9_*][A-Za-z0-9_:*?.-]*", stripped):
                if len(token) > 1:
                    words.add(token)
        return sorted(words, key=str.casefold)

    def suggestions(self, document_text: str = "", prefix: str = "", exclude: str = "") -> list[str]:
        candidates: list[str] = []
        candidates.extend(BATCH_KEYWORDS)
        candidates.extend(COMMENT_SNIPPETS)
        candidates.extend(self.known_commands)
        candidates.extend(self.history_commands)
        candidates.extend(self.quick_command_texts())
        candidates.extend(self.document_words(document_text))
        seen: set[str] = set()
        prefix_key = prefix.casefold()
        exclude_key = exclude.casefold()
        result: list[str] = []
        for candidate in candidates:
            value = candidate.strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            if exclude_key and key == exclude_key:
                continue
            if prefix_key and prefix_key not in key:
                continue
            seen.add(key)
            result.append(value)
        if prefix_key:
            result.sort(key=lambda value: (0 if value.casefold().startswith(prefix_key) else 1, value.casefold()))
        return result[:200]

    def validation_issues(self, text: str, *, warn_unknown: bool = True) -> list[CommandValidationIssue]:
        known_tokens = self.known_command_tokens()
        issues: list[CommandValidationIssue] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            stripped = strip_c_style_comment(raw_line)
            if not stripped or stripped.startswith("#"):
                continue
            if has_parameter(stripped):
                command_text = command_text_from_line(stripped)
            else:
                try:
                    step = parse_batch_line(stripped, line_number)
                except BatchParseError as exc:
                    issues.append(CommandValidationIssue(line_number, str(exc), 0, len(raw_line), "error"))
                    continue
                command_text = str(step.payload).strip() if step.kind == "send" else ""
            if not warn_unknown or not command_text or has_parameter(command_text):
                continue
            token = command_token(command_text)
            if token and token.casefold() not in known_tokens:
                start = raw_line.find(token)
                issues.append(
                    CommandValidationIssue(
                        line_number,
                        f"Unknown command: {token}",
                        max(start, 0),
                        len(token),
                        "warning",
                    )
                )
        return issues


@dataclass(slots=True)
class CommandEditorQuickActionCallbacks:
    quick_commands_supplier: Callable[[], list[QuickCommand]] | None = None
    visible_quick_commands_supplier: Callable[[], list[QuickCommand]] | None = None
    quick_command_groups_supplier: Callable[[], list[str]] | None = None
    quick_command_hidden_groups_supplier: Callable[[], list[str]] | None = None
    quick_command_sort_mode_supplier: Callable[[], str] | None = None
    set_quick_command_sort_mode: Callable[[str], None] | None = None
    set_quick_command_group_visible: Callable[[str, bool], None] | None = None
    show_all_quick_command_groups: Callable[[], None] | None = None
    hide_all_quick_command_groups: Callable[[], None] | None = None
    add_quick_command: Callable[[], None] | None = None
    edit_quick_command: Callable[[str], None] | None = None
    delete_quick_command: Callable[[str], None] | None = None
    move_quick_command: Callable[[str, int], None] | None = None
    reorder_quick_commands: Callable[[list[str], str], None] | None = None
    import_quick_commands_csv: Callable[[], None] | None = None
    export_quick_commands_csv: Callable[[], None] | None = None
    quick_files_supplier: Callable[[], list[QuickFile]] | None = None
    visible_quick_files_supplier: Callable[[], list[QuickFile]] | None = None
    quick_file_sort_mode_supplier: Callable[[], str] | None = None
    set_quick_file_sort_mode: Callable[[str], None] | None = None
    add_quick_file: Callable[[], None] | None = None
    edit_quick_file: Callable[[str], None] | None = None
    delete_quick_file: Callable[[str], None] | None = None
    move_quick_file: Callable[[str, int], None] | None = None
    reorder_quick_files: Callable[[list[str], str, bool], None] | None = None
    import_quick_files_csv: Callable[[], None] | None = None
    export_quick_files_csv: Callable[[], None] | None = None


class LineNumberArea(QWidget):
    def __init__(self, editor: "CommandPlainTextEdit") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.line_number_area_paint_event(event)


class CommandPlainTextEdit(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.completer: QCompleter | None = None
        self.completion_refresh_callback: Callable[[str], None] | None = None
        self.font_zoom_callback: Callable[[int], None] | None = None
        self.save_callback: Callable[[], None] | None = None
        self.save_as_callback: Callable[[], None] | None = None
        self.find_callback: Callable[[], None] | None = None
        self.replace_callback: Callable[[], None] | None = None
        self.search_extra_selections: list[QTextEdit.ExtraSelection] = []
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def setCompleter(self, completer: QCompleter) -> None:
        self.completer = completer
        completer.setWidget(self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.popup().installEventFilter(self)
        completer.activated.connect(self.insert_completion)

    def set_completion_refresh_callback(self, callback: Callable[[str], None]) -> None:
        self.completion_refresh_callback = callback

    def set_font_zoom_callback(self, callback: Callable[[int], None]) -> None:
        self.font_zoom_callback = callback

    def set_save_callbacks(self, save_callback: Callable[[], None], save_as_callback: Callable[[], None]) -> None:
        self.save_callback = save_callback
        self.save_as_callback = save_as_callback

    def set_find_callbacks(self, find_callback: Callable[[], None], replace_callback: Callable[[], None]) -> None:
        self.find_callback = find_callback
        self.replace_callback = replace_callback

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        content_rect = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(content_rect.left(), content_rect.top(), self.line_number_area_width(), content_rect.height())
        )

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#181818"))
        painter.setPen(QColor("#858585"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        self._apply_extra_selections()

    def _current_line_selection(self) -> QTextEdit.ExtraSelection:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#202020"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        return selection

    def _apply_extra_selections(self) -> None:
        self.setExtraSelections([self._current_line_selection(), *self.search_extra_selections])

    def set_search_highlights(self, ranges: list[tuple[int, int]], current_index: int = -1) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        for index, (start, end) in enumerate(ranges):
            if end <= start:
                continue
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(self.document())
            selection.cursor.setPosition(start)
            selection.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            selection.format.setBackground(QColor("#515C6A" if index == current_index else "#264F78"))
            selection.format.setForeground(QColor("#FFFFFF"))
            selections.append(selection)
        self.search_extra_selections = selections
        self._apply_extra_selections()

    def token_under_cursor(self) -> str:
        cursor = self.textCursor()
        position = cursor.positionInBlock()
        text = cursor.block().text()
        start = position
        while start > 0 and text[start - 1] in COMPLETION_TOKEN_CHARS:
            start -= 1
        end = position
        while end < len(text) and text[end] in COMPLETION_TOKEN_CHARS:
            end += 1
        return text[start:end]

    def insert_completion(self, completion: str) -> None:
        cursor = self.textCursor()
        token = self.token_under_cursor()
        if token:
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, len(token))
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def accept_current_completion(self) -> None:
        if not self.completer:
            return
        popup_index = self.completer.popup().currentIndex()
        completion = str(popup_index.data() or "") if popup_index.isValid() else ""
        if not completion:
            completion = self.completer.currentCompletion()
        if not completion:
            index = self.completer.completionModel().index(0, 0)
            completion = str(index.data() or "") if index.isValid() else ""
        if completion:
            self.insert_completion(completion)
        self.completer.popup().hide()

    def navigate_completion(self, key: Qt.Key) -> None:
        if not self.completer:
            return
        model = self.completer.completionModel()
        row_count = model.rowCount()
        if row_count <= 0:
            return
        popup = self.completer.popup()
        current_row = popup.currentIndex().row()
        if current_row < 0:
            current_row = max(self.completer.currentRow(), 0)
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
        self.completer.setCurrentRow(target_row)
        index = model.index(target_row, 0)
        if index.isValid():
            popup.setCurrentIndex(index)

    def show_completions(self, *, forced: bool = False) -> None:
        if not self.completer:
            return
        token = self.token_under_cursor()
        if self.completion_refresh_callback:
            self.completion_refresh_callback(token)
        if not forced and len(token) < 2:
            self.completer.popup().hide()
            return
        self.completer.setCompletionPrefix(token)
        if self.completer.completionCount() <= 0:
            self.completer.popup().hide()
            return
        popup = self.completer.popup()
        first_index = self.completer.completionModel().index(0, 0)
        if first_index.isValid():
            self.completer.setCurrentRow(0)
            popup.setCurrentIndex(first_index)
        rect = self.cursorRect()
        width = popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width()
        rect.setWidth(max(width, self.fontMetrics().horizontalAdvance(token) + 96))
        self.completer.complete(rect)

    def eventFilter(self, watched, event) -> bool:
        try:
            popup = self.completer.popup() if self.completer else None
        except RuntimeError:
            return False
        if (
            popup is not None
            and watched is popup
            and event.type() == QEvent.Type.KeyPress
            and popup.isVisible()
        ):
            if event.key() in COMPLETION_NAVIGATION_KEYS:
                self.navigate_completion(event.key())
                return True
            if event.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
                self.accept_current_completion()
                return True
            if event.key() == Qt.Key.Key_Escape:
                popup.hide()
                return True
        return super().eventFilter(watched, event)

    def event(self, event) -> bool:
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() in {Qt.Key.Key_F, Qt.Key.Key_H, Qt.Key.Key_S}
        ):
            event.accept()
            return True
        return super().event(event)

    def wheelEvent(self, event) -> None:
        if self.font_zoom_callback and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            self.font_zoom_callback(delta)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.find_callback:
                self.find_callback()
                event.accept()
                return
        if event.key() == Qt.Key.Key_H and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.replace_callback:
                self.replace_callback()
                event.accept()
                return
        if event.key() == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if self.save_as_callback:
                    self.save_as_callback()
                    event.accept()
                    return
            elif self.save_callback:
                self.save_callback()
                event.accept()
                return
        if self.completer and self.completer.popup().isVisible():
            if event.key() in COMPLETION_NAVIGATION_KEYS:
                self.navigate_completion(event.key())
                event.accept()
                return
            if event.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
                self.accept_current_completion()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.completer.popup().hide()
                event.accept()
                return
        is_completion_shortcut = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_Space
        if not is_completion_shortcut:
            super().keyPressEvent(event)
        if is_completion_shortcut:
            self.show_completions(forced=True)
            return
        if event.text() and event.text()[-1] in COMPLETION_TOKEN_CHARS:
            self.show_completions()
        elif self.completer:
            self.completer.popup().hide()


class CommandFileHighlighter(QSyntaxHighlighter):
    def __init__(self, document, sources: CommandEditorSources) -> None:
        super().__init__(document)
        self.sources = sources
        self.warn_unknown = True
        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor("#4FC1FF"))
        self.keyword_format.setFontWeight(QFont.Weight.Bold)
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#6A9955"))
        self.parameter_format = QTextCharFormat()
        self.parameter_format.setForeground(QColor("#DCDCAA"))
        self.issue_format = QTextCharFormat()
        self.issue_format.setUnderlineColor(QColor("#F14C4C"))
        self.issue_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)

    def set_warn_unknown(self, enabled: bool) -> None:
        self.warn_unknown = enabled
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        stripped = text.lstrip()
        leading = len(text) - len(stripped)
        for keyword in BATCH_KEYWORDS:
            if re.match(rf"^{keyword}\b", stripped, re.IGNORECASE):
                self.setFormat(leading, len(keyword), self.keyword_format)
                break
        comment_index = text.find("//")
        hash_index = text.find("#")
        comment_starts = [index for index in (comment_index, hash_index) if index >= 0]
        if comment_starts:
            start = min(comment_starts)
            self.setFormat(start, len(text) - start, self.comment_format)
        for match in re.finditer(r"\{\{[^{}]*\}\}", text):
            self.setFormat(match.start(), match.end() - match.start(), self.parameter_format)
        line_number = self.currentBlock().blockNumber() + 1
        for issue in self.sources.validation_issues(text, warn_unknown=self.warn_unknown):
            if issue.line_number == 1 and issue.start < len(text):
                length = issue.length or max(1, len(text) - issue.start)
                self.setFormat(issue.start, min(length, len(text) - issue.start), self.issue_format)
        self.setCurrentBlockState(line_number)


class CommandFileEditorDialog(QDialog):
    stateChanged = Signal()

    def __init__(
        self,
        *,
        sources: CommandEditorSources,
        path: Path | None = None,
        run_callback: Callable[[str, Path | None], None] | None = None,
        font_change_callback: Callable[[int], None] | None = None,
        quick_files_supplier: Callable[[], list[QuickFile]] | None = None,
        quick_action_callbacks: CommandEditorQuickActionCallbacks | None = None,
        run_targets_supplier: Callable[[], list[tuple[int, str]]] | None = None,
        run_target_callback: Callable[["CommandFileEditorDialog", int], None] | None = None,
        embedded: bool = False,
        show_run_button: bool = True,
        show_workspace_side_panel: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sources = sources
        self.path = path
        self.run_callback = run_callback
        self.font_change_callback = font_change_callback
        self.quick_files_supplier = quick_files_supplier
        self.quick_action_callbacks = quick_action_callbacks or CommandEditorQuickActionCallbacks()
        self.run_targets_supplier = run_targets_supplier
        self.run_target_callback = run_target_callback
        self.embedded = embedded
        self.show_workspace_side_panel = show_workspace_side_panel
        self._local_quick_command_sort_mode = "Custom"
        self._local_quick_file_sort_mode = "Custom"
        self._quick_list_refreshing = False
        self._quick_file_list_refreshing = False
        self._dirty = False
        self.search_matches: list[tuple[int, int]] = []
        self.current_match_index = -1
        if self.embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle("Command File Editor")
        self.setMinimumSize(860, 640)

        self.path_label = QLabel(self)
        self.path_label.setObjectName("editorPathLabel")
        self.status_label = QLabel(self)
        self.status_label.setObjectName("editorStatusLabel")
        self.shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self.shortcut_save.activated.connect(self.save)
        self.shortcut_save_as = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self.shortcut_save_as.activated.connect(self.save_as)
        self.shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_find.activated.connect(self.show_find_bar)
        self.shortcut_replace = QShortcut(QKeySequence("Ctrl+H"), self)
        self.shortcut_replace.activated.connect(self.show_replace_bar)

        self.warn_unknown = QCheckBox("Warn unknown commands", self)
        self.warn_unknown.setChecked(True)
        self.warn_unknown.toggled.connect(self._warn_unknown_changed)

        self.editor = CommandPlainTextEdit(self)
        self.editor.setObjectName("commandFileEditor")
        self.editor.setFont(QFont("Cascadia Mono", 10))
        self.editor.set_save_callbacks(self.save, self.save_as)
        self.editor.set_find_callbacks(self.show_find_bar, self.show_replace_bar)
        if self.font_change_callback:
            self.editor.set_font_zoom_callback(self.font_change_callback)
        self.completion_model = QStringListModel(self)
        self.completer = QCompleter(self.completion_model, self)
        self.editor.setCompleter(self.completer)
        self.editor.set_completion_refresh_callback(self._refresh_completion_model)
        self.highlighter = CommandFileHighlighter(self.editor.document(), self.sources)
        self.editor.textChanged.connect(self._text_changed)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        for label, callback in (
            ("New", self.new_file),
            ("Open", self.open_file),
            ("Save", self.save),
            ("Save As", self.save_as),
            ("Find", self.show_find_bar),
            ("Replace", self.show_replace_bar),
        ):
            button = QPushButton(label, self)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        if show_run_button:
            button = QPushButton("Run Buffer", self)
            button.clicked.connect(self.run_buffer)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.warn_unknown)
        if self.font_change_callback:
            font_down = QToolButton(self)
            font_down.setText("-")
            font_down.setToolTip("Decrease editor font")
            font_down.clicked.connect(lambda: self.font_change_callback(-1))
            font_up = QToolButton(self)
            font_up.setText("+")
            font_up.setToolTip("Increase editor font")
            font_up.clicked.connect(lambda: self.font_change_callback(1))
            toolbar.addWidget(font_down)
            toolbar.addWidget(font_up)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.path_label, 1)
        if not self.embedded:
            close_button = QToolButton(self)
            close_button.setText("Close")
            close_button.clicked.connect(self.reject)
            header.addWidget(close_button)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)

        editor_column = QWidget(self)
        editor_layout = QVBoxLayout(editor_column)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addLayout(header)
        editor_layout.addLayout(toolbar)
        editor_layout.addWidget(self._build_find_replace_bar())
        editor_layout.addWidget(line)
        editor_layout.addWidget(self.editor, 1)
        editor_layout.addWidget(self.status_label)
        if self.run_targets_supplier and self.run_target_callback:
            editor_layout.addWidget(self._build_run_bar())

        if self.show_workspace_side_panel:
            root_layout = QHBoxLayout(self)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
            root_layout.addWidget(self._build_workspace_side_panel())
            root_layout.addWidget(editor_column, 1)
        else:
            layout = QVBoxLayout(self)
            layout.addWidget(editor_column, 1)

        if self.path:
            self.load_path(self.path)
        else:
            self.editor.setPlainText("")
            self._dirty = False
            self.update_window_state()
            self.update_validation_status()
        self._refresh_completion_model()
        self.refresh_workspace_side_panel()
        self.refresh_run_targets()

    def _select_workspace_drawer_page(self, index: int) -> None:
        if not hasattr(self, "workspace_drawer"):
            return
        self.workspace_drawer.select_page(index)

    def _quick_action_callback(self, name: str) -> Callable | None:
        return getattr(self.quick_action_callbacks, name, None)

    def _quick_commands(self) -> list[QuickCommand]:
        supplier = self._quick_action_callback("quick_commands_supplier")
        return list(supplier()) if supplier else list(self.sources.quick_commands)

    def _quick_files(self) -> list[QuickFile]:
        supplier = self._quick_action_callback("quick_files_supplier") or self.quick_files_supplier
        return list(supplier()) if supplier else []

    def _quick_command_sort_mode(self) -> str:
        supplier = self._quick_action_callback("quick_command_sort_mode_supplier")
        mode = str(supplier()) if supplier else self._local_quick_command_sort_mode
        return mode if mode in QUICK_COMMAND_SORT_MODES else "Custom"

    def _quick_file_sort_mode(self) -> str:
        supplier = self._quick_action_callback("quick_file_sort_mode_supplier")
        mode = str(supplier()) if supplier else self._local_quick_file_sort_mode
        return mode if mode in QUICK_FILE_SORT_MODES else "Custom"

    def _quick_command_groups(self) -> list[str]:
        supplier = self._quick_action_callback("quick_command_groups_supplier")
        if supplier:
            return list(supplier())
        names = {quick_group_name(command.group) for command in self._quick_commands()}
        return sorted(names, key=str.casefold)

    def _quick_command_hidden_groups(self) -> list[str]:
        supplier = self._quick_action_callback("quick_command_hidden_groups_supplier")
        if supplier:
            return list(supplier())
        return list(self.sources.quick_command_hidden_groups)

    def _visible_quick_commands(self) -> list[QuickCommand]:
        supplier = self._quick_action_callback("visible_quick_commands_supplier")
        if supplier:
            return list(supplier())
        hidden = {group.casefold() for group in self._quick_command_hidden_groups()}
        commands = [
            command
            for command in self._quick_commands()
            if quick_group_name(command.group).casefold() not in hidden
        ]
        mode = self._quick_command_sort_mode()
        if mode == "Title":
            return sorted(
                commands,
                key=lambda command: (
                    command.display_label().casefold(),
                    quick_group_name(command.group).casefold(),
                    command.command.casefold(),
                ),
            )
        if mode == "Group":
            return sorted(
                commands,
                key=lambda command: (
                    quick_group_name(command.group).casefold(),
                    command.display_label().casefold(),
                    command.command.casefold(),
                ),
            )
        return commands

    def _visible_quick_files(self) -> list[QuickFile]:
        supplier = self._quick_action_callback("visible_quick_files_supplier")
        quick_files = list(supplier()) if supplier else self._quick_files()
        if supplier:
            return quick_files
        mode = self._quick_file_sort_mode()
        if mode == "Title":
            return sorted(
                quick_files,
                key=lambda quick_file: (
                    quick_file_display_text(quick_file).casefold(),
                    quick_file.path.casefold(),
                ),
            )
        if mode == "Path":
            return sorted(
                quick_files,
                key=lambda quick_file: (
                    quick_file.path.casefold(),
                    quick_file_display_text(quick_file).casefold(),
                ),
            )
        return quick_files

    def _can_manually_reorder_quick_commands(self) -> bool:
        hidden = {group.casefold() for group in self._quick_command_hidden_groups()}
        group_names = {group.casefold() for group in self._quick_command_groups()}
        hidden_active = any(group in group_names for group in hidden)
        return (
            self._quick_command_sort_mode() == "Custom"
            and not hidden_active
            and self._quick_action_callback("reorder_quick_commands") is not None
        )

    def _set_quick_command_group_visible(self, group: str, visible: bool) -> None:
        callback = self._quick_action_callback("set_quick_command_group_visible")
        if callback:
            callback(group, visible)
            return
        group = quick_group_name(group)
        hidden = [
            hidden_group
            for hidden_group in self.sources.quick_command_hidden_groups
            if hidden_group.casefold() != group.casefold()
        ]
        if not visible:
            hidden.append(group)
        self.sources.quick_command_hidden_groups = hidden
        self.refresh_workspace_side_panel()
        self._refresh_completion_model()

    def _show_all_quick_command_groups(self) -> None:
        callback = self._quick_action_callback("show_all_quick_command_groups")
        if callback:
            callback()
            return
        self.sources.quick_command_hidden_groups = []
        self.refresh_workspace_side_panel()
        self._refresh_completion_model()

    def _hide_all_quick_command_groups(self) -> None:
        callback = self._quick_action_callback("hide_all_quick_command_groups")
        if callback:
            callback()
            return
        self.sources.quick_command_hidden_groups = self._quick_command_groups()
        self.refresh_workspace_side_panel()
        self._refresh_completion_model()

    def _quick_sort_changed(self) -> None:
        mode = self.quick_sort_combo.currentData()
        if not mode:
            return
        callback = self._quick_action_callback("set_quick_command_sort_mode")
        if callback:
            callback(str(mode))
            return
        self._local_quick_command_sort_mode = str(mode)
        self.refresh_workspace_side_panel()

    def _quick_file_sort_changed(self) -> None:
        mode = self.quick_file_sort_combo.currentData()
        if not mode:
            return
        callback = self._quick_action_callback("set_quick_file_sort_mode")
        if callback:
            callback(str(mode))
            return
        self._local_quick_file_sort_mode = str(mode)
        self.refresh_workspace_side_panel()

    def _add_menu_action(
        self,
        menu: QMenu,
        text: str,
        callback: Callable[[], None],
        *,
        icon: QStyle.StandardPixmap | None = None,
        enabled: bool = True,
    ) -> QAction:
        action = QAction(text, menu)
        if icon is not None:
            action.setIcon(standard_icon(icon))
        action.setEnabled(enabled)
        action.triggered.connect(lambda _checked=False, callback=callback: callback())
        menu.addAction(action)
        return action

    def _refresh_quick_command_controls(self) -> None:
        if not hasattr(self, "quick_sort_combo"):
            return
        mode = self._quick_command_sort_mode()
        self.quick_sort_combo.blockSignals(True)
        index = self.quick_sort_combo.findData(mode)
        if index >= 0:
            self.quick_sort_combo.setCurrentIndex(index)
        self.quick_sort_combo.blockSignals(False)

        groups = self._quick_command_groups()
        hidden = {group.casefold() for group in self._quick_command_hidden_groups()}
        visible_count = sum(1 for group in groups if group.casefold() not in hidden)
        total_count = len(groups)
        if total_count == 0:
            group_text = "Groups: None"
        elif visible_count == total_count:
            group_text = "Groups: All"
        elif visible_count == 0:
            group_text = "Groups: Hidden"
        else:
            group_text = f"Groups: {visible_count}/{total_count}"
        self.quick_group_button.setText(group_text)

        old_menu = self.quick_group_button.menu()
        if old_menu is not None:
            old_menu.deleteLater()
        menu = QMenu(self.quick_group_button)
        self._add_menu_action(
            menu,
            "Show All Groups",
            self._show_all_quick_command_groups,
            icon=QStyle.StandardPixmap.SP_DialogApplyButton,
            enabled=total_count > 0 and visible_count < total_count,
        )
        self._add_menu_action(
            menu,
            "Hide All Groups",
            self._hide_all_quick_command_groups,
            icon=QStyle.StandardPixmap.SP_TrashIcon,
            enabled=total_count > 0 and visible_count > 0,
        )
        if groups:
            menu.addSeparator()
            for group in groups:
                action = QAction(group, menu)
                action.setCheckable(True)
                action.setChecked(group.casefold() not in hidden)
                action.toggled.connect(lambda checked, group=group: self._set_quick_command_group_visible(group, checked))
                menu.addAction(action)
        else:
            action = QAction("No groups yet", menu)
            action.setEnabled(False)
            menu.addAction(action)
        self.quick_group_button.setMenu(menu)

        can_reorder = self._can_manually_reorder_quick_commands()
        self.quick_command_list.setDragEnabled(can_reorder)
        self.quick_command_list.setAcceptDrops(can_reorder)
        self.quick_command_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if can_reorder
            else QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.quick_command_move_up_button.setEnabled(can_reorder and self.selected_quick_command_id() != "")
        self.quick_command_move_down_button.setEnabled(can_reorder and self.selected_quick_command_id() != "")
        if can_reorder:
            self.quick_command_list.setToolTip("Right-click a saved command for actions. Press and drag to reorder.")
        else:
            self.quick_command_list.setToolTip("Reorder is available only in Custom order with all groups visible.")

    def _refresh_quick_file_controls(self) -> None:
        if not hasattr(self, "quick_file_sort_combo"):
            return
        mode = self._quick_file_sort_mode()
        self.quick_file_sort_combo.blockSignals(True)
        index = self.quick_file_sort_combo.findData(mode)
        if index >= 0:
            self.quick_file_sort_combo.setCurrentIndex(index)
        self.quick_file_sort_combo.blockSignals(False)

        can_reorder = self._quick_action_callback("reorder_quick_files") is not None
        self.quick_file_list.setDragEnabled(can_reorder)
        self.quick_file_list.setAcceptDrops(can_reorder)
        self.quick_file_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if can_reorder
            else QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.quick_file_move_up_button.setEnabled(can_reorder and self.selected_quick_file_id() != "")
        self.quick_file_move_down_button.setEnabled(can_reorder and self.selected_quick_file_id() != "")
        if can_reorder and mode == "Custom":
            self.quick_file_list.setToolTip("Double-click a saved command file to open it. Press and drag to reorder.")
        elif can_reorder:
            self.quick_file_list.setToolTip("Double-click to open. Dragging or moving a file switches this list to Custom order.")
        else:
            self.quick_file_list.setToolTip("Double-click or press Open to load the saved file into this editor.")

    def _refresh_quick_action_buttons(self) -> None:
        command_id = self.selected_quick_command_id()
        command_count = len(self._quick_commands())
        self.insert_quick_command_button.setEnabled(bool(command_id))
        self.add_quick_command_button.setEnabled(self._quick_action_callback("add_quick_command") is not None)
        self.edit_quick_command_button.setEnabled(bool(command_id) and self._quick_action_callback("edit_quick_command") is not None)
        self.delete_quick_command_button.setEnabled(bool(command_id) and self._quick_action_callback("delete_quick_command") is not None)
        self.import_quick_commands_button.setEnabled(self._quick_action_callback("import_quick_commands_csv") is not None)
        self.export_quick_commands_button.setEnabled(command_count > 0 and self._quick_action_callback("export_quick_commands_csv") is not None)

        file_id = self.selected_quick_file_id()
        file_count = len(self._quick_files())
        self.open_quick_file_button.setEnabled(bool(file_id))
        self.add_quick_file_button.setEnabled(self._quick_action_callback("add_quick_file") is not None)
        self.edit_quick_file_button.setEnabled(bool(file_id) and self._quick_action_callback("edit_quick_file") is not None)
        self.delete_quick_file_button.setEnabled(bool(file_id) and self._quick_action_callback("delete_quick_file") is not None)
        self.import_quick_files_button.setEnabled(self._quick_action_callback("import_quick_files_csv") is not None)
        self.export_quick_files_button.setEnabled(file_count > 0 and self._quick_action_callback("export_quick_files_csv") is not None)
        self._refresh_quick_command_controls()
        self._refresh_quick_file_controls()

    def _run_optional_quick_action(self, name: str, *args) -> None:
        callback = self._quick_action_callback(name)
        if callback:
            callback(*args)

    def _edit_selected_quick_command(self) -> None:
        command_id = self.selected_quick_command_id()
        if command_id:
            self._run_optional_quick_action("edit_quick_command", command_id)

    def _delete_selected_quick_command(self) -> None:
        command_id = self.selected_quick_command_id()
        if command_id:
            self._run_optional_quick_action("delete_quick_command", command_id)

    def _move_selected_quick_command(self, direction: int) -> None:
        command_id = self.selected_quick_command_id()
        if command_id:
            self._run_optional_quick_action("move_quick_command", command_id, direction)

    def _edit_selected_quick_file(self) -> None:
        quick_file_id = self.selected_quick_file_id()
        if quick_file_id:
            self._run_optional_quick_action("edit_quick_file", quick_file_id)

    def _delete_selected_quick_file(self) -> None:
        quick_file_id = self.selected_quick_file_id()
        if quick_file_id:
            self._run_optional_quick_action("delete_quick_file", quick_file_id)

    def _move_selected_quick_file(self, direction: int) -> None:
        quick_file_id = self.selected_quick_file_id()
        if not quick_file_id:
            return
        reorder = self._quick_action_callback("reorder_quick_files")
        if reorder:
            reorder(item_ids_in_order(self.quick_file_list), quick_file_id, True)
        self._run_optional_quick_action("move_quick_file", quick_file_id, direction)

    def _persist_quick_command_order(self) -> None:
        if self._quick_list_refreshing or not self._can_manually_reorder_quick_commands():
            return
        callback = self._quick_action_callback("reorder_quick_commands")
        if callback:
            callback(item_ids_in_order(self.quick_command_list), self.selected_quick_command_id())

    def _persist_quick_file_order(self) -> None:
        if self._quick_file_list_refreshing:
            return
        callback = self._quick_action_callback("reorder_quick_files")
        if callback:
            callback(item_ids_in_order(self.quick_file_list), self.selected_quick_file_id(), True)

    def _build_workspace_side_panel(self) -> QWidget:
        drawer = QuickActionsSidebar(
            actions=QuickActionsSidebarActions(
                command_primary=self.insert_selected_quick_command,
                file_primary=self.open_selected_quick_file,
                add_command=lambda: self._run_optional_quick_action("add_quick_command"),
                edit_command=self._edit_selected_quick_command,
                delete_command=self._delete_selected_quick_command,
                move_command_up=lambda: self._move_selected_quick_command(-1),
                move_command_down=lambda: self._move_selected_quick_command(1),
                import_commands=lambda: self._run_optional_quick_action("import_quick_commands_csv"),
                export_commands=lambda: self._run_optional_quick_action("export_quick_commands_csv"),
                add_file=lambda: self._run_optional_quick_action("add_quick_file"),
                edit_file=self._edit_selected_quick_file,
                delete_file=self._delete_selected_quick_file,
                move_file_up=lambda: self._move_selected_quick_file(-1),
                move_file_down=lambda: self._move_selected_quick_file(1),
                import_files=lambda: self._run_optional_quick_action("import_quick_files_csv"),
                export_files=lambda: self._run_optional_quick_action("export_quick_files_csv"),
            ),
            command_primary_label="Insert",
            file_primary_label="Open",
            command_tooltip="Right-click a saved command for actions. Press and drag to reorder.",
            file_tooltip="Double-click a saved command file to open it. Press and drag to reorder.",
            command_double_clicked=self.insert_selected_quick_command,
            file_double_clicked=self.open_selected_quick_file,
            command_sort_changed=self._quick_sort_changed,
            file_sort_changed=self._quick_file_sort_changed,
            command_order_changed=self._persist_quick_command_order,
            file_order_changed=self._persist_quick_file_order,
            command_selection_changed=self._refresh_quick_action_buttons,
            file_selection_changed=self._refresh_quick_action_buttons,
            parent=self,
        )
        self.quick_command_list = drawer.quick_command_list
        self.quick_file_list = drawer.quick_file_list
        self.quick_sort_combo = drawer.quick_sort_combo
        self.quick_group_button = drawer.quick_group_button
        self.quick_file_sort_combo = drawer.quick_file_sort_combo
        self.insert_quick_command_button = drawer.command_primary_button
        self.open_quick_file_button = drawer.file_primary_button
        self.add_quick_command_button = drawer.add_command_button
        self.edit_quick_command_button = drawer.edit_command_button
        self.delete_quick_command_button = drawer.delete_command_button
        self.quick_command_move_up_button = drawer.quick_command_move_up_button
        self.quick_command_move_down_button = drawer.quick_command_move_down_button
        self.import_quick_commands_button = drawer.import_quick_commands_button
        self.export_quick_commands_button = drawer.export_quick_commands_button
        self.add_quick_file_button = drawer.add_file_button
        self.edit_quick_file_button = drawer.edit_file_button
        self.delete_quick_file_button = drawer.delete_file_button
        self.quick_file_move_up_button = drawer.quick_file_move_up_button
        self.quick_file_move_down_button = drawer.quick_file_move_down_button
        self.import_quick_files_button = drawer.import_quick_files_button
        self.export_quick_files_button = drawer.export_quick_files_button
        self.workspace_drawer = drawer
        self.workspace_drawer_pages = drawer.pages
        self.workspace_drawer_rail = drawer.rail
        self.quick_actions_panel = drawer
        return drawer

    def _build_run_bar(self) -> QWidget:
        bar = QFrame(self)
        bar.setObjectName("commandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        label = QLabel("Send file to", bar)
        self.run_target_combo = ChevronComboBox(bar)
        self.run_target_combo.setMinimumWidth(220)
        self.run_target_combo.setToolTip("Connected COM port target")
        self.send_to_target_button = QPushButton("Send", bar)
        self.send_to_target_button.clicked.connect(self.send_to_selected_target)
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addWidget(self.run_target_combo)
        layout.addWidget(self.send_to_target_button)
        return bar

    def _build_find_replace_bar(self) -> QWidget:
        self.find_replace_bar = QFrame(self)
        self.find_replace_bar.setObjectName("searchBar")
        layout = QHBoxLayout(self.find_replace_bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self.search_input = QLineEdit(self.find_replace_bar)
        self.search_input.setPlaceholderText("Find")
        self.search_input.textChanged.connect(lambda _: self.refresh_search_matches(reset=True))
        self.search_input.returnPressed.connect(self.find_next)
        self.replace_input = QLineEdit(self.find_replace_bar)
        self.replace_input.setPlaceholderText("Replace")
        self.case_sensitive_check = QCheckBox("Aa", self.find_replace_bar)
        self.case_sensitive_check.setToolTip("Case sensitive search")
        self.case_sensitive_check.toggled.connect(lambda _: self.refresh_search_matches(reset=True))
        previous_button = QPushButton("Prev", self.find_replace_bar)
        previous_button.clicked.connect(self.find_previous)
        next_button = QPushButton("Next", self.find_replace_bar)
        next_button.clicked.connect(self.find_next)
        replace_button = QPushButton("Replace", self.find_replace_bar)
        replace_button.clicked.connect(self.replace_current)
        replace_all_button = QPushButton("Replace All", self.find_replace_bar)
        replace_all_button.clicked.connect(self.replace_all)
        close_button = QToolButton(self.find_replace_bar)
        close_button.setText("X")
        close_button.clicked.connect(self.hide_find_replace_bar)
        self.search_count_label = QLabel("0/0", self.find_replace_bar)

        layout.addWidget(self.search_input, 2)
        layout.addWidget(self.replace_input, 2)
        layout.addWidget(self.case_sensitive_check)
        layout.addWidget(previous_button)
        layout.addWidget(next_button)
        layout.addWidget(replace_button)
        layout.addWidget(replace_all_button)
        layout.addWidget(self.search_count_label)
        layout.addWidget(close_button)
        self.find_replace_bar.hide()
        return self.find_replace_bar

    def setPlainText(self, text: str) -> None:
        self.editor.setPlainText(text)
        self._dirty = True
        self.update_window_state()
        self.update_validation_status()

    def text(self) -> str:
        return self.editor.toPlainText()

    def is_dirty(self) -> bool:
        return self._dirty

    def display_name(self) -> str:
        return self.path.name if self.path else "Untitled"

    def tab_title(self) -> str:
        suffix = " *" if self._dirty else ""
        return f"{self.display_name()}{suffix}"

    def status_summary(self) -> str:
        issues = self.sources.validation_issues(self.text(), warn_unknown=self.warn_unknown.isChecked())
        errors = len([issue for issue in issues if issue.severity == "error"])
        warnings = len(issues) - errors
        saved_state = "Unsaved" if self._dirty else "Saved"
        if errors:
            issue_text = f"{errors} error(s)"
        elif warnings:
            issue_text = f"{warnings} warning(s)"
        else:
            issue_text = "No syntax issues"
        return f"Command file | {self.display_name()} | {saved_state} | {issue_text}"

    def validation_errors(self) -> list[CommandValidationIssue]:
        return [
            issue
            for issue in self.sources.validation_issues(self.text(), warn_unknown=False)
            if issue.severity == "error"
        ]

    def apply_editor_font(self, font: QFont) -> None:
        self.editor.setFont(font)
        self.editor.document().setDefaultFont(font)
        self.editor.update_line_number_area_width(0)

    def restore_text(self, text: str, *, dirty: bool) -> None:
        self.editor.setPlainText(text)
        self._dirty = dirty
        self.update_window_state()
        self.update_validation_status()

    def _warn_unknown_changed(self, checked: bool) -> None:
        self.highlighter.set_warn_unknown(checked)
        self.update_validation_status()

    def _text_changed(self) -> None:
        self._dirty = True
        self._refresh_completion_model()
        self.refresh_search_matches(reset=False)
        self.update_window_state()
        self.update_validation_status()

    def _refresh_completion_model(self, prefix: str = "") -> None:
        self.completion_model.setStringList(self.sources.suggestions(self.text(), prefix=prefix, exclude=prefix))

    def refresh_workspace_side_panel(self) -> None:
        if not hasattr(self, "quick_command_list"):
            return
        self.sources.quick_commands = self._quick_commands()
        self.sources.quick_command_hidden_groups = self._quick_command_hidden_groups()
        selected_command_id = self.selected_quick_command_id()
        self._quick_list_refreshing = True
        self._refresh_quick_command_controls()
        populate_quick_command_list(
            self.quick_command_list,
            self._visible_quick_commands(),
            selected_id=selected_command_id,
            label_limit=30,
            group_limit=10,
            draggable=self._can_manually_reorder_quick_commands(),
        )
        self._quick_list_refreshing = False

        selected_file_id = self.selected_quick_file_id()
        quick_files = self._visible_quick_files()
        self._quick_file_list_refreshing = True
        self._refresh_quick_file_controls()
        populate_quick_file_list(
            self.quick_file_list,
            quick_files,
            selected_id=selected_file_id,
            label_limit=32,
            draggable=self._quick_action_callback("reorder_quick_files") is not None,
        )
        self._quick_file_list_refreshing = False
        self._refresh_quick_action_buttons()
        self._refresh_completion_model()

    def refresh_run_targets(self) -> None:
        if not hasattr(self, "run_target_combo"):
            return
        selected_id = self.run_target_combo.currentData()
        self.run_target_combo.blockSignals(True)
        self.run_target_combo.clear()
        targets = self.run_targets_supplier() if self.run_targets_supplier else []
        for target_id, label in targets:
            self.run_target_combo.addItem(label, target_id)
        if selected_id is not None:
            index = self.run_target_combo.findData(selected_id)
            if index >= 0:
                self.run_target_combo.setCurrentIndex(index)
        has_targets = self.run_target_combo.count() > 0
        if not has_targets:
            self.run_target_combo.addItem("No connected COM ports", None)
        self.run_target_combo.setEnabled(has_targets)
        self.send_to_target_button.setEnabled(has_targets)
        self.run_target_combo.blockSignals(False)

    def selected_quick_command_id(self) -> str:
        return selected_item_id(self.quick_command_list) if hasattr(self, "quick_command_list") else ""

    def selected_quick_file_id(self) -> str:
        return selected_item_id(self.quick_file_list) if hasattr(self, "quick_file_list") else ""

    def selected_quick_command(self) -> QuickCommand | None:
        command_id = self.selected_quick_command_id()
        return next((command for command in self._quick_commands() if command.id == command_id), None)

    def selected_quick_file(self) -> QuickFile | None:
        quick_file_id = self.selected_quick_file_id()
        return next((quick_file for quick_file in self._quick_files() if quick_file.id == quick_file_id), None)

    def insert_selected_quick_command(self) -> None:
        command = self.selected_quick_command()
        if not command:
            return
        text = f"HEX {command.command}" if command.send_mode == "Hex Bytes" else command.command
        self.insert_text_at_cursor(text)

    def insert_text_at_cursor(self, text: str) -> None:
        if not text:
            return
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def open_selected_quick_file(self) -> None:
        quick_file = self.selected_quick_file()
        if not quick_file:
            return
        if self.confirm_save_or_discard_if_dirty():
            self.load_path(Path(quick_file.path))

    def send_to_selected_target(self) -> None:
        if not self.run_target_callback:
            return
        self.refresh_run_targets()
        target_id = self.run_target_combo.currentData() if hasattr(self, "run_target_combo") else None
        if target_id is None:
            QApplication.beep()
            return
        errors = self.validation_errors()
        if errors:
            self.update_validation_status()
            QApplication.beep()
            return
        self.run_target_callback(self, int(target_id))

    def show_find_bar(self) -> None:
        self._show_find_replace_bar(show_replace=False)

    def show_replace_bar(self) -> None:
        self._show_find_replace_bar(show_replace=True)

    def _show_find_replace_bar(self, *, show_replace: bool) -> None:
        selection = self.editor.textCursor().selectedText().replace("\u2029", "\n")
        if selection:
            self.search_input.setText(selection)
        self.replace_input.setVisible(show_replace)
        self.find_replace_bar.show()
        self.refresh_search_matches(reset=True)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def hide_find_replace_bar(self) -> None:
        self.find_replace_bar.hide()
        self.search_matches = []
        self.current_match_index = -1
        self.editor.set_search_highlights([])
        self.editor.setFocus()

    def _search_text_pair(self) -> tuple[str, str]:
        needle = self.search_input.text()
        haystack = self.text()
        if self.case_sensitive_check.isChecked():
            return haystack, needle
        return haystack.casefold(), needle.casefold()

    def _find_search_matches(self) -> list[tuple[int, int]]:
        needle = self.search_input.text()
        if not needle:
            return []
        haystack, search_needle = self._search_text_pair()
        matches: list[tuple[int, int]] = []
        start = 0
        step = max(1, len(search_needle))
        while start <= len(haystack):
            index = haystack.find(search_needle, start)
            if index < 0:
                break
            matches.append((index, index + len(needle)))
            start = index + step
        return matches

    def refresh_search_matches(self, *, reset: bool) -> None:
        if not hasattr(self, "search_input"):
            return
        old_start = -1
        if 0 <= self.current_match_index < len(self.search_matches):
            old_start = self.search_matches[self.current_match_index][0]
        cursor_position = self.editor.textCursor().selectionStart()
        self.search_matches = self._find_search_matches()
        if not self.search_matches:
            self.current_match_index = -1
            self.search_count_label.setText("0/0")
            self.editor.set_search_highlights([])
            return
        if reset:
            self.current_match_index = next(
                (index for index, (start, _end) in enumerate(self.search_matches) if start >= cursor_position),
                0,
            )
        else:
            self.current_match_index = next(
                (index for index, (start, _end) in enumerate(self.search_matches) if start >= old_start),
                min(max(self.current_match_index, 0), len(self.search_matches) - 1),
            )
        self._select_current_search_match()

    def _select_current_search_match(self) -> None:
        if not (0 <= self.current_match_index < len(self.search_matches)):
            self.search_count_label.setText("0/0")
            self.editor.set_search_highlights(self.search_matches, self.current_match_index)
            return
        start, end = self.search_matches[self.current_match_index]
        cursor = self.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.search_count_label.setText(f"{self.current_match_index + 1}/{len(self.search_matches)}")
        self.editor.set_search_highlights(self.search_matches, self.current_match_index)

    def find_next(self) -> None:
        if not self.search_matches:
            self.refresh_search_matches(reset=True)
        if not self.search_matches:
            QApplication.beep()
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        self._select_current_search_match()

    def find_previous(self) -> None:
        if not self.search_matches:
            self.refresh_search_matches(reset=True)
        if not self.search_matches:
            QApplication.beep()
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.search_matches)
        self._select_current_search_match()

    def replace_current(self) -> None:
        if not self.search_matches:
            self.refresh_search_matches(reset=True)
        if not (0 <= self.current_match_index < len(self.search_matches)):
            QApplication.beep()
            return
        start, end = self.search_matches[self.current_match_index]
        cursor = self.editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(self.replace_input.text())
        self.editor.setTextCursor(cursor)
        self.refresh_search_matches(reset=True)

    def replace_all(self) -> None:
        matches = self._find_search_matches()
        if not matches:
            QApplication.beep()
            return
        replacement = self.replace_input.text()
        original = self.text()
        pieces: list[str] = []
        cursor = 0
        for start, end in matches:
            pieces.append(original[cursor:start])
            pieces.append(replacement)
            cursor = end
        pieces.append(original[cursor:])
        self.editor.setPlainText("".join(pieces))
        self.search_matches = []
        self.current_match_index = -1
        self.refresh_search_matches(reset=True)
        self.status_label.setText(f"Replaced {len(matches)} match(es).")

    def update_window_state(self) -> None:
        name = self.path.name if self.path else "Untitled command file"
        dirty = "*" if self._dirty else ""
        self.setWindowTitle(f"{dirty}{name} - Command File Editor")
        self.path_label.setText(str(self.path) if self.path else "Unsaved command file")
        self.stateChanged.emit()

    def update_validation_status(self) -> None:
        issues = self.sources.validation_issues(self.text(), warn_unknown=self.warn_unknown.isChecked())
        errors = [issue for issue in issues if issue.severity == "error"]
        warnings = [issue for issue in issues if issue.severity != "error"]
        if not issues:
            self.status_label.setText("No syntax issues.")
            self.stateChanged.emit()
            return
        preview = "; ".join(f"Line {issue.line_number}: {issue.message}" for issue in issues[:3])
        suffix = "" if len(issues) <= 3 else f"; +{len(issues) - 3} more"
        self.status_label.setText(f"{len(errors)} error(s), {len(warnings)} warning(s): {preview}{suffix}")
        self.stateChanged.emit()

    def confirm_discard_if_dirty(self) -> bool:
        if not self._dirty:
            return True
        return (
            QMessageBox.question(
                self,
                "Command File Editor",
                "Discard unsaved command-file changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def confirm_save_or_discard_if_dirty(self) -> bool:
        if not self._dirty:
            return True
        message = QMessageBox(self)
        message.setWindowTitle("Command File Editor")
        message.setText(f"Save changes to {self.display_name()} before continuing?")
        message.setIcon(QMessageBox.Icon.Warning)
        save_button = message.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = message.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        message.setDefaultButton(save_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is save_button:
            return self.save()
        if clicked is discard_button:
            return True
        return clicked is not cancel_button and False

    def new_file(self) -> None:
        if not self.confirm_save_or_discard_if_dirty():
            return
        self.path = None
        self.editor.setPlainText("")
        self._dirty = False
        self.update_window_state()
        self.update_validation_status()

    def open_file(self) -> None:
        if not self.confirm_save_or_discard_if_dirty():
            return
        start_dir = str(self.path.parent if self.path else Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Command File",
            start_dir,
            "Text Files (*.txt *.cmd *.scr);;All Files (*)",
        )
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Open Command File", str(exc))
            return False
        self.path = path
        self.editor.setPlainText(text)
        self._dirty = False
        self.update_window_state()
        self.update_validation_status()
        return True

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(self.text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save Command File", str(exc))
            return False
        self._dirty = False
        self.update_window_state()
        self.status_label.setText(f"Saved {self.path}")
        return True

    def save_as(self) -> bool:
        start = str(self.path if self.path else Path.cwd() / "command-file.txt")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Command File",
            start,
            "Text Files (*.txt *.cmd *.scr);;All Files (*)",
        )
        if not path:
            return False
        self.path = Path(path)
        return self.save()

    def run_buffer(self) -> None:
        issues = self.sources.validation_issues(self.text(), warn_unknown=False)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            self.update_validation_status()
            QApplication.beep()
            return
        if self.run_callback:
            self.run_callback(self.text(), self.path)
            self.status_label.setText("Running editor buffer.")

    def reject(self) -> None:
        if self.confirm_discard_if_dirty():
            super().reject()
