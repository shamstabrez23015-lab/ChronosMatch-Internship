"""ChronosMatch Market Firehose: High-Throughput Asyncio Order Generator.

Generates and streams 100,000+ mock financial trade orders per second into
the zero-copy memory-mapped IPC ring buffer.

Emulates real-world market feeds (e.g. NASDAQ ITCH / NYSE Pillar) using
micro-burst streaming with microsecond-precision timestamps.
"""

from __future__ import annotations
import asyncio
import ctypes
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Enable 1ms timer resolution on Windows if available
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
    OrderType,
    Side,
    SYMBOLS,
    SYMBOL_ID_TO_TICKER,
)
from chronos.ring_buffer import MmapRingBuffer

# Realistic reference market prices for mock order generation
BASE_PRICES = {
    "AAPL": 225.50,
    "NVDA": 128.40,
    "TSLA": 240.10,
    "MSFT": 415.00,
    "AMZN": 185.30,
    "GOOGL": 165.80,
    "META": 505.20,
    "AMD": 155.60,
}

SYMBOL_IDS = list(SYMBOLS.values())
SYMBOL_WEIGHTS = [0.25, 0.25, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05]
ID_TO_BASE_PRICE = {SYMBOLS[k]: BASE_PRICES[k] for k in SYMBOLS}


@dataclass
class FirehoseStats:
    total_orders_sent: int = 0
    total_batches_sent: int = 0
    start_time: float = 0.0
    elapsed_time: float = 0.0
    current_rate: float = 0.0
    avg_rate: float = 0.0
    dropped_orders: int = 0
    buffer_lag: int = 0


class FastOrderGenerator:
    """High-speed pseudo-random order generator pre-configured for microsecond latency."""

    def __init__(self, initial_order_id: int = 1):
        self.next_order_id = initial_order_id
        # Cache random pools to bypass Python's high random overhead in the hot path
        self._price_offsets = [round((i - 50) * 0.05, 2) for i in range(101)]
        self._quantities = [10, 20, 50, 100, 200, 500, 1000]
        self._sides = [Side.BUY, Side.SELL]
        self._pool_size = 4096
        self._cursor = 0

        # Pre-generate randomized parameter tuples to achieve >1M/s generator speeds
        self._pool = []
        for _ in range(self._pool_size):
            sym_id = random.choices(SYMBOL_IDS, weights=SYMBOL_WEIGHTS)[0]
            base_px = ID_TO_BASE_PRICE[sym_id]
            offset = random.choice(self._price_offsets)
            price = max(1.0, round(base_px + offset, 2))
            qty = random.choice(self._quantities)
            side = random.choice(self._sides)
            order_type = OrderType.LIMIT if random.random() < 0.90 else OrderType.MARKET
            self._pool.append((price, qty, sym_id, int(side), int(order_type)))

    def generate_batch(
        self, batch_size: int
    ) -> List[Tuple[int, int, float, int, int, int, int]]:
        """Generate a batch of raw order tuples.

        Tuple layout: (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type)
        """
        now_ns = time.time_ns()
        orders = []
        start_id = self.next_order_id
        pool = self._pool
        pool_len = self._pool_size
        cursor = self._cursor

        for i in range(batch_size):
            price, qty, sym_id, side, order_type = pool[(cursor + i) % pool_len]
            orders.append((start_id + i, now_ns, price, qty, sym_id, side, order_type))

        self.next_order_id += batch_size
        self._cursor = (cursor + batch_size) % pool_len
        return orders


class MarketFirehose:
    """Asyncio market firehose streaming high-frequency mock trade orders into the IPC buffer."""

    def __init__(
        self,
        ring_buffer: MmapRingBuffer,
        target_rate: int = 100_000,
        batch_size: int = 500,
        overwrite_on_full: bool = True,
    ):
        """Initialize Market Firehose.

        Args:
            ring_buffer: Shared memory ring buffer.
            target_rate: Target orders per second (default: 100,000).
            batch_size: Orders per burst batch (default: 500).
            overwrite_on_full: Whether to overwrite oldest orders when the buffer saturates.
        """
        self.ring_buffer = ring_buffer
        self.target_rate = target_rate
        self.batch_size = batch_size
        self.overwrite_on_full = overwrite_on_full
        self.generator = FastOrderGenerator()
        self.is_running = False
        self.stats = FirehoseStats()

        # Batch timing
        self._batch_interval = batch_size / target_rate  # e.g. 500 / 100,000 = 0.005s (5ms)

    async def blast(
        self,
        duration_seconds: Optional[float] = None,
        total_orders: Optional[int] = None,
        print_progress: bool = True,
    ) -> FirehoseStats:
        """Start blasting mock market orders at target_rate.

        Args:
            duration_seconds: Stop after this many seconds (None for indefinite).
            total_orders: Stop after sending this many orders (None for indefinite).
            print_progress: If True, prints formatted real-time terminal stats.
        """
        self.is_running = True
        self.stats = FirehoseStats()
        self.stats.start_time = time.perf_counter()

        last_report_time = self.stats.start_time
        last_report_orders = 0

        try:
            while self.is_running:
                cycle_start = time.perf_counter()

                # Generate batch
                batch = self.generator.generate_batch(self.batch_size)

                # Zero-copy write directly to memory-mapped ring buffer
                written = self.ring_buffer.write_batch(
                    batch, overwrite_on_full=self.overwrite_on_full
                )
                self.stats.total_orders_sent += written
                self.stats.total_batches_sent += 1

                # Check stopping conditions
                now = time.perf_counter()
                elapsed = now - self.stats.start_time
                self.stats.elapsed_time = elapsed

                if total_orders is not None and self.stats.total_orders_sent >= total_orders:
                    break
                if duration_seconds is not None and elapsed >= duration_seconds:
                    break

                # Progress reporting every 500ms
                if print_progress and (now - last_report_time) >= 0.5:
                    dt = now - last_report_time
                    d_orders = self.stats.total_orders_sent - last_report_orders
                    self.stats.current_rate = d_orders / dt if dt > 0 else 0
                    self.stats.avg_rate = (
                        self.stats.total_orders_sent / elapsed if elapsed > 0 else 0
                    )
                    self.stats.buffer_lag = self.ring_buffer.available_to_read()
                    self.stats.dropped_orders = self.ring_buffer.messages_dropped

                    self._print_status_line()
                    last_report_time = now
                    last_report_orders = self.stats.total_orders_sent

                # Drift-free high-precision rate pacing
                target_time = self.stats.start_time + (self.stats.total_orders_sent / self.target_rate)
                now = time.perf_counter()
                slack = target_time - now

                if slack > 0.0025:
                    # Sleep bulk of interval, leaving 1ms buffer for spin-wait
                    await asyncio.sleep(slack - 0.001)
                    # Tight spin to hit exact target time
                    while time.perf_counter() < target_time:
                        pass
                elif slack > 0:
                    # Very short slack: spin-wait or yield
                    while time.perf_counter() < target_time:
                        pass
                else:
                    # Behind schedule: yield periodically to keep event loop responsive
                    if self.stats.total_batches_sent % 10 == 0:
                        await asyncio.sleep(0)

        finally:
            self.is_running = False
            self.stats.elapsed_time = time.perf_counter() - self.stats.start_time
            if self.stats.elapsed_time > 0:
                self.stats.avg_rate = self.stats.total_orders_sent / self.stats.elapsed_time
            if print_progress:
                sys.stdout.write("\n")
                sys.stdout.flush()

        return self.stats

    def stop(self) -> None:
        """Signal the firehose to stop blasting."""
        self.is_running = False

    def _print_status_line(self) -> None:
        """Print a compact ANSI terminal status line."""
        stat = self.stats
        lag = stat.buffer_lag
        cap = self.ring_buffer.capacity
        utilization = (lag / cap) * 100.0 if cap > 0 else 0.0

        status = (
            f"\r\033[1;36m[Chronos Firehose]\033[0m "
            f"Orders: \033[1;32m{stat.total_orders_sent:,}\033[0m | "
            f"Rate: \033[1;33m{stat.current_rate:,.0f} ord/s\033[0m (avg: {stat.avg_rate:,.0f}) | "
            f"Lag: \033[1;34m{lag:,}\033[0m ({utilization:.1f}%) | "
            f"Elapsed: \033[1;37m{stat.elapsed_time:.1f}s\033[0m"
        )
        sys.stdout.write(status)
        sys.stdout.flush()
