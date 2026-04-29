import unittest

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from ComPort_Zone.command_editor_core import CommandEditorSources
from ComPort_Zone.command_editor_highlighting import CommandFileHighlighter


class CommandEditorHighlightingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_highlighter_tracks_sources_and_warn_unknown_toggle(self) -> None:
        document = QTextDocument()
        sources = CommandEditorSources()
        highlighter = CommandFileHighlighter(document, sources)
        try:
            self.assertIs(highlighter.sources, sources)
            self.assertTrue(highlighter.warn_unknown)

            highlighter.set_warn_unknown(False)

            self.assertFalse(highlighter.warn_unknown)
        finally:
            document.deleteLater()


if __name__ == "__main__":
    unittest.main()
