"""ChronosMatch Pipeline Integration Test Foundation (Working Day 6).

Builds an executable integration-test foundation linking:
1. Binary Order Protocol (<QQdIHBB struct packing/unpacking)
2. Zero-Copy SPSC Memory-Mapped Ring Buffer (single, batch, and sequential transfers)
3. Ring Buffer Consumer Component (ZeroCopyConsumer draining real buffer)
4. Binary Decoded Values to Matching Engine Order Adaptation Boundary
5. Day 5 Reusable Deterministic Trading Scenarios (protocol compatibility and engine matching)
6. Integrated Multi-Step Pipeline Flow across existing real boundaries

Prepares the test foundation for Day 7 end-to-end order-flow testing.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Generator, List, Tuple

import pytest

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
