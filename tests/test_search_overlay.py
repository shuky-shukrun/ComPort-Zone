import unittest

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.ui.search_overlay import SearchOverlay


class SearchOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_replace_mode_emits_signals_and_closes(self) -> None:
        host = QWidget()
        host.resize(520, 320)
        overlay = SearchOverlay(host, with_replace=True, parent=host)
        fired: list[str] = []
        overlay.findNext.connect(lambda: fired.append("next"))
        overlay.findPrevious.connect(lambda: fired.append("prev"))
        overlay.replaceOne.connect(lambda: fired.append("one"))
        overlay.replaceAll.connect(lambda: fired.append("all"))
        overlay.closeRequested.connect(lambda: fired.append("close"))
        try:
            host.show()
            overlay.open_for("cal", replace=True)
            self.qt.processEvents()

            self.assertEqual(overlay.search_field.text(), "cal")
            self.assertTrue(overlay._replace_holder.isVisibleTo(overlay))
            overlay.set_count("1/6")
            self.assertEqual(overlay.count_label.text(), "1/6")

            overlay.next_button.click()
            overlay.prev_button.click()
            overlay.replace_one_button.click()
            overlay.replace_all_button.click()
            overlay.close_button.click()
            self.assertEqual(fired, ["next", "prev", "one", "all", "close"])
            self.assertTrue(overlay.isHidden())
        finally:
            host.deleteLater()
            self.qt.processEvents()

    def test_find_only_mode_hides_replace_row(self) -> None:
        host = QWidget()
        host.resize(400, 200)
        overlay = SearchOverlay(host, with_replace=False, parent=host)
        try:
            host.show()
            overlay.open_for("x", replace=True)  # ignored: built without replace
            self.qt.processEvents()
            self.assertFalse(overlay._replace_holder.isVisibleTo(overlay))
            self.assertIsNone(overlay.toggle_button)  # no replace chevron in find-only
            self.assertFalse(overlay.is_case_sensitive())
            overlay.case_button.setChecked(True)
            self.assertTrue(overlay.is_case_sensitive())
        finally:
            host.deleteLater()
            self.qt.processEvents()

    def test_chevron_toggles_replace_row(self) -> None:
        host = QWidget()
        host.resize(520, 300)
        overlay = SearchOverlay(host, with_replace=True, parent=host)
        try:
            host.show()
            overlay.open_for("x", replace=False)  # find mode -> replace collapsed
            self.qt.processEvents()
            self.assertIsNotNone(overlay.toggle_button)
            self.assertFalse(overlay._replace_shown)

            overlay.toggle_button.click()
            self.assertTrue(overlay._replace_shown)
            self.assertTrue(overlay._replace_holder.isVisibleTo(overlay))

            overlay.toggle_button.click()
            self.assertFalse(overlay._replace_shown)
        finally:
            host.deleteLater()
            self.qt.processEvents()


if __name__ == "__main__":
    unittest.main()
