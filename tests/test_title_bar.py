import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QMenuBar

from ComPort_Zone.ui.title_bar import TitleBar


class TitleBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def _build(self):
        window = QMainWindow()
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        bar = TitleBar(window, Path("does-not-exist.png"))
        menu = QMenuBar(window)
        for name in ("File", "Edit", "View", "Session", "Serial", "Tools", "Help"):
            menu.addMenu(name)
        bar.attach_menu_bar(menu)
        window.setMenuWidget(bar)
        window.resize(1200, 600)
        window.show()
        self.qt.processEvents()
        return window, bar, menu

    def test_command_center_click_requests_the_palette(self) -> None:
        window, bar, _menu = self._build()
        try:
            requests: list[str] = []
            bar.commandPaletteRequested.connect(lambda: requests.append("palette"))
            bar.command_center.click()
            self.assertEqual(requests, ["palette"])
        finally:
            window.deleteLater()
            self.qt.processEvents()

    def test_menu_bar_sits_in_the_single_title_row(self) -> None:
        window, bar, menu = self._build()
        try:
            self.assertIs(menu.parent(), bar)
            self.assertGreaterEqual(bar._layout.indexOf(menu), 0)
            self.assertIs(window.menuWidget(), bar)  # no separate menu row
        finally:
            window.deleteLater()
            self.qt.processEvents()

    def test_command_center_hides_when_the_window_is_narrow(self) -> None:
        window, bar, _menu = self._build()
        try:
            window.resize(1200, 600)
            self.qt.processEvents()
            self.assertFalse(bar.command_center.isHidden())

            window.resize(480, 600)
            self.qt.processEvents()
            self.assertTrue(bar.command_center.isHidden())
        finally:
            window.deleteLater()
            self.qt.processEvents()

    def test_set_subtitle_updates_the_window_title(self) -> None:
        window, bar, _menu = self._build()
        try:
            bar.set_subtitle("Connected · COM6")
            self.assertIn("Connected · COM6", window.windowTitle())
            bar.set_subtitle("")
            self.assertEqual(window.windowTitle(), "ComPort Zone")
        finally:
            window.deleteLater()
            self.qt.processEvents()


if __name__ == "__main__":
    unittest.main()
