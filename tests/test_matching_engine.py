"""Unit tests for the ChronosMatch Cython Matching Engine foundation.

Tests cover:
  - Extension import
  - Engine initialisation and readiness
  - Valid order acceptance
  - Rejection of invalid side, non-positive price, and zero quantity
  - Price-to-cents conversion
"""

import pytest


# ---------------------------------------------------------------------------
# 1. Extension import
# ---------------------------------------------------------------------------
class TestImport:
    """Verify the compiled Cython extension can be imported."""

    def test_import_module(self):
        import chronos.matching_engine  # noqa: F401

    def test_import_classes(self):
        from chronos.matching_engine import COrder, MatchingEngine  # noqa: F401

    def test_import_helper(self):
        from chronos.matching_engine import price_to_cents  # noqa: F401


# ---------------------------------------------------------------------------
# 2. Engine initialisation
# ---------------------------------------------------------------------------
class TestEngineInit:
    """Verify engine starts in a clean, ready state."""

    def test_engine_is_ready(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.is_ready() is True

    def test_engine_order_count_starts_at_zero(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.order_count() == 0

    def test_engine_status_dict(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        st = engine.status()
        assert st == {"ready": True, "order_count": 0}


# ---------------------------------------------------------------------------
# 3. Valid order acceptance
# ---------------------------------------------------------------------------
class TestSubmitValidOrder:
    """Verify a valid order is accepted and acknowledged correctly."""

    def test_accept_buy_order(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        order = engine.submit_order(
            order_id=1,
            side=1,          # BUY
            price=225.50,
            quantity=100,
            timestamp_ns=1_000_000_000,
        )
        assert order.order_id == 1
        assert order.side == 1
        assert order.price_cents == 22550
        assert order.quantity == 100
        assert order.timestamp_ns == 1_000_000_000
        assert engine.order_count() == 1

    def test_accept_sell_order(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        order = engine.submit_order(
            order_id=42,
            side=2,          # SELL
            price=128.45,
            quantity=500,
            timestamp_ns=2_000_000_000,
        )
        assert order.order_id == 42
        assert order.side == 2
        assert order.price_cents == 12845
        assert order.quantity == 500
        assert engine.order_count() == 1

    def test_order_repr(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        order = engine.submit_order(1, 1, 100.00, 50, 999)
        r = repr(order)
        assert "BUY" in r
        assert "10000" in r   # price_cents

    def test_order_as_dict(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        order = engine.submit_order(7, 2, 50.25, 10, 12345)
        d = order.as_dict()
        assert d == {
            "order_id": 7,
            "side": 2,
            "price_cents": 5025,
            "quantity": 10,
            "timestamp_ns": 12345,
        }

    def test_multiple_orders_increment_count(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        for i in range(5):
            engine.submit_order(i, 1, 100.0, 10, i * 100)
        assert engine.order_count() == 5


# ---------------------------------------------------------------------------
# 4. Invalid order rejection
# ---------------------------------------------------------------------------
class TestRejectInvalidOrders:
    """Verify that invalid inputs raise ``ValueError``."""

    def test_reject_invalid_side_zero(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid side"):
            engine.submit_order(1, 0, 100.0, 10, 1000)

    def test_reject_invalid_side_three(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid side"):
            engine.submit_order(1, 3, 100.0, 10, 1000)

    def test_reject_negative_price(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid price"):
            engine.submit_order(1, 1, -10.0, 10, 1000)

    def test_reject_zero_price(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid price"):
            engine.submit_order(1, 1, 0.0, 10, 1000)

    def test_reject_zero_quantity(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.submit_order(1, 1, 100.0, 0, 1000)

    def test_rejected_order_does_not_increment_count(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError):
            engine.submit_order(1, 0, 100.0, 10, 1000)
        assert engine.order_count() == 0


# ---------------------------------------------------------------------------
# 5. Price conversion helper
# ---------------------------------------------------------------------------
class TestPriceToCents:
    """Verify the ``price_to_cents`` helper."""

    def test_whole_dollar(self):
        from chronos.matching_engine import price_to_cents
        assert price_to_cents(100.0) == 10000

    def test_fractional_cents(self):
        from chronos.matching_engine import price_to_cents
        assert price_to_cents(225.50) == 22550

    def test_sub_penny(self):
        from chronos.matching_engine import price_to_cents
        # 99.999 → nearest cent = 10000
        assert price_to_cents(99.999) == 10000

    def test_small_price(self):
        from chronos.matching_engine import price_to_cents
        assert price_to_cents(0.01) == 1


# ===========================================================================
# Day 2: Order Book Data Structures Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 6. Empty order book initialization
# ---------------------------------------------------------------------------
class TestOrderBookInit:
    """Verify empty order book initialization and reset functionality."""

    def test_initial_counts_are_zero(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.get_bid_count() == 0
        assert engine.get_ask_count() == 0
        assert engine.order_count() == 0

    def test_initial_storage_is_empty(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.get_bids() == []
        assert engine.get_asks() == []
        assert engine.get_buy_orders() == []
        assert engine.get_sell_orders() == []
        assert list(engine.bids) == []
        assert list(engine.asks) == []
        assert engine.bids() == []
        assert engine.asks() == []

    def test_clear_resets_order_book(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        engine.submit_order(1, 1, 150.00, 10, 1000)
        engine.submit_order(2, 2, 155.00, 20, 2000)
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.order_count() == 2

        engine.clear()
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.order_count() == 0
        assert engine.get_bids() == []
        assert engine.get_asks() == []
        assert engine.is_ready() is True

    def test_reset_and_init_order_book_aliases(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        engine.submit_order(1, 1, 100.0, 5, 100)
        engine.reset()
        assert engine.bid_count() == 0

        engine.submit_order(2, 2, 200.0, 5, 200)
        engine.init_order_book()
        assert engine.ask_count() == 0


# ---------------------------------------------------------------------------
# 7. Adding BUY orders (single and multiple)
# ---------------------------------------------------------------------------
class TestAddBuyOrders:
    """Verify adding single and multiple BUY orders."""

    def test_add_single_buy_order_via_submit(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        order = engine.submit_order(
            order_id=101,
            side=SIDE_BUY,
            price=250.75,
            quantity=50,
            timestamp_ns=1_000_001,
        )
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.order_count() == 1

        bids = engine.get_bids()
        assert len(bids) == 1
        assert bids[0] is order
        assert bids[0].order_id == 101

    def test_add_single_buy_order_via_helper(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        order = engine.add_buy_order(
            order_id=202,
            price=190.25,
            quantity=30,
            timestamp_ns=500_000,
        )
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert order.side == 1
        assert order.price_cents == 19025
        assert order.quantity == 30
        assert engine.get_bids()[0].order_id == 202

    def test_add_multiple_buy_orders(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        prices = [100.00, 101.50, 99.25, 105.00, 98.75]
        created = []
        for i, p in enumerate(prices, start=1):
            o = engine.submit_order(order_id=i, side=SIDE_BUY, price=p, quantity=10 * i, timestamp_ns=i * 1000)
            created.append(o)

        assert engine.bid_count() == len(prices)
        assert engine.ask_count() == 0
        assert engine.order_count() == len(prices)

        bids = engine.get_bids()
        assert len(bids) == len(prices)
        for actual, expected in zip(bids, created):
            assert actual.order_id == expected.order_id
            assert actual.price_cents == expected.price_cents


# ---------------------------------------------------------------------------
# 8. Adding SELL orders (single and multiple)
# ---------------------------------------------------------------------------
class TestAddSellOrders:
    """Verify adding single and multiple SELL orders."""

    def test_add_single_sell_order_via_submit(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        order = engine.submit_order(
            order_id=301,
            side=SIDE_SELL,
            price=310.50,
            quantity=80,
            timestamp_ns=2_000_002,
        )
        assert engine.ask_count() == 1
        assert engine.bid_count() == 0
        assert engine.order_count() == 1

        asks = engine.get_asks()
        assert len(asks) == 1
        assert asks[0] is order
        assert asks[0].order_id == 301

    def test_add_single_sell_order_via_helper(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        order = engine.add_sell_order(
            order_id=402,
            price=275.80,
            quantity=45,
            timestamp_ns=600_000,
        )
        assert engine.ask_count() == 1
        assert engine.bid_count() == 0
        assert order.side == 2
        assert order.price_cents == 27580
        assert order.quantity == 45
        assert engine.get_asks()[0].order_id == 402

    def test_add_multiple_sell_orders(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        prices = [300.00, 305.25, 298.50, 310.00, 295.75]
        created = []
        for i, p in enumerate(prices, start=1):
            o = engine.submit_order(order_id=i, side=SIDE_SELL, price=p, quantity=5 * i, timestamp_ns=i * 2000)
            created.append(o)

        assert engine.ask_count() == len(prices)
        assert engine.bid_count() == 0
        assert engine.order_count() == len(prices)

        asks = engine.get_asks()
        assert len(asks) == len(prices)
        for actual, expected in zip(asks, created):
            assert actual.order_id == expected.order_id
            assert actual.price_cents == expected.price_cents


# ---------------------------------------------------------------------------
# 9. Preserving stored order information
# ---------------------------------------------------------------------------
class TestPreserveStoredOrderInfo:
    """Verify that stored orders retain full fidelity of all order fields."""

    def test_stored_buy_order_attributes(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        order = engine.submit_order(
            order_id=999,
            side=SIDE_BUY,
            price=123.45,
            quantity=75,
            timestamp_ns=987_654_321,
        )
        stored = engine.get_bids()[0]
        assert stored.order_id == 999
        assert stored.side == SIDE_BUY
        assert stored.price_cents == 12345
        assert stored.price == 123.45
        assert stored.quantity == 75
        assert stored.timestamp_ns == 987_654_321
        assert stored.sequence_num == 1

    def test_stored_sell_order_attributes(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        order = engine.submit_order(
            order_id=888,
            side=SIDE_SELL,
            price=876.54,
            quantity=120,
            timestamp_ns=123_456_789,
        )
        stored = engine.get_asks()[0]
        assert stored.order_id == 888
        assert stored.side == SIDE_SELL
        assert stored.price_cents == 87654
        assert stored.price == 876.54
        assert stored.quantity == 120
        assert stored.timestamp_ns == 123_456_789
        assert stored.sequence_num == 1

    def test_adding_existing_corder_instance(self):
        from chronos.matching_engine import MatchingEngine, COrder, SIDE_BUY, price_to_cents
        engine = MatchingEngine()
        corder = COrder(
            order_id=555,
            side=SIDE_BUY,
            price_cents=price_to_cents(50.25),
            quantity=25,
            timestamp_ns=111_222,
        )
        accepted = engine.add_buy_order(corder)
        assert accepted.order_id == 555
        assert accepted.sequence_num == 1
        assert engine.bid_count() == 1
        assert engine.get_bids()[0].order_id == 555


# ---------------------------------------------------------------------------
# 10. Preserving arrival order
# ---------------------------------------------------------------------------
class TestPreserveArrivalOrder:
    """Verify that orders are stored in deterministic arrival sequence."""

    def test_buy_arrival_sequence_preserved(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        # Submit with prices out of price-priority order to prove arrival order is preserved
        submissions = [
            (10, 100.0, 10, 1000),
            (20, 105.0, 20, 2000),
            (30,  95.0, 30, 3000),
            (40, 102.5, 40, 4000),
        ]
        for oid, pr, qty, ts in submissions:
            engine.submit_order(oid, SIDE_BUY, pr, qty, ts)

        bids = engine.get_bids()
        expected_ids = [10, 20, 30, 40]
        assert [b.order_id for b in bids] == expected_ids
        assert [b.sequence_num for b in bids] == [1, 2, 3, 4]

    def test_sell_arrival_sequence_preserved(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        submissions = [
            (100, 200.0, 15, 1000),
            (200, 195.0, 25, 2000),
            (300, 210.0, 35, 3000),
            (400, 198.0, 45, 4000),
        ]
        for oid, pr, qty, ts in submissions:
            engine.submit_order(oid, SIDE_SELL, pr, qty, ts)

        asks = engine.get_asks()
        expected_ids = [100, 200, 300, 400]
        assert [a.order_id for a in asks] == expected_ids
        assert [a.sequence_num for a in asks] == [1, 2, 3, 4]

    def test_interleaved_arrival_sequences(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 10, 100)   # seq 1
        engine.submit_order(2, SIDE_SELL, 105.0, 10, 200)  # seq 2
        engine.submit_order(3, SIDE_BUY, 101.0, 10, 300)   # seq 3
        engine.submit_order(4, SIDE_SELL, 106.0, 10, 400)  # seq 4

        bids = engine.get_bids()
        asks = engine.get_asks()

        assert [b.order_id for b in bids] == [1, 3]
        assert [b.sequence_num for b in bids] == [1, 3]

        assert [a.order_id for a in asks] == [2, 4]
        assert [a.sequence_num for a in asks] == [2, 4]


# ---------------------------------------------------------------------------
# 11. Rejecting invalid orders
# ---------------------------------------------------------------------------
class TestOrderBookValidation:
    """Verify that invalid orders are rejected and not stored in the book."""

    def test_invalid_side_not_stored(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid side"):
            engine.submit_order(1, 0, 100.0, 10, 1000)
        with pytest.raises(ValueError, match="Invalid side"):
            engine.submit_order(2, 3, 100.0, 10, 1000)

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.order_count() == 0

    def test_invalid_price_not_stored(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid price"):
            engine.submit_order(1, SIDE_BUY, 0.0, 10, 1000)
        with pytest.raises(ValueError, match="Invalid price"):
            engine.submit_order(2, SIDE_BUY, -50.0, 10, 1000)

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_invalid_quantity_not_stored(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.submit_order(1, SIDE_SELL, 100.0, 0, 1000)

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_add_buy_order_rejects_wrong_side(self):
        from chronos.matching_engine import MatchingEngine, COrder, SIDE_SELL
        engine = MatchingEngine()
        bad_order = COrder(1, SIDE_SELL, 10000, 10, 100)
        with pytest.raises(ValueError, match="Invalid side"):
            engine.add_buy_order(bad_order)
        assert engine.bid_count() == 0

    def test_add_sell_order_rejects_wrong_side(self):
        from chronos.matching_engine import MatchingEngine, COrder, SIDE_BUY
        engine = MatchingEngine()
        bad_order = COrder(1, SIDE_BUY, 10000, 10, 100)
        with pytest.raises(ValueError, match="Invalid side"):
            engine.add_sell_order(bad_order)
        assert engine.ask_count() == 0


# ---------------------------------------------------------------------------
# 12. Keeping BUY and SELL storage separate
# ---------------------------------------------------------------------------
class TestSeparateBuySellStorage:
    """Verify BUY and SELL orders are completely isolated in separate storage."""

    def test_separation_integrity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Submit 3 BUYs and 2 SELLs interleaved
        engine.submit_order(1, SIDE_BUY, 100.0, 10, 1000)
        engine.submit_order(2, SIDE_SELL, 105.0, 20, 2000)
        engine.submit_order(3, SIDE_BUY, 101.0, 15, 3000)
        engine.submit_order(4, SIDE_SELL, 106.0, 25, 4000)
        engine.submit_order(5, SIDE_BUY, 102.0, 30, 5000)

        assert engine.bid_count() == 3
        assert engine.ask_count() == 2
        assert engine.order_count() == 5

        bids = engine.get_bids()
        asks = engine.get_asks()

        # Check all bids are strictly BUY
        assert all(b.side == SIDE_BUY for b in bids)
        assert [b.order_id for b in bids] == [1, 3, 5]

        # Check all asks are strictly SELL
        assert all(a.side == SIDE_SELL for a in asks)
        assert [a.order_id for a in asks] == [2, 4]

        # Cross check no leakage
        bid_ids = {b.order_id for b in bids}
        ask_ids = {a.order_id for a in asks}
        assert bid_ids.isdisjoint(ask_ids)

    def test_order_book_alias(self):
        from chronos.matching_engine import OrderBook, SIDE_BUY, SIDE_SELL
        book = OrderBook()
        book.submit_order(1, SIDE_BUY, 100.0, 10, 1000)
        book.submit_order(2, SIDE_SELL, 105.0, 20, 2000)
        assert book.bid_count() == 1
        assert book.ask_count() == 1


# ===========================================================================
# Day 3: Price Priority Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 13. Highest BUY price selection
# ---------------------------------------------------------------------------
class TestHighestBuyPriceSelection:
    """Verify that the highest BUY price has the highest priority."""

    def test_highest_buy_price_spec_example(self):
        """Spec example:
        BUY order 101: price 500, quantity 100
        BUY order 102: price 510, quantity 50
        BUY order 103: price 505, quantity 80
        Expected best BUY order: Order 102, price 510.
        """
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(order_id=101, side=SIDE_BUY, price=500.0, quantity=100, timestamp_ns=1000)
        engine.submit_order(order_id=102, side=SIDE_BUY, price=510.0, quantity=50, timestamp_ns=2000)
        engine.submit_order(order_id=103, side=SIDE_BUY, price=505.0, quantity=80, timestamp_ns=3000)

        best_buy = engine.get_best_buy_order()
        assert best_buy is not None
        assert best_buy.order_id == 102
        assert best_buy.price == 510.0
        assert best_buy.price_cents == 51000
        assert best_buy.quantity == 50

        assert engine.get_best_buy_price() == 510.0
        assert engine.get_best_buy_price_cents() == 51000

    def test_single_buy_order_is_best(self):
        """A single submitted BUY order must be the best BUY order."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        order = engine.submit_order(1, SIDE_BUY, 250.25, 10, 1000)
        assert engine.get_best_buy_order() is order
        assert engine.get_best_buy_price() == 250.25
        assert engine.get_best_buy_price_cents() == 25025

    def test_buy_price_priority_aliases(self):
        """Verify all best-bid / best-buy alias methods return consistent results."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 10, 100)
        engine.submit_order(2, SIDE_BUY, 120.0, 10, 200)

        best = engine.get_best_buy_order()
        assert engine.get_best_bid() is best
        assert engine.get_best_bid_order() is best
        assert engine.best_buy_order() is best
        assert engine.best_bid() is best

        assert engine.get_best_buy_price() == 120.0
        assert engine.get_best_bid_price() == 120.0
        assert engine.best_buy_price() == 120.0
        assert engine.best_bid_price() == 120.0
        assert engine.get_best_buy_price_cents() == 12000
        assert engine.get_best_bid_price_cents() == 12000

    def test_equal_highest_buy_prices_preserve_arrival_order(self):
        """When multiple BUY orders share the highest price, the earlier arrival has priority."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        # Order 1 arrives first at 500.0
        engine.submit_order(order_id=1, side=SIDE_BUY, price=500.0, quantity=100, timestamp_ns=1000)
        # Order 2 arrives later with the same price 500.0
        engine.submit_order(order_id=2, side=SIDE_BUY, price=500.0, quantity=50, timestamp_ns=2000)
        # Order 3 arrives with lower price 490.0
        engine.submit_order(order_id=3, side=SIDE_BUY, price=490.0, quantity=75, timestamp_ns=3000)

        best = engine.get_best_buy_order()
        assert best is not None
        assert best.order_id == 1
        assert best.sequence_num == 1
        assert best.quantity == 100


# ---------------------------------------------------------------------------
# 14. Lowest SELL price selection
# ---------------------------------------------------------------------------
class TestLowestSellPriceSelection:
    """Verify that the lowest SELL price has the highest priority."""

    def test_lowest_sell_price_spec_example(self):
        """Spec example:
        SELL order 201: price 515, quantity 100
        SELL order 202: price 508, quantity 40
        SELL order 203: price 520, quantity 80
        Expected best SELL order: Order 202, price 508.
        """
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(order_id=201, side=SIDE_SELL, price=515.0, quantity=100, timestamp_ns=1000)
        engine.submit_order(order_id=202, side=SIDE_SELL, price=508.0, quantity=40, timestamp_ns=2000)
        engine.submit_order(order_id=203, side=SIDE_SELL, price=520.0, quantity=80, timestamp_ns=3000)

        best_sell = engine.get_best_sell_order()
        assert best_sell is not None
        assert best_sell.order_id == 202
        assert best_sell.price == 508.0
        assert best_sell.price_cents == 50800
        assert best_sell.quantity == 40

        assert engine.get_best_sell_price() == 508.0
        assert engine.get_best_sell_price_cents() == 50800

    def test_single_sell_order_is_best(self):
        """A single submitted SELL order must be the best SELL order."""
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        order = engine.submit_order(1, SIDE_SELL, 305.50, 15, 1000)
        assert engine.get_best_sell_order() is order
        assert engine.get_best_sell_price() == 305.50
        assert engine.get_best_sell_price_cents() == 30550

    def test_sell_price_priority_aliases(self):
        """Verify all best-ask / best-sell alias methods return consistent results."""
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 200.0, 10, 100)
        engine.submit_order(2, SIDE_SELL, 180.0, 10, 200)

        best = engine.get_best_sell_order()
        assert engine.get_best_ask() is best
        assert engine.get_best_ask_order() is best
        assert engine.best_sell_order() is best
        assert engine.best_ask() is best

        assert engine.get_best_sell_price() == 180.0
        assert engine.get_best_ask_price() == 180.0
        assert engine.best_sell_price() == 180.0
        assert engine.best_ask_price() == 180.0
        assert engine.get_best_sell_price_cents() == 18000
        assert engine.get_best_ask_price_cents() == 18000

    def test_equal_lowest_sell_prices_preserve_arrival_order(self):
        """When multiple SELL orders share the lowest price, the earlier arrival has priority."""
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        # Order 1 arrives first at 508.0
        engine.submit_order(order_id=10, side=SIDE_SELL, price=508.0, quantity=40, timestamp_ns=1000)
        # Order 2 arrives later with the same price 508.0
        engine.submit_order(order_id=20, side=SIDE_SELL, price=508.0, quantity=90, timestamp_ns=2000)
        # Order 3 arrives with higher price 520.0
        engine.submit_order(order_id=30, side=SIDE_SELL, price=520.0, quantity=60, timestamp_ns=3000)

        best = engine.get_best_sell_order()
        assert best is not None
        assert best.order_id == 10
        assert best.sequence_num == 1
        assert best.quantity == 40


# ---------------------------------------------------------------------------
# 15. Random order insertion
# ---------------------------------------------------------------------------
class TestRandomOrderInsertion:
    """Verify that price priority does not depend on insertion order."""

    def test_buy_prices_inserted_in_random_order(self):
        """Highest BUY order is correctly selected regardless of insertion order."""
        import random
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        rng = random.Random(42)
        prices = [round(rng.uniform(10.0, 500.0), 2) for _ in range(50)]
        max_price = max(prices)

        engine = MatchingEngine()
        for i, price in enumerate(prices, start=1):
            engine.submit_order(order_id=i, side=SIDE_BUY, price=price, quantity=10, timestamp_ns=i * 1000)

        best_buy = engine.get_best_buy_order()
        assert best_buy is not None
        assert best_buy.price == max_price
        assert engine.get_best_buy_price() == max_price

    def test_sell_prices_inserted_in_random_order(self):
        """Lowest SELL order is correctly selected regardless of insertion order."""
        import random
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        rng = random.Random(42)
        prices = [round(rng.uniform(10.0, 500.0), 2) for _ in range(50)]
        min_price = min(prices)

        engine = MatchingEngine()
        for i, price in enumerate(prices, start=1):
            engine.submit_order(order_id=i, side=SIDE_SELL, price=price, quantity=10, timestamp_ns=i * 1000)

        best_sell = engine.get_best_sell_order()
        assert best_sell is not None
        assert best_sell.price == min_price
        assert engine.get_best_sell_price() == min_price


# ---------------------------------------------------------------------------
# 16. Empty order book priority inspection
# ---------------------------------------------------------------------------
class TestEmptyOrderBookPriority:
    """Verify empty-book behavior for price priority inspection methods."""

    def test_empty_buy_order_book(self):
        """Empty BUY book yields None for best BUY order and prices."""
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.get_best_buy_order() is None
        assert engine.get_best_bid() is None
        assert engine.get_best_buy_price() is None
        assert engine.get_best_bid_price() is None
        assert engine.get_best_buy_price_cents() is None
        assert engine.get_best_bid_price_cents() is None

    def test_empty_sell_order_book(self):
        """Empty SELL book yields None for best SELL order and prices."""
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.get_best_sell_order() is None
        assert engine.get_best_ask() is None
        assert engine.get_best_sell_price() is None
        assert engine.get_best_ask_price() is None
        assert engine.get_best_sell_price_cents() is None
        assert engine.get_best_ask_price_cents() is None

    def test_empty_book_crossing_detection(self):
        """Crossing detection returns False when either or both books are empty."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        # Both empty
        assert engine.has_crossing_prices() is False
        assert engine.crossing_prices() is False

        # Only BUY orders present
        engine.submit_order(1, SIDE_BUY, 100.0, 10, 1000)
        assert engine.has_crossing_prices() is False
        assert engine.crossing_prices() is False

        # Clear and only SELL orders present
        engine.clear()
        engine.submit_order(2, SIDE_SELL, 90.0, 10, 2000)
        assert engine.has_crossing_prices() is False
        assert engine.crossing_prices() is False

    def test_cleared_engine_resets_best_orders(self):
        """After clear(), best order inspection returns None again."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 150.0, 10, 1000)
        engine.submit_order(2, SIDE_SELL, 140.0, 10, 2000)
        assert engine.get_best_buy_order() is not None
        assert engine.get_best_sell_order() is not None
        assert engine.has_crossing_prices() is True

        engine.clear()
        assert engine.get_best_buy_order() is None
        assert engine.get_best_sell_order() is None
        assert engine.get_best_buy_price() is None
        assert engine.get_best_sell_price() is None
        assert engine.has_crossing_prices() is False


# ---------------------------------------------------------------------------
# 17. Crossing-price detection
# ---------------------------------------------------------------------------
class TestCrossingPriceDetection:
    """Verify crossing-price detection logic (BUY price >= SELL price)."""

    def test_crossing_prices_higher_buy(self):
        """BUY 510, SELL 508: Crossing prices = True."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 510.0, 50, 1000)
        engine.submit_order(2, SIDE_SELL, 508.0, 40, 2000)

        assert engine.has_crossing_prices() is True
        assert engine.crossing_prices() is True
        assert engine.has_crossing_price() is True
        assert engine.is_crossed() is True
        assert engine.can_match() is True

    def test_non_crossing_prices(self):
        """BUY 500, SELL 505: Crossing prices = False."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 500.0, 50, 1000)
        engine.submit_order(2, SIDE_SELL, 505.0, 40, 2000)

        assert engine.has_crossing_prices() is False
        assert engine.crossing_prices() is False
        assert engine.has_crossing_price() is False
        assert engine.is_crossed() is False
        assert engine.can_match() is False

    def test_equal_buy_and_sell_prices(self):
        """BUY 500, SELL 500: Crossing prices = True."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 500.0, 50, 1000)
        engine.submit_order(2, SIDE_SELL, 500.0, 40, 2000)

        assert engine.has_crossing_prices() is True
        assert engine.crossing_prices() is True

    def test_crossing_with_multiple_orders_on_both_sides(self):
        """Engine correctly tests the best prices when multiple orders exist."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        # Bids: 480, 490, 502 -> Best BUY = 502
        engine.submit_order(1, SIDE_BUY, 480.0, 10, 100)
        engine.submit_order(2, SIDE_BUY, 490.0, 20, 200)
        engine.submit_order(3, SIDE_BUY, 502.0, 30, 300)

        # Asks: 510, 505, 501 -> Best SELL = 501
        engine.submit_order(4, SIDE_SELL, 510.0, 15, 400)
        engine.submit_order(5, SIDE_SELL, 505.0, 25, 500)
        engine.submit_order(6, SIDE_SELL, 501.0, 35, 600)

        # 502 >= 501 -> True
        assert engine.has_crossing_prices() is True

        # Now add a new ask at 503 -> Best ask is still 501 -> Still True
        engine.submit_order(7, SIDE_SELL, 503.0, 10, 700)
        assert engine.get_best_sell_price() == 501.0
        assert engine.has_crossing_prices() is True


# ---------------------------------------------------------------------------
# 18. Order data preservation during inspection
# ---------------------------------------------------------------------------
class TestPreserveOrderDataOnPriorityInspection:
    """Verify that price-priority inspection does not modify stored orders."""

    def test_inspection_does_not_modify_order_book(self):
        """Calling price priority inspection methods must preserve order state."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(101, SIDE_BUY, 500.0, 100, 1000)
        engine.submit_order(102, SIDE_BUY, 510.0, 50, 2000)
        engine.submit_order(103, SIDE_BUY, 505.0, 80, 3000)

        engine.submit_order(201, SIDE_SELL, 515.0, 100, 4000)
        engine.submit_order(202, SIDE_SELL, 508.0, 40, 5000)
        engine.submit_order(203, SIDE_SELL, 520.0, 80, 6000)

        # Snapshot before inspection
        before_bids_data = [
            (b.order_id, b.side, b.price_cents, b.quantity, b.timestamp_ns, b.sequence_num)
            for b in engine.get_bids()
        ]
        before_asks_data = [
            (a.order_id, a.side, a.price_cents, a.quantity, a.timestamp_ns, a.sequence_num)
            for a in engine.get_asks()
        ]
        before_order_count = engine.order_count()
        before_bid_count = engine.bid_count()
        before_ask_count = engine.ask_count()

        # Perform multiple inspections
        for _ in range(5):
            _ = engine.get_best_buy_order()
            _ = engine.get_best_sell_order()
            _ = engine.get_best_buy_price()
            _ = engine.get_best_sell_price()
            _ = engine.get_best_buy_price_cents()
            _ = engine.get_best_sell_price_cents()
            _ = engine.has_crossing_prices()
            _ = engine.crossing_prices()

        # Snapshot after inspection
        after_bids_data = [
            (b.order_id, b.side, b.price_cents, b.quantity, b.timestamp_ns, b.sequence_num)
            for b in engine.get_bids()
        ]
        after_asks_data = [
            (a.order_id, a.side, a.price_cents, a.quantity, a.timestamp_ns, a.sequence_num)
            for a in engine.get_asks()
        ]

        assert engine.order_count() == before_order_count
        assert engine.bid_count() == before_bid_count
        assert engine.ask_count() == before_ask_count
        assert after_bids_data == before_bids_data
        assert after_asks_data == before_asks_data

    def test_inspection_is_idempotent(self):
        """Repeated inspection queries return the exact same objects and values."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        b = engine.submit_order(1, SIDE_BUY, 100.0, 10, 100)
        a = engine.submit_order(2, SIDE_SELL, 90.0, 10, 200)

        for _ in range(3):
            assert engine.get_best_buy_order() is b
            assert engine.get_best_sell_order() is a
            assert engine.get_best_buy_price() == 100.0
            assert engine.get_best_sell_price() == 90.0
            assert engine.has_crossing_prices() is True


