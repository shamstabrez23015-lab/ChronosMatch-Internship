"""ChronosMatch Pipeline Integration Test Foundation (Working Day 6, extended Day 6+).

Builds an executable integration-test foundation linking:
1. Binary Order Protocol (<QQdIHBB struct packing/unpacking)
2. Zero-Copy SPSC Memory-Mapped Ring Buffer (single, batch, and sequential transfers)
3. Ring Buffer Consumer Component (ZeroCopyConsumer draining real buffer)
4. Binary Decoded Values to Matching Engine Order Adaptation Boundary
5. Day 5 Reusable Deterministic Trading Scenarios (protocol compatibility and engine matching)
6. Integrated Multi-Step Pipeline Flow across existing real boundaries

Day 6+ Extension Boundaries:
7. OrderAdapter Smoke Tests (dispatch mode, stats, event emission, latency tracking)
8. Ring Buffer Capacity & Saturation Boundaries (overwrite policy, available_to_read/write)
9. Consumer-to-Adapter-to-Engine Coupled Pipeline (run_consumer bound to adapter)
10. AdapterStats Accumulation Across Multiple Dispatch Calls
11. TradeExecutionEvent Introspection (latency_ns, matched, volume_matched)
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Generator, List, Tuple

import pytest

from chronos.adapter import AdapterStats, OrderAdapter, TradeExecutionEvent
from chronos.consumer import ConsumerStats, ZeroCopyConsumer
from chronos.matching_engine import COrder, MatchingEngine, TradeResult, price_to_cents
from chronos.ring_buffer import MmapRingBuffer
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
from tests.trading_scenarios import (
    ALL_SCENARIOS,
    SCENARIO_1_EXACT_MATCH,
    SCENARIO_3_NO_TRADE,
    SCENARIO_4_PARTIAL_FILL_BUY_LARGER,
    SCENARIO_7_FIFO_SAME_PRICE,
    ScenarioOrder,
    get_all_scenarios,
    get_scenario,
)


# ==============================================================================
# Pytest Fixtures
# ==============================================================================

@pytest.fixture
def isolated_ring_buffer() -> Generator[MmapRingBuffer, None, None]:
    """Create an isolated, temporary memory-mapped ring buffer with safe cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_int_ring_", suffix=".bin")
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
    """Provide a clean, ready MatchingEngine instance."""
    engine = MatchingEngine()
    assert engine.is_ready() is True
    yield engine
    engine.clear()


@pytest.fixture
def sample_buy_order() -> Order:
    """Provide a valid deterministic BUY order in protocol representation."""
    return Order(
        order_id=1001,
        timestamp_ns=1_000_000_000,
        price=225.50,
        quantity=100,
        symbol_id=SYMBOLS["AAPL"],
        side=int(Side.BUY),
        order_type=int(OrderType.LIMIT),
    )


@pytest.fixture
def sample_sell_order() -> Order:
    """Provide a valid deterministic SELL order in protocol representation."""
    return Order(
        order_id=1002,
        timestamp_ns=1_000_000_100,
        price=226.00,
        quantity=150,
        symbol_id=SYMBOLS["AAPL"],
        side=int(Side.SELL),
        order_type=int(OrderType.LIMIT),
    )


@pytest.fixture
def deterministic_order_batch() -> List[Order]:
    """Provide a deterministic batch of mixed BUY and SELL orders."""
    symbols = [SYMBOLS["AAPL"], SYMBOLS["NVDA"], SYMBOLS["TSLA"], SYMBOLS["MSFT"]]
    orders: List[Order] = []
    base_ts = 1_700_000_000_000_000_000

    for i in range(12):
        side = int(Side.BUY) if i % 2 == 0 else int(Side.SELL)
        price = round(100.0 + (i * 1.25), 2)
        qty = (i + 1) * 25
        sym_id = symbols[i % len(symbols)]
        orders.append(
            Order(
                order_id=2000 + i,
                timestamp_ns=base_ts + (i * 1000),
                price=price,
                quantity=qty,
                symbol_id=sym_id,
                side=side,
                order_type=int(OrderType.LIMIT),
            )
        )
    return orders


# ==============================================================================
# Boundary 1: Binary Order Protocol Serialization / Deserialization
# ==============================================================================

class TestBinaryProtocolBoundary:
    """Validates binary serialization fidelity, struct layout, and zero-copy unpack."""

    def test_order_to_binary_conversion(self, sample_buy_order: Order):
        """1. A valid test order can be converted to the established binary format."""
        raw_bytes = sample_buy_order.pack()
        assert len(raw_bytes) == ORDER_SIZE
        assert len(raw_bytes) == 32

    def test_binary_order_decoding_roundtrip(self, sample_buy_order: Order):
        """2. The binary order can be decoded back into the expected fields."""
        raw_bytes = sample_buy_order.pack()
        decoded = Order.unpack(raw_bytes)

        assert decoded.order_id == sample_buy_order.order_id
        assert decoded.timestamp_ns == sample_buy_order.timestamp_ns
        assert abs(decoded.price - sample_buy_order.price) < 1e-6
        assert decoded.quantity == sample_buy_order.quantity
        assert decoded.symbol_id == sample_buy_order.symbol_id
        assert decoded.side == sample_buy_order.side
        assert decoded.order_type == sample_buy_order.order_type
        assert decoded.side_str == "BUY"
        assert decoded.order_type_str == "LIMIT"
        assert decoded.symbol_str == "AAPL"

    def test_zero_copy_pack_into_and_unpack_raw(self, sample_sell_order: Order):
        """Verify zero-copy buffer serialization into arbitrary byte offsets."""
        buffer = bytearray(64)
        view = memoryview(buffer)
        offset = 32

        sample_sell_order.pack_into(view, offset=offset)
        raw_tuple = unpack_order_raw(view, offset=offset)

        assert raw_tuple[0] == sample_sell_order.order_id
        assert raw_tuple[1] == sample_sell_order.timestamp_ns
        assert abs(raw_tuple[2] - sample_sell_order.price) < 1e-6
        assert raw_tuple[3] == sample_sell_order.quantity
        assert raw_tuple[4] == sample_sell_order.symbol_id
        assert raw_tuple[5] == sample_sell_order.side
        assert raw_tuple[6] == sample_sell_order.order_type

    def test_protocol_numeric_boundaries(self):
        """Verify max integer values and float precision are preserved in 32B struct."""
        max_uint64 = 0xFFFFFFFFFFFFFFFF
        max_uint32 = 0xFFFFFFFF
        max_uint16 = 0xFFFF
        ts = 1_700_000_000_000_000_000
        price = 9999.99

        order = Order(
            order_id=max_uint64,
            timestamp_ns=ts,
            price=price,
            quantity=max_uint32,
            symbol_id=max_uint16,
            side=int(Side.SELL),
            order_type=int(OrderType.CANCEL),
        )

        packed = order.pack()
        unpacked = Order.unpack(packed)

        assert unpacked.order_id == max_uint64
        assert unpacked.timestamp_ns == ts
        assert abs(unpacked.price - price) < 1e-6
        assert unpacked.quantity == max_uint32
        assert unpacked.symbol_id == max_uint16
        assert unpacked.side == int(Side.SELL)
        assert unpacked.order_type == int(OrderType.CANCEL)


# ==============================================================================
# Boundary 2: Shared Memory Ring Buffer IPC Data Preservation & Sequencing
# ==============================================================================

class TestRingBufferBoundary:
    """Validates that existing ring buffer operations preserve data and FIFO sequencing."""

    def test_single_order_producer_consumer_preservation(
        self, isolated_ring_buffer: MmapRingBuffer, sample_buy_order: Order
    ):
        """3. Existing ring buffer producer and consumer operations preserve order data."""
        written = isolated_ring_buffer.write_order(sample_buy_order)
        assert written is True
        assert isolated_ring_buffer.available_to_read() == 1

        read_order = isolated_ring_buffer.read_order()
        assert read_order is not None
        assert read_order.order_id == sample_buy_order.order_id
        assert read_order.timestamp_ns == sample_buy_order.timestamp_ns
        assert abs(read_order.price - sample_buy_order.price) < 1e-6
        assert read_order.quantity == sample_buy_order.quantity
        assert read_order.symbol_id == sample_buy_order.symbol_id
        assert read_order.side == sample_buy_order.side
        assert read_order.order_type == sample_buy_order.order_type
        assert isolated_ring_buffer.is_empty() is True

    def test_multiple_orders_sequence_preservation(
        self, isolated_ring_buffer: MmapRingBuffer, deterministic_order_batch: List[Order]
    ):
        """4. Multiple orders can be transferred in the intended sequence."""
        # Write multiple orders sequentially
        for ord_item in deterministic_order_batch:
            ok = isolated_ring_buffer.write_order(ord_item)
            assert ok is True

        assert isolated_ring_buffer.available_to_read() == len(deterministic_order_batch)

        # Read back sequentially and verify exact FIFO order
        for expected_ord in deterministic_order_batch:
            actual_ord = isolated_ring_buffer.read_order()
            assert actual_ord is not None
            assert actual_ord.order_id == expected_ord.order_id
            assert actual_ord.timestamp_ns == expected_ord.timestamp_ns
            assert abs(actual_ord.price - expected_ord.price) < 1e-6
            assert actual_ord.quantity == expected_ord.quantity
            assert actual_ord.symbol_id == expected_ord.symbol_id
            assert actual_ord.side == expected_ord.side
            assert actual_ord.order_type == expected_ord.order_type

        assert isolated_ring_buffer.is_empty() is True
        assert isolated_ring_buffer.read_order() is None

    def test_batch_write_and_batch_read_preservation(
        self, isolated_ring_buffer: MmapRingBuffer, deterministic_order_batch: List[Order]
    ):
        """Verify high-throughput batch operations preserve sequence and data."""
        raw_tuples = [
            (
                o.order_id,
                o.timestamp_ns,
                o.price,
                o.quantity,
                o.symbol_id,
                o.side,
                o.order_type,
            )
            for o in deterministic_order_batch
        ]

        written_count = isolated_ring_buffer.write_batch(raw_tuples)
        assert written_count == len(raw_tuples)
        assert isolated_ring_buffer.available_to_read() == len(raw_tuples)

        read_batch = isolated_ring_buffer.read_batch_orders(max_items=50)
        assert len(read_batch) == len(deterministic_order_batch)

        for actual, expected in zip(read_batch, deterministic_order_batch):
            assert actual.order_id == expected.order_id
            assert actual.timestamp_ns == expected.timestamp_ns
            assert abs(actual.price - expected.price) < 1e-6
            assert actual.quantity == expected.quantity
            assert actual.side == expected.side

        assert isolated_ring_buffer.is_empty() is True


# ==============================================================================
# Boundary 3: Consumer Component Integration
# ==============================================================================

class TestConsumerComponentBoundary:
    """Validates that ZeroCopyConsumer reads from the real memory-mapped ring buffer."""

    def test_consumer_drains_real_buffer(
        self, isolated_ring_buffer: MmapRingBuffer, deterministic_order_batch: List[Order]
    ):
        """ZeroCopyConsumer drains batch of orders from mmap buffer and updates stats."""
        raw_tuples = [
            (
                o.order_id,
                o.timestamp_ns,
                o.price,
                o.quantity,
                o.symbol_id,
                o.side,
                o.order_type,
            )
            for o in deterministic_order_batch
        ]
        isolated_ring_buffer.write_batch(raw_tuples)

        consumer = ZeroCopyConsumer(isolated_ring_buffer, batch_size=5)
        stats = consumer.run(total_orders=len(raw_tuples), print_progress=False)

        assert stats.total_orders_read == len(raw_tuples)
        assert isolated_ring_buffer.is_empty() is True
        assert stats.elapsed_time >= 0.0

    def test_consumer_clean_exit_on_duration_limit(
        self, isolated_ring_buffer: MmapRingBuffer
    ):
        """ZeroCopyConsumer exits cleanly when duration limit expires without hanging."""
        consumer = ZeroCopyConsumer(isolated_ring_buffer, batch_size=10)
        # Run on empty buffer for 10ms
        stats = consumer.run(duration_seconds=0.01, print_progress=False)

        assert stats.total_orders_read == 0
        assert consumer.is_running is False


# ==============================================================================
# Boundary 4: Binary Decoded Values to Matching Engine Order Adaptation
# ==============================================================================

class TestBinaryToEngineAdaptationBoundary:
    """5. Binary decoded values can be adapted to the existing matching-engine order representation."""

    def test_adapt_decoded_order_to_matching_engine_submit(
        self, matching_engine: MatchingEngine, sample_buy_order: Order
    ):
        """Verify unpacked protocol Order adapts into MatchingEngine.submit_order."""
        # Step 1: Pack order into binary format
        raw_bytes = sample_buy_order.pack()

        # Step 2: Decode from binary
        decoded = Order.unpack(raw_bytes)

        # Step 3: Adapt decoded fields to matching engine's supported submission API
        cord: COrder = matching_engine.submit_order(
            order_id=decoded.order_id,
            side=decoded.side,
            price=decoded.price,
            quantity=decoded.quantity,
            timestamp_ns=decoded.timestamp_ns,
        )

        assert cord is not None
        assert cord.order_id == sample_buy_order.order_id
        assert cord.side == sample_buy_order.side
        assert cord.price_cents == price_to_cents(sample_buy_order.price)
        assert cord.price_cents == 22550
        assert cord.quantity == sample_buy_order.quantity
        assert cord.remaining_quantity == sample_buy_order.quantity
        assert cord.timestamp_ns == sample_buy_order.timestamp_ns
        assert cord.sequence_num == 1
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 0

    def test_adapt_raw_unpacked_tuple_to_matching_engine(
        self, matching_engine: MatchingEngine, sample_sell_order: Order
    ):
        """Verify raw tuple from unpack_order_raw adapts into MatchingEngine."""
        raw_bytes = sample_sell_order.pack()
        raw_tuple = unpack_order_raw(raw_bytes, 0)
        # raw_tuple: (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type)

        cord: COrder = matching_engine.submit_order(
            order_id=raw_tuple[0],
            side=raw_tuple[5],
            price=raw_tuple[2],
            quantity=raw_tuple[3],
            timestamp_ns=raw_tuple[1],
        )

        assert cord.order_id == sample_sell_order.order_id
        assert cord.side == int(Side.SELL)
        assert cord.price_cents == 22600
        assert cord.quantity == 150
        assert matching_engine.ask_count() == 1

    def test_adapted_binary_orders_maintain_price_priority(
        self, matching_engine: MatchingEngine
    ):
        """Multiple binary decoded orders maintain Price Priority inside the engine."""
        buy_prices = [100.00, 105.00, 102.50, 99.00]
        for idx, px in enumerate(buy_prices):
            ord_item = Order(
                order_id=3000 + idx,
                timestamp_ns=1000 + idx,
                price=px,
                quantity=10,
                symbol_id=SYMBOLS["AAPL"],
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            )
            # Pack, decode, adapt
            decoded = Order.unpack(ord_item.pack())
            matching_engine.submit_order(
                order_id=decoded.order_id,
                side=decoded.side,
                price=decoded.price,
                quantity=decoded.quantity,
                timestamp_ns=decoded.timestamp_ns,
            )

        best_buy = matching_engine.get_best_buy_order()
        assert best_buy is not None
        assert best_buy.order_id == 3001
        assert best_buy.price_cents == 10500
        assert matching_engine.get_best_bid_price() == 105.00

        prioritized = matching_engine.get_prioritized_bids()
        prioritized_prices = [o.price_cents for o in prioritized]
        assert prioritized_prices == [10500, 10250, 10000, 9900]

    def test_adapted_binary_orders_maintain_fifo_time_priority(
        self, matching_engine: MatchingEngine
    ):
        """Orders with identical prices maintain FIFO arrival priority when adapted."""
        same_price = 150.00
        for i in range(3):
            ord_item = Order(
                order_id=4000 + i,
                timestamp_ns=1_000_000 + (i * 500),
                price=same_price,
                quantity=50,
                symbol_id=SYMBOLS["NVDA"],
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            )
            decoded = Order.unpack(ord_item.pack())
            matching_engine.submit_order(
                order_id=decoded.order_id,
                side=decoded.side,
                price=decoded.price,
                quantity=decoded.quantity,
                timestamp_ns=decoded.timestamp_ns,
            )

        prioritized = matching_engine.get_prioritized_bids()
        prioritized_ids = [o.order_id for o in prioritized]
        assert prioritized_ids == [4000, 4001, 4002]


# ==============================================================================
# Boundary 5: Day 5 Deterministic Trading Scenarios & Pipeline Compatibility
# ==============================================================================

class TestDay5ScenariosCompatibilityBoundary:
    """6. Known Day 5 scenarios remain compatible with the real order protocol."""

    def test_all_day5_scenarios_binary_protocol_fidelity(self):
        """Verify all orders across all 10 Day 5 scenarios pack and unpack with full fidelity."""
        all_scenarios = get_all_scenarios()
        assert len(all_scenarios) == 10

        total_orders_tested = 0
        for scenario in all_scenarios:
            for sc_order in scenario.orders:
                # Test ScenarioOrder -> Order conversion
                proto_order = sc_order.to_protocol_order()
                assert isinstance(proto_order, Order)

                # Test serialization into 32 bytes
                packed = sc_order.pack()
                assert len(packed) == ORDER_SIZE

                # Test deserialization
                unpacked = Order.unpack(packed)
                assert unpacked.order_id == sc_order.order_id
                assert unpacked.side == sc_order.side
                assert abs(unpacked.price - sc_order.price) < 1e-6
                assert unpacked.quantity == sc_order.quantity
                assert unpacked.timestamp_ns == sc_order.timestamp_ns
                assert unpacked.symbol_id == sc_order.symbol_id
                assert unpacked.order_type == sc_order.order_type
                total_orders_tested += 1

        assert total_orders_tested >= 20

    def test_day5_scenario_transfer_through_ring_buffer(
        self, isolated_ring_buffer: MmapRingBuffer
    ):
        """Verify Day 5 scenario orders transfer cleanly through the mmap ring buffer."""
        scenario = SCENARIO_1_EXACT_MATCH
        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        assert isolated_ring_buffer.available_to_read() == len(scenario.orders)

        for expected_sc_order in scenario.orders:
            read_ord = isolated_ring_buffer.read_order()
            assert read_ord is not None
            assert read_ord.order_id == expected_sc_order.order_id
            assert abs(read_ord.price - expected_sc_order.price) < 1e-6
            assert read_ord.quantity == expected_sc_order.quantity
            assert read_ord.side == expected_sc_order.side

        assert isolated_ring_buffer.is_empty() is True

    def test_day5_exact_match_execution_via_buffer_to_engine(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """Scenario 1: Buffer transfer -> Engine ingestion -> Exact match execution."""
        scenario = SCENARIO_1_EXACT_MATCH

        # 1. Producer writes scenario orders to ring buffer
        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        # 2. Consumer reads orders and adapts to matching engine
        while not isolated_ring_buffer.is_empty():
            ord_item = isolated_ring_buffer.read_order()
            assert ord_item is not None
            matching_engine.submit_order(
                order_id=ord_item.order_id,
                side=ord_item.side,
                price=ord_item.price,
                quantity=ord_item.quantity,
                timestamp_ns=ord_item.timestamp_ns,
            )

        # 3. Verify engine detected crossing
        assert matching_engine.has_crossing_prices() is True
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 1

        # 4. Execute match and verify against Day 5 expected trade
        trade: TradeResult = matching_engine.execute_partial_match()
        assert trade is not None
        assert trade.buy_order_id == scenario.expected.trades[0].buy_order_id
        assert trade.sell_order_id == scenario.expected.trades[0].sell_order_id
        assert trade.executed_quantity == scenario.expected.total_matched_quantity
        assert trade.execution_price_cents == scenario.expected.trades[0].execution_price_cents
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 0

        # Both orders fully filled and removed
        assert matching_engine.bid_count() == 0
        assert matching_engine.ask_count() == 0

    def test_day5_partial_fill_execution_via_buffer_to_engine(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """Scenario 4: BUY larger than SELL -> partial fill execution via pipeline."""
        scenario = SCENARIO_4_PARTIAL_FILL_BUY_LARGER

        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        while not isolated_ring_buffer.is_empty():
            ord_item = isolated_ring_buffer.read_order()
            assert ord_item is not None
            matching_engine.submit_order(
                order_id=ord_item.order_id,
                side=ord_item.side,
                price=ord_item.price,
                quantity=ord_item.quantity,
                timestamp_ns=ord_item.timestamp_ns,
            )

        assert matching_engine.has_crossing_prices() is True
        trade: TradeResult = matching_engine.execute_partial_match()
        assert trade is not None
        assert trade.executed_quantity == 40
        assert trade.buy_remaining_quantity == 60
        assert trade.sell_remaining_quantity == 0

        # BUY order remains partially filled; SELL is cleared
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 0
        remaining_buy = matching_engine.get_best_buy_order()
        assert remaining_buy.remaining_quantity == 60

    def test_day5_non_crossing_scenario_remains_in_book(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """Scenario 3: Non-crossing spread -> orders persist in book, zero matches."""
        scenario = SCENARIO_3_NO_TRADE

        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        while not isolated_ring_buffer.is_empty():
            ord_item = isolated_ring_buffer.read_order()
            assert ord_item is not None
            matching_engine.submit_order(
                order_id=ord_item.order_id,
                side=ord_item.side,
                price=ord_item.price,
                quantity=ord_item.quantity,
                timestamp_ns=ord_item.timestamp_ns,
            )

        assert matching_engine.has_crossing_prices() is False
        assert matching_engine.execute_partial_match() is None
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 1


# ==============================================================================
# Boundary 6: Integrated Multi-Step Pipeline Flow
# ==============================================================================

class TestIntegratedOrderFlowPipeline:
    """Validates multi-step flow across all real boundaries without mocks."""

    def test_complete_batch_order_flow(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """Pipeline flow: Raw batch -> Ring buffer -> Raw drain -> Engine -> Execution."""
        # Step 1: Create a batch with crossing bids and asks
        # Orders:
        # BUY 1: 100 shares @ $150.00
        # BUY 2: 50 shares @ $152.00 (highest bid)
        # SELL 1: 30 shares @ $148.00 (lowest ask - crosses with BUY 2)
        # SELL 2: 70 shares @ $155.00
        orders_batch = [
            (5001, 1_000_000, 150.00, 100, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            (5002, 1_001_000, 152.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            (5003, 1_002_000, 148.00, 30, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (5004, 1_003_000, 155.00, 70, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
        ]

        # Step 2: Write batch directly to ring buffer
        written = isolated_ring_buffer.write_batch(orders_batch)
        assert written == 4

        # Step 3: Drain batch using raw consumer method
        drained_raw = isolated_ring_buffer.read_batch_raw(max_items=10)
        assert len(drained_raw) == 4
        assert isolated_ring_buffer.is_empty() is True

        # Step 4: Adapt drained raw tuples into the Matching Engine
        for raw in drained_raw:
            matching_engine.submit_order(
                order_id=raw[0],
                side=raw[5],
                price=raw[2],
                quantity=raw[3],
                timestamp_ns=raw[1],
            )

        assert matching_engine.order_count() == 4
        assert matching_engine.bid_count() == 2
        assert matching_engine.ask_count() == 2

        # Step 5: Verify Price Priority on ingested book
        best_bid = matching_engine.get_best_buy_order()
        best_ask = matching_engine.get_best_sell_order()
        assert best_bid.order_id == 5002  # $152.00
        assert best_ask.order_id == 5003  # $148.00
        assert matching_engine.has_crossing_prices() is True

        # Step 6: Execute match: BUY 5002 (50 shares @ 152.00) vs SELL 5003 (30 shares @ 148.00)
        trade = matching_engine.execute_partial_match()
        assert trade is not None
        assert trade.buy_order_id == 5002
        assert trade.sell_order_id == 5003
        assert trade.executed_quantity == 30
        assert trade.execution_price_cents == 14800  # maker price = best ask
        assert trade.buy_remaining_quantity == 20
        assert trade.sell_remaining_quantity == 0

        # SELL 5003 is fully filled and removed; BUY 5002 remains with 20 shares
        assert matching_engine.ask_count() == 1  # only SELL 5004 remains
        assert matching_engine.bid_count() == 2  # BUY 5002 (rem 20) and BUY 5001 (rem 100)

        # Remaining best ask is SELL 5004 ($155.00), best bid is BUY 5002 ($152.00)
        # 152.00 < 155.00 -> prices no longer cross
        assert matching_engine.has_crossing_prices() is False
        assert matching_engine.execute_partial_match() is None


# ==============================================================================
# Boundary 7: OrderAdapter Smoke Tests
# ==============================================================================

class TestOrderAdapterSmokeTests:
    """Smoke tests for OrderAdapter dispatch modes, stats accumulation, and event emission.

    Verifies the adapter's core contract without duplicating the deep coverage in
    test_adapter.py or test_end_to_end_order_flow.py.
    """

    def test_adapter_match_mode_generates_trades_and_updates_stats(
        self, matching_engine: MatchingEngine
    ):
        """In 'match' mode a crossing pair produces a TradeResult and increments stats."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        buy = Order(
            order_id=9001,
            timestamp_ns=1_000_000,
            price=100.00,
            quantity=50,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        sell = Order(
            order_id=9002,
            timestamp_ns=1_001_000,
            price=100.00,
            quantity=50,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.SELL),
            order_type=int(OrderType.LIMIT),
        )

        trades1 = adapter.dispatch_raw_order(buy)
        assert len(trades1) == 0  # Resting BUY, no crossing yet
        assert adapter.stats.total_orders_dispatched == 1
        assert adapter.stats.non_crossing_orders == 1

        trades2 = adapter.dispatch_raw_order(sell)
        assert len(trades2) == 1
        trade = trades2[0]
        assert trade.buy_order_id == 9001
        assert trade.sell_order_id == 9002
        assert trade.executed_quantity == 50

        assert adapter.stats.total_orders_dispatched == 2
        assert adapter.stats.total_trades_generated == 1
        assert adapter.stats.total_volume_matched == 50
        assert adapter.stats.non_crossing_orders == 1  # Only the BUY was non-crossing

    def test_adapter_submit_mode_stores_orders_without_matching(
        self, matching_engine: MatchingEngine
    ):
        """In 'submit' mode, orders are submitted to the book without active matching."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="submit")

        buy = Order(
            order_id=9101,
            timestamp_ns=1_000_000,
            price=200.00,
            quantity=100,
            symbol_id=SYMBOLS["NVDA"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )
        sell = Order(
            order_id=9102,
            timestamp_ns=1_001_000,
            price=200.00,
            quantity=100,
            symbol_id=SYMBOLS["NVDA"],
            side=int(Side.SELL),
            order_type=int(OrderType.LIMIT),
        )

        adapter.dispatch_raw_order(buy)
        adapter.dispatch_raw_order(sell)

        # In submit mode, no active matching occurs; orders rest in both books
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 1
        assert adapter.stats.total_trades_generated == 0
        assert adapter.stats.total_volume_matched == 0
        assert adapter.stats.total_orders_dispatched == 2

    def test_adapter_cancel_order_type_does_not_crash_engine(
        self, matching_engine: MatchingEngine
    ):
        """CANCEL order type is recorded as unhandled; engine and stats remain consistent."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        cancel_order = Order(
            order_id=9201,
            timestamp_ns=2_000_000,
            price=150.00,
            quantity=10,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            order_type=int(OrderType.CANCEL),
        )

        trades = adapter.dispatch_raw_order(cancel_order)
        assert len(trades) == 0
        assert adapter.stats.unhandled_order_types == 1
        assert len(adapter.unhandled_orders) == 1
        # Engine is completely untouched
        assert matching_engine.bid_count() == 0
        assert matching_engine.ask_count() == 0

    def test_adapter_unrouted_symbol_recorded_truthfully(self):
        """Order with unknown symbol_id and no default engine is tracked in unrouted_orders."""
        engine_aapl = MatchingEngine()
        adapter = OrderAdapter(
            engine=None,
            symbol_engines={SYMBOLS["AAPL"]: engine_aapl},
            dispatch_mode="match",
        )

        nvda_order = Order(
            order_id=9301,
            timestamp_ns=3_000_000,
            price=500.00,
            quantity=20,
            symbol_id=SYMBOLS["NVDA"],  # Not registered
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )

        trades = adapter.dispatch_raw_order(nvda_order)
        assert len(trades) == 0
        assert adapter.stats.unrouted_symbols == 1
        assert len(adapter.unrouted_orders) == 1
        # AAPL engine is completely untouched
        assert engine_aapl.bid_count() == 0

    def test_adapter_clear_resets_all_state(self, matching_engine: MatchingEngine):
        """adapter.clear() resets stats, trades, events, and unhandled collections."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        # Dispatch a crossing pair to generate state
        buy = Order(9401, 1_000, 50.00, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        sell = Order(9402, 1_100, 50.00, 10, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(buy)
        adapter.dispatch_raw_order(sell)

        assert adapter.stats.total_trades_generated == 1
        assert len(adapter.trades) == 1
        assert len(adapter.execution_events) == 2

        adapter.clear()

        assert adapter.stats.total_trades_generated == 0
        assert adapter.stats.total_orders_dispatched == 0
        assert len(adapter.trades) == 0
        assert len(adapter.execution_events) == 0

    def test_adapter_context_manager_clears_on_exit(self, matching_engine: MatchingEngine):
        """OrderAdapter context manager clears internal state on __exit__."""
        with OrderAdapter(engine=matching_engine, dispatch_mode="match") as adapter:
            buy = Order(9501, 1_000, 75.00, 5, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
            adapter.dispatch_raw_order(buy)
            assert adapter.stats.total_orders_dispatched == 1

        # After context exit, stats should be reset
        assert adapter.stats.total_orders_dispatched == 0


# ==============================================================================
# Boundary 8: TradeExecutionEvent Introspection
# ==============================================================================

class TestTradeExecutionEventBoundary:
    """Verifies that TradeExecutionEvent instances correctly capture per-order telemetry.

    Each dispatched order produces a TradeExecutionEvent stored in
    adapter.execution_events, which records nanosecond latency and match outcomes.
    """

    def test_execution_event_emitted_per_dispatched_order(
        self, matching_engine: MatchingEngine
    ):
        """Every dispatched LIMIT order produces exactly one TradeExecutionEvent."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        orders = [
            Order(8001, 1_000, 100.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            Order(8002, 2_000, 100.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
        ]
        for o in orders:
            adapter.dispatch_raw_order(o)

        assert len(adapter.execution_events) == 2

    def test_non_crossing_event_has_matched_false_and_zero_volume(
        self, matching_engine: MatchingEngine
    ):
        """Non-crossing order dispatches emit TradeExecutionEvent with matched=False."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        buy = Order(8101, 1_000, 95.00, 100, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        sell = Order(8102, 2_000, 105.00, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))

        adapter.dispatch_raw_order(buy)
        adapter.dispatch_raw_order(sell)

        for event in adapter.execution_events:
            assert isinstance(event, TradeExecutionEvent)
            assert event.matched is False
            assert event.volume_matched == 0
            assert event.trades == []

    def test_crossing_event_has_matched_true_and_positive_volume(
        self, matching_engine: MatchingEngine
    ):
        """Crossing order dispatch emits TradeExecutionEvent with matched=True and volume>0."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        buy = Order(8201, 1_000, 100.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        sell = Order(8202, 2_000, 100.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))

        adapter.dispatch_raw_order(buy)
        adapter.dispatch_raw_order(sell)

        # BUY event (non-crossing)
        buy_event = adapter.execution_events[0]
        assert buy_event.matched is False
        assert buy_event.volume_matched == 0

        # SELL event (crossing: matches the resting BUY)
        sell_event = adapter.execution_events[1]
        assert sell_event.matched is True
        assert sell_event.volume_matched == 50
        assert len(sell_event.trades) == 1

    def test_execution_event_latency_ns_is_non_negative(
        self, matching_engine: MatchingEngine
    ):
        """TradeExecutionEvent.latency_ns is always >= 0 and latency_us == latency_ns / 1000."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        order = Order(8301, 1_000, 50.00, 25, SYMBOLS["TSLA"], int(Side.BUY), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(order)

        assert len(adapter.execution_events) == 1
        ev = adapter.execution_events[0]
        assert ev.latency_ns >= 0
        assert ev.exit_timestamp_ns >= ev.entry_timestamp_ns
        assert ev.latency_us == ev.latency_ns / 1_000.0

    def test_execution_event_order_fields_match_dispatched_order(
        self, matching_engine: MatchingEngine
    ):
        """TradeExecutionEvent captures order_id, symbol_id, side, price, quantity correctly."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        order = Order(8401, 9_999, 300.50, 75, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(order)

        ev = adapter.execution_events[0]
        assert ev.order_id == 8401
        assert ev.symbol_id == SYMBOLS["MSFT"]
        assert ev.side == int(Side.SELL)
        assert abs(ev.price - 300.50) < 1e-6
        assert ev.quantity == 75


# ==============================================================================
# Boundary 9: Ring Buffer Capacity & Saturation Boundaries
# ==============================================================================

class TestRingBufferCapacityBoundary:
    """Verifies ring buffer capacity limits, saturation behaviour, and metric counters."""

    def test_ring_buffer_capacity_tracking(self, isolated_ring_buffer: MmapRingBuffer):
        """available_to_read + available_to_write must always equal capacity."""
        capacity = isolated_ring_buffer.capacity
        assert isolated_ring_buffer.available_to_read() + isolated_ring_buffer.available_to_write() == capacity
        assert isolated_ring_buffer.is_empty() is True

        # Write a few orders and re-check
        for i in range(5):
            isolated_ring_buffer.write(
                order_id=i + 1,
                timestamp_ns=i * 1000,
                price=100.0,
                quantity=10,
                symbol_id=SYMBOLS["AAPL"],
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            )

        assert isolated_ring_buffer.available_to_read() == 5
        assert isolated_ring_buffer.available_to_write() == capacity - 5
        assert isolated_ring_buffer.is_empty() is False
        assert isolated_ring_buffer.is_full() is False

    def test_ring_buffer_write_returns_false_when_full(self):
        """write() returns False when buffer is full and overwrite_on_full=False."""
        fd, path = tempfile.mkstemp(prefix="chronos_cap_test_", suffix=".bin")
        os.close(fd)
        small_buf = MmapRingBuffer(filepath=path, capacity=4, slot_size=ORDER_SIZE, create=True)
        try:
            # Fill all 4 slots
            for i in range(4):
                ok = small_buf.write(
                    order_id=i + 1,
                    timestamp_ns=i,
                    price=10.0,
                    quantity=1,
                    symbol_id=SYMBOLS["AAPL"],
                    side=int(Side.BUY),
                    order_type=int(OrderType.LIMIT),
                )
                assert ok is True

            assert small_buf.is_full() is True

            # Next write without overwrite must fail
            ok = small_buf.write(
                order_id=99,
                timestamp_ns=9999,
                price=10.0,
                quantity=1,
                symbol_id=SYMBOLS["AAPL"],
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
                overwrite_on_full=False,
            )
            assert ok is False
            assert small_buf.available_to_read() == 4  # Still 4 orders, nothing lost
        finally:
            small_buf.close()
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def test_ring_buffer_overwrite_on_full_advances_read_tail(self):
        """overwrite_on_full=True advances read_tail and increments dropped metric."""
        fd, path = tempfile.mkstemp(prefix="chronos_overwrite_test_", suffix=".bin")
        os.close(fd)
        small_buf = MmapRingBuffer(filepath=path, capacity=4, slot_size=ORDER_SIZE, create=True)
        try:
            # Fill buffer
            for i in range(4):
                small_buf.write(i + 1, i, 10.0, 1, SYMBOLS["AAPL"], int(Side.BUY), 1)

            assert small_buf.is_full() is True
            dropped_before = small_buf.messages_dropped

            # Overwrite oldest with new order (order_id=99)
            ok = small_buf.write(
                order_id=99,
                timestamp_ns=9999,
                price=20.0,
                quantity=5,
                symbol_id=SYMBOLS["AAPL"],
                side=int(Side.SELL),
                order_type=int(OrderType.LIMIT),
                overwrite_on_full=True,
            )
            assert ok is True
            # Buffer still has capacity orders (oldest was dropped)
            assert small_buf.available_to_read() == 4
            # Dropped count incremented
            assert small_buf.messages_dropped == dropped_before + 1
        finally:
            small_buf.close()
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def test_read_raw_returns_none_on_empty_buffer(self, isolated_ring_buffer: MmapRingBuffer):
        """read_raw() returns None when the buffer has no unread slots."""
        assert isolated_ring_buffer.is_empty() is True
        result = isolated_ring_buffer.read_raw()
        assert result is None

    def test_batch_write_returns_zero_on_full_buffer(self):
        """write_batch() returns 0 when the buffer is full and overwrite is disabled."""
        fd, path = tempfile.mkstemp(prefix="chronos_batch_cap_test_", suffix=".bin")
        os.close(fd)
        small_buf = MmapRingBuffer(filepath=path, capacity=4, slot_size=ORDER_SIZE, create=True)
        try:
            fill = [(i + 1, i, 10.0, 1, SYMBOLS["AAPL"], int(Side.BUY), 1) for i in range(4)]
            small_buf.write_batch(fill)
            assert small_buf.is_full() is True

            extra = [(99, 9999, 10.0, 1, SYMBOLS["AAPL"], int(Side.BUY), 1)]
            written = small_buf.write_batch(extra, overwrite_on_full=False)
            assert written == 0
        finally:
            small_buf.close()
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


# ==============================================================================
# Boundary 10: Consumer-to-Adapter-to-Engine Coupled Pipeline
# ==============================================================================

class TestConsumerAdapterEngineCoupledPipeline:
    """Verifies that ZeroCopyConsumer, OrderAdapter, and MatchingEngine work as
    a coupled in-process pipeline without external processes or mocks."""

    def test_run_consumer_via_adapter_drains_buffer_and_produces_trades(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """adapter.run_consumer() drains all orders and matches crossing pairs."""
        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            engine=matching_engine,
            dispatch_mode="match",
        )

        # 3 orders: BUY @ 50.00, BUY @ 48.00, SELL @ 50.00
        # Only the first BUY and the SELL cross; second BUY does not
        orders = [
            (7001, 1_000, 50.00, 20, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            (7002, 2_000, 48.00, 20, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
            (7003, 3_000, 50.00, 20, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        assert isolated_ring_buffer.available_to_read() == 3

        consumer = ZeroCopyConsumer(isolated_ring_buffer, batch_size=10)
        final_stats = adapter.run_consumer(
            consumer=consumer,
            total_orders=3,
            print_progress=False,
        )

        assert isolated_ring_buffer.is_empty() is True
        assert final_stats.total_orders_read == 3
        assert final_stats.total_trades_generated == 1
        assert final_stats.total_volume_matched == 20

        # Only BUY 7001 at $50.00 matched with SELL 7003
        assert len(adapter.trades) == 1
        trade = adapter.trades[0]
        assert trade.buy_order_id == 7001
        assert trade.sell_order_id == 7003
        assert trade.executed_quantity == 20

        # BUY 7002 at $48.00 rests in bids; SELL 7003 fully matched
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 0
        assert matching_engine.get_best_buy_order().order_id == 7002

    def test_consumer_with_adapter_exit_when_empty(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """Consumer with exit_when_empty=True terminates cleanly on an already-drained buffer."""
        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            engine=matching_engine,
            dispatch_mode="match",
        )

        # Write one order and consume it immediately
        isolated_ring_buffer.write(
            order_id=7101,
            timestamp_ns=1_000,
            price=100.00,
            quantity=10,
            symbol_id=SYMBOLS["NVDA"],
            side=int(Side.BUY),
            order_type=int(OrderType.LIMIT),
        )

        consumer = ZeroCopyConsumer(isolated_ring_buffer, batch_size=5)
        final_stats = adapter.run_consumer(
            consumer=consumer,
            exit_when_empty=True,
            print_progress=False,
        )

        assert final_stats.total_orders_read == 1
        assert isolated_ring_buffer.is_empty() is True
        assert consumer.is_running is False

    def test_scenario_7_fifo_via_consumer_to_engine(
        self, isolated_ring_buffer: MmapRingBuffer, matching_engine: MatchingEngine
    ):
        """FIFO priority scenario (Scenario 7) executed via run_consumer produces correct fills."""
        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            engine=matching_engine,
            dispatch_mode="match",
        )
        scenario = SCENARIO_7_FIFO_SAME_PRICE

        # Load scenario orders into ring buffer via protocol encoding
        for sc_order in scenario.orders:
            isolated_ring_buffer.write_order(sc_order.to_protocol_order())

        consumer = ZeroCopyConsumer(isolated_ring_buffer, batch_size=10)
        adapter.run_consumer(consumer=consumer, total_orders=len(scenario.orders), print_progress=False)

        # Verify against expected scenario outcome
        assert len(adapter.trades) == len(scenario.expected.trades)
        total_matched = sum(t.executed_quantity for t in adapter.trades)
        assert total_matched == scenario.expected.total_matched_quantity

        # FIFO: Order 701 must fill first (40 shares), then Order 702 partially fills (10 shares)
        assert adapter.trades[0].buy_order_id == scenario.expected.trades[0].buy_order_id
        assert adapter.trades[1].buy_order_id == scenario.expected.trades[1].buy_order_id


# ==============================================================================
# Boundary 11: AdapterStats Accumulation Across Multiple Dispatch Calls
# ==============================================================================

class TestAdapterStatsAccumulation:
    """Verifies that AdapterStats accumulates correctly across sequential dispatch calls."""

    def test_stats_accumulate_across_multiple_crossing_orders(
        self, matching_engine: MatchingEngine
    ):
        """Multiple crossing pairs accumulate correctly in AdapterStats."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")
        sym = SYMBOLS["AAPL"]

        # Submit 3 crossing pairs
        pairs = [
            (Order(1, 100, 10.00, 10, sym, int(Side.BUY), int(OrderType.LIMIT)),
             Order(2, 200, 10.00, 10, sym, int(Side.SELL), int(OrderType.LIMIT))),
            (Order(3, 300, 20.00, 25, sym, int(Side.BUY), int(OrderType.LIMIT)),
             Order(4, 400, 20.00, 25, sym, int(Side.SELL), int(OrderType.LIMIT))),
            (Order(5, 500, 30.00, 15, sym, int(Side.BUY), int(OrderType.LIMIT)),
             Order(6, 600, 30.00, 15, sym, int(Side.SELL), int(OrderType.LIMIT))),
        ]

        for buy, sell in pairs:
            adapter.dispatch_raw_order(buy)
            adapter.dispatch_raw_order(sell)

        s = adapter.stats
        assert s.total_orders_dispatched == 6
        assert s.total_trades_generated == 3
        assert s.total_volume_matched == 50  # 10 + 25 + 15
        assert s.non_crossing_orders == 3    # Each BUY was non-crossing on submission

    def test_stats_latency_samples_non_negative(self, matching_engine: MatchingEngine):
        """All recorded execution latency samples in AdapterStats are non-negative."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")
        sym = SYMBOLS["NVDA"]

        for i in range(5):
            order = Order(
                order_id=100 + i,
                timestamp_ns=i * 1_000,
                price=50.0 + i,
                quantity=10,
                symbol_id=sym,
                side=int(Side.BUY),
                order_type=int(OrderType.LIMIT),
            )
            adapter.dispatch_raw_order(order)

        assert adapter.stats.latency_samples_count == 5
        for lat in adapter.stats.execution_latencies_ns:
            assert lat >= 0
        assert adapter.stats.min_execution_latency_ns >= 0
        assert adapter.stats.max_execution_latency_ns >= adapter.stats.min_execution_latency_ns

    def test_stats_avg_latency_property_returns_float(self, matching_engine: MatchingEngine):
        """avg_execution_latency_ns returns 0.0 on empty stats and a float once sampled."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        # Empty: should return 0.0
        assert adapter.stats.avg_execution_latency_ns == 0.0
        assert isinstance(adapter.stats.avg_execution_latency_ns, float)

        order = Order(1, 100, 50.00, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(order)

        # After dispatch: float
        assert isinstance(adapter.stats.avg_execution_latency_ns, float)

    def test_stats_percentile_returns_zero_on_empty(self):
        """percentile_latency_ns returns 0.0 when no samples have been recorded."""
        stats = AdapterStats()
        assert stats.percentile_latency_ns(50.0) == 0.0
        assert stats.percentile_latency_ns(99.0) == 0.0
        assert stats.p50_execution_latency_ns == 0.0
        assert stats.p99_execution_latency_ns == 0.0

    def test_stats_get_trade_latency_snapshot_matches_tracker(
        self, matching_engine: MatchingEngine
    ):
        """stats.get_trade_latency_snapshot() reflects the same values as the stats fields."""
        adapter = OrderAdapter(engine=matching_engine, dispatch_mode="match")

        buy = Order(1, 100, 100.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        sell = Order(2, 200, 100.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(buy)
        adapter.dispatch_raw_order(sell)

        snap = adapter.stats.get_trade_latency_snapshot()
        assert snap.trade_count == adapter.stats.total_trades_generated
        assert snap.min_latency_ns == adapter.stats.min_execution_latency_ns
        assert snap.max_latency_ns == adapter.stats.max_execution_latency_ns


# ==============================================================================
# Boundary 12: Pipeline Component Interface Smoke Tests
# ==============================================================================

class TestPipelineComponentInterfaceSmoke:
    """Lightweight smoke tests verifying that core pipeline component interfaces
    are present and callable as expected. These protect against interface regressions
    and serve as a living specification of the Day 6 integration contract.
    """

    def test_matching_engine_is_ready_and_has_expected_interface(self):
        """MatchingEngine exposes all required integration-layer APIs."""
        engine = MatchingEngine()
        assert engine.is_ready() is True
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.order_count() == 0
        assert engine.has_crossing_prices() is False
        assert engine.get_best_buy_order() is None
        assert engine.get_best_sell_order() is None
        # On an empty book get_best_bid/ask_price return None or 0.0 depending on engine version
        bid_price = engine.get_best_bid_price()
        ask_price = engine.get_best_ask_price()
        assert bid_price is None or bid_price == 0.0
        assert ask_price is None or ask_price == 0.0
        spread = engine.get_spread()
        assert spread is None or spread == 0.0
        assert engine.get_prioritized_bids() == []
        assert engine.get_prioritized_asks() == []
        engine.clear()

    def test_ring_buffer_exposes_required_read_write_interface(
        self, isolated_ring_buffer: MmapRingBuffer
    ):
        """MmapRingBuffer exposes all integration-layer read/write APIs."""
        assert hasattr(isolated_ring_buffer, "write")
        assert hasattr(isolated_ring_buffer, "write_order")
        assert hasattr(isolated_ring_buffer, "write_batch")
        assert hasattr(isolated_ring_buffer, "read_raw")
        assert hasattr(isolated_ring_buffer, "read_order")
        assert hasattr(isolated_ring_buffer, "read_batch_raw")
        assert hasattr(isolated_ring_buffer, "read_batch_orders")
        assert hasattr(isolated_ring_buffer, "available_to_read")
        assert hasattr(isolated_ring_buffer, "available_to_write")
        assert hasattr(isolated_ring_buffer, "is_empty")
        assert hasattr(isolated_ring_buffer, "is_full")
        assert hasattr(isolated_ring_buffer, "close")
        assert isolated_ring_buffer.slot_size == ORDER_SIZE
        assert isolated_ring_buffer.capacity > 0

    def test_consumer_stats_has_expected_fields(self):
        """ConsumerStats dataclass has all required tracking fields."""
        stats = ConsumerStats()
        assert hasattr(stats, "total_orders_read")
        assert hasattr(stats, "elapsed_time")
        assert hasattr(stats, "avg_rate")
        assert hasattr(stats, "min_latency_us")
        assert hasattr(stats, "max_latency_us")
        assert hasattr(stats, "avg_latency_us")
        assert stats.total_orders_read == 0

    def test_adapter_stats_has_expected_fields(self):
        """AdapterStats dataclass has all required tracking fields."""
        stats = AdapterStats()
        assert hasattr(stats, "total_orders_read")
        assert hasattr(stats, "total_orders_dispatched")
        assert hasattr(stats, "total_trades_generated")
        assert hasattr(stats, "total_volume_matched")
        assert hasattr(stats, "non_crossing_orders")
        assert hasattr(stats, "unhandled_order_types")
        assert hasattr(stats, "unrouted_symbols")
        assert hasattr(stats, "execution_latencies_ns")
        assert hasattr(stats, "avg_execution_latency_ns")
        assert hasattr(stats, "percentile_latency_ns")

    def test_zero_copy_consumer_interface_contract(
        self, isolated_ring_buffer: MmapRingBuffer
    ):
        """ZeroCopyConsumer exposes the minimum interface required by the pipeline."""
        consumer = ZeroCopyConsumer(isolated_ring_buffer, batch_size=100)
        assert hasattr(consumer, "run")
        assert hasattr(consumer, "drain_available")
        assert hasattr(consumer, "stop")
        assert hasattr(consumer, "is_running")
        assert hasattr(consumer, "stats")
        assert consumer.is_running is False

    def test_order_adapter_symbol_routing_interface(self, matching_engine: MatchingEngine):
        """OrderAdapter.resolve_engine correctly maps symbol IDs to engines."""
        engine_aapl = MatchingEngine()
        engine_nvda = MatchingEngine()

        adapter = OrderAdapter(
            symbol_engines={
                SYMBOLS["AAPL"]: engine_aapl,
                SYMBOLS["NVDA"]: engine_nvda,
            },
            dispatch_mode="match",
        )

        assert adapter.resolve_engine(SYMBOLS["AAPL"]) is engine_aapl
        assert adapter.resolve_engine(SYMBOLS["NVDA"]) is engine_nvda
        assert adapter.resolve_engine(SYMBOLS["TSLA"]) is None

    def test_price_to_cents_converts_precisely(self):
        """price_to_cents produces correct integer cent conversions without float drift."""
        assert price_to_cents(100.00) == 10000
        assert price_to_cents(100.01) == 10001
        assert price_to_cents(99.99) == 9999
        assert price_to_cents(0.01) == 1
        assert price_to_cents(9999.99) == 999999
        assert price_to_cents(225.50) == 22550
