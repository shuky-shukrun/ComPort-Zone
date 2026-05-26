import unittest

from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from ComPort_Zone.ui.split_workspace import TAB_MIME_TYPE, SplitWorkspaceWidget


class FakeDragEvent:
    def __init__(self, index: int, position: QPointF) -> None:
        self._mime = QMimeData()
        self._mime.setData(TAB_MIME_TYPE, QByteArray(str(index).encode("ascii")))
        self._position = position

    def mimeData(self) -> QMimeData:
        return self._mime

    def position(self) -> QPointF:
        return self._position


class SplitWorkspaceWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_starts_with_one_pane(self) -> None:
        workspace = SplitWorkspaceWidget()

        self.assertEqual(workspace.pane_count(), 1)
        self.assertEqual(workspace.count(), 0)

        workspace.deleteLater()

    def test_move_tab_to_other_pane_preserves_widget_instance(self) -> None:
        workspace = SplitWorkspaceWidget()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")

        self.assertTrue(workspace.move_tab_to_other_pane(1))

        self.assertEqual(workspace.pane_count(), 2)
        self.assertIs(workspace.currentWidget(), second)
        self.assertEqual(workspace.indexOf(first), 0)
        self.assertEqual(workspace.indexOf(second), 1)

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()

    def test_splitting_only_tab_keeps_empty_source_pane_visible(self) -> None:
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        terminal = QWidget()
        workspace.addTab(terminal, "Terminal")

        self.assertTrue(workspace.split_current_right())
        self.qt.processEvents()

        self.assertEqual(workspace.pane_count(), 2)
        self.assertEqual(workspace.panes()[0].count(), 0)
        self.assertEqual(workspace.panes()[1].count(), 1)
        self.assertIs(workspace.currentWidget(), terminal)
        sizes = workspace.splitter.sizes()
        self.assertEqual(len(sizes), 2)
        self.assertGreater(sizes[0], 0)
        self.assertGreater(sizes[1], 0)

        workspace.deleteLater()
        terminal.deleteLater()

    def test_removing_last_tab_collapses_empty_pane(self) -> None:
        workspace = SplitWorkspaceWidget()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.move_tab_to_other_pane(1)

        workspace.removeTab(workspace.indexOf(second))

        self.assertEqual(workspace.pane_count(), 1)
        self.assertEqual(workspace.count(), 1)
        self.assertIs(workspace.widget(0), first)

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()

    def test_clicking_tab_content_activates_that_pane(self) -> None:
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        first = QLineEdit()
        second = QLineEdit()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.move_tab_to_other_pane(1)
        self.qt.processEvents()

        self.assertIs(workspace.currentWidget(), second)

        QTest.mouseClick(first, Qt.MouseButton.LeftButton)
        self.qt.processEvents()

        self.assertIs(workspace.currentWidget(), first)
        self.assertIs(workspace.active_pane(), workspace.panes()[0])

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()

    def test_join_panes_moves_tabs_back_to_primary_pane(self) -> None:
        workspace = SplitWorkspaceWidget()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.move_tab_to_other_pane(1)

        self.assertTrue(workspace.join_panes())

        self.assertEqual(workspace.pane_count(), 1)
        self.assertEqual(workspace.count(), 2)
        self.assertIs(workspace.widget(0), first)
        self.assertIs(workspace.widget(1), second)

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()

    def test_configure_layout_tracks_orientation_and_active_pane(self) -> None:
        workspace = SplitWorkspaceWidget()

        workspace.configure_layout(
            orientation=Qt.Orientation.Vertical,
            active_pane=1,
            splitter_sizes=[300, 500],
        )

        self.assertEqual(workspace.pane_count(), 2)
        self.assertEqual(workspace.splitter.orientation(), Qt.Orientation.Vertical)
        self.assertIs(workspace.active_pane(), workspace.panes()[1])

        workspace.deleteLater()

    def test_drop_preview_shows_resulting_split_zone(self) -> None:
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        tab = QWidget()
        workspace.addTab(tab, "Terminal")

        workspace._show_drop_preview(FakeDragEvent(0, QPointF(20, 20)))
        self.qt.processEvents()

        self.assertTrue(workspace.drop_preview.isVisible())
        self.assertEqual(workspace.drop_preview.text(), "Release to split right")
        self.assertGreater(workspace.drop_preview.geometry().left(), workspace.width() // 2)

        workspace.deleteLater()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
