"""Validation tests for ChronosMatch Reusable Trading Scenarios.

Verifies:
1. All expected scenarios exist and have unique, non-empty identifiers.
2. Order IDs are valid and unique within each scenario.
3. Side values match project protocol (Side.BUY == 1, Side.SELL == 2).
4. Order prices are positive and correctly converted to integer cents.
5. Order quantities are strictly positive integers.
6. Expected crossing-price results match logical and engine evaluation.
7. Expected partial-fill and full-fill arithmetic is exact.
8. Non-crossing scenarios expect zero executed quantity.
9. FIFO time priority and price priority match engine inspection.
10. Binary protocol compatibility (32-byte struct pack/unpack roundtrip).
11. Scenario immutability and resistance to shared-state mutation.
"""

from __future__ import annotations

import pytest

from chronos.matching_engine import MatchingEngine, price_to_cents
from chronos.protocol import ORDER_SIZE, Order, Side, unpack_order_raw
from tests.trading_scenarios import (
    ALL_SCENARIOS,
    SCENARIO_1_EXACT_MATCH,
    SCENARIO_2_CROSSED_MARKET,
    SCENARIO_3_NO_TRADE,
    SCENARIO_4_PARTIAL_FILL_BUY_LARGER,
    SCENARIO_5_PARTIAL_FILL_SELL_LARGER,
    SCENARIO_6_EXACT_FULL_FILL,
    SCENARIO_7_FIFO_SAME_PRICE,
    SCENARIO_8_PRICE_PRIORITY_BUY,
    SCENARIO_9_PRICE_PRIORITY_SELL,
    SCENARIO_10_EMPTY_ORDER_BOOK,
    SCENARIOS_BY_NAME,
    ExpectedOutcome,
    ExpectedTrade,
    ScenarioOrder,
    TradingScenario,
    get_all_scenarios,
    get_scenario,
)


# ==============================================================================
# 1. Existence, Registry, and Metadata Tests
# ==============================================================================

class TestScenarioRegistry:
    """Verify all 10 expected scenarios are registered and accessible."""

    EXPECTED_NAMES = [
        "scenario_1_exact_match",
        "scenario_2_crossed_market",
        "scenario_3_no_trade_wide_spread",
        "scenario_4_partial_fill_buy_larger",
        "scenario_5_partial_fill_sell_larger",
        "scenario_6_exact_full_fill",
        "scenario_7_fifo_same_price",
        "scenario_8_price_priority_buy",
        "scenario_9_price_priority_sell",
        "scenario_10_empty_order_book",
    ]

    def test_all_ten_scenarios_exist(self):
        """Verify exactly 10 trading scenarios are defined."""
        assert len(ALL_SCENARIOS) == 10
        assert len(SCENARIOS_BY_NAME) == 10

    @pytest.mark.parametrize("name", EXPECTED_NAMES)
    def test_scenario_name_present_in_registry(self, name: str):
        """Verify each expected scenario is indexed by its canonical name."""
        assert name in SCENARIOS_BY_NAME
        scenario = get_scenario(name)
        assert scenario.name == name

    def test_scenario_names_and_descriptions_are_nonempty(self):
        """Verify every scenario has a non-empty name and description."""
        for s in ALL_SCENARIOS:
            assert isinstance(s.name, str) and s.name.strip() != ""
            assert isinstance(s.description, str) and s.description.strip() != ""

    def test_get_all_scenarios_returns_copies(self):
        """Verify get_all_scenarios returns independent instances."""
        scenarios1 = get_all_scenarios()
        scenarios2 = get_all_scenarios()
        assert len(scenarios1) == 10
        assert scenarios1 is not scenarios2

    def test_get_scenario_raises_on_unknown(self):
        """Verify get_scenario raises KeyError on invalid names."""
        with pytest.raises(KeyError, match="Unknown scenario"):
            get_scenario("non_existent_scenario")


# ==============================================================================
# 2. Order Field Validation Tests
# ==============================================================================

class TestOrderFieldsValidation:
    """Verify order structure, fields, protocol sides, prices, and quantities."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_order_ids_are_unique_and_positive(self, scenario: TradingScenario):
        """Verify order IDs within each scenario are unique positive integers."""
        order_ids = [o.order_id for o in scenario.orders]
        assert len(order_ids) == len(set(order_ids)), f"Duplicate order ID in {scenario.name}"
        for oid in order_ids:
            assert isinstance(oid, int) and oid > 0

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_side_matches_project_protocol(self, scenario: TradingScenario):
        """Verify BUY/SELL sides strictly match protocol values (1=BUY, 2=SELL)."""
        for o in scenario.orders:
            assert o.side in (int(Side.BUY), int(Side.SELL))
            if o.side == int(Side.BUY):
                assert o.side_str == "BUY"
            else:
                assert o.side_str == "SELL"

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_order_prices_are_strictly_positive(self, scenario: TradingScenario):
        """Verify all order prices are positive numbers with matching cent representations."""
        for o in scenario.orders:
            assert isinstance(o.price, (int, float))
            assert o.price > 0.0
            assert o.price_cents > 0
            assert o.price_cents == price_to_cents(o.price)

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_order_quantities_are_positive_integers(self, scenario: TradingScenario):
        """Verify order quantities are positive integers (> 0)."""
        for o in scenario.orders:
            assert isinstance(o.quantity, int)
            assert o.quantity > 0

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_order_timestamps_are_deterministic(self, scenario: TradingScenario):
        """Verify timestamps are strictly monotonic or deterministic in arrival sequence."""
        if len(scenario.orders) > 1:
            timestamps = [o.timestamp_ns for o in scenario.orders]
            # Timestamps in arrival sequence must be non-decreasing
            for i in range(len(timestamps) - 1):
                assert timestamps[i] <= timestamps[i + 1]


# ==============================================================================
# 3. Binary Protocol Compatibility Tests
# ==============================================================================

class TestBinaryProtocolCompatibility:
    """Verify that scenario orders are fully compatible with Week 1 binary struct."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_order_packs_to_32_bytes(self, scenario: TradingScenario):
        """Verify all scenario orders serialize to exactly 32 bytes."""
        for o in scenario.orders:
            packed = o.pack()
            assert isinstance(packed, bytes)
            assert len(packed) == ORDER_SIZE == 32

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_order_binary_roundtrip(self, scenario: TradingScenario):
        """Verify binary serialization unpacks into identical field values."""
        for o in scenario.orders:
            packed = o.pack()
            unpacked = Order.unpack(packed)
            assert unpacked.order_id == o.order_id
            assert unpacked.timestamp_ns == o.timestamp_ns
            assert abs(unpacked.price - o.price) < 1e-6
            assert unpacked.quantity == o.quantity
            assert unpacked.symbol_id == o.symbol_id
            assert unpacked.side == o.side
            assert unpacked.order_type == o.order_type

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_unpack_order_raw_compatibility(self, scenario: TradingScenario):
        """Verify unpack_order_raw extracts matching fields from packed buffer."""
        for o in scenario.orders:
            packed = o.pack()
            raw = unpack_order_raw(packed)
            assert raw[0] == o.order_id
            assert raw[1] == o.timestamp_ns
            assert abs(raw[2] - o.price) < 1e-6
            assert raw[3] == o.quantity
            assert raw[4] == o.symbol_id
            assert raw[5] == o.side
            assert raw[6] == o.order_type


# ==============================================================================
# 4. Crossing Price and Matching Expectations Validation
# ==============================================================================

class TestCrossingAndMatchingExpectations:
    """Validate logical crossing conditions and engine integration."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_logical_crossing_matches_expected(self, scenario: TradingScenario):
        """Verify logical best BUY >= best SELL matches expected has_crossing."""
        buys = scenario.get_buy_orders()
        sells = scenario.get_sell_orders()

        if not buys or not sells:
            assert scenario.expected.has_crossing is False
        else:
            max_buy_cents = max(o.price_cents for o in buys)
            min_sell_cents = min(o.price_cents for o in sells)
            computed_crossing = max_buy_cents >= min_sell_cents
            assert computed_crossing == scenario.expected.has_crossing

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_engine_crossing_detection_matches_scenario(self, scenario: TradingScenario):
        """Verify Cython MatchingEngine produces identical crossing detection."""
        engine = MatchingEngine()
        scenario.load_into_engine(engine)
        assert engine.has_crossing_prices() == scenario.expected.has_crossing

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_engine_best_orders_match_expected(self, scenario: TradingScenario):
        """Verify engine best buy/sell orders match scenario expectations."""
        engine = MatchingEngine()
        scenario.load_into_engine(engine)

        best_buy = engine.get_best_buy_order()
        expected_best_buy_id = scenario.expected.best_buy_id
        if expected_best_buy_id is None:
            assert best_buy is None
        else:
            assert best_buy is not None
            assert best_buy.order_id == expected_best_buy_id

        best_sell = engine.get_best_sell_order()
        expected_best_sell_id = scenario.expected.best_sell_id
        if expected_best_sell_id is None:
            assert best_sell is None
        else:
            assert best_sell is not None
            assert best_sell.order_id == expected_best_sell_id

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_engine_prioritized_sequences_match_expected(self, scenario: TradingScenario):
        """Verify engine prioritized bids and asks match scenario sequences."""
        engine = MatchingEngine()
        scenario.load_into_engine(engine)

        engine_buy_ids = tuple(o.order_id for o in engine.get_prioritized_bids())
        assert engine_buy_ids == scenario.expected.prioritized_buy_ids

        engine_sell_ids = tuple(o.order_id for o in engine.get_prioritized_asks())
        assert engine_sell_ids == scenario.expected.prioritized_sell_ids


# ==============================================================================
# 5. Arithmetic and Trade Conservation Tests
# ==============================================================================

class TestQuantityConservationAndArithmetic:
    """Verify that quantity conservation (matched + remaining == initial) holds."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_quantity_conservation_for_all_orders(self, scenario: TradingScenario):
        """Verify initial quantity equals executed quantity plus remaining quantity for all orders."""
        order_map = {o.order_id: o.quantity for o in scenario.orders}

        # Calculate total executed quantity per order from expected trades
        executed_per_order = {o.order_id: 0 for o in scenario.orders}
        for trade in scenario.expected.trades:
            executed_per_order[trade.buy_order_id] += trade.trade_quantity
            executed_per_order[trade.sell_order_id] += trade.trade_quantity

        for order_id, initial_qty in order_map.items():
            remaining_qty = scenario.expected.remaining_quantities[order_id]
            executed_qty = executed_per_order[order_id]
            assert initial_qty == executed_qty + remaining_qty, (
                f"Conservation violated in {scenario.name} for order {order_id}: "
                f"initial={initial_qty}, executed={executed_qty}, remaining={remaining_qty}"
            )

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_total_matched_quantity_matches_sum_of_trades(self, scenario: TradingScenario):
        """Verify total_matched_quantity equals the sum of trade quantities."""
        sum_trades = sum(t.trade_quantity for t in scenario.expected.trades)
        assert sum_trades == scenario.expected.total_matched_quantity


# ==============================================================================
# 6. Specific Scenario Tests (Scenarios 1 through 10)
# ==============================================================================

class TestSpecificScenarios:
    """In-depth verification for each individual scenario requirement."""

    def test_scenario_1_exact_match(self):
        """Scenario 1: Exact price match with equal quantities (50 each)."""
        s = SCENARIO_1_EXACT_MATCH
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 50
        assert s.expected.remaining_quantities == {101: 0, 102: 0}
        assert len(s.expected.trades) == 1
        t = s.expected.trades[0]
        assert t.buy_order_id == 101 and t.sell_order_id == 102
        assert t.execution_price == 100.00 and t.trade_quantity == 50

    def test_scenario_2_crossed_market(self):
        """Scenario 2: BUY (105.00) higher than SELL (100.00) crosses."""
        s = SCENARIO_2_CROSSED_MARKET
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 100
        assert s.expected.remaining_quantities == {201: 0, 202: 0}

    def test_scenario_3_no_trade_wide_spread(self):
        """Scenario 3: BUY (95.00) below SELL (105.00) results in zero trades."""
        s = SCENARIO_3_NO_TRADE
        assert s.expected.has_crossing is False
        assert s.expected.total_matched_quantity == 0
        assert len(s.expected.trades) == 0
        assert s.expected.remaining_quantities == {301: 100, 302: 100}

    def test_scenario_4_partial_fill_buy_larger(self):
        """Scenario 4: BUY (qty 100) partially fills against SELL (qty 40); 60 remains."""
        s = SCENARIO_4_PARTIAL_FILL_BUY_LARGER
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 40
        assert s.expected.remaining_quantities[401] == 60
        assert s.expected.remaining_quantities[402] == 0
        assert len(s.expected.trades) == 1
        assert s.expected.trades[0].trade_quantity == 40

    def test_scenario_5_partial_fill_sell_larger(self):
        """Scenario 5: SELL (qty 80) partially fills against BUY (qty 30); 50 remains."""
        s = SCENARIO_5_PARTIAL_FILL_SELL_LARGER
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 30
        assert s.expected.remaining_quantities[501] == 0
        assert s.expected.remaining_quantities[502] == 50
        assert len(s.expected.trades) == 1
        assert s.expected.trades[0].trade_quantity == 30

    def test_scenario_6_exact_full_fill(self):
        """Scenario 6: Exact full fill with identical quantity 75 on both sides."""
        s = SCENARIO_6_EXACT_FULL_FILL
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 75
        assert s.expected.remaining_quantities == {601: 0, 602: 0}

    def test_scenario_7_fifo_same_price(self):
        """Scenario 7: Equal price BUYs: earlier 701 is filled before later 702."""
        s = SCENARIO_7_FIFO_SAME_PRICE
        assert s.expected.has_crossing is True
        assert s.expected.prioritized_buy_ids == (701, 702)
        assert s.expected.best_buy_id == 701
        # Order 701 (qty 40) filled fully; Order 702 (qty 60) filled 10, remaining 50
        assert s.expected.remaining_quantities[701] == 0
        assert s.expected.remaining_quantities[702] == 50
        assert s.expected.remaining_quantities[703] == 0
        assert len(s.expected.trades) == 2
        assert s.expected.trades[0].buy_order_id == 701
        assert s.expected.trades[0].trade_quantity == 40
        assert s.expected.trades[1].buy_order_id == 702
        assert s.expected.trades[1].trade_quantity == 10

    def test_scenario_8_price_priority_buy(self):
        """Scenario 8: Higher BUY price (802 @ 102.00) takes priority over earlier 801 @ 100.00."""
        s = SCENARIO_8_PRICE_PRIORITY_BUY
        assert s.expected.has_crossing is True
        assert s.expected.prioritized_buy_ids == (802, 801)
        assert s.expected.best_buy_id == 802
        # Order 802 matches first: fills 30. SELL 803 has 10 left, matched with 801.
        assert s.expected.remaining_quantities[802] == 0
        assert s.expected.remaining_quantities[801] == 40
        assert s.expected.remaining_quantities[803] == 0
        assert len(s.expected.trades) == 2
        assert s.expected.trades[0].buy_order_id == 802
        assert s.expected.trades[0].trade_quantity == 30
        assert s.expected.trades[1].buy_order_id == 801
        assert s.expected.trades[1].trade_quantity == 10

    def test_scenario_9_price_priority_sell(self):
        """Scenario 9: Lower SELL price (902 @ 200.00) takes priority over earlier 901 @ 205.00."""
        s = SCENARIO_9_PRICE_PRIORITY_SELL
        assert s.expected.has_crossing is True
        assert s.expected.prioritized_sell_ids == (902, 901)
        assert s.expected.best_sell_id == 902
        # Order 902 matches first: fills 25. BUY 903 has 25 left, matched with 901.
        assert s.expected.remaining_quantities[902] == 0
        assert s.expected.remaining_quantities[901] == 15
        assert s.expected.remaining_quantities[903] == 0
        assert len(s.expected.trades) == 2
        assert s.expected.trades[0].sell_order_id == 902
        assert s.expected.trades[0].trade_quantity == 25
        assert s.expected.trades[1].sell_order_id == 901
        assert s.expected.trades[1].trade_quantity == 25

    def test_scenario_10_empty_order_book(self):
        """Scenario 10: Empty order book has no crossing, no best orders, no matches."""
        s = SCENARIO_10_EMPTY_ORDER_BOOK
        assert s.expected.has_crossing is False
        assert s.expected.best_buy_id is None
        assert s.expected.best_sell_id is None
        assert s.expected.prioritized_buy_ids == ()
        assert s.expected.prioritized_sell_ids == ()
        assert s.expected.total_matched_quantity == 0
        assert s.expected.remaining_quantities == {}
        assert len(s.expected.trades) == 0


# ==============================================================================
# 7. Immutability and State Isolation Tests
# ==============================================================================

class TestScenarioImmutability:
    """Verify scenarios cannot be accidentally mutated across test runs."""

    def test_scenario_order_is_frozen(self):
        """Verify ScenarioOrder fields cannot be modified."""
        order = SCENARIO_1_EXACT_MATCH.orders[0]
        with pytest.raises(Exception):
            order.price = 999.0  # Frozen dataclass raises FrozenInstanceError

    def test_scenario_orders_list_copy(self):
        """Verify get_orders returns a list copy that does not alter scenario."""
        s = get_scenario("scenario_1_exact_match")
        orders_list = s.get_orders()
        orders_list.clear()
        assert len(s.orders) == 2

    def test_scenario_copy_is_isolated(self):
        """Verify deep copy isolates remaining_quantities dictionary."""
        s = get_scenario("scenario_4_partial_fill_buy_larger")
        copy_s = s.copy()
        copy_s.expected.remaining_quantities[401] = 999
        assert s.expected.remaining_quantities[401] == 60
        assert SCENARIO_4_PARTIAL_FILL_BUY_LARGER.expected.remaining_quantities[401] == 60

    def test_repeated_engine_load_is_idempotent(self):
        """Verify loading into different engine instances yields identical state."""
        s = get_scenario("scenario_7_fifo_same_price")
        engine1 = MatchingEngine()
        engine2 = MatchingEngine()

        s.load_into_engine(engine1)
        s.load_into_engine(engine2)

        assert engine1.bid_count() == engine2.bid_count() == 2
        assert engine1.ask_count() == engine2.ask_count() == 1
        assert engine1.get_best_buy_order().order_id == engine2.get_best_buy_order().order_id == 701
        assert engine1.has_crossing_prices() is engine2.has_crossing_prices() is True
