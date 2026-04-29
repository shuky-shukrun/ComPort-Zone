from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from .command_editor_core import BATCH_KEYWORDS, CommandEditorSources


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
