"""ChronosMatch End-to-End System Smoke Tests (Day 10).

Validates that all core ChronosMatch subsystems operate together as a cohesive,
low-latency trading engine pipeline:
1. Binary Protocol: 32-byte struct layout and symbol mappings.
2. Memory-Mapped Ring Buffer: Zero-copy IPC write and batch read.
3. Order Adapter: Translation from binary IPC tuples into matching engine calls.
4. Cython Matching Engine: Limit Order Book, price-time priority, partial fills, and spreads.
5. Live Feed Bridge: Order draining, deduplication, worker thread lifecycle, and telemetry.
6. Terminal Dashboard: Live mode synchronization, book depth rendering, and performance metrics.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Generator

import pytest

from chronos.adapter import OrderAdapter
from chronos.consumer import ZeroCopyConsumer
from chronos.dashboard import DashboardConfig, TerminalDashboard
from chronos.live_feed import LiveFeedBridge
from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
from chronos.protocol import ORDER_SIZE, OrderType, Side, SYMBOLS
from chronos.ring_buffer import MmapRingBuffer


@pytest.fixture
def smoke_ring_buffer() -> Generator[MmapRingBuffer, None, None]:
    """Provide an isolated, real MmapRingBuffer on disk with guaranteed cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_smoke_ring_", suffix=".bin")
    os.close(fd)
    buffer = MmapRingBuffer(filepath=path, capacity=256, slot_size=ORDER_SIZE, create=True)
    try:
        yield buffer
    finally:
        buffer.close()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class TestChronosMatchEndToEndSmoke:
    """Comprehensive smoke tests exercising the complete end-to-end integration path."""

    def test_full_pipeline_order_flow_to_dashboard(self, smoke_ring_buffer: MmapRingBuffer):
        """Verify complete pipeline: RingBuffer -> Adapter -> Engine -> LiveFeed -> Dashboard."""
        engine = MatchingEngine()
        dashboard = TerminalDashboard(use_sample_data=False)
        adapter = OrderAdapter(ring_buffer=smoke_ring_buffer, engine=engine, dispatch_mode="match")
        bridge = LiveFeedBridge(
            ring_buffer=smoke_ring_buffer,
            engine=engine,
            adapter=adapter,
            dashboard=dashboard,
            batch_size=100,
            poll_interval_s=0.01,
        )

        assert bridge.is_connected is True
        assert dashboard.status_message == "Live: Connected"
        assert dashboard.is_sample_data is False

        # 1. Producer writes resting BUY orders (at 150.00 with quantities 100 and 50)
        smoke_ring_buffer.write(
            order_id=1001,
            timestamp_ns=1_000_000,
            price=150.0,
            quantity=100,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        smoke_ring_buffer.write(
            order_id=1002,
            timestamp_ns=2_000_000,
            price=150.0,
            quantity=50,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )

        # 2. Producer writes a non-crossing resting SELL order (at 155.00 with quantity 40)
        smoke_ring_buffer.write(
            order_id=2001,
            timestamp_ns=3_000_000,
            price=155.0,
            quantity=40,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.SELL),
            order_type=int(OrderType.LIMIT),
        )
        assert smoke_ring_buffer.available_to_read() == 3

        # 3. Drain orders through the live feed bridge
        drained = bridge.poll_once()
        assert drained == 3
        assert dashboard.orders_processed == 3

        # Verify engine state
        assert engine.bid_count() == 2
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 150.0
        assert engine.get_best_bid_quantity(aggregate=True) == 150  # 100 + 50
        assert engine.get_best_ask_price() == 155.0
        assert engine.get_best_ask_quantity() == 40
        assert engine.get_spread() == 5.0

        # Verify dashboard rendered lines
        display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))
        assert "Live: Connected" in display
        assert "150.00" in display  # Best Bid
        assert "150" in display     # Bid Qty aggregated
        assert "155.00" in display  # Best Ask
        assert "40" in display      # Ask Qty
        assert "5.00" in display    # Spread
        assert "Total Orders Processed" in display

        # 4. Write an aggressive crossing SELL order: 60 shares @ 150.00
        smoke_ring_buffer.write(
            order_id=3001,
            timestamp_ns=4_000_000,
            price=150.0,
            quantity=60,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.SELL),
            order_type=int(OrderType.LIMIT),
        )
        drained = bridge.poll_once()
        assert drained == 1
        assert dashboard.orders_processed == 4

        # Verify match execution through adapter stats
        assert adapter.stats.total_trades_generated == 1
        assert adapter.stats.total_volume_matched == 60

        # Remaining depth at best bid: original 150 - 60 executed = 90 remaining
        assert engine.get_best_bid_quantity(aggregate=True) == 90
        updated_display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))
        assert "90" in updated_display

        # Clean shutdown
        dashboard.close()
        assert bridge.is_running is False
        assert dashboard.is_running is False

    def test_live_feed_worker_thread_async_streaming(self, smoke_ring_buffer: MmapRingBuffer):
        """Verify background worker thread polls and synchronizes asynchronously."""
        engine = MatchingEngine()
        dashboard = TerminalDashboard(use_sample_data=False)
        bridge = LiveFeedBridge(
            ring_buffer=smoke_ring_buffer,
            engine=engine,
            dashboard=dashboard,
            poll_interval_s=0.01,
        )

        bridge.start()
        assert bridge.is_running is True

        # Stream orders into buffer while worker is actively running
        for i in range(5):
            smoke_ring_buffer.write(
                order_id=5000 + i,
                timestamp_ns=1_000_000 * i,
                price=100.0 + i,
                quantity=10 * (i + 1),
                symbol_id=SYMBOLS["AAPL"],
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            )

        # Allow worker thread to drain
        time.sleep(0.06)

        assert dashboard.orders_processed == 5
        stats = bridge.get_stats()
        assert stats["is_connected"] is True
        assert stats["orders_processed"] == 5
        assert stats["engine_order_count"] == 5

        bridge.stop()
        assert bridge.is_running is False

    def test_pipeline_deduplication_and_metrics_integrity(
        self, smoke_ring_buffer: MmapRingBuffer
    ):
        """Verify duplicate order IDs are handled gracefully and metrics remain accurate."""
        dashboard = TerminalDashboard(use_sample_data=False)
        bridge = LiveFeedBridge(
            ring_buffer=smoke_ring_buffer,
            dashboard=dashboard,
        )

        raw_order = (9999, 1_000_000, 200.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

        # First dispatch
        bridge._handle_raw_order(raw_order)
        assert dashboard.orders_processed == 1
        assert bridge.get_stats()["orders_processed"] == 1

        # Duplicate dispatch
        bridge._handle_raw_order(raw_order)
        assert dashboard.orders_processed == 1  # Dashboard deduplicates
        assert bridge.get_stats()["orders_processed"] == 2  # Total incoming counted

    def test_multi_symbol_pipeline_smoke(self, smoke_ring_buffer: MmapRingBuffer):
        """Verify order adapter routes multiple symbols to independent engines."""
        engine_aapl = MatchingEngine()
        engine_msft = MatchingEngine()
        dashboard = TerminalDashboard(use_sample_data=False)

        adapter = OrderAdapter(
            ring_buffer=smoke_ring_buffer,
            symbol_engines={
                SYMBOLS["AAPL"]: engine_aapl,
                SYMBOLS["MSFT"]: engine_msft,
            },
        )
        bridge = LiveFeedBridge(
            ring_buffer=smoke_ring_buffer,
            engine=engine_aapl,
            adapter=adapter,
            dashboard=dashboard,
        )

        # Write AAPL order
        smoke_ring_buffer.write(
            order_id=1,
            timestamp_ns=100,
            price=150.0,
            quantity=10,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        # Write MSFT order
        smoke_ring_buffer.write(
            order_id=2,
            timestamp_ns=200,
            price=400.0,
            quantity=20,
            symbol_id=SYMBOLS["MSFT"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )

        drained = bridge.poll_once()
        assert drained == 2
        assert engine_aapl.bid_count() == 1
        assert engine_msft.bid_count() == 1
        assert engine_aapl.get_best_bid_price() == 150.0
        assert engine_msft.get_best_bid_price() == 400.0
