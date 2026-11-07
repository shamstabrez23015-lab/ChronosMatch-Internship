"""ChronosMatch -- Week 3, Day 8: Matched-Trade Record Generation Tests.

Tests the Cython matching engine's matched-trade record generation:
1. Full order fills (exact volume, maker pricing, buy/sell references, book eviction).
2. Partial order fills (remaining quantities, book retention/removal, fill flags).
3. Multi-level executions (order sweeps, ascending/descending prices, residual resting).
4. Additional validation (non-duplication, volume conservation, price-time priority, book consistency).
"""

import pytest
from chronos.matching_engine import MatchingEngine, TradeResult, COrder, SIDE_BUY, SIDE_SELL


# ==============================================================================
# 1. Full Order Fills
# ==============================================================================

class TestFullOrderFills:
    """Verify that completely matched orders generate correct TradeResult records."""

    def test_exact_full_fill_buy_incoming(self):
        """Resting SELL 100 @ 100.00, incoming BUY 100 @ 100.00 matches fully."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 100, timestamp_ns=1000)

        trades = engine.match_order(2, SIDE_BUY, 100.00, 100, timestamp_ns=2000)

        assert len(trades) == 1
        trade = trades[0]
        assert isinstance(trade, TradeResult)
        assert trade.buy_order_id == 2
        assert trade.sell_order_id == 1
        assert trade.executed_quantity == 100
        assert trade.trade_quantity == 100
        assert trade.execution_price_cents == 10000
        assert trade.execution_price == 100.00
        assert trade.price == 100.00
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 0
        assert trade.is_full_fill is True
        assert trade.is_partial_fill is False

        # Both orders evicted from book
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None

    def test_exact_full_fill_sell_incoming(self):
        """Resting BUY 100 @ 100.00, incoming SELL 100 @ 100.00 matches fully."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.00, 100, timestamp_ns=1000)

        trades = engine.match_order(2, SIDE_SELL, 100.00, 100, timestamp_ns=2000)

        assert len(trades) == 1
        trade = trades[0]
        assert trade.buy_order_id == 1
        assert trade.sell_order_id == 2
        assert trade.executed_quantity == 100
        assert trade.execution_price == 100.00
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 0
        assert trade.is_full_fill is True
        assert trade.is_partial_fill is False

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_full_fill_crossed_prices_maker_pricing(self):
        """Execution price is always the maker (resting) order's price."""
        # Case A: Resting SELL @ 50.00, incoming BUY @ 55.00 -> trade price = 50.00
        eng_a = MatchingEngine()
        eng_a.submit_order(101, SIDE_SELL, 50.00, 50, timestamp_ns=100)
        trades_a = eng_a.match_order(102, SIDE_BUY, 55.00, 50, timestamp_ns=200)

        assert len(trades_a) == 1
        assert trades_a[0].execution_price == 50.00
        assert trades_a[0].execution_price_cents == 5000
        assert trades_a[0].buy_order_id == 102
        assert trades_a[0].sell_order_id == 101

        # Case B: Resting BUY @ 55.00, incoming SELL @ 50.00 -> trade price = 55.00
        eng_b = MatchingEngine()
        eng_b.submit_order(201, SIDE_BUY, 55.00, 50, timestamp_ns=100)
        trades_b = eng_b.match_order(202, SIDE_SELL, 50.00, 50, timestamp_ns=200)

        assert len(trades_b) == 1
        assert trades_b[0].execution_price == 55.00
        assert trades_b[0].execution_price_cents == 5500
        assert trades_b[0].buy_order_id == 201
        assert trades_b[0].sell_order_id == 202

    def test_full_fill_via_execute_partial_match(self):
        """Pre-submitted crossing orders matched fully via execute_partial_match."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.00, 50, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 100.00, 50, timestamp_ns=2000)

        trade = engine.execute_partial_match()

        assert trade is not None
        assert trade.buy_order_id == 1
        assert trade.sell_order_id == 2
        assert trade.executed_quantity == 50
        assert trade.execution_price == 100.00
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 0
        assert trade.is_full_fill is True

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_full_fill_large_quantity_and_cent_precision(self):
        """Verify full fill with large quantity and fractional cent price."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 123.45, 1_000_000, timestamp_ns=1000)
        trades = engine.match_order(2, SIDE_BUY, 123.45, 1_000_000, timestamp_ns=2000)

        assert len(trades) == 1
        t = trades[0]
        assert t.executed_quantity == 1_000_000
        assert t.execution_price_cents == 12345
        assert t.execution_price == 123.45
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 0

    def test_full_fill_trade_result_as_dict_and_repr(self):
        """Verify TradeResult dictionary representation and string formatting."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 50.00, 20, timestamp_ns=100)
        t = engine.match_order(2, SIDE_BUY, 50.00, 20, timestamp_ns=200)[0]

        d = t.as_dict()
        assert d == {
            "buy_order_id": 2,
            "sell_order_id": 1,
            "executed_quantity": 20,
            "execution_price_cents": 5000,
            "execution_price": 50.0,
            "buy_remaining_quantity": 0,
            "sell_remaining_quantity": 0,
        }

        r = repr(t)
        assert "TradeResult" in r
        assert "buy=2" in r
        assert "sell=1" in r
        assert "exec_qty=20" in r


# ==============================================================================
# 2. Partial Order Fills
# ==============================================================================

class TestPartialOrderFills:
    """Verify that partially matched orders generate accurate TradeResult records."""

    def test_partial_fill_incoming_buy_larger_than_resting_sell(self):
        """Incoming BUY (100) partially filled by resting SELL (40); 60 rests in bids."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 40, timestamp_ns=1000)

        trades = engine.match_order(2, SIDE_BUY, 100.00, 100, timestamp_ns=2000)

        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 2
        assert t.sell_order_id == 1
        assert t.executed_quantity == 40
        assert t.execution_price == 100.00
        assert t.buy_remaining_quantity == 60
        assert t.sell_remaining_quantity == 0
        assert t.is_full_fill is False
        assert t.is_partial_fill is True

        # Resting SELL consumed and removed
        assert engine.ask_count() == 0
        # Residual BUY (60) rests in book
        assert engine.bid_count() == 1
        residual = engine.get_best_bid()
        assert residual.order_id == 2
        assert residual.quantity == 100
        assert residual.remaining_quantity == 60
        assert residual.filled_quantity == 40
        assert residual.is_partially_filled is True

    def test_partial_fill_incoming_buy_smaller_than_resting_sell(self):
        """Incoming BUY (40) fully filled; resting SELL (100) has 60 remaining in asks."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 100, timestamp_ns=1000)

        trades = engine.match_order(2, SIDE_BUY, 100.00, 40, timestamp_ns=2000)

        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 2
        assert t.sell_order_id == 1
        assert t.executed_quantity == 40
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 60
        assert t.is_full_fill is False
        assert t.is_partial_fill is True

        # Incoming BUY fully matched, does not rest
        assert engine.bid_count() == 0
        # Resting SELL remains with 60 shares
        assert engine.ask_count() == 1
        resting = engine.get_best_ask()
        assert resting.order_id == 1
        assert resting.quantity == 100
        assert resting.remaining_quantity == 60
        assert resting.filled_quantity == 40
        assert resting.is_partially_filled is True

    def test_partial_fill_incoming_sell_larger_than_resting_buy(self):
        """Incoming SELL (100) partially filled by resting BUY (40); 60 rests in asks."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.00, 40, timestamp_ns=1000)

        trades = engine.match_order(2, SIDE_SELL, 100.00, 100, timestamp_ns=2000)

        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 1
        assert t.sell_order_id == 2
        assert t.executed_quantity == 40
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 60
        assert t.is_full_fill is False
        assert t.is_partial_fill is True

        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        residual = engine.get_best_ask()
        assert residual.order_id == 2
        assert residual.remaining_quantity == 60

    def test_partial_fill_incoming_sell_smaller_than_resting_buy(self):
        """Incoming SELL (40) fully filled; resting BUY (100) has 60 remaining in bids."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.00, 100, timestamp_ns=1000)

        trades = engine.match_order(2, SIDE_SELL, 100.00, 40, timestamp_ns=2000)

        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 1
        assert t.sell_order_id == 2
        assert t.executed_quantity == 40
        assert t.buy_remaining_quantity == 60
        assert t.sell_remaining_quantity == 0

        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        assert engine.get_best_bid().remaining_quantity == 60

    def test_partial_fill_via_execute_partial_match(self):
        """execute_partial_match handles partial fill and preserves remaining order."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.00, 100, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 100.00, 40, timestamp_ns=2000)

        trade = engine.execute_partial_match()

        assert trade is not None
        assert trade.executed_quantity == 40
        assert trade.buy_remaining_quantity == 60
        assert trade.sell_remaining_quantity == 0
        assert trade.is_partial_fill is True

        # SELL #2 evicted; BUY #1 remains with 60
        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        assert engine.get_best_bid().remaining_quantity == 60

    def test_chained_sequential_partial_fills(self):
        """A resting order is partially filled multiple times until fully exhausted."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 100, timestamp_ns=1000)

        # Fill 1: BUY 30
        t1 = engine.match_order(10, SIDE_BUY, 100.00, 30, timestamp_ns=2000)[0]
        assert t1.executed_quantity == 30
        assert t1.buy_remaining_quantity == 0
        assert t1.sell_remaining_quantity == 70
        assert engine.get_best_ask().remaining_quantity == 70

        # Fill 2: BUY 40
        t2 = engine.match_order(20, SIDE_BUY, 100.00, 40, timestamp_ns=3000)[0]
        assert t2.executed_quantity == 40
        assert t2.buy_remaining_quantity == 0
        assert t2.sell_remaining_quantity == 30
        assert engine.get_best_ask().remaining_quantity == 30

        # Fill 3: BUY 30 (final fill)
        t3 = engine.match_order(30, SIDE_BUY, 100.00, 30, timestamp_ns=4000)[0]
        assert t3.executed_quantity == 30
        assert t3.buy_remaining_quantity == 0
        assert t3.sell_remaining_quantity == 0
        assert t3.is_full_fill is True

        # Entire book empty after fill 3
        assert engine.ask_count() == 0
        assert engine.bid_count() == 0


# ==============================================================================
# 3. Multi-Level Executions
# ==============================================================================

class TestMultiLevelExecutions:
    """Verify that an order matching across multiple price levels generates accurate records."""

    def test_multi_level_buy_sweeping_ascending_asks(self):
        """Incoming BUY sweeps across 3 SELL levels in ascending price order."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 50.00, 20, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 51.00, 30, timestamp_ns=2000)
        engine.submit_order(3, SIDE_SELL, 52.00, 40, timestamp_ns=3000)

        # Incoming BUY 75 sweeps: 20 @ 50, 30 @ 51, and 25 @ 52
        trades = engine.match_order(10, SIDE_BUY, 55.00, 75, timestamp_ns=4000)

        assert len(trades) == 3

        # Trade 1: Level 50.00
        assert trades[0].buy_order_id == 10
        assert trades[0].sell_order_id == 1
        assert trades[0].executed_quantity == 20
        assert trades[0].execution_price == 50.00
        assert trades[0].buy_remaining_quantity == 55  # 75 - 20
        assert trades[0].sell_remaining_quantity == 0

        # Trade 2: Level 51.00
        assert trades[1].buy_order_id == 10
        assert trades[1].sell_order_id == 2
        assert trades[1].executed_quantity == 30
        assert trades[1].execution_price == 51.00
        assert trades[1].buy_remaining_quantity == 25  # 55 - 30
        assert trades[1].sell_remaining_quantity == 0

        # Trade 3: Level 52.00
        assert trades[2].buy_order_id == 10
        assert trades[2].sell_order_id == 3
        assert trades[2].executed_quantity == 25
        assert trades[2].execution_price == 52.00
        assert trades[2].buy_remaining_quantity == 0   # 25 - 25
        assert trades[2].sell_remaining_quantity == 15 # 40 - 25

        # Check order book state
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        remaining_ask = engine.get_best_ask()
        assert remaining_ask.order_id == 3
        assert remaining_ask.price == 52.00
        assert remaining_ask.remaining_quantity == 15

    def test_multi_level_sell_sweeping_descending_bids(self):
        """Incoming SELL sweeps across 3 BUY levels in descending price order."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 52.00, 25, timestamp_ns=1000)
        engine.submit_order(2, SIDE_BUY, 51.00, 35, timestamp_ns=2000)
        engine.submit_order(3, SIDE_BUY, 50.00, 50, timestamp_ns=3000)

        # Incoming SELL 80 sweeps: 25 @ 52, 35 @ 51, and 20 @ 50
        trades = engine.match_order(10, SIDE_SELL, 49.00, 80, timestamp_ns=4000)

        assert len(trades) == 3

        # Trade 1: Level 52.00 (highest bid first)
        assert trades[0].sell_order_id == 10
        assert trades[0].buy_order_id == 1
        assert trades[0].executed_quantity == 25
        assert trades[0].execution_price == 52.00
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 55  # 80 - 25

        # Trade 2: Level 51.00
        assert trades[1].sell_order_id == 10
        assert trades[1].buy_order_id == 2
        assert trades[1].executed_quantity == 35
        assert trades[1].execution_price == 51.00
        assert trades[1].buy_remaining_quantity == 0
        assert trades[1].sell_remaining_quantity == 20  # 55 - 35

        # Trade 3: Level 50.00
        assert trades[2].sell_order_id == 10
        assert trades[2].buy_order_id == 3
        assert trades[2].executed_quantity == 20
        assert trades[2].execution_price == 50.00
        assert trades[2].buy_remaining_quantity == 30   # 50 - 20
        assert trades[2].sell_remaining_quantity == 0   # 20 - 20

        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        remaining_bid = engine.get_best_bid()
        assert remaining_bid.order_id == 3
        assert remaining_bid.price == 50.00
        assert remaining_bid.remaining_quantity == 30

    def test_multi_level_sweep_with_incoming_residual_resting(self):
        """Incoming BUY sweeps all resting SELL levels and leftover rests in bids."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 15, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 101.00, 25, timestamp_ns=200)

        # BUY 50 sweeps all 40 shares, leaves 10 resting
        trades = engine.match_order(10, SIDE_BUY, 105.00, 50, timestamp_ns=300)

        assert len(trades) == 2
        assert trades[0].executed_quantity == 15
        assert trades[0].buy_remaining_quantity == 35
        assert trades[1].executed_quantity == 25
        assert trades[1].buy_remaining_quantity == 10

        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        residual = engine.get_best_bid()
        assert residual.order_id == 10
        assert residual.price == 105.00
        assert residual.remaining_quantity == 10

    def test_multi_level_sweep_stops_at_limit_price(self):
        """Incoming order stops matching when resting orders exceed its limit price."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 10, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 101.00, 10, timestamp_ns=200)
        engine.submit_order(3, SIDE_SELL, 103.00, 10, timestamp_ns=300)

        # BUY limit 101.50 matches levels 100 and 101, but NOT 103
        trades = engine.match_order(10, SIDE_BUY, 101.50, 30, timestamp_ns=400)

        assert len(trades) == 2
        assert trades[0].execution_price == 100.00
        assert trades[1].execution_price == 101.00
        assert trades[1].buy_remaining_quantity == 10

        # SELL #3 must remain untouched in asks
        assert engine.ask_count() == 1
        assert engine.get_best_ask().order_id == 3
        assert engine.get_best_ask().price == 103.00
        assert engine.get_best_ask().remaining_quantity == 10

        # Residual BUY (10) rests in bids @ 101.50
        assert engine.bid_count() == 1
        assert engine.get_best_bid().order_id == 10
        assert engine.get_best_bid().price == 101.50
        assert engine.get_best_bid().remaining_quantity == 10

    def test_multiple_resting_orders_per_price_level_multi_level(self):
        """Multiple orders at each price level matched in strict FIFO order per level."""
        engine = MatchingEngine()
        # Level 100: two orders (ts=100, ts=200)
        engine.submit_order(1, SIDE_SELL, 100.00, 10, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 100.00, 15, timestamp_ns=200)
        # Level 101: two orders (ts=300, ts=400)
        engine.submit_order(3, SIDE_SELL, 101.00, 20, timestamp_ns=300)
        engine.submit_order(4, SIDE_SELL, 101.00, 25, timestamp_ns=400)

        # Incoming BUY 50 sweeps: #1 (10), #2 (15), #3 (20), #4 (5)
        trades = engine.match_order(10, SIDE_BUY, 105.00, 50, timestamp_ns=500)

        assert len(trades) == 4
        matched_sellers = [t.sell_order_id for t in trades]
        assert matched_sellers == [1, 2, 3, 4]
        assert [t.executed_quantity for t in trades] == [10, 15, 20, 5]

        # SELL #4 has 20 remaining
        assert engine.ask_count() == 1
        assert engine.get_best_ask().order_id == 4
        assert engine.get_best_ask().remaining_quantity == 20


# ==============================================================================
# 4. Additional Validation and Invariants
# ==============================================================================

class TestAdditionalValidationAndInvariants:
    """Verify non-duplication, volume conservation, price-time priority, and book consistency."""

    def test_trade_records_not_duplicated(self):
        """Verify that trade records are unique and not duplicated."""
        engine = MatchingEngine()
        for i in range(1, 6):
            engine.submit_order(i, SIDE_SELL, 100.00 + i, 10, timestamp_ns=i * 100)

        trades = engine.match_order(100, SIDE_BUY, 110.00, 50, timestamp_ns=1000)

        assert len(trades) == 5
        # Each trade record references a distinct sell order
        sell_ids = [t.sell_order_id for t in trades]
        assert len(sell_ids) == len(set(sell_ids))
        assert sell_ids == [1, 2, 3, 4, 5]

    def test_executed_quantity_conservation(self):
        """Sum of trade quantities strictly equals total filled quantity without loss or double counting."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 50.00, 15, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 51.00, 25, timestamp_ns=200)
        engine.submit_order(3, SIDE_SELL, 52.00, 35, timestamp_ns=300)

        incoming_qty = 60
        trades = engine.match_order(10, SIDE_BUY, 55.00, incoming_qty, timestamp_ns=400)

        total_exec = sum(t.executed_quantity for t in trades)
        assert total_exec == incoming_qty
        # 15 + 25 + 20 = 60
        assert [t.executed_quantity for t in trades] == [15, 25, 20]

        # Verify against order book remaining quantities
        snapshot = engine.get_order_book_snapshot()
        remaining_ask_qty = sum(o["remaining_quantity"] for o in snapshot["asks"])
        initial_total_ask_qty = 15 + 25 + 35  # 75
        assert total_exec + remaining_ask_qty == initial_total_ask_qty

    def test_no_negative_quantities_or_prices(self):
        """All quantities and prices in TradeResult and book are strictly positive/valid."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.00, 10, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 101.00, 20, timestamp_ns=200)

        trades = engine.match_order(10, SIDE_BUY, 102.00, 25, timestamp_ns=300)

        for t in trades:
            assert t.executed_quantity > 0
            assert t.execution_price_cents > 0
            assert t.execution_price > 0.0
            assert t.buy_remaining_quantity >= 0
            assert t.sell_remaining_quantity >= 0

        snapshot = engine.get_order_book_snapshot()
        for o in snapshot["asks"]:
            assert o["remaining_quantity"] > 0
            assert o["price_cents"] > 0

    def test_price_time_priority_same_price_fifo(self):
        """At equal price, earlier order arrives first and matches first (FIFO)."""
        engine = MatchingEngine()
        engine.submit_order(101, SIDE_BUY, 100.00, 10, timestamp_ns=1000)
        engine.submit_order(102, SIDE_BUY, 100.00, 10, timestamp_ns=2000)
        engine.submit_order(103, SIDE_BUY, 100.00, 10, timestamp_ns=3000)

        # Incoming SELL 20 matches #101 then #102
        trades = engine.match_order(201, SIDE_SELL, 100.00, 20, timestamp_ns=4000)

        assert len(trades) == 2
        assert trades[0].buy_order_id == 101
        assert trades[1].buy_order_id == 102

        # #103 must remain
        assert engine.bid_count() == 1
        assert engine.get_best_bid().order_id == 103

    def test_price_priority_beats_time_priority(self):
        """A better price arriving later takes precedence over a worse price arriving earlier."""
        engine = MatchingEngine()
        # Order 1: arrives earlier (ts=1000) @ 101.00
        engine.submit_order(1, SIDE_SELL, 101.00, 10, timestamp_ns=1000)
        # Order 2: arrives later (ts=2000) @ 100.00 (better ask!)
        engine.submit_order(2, SIDE_SELL, 100.00, 10, timestamp_ns=2000)

        trades = engine.match_order(10, SIDE_BUY, 105.00, 10, timestamp_ns=3000)

        assert len(trades) == 1
        assert trades[0].sell_order_id == 2  # Better price executed first
        assert trades[0].execution_price == 100.00

        # Worse price remains in book
        assert engine.ask_count() == 1
        assert engine.get_best_ask().order_id == 1

    def test_order_book_consistency_post_execution(self):
        """Verify best bid, best ask, counts, and snapshot consistency after execution."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 99.00, 20, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 101.00, 30, timestamp_ns=200)

        # Execute partial fill against SELL
        trades = engine.match_order(3, SIDE_BUY, 101.00, 10, timestamp_ns=300)
        assert len(trades) == 1

        # Post-execution checks
        assert engine.get_best_bid_price() == 99.00
        assert engine.get_best_ask_price() == 101.00
        assert engine.get_best_ask_quantity() == 20  # 30 - 10
        assert engine.get_spread() == 2.0
        # Order 3 executed completely without resting in book
        assert engine.order_count() == 2

        snap = engine.get_order_book_snapshot()
        assert snap["best_bid_price"] == 99.00
        assert snap["best_ask_price"] == 101.00
        assert snap["best_ask_quantity"] == 20
        assert snap["spread"] == 2.0
        assert len(snap["bids"]) == 1
        assert len(snap["asks"]) == 1

    def test_non_crossing_orders_generate_zero_trades(self):
        """Orders that do not cross prices produce an empty trades list and rest in book."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 105.00, 50, timestamp_ns=100)

        # BUY 100.00 does not cross SELL 105.00
        trades = engine.match_order(2, SIDE_BUY, 100.00, 50, timestamp_ns=200)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 100.00
        assert engine.get_best_ask_price() == 105.00

    def test_empty_book_order_generates_zero_trades(self):
        """Submitting an order to an empty book generates zero trades and rests."""
        engine = MatchingEngine()
        trades = engine.match_order(1, SIDE_BUY, 100.00, 50, timestamp_ns=100)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.get_best_bid_price() == 100.00
