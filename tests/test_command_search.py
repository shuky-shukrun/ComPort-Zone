import unittest

from ComPort_Zone.command_search import CommandSearchState, find_search_matches, replace_all_matches


class CommandSearchTests(unittest.TestCase):
    def test_find_search_matches_is_case_insensitive_by_default(self) -> None:
        self.assertEqual(
            find_search_matches("SEND VOLT?\nSEND volt?\n", "volt"),
            [(5, 9), (16, 20)],
        )
        self.assertEqual(
            find_search_matches("SEND VOLT?\nSEND volt?\n", "volt", case_sensitive=True),
            [(16, 20)],
        )
        self.assertEqual(find_search_matches("abc", ""), [])

    def test_search_state_refresh_and_navigation(self) -> None:
        state = CommandSearchState()

        self.assertEqual(
            state.refresh("one two one", "one", case_sensitive=False, cursor_position=1, reset=True),
            (8, 11),
        )
        self.assertEqual(state.count_label, "2/2")
        self.assertEqual(state.move_next(), (0, 3))
        self.assertEqual(state.count_label, "1/2")
        self.assertEqual(state.move_previous(), (8, 11))
        self.assertEqual(state.count_label, "2/2")

        self.assertIsNone(state.refresh("one two", "missing", case_sensitive=False, cursor_position=0, reset=True))
        self.assertEqual(state.count_label, "0/0")

    def test_replace_all_matches_rewrites_original_text(self) -> None:
        text = "SEND VOLT?\nSEND CURR?\n"
        matches = find_search_matches(text, "SEND")

        self.assertEqual(replace_all_matches(text, matches, "EXPECT"), "EXPECT VOLT?\nEXPECT CURR?\n")


if __name__ == "__main__":
    unittest.main()
