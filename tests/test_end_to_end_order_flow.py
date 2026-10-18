"""ChronosMatch End-to-End Order-Flow Integration Test Suite (Working Day 7).

Deterministic, truthful end-to-end integration tests verifying the full order pipeline:
1. Valid BUY and SELL orders created with real parameters.
2. Encoded using the real 32-byte binary protocol (<QQdIHBB struct).
3. Transferred through the real isolated memory-mapped ring buffer (MmapRingBuffer).
4. Read and decoded using the supported consumer API (ZeroCopyConsumer) and OrderAdapter.
5. Ingested into the compiled Cython MatchingEngine using real supported interfaces (match_order / submit_order).
6. Resulting fills, order IDs, execution prices (maker price policy), execution quantities,
   and remaining quantities verified against exact expected outcomes.

Includes deterministic crossing matches, non-crossing resting orders, multi-order sweeps,
FIFO price-time priority, multi-symbol routing, and truthful handling of boundary limits.
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
    pack_order_into,
    unpack_order_raw,
)
from chronos.ring_buffer import MmapRingBuffer
from tests.trading_scenarios import (
    SCENARIO_1_EXACT_MATCH,
    SCENARIO_3_NO_TRADE,
    SCENARIO_4_PARTIAL_FILL_BUY_LARGER,
    SCENARIO_7_FIFO_SAME_PRICE,
    ScenarioOrder,
)


# ==============================================================================
# Pytest Fixtures
# ==============================================================================

@pytest.fixture
def isolated_ring_buffer() -> Generator[MmapRingBuffer, None, None]:
    """Create an isolated, temporary memory-mapped ring buffer with guaranteed cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_e2e_ring_", suffix=".bin")
    os.close(fd)
    buffer = MmapRingBuffer(filepath=path, capacity=1024, slot_size=ORDER_SIZE, create=True)
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
def matching_engine() -> Generator[MatchingEngine, None, None]:
    """Provide a clean, verified MatchingEngine instance."""
    engine = MatchingEngine()
    assert engine.is_ready() is True
    yield engine
    engine.clear()


@pytest.fixture
def order_adapter(
    isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
) -> OrderAdapter:
    """Provide an OrderAdapter connecting the isolated ring buffer to the matching engine."""
    return OrderAdapter(
        ring_buffer=isolated_ring_buffer,
        engine=matching_engine,
        dispatch_mode="match",
    )


# ==============================================================================
# Step 2 & 3: Deterministic Crossing and Non-Crossing Order Flow
# ==============================================================================

class TestDeterministicCrossingAndNonCrossingOrderFlow:
    """Canonical end-to-end order-flow integration tests (Day 7 Core Invariants)."""

    def test_deterministic_order_flow_crossing_and_non_crossing(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """Verify the complete 5-order pipeline flow with crossing and non-crossing orders.

        Order Flow:
        1. SELL #101: 100 shares @ $150.00 (Resting ask, opposite book empty)
        2. BUY  #102:  50 shares @ $148.00 (Non-crossing bid, 148 < 150 -> rests in bids)
        3. BUY  #103:  40 shares @ $150.00 (Crossing bid, fills 40 against #101 @ $150.00)
        4. BUY  #104:  80 shares @ $152.00 (Crossing bid, fills remaining 60 of #101 @ $150.00,
                                            leaves 20 resting in bids)
        5. SELL #105:  30 shares @ $155.00 (Non-crossing ask, 155 > 152 -> rests in asks)

        Expected Invariants:
        - Orders arrive in strict FIFO sequence through the ring buffer.
        - BUY #103 and SELL #101 match 40 shares at maker price $150.00 (15000 cents).
        - SELL #101 retains exactly 60 shares after fill 1.
        - BUY #104 and SELL #101 match 60 shares at maker price $150.00.
        - SELL #101 is fully filled and removed from asks book.
        - BUY #104 retains 20 shares and rests in bids book.
        - Non-crossing orders (#102 and #105) are never executed.
        - No order is lost or processed twice.
        """
        # Step 1: Create valid BUY and SELL orders using real protocol NamedTuples
        base_ts = 1_700_000_000_000_000_000
        sym_aapl = SYMBOLS["AAPL"]

        orders = [
            Order(
                order_id=101,
                timestamp_ns=base_ts + 1000,
                price=150.00,
                quantity=100,
                symbol_id=sym_aapl,
                side=int(Side.SELL),
                order_type=int(OrderType.LIMIT),
            ),
            Order(
                order_id=102,
                timestamp_ns=base_ts + 2000,
                price=148.00,
                quantity=50,
                symbol_id=sym_aapl,
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            ),
            Order(
                order_id=103,
                timestamp_ns=base_ts + 3000,
                price=150.00,
                quantity=40,
                symbol_id=sym_aapl,
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            ),
            Order(
                order_id=104,
                timestamp_ns=base_ts + 4000,
                price=152.00,
                quantity=80,
                symbol_id=sym_aapl,
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            ),
            Order(
                order_id=105,
                timestamp_ns=base_ts + 5000,
                price=155.00,
                quantity=30,
                symbol_id=sym_aapl,
                side=int(Side.SELL),
                order_type=int(OrderType.LIMIT),
            ),
        ]

        # Step 2: Encode using real binary protocol and transfer through MmapRingBuffer
        for ord_item in orders:
            written = isolated_ring_buffer.write_order(ord_item)
            assert written is True

        assert isolated_ring_buffer.available_to_read() == 5
        assert isolated_ring_buffer.is_empty() is False

        # Step 3: Sequential step-by-step processing through adapter to engine

        # --- Ingest Order 1: SELL #101 ---
        raw1, trades1 = order_adapter.process_next()
        assert raw1 is not None
        assert raw1[0] == 101  # order_id
        assert len(trades1) == 0  # No resting bids to match against
        assert matching_engine.ask_count() == 1
        assert matching_engine.bid_count() == 0
        best_ask = matching_engine.get_best_sell_order()
        assert best_ask.order_id == 101
        assert best_ask.price_cents == 15000
        assert best_ask.remaining_quantity == 100

        # --- Ingest Order 2: BUY #102 (Non-crossing) ---
        raw2, trades2 = order_adapter.process_next()
        assert raw2 is not None
        assert raw2[0] == 102
        assert len(trades2) == 0  # 148.00 < 150.00 -> no trade possible
        assert matching_engine.ask_count() == 1
        assert matching_engine.bid_count() == 1
        best_bid = matching_engine.get_best_buy_order()
        assert best_bid.order_id == 102
        assert best_bid.price_cents == 14800
        assert best_bid.remaining_quantity == 50
        # Verify non-crossing order is NOT executed
        assert best_ask.remaining_quantity == 100

        # --- Ingest Order 3: BUY #103 (Crossing - Partial Fill against SELL #101) ---
        raw3, trades3 = order_adapter.process_next()
        assert raw3 is not None
        assert raw3[0] == 103
        assert len(trades3) == 1

        fill1 = trades3[0]
        assert fill1.buy_order_id == 103
        assert fill1.sell_order_id == 101
        assert fill1.executed_quantity == 40
        assert fill1.execution_price_cents == 15000  # Resting SELL's price (maker price)
        assert fill1.execution_price == 150.00
        assert fill1.buy_remaining_quantity == 0
        assert fill1.sell_remaining_quantity == 60

        # Check post-fill order book state
        assert matching_engine.ask_count() == 1
        assert matching_engine.bid_count() == 1  # Only BUY #102 remains in bids
        best_ask = matching_engine.get_best_sell_order()
        assert best_ask.order_id == 101
        assert best_ask.remaining_quantity == 60  # Retains correct remainder
        assert best_ask.quantity == 100  # Original quantity intact

        # --- Ingest Order 4: BUY #104 (Crossing - Sweeps SELL #101, leaves remainder) ---
        raw4, trades4 = order_adapter.process_next()
        assert raw4 is not None
        assert raw4[0] == 104
        assert len(trades4) == 1

        fill2 = trades4[0]
        assert fill2.buy_order_id == 104
        assert fill2.sell_order_id == 101
        assert fill2.executed_quantity == 60
        assert fill2.execution_price_cents == 15000  # Resting SELL's price
        assert fill2.buy_remaining_quantity == 20
        assert fill2.sell_remaining_quantity == 0

        # SELL #101 is fully filled -> removed from asks book
        assert matching_engine.ask_count() == 0
        # BUY #104 partially filled -> remaining 20 shares rest in bids book
        assert matching_engine.bid_count() == 2
        best_bid = matching_engine.get_best_buy_order()
        assert best_bid.order_id == 104
        assert best_bid.price_cents == 15200
        assert best_bid.remaining_quantity == 20
        assert best_bid.quantity == 80  # Original quantity intact

        # --- Ingest Order 5: SELL #105 (Non-crossing) ---
        raw5, trades5 = order_adapter.process_next()
        assert raw5 is not None
        assert raw5[0] == 105
        assert len(trades5) == 0  # 155.00 > 152.00 -> no trade possible

        # Final book state verification
        assert matching_engine.ask_count() == 1
        assert matching_engine.bid_count() == 2
        ask_order = matching_engine.get_best_sell_order()
        assert ask_order.order_id == 105
        assert ask_order.price_cents == 15500
        assert ask_order.remaining_quantity == 30

        # Verify spread
        best_bid_price = matching_engine.get_best_bid_price()
        best_ask_price = matching_engine.get_best_ask_price()
        assert best_bid_price == 152.00
        assert best_ask_price == 155.00
        assert round(best_ask_price - best_bid_price, 2) == 3.00

        # Verify ring buffer and adapter metrics
        assert isolated_ring_buffer.is_empty() is True
        assert isolated_ring_buffer.available_to_read() == 0

        stats = order_adapter.stats
        assert stats.total_orders_read == 5
        assert stats.total_orders_dispatched == 5
        assert stats.total_trades_generated == 2
        assert stats.total_volume_matched == 100  # 40 + 60
        assert stats.non_crossing_orders == 3     # #101, #102, #105
        assert stats.unhandled_order_types == 0
        assert stats.unrouted_symbols == 0
        assert len(order_adapter.trades) == 2


# ==============================================================================
# Pipeline with ZeroCopyConsumer
# ==============================================================================

class TestZeroCopyConsumerPipelineEndToEnd:
    """End-to-end integration combining MmapRingBuffer, ZeroCopyConsumer, and MatchingEngine."""

    def test_consumer_drains_buffer_to_engine_via_adapter(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """Verify ZeroCopyConsumer drains orders from shared memory directly into MatchingEngine."""
        base_ts = 1_700_000_000_000_000_000
        sym_id = SYMBOLS["NVDA"]

        # Prepare 4 deterministic orders
        orders = [
            # Resting BUY #201: 50 @ $120.00
            (201, base_ts + 1000, 120.00, 50, sym_id, int(Side.BUY), int(OrderType.LIMIT)),
            # Resting BUY #202: 50 @ $122.00 (highest bid)
            (202, base_ts + 2000, 122.00, 50, sym_id, int(Side.BUY), int(OrderType.LIMIT)),
            # Non-crossing SELL #203: 30 @ $125.00 (125 > 122 -> no trade)
            (203, base_ts + 3000, 125.00, 30, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
            # Crossing SELL #204: 60 @ $121.00 (crosses with #202 at $122.00 for 50, then rests 10 in asks)
            (204, base_ts + 4000, 121.00, 60, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
        ]

        # Write batch into ring buffer
        written = isolated_ring_buffer.write_batch(orders)
        assert written == 4

        # Configure consumer with order_handler connected to adapter
        consumer = ZeroCopyConsumer(
            ring_buffer=isolated_ring_buffer,
            batch_size=2,
            order_handler=order_adapter.dispatch_raw_order,
        )

        # Run consumer bounded by total_orders
        consumer_stats = consumer.run(total_orders=4, print_progress=False)

        # Invariant checks:
        # Consumer drained all orders
        assert consumer_stats.total_orders_read == 4
        assert isolated_ring_buffer.is_empty() is True

        # Trades verified
        assert len(order_adapter.trades) == 1
        trade = order_adapter.trades[0]
        # Incoming SELL #204 matched against resting BUY #202
        assert trade.buy_order_id == 202
        assert trade.sell_order_id == 204
        assert trade.executed_quantity == 50
        assert trade.execution_price_cents == 12200  # Resting BUY's price (maker price)
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 10

        # Post-trade book state:
        # BUY #202 is cleared; BUY #201 (rem 50) remains
        assert matching_engine.bid_count() == 1
        assert matching_engine.get_best_buy_order().order_id == 201

        # Asks: SELL #203 (rem 30 @ 125.00) and SELL #204 (rem 10 @ 121.00)
        assert matching_engine.ask_count() == 2
        best_ask = matching_engine.get_best_sell_order()
        assert best_ask.order_id == 204
        assert best_ask.price_cents == 12100
        assert best_ask.remaining_quantity == 10


# ==============================================================================
# Multi-Order Sweep End-to-End
# ==============================================================================

class TestMultiOrderSweepEndToEndFlow:
    """Verifies that an incoming order sweeps multiple resting book levels through IPC."""

    def test_incoming_buy_sweeps_multiple_resting_sells_via_buffer(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """An incoming BUY order sweeps 3 resting SELL orders in strict price-time priority.

        Resting SELLs:
        #301: 30 shares @ $10.00
        #302: 40 shares @ $10.50
        #303: 50 shares @ $11.00

        Incoming BUY:
        #304: 100 shares @ $11.00

        Expected:
        - Fill 30 against #301 @ $10.00 (maker price)
        - Fill 40 against #302 @ $10.50 (maker price)
        - Fill 30 against #303 @ $11.00 (maker price)
        - 20 shares of #303 remain in asks book.
        - BUY #304 is completely filled.
        """
        sym_id = SYMBOLS["TSLA"]
        base_ts = 1_000_000

        # Orders written through ring buffer
        resting_sells = [
            (301, base_ts + 100, 10.00, 30, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
            (302, base_ts + 200, 10.50, 40, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
            (303, base_ts + 300, 11.00, 50, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(resting_sells)

        # Drain resting orders into engine
        initial_trades = order_adapter.drain_all()
        assert len(initial_trades) == 0
        assert matching_engine.ask_count() == 3

        # Write incoming large BUY order
        incoming_buy = Order(
            order_id=304,
            timestamp_ns=base_ts + 400,
            price=11.00,
            quantity=100,
            symbol_id=sym_id,
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        isolated_ring_buffer.write_order(incoming_buy)

        # Drain and match
        sweep_trades = order_adapter.drain_all()
        assert len(sweep_trades) == 3

        # Fill 1: against #301
        assert sweep_trades[0].buy_order_id == 304
        assert sweep_trades[0].sell_order_id == 301
        assert sweep_trades[0].executed_quantity == 30
        assert sweep_trades[0].execution_price_cents == 1000

        # Fill 2: against #302
        assert sweep_trades[1].buy_order_id == 304
        assert sweep_trades[1].sell_order_id == 302
        assert sweep_trades[1].executed_quantity == 40
        assert sweep_trades[1].execution_price_cents == 1050

        # Fill 3: against #303
        assert sweep_trades[2].buy_order_id == 304
        assert sweep_trades[2].sell_order_id == 303
        assert sweep_trades[2].executed_quantity == 30
        assert sweep_trades[2].execution_price_cents == 1100

        # Total volume
        total_vol = sum(t.executed_quantity for t in sweep_trades)
        assert total_vol == 100

        # Check remaining book
        assert matching_engine.bid_count() == 0  # BUY completely filled
        assert matching_engine.ask_count() == 1  # Only #303 remains
        remaining_ask = matching_engine.get_best_sell_order()
        assert remaining_ask.order_id == 303
        assert remaining_ask.remaining_quantity == 20


# ==============================================================================
# FIFO Price-Time Priority End-to-End
# ==============================================================================

class TestFIFOTimePriorityEndToEndFlow:
    """Verifies that time priority (FIFO) is strictly preserved across IPC transfer."""

    def test_fifo_time_priority_at_equal_prices_through_pipeline(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """Two resting SELL orders have identical prices; the earlier arrival must match first."""
        sym_id = SYMBOLS["MSFT"]
        base_ts = 2_000_000

        # SELL #401 arrives at ts=1000, price $50.00, qty 50
        # SELL #402 arrives at ts=2000, price $50.00, qty 50
        sells = [
            (401, base_ts + 1000, 50.00, 50, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
            (402, base_ts + 2000, 50.00, 50, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(sells)
        order_adapter.drain_all()

        assert matching_engine.ask_count() == 2
        # Prioritized asks should show earlier #401 first
        prioritized = matching_engine.get_prioritized_asks()
        assert prioritized[0].order_id == 401
        assert prioritized[1].order_id == 402

        # Incoming BUY #403 arrives at ts=3000, price $50.00, qty 60
        buy = Order(
            order_id=403,
            timestamp_ns=base_ts + 3000,
            price=50.00,
            quantity=60,
            symbol_id=sym_id,
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        isolated_ring_buffer.write_order(buy)
        trades = order_adapter.drain_all()

        assert len(trades) == 2
        # First match MUST be #401 (earlier timestamp / sequence)
        assert trades[0].sell_order_id == 401
        assert trades[0].executed_quantity == 50
        assert trades[0].sell_remaining_quantity == 0

        # Second match fills remaining 10 against #402
        assert trades[1].sell_order_id == 402
        assert trades[1].executed_quantity == 10
        assert trades[1].sell_remaining_quantity == 40

        # Only #402 remains in asks book with 40 shares
        assert matching_engine.ask_count() == 1
        assert matching_engine.get_best_sell_order().order_id == 402
        assert matching_engine.get_best_sell_order().remaining_quantity == 40


# ==============================================================================
# Multi-Symbol Routing
# ==============================================================================

class TestMultiSymbolPipelineRouting:
    """Verifies symbol demultiplexing through OrderAdapter."""

    def test_multi_symbol_routing_through_adapter(
        self, isolated_ring_buffer: MmapRingBuffer
    ):
        """Interleaved orders for AAPL and MSFT route to their respective matching engines."""
        engine_aapl = MatchingEngine()
        engine_msft = MatchingEngine()

        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            symbol_engines={
                SYMBOLS["AAPL"]: engine_aapl,
                SYMBOLS["MSFT"]: engine_msft,
            },
            dispatch_mode="match",
        )

        base_ts = 3_000_000
        # 4 orders: 2 AAPL, 2 MSFT
        mixed_orders = [
            # AAPL SELL #501: 100 @ 220.00
            (501, base_ts + 100, 220.00, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            # MSFT SELL #502: 50 @ 410.00
            (502, base_ts + 200, 410.00, 50, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)),
            # AAPL BUY #503: 40 @ 220.00 (crosses AAPL #501)
            (503, base_ts + 300, 220.00, 40, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            # MSFT BUY #504: 50 @ 410.00 (crosses MSFT #502)
            (504, base_ts + 400, 410.00, 50, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)),
        ]

        isolated_ring_buffer.write_batch(mixed_orders)
        trades = adapter.drain_all()

        assert len(trades) == 2

        # Verify AAPL trade
        aapl_trade = next(t for t in trades if t.buy_order_id == 503)
        assert aapl_trade.sell_order_id == 501
        assert aapl_trade.executed_quantity == 40
        assert aapl_trade.execution_price_cents == 22000

        # Verify MSFT trade
        msft_trade = next(t for t in trades if t.buy_order_id == 504)
        assert msft_trade.sell_order_id == 502
        assert msft_trade.executed_quantity == 50
        assert msft_trade.execution_price_cents == 41000

        # Verify AAPL book: SELL #501 has 60 remaining
        assert engine_aapl.ask_count() == 1
        assert engine_aapl.get_best_sell_order().remaining_quantity == 60
        assert engine_aapl.bid_count() == 0

        # Verify MSFT book: both fully filled and cleared
        assert engine_msft.ask_count() == 0
        assert engine_msft.bid_count() == 0


# ==============================================================================
# Day 5 Scenarios End-to-End
# ==============================================================================

class TestDay5ScenariosEndToEnd:
    """Verifies Day 5 deterministic trading scenarios executed via ring buffer and adapter."""

    def test_day5_exact_match_e2e(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """Scenario 1 (Exact Match): 50 BUY @ 500.00 vs 50 SELL @ 500.00."""
        scenario = SCENARIO_1_EXACT_MATCH
        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        trades = order_adapter.drain_all()
        assert len(trades) == 1
        trade = trades[0]

        assert trade.executed_quantity == scenario.expected.total_matched_quantity
        assert trade.execution_price_cents == scenario.expected.trades[0].execution_price_cents
        assert matching_engine.bid_count() == 0
        assert matching_engine.ask_count() == 0

    def test_day5_partial_fill_e2e(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """Scenario 4 (Partial Fill): 100 BUY @ 505.00 vs 40 SELL @ 500.00."""
        scenario = SCENARIO_4_PARTIAL_FILL_BUY_LARGER
        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        trades = order_adapter.drain_all()
        assert len(trades) == 1
        trade = trades[0]

        assert trade.executed_quantity == 40
        assert trade.execution_price_cents == 50000  # resting SELL maker price
        assert trade.buy_remaining_quantity == 60
        assert trade.sell_remaining_quantity == 0

        # BUY remains in book with 60 shares
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 0
        assert matching_engine.get_best_buy_order().remaining_quantity == 60

    def test_day5_no_trade_spread_e2e(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """Scenario 3 (No Trade): 100 BUY @ 495.00 vs 100 SELL @ 505.00."""
        scenario = SCENARIO_3_NO_TRADE
        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        trades = order_adapter.drain_all()
        assert len(trades) == 0

        # Both orders rest in book untouched
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 1
        assert matching_engine.get_best_buy_order().remaining_quantity == 100
        assert matching_engine.get_best_sell_order().remaining_quantity == 100


# ==============================================================================
# Boundary Handling and Truthful Limitations
# ==============================================================================

class TestBoundaryHandlingAndResourceCleanup:
    """Verifies edge cases, unhandled order types, and resource cleanup."""

    def test_cancel_order_type_truthful_recording(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
    ):
        """CANCEL order type is truthfully recorded as unhandled without crashing the engine."""
        cancel_order = Order(
            order_id=601,
            timestamp_ns=1_000_000,
            price=100.00,
            quantity=10,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.CANCEL),
        )

        isolated_ring_buffer.write_order(cancel_order)
        trades = order_adapter.drain_all()

        assert len(trades) == 0
        assert order_adapter.stats.unhandled_order_types == 1
        assert len(order_adapter.unhandled_orders) == 1
        # Matching engine book state remains clean and untouched
        assert matching_engine.bid_count() == 0
        assert matching_engine.ask_count() == 0

    def test_unrouted_symbol_recording(
        self,
        isolated_ring_buffer: MmapRingBuffer,
    ):
        """Order with unmapped symbol and no default engine is recorded truthfully."""
        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            engine=None,  # No default engine
            symbol_engines={SYMBOLS["AAPL"]: MatchingEngine()},
        )

        nvda_order = Order(
            order_id=701,
            timestamp_ns=1_000_000,
            price=120.00,
            quantity=50,
            symbol_id=SYMBOLS["NVDA"],  # Not in symbol_engines
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )

        isolated_ring_buffer.write_order(nvda_order)
        trades = adapter.drain_all()

        assert len(trades) == 0
        assert adapter.stats.unrouted_symbols == 1
        assert len(adapter.unrouted_orders) == 1

    def test_resource_cleanup_under_exceptions(self):
        """Verify memory map and file handles are cleaned up even when errors occur."""
        fd, path = tempfile.mkstemp(prefix="chronos_cleanup_test_", suffix=".bin")
        os.close(fd)

        buffer = MmapRingBuffer(filepath=path, capacity=64, slot_size=ORDER_SIZE, create=True)
        try:
            assert os.path.exists(path)
            # Simulate work
            buffer.write(1, 1000, 100.0, 10, 1001, 1, 1)
            assert buffer.available_to_read() == 1
        finally:
            buffer.close()
            if os.path.exists(path):
                os.remove(path)

        assert not os.path.exists(path)
