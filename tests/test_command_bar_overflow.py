import unittest

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QWidget

from ComPort_Zone.widgets import fit_overflow_groups


class _FixedHintWidget(QWidget):
    """Reports a fixed sizeHint width but can shrink to nothing — like the real
    command-bar controls, so the bar can be forced narrower than its natural size."""

    def __init__(self, hint_width: int) -> None:
        super().__init__()
        self._hint_width = hint_width
        self.setMinimumWidth(0)

    def sizeHint(self) -> QSize:
        return QSize(self._hint_width, 24)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class FitOverflowGroupsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def _make_bar(self):
        bar = QFrame()
        bar.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        bar.setMinimumWidth(0)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        def widget(width: int) -> _FixedHintWidget:
            item = _FixedHintWidget(width)
            layout.addWidget(item)
            return item

        keep = widget(100)
        groups = [[widget(80)], [widget(80)], [widget(80)]]
        overflow = _FixedHintWidget(20)
        layout.addWidget(overflow)
        bar.show()
        return bar, keep, groups, overflow

    def _collapsed_at(self, bar, keep, groups, overflow, width: int) -> int:
        bar.resize(width, 32)
        self.qt.processEvents()
        self.assertEqual(bar.width(), width)  # the bar really is this narrow
        return len(fit_overflow_groups(bar, [keep], groups, overflow, reserve=0))

    def test_wide_bar_keeps_every_group_and_hides_overflow(self) -> None:
        bar, keep, groups, overflow = self._make_bar()
        try:
            self.assertEqual(self._collapsed_at(bar, keep, groups, overflow, 600), 0)
            self.assertTrue(overflow.isHidden())
            self.assertFalse(any(widget.isHidden() for group in groups for widget in group))
        finally:
            bar.deleteLater()

    def test_narrow_bar_folds_all_groups_keeping_fixed_and_overflow(self) -> None:
        bar, keep, groups, overflow = self._make_bar()
        try:
            # Only the fixed widget (100) + overflow (20) fit.
            self.assertEqual(self._collapsed_at(bar, keep, groups, overflow, 130), 3)
            self.assertFalse(keep.isHidden())
            self.assertFalse(overflow.isHidden())
            self.assertTrue(all(widget.isHidden() for group in groups for widget in group))
        finally:
            bar.deleteLater()

    def test_collapse_count_grows_monotonically_as_the_bar_narrows(self) -> None:
        bar, keep, groups, overflow = self._make_bar()
        try:
            counts = [
                self._collapsed_at(bar, keep, groups, overflow, width)
                for width in (600, 360, 280, 200, 130)
            ]
            self.assertEqual(counts, sorted(counts))  # never un-collapses as it shrinks
            self.assertEqual(counts[0], 0)
            self.assertEqual(counts[-1], len(groups))
        finally:
            bar.deleteLater()


if __name__ == "__main__":
    unittest.main()
