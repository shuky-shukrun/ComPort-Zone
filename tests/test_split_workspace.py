import unittest

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from ComPort_Zone.ui.split_workspace import TAB_MIME_TYPE, SplitWorkspaceWidget
from ComPort_Zone.ui.tokens import WORKSPACE_PANE_MIN_W


class FakeDragEvent:
    def __init__(self, index: int, position: QPointF) -> None:
        self._mime = QMimeData()
        self._mime.setData(TAB_MIME_TYPE, QByteArray(str(index).encode("ascii")))
        self._position = position
        self.accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime

    def position(self) -> QPointF:
        return self._position

    def acceptProposedAction(self) -> None:
        self.accepted = True


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
        # Updates are suppressed only during the reparent and restored after
        # (a live control panel paints on a timer; a paint mid-reparent
        # crashes Qt) — the moved widget must be paintable again.
        self.assertTrue(second.updatesEnabled())

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

    def test_new_tab_menu_targets_requesting_pane_despite_focus_change(self) -> None:
        # The right pane's + opens a modal menu; while it is up a focus event flips
        # the active pane back to the left. The new tab must still land in the pane
        # whose + was clicked (the right one), not the focus-stolen left pane.
        workspace = SplitWorkspaceWidget()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.move_tab_to_other_pane(1)  # second -> right pane
        left, right = workspace.panes()
        self.assertEqual((left.count(), right.count()), (1, 1))

        created: list[QWidget] = []

        def on_menu(_position):
            # Stand in for the modal menu: focus flips to the left pane, then the
            # chosen action creates a tab.
            workspace._activate_pane(left)
            self.assertIs(workspace.active_pane(), left)
            new_tab = QWidget()
            created.append(new_tab)
            workspace.addTab(new_tab, "New")

        workspace.newTabMenuRequested.connect(on_menu)
        workspace._new_tab_menu_requested(right, QPoint(0, 0))

        self.assertEqual(right.count(), 2)
        self.assertEqual(left.count(), 1)
        self.assertIs(right.widget(1), created[0])
        # Pin is cleared once the menu closes, so later adds follow the active pane.
        self.assertIsNone(workspace._pending_tab_pane)

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()
        created[0].deleteLater()

    def test_panes_have_small_minimum_width_so_divider_stays_movable(self) -> None:
        # Each pane keeps a small hard floor; without it the terminal/editor content
        # size hints pin the divider and it looks frozen at common window sizes.
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.move_tab_to_other_pane(1)  # two panes
        self.qt.processEvents()
        self.assertEqual(workspace.pane_count(), 2)
        for pane in workspace.panes():
            self.assertEqual(pane.minimumWidth(), WORKSPACE_PANE_MIN_W)

        # The splitter honors the small floor: a pane can shrink near it instead of
        # being clamped to its (larger) content size hint.
        workspace.splitter.setSizes([WORKSPACE_PANE_MIN_W, 900 - WORKSPACE_PANE_MIN_W])
        self.qt.processEvents()
        self.assertLessEqual(workspace.panes()[0].width(), WORKSPACE_PANE_MIN_W + 40)

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()

    def test_tab_index_at_returns_global_index_in_second_pane(self) -> None:
        # Regression for issue #11: a context menu opened on the right pane's tab must
        # resolve to that tab's *global* index, not its pane-local one (which would
        # alias the left pane's tab and rename/close/etc. the wrong tab).
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.move_tab_to_other_pane(1)  # second -> right pane (global index 1)
        self.qt.processEvents()
        left, right = workspace.panes()
        self.assertIs(workspace.active_pane(), right)

        position = right.tabBar().tabRect(0).center()
        self.assertEqual(right.tabBar().tabAt(position), 0)  # pane-local
        self.assertEqual(workspace.tab_index_at(position), 1)  # global
        self.assertIs(workspace.widget(workspace.tab_index_at(position)), second)

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

    def test_drop_preview_offers_split_down_for_a_low_drop(self) -> None:
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        workspace.addTab(QWidget(), "Terminal")

        workspace._show_drop_preview(FakeDragEvent(0, QPointF(250, 430)))
        self.qt.processEvents()

        self.assertEqual(workspace.drop_preview.text(), "Release to split down")
        # The preview fills the bottom half rather than a right-hand column.
        self.assertGreater(workspace.drop_preview.geometry().top(), workspace.height() // 2)

        workspace.deleteLater()

    def test_dropping_a_tab_low_splits_the_view_down(self) -> None:
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        workspace.addTab(QWidget(), "Terminal")

        event = FakeDragEvent(0, QPointF(250, 430))
        workspace.dropEvent(event)
        self.qt.processEvents()

        self.assertTrue(event.accepted)
        self.assertEqual(workspace.pane_count(), 2)
        self.assertEqual(workspace.splitter.orientation(), Qt.Orientation.Vertical)

        workspace.deleteLater()

    def test_dropping_a_tab_to_the_right_splits_the_view_right(self) -> None:
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        workspace.addTab(QWidget(), "Terminal")

        workspace.dropEvent(FakeDragEvent(0, QPointF(750, 120)))
        self.qt.processEvents()

        self.assertEqual(workspace.pane_count(), 2)
        self.assertEqual(workspace.splitter.orientation(), Qt.Orientation.Horizontal)

        workspace.deleteLater()

    def test_dragging_a_tab_between_panes_keeps_the_current_orientation(self) -> None:
        # Regression: the drop used to force a horizontal split, flipping a vertical
        # (split-down) layout to side-by-side when a tab was dragged between panes.
        workspace = SplitWorkspaceWidget()
        workspace.resize(900, 500)
        workspace.show()
        self.qt.processEvents()
        first = QWidget()
        second = QWidget()
        workspace.addTab(first, "First")
        workspace.addTab(second, "Second")
        workspace.split_current_down()
        self.qt.processEvents()
        self.assertEqual(workspace.splitter.orientation(), Qt.Orientation.Vertical)

        workspace.dropEvent(FakeDragEvent(workspace.indexOf(first), QPointF(100, 100)))
        self.qt.processEvents()

        self.assertEqual(workspace.splitter.orientation(), Qt.Orientation.Vertical)

        workspace.deleteLater()
        first.deleteLater()
        second.deleteLater()


if __name__ == "__main__":
    unittest.main()
