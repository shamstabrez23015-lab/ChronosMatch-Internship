"""ChronosMatch Live Feed Integration: Bridge between Ring Buffer, Engine, and Dashboard.

Connects the zero-copy shared memory ring buffer, Cython matching engine,
order adapter, and curses terminal dashboard into a synchronized real-time pipeline.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from chronos.matching_engine import MatchingEngine
from chronos.ring_buffer import MmapRingBuffer
from chronos.adapter import OrderAdapter
from chronos.consumer import ZeroCopyConsumer
from chronos.dashboard import TerminalDashboard, _extract_order_id


class LiveFeedBridge:
    """Bridge connecting MmapRingBuffer, MatchingEngine, OrderAdapter, and TerminalDashboard."""

    def __init__(
        self,
        engine: Optional[MatchingEngine] = None,
        ring_buffer: Optional[MmapRingBuffer] = None,
        adapter: Optional[OrderAdapter] = None,
        dashboard: Optional[TerminalDashboard] = None,
        consumer: Optional[ZeroCopyConsumer] = None,
        batch_size: int = 1000,
        poll_interval_s: float = 0.05,
        clock: Optional[Callable[[], float]] = None,
        ns_clock: Optional[Callable[[], int]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the LiveFeedBridge.

        Args:
            engine: Cython MatchingEngine instance (creates new if None).
            ring_buffer: Memory-mapped IPC ring buffer to drain orders from.
            adapter: OrderAdapter instance (creates new if None).
            dashboard: TerminalDashboard to update with live metrics.
            consumer: Optional ZeroCopyConsumer for high-throughput streaming.
            batch_size: Max orders to drain per poll iteration.
            poll_interval_s: Sleep interval between background polls in seconds.
            clock: Monotonic clock callable (seconds).
            ns_clock: Nanosecond clock callable.
        """
        self.engine: MatchingEngine = engine if engine is not None else MatchingEngine()
        self.ring_buffer: Optional[MmapRingBuffer] = ring_buffer

        if adapter is not None:
            self.adapter = adapter
        else:
            self.adapter = OrderAdapter(ring_buffer=self.ring_buffer, engine=self.engine)

        self.dashboard: Optional[TerminalDashboard] = dashboard
        if self.dashboard is not None and getattr(self.dashboard, "live_feed", None) is None:
            self.dashboard.live_feed = self

        self.consumer: Optional[ZeroCopyConsumer] = consumer
        self.batch_size: int = int(batch_size)
        self.poll_interval_s: float = float(poll_interval_s)
        self.clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self.ns_clock: Callable[[], int] = ns_clock if ns_clock is not None else time.perf_counter_ns

        self.is_running: bool = False
        self._is_connected: Optional[bool] = None
        self._orders_processed: int = 0
        self._seen_order_ids: Set[Any] = set()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()

    @property
    def is_connected(self) -> bool:
        """Return connection status to ring buffer or upstream source."""
        if self._is_connected is False:
            return False
        if self.ring_buffer is not None:
            if getattr(self.ring_buffer, "_is_closed", False):
                return False
        if self._is_connected is not None:
            return self._is_connected
        return True

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        """Override connection status."""
        self._is_connected = bool(value)

    def _handle_raw_order(self, raw_order: Any) -> None:
        """Handle a single raw order notification.

        Args:
            raw_order: 7-tuple or Order instance representing an incoming order.
        """
        self._orders_processed += 1
        order_id = _extract_order_id(raw_order)
        is_duplicate = False
        if order_id is not None:
            if order_id in self._seen_order_ids:
                is_duplicate = True
            else:
                self._seen_order_ids.add(order_id)

        if not is_duplicate:
            if self.adapter is not None:
                try:
                    self.adapter.stats.total_orders_read += 1
                    self.adapter.dispatch_raw_order(raw_order)
                except Exception:
                    pass
            elif self.engine is not None:
                pass

        if self.dashboard is not None:
            self.dashboard.record_order_processed(raw_order)

    def sync_to_dashboard(self) -> None:
        """Synchronize engine order book state into the dashboard."""
        if self.dashboard is None:
            return

        if self.engine is not None:
            bids = self.engine.get_prioritized_bids()
            asks = self.engine.get_prioritized_asks()
        else:
            bids = []
            asks = []

        self.dashboard.set_buy_orders(bids, is_sample=False)
        self.dashboard.set_sell_orders(asks, is_sample=False)
        self.dashboard.is_sample_data = False

    def poll_once(self) -> int:
        """Drain and process currently available orders from ring buffer.

        Returns:
            Count of orders drained and dispatched in this poll operation.
        """
        drained = 0
        if self.ring_buffer is not None and self.is_connected:
            try:
                avail = self.ring_buffer.available_to_read()
                if avail > 0:
                    limit = min(avail, self.batch_size) if self.batch_size else avail
                    batch = self.ring_buffer.read_batch_raw(limit)
                    drained = len(batch)
                    for raw in batch:
                        self._handle_raw_order(raw)
            except Exception:
                pass

        self.sync_to_dashboard()
        return drained

    def get_stats(self) -> Dict[str, Any]:
        """Return operational and performance statistics."""
        eng_order_cnt = self.engine.order_count() if self.engine is not None else 0
        eng_bid_cnt = self.engine.bid_count() if self.engine is not None else 0
        eng_ask_cnt = self.engine.ask_count() if self.engine is not None else 0

        return {
            "is_connected": self.is_connected,
            "is_running": self.is_running,
            "orders_processed": self._orders_processed,
            "unique_orders_seen": len(self._seen_order_ids),
            "engine_order_count": eng_order_cnt,
            "engine_bid_count": eng_bid_cnt,
            "engine_ask_count": eng_ask_cnt,
            "batch_size": self.batch_size,
            "poll_interval_s": self.poll_interval_s,
        }

    def start(self) -> None:
        """Start background polling worker thread (idempotent)."""
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="ChronosLiveFeedWorker", daemon=True
        )
        self._worker_thread.start()

    def stop(self) -> None:
        """Stop background polling worker thread."""
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self._worker_thread = None

    def _worker_loop(self) -> None:
        """Worker loop running in a background thread."""
        while self.is_running and not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                pass
            self._stop_event.wait(timeout=self.poll_interval_s)

    def close(self) -> None:
        """Stop worker thread and clean up resources."""
        self.stop()

    def __enter__(self) -> LiveFeedBridge:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
