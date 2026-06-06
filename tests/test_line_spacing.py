import unittest

from PySide6.QtGui import QTextBlockFormat
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from ComPort_Zone.widgets import LineSpacingController, apply_line_spacing

_PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value


class LineSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def _line_heights(self, edit: QPlainTextEdit) -> list:
        heights = []
        block = edit.document().firstBlock()
        while block.isValid():
            fmt = block.blockFormat()
            heights.append((fmt.lineHeight(), fmt.lineHeightType()))
            block = block.next()
        return heights

    def test_controller_applies_to_existing_and_appended_lines(self) -> None:
        edit = QPlainTextEdit()
        edit.setPlainText("a\nb\nc")
        controller = LineSpacingController(edit)
        controller.set_percent(135)
        self.assertEqual(self._line_heights(edit), [(135.0, _PROPORTIONAL)] * 3)

        edit.appendPlainText("d")  # a line that streams in / is typed afterwards
        last = edit.document().lastBlock().blockFormat()
        self.assertEqual((last.lineHeight(), last.lineHeightType()), (135.0, _PROPORTIONAL))
        edit.deleteLater()

    def test_apply_line_spacing_sets_the_whole_document(self) -> None:
        edit = QPlainTextEdit()
        edit.setPlainText("x\ny")
        apply_line_spacing(edit, 120)
        self.assertEqual(self._line_heights(edit), [(120.0, _PROPORTIONAL)] * 2)
        edit.deleteLater()


if __name__ == "__main__":
    unittest.main()
