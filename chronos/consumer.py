"""ChronosMatch Zero-Copy Consumer: Reader Process for Shared IPC Buffer.

Demonstrates consuming raw order bytes directly from the memory-mapped ring buffer
without deserialization overhead, measuring read throughput and end-to-end transit latency.
"""

from __future__ import annotations
import ctypes
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

if sys.platform == "win32":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from chronos.protocol import (
    ORDER_SIZE,
    Order,
    SYMBOL_ID_TO_TICKER,
    Side,
)
from chronos.ring_buffer import MmapRingBuffer


@dataclass
class ConsumerStats:
    total_orders_read: int = 0
    start_time: float = 0.0
    elapsed_time: float = 0.0
    current_rate: float = 0.0
    avg_rate: float = 0.0
    min_latency_us: float = float("inf")
    max_latency_us: float = 0.0
    avg_latency_us: float = 0.0
    p99_latency_us: float = 0.0


class ZeroCopyConsumer:
    """Consumes orders from the shared mmap ring buffer."""

    def __init__(
        self,
        ring_buffer: MmapRingBuffer,
        batch_size: int = 1000,
    ):
        self.ring_buffer = ring_buffer
        self.batch_size = batch_size
        self.is_running = False
        self.stats = ConsumerStats()
        self._latencies_sample: List[float] = []

    def run(
        self,
        duration_seconds: Optional[float] = None,
        total_orders: Optional[int] = None,
        print_progress: bool = True,
    ) -> ConsumerStats:
        """Poll and drain orders from the ring buffer.

        Zero-copy reads raw tuples directly from memory.
        """
        self.is_running = True
        self.stats = ConsumerStats()
        self.stats.start_time = time.perf_counter()

        last_report_time = self.stats.start_time
        last_report_orders = 0
        total_latency_us = 0.0
        latency_sample_count = 0
        max_samples = 50_000

        try:
            while self.is_running:
                # Batch read raw bytes/tuples from mmap
                batch = self.ring_buffer.read_batch_raw(self.batch_size)
                batch_count = len(batch)

                if batch_count > 0:
                    now_ns = time.time_ns()
                    self.stats.total_orders_read += batch_count

                    # Sample latencies (order timestamp_ns vs current read time)
                    for item in batch:
                        order_ts_ns = item[1]
                        lat_us = max(0.0, (now_ns - order_ts_ns) / 1_000.0)
                        total_latency_us += lat_us
                        latency_sample_count += 1

                        if lat_us < self.stats.min_latency_us:
                            self.stats.min_latency_us = lat_us
                        if lat_us > self.stats.max_latency_us:
                            self.stats.max_latency_us = lat_us

                        if len(self._latencies_sample) < max_samples:
                            self._latencies_sample.append(lat_us)
                else:
                    # Buffer currently empty: brief pause to avoid spinning CPU 100%
                    time.sleep(0.0005)

                now = time.perf_counter()
                elapsed = now - self.stats.start_time
                self.stats.elapsed_time = elapsed

                if total_orders is not None and self.stats.total_orders_read >= total_orders:
                    break
                if duration_seconds is not None and elapsed >= duration_seconds:
                    break

                # Periodic status report
                if print_progress and (now - last_report_time) >= 0.5:
                    dt = now - last_report_time
                    d_orders = self.stats.total_orders_read - last_report_orders
                    self.stats.current_rate = d_orders / dt if dt > 0 else 0
                    self.stats.avg_rate = (
                        self.stats.total_orders_read / elapsed if elapsed > 0 else 0
                    )
                    if latency_sample_count > 0:
                        self.stats.avg_latency_us = total_latency_us / latency_sample_count
                    self._print_status_line()
                    last_report_time = now
                    last_report_orders = self.stats.total_orders_read

        finally:
            self.is_running = False
            self.stats.elapsed_time = time.perf_counter() - self.stats.start_time
            if self.stats.elapsed_time > 0:
                self.stats.avg_rate = self.stats.total_orders_read / self.stats.elapsed_time
            if latency_sample_count > 0:
                self.stats.avg_latency_us = total_latency_us / latency_sample_count
            if self._latencies_sample:
                sorted_lat = sorted(self._latencies_sample)
                p99_idx = int(len(sorted_lat) * 0.99)
                self.stats.p99_latency_us = sorted_lat[min(p99_idx, len(sorted_lat) - 1)]

            if print_progress:
                sys.stdout.write("\n")
                sys.stdout.flush()

        return self.stats

    def stop(self) -> None:
        self.is_running = False

    def _print_status_line(self) -> None:
        stat = self.stats
        lag = self.ring_buffer.available_to_read()
        status = (
            f"\r\033[1;32m[Chronos Consumer]\033[0m "
            f"Read: \033[1;36m{stat.total_orders_read:,}\033[0m | "
            f"Rate: \033[1;33m{stat.current_rate:,.0f} ord/s\033[0m (avg: {stat.avg_rate:,.0f}) | "
            f"Latency: \033[1;35m{stat.avg_latency_us:,.1f} us\033[0m | "
            f"Lag: \033[1;34m{lag:,}\033[0m | "
            f"Elapsed: \033[1;37m{stat.elapsed_time:.1f}s\033[0m"
        )
        sys.stdout.write(status)
        sys.stdout.flush()
