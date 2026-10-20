"""Focused Unit and Integration Tests for chronos.adapter (OrderAdapter & AdapterStats).

Tests:
1. AdapterStats initialization, metric tracking, and reset behavior.
2. OrderAdapter configuration, symbol engine routing, and dispatch modes.
3. Raw tuple and Order NamedTuple dispatching into compiled MatchingEngine.
4. TradeResult execution details (maker price, fill quantity, remaining quantity).
5. Unhandled order types (CANCEL, MARKET) and unrouted symbol tracking.
6. Buffer operations: process_next, process_available, drain_all with MmapRingBuffer.
7. ZeroCopyConsumer integration via run_consumer.
8. State clearance and resource lifecycle.
"""

from __future__ import annotations

import os
import tempfile
from typing import Generator

import pytest

from chronos.adapter import AdapterStats, OrderAdapter
from chronos.consumer import ZeroCopyConsumer
from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL, price_to_cents
from chronos.protocol import (
    ORDER_SIZE,
    Order,
    OrderType,
    Side,
    SYMBOLS,
)
from chronos.ring_buffer import MmapRingBuffer


@pytest.fixture
def temp_ring_buffer() -> Generator[MmapRingBuffer, None, None]:
    """Isolated MmapRingBuffer fixture with guaranteed cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_adapter_test_", suffix=".bin")
    os.close(fd)
    buf = MmapRingBuffer(filepath=path, capacity=256, slot_size=ORDER_SIZE, create=True)
    try:
        yield buf
    finally:
        buf.close()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@pytest.fixture
def engine() -> Generator[MatchingEngine, None, None]:
    """Clean MatchingEngine instance."""
    eng = MatchingEngine()
    assert eng.is_ready() is True
    yield eng
    eng.clear()


class TestAdapterStats:
    """Verifies operational statistics counters and reset logic."""

    def test_default_stats_values(self):
        stats = AdapterStats()
        assert stats.total_orders_read == 0
        assert stats.total_orders_dispatched == 0
        assert stats.total_trades_generated == 0
        assert stats.total_volume_matched == 0
        assert stats.non_crossing_orders == 0
        assert stats.unhandled_order_types == 0
        assert stats.unrouted_symbols == 0

    def test_reset_clears_all_counters(self):
        stats = AdapterStats(
            total_orders_read=10,
            total_orders_dispatched=10,
            total_trades_generated=5,
            total_volume_matched=500,
            non_crossing_orders=5,
            unhandled_order_types=2,
            unrouted_symbols=1,
        )
        stats.reset()
        assert stats.total_orders_read == 0
        assert stats.total_orders_dispatched == 0
        assert stats.total_trades_generated == 0
        assert stats.total_volume_matched == 0
        assert stats.non_crossing_orders == 0
        assert stats.unhandled_order_types == 0
        assert stats.unrouted_symbols == 0


class TestOrderAdapterConfiguration:
    """Verifies adapter constructor, mode handling, and symbol routing."""

    def test_invalid_dispatch_mode_raises(self, engine: MatchingEngine):
        with pytest.raises(ValueError, match="Invalid dispatch_mode"):
            OrderAdapter(engine=engine, dispatch_mode="invalid_mode")

    def test_resolve_engine_single_default(self, engine: MatchingEngine):
        adapter = OrderAdapter(engine=engine, default_symbol_id=SYMBOLS["AAPL"])
        assert adapter.resolve_engine(SYMBOLS["AAPL"]) is engine
        assert adapter.resolve_engine(SYMBOLS["MSFT"]) is engine  # falls back to default

    def test_resolve_engine_multi_symbol(self):
        eng_aapl = MatchingEngine()
        eng_msft = MatchingEngine()
        adapter = OrderAdapter(
            symbol_engines={
                SYMBOLS["AAPL"]: eng_aapl,
                SYMBOLS["MSFT"]: eng_msft,
            }
        )
        assert adapter.resolve_engine(SYMBOLS["AAPL"]) is eng_aapl
        assert adapter.resolve_engine(SYMBOLS["MSFT"]) is eng_msft
        assert adapter.resolve_engine(SYMBOLS["NVDA"]) is None

    def test_clear_resets_adapter_state(self, engine: MatchingEngine):
        adapter = OrderAdapter(engine=engine)
        order = Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(order)
        assert adapter.stats.total_orders_dispatched == 1

        adapter.clear()
        assert adapter.stats.total_orders_dispatched == 0
        assert len(adapter.trades) == 0
        assert len(adapter.unhandled_orders) == 0
        assert len(adapter.unrouted_orders) == 0


class TestOrderAdapterDispatch:
    """Verifies order dispatching, matching execution, and remaining quantities."""

    def test_dispatch_order_namedtuple_and_raw_tuple(self, engine: MatchingEngine):
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        # 1. Dispatch resting SELL as Order NamedTuple
        sell_order = Order(
            order_id=1,
            timestamp_ns=1000,
            price=150.00,
            quantity=100,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.SELL),
            order_type=int(OrderType.LIMIT),
        )
        trades1 = adapter.dispatch_raw_order(sell_order)
        assert len(trades1) == 0
        assert engine.ask_count() == 1
        assert adapter.stats.total_orders_dispatched == 1
        assert adapter.stats.non_crossing_orders == 1

        # 2. Dispatch crossing BUY as raw tuple: (order_id, ts, price, qty, sym, side, type)
        buy_raw = (2, 2000, 150.00, 40, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades2 = adapter.dispatch_raw_order(buy_raw)
        assert len(trades2) == 1
        trade = trades2[0]

        # Verify trade execution details
        assert trade.buy_order_id == 2
        assert trade.sell_order_id == 1
        assert trade.executed_quantity == 40
        assert trade.execution_price_cents == 15000
        assert trade.execution_price == 150.00
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 60

        # Verify remaining quantity in engine
        assert engine.ask_count() == 1
        assert engine.get_best_sell_order().remaining_quantity == 60
        assert engine.bid_count() == 0

        assert adapter.stats.total_orders_dispatched == 2
        assert adapter.stats.total_trades_generated == 1
        assert adapter.stats.total_volume_matched == 40
        assert adapter.stats.non_crossing_orders == 1

    def test_dispatch_submit_mode(self, engine: MatchingEngine):
        """In submit mode, crossing orders are passively stored without executing fills."""
        adapter = OrderAdapter(engine=engine, dispatch_mode="submit")

        sell = Order(1, 1000, 100.0, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        buy = Order(2, 2000, 105.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

        adapter.dispatch_raw_order(sell)
        adapter.dispatch_raw_order(buy)

        assert len(adapter.trades) == 0
        assert engine.ask_count() == 1
        assert engine.bid_count() == 1
        assert adapter.stats.total_trades_generated == 0
        assert adapter.stats.non_crossing_orders == 2

    def test_unhandled_order_types_recorded_truthfully(self, engine: MatchingEngine):
        adapter = OrderAdapter(engine=engine)

        cancel_order = Order(
            order_id=99,
            timestamp_ns=1000,
            price=100.0,
            quantity=10,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.CANCEL),
        )
        trades = adapter.dispatch_raw_order(cancel_order)
        assert len(trades) == 0
        assert adapter.stats.unhandled_order_types == 1
        assert len(adapter.unhandled_orders) == 1
        assert engine.bid_count() == 0

        market_order = Order(
            order_id=100,
            timestamp_ns=2000,
            price=0.0,
            quantity=10,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.MARKET),
        )
        trades_m = adapter.dispatch_raw_order(market_order)
        assert len(trades_m) == 0
        assert adapter.stats.unhandled_order_types == 2
        assert len(adapter.unhandled_orders) == 2

    def test_unrouted_symbol_recorded_truthfully(self):
        # Adapter with no default engine and only AAPL configured
        adapter = OrderAdapter(symbol_engines={SYMBOLS["AAPL"]: MatchingEngine()})

        nvda_order = Order(
            order_id=201,
            timestamp_ns=1000,
            price=50.0,
            quantity=10,
            symbol_id=SYMBOLS["NVDA"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        trades = adapter.dispatch_raw_order(nvda_order)
        assert len(trades) == 0
        assert adapter.stats.unrouted_symbols == 1
        assert len(adapter.unrouted_orders) == 1


class TestOrderAdapterBufferOperations:
    """Verifies reading and draining orders from MmapRingBuffer."""

    def test_process_next_and_process_available(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)

        # Buffer is empty initially
        raw, trades = adapter.process_next()
        assert raw is None
        assert trades == []

        # Write 2 orders
        o1 = Order(1, 1000, 200.0, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        o2 = Order(2, 2000, 200.0, 20, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        temp_ring_buffer.write_order(o1)
        temp_ring_buffer.write_order(o2)

        # Process first
        raw1, trades1 = adapter.process_next()
        assert raw1[0] == 1
        assert len(trades1) == 0
        assert adapter.stats.total_orders_read == 1

        # Process available (second order)
        trades2 = adapter.process_available(max_orders=10)
        assert len(trades2) == 1
        assert trades2[0].buy_order_id == 2
        assert trades2[0].sell_order_id == 1
        assert trades2[0].executed_quantity == 20
        assert adapter.stats.total_orders_read == 2

    def test_drain_all(self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine):
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)

        orders = [
            (10, 1000, 10.0, 100, SYMBOLS["TSLA"], int(Side.SELL), int(OrderType.LIMIT)),
            (11, 2000, 10.0, 60, SYMBOLS["TSLA"], int(Side.BUY), int(OrderType.LIMIT)),
            (12, 3000, 10.0, 40, SYMBOLS["TSLA"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        trades = adapter.drain_all()
        assert len(trades) == 2
        assert trades[0].executed_quantity == 60
        assert trades[1].executed_quantity == 40
        assert engine.ask_count() == 0  # Fully swept
        assert engine.bid_count() == 0

    def test_missing_ring_buffer_raises_on_buffer_methods(self, engine: MatchingEngine):
        adapter = OrderAdapter(engine=engine)
        with pytest.raises(ValueError, match="no ring_buffer provided"):
            adapter.process_next()
        with pytest.raises(ValueError, match="no ring_buffer provided"):
            adapter.process_available()


class TestOrderAdapterConsumerIntegration:
    """Verifies run_consumer method coordinating ZeroCopyConsumer and OrderAdapter."""

    def test_run_consumer_bounded_execution(
        self, temp_ring_buffer: MmapRingBuffer, engine: MatchingEngine
    ):
        adapter = OrderAdapter(ring_buffer=temp_ring_buffer, engine=engine)

        orders = [
            (1, 1000, 80.0, 10, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)),
            (2, 2000, 80.0, 10, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        temp_ring_buffer.write_batch(orders)

        consumer = ZeroCopyConsumer(ring_buffer=temp_ring_buffer, batch_size=1)
        stats = adapter.run_consumer(consumer=consumer, total_orders=2)

        assert stats.total_orders_read == 2
        assert stats.total_orders_dispatched == 2
        assert stats.total_trades_generated == 1
        assert len(adapter.trades) == 1
        assert engine.ask_count() == 0
        assert engine.bid_count() == 0
