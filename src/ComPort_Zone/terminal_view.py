from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

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
# Timestamp column renders "HH:MM:SS.mmm" (12 cells); the input prompt borrows
# that same width so the tab-name label aligns under the history timestamps.
_TIMESTAMP_WIDTH = 12


def clamp_prompt_label(label: str, width: int = _TIMESTAMP_WIDTH) -> str:
    """Collapse whitespace and clamp ``label`` to ``width`` cells, eliding with …
    so the prompt's tab name never overflows the timestamp column."""
    label = " ".join(str(label).split())
    if len(label) <= width:
        return label
    if width <= 1:
        return label[:width]
    return label[: width - 1] + "…"


def prompt_leader_text(label: str, *, timestamps_enabled: bool, chevron: str = ">") -> str:
    """Columnar leader for the input prompt, mirroring :meth:`_leader_runs`.

    The tab name fills the timestamp column and ``chevron`` (normally ``>``, or an
    auto-reconnect spinner frame) sits in the direction column, so the caret lines up
    under the transcript message column. With timestamps off there is no timestamp
    column, so only the chevron shows."""
    chevron = chevron.ljust(_DIR_WIDTH)
    label = clamp_prompt_label(label)
    if timestamps_enabled and label:
        return f"{label.ljust(_TIMESTAMP_WIDTH)} {chevron} "
    return f"{chevron} "


class TerminalView:
    def __init__(self, terminal: QTextEdit, search_count: QLabel) -> None:
        self.terminal = terminal
        self.search_count = search_count
        self._batch_active = False
        self._batch_changed = False
        self._pending_search: tuple[str, str] | None = None

    @contextmanager
    def batch_render(self) -> Iterator[None]:
        """Lay out a burst once while keeping every event's text and metadata."""
        if self._batch_active:
            yield
            return
        document = self.terminal.document()
        layout_enabled = document.isLayoutEnabled()
        self._batch_active = True
        self._batch_changed = False
        self._pending_search = None
        try:
            yield
        finally:
            self._batch_active = False
            if self._batch_changed:
                document.setLayoutEnabled(layout_enabled)
                if layout_enabled:
                    self.terminal.ensureCursorVisible()
            if self._pending_search is not None:
                self.refresh_search_highlights(*self._pending_search)
            self._pending_search = None

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
        with self.batch_render():
            # A drain containing only hidden control-panel traffic or paused RX
            # must not invalidate an unchanged terminal's layout.
            if not self._batch_changed:
                self.terminal.document().setLayoutEnabled(False)
                self._batch_changed = True
            if plan.stream_text:
                self._render_stream_plan(plan, colors=colors, timestamps_enabled=timestamps_enabled)
            else:
                self._render_line_plan(plan, colors=colors, timestamps_enabled=timestamps_enabled)
            if search_visible:
                self._pending_search = (search_text, search_highlight)

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
        return body_color, role in {"status", "script"}

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
        if self.terminal.document().isLayoutEnabled():
            self.terminal.ensureCursorVisible()

    def _char_format(self, color: str, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _terminal_at_line_start(self) -> bool:
        committed_end = getattr(self.terminal, "committed_end_cursor", None)
        if callable(committed_end):
            cursor = committed_end()
        else:
            cursor = QTextCursor(self.terminal.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
        # Inspect only the insertion point. Reading toPlainText here copies all
        # prior output once per RX chunk, making long-lived sessions crawl.
        return (
            cursor.atBlockStart()
            or self.terminal.document().characterAt(cursor.position() - 1) == "\u2028"
        )

    def _ensure_terminal_line_break(self) -> None:
        if self._terminal_at_line_start():
            return
        self._insert_runs([("\n", "#d4d4d4")], hang_indent=0.0)
