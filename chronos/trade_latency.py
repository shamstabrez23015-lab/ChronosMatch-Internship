"""ChronosMatch Trade Latency Tracking Module.

Provides nanosecond-precision trade latency tracking using time.perf_counter_ns(),
capturing trade execution entry and exit timestamps, calculating latency,
maintaining running metrics (count, avg, min, max, percentiles), and providing
immutable metrics snapshots for dashboard and benchmark consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union


@dataclass(frozen=True)
class TradeLatencySnapshot:
    """Immutable point-in-time snapshot of trade latency metrics.

    Implements the standard ChronosMatch metrics interface:
      - trade_count: Total number of trades executed and measured.
      - avg_latency_ns: Arithmetic mean execution latency in nanoseconds.
      - min_latency_ns: Minimum observed execution latency in nanoseconds.
      - max_latency_ns: Maximum observed execution latency in nanoseconds.
    """

    trade_count: int = 0
    avg_latency_ns: float = 0.0
    min_latency_ns: int = 0
    max_latency_ns: int = 0
    last_latency_ns: int = 0
    total_latency_ns: int = 0
    p50_latency_ns: float = 0.0
    p90_latency_ns: float = 0.0
    p99_latency_ns: float = 0.0

    @property
    def avg_latency_us(self) -> float:
        """Average latency in microseconds."""
        return self.avg_latency_ns / 1_000.0

    @property
    def min_latency_us(self) -> float:
        """Minimum latency in microseconds."""
        return self.min_latency_ns / 1_000.0

    @property
    def max_latency_us(self) -> float:
        """Maximum latency in microseconds."""
        return self.max_latency_ns / 1_000.0

    @property
    def last_latency_us(self) -> float:
        """Last latency in microseconds."""
        return self.last_latency_ns / 1_000.0

    def as_dict(self) -> Dict[str, Any]:
        """Return metrics as a dictionary."""
        return {
            "trade_count": self.trade_count,
            "avg_latency_ns": self.avg_latency_ns,
            "min_latency_ns": self.min_latency_ns,
            "max_latency_ns": self.max_latency_ns,
            "last_latency_ns": self.last_latency_ns,
            "total_latency_ns": self.total_latency_ns,
            "p50_latency_ns": self.p50_latency_ns,
            "p90_latency_ns": self.p90_latency_ns,
            "p99_latency_ns": self.p99_latency_ns,
            "avg_latency_us": self.avg_latency_us,
            "min_latency_us": self.min_latency_us,
            "max_latency_us": self.max_latency_us,
        }

    # Dict-like compatibility for dashboard / downstream consumers
    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> List[str]:
        return list(self.as_dict().keys())

    def values(self) -> List[Any]:
        return list(self.as_dict().values())

    def items(self) -> List[Tuple[str, Any]]:
        return list(self.as_dict().items())

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


class _TradeLatencyTimer:
    """Context manager for measuring trade execution duration."""

    def __init__(self, tracker: TradeLatencyTracker, count: int = 1) -> None:
        self.tracker = tracker
        self.count = count
        self.entry_ns: int = 0
        self.exit_ns: int = 0
        self.latency_ns: int = 0

    def __enter__(self) -> _TradeLatencyTimer:
        self.entry_ns = self.tracker.start_trade()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.exit_ns = self.tracker.clock()
        lat = (
            max(0, self.exit_ns - self.entry_ns)
            if self.exit_ns >= self.entry_ns
            else 0
        )
        self.latency_ns = lat
        self.tracker.record_latency(lat, count=self.count)


class TradeLatencyTracker:
    """Low-overhead nanosecond trade latency tracker.

    Uses time.perf_counter_ns() by default for high-resolution timing.
    Maintains O(1) running accumulators for count, sum, min, and max latency,
    avoiding heap allocations during hot-path execution.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], int]] = None,
        max_samples: int = 100_000,
    ) -> None:
        self._clock: Callable[[], int] = clock if clock is not None else time.perf_counter_ns
        self._max_samples: int = max_samples

        self._trade_count: int = 0
        self._total_latency_ns: int = 0
        self._min_latency_ns: int = 0
        self._max_latency_ns: int = 0
        self._last_latency_ns: int = 0
        self._samples: List[int] = []

    @property
    def clock(self) -> Callable[[], int]:
        return self._clock

    @property
    def trade_count(self) -> int:
        return self._trade_count

    @property
    def total_latency_ns(self) -> int:
        return self._total_latency_ns

    @property
    def avg_latency_ns(self) -> float:
        if self._trade_count == 0:
            return 0.0
        return self._total_latency_ns / float(self._trade_count)

    @property
    def min_latency_ns(self) -> int:
        return self._min_latency_ns

    @property
    def max_latency_ns(self) -> int:
        return self._max_latency_ns

    @property
    def last_latency_ns(self) -> int:
        return self._last_latency_ns

    @property
    def avg_latency_us(self) -> float:
        return self.avg_latency_ns / 1_000.0

    @property
    def min_latency_us(self) -> float:
        return self.min_latency_ns / 1_000.0

    @property
    def max_latency_us(self) -> float:
        return self.max_latency_ns / 1_000.0

    def start_trade(self) -> int:
        """Capture entry timestamp in nanoseconds."""
        return self._clock()

    def stop_trade(self, entry_timestamp_ns: int, count: int = 1) -> int:
        """Capture exit timestamp, compute latency, record and return latency_ns."""
        exit_ns = self._clock()
        latency_ns = (
            max(0, exit_ns - entry_timestamp_ns)
            if exit_ns >= entry_timestamp_ns
            else 0
        )
        self.record_latency(latency_ns, count=count)
        return latency_ns

    def record_latency(self, latency_ns: int, count: int = 1) -> None:
        """Record an execution latency measurement in nanoseconds.

        Args:
            latency_ns: Latency in nanoseconds (guarded against negative values).
            count: Number of trades associated with this latency (default 1).
        """
        if count <= 0:
            return

        lat = max(0, int(latency_ns))
        self._trade_count += count
        self._total_latency_ns += lat * count
        self._last_latency_ns = lat

        if self._trade_count == count:
            self._min_latency_ns = lat
            self._max_latency_ns = lat
        else:
            if lat < self._min_latency_ns or self._min_latency_ns == 0:
                self._min_latency_ns = lat
            if lat > self._max_latency_ns:
                self._max_latency_ns = lat

        if len(self._samples) < self._max_samples:
            remaining = self._max_samples - len(self._samples)
            num_to_add = min(count, remaining)
            for _ in range(num_to_add):
                self._samples.append(lat)

    def record_execution(
        self, entry_timestamp_ns: int, exit_timestamp_ns: int, count: int = 1
    ) -> int:
        """Record trade execution from entry and exit timestamps in nanoseconds."""
        lat = (
            max(0, int(exit_timestamp_ns - entry_timestamp_ns))
            if exit_timestamp_ns >= entry_timestamp_ns
            else 0
        )
        self.record_latency(lat, count=count)
        return lat

    def record_trade(self, trade: Any) -> int:
        """Extract latency from a TradeResult or compatible object and record it.

        Supports:
          - TradeResult with latency_ns attribute
          - Objects with entry_timestamp_ns and exit_timestamp_ns
          - Dicts with 'latency_ns' or 'entry_timestamp_ns'/'exit_timestamp_ns'
        """
        if trade is None:
            return 0

        lat: int = 0
        if isinstance(trade, dict):
            if "latency_ns" in trade and trade["latency_ns"] is not None:
                lat = int(trade["latency_ns"])
            elif "entry_timestamp_ns" in trade and "exit_timestamp_ns" in trade:
                en = int(trade["entry_timestamp_ns"])
                ex = int(trade["exit_timestamp_ns"])
                lat = max(0, ex - en) if ex >= en else 0
        else:
            lat_attr = getattr(trade, "latency_ns", None)
            if lat_attr is not None and lat_attr > 0:
                lat = int(lat_attr)
            else:
                en = getattr(trade, "entry_timestamp_ns", 0)
                ex = getattr(trade, "exit_timestamp_ns", 0)
                if ex >= en and en > 0:
                    lat = int(ex - en)
                elif lat_attr is not None:
                    lat = max(0, int(lat_attr))

        lat = max(0, lat)
        self.record_latency(lat, count=1)
        return lat

    def record_trades(self, trades: Iterable[Any]) -> int:
        """Record all trades in an iterable and return total trades recorded."""
        c = 0
        for t in trades:
            self.record_trade(t)
            c += 1
        return c

    def measure_trade(self, count: int = 1) -> _TradeLatencyTimer:
        """Context manager for measuring trade execution duration."""
        return _TradeLatencyTimer(self, count=count)

    def measure(self, count: int = 1) -> _TradeLatencyTimer:
        """Alias for measure_trade()."""
        return self.measure_trade(count=count)

    def percentile_latency_ns(self, pct: float) -> float:
        """Compute the given percentile (e.g. 50.0, 90.0, 99.0) in nanoseconds."""
        if not self._samples:
            return 0.0
        s = sorted(self._samples)
        idx = int(len(s) * (pct / 100.0))
        return float(s[min(idx, len(s) - 1)])

    def get_snapshot(self) -> TradeLatencySnapshot:
        """Return an immutable snapshot of the current latency metrics."""
        p50 = self.percentile_latency_ns(50.0)
        p90 = self.percentile_latency_ns(90.0)
        p99 = self.percentile_latency_ns(99.0)
        return TradeLatencySnapshot(
            trade_count=self._trade_count,
            avg_latency_ns=self.avg_latency_ns,
            min_latency_ns=self._min_latency_ns,
            max_latency_ns=self._max_latency_ns,
            last_latency_ns=self._last_latency_ns,
            total_latency_ns=self._total_latency_ns,
            p50_latency_ns=p50,
            p90_latency_ns=p90,
            p99_latency_ns=p99,
        )

    def snapshot(self) -> TradeLatencySnapshot:
        """Alias for get_snapshot()."""
        return self.get_snapshot()

    def reset(self) -> None:
        """Reset all tracking metrics and sample buffers."""
        self._trade_count = 0
        self._total_latency_ns = 0
        self._min_latency_ns = 0
        self._max_latency_ns = 0
        self._last_latency_ns = 0
        self._samples.clear()
