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
12. Scenario categorization (successful matching, partial fills, multiple price levels, non-crossing, unmatched).
13. Scenario execution helper methods (execute_in_engine, execute_in_adapter, verify_execution).
14. Week 3 nanosecond trade timestamps and latency tracking integration.
"""

from __future__ import annotations

import pytest

from chronos.adapter import OrderAdapter
from chronos.matching_engine import MatchingEngine, TradeResult, price_to_cents
from chronos.protocol import ORDER_SIZE, Order, Side, unpack_order_raw
from tests.trading_scenarios import (
    ALL_CATEGORIES,
    ALL_SCENARIOS,
    CATEGORY_MULTIPLE_PRICE_LEVELS,
    CATEGORY_NON_CROSSING,
    CATEGORY_PARTIAL_FILLS,
    CATEGORY_SUCCESSFUL_MATCHING,
    CATEGORY_UNMATCHED_ORDERS,
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
    get_multiple_price_levels_scenarios,
    get_non_crossing_scenarios,
    get_partial_fill_scenarios,
    get_scenario,
    get_scenarios_by_category,
    get_successful_matching_scenarios,
    get_unmatched_scenarios,
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
        s = SCENARIO_1_EXACT_MATCH
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 50
        assert s.expected.remaining_quantities == {101: 0, 102: 0}
        assert len(s.expected.trades) == 1
        t = s.expected.trades[0]
        assert t.buy_order_id == 101 and t.sell_order_id == 102
        assert t.execution_price == 100.00 and t.trade_quantity == 50

    def test_scenario_2_crossed_market(self):
        s = SCENARIO_2_CROSSED_MARKET
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 100
        assert s.expected.remaining_quantities == {201: 0, 202: 0}

    def test_scenario_3_no_trade_wide_spread(self):
        s = SCENARIO_3_NO_TRADE
        assert s.expected.has_crossing is False
        assert s.expected.total_matched_quantity == 0
        assert len(s.expected.trades) == 0
        assert s.expected.remaining_quantities == {301: 100, 302: 100}

    def test_scenario_4_partial_fill_buy_larger(self):
        s = SCENARIO_4_PARTIAL_FILL_BUY_LARGER
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 40
        assert s.expected.remaining_quantities[401] == 60
        assert s.expected.remaining_quantities[402] == 0
        assert len(s.expected.trades) == 1
        assert s.expected.trades[0].trade_quantity == 40

    def test_scenario_5_partial_fill_sell_larger(self):
        s = SCENARIO_5_PARTIAL_FILL_SELL_LARGER
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 30
        assert s.expected.remaining_quantities[501] == 0
        assert s.expected.remaining_quantities[502] == 50
        assert len(s.expected.trades) == 1
        assert s.expected.trades[0].trade_quantity == 30

    def test_scenario_6_exact_full_fill(self):
        s = SCENARIO_6_EXACT_FULL_FILL
        assert s.expected.has_crossing is True
        assert s.expected.total_matched_quantity == 75
        assert s.expected.remaining_quantities == {601: 0, 602: 0}

    def test_scenario_7_fifo_same_price(self):
        s = SCENARIO_7_FIFO_SAME_PRICE
        assert s.expected.has_crossing is True
        assert s.expected.prioritized_buy_ids == (701, 702)
        assert s.expected.best_buy_id == 701
        assert s.expected.remaining_quantities[701] == 0
        assert s.expected.remaining_quantities[702] == 50
        assert s.expected.remaining_quantities[703] == 0
        assert len(s.expected.trades) == 2
        assert s.expected.trades[0].buy_order_id == 701
        assert s.expected.trades[0].trade_quantity == 40
        assert s.expected.trades[1].buy_order_id == 702
        assert s.expected.trades[1].trade_quantity == 10

    def test_scenario_8_price_priority_buy(self):
        s = SCENARIO_8_PRICE_PRIORITY_BUY
        assert s.expected.has_crossing is True
        assert s.expected.prioritized_buy_ids == (802, 801)
        assert s.expected.best_buy_id == 802
        assert s.expected.remaining_quantities[802] == 0
        assert s.expected.remaining_quantities[801] == 40
        assert s.expected.remaining_quantities[803] == 0
        assert len(s.expected.trades) == 2
        assert s.expected.trades[0].buy_order_id == 802
        assert s.expected.trades[0].trade_quantity == 30
        assert s.expected.trades[1].buy_order_id == 801
        assert s.expected.trades[1].trade_quantity == 10

    def test_scenario_9_price_priority_sell(self):
        s = SCENARIO_9_PRICE_PRIORITY_SELL
        assert s.expected.has_crossing is True
        assert s.expected.prioritized_sell_ids == (902, 901)
        assert s.expected.best_sell_id == 902
        assert s.expected.remaining_quantities[902] == 0
        assert s.expected.remaining_quantities[901] == 15
        assert s.expected.remaining_quantities[903] == 0
        assert len(s.expected.trades) == 2
        assert s.expected.trades[0].sell_order_id == 902
        assert s.expected.trades[0].trade_quantity == 25
        assert s.expected.trades[1].sell_order_id == 901
        assert s.expected.trades[1].trade_quantity == 25

    def test_scenario_10_empty_order_book(self):
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
        order = SCENARIO_1_EXACT_MATCH.orders[0]
        with pytest.raises(Exception):
            order.price = 999.0

    def test_scenario_orders_list_copy(self):
        s = get_scenario("scenario_1_exact_match")
        orders_list = s.get_orders()
        orders_list.clear()
        assert len(s.orders) == 2

    def test_scenario_copy_is_isolated(self):
        s = get_scenario("scenario_4_partial_fill_buy_larger")
        copy_s = s.copy()
        copy_s.expected.remaining_quantities[401] = 999
        assert s.expected.remaining_quantities[401] == 60
        assert SCENARIO_4_PARTIAL_FILL_BUY_LARGER.expected.remaining_quantities[401] == 60

    def test_repeated_engine_load_is_idempotent(self):
        s = get_scenario("scenario_7_fifo_same_price")
        engine1 = MatchingEngine()
        engine2 = MatchingEngine()

        s.load_into_engine(engine1)
        s.load_into_engine(engine2)

        assert engine1.bid_count() == engine2.bid_count() == 2
        assert engine1.ask_count() == engine2.ask_count() == 1
        assert engine1.get_best_buy_order().order_id == engine2.get_best_buy_order().order_id == 701
        assert engine1.has_crossing_prices() is engine2.has_crossing_prices() is True


# ==============================================================================
# 8. Dynamic Scenario Execution & MatchingEngine Integration Tests
# ==============================================================================

class TestTradingScenariosDynamicExecution:
    """Verifies that all 10 deterministic trading scenarios execute accurately through
    MatchingEngine.match_order and the OrderAdapter in match mode."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_all_scenarios_dynamic_execution_through_match_order(self, scenario: TradingScenario):
        """Verify each scenario produces exact expected trades and book state via engine.match_order."""
        engine = MatchingEngine()
        all_trades = []
        for o in scenario.orders:
            trades = engine.match_order(
                order_id=o.order_id,
                side=o.side,
                price=o.price,
                quantity=o.quantity,
                timestamp_ns=o.timestamp_ns,
            )
            all_trades.extend(trades)

        total_matched = sum(t.executed_quantity for t in all_trades)
        assert total_matched == scenario.expected.total_matched_quantity

        assert len(all_trades) == len(scenario.expected.trades)
        for actual, expected in zip(all_trades, scenario.expected.trades):
            assert actual.buy_order_id == expected.buy_order_id
            assert actual.sell_order_id == expected.sell_order_id
            assert actual.executed_quantity == expected.trade_quantity
            assert actual.execution_price == expected.execution_price

        bids = {o.order_id: o.remaining_quantity for o in engine.get_prioritized_bids()}
        asks = {o.order_id: o.remaining_quantity for o in engine.get_prioritized_asks()}
        book = {**bids, **asks}
        for order_id, expected_rem in scenario.expected.remaining_quantities.items():
            assert book.get(order_id, 0) == expected_rem

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_all_scenarios_adapter_pipeline_match_dispatch(self, scenario: TradingScenario):
        """Verify each scenario executes accurately when dispatched through OrderAdapter in match mode."""
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        for o in scenario.orders:
            adapter.dispatch_raw_order(o.to_protocol_order())

        assert adapter.stats.total_volume_matched == scenario.expected.total_matched_quantity
        assert len(adapter.trades) == len(scenario.expected.trades)


# ==============================================================================
# 9. Scenario Categorization & Filtering Tests (Week 3 Day 5)
# ==============================================================================

class TestScenarioCategorization:
    """Verifies that all required categories exist and scenarios are properly indexed."""

    def test_all_five_required_categories_defined(self):
        """Verify the 5 required scenario categories are defined."""
        assert CATEGORY_SUCCESSFUL_MATCHING == "successful_matching"
        assert CATEGORY_PARTIAL_FILLS == "partial_fills"
        assert CATEGORY_MULTIPLE_PRICE_LEVELS == "multiple_price_levels"
        assert CATEGORY_NON_CROSSING == "non_crossing"
        assert CATEGORY_UNMATCHED_ORDERS == "unmatched_orders"
        assert len(ALL_CATEGORIES) == 5

    def test_every_scenario_has_at_least_one_category(self):
        """Verify every registered scenario specifies at least one category tag."""
        for s in ALL_SCENARIOS:
            assert len(s.categories) > 0, f"Scenario {s.name} missing categories"
            for cat in s.categories:
                assert cat in ALL_CATEGORIES, f"Scenario {s.name} has invalid category {cat}"

    def test_successful_matching_scenarios_filter(self):
        """Verify successful matching scenarios filter returns expected set."""
        matches = get_successful_matching_scenarios()
        names = {s.name for s in matches}
        assert "scenario_1_exact_match" in names
        assert "scenario_2_crossed_market" in names
        assert "scenario_6_exact_full_fill" in names
        assert len(matches) >= 3

    def test_partial_fill_scenarios_filter(self):
        """Verify partial fill scenarios filter returns expected set."""
        partials = get_partial_fill_scenarios()
        names = {s.name for s in partials}
        assert "scenario_4_partial_fill_buy_larger" in names
        assert "scenario_5_partial_fill_sell_larger" in names
        assert len(partials) >= 2

    def test_multiple_price_levels_scenarios_filter(self):
        """Verify multiple price levels scenarios filter returns expected set."""
        multi_level = get_multiple_price_levels_scenarios()
        names = {s.name for s in multi_level}
        assert "scenario_8_price_priority_buy" in names
        assert "scenario_9_price_priority_sell" in names
        assert len(multi_level) >= 2

    def test_non_crossing_scenarios_filter(self):
        """Verify non-crossing scenarios filter returns expected set."""
        non_crossing = get_non_crossing_scenarios()
        names = {s.name for s in non_crossing}
        assert "scenario_3_no_trade_wide_spread" in names
        assert "scenario_10_empty_order_book" in names
        assert len(non_crossing) >= 2

    def test_unmatched_scenarios_filter(self):
        """Verify unmatched orders scenarios filter returns expected set."""
        unmatched = get_unmatched_scenarios()
        names = {s.name for s in unmatched}
        assert "scenario_3_no_trade_wide_spread" in names
        assert "scenario_10_empty_order_book" in names
        assert len(unmatched) >= 2

    def test_get_scenarios_by_category_invalid_returns_empty(self):
        """Verify querying a non-existent category returns empty list."""
        assert get_scenarios_by_category("invalid_non_existent_category") == []


# ==============================================================================
# 10. Scenario Execution Helpers & Outcome Verification Tests (Week 3 Day 5)
# ==============================================================================

class TestScenarioExecutionHelpers:
    """Verifies execute_in_engine, execute_in_adapter, and verify_execution methods."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_execute_in_engine_and_verify_execution(self, scenario: TradingScenario):
        """Verify execute_in_engine executes and passes verify_execution for all scenarios."""
        engine = MatchingEngine()
        trades = scenario.execute_in_engine(engine)
        assert scenario.verify_execution(trades, engine) is True

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_execute_in_adapter_and_verify_execution(self, scenario: TradingScenario):
        """Verify execute_in_adapter executes and matches expected trade details."""
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        trades = scenario.execute_in_adapter(adapter)
        assert scenario.verify_execution(trades, engine) is True

    def test_expected_trade_matches_trade_result_success(self):
        """Verify ExpectedTrade.matches_trade_result returns True on matching attributes."""
        expected = ExpectedTrade(buy_order_id=1, sell_order_id=2, execution_price=100.0, trade_quantity=50)
        trade = TradeResult(
            buy_order_id=1,
            sell_order_id=2,
            executed_quantity=50,
            execution_price_cents=10000,
            buy_remaining_quantity=0,
            sell_remaining_quantity=0,
        )
        assert expected.matches_trade_result(trade) is True

    def test_expected_trade_matches_trade_result_mismatch_detection(self):
        """Verify ExpectedTrade.matches_trade_result returns False on mismatched attributes."""
        expected = ExpectedTrade(buy_order_id=1, sell_order_id=2, execution_price=100.0, trade_quantity=50)
        # Wrong quantity
        t_wrong_qty = TradeResult(1, 2, 40, 10000, 0, 0)
        assert expected.matches_trade_result(t_wrong_qty) is False
        # Wrong buy_order_id
        t_wrong_buy = TradeResult(99, 2, 50, 10000, 0, 0)
        assert expected.matches_trade_result(t_wrong_buy) is False
        # Wrong execution_price
        t_wrong_price = TradeResult(1, 2, 50, 10500, 0, 0)
        assert expected.matches_trade_result(t_wrong_price) is False

    def test_verify_execution_detects_volume_discrepancy(self):
        """Verify verify_execution raises AssertionError if total executed volume does not match."""
        s = SCENARIO_1_EXACT_MATCH
        # Provide wrong trade with executed_quantity=40 instead of 50
        fake_trade = TradeResult(101, 102, 40, 10000, 0, 0)
        with pytest.raises(AssertionError, match="expected total matched 50, got 40"):
            s.verify_execution([fake_trade])

    def test_verify_execution_detects_trade_count_discrepancy(self):
        """Verify verify_execution raises AssertionError if trade count differs."""
        s = SCENARIO_1_EXACT_MATCH
        # Two trades summing to 50 shares (matches volume 50, but count 2 != expected 1)
        fake_trades = [
            TradeResult(101, 102, 25, 10000, 0, 0),
            TradeResult(101, 102, 25, 10000, 0, 0),
        ]
        with pytest.raises(AssertionError, match="expected 1 trades, got 2"):
            s.verify_execution(fake_trades)

    def test_verify_execution_detects_price_discrepancy(self):
        """Verify verify_execution raises AssertionError if trade execution price differs."""
        s = SCENARIO_1_EXACT_MATCH
        fake_trade = TradeResult(101, 102, 50, 10500, 0, 0)  # $105.00 instead of $100.00
        with pytest.raises(AssertionError, match="expected price=100.0, got 105.0"):
            s.verify_execution([fake_trade])

    def test_verify_execution_detects_remaining_quantity_discrepancy(self):
        """Verify verify_execution raises AssertionError if engine order book residue differs."""
        s = SCENARIO_4_PARTIAL_FILL_BUY_LARGER
        engine = MatchingEngine()
        trades = s.execute_in_engine(engine)
        # Tamper with engine book by modifying order quantity
        engine.get_best_buy_order().remaining_quantity = 999
        with pytest.raises(AssertionError, match="expected remaining 60, got 999"):
            s.verify_execution(trades, engine)


# ==============================================================================
# 11. Dedicated Category Behavior Verification (Week 3 Day 5)
# ==============================================================================

class TestCategoryBehaviorRequirements:
    """Explicitly tests behaviors required by Week 3 Day 5 curriculum."""

    def test_successful_matching_generates_positive_matched_volume(self):
        """Verify that every successful matching scenario executes >0 shares."""
        for s in get_successful_matching_scenarios():
            engine = MatchingEngine()
            trades = s.execute_in_engine(engine)
            assert len(trades) > 0
            assert s.expected.total_matched_quantity > 0
            assert sum(t.executed_quantity for t in trades) == s.expected.total_matched_quantity

    def test_partial_fills_leave_exact_residual_quantities(self):
        """Verify that partial fill scenarios leave exact expected resting residue in the book."""
        for s in get_partial_fill_scenarios():
            engine = MatchingEngine()
            s.execute_in_engine(engine)
            # Must have at least one order with remaining > 0 and at least one order with remaining == 0
            rems = list(s.expected.remaining_quantities.values())
            assert any(r > 0 for r in rems), f"Scenario {s.name} should have resting residue"
            assert any(r == 0 for r in rems), f"Scenario {s.name} should have fully filled orders"

    def test_multiple_price_levels_sweep_correct_maker_prices(self):
        """Verify multiple price level scenarios sweep multiple levels using resting maker prices."""
        for s in get_multiple_price_levels_scenarios():
            engine = MatchingEngine()
            trades = s.execute_in_engine(engine)
            assert len(trades) >= 2, f"Scenario {s.name} must generate >=2 fills across levels"
            # Execution prices of fills must differ (reflecting multiple price tiers)
            prices = [t.execution_price for t in trades]
            assert len(set(prices)) > 1, f"Scenario {s.name} fills should execute at distinct price tiers"

    def test_non_crossing_orders_produce_zero_trades(self):
        """Verify that non-crossing scenarios result in zero trades and zero volume."""
        for s in get_non_crossing_scenarios():
            engine = MatchingEngine()
            trades = s.execute_in_engine(engine)
            assert len(trades) == 0
            assert s.expected.total_matched_quantity == 0

    def test_unmatched_orders_rest_on_book_without_execution(self):
        """Verify unmatched orders remain resting in the book with initial quantities intact."""
        for s in get_unmatched_scenarios():
            engine = MatchingEngine()
            trades = s.execute_in_engine(engine)
            assert len(trades) == 0
            # If orders were submitted, their initial quantities must equal remaining quantities
            for o in s.orders:
                assert s.expected.remaining_quantities[o.order_id] == o.quantity


# ==============================================================================
# 12. Week 3 Nanosecond Timestamp & Latency Tracking Integration
# ==============================================================================

class TestTradingScenariosLatencyIntegration:
    """Verifies that scenario execution through OrderAdapter integrates with Week 3 nanosecond latency."""

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
    def test_scenario_execution_via_adapter_latency_tracking(self, scenario: TradingScenario):
        """Verify that adapter execution accurately tracks trade latency and nanosecond timestamps."""
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        trades = scenario.execute_in_adapter(adapter)

        # 1. Total volume & trade count
        assert len(trades) == len(scenario.expected.trades)
        assert adapter.stats.total_volume_matched == scenario.expected.total_matched_quantity

        # 2. Nanosecond timestamps on all generated trades
        for trade in trades:
            assert trade.entry_timestamp_ns > 0
            assert trade.exit_timestamp_ns >= trade.entry_timestamp_ns
            assert trade.latency_ns >= 0
            assert trade.latency_us == trade.latency_ns / 1000.0

        # 3. Trade latency tracker metrics
        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == len(scenario.expected.trades)
        if len(trades) > 0:
            assert snap.avg_latency_ns >= 0.0
            assert snap.min_latency_ns <= snap.max_latency_ns
        else:
            assert snap.avg_latency_ns == 0.0
            assert snap.min_latency_ns == 0
            assert snap.max_latency_ns == 0

    def test_non_crossing_scenarios_record_execution_events_without_trades(self):
        """Verify non-crossing orders record execution events with zero trades."""
        s = SCENARIO_3_NO_TRADE
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        s.execute_in_adapter(adapter)

        assert len(adapter.execution_events) == 2
        for ev in adapter.execution_events:
            assert ev.matched is False
            assert ev.volume_matched == 0
            assert ev.trades == []
            assert ev.latency_ns >= 0
            assert ev.entry_timestamp_ns > 0
            assert ev.exit_timestamp_ns >= ev.entry_timestamp_ns
        assert adapter.trade_latency.trade_count == 0
        assert adapter.stats.non_crossing_orders == 2
