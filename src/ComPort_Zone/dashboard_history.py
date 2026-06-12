"""Bounded numeric history for dashboard entries (FR-46) + paint math.

One :class:`EntryHistory` per numeric entry lives in the dashboard tab
while it is open — never persisted (NFR-3; CSV logging is the durable
record). Time is whatever monotonic clock the tab injects, so all tests
run on a fake clock. The helpers (:func:`downsample_minmax`,
:func:`nice_ticks`, :func:`nearest_sample`) carry the sparkline/chart
math so painting code stays a thin Qt shell.

Qt-free by design (enforced via ``core/dashboard.py`` re-exports).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence

HISTORY_MAX_SAMPLES = 600
HISTORY_MAX_AGE_S = 3600.0

Sample = tuple[float, float]  # (monotonic seconds, value)


class EntryHistory:
    """Ring of (time, value) samples bounded by count and age."""

    __slots__ = ("_samples", "_max_age_s")

    def __init__(
        self,
        *,
        max_samples: int = HISTORY_MAX_SAMPLES,
        max_age_s: float = HISTORY_MAX_AGE_S,
    ) -> None:
        self._samples: deque[Sample] = deque(maxlen=max_samples)
        self._max_age_s = max_age_s

    def append(self, t: float, value: float) -> None:
        """Add a sample; evicts everything older than the age cap."""
        self._samples.append((t, value))
        cutoff = t - self._max_age_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def samples(self) -> list[Sample]:
        return list(self._samples)

    def window(self, start: float, end: float) -> list[Sample]:
        """Samples with start <= t <= end (history is time-ordered)."""
        return [sample for sample in self._samples if start <= sample[0] <= end]

    def latest(self) -> Sample | None:
        return self._samples[-1] if self._samples else None

    def value_bounds(self) -> tuple[float, float] | None:
        if not self._samples:
            return None
        values = [value for _t, value in self._samples]
        return min(values), max(values)

    def clear(self) -> None:
        self._samples.clear()

    def __len__(self) -> int:
        return len(self._samples)


def downsample_minmax(samples: Sequence[Sample], buckets: int) -> list[Sample]:
    """Decimate ``samples`` to at most ``2 * buckets`` points by keeping
    each time-bucket's minimum and maximum — spikes survive, which a plain
    stride would lose. Input must be time-ordered."""
    if buckets <= 0 or len(samples) <= 2 * buckets:
        return list(samples)
    start = samples[0][0]
    end = samples[-1][0]
    span = end - start
    if span <= 0:
        return [samples[0], samples[-1]]
    result: list[Sample] = []
    bucket_width = span / buckets
    index = 0
    total = len(samples)
    for bucket in range(buckets):
        bucket_end = start + (bucket + 1) * bucket_width
        low: Sample | None = None
        high: Sample | None = None
        while index < total and (samples[index][0] <= bucket_end or bucket == buckets - 1):
            sample = samples[index]
            if low is None or sample[1] < low[1]:
                low = sample
            if high is None or sample[1] > high[1]:
                high = sample
            index += 1
        if low is None or high is None:
            continue
        result.extend(sorted({low, high}, key=lambda item: item[0]))
    return result


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Rounded axis tick positions covering [lo, hi] (1/2/5 * 10^n steps)."""
    if not math.isfinite(lo) or not math.isfinite(hi):
        return []
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        # Degenerate range: pad around the value so the axis has body.
        pad = max(abs(lo) * 0.1, 1.0)
        lo, hi = lo - pad, hi + pad
    span = hi - lo
    raw_step = span / max(1, target)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    residual = raw_step / magnitude
    if residual <= 1:
        step = magnitude
    elif residual <= 2:
        step = 2 * magnitude
    elif residual <= 5:
        step = 5 * magnitude
    else:
        step = 10 * magnitude
    first = math.ceil(lo / step) * step
    ticks: list[float] = []
    tick = first
    while tick <= hi + step * 1e-9:
        # Snap floating noise (e.g. 0.30000000000000004) for clean labels.
        ticks.append(round(tick, 10))
        tick += step
    return ticks


def nearest_sample(samples: Sequence[Sample], t: float) -> Sample | None:
    """The sample whose time is closest to ``t`` (for the chart cursor)."""
    if not samples:
        return None
    return min(samples, key=lambda sample: abs(sample[0] - t))
