import unittest

from PySide6.QtCore import Qt

from ComPort_Zone.command_completion import (
    ACCEPT,
    CANCEL,
    COMPLETION_NAVIGATION_KEYS,
    DISMISS,
    IGNORE,
    NAVIGATE,
    classify_completion_key,
)


class ClassifyCompletionKeyTests(unittest.TestCase):
    """The one place the terminal and editor agree on completion key behavior."""

    def test_tab_accepts(self) -> None:
        self.assertEqual(classify_completion_key(Qt.Key.Key_Tab), ACCEPT)
        self.assertEqual(classify_completion_key(Qt.Key.Key_Backtab), ACCEPT)

    def test_enter_dismisses_rather_than_accepts(self) -> None:
        # The whole point: Enter never accepts the suggestion in either surface.
        self.assertEqual(classify_completion_key(Qt.Key.Key_Return), DISMISS)
        self.assertEqual(classify_completion_key(Qt.Key.Key_Enter), DISMISS)

    def test_escape_cancels(self) -> None:
        self.assertEqual(classify_completion_key(Qt.Key.Key_Escape), CANCEL)

    def test_navigation_keys_navigate(self) -> None:
        for key in COMPLETION_NAVIGATION_KEYS:
            self.assertEqual(classify_completion_key(key), NAVIGATE)

    def test_other_keys_are_ignored(self) -> None:
        self.assertEqual(classify_completion_key(Qt.Key.Key_A), IGNORE)
        self.assertEqual(classify_completion_key(Qt.Key.Key_Space), IGNORE)


if __name__ == "__main__":
    unittest.main()
