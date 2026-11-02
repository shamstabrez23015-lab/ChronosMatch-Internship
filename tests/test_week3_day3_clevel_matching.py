"""Week 3 Day 3 — Matching engine C-level refactor correctness tests.

Covers:
1. price_to_cents / _price_to_cents_c consistency
2. _c_match_loop fill-buffer mechanics (via match_order)
3. execute_partial_match compaction-scan removal
4. Full fills, partial fills, multi-level sweeps
5. BUY and SELL side handling
6. Price-time priority preservation through the new path
7. Residual order FIFO priority retained after partial sweep
8. Quantity conservation invariant
9. TradeResult field correctness (buy_order_id, sell_order_id, price)
10. Buffer safety: many fills without overflow
"""

import pytest
from chronos.matching_engine import (
    MatchingEngine,
    COrder,
    TradeResult,
    price_to_cents,
    SIDE_BUY,
    SIDE_SELL,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_engine():
    return MatchingEngine()


# ---------------------------------------------------------------------------
# 1. price_to_cents round-trip through new _price_to_cents_c helper
# ---------------------------------------------------------------------------

class TestPriceToCents:
    """Verify the public price_to_cents interface still works after refactor."""

    def test_whole_dollar(self):
        assert price_to_cents(100.0) == 10000

    def test_fractional_cents(self):
        assert price_to_cents(225.50) == 22550

    def test_one_cent(self):
        assert price_to_cents(0.01) == 1

    def test_rounding_half_up(self):
        # 99.999 rounds to 100.00 == 10000 cents
        assert price_to_cents(99.999) == 10000

    def test_large_price(self):
        assert price_to_cents(9999.99) == 999999


# ---------------------------------------------------------------------------
# 2. submit_order still stores price in cents correctly
# ---------------------------------------------------------------------------

class TestSubmitOrderCents:
    def test_price_stored_as_cents(self):
        engine = make_engine()
        order = engine.submit_order(1, SIDE_BUY, 123.45, 10, 1000)
        assert order.price_cents == 12345

    def test_price_stored_as_cents_sell(self):
        engine = make_engine()
        order = engine.submit_order(1, SIDE_SELL, 50.25, 5, 2000)
        assert order.price_cents == 5025


# ---------------------------------------------------------------------------
# 3. execute_partial_match: compaction scan removes fully filled orders
# ---------------------------------------------------------------------------

class TestExecutePartialMatchRemoval:
    def test_both_full_fill_removes_both(self):
        """When both orders are fully filled, both are removed from the book."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 1000)
        engine.submit_order(2, SIDE_SELL, 99.0, 50, 2000)
        result = engine.execute_partial_match()
        assert result is not None
        assert result.executed_quantity == 50
        assert result.buy_remaining_quantity == 0
        assert result.sell_remaining_quantity == 0
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_buy_full_sell_partial_removes_buy(self):
        """BUY fully filled → removed; SELL partially filled → stays."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.0, 30, 1000)
        engine.submit_order(2, SIDE_SELL, 99.0, 60, 2000)
        result = engine.execute_partial_match()
        assert result is not None
        assert result.executed_quantity == 30
        assert result.buy_remaining_quantity == 0
        assert result.sell_remaining_quantity == 30
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        assert engine.get_best_ask().remaining_quantity == 30

    def test_buy_partial_sell_full_removes_sell(self):
        """SELL fully filled → removed; BUY partially filled → stays."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.0, 80, 1000)
        engine.submit_order(2, SIDE_SELL, 99.0, 30, 2000)
        result = engine.execute_partial_match()
        assert result is not None
        assert result.executed_quantity == 30
        assert result.buy_remaining_quantity == 50
        assert result.sell_remaining_quantity == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.get_best_bid().remaining_quantity == 50

    def test_multiple_bids_only_filled_removed(self):
        """With multiple BUY orders, only the filled one is removed."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.0, 20, 1000)
        engine.submit_order(2, SIDE_BUY, 101.0, 40, 2000)  # highest priority BUY
        engine.submit_order(3, SIDE_SELL, 99.0, 40, 3000)
        result = engine.execute_partial_match()
        assert result is not None
        assert result.buy_order_id == 2
        assert result.executed_quantity == 40
        assert engine.bid_count() == 1
        assert engine.get_bids()[0].order_id == 1

    def test_partial_match_price_is_maker_sell(self):
        """Execution price must be the resting SELL price (maker price)."""
        engine = make_engine()
        engine.submit_order(10, SIDE_BUY, 105.0, 50, 1000)
        engine.submit_order(20, SIDE_SELL, 102.0, 50, 2000)
        result = engine.execute_partial_match()
        assert result.execution_price_cents == 10200  # 102.00

    def test_no_match_when_no_crossing(self):
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 99.0, 50, 1000)
        engine.submit_order(2, SIDE_SELL, 100.0, 50, 2000)
        result = engine.execute_partial_match()
        assert result is None


# ---------------------------------------------------------------------------
# 4. match_order via _c_match_loop: full fill
# ---------------------------------------------------------------------------

class TestMatchOrderFullFill:
    def test_incoming_buy_full_fill(self):
        """Incoming BUY for exact quantity of resting SELL: both fully filled."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 100, 1000)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 100, 2000)
        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 2
        assert t.sell_order_id == 1
        assert t.executed_quantity == 100
        assert t.buy_remaining_quantity == 0
        assert t.sell_remaining_quantity == 0
        assert t.execution_price_cents == 5000
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_incoming_sell_full_fill(self):
        """Incoming SELL for exact quantity of resting BUY: both fully filled."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 75.0, 60, 1000)
        trades = engine.match_order(2, SIDE_SELL, 75.0, 60, 2000)
        assert len(trades) == 1
        t = trades[0]
        assert t.buy_order_id == 1
        assert t.sell_order_id == 2
        assert t.executed_quantity == 60
        assert t.execution_price_cents == 7500  # maker = resting BUY price

    def test_incoming_buy_smaller_than_resting(self):
        """Incoming BUY smaller than resting SELL: BUY fully filled, SELL partial."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 200, 1000)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 80, 2000)
        assert len(trades) == 1
        assert trades[0].executed_quantity == 80
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 120
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        assert engine.get_best_ask().remaining_quantity == 120


# ---------------------------------------------------------------------------
# 5. match_order: partial fill with residual resting
# ---------------------------------------------------------------------------

class TestMatchOrderPartialFillResidue:
    def test_incoming_buy_larger_than_resting(self):
        """Incoming BUY larger than resting SELL: SELL fully filled, BUY rests."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 30, 1000)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 80, 2000)
        assert len(trades) == 1
        assert trades[0].executed_quantity == 30
        assert trades[0].buy_remaining_quantity == 50
        assert trades[0].sell_remaining_quantity == 0
        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        bid = engine.get_best_bid()
        assert bid.order_id == 2
        assert bid.remaining_quantity == 50

    def test_incoming_sell_larger_than_resting(self):
        """Incoming SELL larger than resting BUY: BUY fully filled, SELL rests."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 75.0, 40, 1000)
        trades = engine.match_order(2, SIDE_SELL, 75.0, 90, 2000)
        assert len(trades) == 1
        assert trades[0].executed_quantity == 40
        assert trades[0].sell_remaining_quantity == 50
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        ask = engine.get_best_ask()
        assert ask.order_id == 2
        assert ask.remaining_quantity == 50

    def test_residual_order_retains_original_seq(self):
        """Residual order keeps the sequence_num assigned before matching."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 10, 1000)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 40, 2000)
        assert len(trades) == 1
        bid = engine.get_best_bid()
        assert bid.order_id == 2
        assert bid.sequence_num == 2  # sequence assigned at entry to match_order


# ---------------------------------------------------------------------------
# 6. Multi-level sweep
# ---------------------------------------------------------------------------

class TestMatchOrderMultiLevelSweep:
    def test_buy_sweeps_two_sell_levels(self):
        """Incoming BUY sweeps two SELL price levels in priority order."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.0, 30, 1000)  # lower price → matches first
        engine.submit_order(2, SIDE_SELL, 102.0, 20, 2000)  # higher price → matches second
        trades = engine.match_order(10, SIDE_BUY, 102.0, 50, 3000)
        assert len(trades) == 2
        assert trades[0].sell_order_id == 1
        assert trades[0].execution_price_cents == 10000
        assert trades[0].executed_quantity == 30
        assert trades[1].sell_order_id == 2
        assert trades[1].execution_price_cents == 10200
        assert trades[1].executed_quantity == 20
        assert engine.ask_count() == 0
        assert engine.bid_count() == 0  # incoming BUY also fully filled

    def test_sell_sweeps_two_buy_levels(self):
        """Incoming SELL sweeps two BUY price levels in priority order (highest first)."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 102.0, 25, 1000)  # higher price → matches first
        engine.submit_order(2, SIDE_BUY, 100.0, 25, 2000)  # lower price → matches second
        trades = engine.match_order(10, SIDE_SELL, 100.0, 50, 3000)
        assert len(trades) == 2
        assert trades[0].buy_order_id == 1
        assert trades[0].execution_price_cents == 10200
        assert trades[0].executed_quantity == 25
        assert trades[1].buy_order_id == 2
        assert trades[1].execution_price_cents == 10000
        assert trades[1].executed_quantity == 25

    def test_buy_stops_at_incompatible_price(self):
        """Incoming BUY stops matching when it reaches a SELL priced above BUY limit."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.0, 20, 1000)
        engine.submit_order(2, SIDE_SELL, 101.0, 20, 2000)  # above incoming BUY price
        trades = engine.match_order(10, SIDE_BUY, 100.0, 50, 3000)
        assert len(trades) == 1
        assert trades[0].sell_order_id == 1
        # Residual 30 shares of BUY 10 rests in book
        assert engine.bid_count() == 1
        assert engine.get_best_bid().remaining_quantity == 30
        assert engine.ask_count() == 1  # SELL 2 remains

    def test_no_trade_when_no_compatible_price(self):
        """Returns empty list when incoming BUY price is below all resting SELLs."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 105.0, 50, 1000)
        trades = engine.match_order(2, SIDE_BUY, 100.0, 50, 2000)
        assert trades == []
        assert engine.ask_count() == 1
        assert engine.bid_count() == 1  # BUY rested in book


# ---------------------------------------------------------------------------
# 7. Price-time priority preservation
# ---------------------------------------------------------------------------

class TestPriceTimePriority:
    def test_buy_sweeps_sells_lowest_price_first(self):
        """The SELL with the lowest price is always matched before a higher-priced SELL."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 101.0, 10, 1000)
        engine.submit_order(2, SIDE_SELL, 99.0, 10, 2000)   # lower price → higher priority
        engine.submit_order(3, SIDE_SELL, 100.0, 10, 3000)
        trades = engine.match_order(10, SIDE_BUY, 105.0, 10, 4000)
        assert len(trades) == 1
        assert trades[0].sell_order_id == 2   # cheapest ask matched
        assert trades[0].execution_price_cents == 9900

    def test_fifo_at_equal_sell_price(self):
        """At equal SELL price, earlier arrival (lower sequence) is matched first."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)  # arrives first
        engine.submit_order(2, SIDE_SELL, 100.0, 10, 2000)
        trades = engine.match_order(10, SIDE_BUY, 100.0, 10, 3000)
        assert trades[0].sell_order_id == 1  # FIFO: order 1 filled first

    def test_sell_sweeps_buys_highest_price_first(self):
        """The BUY with the highest price is always matched before a lower-priced BUY."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 99.0, 10, 1000)
        engine.submit_order(2, SIDE_BUY, 101.0, 10, 2000)  # higher price → higher priority
        engine.submit_order(3, SIDE_BUY, 100.0, 10, 3000)
        trades = engine.match_order(10, SIDE_SELL, 99.0, 10, 4000)
        assert len(trades) == 1
        assert trades[0].buy_order_id == 2
        assert trades[0].execution_price_cents == 10100

    def test_fifo_at_equal_buy_price(self):
        """At equal BUY price, earlier arrival (lower sequence) is matched first."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 100.0, 10, 1000)  # arrives first
        engine.submit_order(2, SIDE_BUY, 100.0, 10, 2000)
        trades = engine.match_order(10, SIDE_SELL, 100.0, 10, 3000)
        assert trades[0].buy_order_id == 1  # FIFO: order 1 filled first


# ---------------------------------------------------------------------------
# 8. Quantity conservation invariant
# ---------------------------------------------------------------------------

class TestQuantityConservation:
    def test_single_fill_conservation(self):
        """executed_qty + remaining_qty == original_qty for both sides."""
        engine = make_engine()
        buy_qty, sell_qty = 80, 60
        engine.submit_order(1, SIDE_BUY, 100.0, buy_qty, 1000)
        engine.submit_order(2, SIDE_SELL, 99.0, sell_qty, 2000)
        result = engine.execute_partial_match()
        exec_q = result.executed_quantity
        assert result.buy_remaining_quantity + exec_q == buy_qty
        assert result.sell_remaining_quantity + exec_q == sell_qty

    def test_multi_fill_conservation(self):
        """Sum of executed quantities equals total volume consumed."""
        engine = make_engine()
        # Resting book: 3 SELL orders totalling 90
        engine.submit_order(1, SIDE_SELL, 100.0, 30, 1000)
        engine.submit_order(2, SIDE_SELL, 101.0, 30, 2000)
        engine.submit_order(3, SIDE_SELL, 102.0, 30, 3000)
        # Incoming BUY for 70
        trades = engine.match_order(10, SIDE_BUY, 105.0, 70, 4000)
        total_exec = sum(t.executed_quantity for t in trades)
        assert total_exec == 70  # all 70 should be matched
        # residual: ask book should have 20 shares left in order 3
        ask_remaining = sum(o.remaining_quantity for o in engine.get_asks())
        assert total_exec + ask_remaining == 90  # sell side conservation

    def test_book_totals_after_sweep(self):
        """After a partial sweep, bid+ask remaining quantities are consistent."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 1000)
        engine.submit_order(2, SIDE_SELL, 101.0, 50, 2000)
        trades = engine.match_order(10, SIDE_BUY, 100.0, 40, 3000)
        total_exec = sum(t.executed_quantity for t in trades)
        assert total_exec == 40
        remaining_asks = sum(o.remaining_quantity for o in engine.get_asks())
        assert remaining_asks == 60  # 50 - 40 + 50 = 60


# ---------------------------------------------------------------------------
# 9. TradeResult field correctness
# ---------------------------------------------------------------------------

class TestTradeResultFields:
    def test_buy_and_sell_ids_set_correctly_for_incoming_buy(self):
        engine = make_engine()
        engine.submit_order(100, SIDE_SELL, 50.0, 20, 1000)
        trades = engine.match_order(200, SIDE_BUY, 50.0, 20, 2000)
        assert trades[0].buy_order_id == 200
        assert trades[0].sell_order_id == 100

    def test_buy_and_sell_ids_set_correctly_for_incoming_sell(self):
        engine = make_engine()
        engine.submit_order(100, SIDE_BUY, 50.0, 20, 1000)
        trades = engine.match_order(200, SIDE_SELL, 50.0, 20, 2000)
        assert trades[0].buy_order_id == 100
        assert trades[0].sell_order_id == 200

    def test_execution_price_is_resting_sell_price(self):
        """Maker price for incoming BUY = resting SELL's price."""
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 102.50, 10, 1000)
        trades = engine.match_order(2, SIDE_BUY, 105.0, 10, 2000)
        assert trades[0].execution_price_cents == 10250
        assert abs(trades[0].execution_price - 102.50) < 1e-9

    def test_execution_price_is_resting_buy_price(self):
        """Maker price for incoming SELL = resting BUY's price."""
        engine = make_engine()
        engine.submit_order(1, SIDE_BUY, 97.75, 10, 1000)
        trades = engine.match_order(2, SIDE_SELL, 95.0, 10, 2000)
        assert trades[0].execution_price_cents == 9775
        assert abs(trades[0].execution_price - 97.75) < 1e-9


# ---------------------------------------------------------------------------
# 10. Buffer safety: large number of fills
# ---------------------------------------------------------------------------

class TestBufferSafety:
    def test_many_resting_sells_swept_by_one_buy(self):
        """Single BUY sweeping 200 resting SELL orders does not overflow."""
        engine = make_engine()
        N = 200
        for i in range(N):
            engine.submit_order(i + 1, SIDE_SELL, 100.0, 1, i * 10)
        trades = engine.match_order(9999, SIDE_BUY, 100.0, N, N * 10 + 1)
        assert len(trades) == N
        total_exec = sum(t.executed_quantity for t in trades)
        assert total_exec == N
        assert engine.ask_count() == 0
        assert engine.bid_count() == 0

    def test_many_resting_buys_swept_by_one_sell(self):
        """Single SELL sweeping 150 resting BUY orders does not overflow."""
        engine = make_engine()
        N = 150
        for i in range(N):
            engine.submit_order(i + 1, SIDE_BUY, 100.0, 1, i * 10)
        trades = engine.match_order(9999, SIDE_SELL, 100.0, N, N * 10 + 1)
        assert len(trades) == N
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0


# ---------------------------------------------------------------------------
# 11. Residual order FIFO priority after partial sweep (regression)
# ---------------------------------------------------------------------------

class TestResidualFIFOPriority:
    def test_residual_buy_has_fifo_priority_over_later_order_same_price(self):
        """
        Verify the scenario from test_residual_order_retains_fifo_priority...
        now exercised through _c_match_loop path.
        """
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 20, 1000)
        # BUY for 50, partially fills 20, leaves 30 at 50.0 as residual
        trades = engine.match_order(10, SIDE_BUY, 50.0, 50, 2000)
        assert len(trades) == 1
        assert engine.bid_count() == 1
        assert engine.get_best_bid().order_id == 10
        assert engine.get_best_bid().remaining_quantity == 30

        # New BUY at same price 50.0 arrives after
        engine.submit_order(20, SIDE_BUY, 50.0, 30, 3000)
        assert engine.bid_count() == 2

        # Incoming SELL for 40: residual order 10 (30) filled first, then order 20 (10)
        sweep = engine.match_order(99, SIDE_SELL, 50.0, 40, 4000)
        assert len(sweep) == 2
        assert sweep[0].buy_order_id == 10
        assert sweep[0].executed_quantity == 30
        assert sweep[1].buy_order_id == 20
        assert sweep[1].executed_quantity == 10

        assert engine.bid_count() == 1
        assert engine.get_best_bid().order_id == 20
        assert engine.get_best_bid().remaining_quantity == 20


# ---------------------------------------------------------------------------
# 12. Public API compatibility (no regressions on interface contracts)
# ---------------------------------------------------------------------------

class TestPublicAPICompat:
    def test_match_order_returns_list(self):
        engine = make_engine()
        result = engine.match_order(1, SIDE_BUY, 100.0, 10, 1000)
        assert isinstance(result, list)

    def test_match_order_returns_empty_when_no_resting(self):
        engine = make_engine()
        result = engine.match_order(1, SIDE_BUY, 100.0, 10, 1000)
        assert result == []

    def test_trade_result_type(self):
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 10, 1000)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 10, 2000)
        assert len(trades) == 1
        assert isinstance(trades[0], TradeResult)

    def test_trade_result_as_dict(self):
        engine = make_engine()
        engine.submit_order(1, SIDE_SELL, 50.0, 10, 1000)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 10, 2000)
        d = trades[0].as_dict()
        assert 'buy_order_id' in d
        assert 'sell_order_id' in d
        assert 'executed_quantity' in d
        assert 'execution_price_cents' in d
        assert 'execution_price' in d

    def test_match_order_raises_on_bad_side(self):
        engine = make_engine()
        with pytest.raises(ValueError, match="Invalid side"):
            engine.match_order(1, 99, 100.0, 10, 1000)

    def test_match_order_raises_on_zero_qty(self):
        engine = make_engine()
        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.match_order(1, SIDE_BUY, 100.0, 0, 1000)

    def test_match_order_raises_on_negative_price(self):
        engine = make_engine()
        with pytest.raises(ValueError, match="Invalid price"):
            engine.match_order(1, SIDE_BUY, -1.0, 10, 1000)

    def test_order_count_incremented_only_for_resting(self):
        """order_count should increment only when an order rests in the book."""
        engine = make_engine()
        # SELL rests: +1
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)
        assert engine.order_count() == 1
        # Incoming BUY fully fills SELL; BUY is fully consumed too → order_count unchanged
        engine.match_order(2, SIDE_BUY, 100.0, 10, 2000)
        assert engine.order_count() == 1  # no residual BUY rested
        # Incoming BUY with residual: +1
        engine.submit_order(3, SIDE_SELL, 100.0, 5, 3000)
        engine.match_order(4, SIDE_BUY, 100.0, 20, 4000)
        assert engine.order_count() == 3  # SELL 3 rested, BUY 4 residual rested

