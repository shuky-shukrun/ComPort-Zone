import os
import unittest

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from ComPort_Zone.icons import gradient_line_image_path


class GradientLineImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_multi_stop_strip_runs_green_to_blue_across_width(self) -> None:
        path = gradient_line_image_path(("#57d98a", "#38c4c0", "#4a9bff"), width=256, thickness=2)
        self.assertTrue(path.endswith(".png"))
        self.assertTrue(os.path.exists(path))
        image = QImage(path)
        self.assertEqual((image.width(), image.height()), (256, 2))

        left = image.pixelColor(0, 0)
        right = image.pixelColor(image.width() - 1, 0)
        self.assertEqual((left.alpha(), right.alpha()), (255, 255))
        # Left stop is green-dominant; right stop is blue-dominant — i.e. a real
        # dual-tone line, not a single flat color.
        self.assertGreater(left.green(), left.blue())
        self.assertGreater(right.blue(), right.green())
        self.assertNotEqual((left.red(), left.green(), left.blue()),
                            (right.red(), right.green(), right.blue()))

    def test_single_color_strip_is_flat(self) -> None:
        path = gradient_line_image_path(("#313a4c",), width=64, thickness=2)
        image = QImage(path)
        left = image.pixelColor(0, 0)
        right = image.pixelColor(image.width() - 1, 0)
        self.assertEqual(
            (left.red(), left.green(), left.blue()),
            (right.red(), right.green(), right.blue()),
        )

    def test_same_inputs_return_cached_path(self) -> None:
        a = gradient_line_image_path(("#57d98a", "#4a9bff"))
        b = gradient_line_image_path(("#57d98a", "#4a9bff"))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
