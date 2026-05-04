from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QLabel, QTextEdit

from .serial_core import SerialEvent
from .terminal_session_controller import TerminalRenderPlan


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

    def refresh_search_highlights(self, text: str, highlight_color: str) -> int:
        query = text.strip()
        selections: list[QTextEdit.ExtraSelection] = []
        if query:
            cursor = self.terminal.document().find(query)
            while not cursor.isNull():
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(highlight_color))
                fmt.setForeground(QColor("#ffffff"))
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
            self._render_stream_plan(
                plan,
                color=colors.get(plan.color_role, colors.get("default", "#d4d4d4")),
                timestamps_enabled=timestamps_enabled,
                search_visible=search_visible,
                search_text=search_text,
                search_highlight=search_highlight,
            )
            return
        if plan.ensure_line_break:
            self._ensure_terminal_line_break(colors.get("default", "#d4d4d4"))
        message = plan.message.replace("\r\n", "\n").replace("\r", "\n")
        if timestamps_enabled:
            stamp = plan.event.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
            rendered = "".join(
                f"[{stamp}] {plan.prefix}{line}\n"
                for line in message.split("\n")
                if line != ""
            )
        else:
            rendered = "".join(
                f"{plan.prefix}{line}\n"
                for line in message.split("\n")
                if line != ""
            )
        self.insert_text(
            rendered,
            colors.get(plan.color_role, colors.get("default", "#d4d4d4")),
            search_visible=search_visible,
            search_text=search_text,
            search_highlight=search_highlight,
        )

    def _render_stream_plan(
        self,
        plan: TerminalRenderPlan,
        *,
        color: str,
        timestamps_enabled: bool,
        search_visible: bool,
        search_text: str,
        search_highlight: str,
    ) -> None:
        message = plan.message.replace("\r\n", "\n").replace("\r", "\n")
        if not message:
            return
        rendered = self._leadered_stream(message, plan, timestamps_enabled=timestamps_enabled)
        self.insert_text(
            rendered,
            color,
            search_visible=search_visible,
            search_text=search_text,
            search_highlight=search_highlight,
        )

    def insert_text(
        self,
        text: str,
        color: str,
        *,
        search_visible: bool,
        search_text: str,
        search_highlight: str,
    ) -> None:
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text, fmt)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        if search_visible:
            self.refresh_search_highlights(search_text, search_highlight)

    def _leadered_stream(
        self,
        message: str,
        plan: TerminalRenderPlan,
        *,
        timestamps_enabled: bool,
    ) -> str:
        stamp = (
            f"[{plan.event.timestamp.astimezone().strftime('%H:%M:%S.%f')[:-3]}] "
            if timestamps_enabled
            else ""
        )
        leader = f"{stamp}{plan.prefix}"
        rendered: list[str] = []
        at_line_start = self._terminal_at_line_start()
        for chunk in message.splitlines(keepends=True):
            if at_line_start and chunk != "\n":
                rendered.append(leader)
            rendered.append(chunk)
            at_line_start = chunk.endswith("\n")
        return "".join(rendered)

    def _terminal_at_line_start(self) -> bool:
        text = self.terminal.toPlainText()
        return not text or text.endswith("\n")

    def _ensure_terminal_line_break(self, color: str) -> None:
        if self._terminal_at_line_start():
            return
        self.insert_text(
            "\n",
            color,
            search_visible=False,
            search_text="",
            search_highlight="#000000",
        )
