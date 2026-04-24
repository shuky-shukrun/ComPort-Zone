import unittest

from ComPort_Zone.history import HistoryStore


class HistoryStoreTests(unittest.TestCase):
    def test_history_navigation_round_trips_to_current_draft(self) -> None:
        history = HistoryStore(["status", "reset"])
        self.assertEqual(history.navigate(-1, "draft"), "reset")
        self.assertEqual(history.navigate(-1, "draft"), "status")
        self.assertEqual(history.navigate(1, "draft"), "reset")
        self.assertEqual(history.navigate(1, "draft"), "draft")

    def test_suggestions_prioritize_frequency_then_recency(self) -> None:
        history = HistoryStore()
        history.add("status")
        history.add("help")
        history.add("status")
        history.add("set mode auto")
        history.add("status")
        self.assertEqual(history.suggestions("s")[:2], ["status", "set mode auto"])

    def test_suggestions_include_contains_matches_after_prefix_matches(self) -> None:
        history = HistoryStore(["factory reset", "reset counters", "status"])
        self.assertEqual(history.suggestions("set")[:2], ["reset counters", "factory reset"])


if __name__ == "__main__":
    unittest.main()
