# -*- coding: utf-8 -*-
"""Week 3, Day 4 — Comprehensive Cython Matching Engine Test Suite.

Verifies:
1. BUY and SELL order matching (maker vs taker price, side-specific routing).
2. Exact quantity matching and full fills (both orders fully consumed and removed).
3. Partial fills when incoming order quantity > available quantity (residual rests).
4. Partial fills when incoming order quantity < available quantity (maker remains with reduced qty).
5. Matching across multiple price levels (sweeping books in price priority order).
6. Price-time priority (FIFO tie-breaking at equal prices; price dominating arrival time).
7. Unmatched quantities remain correctly in the order book (telemetry and top-of-book consistency).
8. Order book integrity: invalid inputs (side, non-positive price, NaN, inf, zero quantity)
   and unmatched orders do not corrupt order book state or sequence numbering.
"""

from __future__ import annotations

import math
import pytest

from chronos.matching_engine import (
    MatchingEngine,
    COrder,
    TradeResult,
    price_to_cents,
    SIDE_BUY,
    SIDE_SELL,
)


# ==============================================================================
# Helper functions
# ==============================================================================

def make_engine() -> MatchingEngine:
    """Create a fresh instance of MatchingEngine."""
    return MatchingEngine()


# ==============================================================================
# 1. BUY and SELL Order Matching Tests (Task 2)
# ==============================================================================

class TestBuyAndSellMatching:
    """Tests for basic BUY and SELL order matching mechanics."""

    def test_incoming_buy_matches_resting_sell_maker_price(self):
        """Incoming BUY taker matches resting SELL maker; execution price is maker price."""
        engine = make_engine()
        # Resting SELL maker: 50 @ 100.00
        engine.submit_order(1, SIDE_SELL, 100.00, 50, timestamp_ns=1_000)
        assert engine.ask_count() == 1
        assert engine.bid_count() == 0

        # Incoming BUY taker: 50 @ 100.00
        trades = engine.match_order(2, SIDE_BUY, 100.00, 50, timestamp_ns=2_000)

        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 2
        assert t.sell_order_id == 1
        assert t.executed_quantity == 50
        assert t.execution_price == 100.00
        assert t.execution_price_cents == 10000
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 0

        # Book is now completely empty
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_incoming_sell_matches_resting_buy_maker_price(self):
        """Incoming SELL taker matches resting BUY maker; execution price is maker price."""
        engine = make_engine()
        # Resting BUY maker: 30 @ 150.00
        engine.submit_order(10, SIDE_BUY, 150.00, 30, timestamp_ns=1_000)
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0

        # Incoming SELL taker: 30 @ 150.00
        trades = engine.match_order(20, SIDE_SELL, 150.00, 30, timestamp_ns=2_000)

        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 10
        assert t.sell_order_id == 20
        assert t.executed_quantity == 30
        assert t.execution_price == 150.00
        assert t.execution_price_cents == 15000
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 0

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_incoming_buy_price_improvement(self):
        """Incoming BUY @ 105.00 crossing resting SELL @ 100.00 executes at resting 100.00."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.00, 25, timestamp_ns=100)

        trades = engine.match_order(2, SIDE_BUY, 105.00, 25, timestamp_ns=200)

        assert len(trades) == 1
        assert trades[0].execution_price == 100.00
        assert trades[0].execution_price_cents == 10000
        assert trades[0].executed_quantity == 25

    def test_incoming_sell_price_improvement(self):
        """Incoming SELL @ 95.00 crossing resting BUY @ 100.00 executes at resting 100.00."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 25, timestamp_ns=100)

        trades = engine.match_order(2, SIDE_SELL, 95.00, 25, timestamp_ns=200)

        assert len(trades) == 1
        assert trades[0].execution_price == 100.00
        assert trades[0].execution_price_cents == 10000
        assert trades[0].executed_quantity == 25

    def test_execute_partial_match_and_match_order_parity(self):
        """execute_partial_match and match_order produce identical results for 1-to-1 match."""
        # 1. execute_partial_match path
        eng1 = make_engine()
        eng1.submit_order(10, SIDE_BUY, 100.00, 50, 100)
        eng1.submit_order(20, SIDE_SELL, 100.00, 50, 200)
        tr1 = eng1.execute_partial_match()

        # 2. match_order path
        eng2 = make_engine()
        eng2.submit_order(10, SIDE_BUY, 100.00, 50, 100)
        trades2 = eng2.match_order(20, SIDE_SELL, 100.00, 50, 200)
        assert len(trades2) == 1
        tr2 = trades2[0]

        assert tr1.buy_order_id == tr2.buy_order_id == 10
        assert tr1.sell_order_id == tr2.sell_order_id == 20
        assert tr1.executed_quantity == tr2.executed_quantity == 50
        assert tr1.execution_price_cents == tr2.execution_price_cents == 10000
        assert eng1.bid_count() == eng2.bid_count() == 0
        assert eng1.ask_count() == eng2.ask_count() == 0


# ==============================================================================
# 2. Exact Quantity Matching & Full Fills (Task 3)
# ==============================================================================

class TestExactQuantityMatchingAndFullFills:
    """Tests for exact quantity matching where both sides fully fill."""

    def test_exact_quantity_single_unit(self):
        """Minimal order size: 1 share matching 1 share."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.00, 1, 10)
        trades = engine.match_order(2, SIDE_BUY, 50.00, 1, 20)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 1
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 0
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_exact_quantity_round_lot(self):
        """Standard round lot: 100 shares."""
        engine = make_engine()
        engine.submit_order(101, SIDE_BUY, 225.50, 100, 1000)
        trades = engine.match_order(102, SIDE_SELL, 225.50, 100, 2000)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 100
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 0
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_exact_quantity_large_block(self):
        """Large institutional block order: 1,000,000 shares."""
        engine = make_engine()
        engine.submit_order(999, SIDE_SELL, 350.25, 1_000_000, 100)
        trades = engine.match_order(1000, SIDE_BUY, 350.25, 1_000_000, 200)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 1_000_000
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 0
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_consecutive_exact_matches_preserve_clean_state(self):
        """Multiple consecutive exact matches keep order book consistently empty."""
        engine = make_engine()
        for i in range(10):
            maker_id = i * 2 + 1
            taker_id = i * 2 + 2
            engine.submit_order(maker_id, SIDE_SELL, 100.0 + i, 50, i * 100)
            assert engine.ask_count() == 1
            trades = engine.match_order(taker_id, SIDE_BUY, 100.0 + i, 50, i * 100 + 50)
            assert len(trades) == 1
            assert trades[0].executed_quantity == 50
            assert engine.ask_count() == 0
            assert engine.bid_count() == 0
            assert engine.get_best_bid() is None
            assert engine.get_best_ask() is None


# ==============================================================================
# 3. Partial Fills When Incoming Quantity > Available Quantity (Task 4)
# ==============================================================================

class TestPartialFillIncomingLarger:
    """Incoming order quantity exceeds resting liquidity: rests residual in book."""

    def test_incoming_buy_larger_than_single_resting_sell(self):
        """Incoming BUY (100 shares) sweeps resting SELL (40 shares); 60 shares rest in bids."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 150.00, 40, timestamp_ns=100)

        trades = engine.match_order(2, SIDE_BUY, 150.00, 100, timestamp_ns=200)

        # 1. Trade inspection
        assert len(trades) == 1
        t = trades[0]
        assert t.executed_quantity == 40
        assert t.buy_remaining_quantity == 60
        assert t.sell_remaining_quantity == 0

        # 2. Book inspection
        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        best_bid = engine.get_best_bid()
        assert best_bid is not None
        assert best_bid.order_id == 2
        assert best_bid.remaining_quantity == 60
        assert best_bid.quantity == 100
        assert best_bid.price == 150.00
        assert best_bid.timestamp_ns == 200

    def test_incoming_sell_larger_than_single_resting_buy(self):
        """Incoming SELL (80 shares) sweeps resting BUY (30 shares); 50 shares rest in asks."""
        engine = make_engine()
        engine.submit_order(10, SIDE_BUY, 75.00, 30, timestamp_ns=10)

        trades = engine.match_order(20, SIDE_SELL, 75.00, 80, timestamp_ns=20)

        # 1. Trade inspection
        assert len(trades) == 1
        t = trades[0]
        assert t.executed_quantity == 30
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 50

        # 2. Book inspection
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        best_ask = engine.get_best_ask()
        assert best_ask is not None
        assert best_ask.order_id == 20
        assert best_ask.remaining_quantity == 50
        assert best_ask.quantity == 80
        assert best_ask.price == 75.00
        assert best_ask.timestamp_ns == 20

    def test_incoming_buy_sweeps_multiple_resting_sells_and_rests(self):
        """Incoming BUY sweeps two resting SELLs and leaves residual quantity in bids."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.00, 15, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 50.00, 25, timestamp_ns=200)

        trades = engine.match_order(3, SIDE_BUY, 50.00, 60, timestamp_ns=300)

        assert len(trades) == 2
        assert trades[0].executed_quantity == 15
        assert trades[1].executed_quantity == 25
        assert sum(t.executed_quantity for t in trades) == 40
        assert trades[-1].buy_remaining_quantity == 20

        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        assert engine.get_best_bid().remaining_quantity == 20

    def test_subsequent_order_fills_residual_taker_order(self):
        """A subsequent taker matches against the residual resting portion of an earlier taker."""
        engine = make_engine()
        # Step 1: Resting SELL 30 @ 100
        engine.submit_order(1, SIDE_SELL, 100.00, 30, 100)
        # Step 2: BUY 50 @ 100 fills 30, rests 20
        trades1 = engine.match_order(2, SIDE_BUY, 100.00, 50, 200)
        assert len(trades1) == 1
        assert trades1[0].executed_quantity == 30
        assert engine.get_best_bid().remaining_quantity == 20

        # Step 3: Subsequent SELL 20 @ 100 matches residual 20
        trades2 = engine.match_order(3, SIDE_SELL, 100.00, 20, 300)
        assert len(trades2) == 1
        assert trades2[0].buy_order_id == 2
        assert trades2[0].sell_order_id == 3
        assert trades2[0].executed_quantity == 20
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0


# ==============================================================================
# 4. Partial Fills When Incoming Quantity < Available Quantity (Task 5)
# ==============================================================================

class TestPartialFillIncomingSmaller:
    """Incoming order quantity is smaller than available resting liquidity."""

    def test_incoming_buy_smaller_than_resting_sell(self):
        """Incoming BUY (30 shares) partially fills resting SELL (100 shares); 70 shares remain."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 200.00, 100, timestamp_ns=100)

        trades = engine.match_order(2, SIDE_BUY, 200.00, 30, timestamp_ns=200)

        assert len(trades) == 1
        t = trades[0]
        assert t.executed_quantity == 30
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 70

        # Resting maker remains in asks with decremented remaining_quantity
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        best_ask = engine.get_best_ask()
        assert best_ask.order_id == 1
        assert best_ask.remaining_quantity == 70
        assert best_ask.quantity == 100  # original quantity untouched

    def test_incoming_sell_smaller_than_resting_buy(self):
        """Incoming SELL (40 shares) partially fills resting BUY (150 shares); 110 shares remain."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 80.00, 150, timestamp_ns=100)

        trades = engine.match_order(2, SIDE_SELL, 80.00, 40, timestamp_ns=200)

        assert len(trades) == 1
        t = trades[0]
        assert t.executed_quantity == 40
        assert t.buy_remaining_quantity == 110
        assert t.sell_remaining_quantity == 0

        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        best_bid = engine.get_best_bid()
        assert best_bid.order_id == 1
        assert best_bid.remaining_quantity == 110
        assert best_bid.quantity == 150

    def test_multiple_takers_deplete_single_large_maker(self):
        """Three small taker orders sequentially chip away and finally exhaust a large maker order."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 50.00, 100, timestamp_ns=100)

        # 1. Fill 25 -> 75 remaining
        t1 = engine.match_order(2, SIDE_SELL, 50.00, 25, 200)
        assert len(t1) == 1
        assert t1[0].executed_quantity == 25
        assert engine.get_best_bid().remaining_quantity == 75

        # 2. Fill 35 -> 40 remaining
        t2 = engine.match_order(3, SIDE_SELL, 50.00, 35, 300)
        assert len(t2) == 1
        assert t2[0].executed_quantity == 35
        assert engine.get_best_bid().remaining_quantity == 40

        # 3. Fill 40 -> 0 remaining (maker order fully consumed and removed)
        t3 = engine.match_order(4, SIDE_SELL, 50.00, 40, 400)
        assert len(t3) == 1
        assert t3[0].executed_quantity == 40
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0


# ==============================================================================
# 5. Matching Across Multiple Price Levels (Task 6)
# ==============================================================================

class TestMatchingAcrossMultiplePriceLevels:
    """Incoming taker sweeps across multiple resting price levels."""

    def test_incoming_buy_sweeps_three_increasing_sell_levels(self):
        """Incoming BUY sweeps asks at 100.00, 101.00, and 102.00 in strict price order."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.00, 10, 1000)
        engine.submit_order(2, SIDE_SELL, 101.00, 20, 2000)
        engine.submit_order(3, SIDE_SELL, 102.00, 30, 3000)

        trades = engine.match_order(4, SIDE_BUY, 105.00, 60, 4000)

        assert len(trades) == 3
        # Strict price order: 100.00 -> 101.00 -> 102.00
        assert [t.execution_price for t in trades] == [100.00, 101.00, 102.00]
        assert [t.sell_order_id for t in trades] == [1, 2, 3]
        assert [t.executed_quantity for t in trades] == [10, 20, 30]
        assert engine.ask_count() == 0
        assert engine.bid_count() == 0

    def test_incoming_sell_sweeps_three_decreasing_buy_levels(self):
        """Incoming SELL sweeps bids at 102.00, 101.00, and 100.00 in descending price order."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 30, 1000)
        engine.submit_order(2, SIDE_BUY, 101.00, 20, 2000)
        engine.submit_order(3, SIDE_BUY, 102.00, 10, 3000)

        trades = engine.match_order(4, SIDE_SELL, 99.00, 60, 4000)

        assert len(trades) == 3
        # Highest buy price first: 102.00 -> 101.00 -> 100.00
        assert [t.execution_price for t in trades] == [102.00, 101.00, 100.00]
        assert [t.buy_order_id for t in trades] == [3, 2, 1]
        assert [t.executed_quantity for t in trades] == [10, 20, 30]
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_sweep_with_partial_fill_at_deepest_accessible_level(self):
        """Incoming BUY sweeps level 1 fully and partially fills at level 2; level 3 untouched."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 10.00, 10, 100)
        engine.submit_order(2, SIDE_SELL, 11.00, 20, 200)
        engine.submit_order(3, SIDE_SELL, 12.00, 30, 300)

        trades = engine.match_order(99, SIDE_BUY, 11.50, 25, 400)

        assert len(trades) == 2
        assert trades[0].sell_order_id == 1 and trades[0].executed_quantity == 10
        assert trades[1].sell_order_id == 2 and trades[1].executed_quantity == 15

        # Resting asks: Order 2 has 5 left @ 11.00, Order 3 has 30 left @ 12.00
        assert engine.ask_count() == 2
        assert engine.bid_count() == 0
        assert engine.get_best_ask_price() == 11.00
        assert engine.get_best_ask_quantity() == 5

    def test_sweep_stops_at_limit_price_and_rests_remaining(self):
        """Incoming BUY limit price stops matching before next ask level; residual BUY rests."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.00, 10, 100)
        engine.submit_order(2, SIDE_SELL, 55.00, 20, 200)

        # BUY for 25 @ 52.00: fills 10 @ 50.00, cannot cross 55.00, rests 15 @ 52.00
        trades = engine.match_order(100, SIDE_BUY, 52.00, 25, 300)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 10
        assert trades[0].execution_price == 50.00

        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 52.00
        assert engine.get_best_bid_quantity() == 15
        assert engine.get_best_ask_price() == 55.00
        assert engine.get_best_ask_quantity() == 20
        assert engine.get_spread() == 3.00


# ==============================================================================
# 6. Price-Time Priority at Same Price & FIFO Order (Task 7)
# ==============================================================================

class TestPriceTimePriorityAtSamePrice:
    """Verifies FIFO arrival priority at equal prices, and price dominating arrival time."""

    def test_bids_fifo_priority_at_same_price(self):
        """Three BUY orders at identical price are filled strictly in arrival timestamp order."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 10, timestamp_ns=1000)
        engine.submit_order(2, SIDE_BUY, 100.00, 20, timestamp_ns=2000)
        engine.submit_order(3, SIDE_BUY, 100.00, 30, timestamp_ns=3000)

        # Incoming SELL for 25: fills Order 1 completely (10), Order 2 partially (15)
        trades = engine.match_order(99, SIDE_SELL, 100.00, 25, timestamp_ns=4000)

        assert len(trades) == 2
        assert trades[0].buy_order_id == 1 and trades[0].executed_quantity == 10
        assert trades[1].buy_order_id == 2 and trades[1].executed_quantity == 15

        # Order 2 has 5 left and still holds priority over Order 3!
        prioritized_bids = engine.get_prioritized_bids()
        assert len(prioritized_bids) == 2
        assert prioritized_bids[0].order_id == 2
        assert prioritized_bids[0].remaining_quantity == 5
        assert prioritized_bids[1].order_id == 3
        assert prioritized_bids[1].remaining_quantity == 30

    def test_asks_fifo_priority_at_same_price(self):
        """Two SELL orders at identical price are filled strictly in arrival timestamp order."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 200.00, 15, timestamp_ns=500)
        engine.submit_order(2, SIDE_SELL, 200.00, 25, timestamp_ns=800)

        trades = engine.match_order(99, SIDE_BUY, 200.00, 20, timestamp_ns=1000)

        assert len(trades) == 2
        assert trades[0].sell_order_id == 1 and trades[0].executed_quantity == 15
        assert trades[1].sell_order_id == 2 and trades[1].executed_quantity == 5

        # Order 2 has 20 left
        assert engine.get_best_ask().order_id == 2
        assert engine.get_best_ask().remaining_quantity == 20

    def test_same_timestamp_tie_break_by_engine_sequence(self):
        """Equal timestamps at same price are deterministically tie-broken by engine sequence."""
        engine = make_engine()
        # Same timestamp_ns
        o1 = engine.submit_order(101, SIDE_BUY, 50.00, 10, timestamp_ns=1000)
        o2 = engine.submit_order(102, SIDE_BUY, 50.00, 10, timestamp_ns=1000)

        assert o1.sequence_num < o2.sequence_num

        trades = engine.match_order(200, SIDE_SELL, 50.00, 10, timestamp_ns=2000)
        assert len(trades) == 1
        assert trades[0].buy_order_id == 101  # Earlier sequence fills first

    def test_price_priority_dominates_time_priority_buy(self):
        """Higher BUY price takes priority over earlier arrival timestamp."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 99.00, 10, timestamp_ns=100)   # Earlier, lower price
        engine.submit_order(2, SIDE_BUY, 100.00, 10, timestamp_ns=200)  # Later, higher price

        trades = engine.match_order(3, SIDE_SELL, 99.00, 10, timestamp_ns=300)

        assert len(trades) == 1
        assert trades[0].buy_order_id == 2  # Higher price filled first
        assert trades[0].execution_price == 100.00

    def test_price_priority_dominates_time_priority_sell(self):
        """Lower SELL price takes priority over earlier arrival timestamp."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 101.00, 10, timestamp_ns=100)  # Earlier, higher price
        engine.submit_order(2, SIDE_SELL, 100.00, 10, timestamp_ns=200)  # Later, lower price

        trades = engine.match_order(3, SIDE_BUY, 101.00, 10, timestamp_ns=300)

        assert len(trades) == 1
        assert trades[0].sell_order_id == 2  # Lower price filled first
        assert trades[0].execution_price == 100.00

    def test_partially_filled_order_retains_priority_over_newer_orders_at_same_price(self):
        """Partially filled maker order does not re-queue to back of line."""
        engine = make_engine()
        # 1. Order 1: 50 @ 100.00 (ts 100)
        engine.submit_order(1, SIDE_BUY, 100.00, 50, 100)
        # 2. Taker fills 20 -> 30 left for Order 1
        engine.match_order(2, SIDE_SELL, 100.00, 20, 200)
        assert engine.get_best_bid().remaining_quantity == 30

        # 3. Order 3 arrives at same price 100.00 (ts 300)
        engine.submit_order(3, SIDE_BUY, 100.00, 40, 300)

        # 4. Taker for 35 must fill remaining 30 of Order 1 first, then 5 of Order 3
        trades = engine.match_order(4, SIDE_SELL, 100.00, 35, 400)
        assert len(trades) == 2
        assert trades[0].buy_order_id == 1 and trades[0].executed_quantity == 30
        assert trades[1].buy_order_id == 3 and trades[1].executed_quantity == 5


# ==============================================================================
# 7. Unmatched Quantities Remain in Order Book (Task 8)
# ==============================================================================

class TestUnmatchedQuantitiesRemainInOrderBook:
    """Unmatched orders and leftover quantities rest accurately in the book."""

    def test_unmatched_buy_on_empty_book_rests(self):
        """Incoming BUY on empty book generates 0 trades and rests in bids."""
        engine = make_engine()
        trades = engine.match_order(1, SIDE_BUY, 50.00, 100, 1000)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.get_best_bid_price() == 50.00
        assert engine.get_best_bid_quantity() == 100
        assert engine.get_spread() is None

    def test_unmatched_sell_on_empty_book_rests(self):
        """Incoming SELL on empty book generates 0 trades and rests in asks."""
        engine = make_engine()
        trades = engine.match_order(1, SIDE_SELL, 55.00, 100, 1000)

        assert len(trades) == 0
        assert engine.ask_count() == 1
        assert engine.bid_count() == 0
        assert engine.get_best_ask_price() == 55.00
        assert engine.get_best_ask_quantity() == 100
        assert engine.get_spread() is None

    def test_non_crossing_buy_below_best_ask_rests(self):
        """Incoming BUY below best ask does not match and widens or narrows bid side."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.00, 50, 1000)
        trades = engine.match_order(2, SIDE_BUY, 98.00, 40, 2000)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 98.00
        assert engine.get_best_ask_price() == 100.00
        assert engine.get_spread() == 2.00
        assert engine.get_spread_cents() == 200

    def test_non_crossing_sell_above_best_bid_rests(self):
        """Incoming SELL above best bid does not match and rests on ask side."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 95.00, 30, 1000)
        trades = engine.match_order(2, SIDE_SELL, 99.00, 45, 2000)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 95.00
        assert engine.get_best_ask_price() == 99.00
        assert engine.get_spread() == 4.00

    def test_aggregate_quantity_reporting_at_price_levels(self):
        """get_best_bid_quantity(aggregate=True) correctly sums all resting shares at top level."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 20, 100)
        engine.submit_order(2, SIDE_BUY, 100.00, 30, 200)
        engine.submit_order(3, SIDE_BUY, 99.00, 50, 300)

        assert engine.get_best_bid_quantity(aggregate=False) == 20
        assert engine.get_best_bid_quantity(aggregate=True) == 50


# ==============================================================================
# 8. Book Integrity on Invalid & Unmatched Orders (Task 9)
# ==============================================================================

class TestBookIntegrityOnInvalidAndUnmatchedOrders:
    """Invalid orders are rejected without side effects; book remains pristine."""

    def test_invalid_side_rejected_book_unchanged(self):
        """Side values other than 1 and 2 raise ValueError; book untouched."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 50, 100)

        for bad_side in [0, 3, -1, 99]:
            with pytest.raises(ValueError, match="Invalid side"):
                engine.submit_order(2, bad_side, 100.00, 10, 200)
            with pytest.raises(ValueError, match="Invalid side"):
                engine.match_order(2, bad_side, 100.00, 10, 200)

        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.order_count() == 1

    def test_non_positive_price_rejected_book_unchanged(self):
        """Prices <= 0.0 raise ValueError; book untouched."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.00, 50, 100)

        for bad_price in [0.0, -1.0, -0.01, -100.0]:
            with pytest.raises(ValueError, match="Invalid price"):
                engine.submit_order(2, SIDE_BUY, bad_price, 10, 200)
            with pytest.raises(ValueError, match="Invalid price"):
                engine.match_order(2, SIDE_BUY, bad_price, 10, 200)

        assert engine.ask_count() == 1
        assert engine.bid_count() == 0

    def test_nan_and_inf_prices_rejected_book_unchanged(self):
        """NaN and inf prices are rejected and cannot corrupt integer cent state."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 50.00, 10, 100)

        for bad_price in [float("nan"), float("inf"), float("-inf")]:
            with pytest.raises(ValueError, match="Invalid price"):
                engine.submit_order(2, SIDE_BUY, bad_price, 10, 200)
            with pytest.raises(ValueError, match="Invalid price"):
                engine.match_order(2, SIDE_BUY, bad_price, 10, 200)

        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.get_best_bid_price() == 50.00

    def test_zero_quantity_rejected_book_unchanged(self):
        """Quantity 0 raises ValueError; book untouched."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 50, 100)

        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.submit_order(2, SIDE_BUY, 100.00, 0, 200)
        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.match_order(2, SIDE_BUY, 100.00, 0, 200)

        assert engine.bid_count() == 1
        assert engine.ask_count() == 0

    def test_interleaved_valid_and_invalid_operations(self):
        """Book state and sequence counters remain reliable across rejected and valid attempts."""
        engine = make_engine()

        # Valid order
        engine.submit_order(1, SIDE_BUY, 100.00, 10, 100)
        assert engine.bid_count() == 1

        # Rejected attempt (invalid quantity)
        with pytest.raises(ValueError):
            engine.submit_order(2, SIDE_BUY, 100.00, 0, 200)

        # Valid match
        trades = engine.match_order(3, SIDE_SELL, 100.00, 10, 300)
        assert len(trades) == 1
        assert engine.bid_count() == 0

        # Rejected attempt (invalid side)
        with pytest.raises(ValueError):
            engine.match_order(4, 99, 100.00, 10, 400)

        # Book remains completely clean
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_execute_partial_match_on_non_crossing_book_is_noop(self):
        """execute_partial_match returns None when prices do not cross and causes no side effects."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 90.00, 10, 100)
        engine.submit_order(2, SIDE_SELL, 100.00, 10, 200)

        res = engine.execute_partial_match()
        assert res is None
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid().remaining_quantity == 10
        assert engine.get_best_ask().remaining_quantity == 10

    def test_clear_and_reset_pristine_initialization(self):
        """Engine clear() and reset() fully zero out book and sequence state."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.00, 10, 100)
        engine.submit_order(2, SIDE_SELL, 105.00, 20, 200)
        assert engine.order_count() == 2

        engine.clear()
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.order_count() == 0
        assert engine.is_ready() is True
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None
