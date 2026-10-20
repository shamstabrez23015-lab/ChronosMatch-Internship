"""Day 8 Focused Integration Test Suite: Ring Buffer to Matching Engine Integration.

Verifies the end-to-end integration path from shared-memory ring buffer through
the ZeroCopyConsumer and OrderAdapter to the compiled Cython MatchingEngine.

Key Architectural Guarantees Verified:
1. End-to-end order path: Write -> Ring Buffer -> Zero-Copy Read -> Adapter -> Cython Engine.
2. Accurate field decoding: order_id, side, price, quantity, timestamp_ns, symbol_id.
3. Deterministic execution: Exact fills, partial fills, multi-order sweeps, maker pricing.
4. Price-Time Priority: Best price priority with deterministic FIFO tie-breaking at equal prices.
5. Multi-symbol routing: Routing orders by symbol_id to dedicated MatchingEngine instances.
6. Bounded consumer execution: total_orders, duration_seconds, exit_when_empty, and clean shutdown.
7. Duplicate processing prevention: Monotonic read_tail progression preventing re-reads.
8. Invalid input & empty-buffer handling: Graceful handling of empty buffers, non-LIMIT order types,
   unrouted symbols, and validation rejections.
9. Zero mocks: 100% real MmapRingBuffer, ZeroCopyConsumer, OrderAdapter, and compiled MatchingEngine.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Generator, List, Tuple

import pytest

from chronos.adapter import AdapterStats, OrderAdapter
from chronos.consumer import ConsumerStats, ZeroCopyConsumer
from chronos.matching_engine import (
    COrder,
    MatchingEngine,
    SIDE_BUY,
    SIDE_SELL,
    TradeResult,
    price_to_cents,
)
from chronos.protocol import (
    ORDER_SIZE,
    ORDER_STRUCT,
    Order,
    OrderType,
    Side,
    SYMBOLS,
    SYMBOL_ID_TO_TICKER,
)
from chronos.ring_buffer import MmapRingBuffer


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def temp_ring_buffer() -> Generator[MmapRingBuffer, None, None]:
    """Isolated, real MmapRingBuffer on disk with guaranteed cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_day8_ring_", suffix=".bin")
    os.close(fd)
    buffer = MmapRingBuffer(filepath=path, capacity=512, slot_size=ORDER_SIZE, create=True)
    try:
        yield buffer
    finally:
        buffer.close()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@pytest.fixture
def engine() -> Generator[MatchingEngine, None, None]:
    """Clean compiled Cython MatchingEngine instance."""
    eng = MatchingEngine()
    assert eng.is_ready() is True
    yield eng
    eng.clear()


# ==============================================================================
# 1. End-to-End Order Path & Field Preservation
# ==============================================================================

class TestEndToEndOrderPathAndFieldPreservation:
    """Verifies that orders written to the ring buffer reach the compiled engine with exact fields."""

    def test_single_order_write_read_and_engine_ingestion(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Trace a single BUY order from ring buffer write to engine book storage."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine, dispatch_mode="submit")

        order_id = 1001
        ts_ns = 1_700_000_000_123_456_789
        price = 185.50
        quantity = 250
        symbol_id = SYMBOLS["AAPL"]
        side = int(Side.BUY)
        order_type = int(OrderType.LIMIT)

        # 1. Write order to ring buffer
        written = temp_ring_buffer.write(
            order_id=order_id,
            timestamp_ns=ts_ns,
            price=price,
            quantity=quantity,
            symbol_id=symbol_id,
            side=side,
            order_type=order_type,
        )
        assert written is True
        assert temp_ring_buffer.available_to_read() == 1

        # 2. Process next from ring buffer via OrderAdapter
        raw_order, trades = adapter.process_next()
        assert raw_order is not None
        assert raw_order[0] == order_id
        assert raw_order[1] == ts_ns
        assert raw_order[2] == pytest.approx(price)
        assert raw_order[3] == quantity
        assert raw_order[4] == symbol_id
        assert raw_order[5] == side
        assert raw_order[6] == order_type
        assert len(trades) == 0

        # 3. Verify engine state
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        best_bid = engine.get_best_buy_order()
        assert best_bid is not None
        assert best_bid.order_id == order_id
        assert best_bid.price_cents == 18550
        assert best_bid.quantity == quantity
        assert best_bid.remaining_quantity == quantity
        assert best_bid.timestamp_ns == ts_ns

        # 4. Verify ring buffer is now empty
        assert temp_ring_buffer.is_empty() is True
        assert temp_ring_buffer.available_to_read() == 0

    def test_consumer_order_handler_direct_connection(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Verify ZeroCopyConsumer directly invoking OrderAdapter.dispatch_raw_order."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine, dispatch_mode="match")
        consumer = ZeroCopyConsumer(
            ring_buffer=temp_ring_buffer,
            batch_size=10,
            order_handler=adapter.dispatch_raw_order,
        )

        # Write resting SELL
        temp_ring_buffer.write_order(
            Order(1, 1000, 100.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        )
        # Write crossing BUY
        temp_ring_buffer.write_order(
            Order(2, 2000, 100.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        )

        stats = consumer.run(total_orders=2, print_progress=False)
        assert stats.total_orders_read == 2
        assert len(adapter.trades) == 1
        trade = adapter.trades[0]
        assert trade.buy_order_id == 2
        assert trade.sell_order_id == 1
        assert trade.executed_quantity == 50
        assert trade.execution_price_cents == 10000

        # Order book clean
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_consumer_with_engine_auto_initialization(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Verify ZeroCopyConsumer initialized directly with an engine."""
        consumer = ZeroCopyConsumer(
            ring_buffer=temp_ring_buffer,
            batch_size=10,
            engine=engine,
        )
        assert consumer.adapter is not None
        assert consumer.order_handler is not None

        temp_ring_buffer.write_order(
            Order(10, 1000, 50.0, 100, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT))
        )
        temp_ring_buffer.write_order(
            Order(11, 2000, 50.0, 100, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT))
        )

        consumer.run(total_orders=2, print_progress=False)
        assert len(consumer.adapter.trades) == 1
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0


# ==============================================================================
# 2. Deterministic Matching, Fills, and Maker Pricing
# ==============================================================================

class TestDeterministicMatchingAndExecution:
    """Verifies deterministic fills, maker pricing policy, and residual book states."""

    def test_exact_fill_clears_both_sides(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Exact match: BUY 100 @ 250.00 matches SELL 100 @ 250.00; leaves book empty."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            (1, 1000, 250.00, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (2, 2000, 250.00, 100, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 2
        assert t.sell_order_id == 1
        assert t.executed_quantity == 100
        assert t.execution_price_cents == 25000
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 0

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None

    def test_partial_fill_buy_larger_rests_residual_in_bids(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Incoming BUY 100 @ 150.00 vs resting SELL 40 @ 150.00 -> fill 40, BUY 60 rests."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            (10, 1000, 150.00, 40, SYMBOLS["NVDA"], int(Side.SELL), int(OrderType.LIMIT)),
            (20, 2000, 150.00, 100, SYMBOLS["NVDA"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 20
        assert t.sell_order_id == 10
        assert t.executed_quantity == 40
        assert t.execution_price_cents == 15000
        assert t.buy_remaining_quantity == 60
        assert t.sell_remaining_quantity == 0

        # Resting book state
        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        best_bid = engine.get_best_buy_order()
        assert best_bid.order_id == 20
        assert best_bid.remaining_quantity == 60
        assert best_bid.quantity == 100  # Original submitted quantity preserved

    def test_partial_fill_sell_larger_rests_residual_in_asks(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Incoming SELL 100 @ 120.00 vs resting BUY 35 @ 120.00 -> fill 35, SELL 65 rests."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            (101, 1000, 120.00, 35, SYMBOLS["AMD"], int(Side.BUY), int(OrderType.LIMIT)),
            (102, 2000, 120.00, 100, SYMBOLS["AMD"], int(Side.SELL), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 101
        assert t.sell_order_id == 102
        assert t.executed_quantity == 35
        assert t.execution_price_cents == 12000
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 65

        # Resting book state
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        best_ask = engine.get_best_sell_order()
        assert best_ask.order_id == 102
        assert best_ask.remaining_quantity == 65
        assert best_ask.quantity == 100

    def test_multi_order_sweep_buy_sweeps_multiple_sells_maker_price(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Aggressive BUY sweeps 3 resting SELLs at ascending price levels."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            # Resting SELL 1: 30 @ $100.00
            (1, 1000, 100.00, 30, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # Resting SELL 2: 40 @ $101.00
            (2, 2000, 101.00, 40, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # Resting SELL 3: 50 @ $102.00
            (3, 3000, 102.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # Incoming BUY: 90 @ $102.00 (crosses all three, partially fills #3)
            (4, 4000, 102.00, 90, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 3

        # Fill 1: against SELL #1 @ maker price 100.00
        assert trades[0].buy_order_id == 4
        assert trades[0].sell_order_id == 1
        assert trades[0].executed_quantity == 30
        assert trades[0].execution_price_cents == 10000
        assert trades[0].buy_remaining_quantity == 60
        assert trades[0].sell_remaining_quantity == 0

        # Fill 2: against SELL #2 @ maker price 101.00
        assert trades[1].buy_order_id == 4
        assert trades[1].sell_order_id == 2
        assert trades[1].executed_quantity == 40
        assert trades[1].execution_price_cents == 10100
        assert trades[1].buy_remaining_quantity == 20
        assert trades[1].sell_remaining_quantity == 0

        # Fill 3: against SELL #3 @ maker price 102.00
        assert trades[2].buy_order_id == 4
        assert trades[2].sell_order_id == 3
        assert trades[2].executed_quantity == 20
        assert trades[2].execution_price_cents == 10200
        assert trades[2].buy_remaining_quantity == 0
        assert trades[2].sell_remaining_quantity == 30

        # Final book state:
        # BUY #4 fully filled; SELL #1, #2 fully filled.
        # SELL #3 remains with 30 @ $102.00
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        best_ask = engine.get_best_sell_order()
        assert best_ask.order_id == 3
        assert best_ask.remaining_quantity == 30
        assert best_ask.price_cents == 10200

    def test_multi_order_sweep_sell_sweeps_multiple_buys_maker_price(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Aggressive SELL sweeps 3 resting BUYs at descending price levels."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            # Resting BUY 1: 25 @ $105.00
            (10, 1000, 105.00, 25, SYMBOLS["TSLA"], int(Side.BUY), int(OrderType.LIMIT)),
            # Resting BUY 2: 35 @ $104.00
            (11, 2000, 104.00, 35, SYMBOLS["TSLA"], int(Side.BUY), int(OrderType.LIMIT)),
            # Resting BUY 3: 50 @ $103.00
            (12, 3000, 103.00, 50, SYMBOLS["TSLA"], int(Side.BUY), int(OrderType.LIMIT)),
            # Incoming SELL: 80 @ $103.00
            (13, 4000, 103.00, 80, SYMBOLS["TSLA"], int(Side.SELL), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 3

        # Fill 1: against highest bid BUY #10 @ maker price 105.00
        assert trades[0].buy_order_id == 10
        assert trades[0].sell_order_id == 13
        assert trades[0].executed_quantity == 25
        assert trades[0].execution_price_cents == 10500
        assert trades[0].sell_remaining_quantity == 55

        # Fill 2: against next bid BUY #11 @ maker price 104.00
        assert trades[1].buy_order_id == 11
        assert trades[1].sell_order_id == 13
        assert trades[1].executed_quantity == 35
        assert trades[1].execution_price_cents == 10400
        assert trades[1].sell_remaining_quantity == 20

        # Fill 3: against BUY #12 @ maker price 103.00
        assert trades[2].buy_order_id == 12
        assert trades[2].sell_order_id == 13
        assert trades[2].executed_quantity == 20
        assert trades[2].execution_price_cents == 10300
        assert trades[2].sell_remaining_quantity == 0
        assert trades[2].buy_remaining_quantity == 30

        # Remaining in book: BUY #12 with 30 @ 103.00
        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        best_bid = engine.get_best_buy_order()
        assert best_bid.order_id == 12
        assert best_bid.remaining_quantity == 30


# ==============================================================================
# 3. Price-Time Priority (FIFO) Across Pipeline
# ==============================================================================

class TestPriceTimePriorityAcrossPipeline:
    """Verifies strict Price-Time priority (price primary, FIFO secondary tie-break)."""

    def test_fifo_ordering_at_identical_prices(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """At equal prices, earlier resting order is matched first."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            # First resting SELL: 50 @ $200.00
            (1, 1000, 200.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # Second resting SELL at SAME price: 50 @ $200.00
            (2, 2000, 200.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # Crossing BUY: 50 @ $200.00 -> MUST match #1 first due to FIFO
            (3, 3000, 200.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 1
        # Matched order 1, not order 2
        assert trades[0].sell_order_id == 1
        assert trades[0].buy_order_id == 3

        # Order 2 still resting in asks
        assert engine.ask_count() == 1
        assert engine.get_best_sell_order().order_id == 2

    def test_partially_filled_order_retains_priority_over_newer_orders(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """A partially filled order must keep its priority over newer orders arriving later."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)

        # Batch 1: Order #1 (100 @ 50.00) and crossing BUY #2 (40 @ 50.00)
        temp_ring_buffer.write_batch([
            (1, 1000, 50.00, 100, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)),
            (2, 2000, 50.00, 40, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
        ])
        t1 = adapter.drain_all()
        assert len(t1) == 1
        assert engine.get_best_sell_order().remaining_quantity == 60

        # Batch 2: Order #3 arrives later at the same price (50 @ 50.00),
        # then BUY #4 arrives (30 @ 50.00). Must match #1 again!
        temp_ring_buffer.write_batch([
            (3, 3000, 50.00, 50, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)),
            (4, 4000, 50.00, 30, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
        ])
        t2 = adapter.drain_all()
        assert len(t2) == 1
        # Order #1 still matched first!
        assert t2[0].sell_order_id == 1
        assert t2[0].buy_order_id == 4
        assert t2[0].sell_remaining_quantity == 30

        # Book has order #1 (rem 30) and order #3 (rem 50)
        assert engine.ask_count() == 2
        prioritized = engine.get_prioritized_asks()
        assert prioritized[0].order_id == 1
        assert prioritized[1].order_id == 3


# ==============================================================================
# 4. Multi-Symbol Pipeline Routing
# ==============================================================================

class TestMultiSymbolPipelineRouting:
    """Verifies that an interleaved multi-symbol stream routes to isolated engines."""

    def test_interleaved_multi_symbol_stream_isolated_matching(
        self, temp_ring_buffer: MmapRingBuffer
    ):
        """Interleave AAPL and NVDA orders; verify isolation and independent matching."""
        engine_aapl = MatchingEngine()
        engine_nvda = MatchingEngine()

        adapter = OrderAdapter(
            ring_buffer=temp_ring_buffer,
            symbol_engines={
                SYMBOLS["AAPL"]: engine_aapl,
                SYMBOLS["NVDA"]: engine_nvda,
            },
        )

        orders = [
            # AAPL: SELL 100 @ 180.00
            (1, 1000, 180.00, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # NVDA: SELL 200 @ 120.00
            (2, 2000, 120.00, 200, SYMBOLS["NVDA"], int(Side.SELL), int(OrderType.LIMIT)),
            # AAPL: BUY 100 @ 180.00 (crosses AAPL)
            (3, 3000, 180.00, 100, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            # NVDA: BUY 50 @ 120.00 (crosses NVDA partially)
            (4, 4000, 120.00, 50, SYMBOLS["NVDA"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        consumer = ZeroCopyConsumer(
            ring_buffer=temp_ring_buffer,
            batch_size=4,
            order_handler=adapter.dispatch_raw_order,
        )
        c_stats = consumer.run(total_orders=4, print_progress=False)
        assert c_stats.total_orders_read == 4

        # AAPL: 1 trade, books cleared
        assert engine_aapl.bid_count() == 0
        assert engine_aapl.ask_count() == 0

        # NVDA: 1 trade, 150 shares remaining in asks
        assert engine_nvda.bid_count() == 0
        assert engine_nvda.ask_count() == 1
        assert engine_nvda.get_best_sell_order().remaining_quantity == 150

        # Verify adapter recorded 2 trades total
        assert len(adapter.trades) == 2
        assert adapter.trades[0].buy_order_id == 3
        assert adapter.trades[0].sell_order_id == 1
        assert adapter.trades[1].buy_order_id == 4
        assert adapter.trades[1].sell_order_id == 2


# ==============================================================================
# 5. Bounded Consumer Execution & Resource Cleanup
# ==============================================================================

class TestBoundedConsumerAndCleanup:
    """Verifies bounded execution limits, exit_when_empty, and clean resource release."""

    def test_consumer_bounded_by_total_orders(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Consumer stops promptly when total_orders reached, even if more orders exist."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            (i, 1000 + i, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
            for i in range(1, 11)
        ]
        temp_ring_buffer.write_batch(orders)

        consumer = ZeroCopyConsumer(
            ring_buffer=temp_ring_buffer,
            batch_size=2,
            order_handler=adapter.dispatch_raw_order,
        )
        stats = consumer.run(total_orders=5, print_progress=False)

        assert stats.total_orders_read == 5
        assert temp_ring_buffer.available_to_read() == 5  # 5 unread remain in buffer
        assert engine.bid_count() == 5

    def test_consumer_bounded_by_duration_seconds(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Consumer terminates cleanly when duration_seconds expires."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        consumer = ZeroCopyConsumer(
            ring_buffer=temp_ring_buffer,
            batch_size=10,
            order_handler=adapter.dispatch_raw_order,
        )

        t0 = time.perf_counter()
        stats = consumer.run(duration_seconds=0.05, print_progress=False)
        t1 = time.perf_counter()

        assert (t1 - t0) >= 0.04
        assert stats.total_orders_read == 0
        assert consumer.is_running is False

    def test_consumer_exit_when_empty(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Consumer with exit_when_empty=True drains all orders and returns immediately without spinning."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        orders = [
            (1, 1000, 10.0, 5, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
            (2, 2000, 10.0, 5, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
            (3, 3000, 10.0, 5, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        consumer = ZeroCopyConsumer(
            ring_buffer=temp_ring_buffer,
            batch_size=2,
            order_handler=adapter.dispatch_raw_order,
        )
        t0 = time.perf_counter()
        stats = consumer.run(exit_when_empty=True, print_progress=False)
        t1 = time.perf_counter()

        assert stats.total_orders_read == 3
        assert (t1 - t0) < 0.2  # Prompt return
        assert temp_ring_buffer.is_empty() is True

    def test_consumer_context_manager_and_drain_available(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Verify context manager usage and drain_available helper."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        temp_ring_buffer.write_order(
            Order(55, 1000, 99.0, 10, SYMBOLS["AMZN"], int(Side.BUY), int(OrderType.LIMIT))
        )

        with ZeroCopyConsumer(temp_ring_buffer, order_handler=adapter.dispatch_raw_order) as consumer:
            read_count = consumer.drain_available()
            assert read_count == 1
            assert engine.bid_count() == 1

        assert consumer.is_running is False


# ==============================================================================
# 6. Duplicate Processing Prevention & Monotonic Reading
# ==============================================================================

class TestDuplicateProcessingPrevention:
    """Verifies that reading from the ring buffer advances read_tail monotonically without duplicates."""

    def test_no_duplicate_orders_on_repeated_reads(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Ensure orders cannot be read twice or re-dispatched to the engine."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        temp_ring_buffer.write_order(
            Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        )

        # First read
        raw1, trades1 = adapter.process_next()
        assert raw1 is not None
        assert adapter.stats.total_orders_read == 1
        assert engine.bid_count() == 1

        # Second read from empty buffer
        raw2, trades2 = adapter.process_next()
        assert raw2 is None
        assert trades2 == []
        assert adapter.stats.total_orders_read == 1  # Not incremented
        assert engine.bid_count() == 1  # No duplicate order in book

    def test_repeated_drain_returns_empty_and_no_duplicate_trades(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Repeatedly calling drain_all does not re-process past orders."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        temp_ring_buffer.write_batch([
            (1, 1000, 50.0, 10, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (2, 2000, 50.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ])

        trades1 = adapter.drain_all()
        assert len(trades1) == 1
        assert adapter.stats.total_orders_read == 2
        assert adapter.stats.total_trades_generated == 1

        trades2 = adapter.drain_all()
        assert len(trades2) == 0
        assert adapter.stats.total_orders_read == 2
        assert adapter.stats.total_trades_generated == 1


# ==============================================================================
# 7. Invalid Inputs & Empty-Buffer Boundary Handling
# ==============================================================================

class TestInvalidInputsAndBoundaryHandling:
    """Verifies truthful error handling and recording for unsupported types and invalid inputs."""

    def test_empty_buffer_process_available_returns_empty_list(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """Calling process_available on an empty buffer safely returns empty list."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        trades = adapter.process_available()
        assert trades == []
        assert adapter.stats.total_orders_read == 0

    def test_unsupported_order_type_market_recorded_truthfully(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """MARKET orders are recorded in unhandled_orders without crashing."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        temp_ring_buffer.write_order(
            Order(88, 1000, 0.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.MARKET))
        )

        trades = adapter.drain_all()
        assert trades == []
        assert adapter.stats.unhandled_order_types == 1
        assert len(adapter.unhandled_orders) == 1
        assert engine.bid_count() == 0

    def test_unsupported_order_type_cancel_recorded_truthfully(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        """CANCEL orders are recorded in unhandled_orders without crashing."""
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)
        temp_ring_buffer.write_order(
            Order(89, 1000, 150.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.CANCEL))
        )

        trades = adapter.drain_all()
        assert trades == []
        assert adapter.stats.unhandled_order_types == 1
        assert len(adapter.unhandled_orders) == 1

    def test_unrouted_symbol_recorded_truthfully(
        self, temp_ring_buffer: MmapRingBuffer
    ):
        """Orders for unrouted symbol are recorded in unrouted_orders."""
        # Adapter with no default engine and only AAPL configured
        adapter = OrderAdapter(
            ring_buffer=temp_ring_buffer,
            symbol_engines={SYMBOLS["AAPL"]: MatchingEngine()},
        )
        temp_ring_buffer.write_order(
            Order(90, 1000, 100.0, 10, SYMBOLS["NVDA"], int(Side.BUY), int(OrderType.LIMIT))
        )

        trades = adapter.drain_all()
        assert trades == []
        assert adapter.stats.unrouted_symbols == 1
        assert len(adapter.unrouted_orders) == 1

    def test_engine_rejects_negative_price_and_zero_quantity(
        self, engine: MatchingEngine
    ):
        """Cython engine raises ValueError on zero quantity or negative price."""
        adapter = OrderAdapter(engine=engine)

        with pytest.raises(ValueError, match="Invalid price"):
            adapter.dispatch_raw_order(
                Order(1, 1000, -10.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
            )

        with pytest.raises(ValueError, match="Invalid quantity"):
            adapter.dispatch_raw_order(
                Order(2, 1000, 100.0, 0, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
            )

        with pytest.raises(ValueError, match="Invalid side"):
            adapter.dispatch_raw_order(
                (3, 1000, 100.0, 10, SYMBOLS["AAPL"], 99, int(OrderType.LIMIT))
            )

        # Book remains clean
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
