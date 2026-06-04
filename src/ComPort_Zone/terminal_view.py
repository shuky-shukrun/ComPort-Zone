from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QLabel, QTextEdit

from .serial_core import SerialEvent
from .terminal_session_controller import TerminalRenderPlan

# Direction column ("TX"/"RX") padded to align with "SYS"/"ERR".
_DIR_WIDTH = 3


class TerminalView:
    def __init__(self, terminal: QTextEdit, search_count: QLabel) -> None:
        self.terminal = terminal
        self.search_count = search_count

    def find(self, query: str, *, backward: bool) -> bool:
        query = query.strip()
        if not query:
            return False
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self.terminal.find(query, flags):
            return True
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.terminal.setTextCursor(cursor)
        return self.terminal.find(query, flags)

    def refresh_search_highlights(
        self, text: str, highlight_color: str, highlight_foreground: str = "#ffffff"
    ) -> int:
        query = text.strip()
        selections: list[QTextEdit.ExtraSelection] = []
        if query:
            cursor = self.terminal.document().find(query)
            while not cursor.isNull():
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(highlight_color))
                fmt.setForeground(QColor(highlight_foreground))
                selection.format = fmt
                selections.append(selection)
                cursor = self.terminal.document().find(query, cursor)
        self.terminal.setExtraSelections(selections)
        self.search_count.setText(str(len(selections)))
        return len(selections)

    def render_plan(
        self,
        plan: TerminalRenderPlan,
        *,
        colors: Mapping[str, str],
        timestamps_enabled: bool,
        search_visible: bool,
        search_text: str,
        search_highlight: str,
    ) -> None:
        if plan.stream_text:
            self._render_stream_plan(plan, colors=colors, timestamps_enabled=timestamps_enabled)
        else:
            self._render_line_plan(plan, colors=colors, timestamps_enabled=timestamps_enabled)
        if search_visible:
            self.refresh_search_highlights(search_text, search_highlight)

    def _render_line_plan(
        self,
        plan: TerminalRenderPlan,
        *,
        colors: Mapping[str, str],
        timestamps_enabled: bool,
    ) -> None:
        if plan.ensure_line_break:
            self._ensure_terminal_line_break()
        message = plan.message.replace("\r\n", "\n").replace("\r", "\n")
        body_color, italic = self._body_format(plan, colors)
        for line in message.split("\n"):
            if line == "":
                continue
            leader = self._leader_runs(plan, timestamps_enabled, colors)
            self._insert_runs(
                [*leader, (line + "\n", body_color, italic)],
                hang_indent=self._leader_width(leader),
            )

    def _render_stream_plan(
        self,
        plan: TerminalRenderPlan,
        *,
        colors: Mapping[str, str],
        timestamps_enabled: bool,
    ) -> None:
        message = plan.message.replace("\r\n", "\n").replace("\r", "\n")
        if not message:
            return
        body_color, italic = self._body_format(plan, colors)
        at_line_start = self._terminal_at_line_start()
        if plan.stream_separator and not at_line_start and not message.startswith("\n"):
            self._insert_runs([(plan.stream_separator, body_color, italic)], hang_indent=0.0)
        for chunk in message.splitlines(keepends=True):
            if at_line_start and chunk != "\n":
                leader = self._leader_runs(plan, timestamps_enabled, colors)
                self._insert_runs(leader, hang_indent=self._leader_width(leader))
            self._insert_runs([(chunk, body_color, italic)], hang_indent=0.0)
            at_line_start = chunk.endswith("\n")

    def _leader_runs(
        self,
        plan: TerminalRenderPlan,
        timestamps_enabled: bool,
        colors: Mapping[str, str],
    ) -> list[tuple]:
        """The detached leader: a gray timestamp + a coloured direction column.
        Decoupled from the message so toggling timestamps re-renders cleanly."""
        runs: list[tuple] = []
        if timestamps_enabled:
            stamp = plan.event.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
            runs.append((f"{stamp} ", colors.get("timestamp", colors.get("default", "#5e6a7e"))))
        direction = (plan.direction or "").strip()
        if direction:
            dir_color = colors.get(plan.color_role, colors.get("default", "#d4d4d4"))
            runs.append((f"{direction.ljust(_DIR_WIDTH)} ", dir_color))
        return runs

    def _body_format(self, plan: TerminalRenderPlan, colors: Mapping[str, str]) -> tuple[str, bool]:
        role = plan.color_role
        body_color = colors.get(f"{role}_body", colors.get(role, colors.get("default", "#d4d4d4")))
        return body_color, role == "status"

    def _leader_width(self, leader_runs: list[tuple]) -> float:
        if not leader_runs:
            return 0.0
        text = "".join(run[0] for run in leader_runs)
        return float(QFontMetrics(self.terminal.font()).horizontalAdvance(text))

    def _insert_runs(self, runs: list[tuple], *, hang_indent: float) -> None:
        runs = [run for run in runs if run and run[0]]
        if not runs:
            return
        appender = getattr(self.terminal, "append_committed_runs", None)
        if callable(appender):
            appender(runs, hang_indent=hang_indent)
            return
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if hang_indent > 0:
            block_format = QTextBlockFormat()
            block_format.setLeftMargin(hang_indent)
            block_format.setTextIndent(-hang_indent)
            cursor.mergeBlockFormat(block_format)
        for run in runs:
            italic = run[2] if len(run) > 2 else False
            cursor.insertText(run[0], self._char_format(run[1], italic))
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()

    def _char_format(self, color: str, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _terminal_at_line_start(self) -> bool:
        text = self.terminal.toPlainText()
        return not text or text.endswith("\n")

    def _ensure_terminal_line_break(self) -> None:
        if self._terminal_at_line_start():
            return
        self._insert_runs([("\n", "#d4d4d4")], hang_indent=0.0)
