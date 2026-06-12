"""Tests for the entry history ring and the chart/sparkline math helpers."""

from __future__ import annotations

import unittest

from ComPort_Zone.dashboard_history import (
    EntryHistory,
    HISTORY_MAX_SAMPLES,
    downsample_minmax,
    nearest_sample,
    nice_ticks,
)


class EntryHistoryTests(unittest.TestCase):
    def test_append_and_latest(self) -> None:
        history = EntryHistory()
        history.append(10.0, 1.0)
        history.append(11.0, 2.0)
        self.assertEqual(len(history), 2)
        self.assertEqual(history.latest(), (11.0, 2.0))

    def test_sample_count_cap(self) -> None:
        history = EntryHistory(max_samples=5)
        for index in range(20):
            history.append(float(index), float(index))
        self.assertEqual(len(history), 5)
        self.assertEqual(history.samples()[0], (15.0, 15.0))

    def test_age_cap_evicts_old_samples(self) -> None:
        history = EntryHistory(max_age_s=60.0)
        history.append(0.0, 1.0)
        history.append(30.0, 2.0)
        history.append(100.0, 3.0)  # cutoff = 40 -> first two evicted? 30 < 40 yes
        self.assertEqual([t for t, _v in history.samples()], [100.0])

    def test_window_slicing(self) -> None:
        history = EntryHistory()
        for index in range(10):
            history.append(float(index), float(index * 10))
        window = history.window(3.0, 6.0)
        self.assertEqual([t for t, _v in window], [3.0, 4.0, 5.0, 6.0])

    def test_value_bounds(self) -> None:
        history = EntryHistory()
        self.assertIsNone(history.value_bounds())
        for value in (5.0, -2.0, 9.0):
            history.append(value, value)
        self.assertEqual(history.value_bounds(), (-2.0, 9.0))

    def test_clear(self) -> None:
        history = EntryHistory()
        history.append(1.0, 1.0)
        history.clear()
        self.assertEqual(len(history), 0)
        self.assertIsNone(history.latest())

    def test_default_caps(self) -> None:
        history = EntryHistory()
        for index in range(HISTORY_MAX_SAMPLES + 50):
            history.append(float(index), 0.0)
        self.assertEqual(len(history), HISTORY_MAX_SAMPLES)


class DownsampleTests(unittest.TestCase):
    def test_small_input_passes_through(self) -> None:
        samples = [(float(i), float(i)) for i in range(8)]
        self.assertEqual(downsample_minmax(samples, 10), samples)

    def test_output_is_bounded(self) -> None:
        samples = [(float(i), float(i % 7)) for i in range(1000)]
        result = downsample_minmax(samples, 50)
        self.assertLessEqual(len(result), 2 * 50)

    def test_spikes_survive(self) -> None:
        samples = [(float(i), 1.0) for i in range(500)]
        samples[250] = (250.0, 99.0)   # positive spike
        samples[400] = (400.0, -99.0)  # negative spike
        result = downsample_minmax(samples, 20)
        values = [value for _t, value in result]
        self.assertIn(99.0, values)
        self.assertIn(-99.0, values)

    def test_zero_time_span(self) -> None:
        samples = [(5.0, float(i)) for i in range(100)]
        result = downsample_minmax(samples, 10)
        self.assertEqual(result, [samples[0], samples[-1]])

    def test_time_order_preserved(self) -> None:
        samples = [(float(i), float((i * 13) % 11)) for i in range(600)]
        result = downsample_minmax(samples, 40)
        times = [t for t, _v in result]
        self.assertEqual(times, sorted(times))


class NiceTicksTests(unittest.TestCase):
    def test_simple_ranges(self) -> None:
        self.assertEqual(nice_ticks(0.0, 10.0), [0.0, 2.0, 4.0, 6.0, 8.0, 10.0])
        self.assertEqual(nice_ticks(0.0, 1.0), [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
        self.assertEqual(nice_ticks(0.0, 100.0), [0.0, 20.0, 40.0, 60.0, 80.0, 100.0])

    def test_offset_range(self) -> None:
        ticks = nice_ticks(12.3, 13.9)
        self.assertTrue(all(12.3 <= tick <= 13.9 for tick in ticks))
        self.assertGreaterEqual(len(ticks), 3)

    def test_negative_range(self) -> None:
        ticks = nice_ticks(-50.0, 50.0)
        self.assertIn(0.0, ticks)
        self.assertEqual(ticks, sorted(ticks))

    def test_degenerate_range_pads(self) -> None:
        ticks = nice_ticks(5.0, 5.0)
        self.assertGreaterEqual(len(ticks), 2)
        self.assertLess(ticks[0], 5.0 + 1e-9)
        self.assertGreater(ticks[-1], 5.0 - 1e-9)

    def test_reversed_bounds(self) -> None:
        self.assertEqual(nice_ticks(10.0, 0.0), nice_ticks(0.0, 10.0))

    def test_non_finite(self) -> None:
        self.assertEqual(nice_ticks(float("nan"), 1.0), [])
        self.assertEqual(nice_ticks(0.0, float("inf")), [])


class NearestSampleTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertIsNone(nearest_sample([], 1.0))

    def test_picks_closest(self) -> None:
        samples = [(0.0, 10.0), (5.0, 20.0), (10.0, 30.0)]
        self.assertEqual(nearest_sample(samples, 6.2), (5.0, 20.0))
        self.assertEqual(nearest_sample(samples, 8.0), (10.0, 30.0))
        self.assertEqual(nearest_sample(samples, -3.0), (0.0, 10.0))


if __name__ == "__main__":
    unittest.main()
