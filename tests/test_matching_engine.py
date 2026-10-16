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
            "remaining_quantity": 10,
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


# ===========================================================================
# Day 4: Time Priority (FIFO) & Price-Time Priority Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 19. Two BUY orders at equal prices
# ---------------------------------------------------------------------------
class TestTwoBuyOrdersEqualPrice:
    """Verify FIFO ordering when two BUY orders arrive with identical prices."""

    def test_two_buy_orders_equal_prices_first_arrived_selected(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        o1 = engine.submit_order(101, SIDE_BUY, 500.0, 100, timestamp_ns=1000)
        o2 = engine.submit_order(102, SIDE_BUY, 500.0, 50, timestamp_ns=2000)

        best = engine.get_best_buy_order()
        assert best is o1
        assert best.order_id == 101

        prioritized = engine.get_prioritized_bids()
        assert len(prioritized) == 2
        assert prioritized[0] is o1
        assert prioritized[1] is o2

        # Check get_bids(priority=True) returns prioritized
        assert engine.get_bids(priority=True) == [o1, o2]
        # Check raw get_bids() returns arrival sequence
        assert engine.get_bids() == [o1, o2]

    def test_two_buy_orders_equal_prices_reverse_id_first_arrived_selected(self):
        """Arrival sequence determines priority, not order_id magnitude."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        # Order with larger ID arrives first
        o1 = engine.submit_order(999, SIDE_BUY, 250.0, 10, timestamp_ns=1000)
        o2 = engine.submit_order(111, SIDE_BUY, 250.0, 20, timestamp_ns=2000)

        best = engine.get_best_buy_order()
        assert best is o1
        assert best.order_id == 999
        assert engine.get_prioritized_bids() == [o1, o2]


# ---------------------------------------------------------------------------
# 20. Three BUY orders at equal prices (Spec Example)
# ---------------------------------------------------------------------------
class TestThreeBuyOrdersEqualPrice:
    """Verify FIFO ordering with three BUY orders at identical price levels."""

    def test_three_buy_orders_spec_example(self):
        """Spec example:
        Order 101: BUY, price 500, quantity 100, arrival first.
        Order 102: BUY, price 500, quantity 50, arrival second.
        Order 103: BUY, price 500, quantity 80, arrival third.
        Expected order priority: 101, then 102, then 103.
        """
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        o101 = engine.submit_order(101, SIDE_BUY, 500.0, 100, timestamp_ns=1000)
        o102 = engine.submit_order(102, SIDE_BUY, 500.0, 50, timestamp_ns=2000)
        o103 = engine.submit_order(103, SIDE_BUY, 500.0, 80, timestamp_ns=3000)

        assert engine.get_best_buy_order() is o101
        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [101, 102, 103]
        assert [o.quantity for o in prioritized] == [100, 50, 80]
        assert engine.get_bids(priority=True) == [o101, o102, o103]


# ---------------------------------------------------------------------------
# 21. Two SELL orders at equal prices
# ---------------------------------------------------------------------------
class TestTwoSellOrdersEqualPrice:
    """Verify FIFO ordering when SELL orders arrive with identical prices."""

    def test_two_sell_orders_equal_prices_first_arrived_selected(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        o1 = engine.submit_order(201, SIDE_SELL, 300.0, 40, timestamp_ns=1000)
        o2 = engine.submit_order(202, SIDE_SELL, 300.0, 60, timestamp_ns=2000)

        best = engine.get_best_sell_order()
        assert best is o1
        assert best.order_id == 201

        prioritized = engine.get_prioritized_asks()
        assert len(prioritized) == 2
        assert prioritized[0] is o1
        assert prioritized[1] is o2
        assert engine.get_asks(priority=True) == [o1, o2]

    def test_three_sell_orders_equal_prices_fifo(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        o1 = engine.submit_order(201, SIDE_SELL, 450.0, 100, timestamp_ns=1000)
        o2 = engine.submit_order(202, SIDE_SELL, 450.0, 50, timestamp_ns=2000)
        o3 = engine.submit_order(203, SIDE_SELL, 450.0, 80, timestamp_ns=3000)

        assert engine.get_best_sell_order() is o1
        prioritized = engine.get_prioritized_asks()
        assert [o.order_id for o in prioritized] == [201, 202, 203]


# ---------------------------------------------------------------------------
# 22. Different BUY prices overriding arrival order
# ---------------------------------------------------------------------------
class TestDifferentBuyPricesOverrideArrival:
    """Verify that a higher BUY price strictly overrides arrival order."""

    def test_buy_price_overrides_arrival_spec_example(self):
        """Spec example:
        Order 101: price 500, first arrival
        Order 102: price 510, second arrival
        Order 103: price 510, third arrival
        Expected selection order: 102, 103, 101.
        Time priority must never override a better price.
        """
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        o101 = engine.submit_order(101, SIDE_BUY, 500.0, 100, timestamp_ns=1000)
        o102 = engine.submit_order(102, SIDE_BUY, 510.0, 50, timestamp_ns=2000)
        o103 = engine.submit_order(103, SIDE_BUY, 510.0, 80, timestamp_ns=3000)

        # 102 has higher price than 101, and earlier arrival than 103
        assert engine.get_best_buy_order() is o102

        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [102, 103, 101]
        assert [o.price for o in prioritized] == [510.0, 510.0, 500.0]

    def test_higher_buy_price_arriving_last_gets_top_priority(self):
        """A BUY order arriving last with the highest price gets top priority."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        o1 = engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=1000)
        o2 = engine.submit_order(2, SIDE_BUY, 100.0, 10, timestamp_ns=2000)
        o3 = engine.submit_order(3, SIDE_BUY, 105.0, 10, timestamp_ns=3000)

        assert engine.get_best_buy_order() is o3
        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [3, 1, 2]


# ---------------------------------------------------------------------------
# 23. Different SELL prices overriding arrival order
# ---------------------------------------------------------------------------
class TestDifferentSellPricesOverrideArrival:
    """Verify that a lower SELL price strictly overrides arrival order."""

    def test_sell_price_overrides_arrival_spec_example(self):
        """Spec example:
        Order 201: price 520, first arrival
        Order 202: price 510, second arrival
        Order 203: price 510, third arrival
        Expected selection order: 202, 203, 201.
        Time priority must never override a better (lower) SELL price.
        """
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        o201 = engine.submit_order(201, SIDE_SELL, 520.0, 100, timestamp_ns=1000)
        o202 = engine.submit_order(202, SIDE_SELL, 510.0, 40, timestamp_ns=2000)
        o203 = engine.submit_order(203, SIDE_SELL, 510.0, 80, timestamp_ns=3000)

        # 202 has lower price than 201, and earlier arrival than 203
        assert engine.get_best_sell_order() is o202

        prioritized = engine.get_prioritized_asks()
        assert [o.order_id for o in prioritized] == [202, 203, 201]
        assert [o.price for o in prioritized] == [510.0, 510.0, 520.0]

    def test_lower_sell_price_arriving_last_gets_top_priority(self):
        """A SELL order arriving last with the lowest price gets top priority."""
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        o1 = engine.submit_order(1, SIDE_SELL, 200.0, 10, timestamp_ns=1000)
        o2 = engine.submit_order(2, SIDE_SELL, 200.0, 10, timestamp_ns=2000)
        o3 = engine.submit_order(3, SIDE_SELL, 195.0, 10, timestamp_ns=3000)

        assert engine.get_best_sell_order() is o3
        prioritized = engine.get_prioritized_asks()
        assert [o.order_id for o in prioritized] == [3, 1, 2]


# ---------------------------------------------------------------------------
# 24. Interleaved BUY and SELL arrivals
# ---------------------------------------------------------------------------
class TestInterleavedBuySellArrivals:
    """Verify price-time priority remains independent for bids and asks when interleaved."""

    def test_interleaved_arrivals_preserve_independent_priorities(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Interleaved order submission
        b1 = engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=100)
        s1 = engine.submit_order(2, SIDE_SELL, 105.0, 20, timestamp_ns=200)
        b2 = engine.submit_order(3, SIDE_BUY, 102.0, 15, timestamp_ns=300)
        b3 = engine.submit_order(4, SIDE_BUY, 102.0, 25, timestamp_ns=400)
        s2 = engine.submit_order(5, SIDE_SELL, 103.0, 30, timestamp_ns=500)
        s3 = engine.submit_order(6, SIDE_SELL, 103.0, 40, timestamp_ns=600)

        # Best BUY should be b2 (price 102, earlier than b3)
        assert engine.get_best_buy_order() is b2
        # Prioritized bids: b2 (102, ts 300), b3 (102, ts 400), b1 (100, ts 100)
        assert [b.order_id for b in engine.get_prioritized_bids()] == [3, 4, 1]

        # Best SELL should be s2 (price 103, earlier than s3)
        assert engine.get_best_sell_order() is s2
        # Prioritized asks: s2 (103, ts 500), s3 (103, ts 600), s1 (105, ts 200)
        assert [s.order_id for s in engine.get_prioritized_asks()] == [5, 6, 2]

        # Verify raw arrival storage is intact
        assert [b.order_id for b in engine.get_bids()] == [1, 3, 4]
        assert [s.order_id for s in engine.get_asks()] == [2, 5, 6]


# ---------------------------------------------------------------------------
# 25. Repeated priority inspection without state mutation
# ---------------------------------------------------------------------------
class TestRepeatedPriorityInspectionNoMutation:
    """Verify that multiple priority inspections do not modify stored state or order quantities."""

    def test_repeated_priority_inspection_immutability(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(101, SIDE_BUY, 500.0, 100, timestamp_ns=1000)
        engine.submit_order(102, SIDE_BUY, 510.0, 50, timestamp_ns=2000)
        engine.submit_order(103, SIDE_BUY, 510.0, 80, timestamp_ns=3000)
        engine.submit_order(201, SIDE_SELL, 520.0, 60, timestamp_ns=4000)
        engine.submit_order(202, SIDE_SELL, 515.0, 70, timestamp_ns=5000)

        # Baseline snapshot
        bids_before = [(b.order_id, b.price_cents, b.quantity, b.sequence_num) for b in engine.get_bids()]
        asks_before = [(a.order_id, a.price_cents, a.quantity, a.sequence_num) for a in engine.get_asks()]
        order_count_before = engine.order_count()

        # Perform 10 consecutive priority inspection calls
        for _ in range(10):
            p_bids = engine.get_prioritized_bids()
            p_asks = engine.get_prioritized_asks()
            best_buy = engine.get_best_buy_order()
            best_sell = engine.get_best_sell_order()

            assert [o.order_id for o in p_bids] == [102, 103, 101]
            assert [o.order_id for o in p_asks] == [202, 201]
            assert best_buy.order_id == 102
            assert best_sell.order_id == 202

        # Verify nothing mutated
        bids_after = [(b.order_id, b.price_cents, b.quantity, b.sequence_num) for b in engine.get_bids()]
        asks_after = [(a.order_id, a.price_cents, a.quantity, a.sequence_num) for a in engine.get_asks()]
        assert bids_after == bids_before
        assert asks_after == asks_before
        assert engine.order_count() == order_count_before

    def test_inspection_does_not_change_order_quantities(self):
        """Quantities must remain completely unchanged after priority inspection."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        b = engine.submit_order(1, SIDE_BUY, 100.0, 777, timestamp_ns=100)
        a = engine.submit_order(2, SIDE_SELL, 105.0, 888, timestamp_ns=200)

        _ = engine.get_prioritized_bids()
        _ = engine.get_prioritized_asks()
        _ = engine.get_best_buy_order()
        _ = engine.get_best_sell_order()

        assert b.quantity == 777
        assert a.quantity == 888
        assert engine.get_bids()[0].quantity == 777
        assert engine.get_asks()[0].quantity == 888


# ---------------------------------------------------------------------------
# 26. Empty order-book behavior
# ---------------------------------------------------------------------------
class TestEmptyOrderBookTimePriority:
    """Verify empty order-book behavior for time-priority inspection methods."""

    def test_empty_book_returns_empty_lists_and_none(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        assert engine.get_prioritized_bids() == []
        assert engine.get_prioritized_asks() == []
        assert engine.get_bids_by_priority() == []
        assert engine.get_asks_by_priority() == []
        assert engine.get_buy_orders_by_priority() == []
        assert engine.get_sell_orders_by_priority() == []
        assert engine.prioritized_bids() == []
        assert engine.prioritized_asks() == []
        assert engine.get_bids(priority=True) == []
        assert engine.get_asks(priority=True) == []
        assert engine.get_best_buy_order() is None
        assert engine.get_best_sell_order() is None

    def test_single_order_prioritized_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        o = engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=100)
        assert engine.get_prioritized_bids() == [o]
        assert engine.get_best_buy_order() is o


# ---------------------------------------------------------------------------
# 27. Existing price-priority behavior remains correct
# ---------------------------------------------------------------------------
class TestExistingPricePriorityRemainsCorrect:
    """Verify Day 3 price-priority and crossing detection functionality remains intact."""

    def test_day3_price_priority_bids_asks(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(101, SIDE_BUY, 500.0, 100, timestamp_ns=1000)
        engine.submit_order(102, SIDE_BUY, 510.0, 50, timestamp_ns=2000)
        engine.submit_order(103, SIDE_BUY, 505.0, 80, timestamp_ns=3000)

        engine.submit_order(201, SIDE_SELL, 515.0, 100, timestamp_ns=1000)
        engine.submit_order(202, SIDE_SELL, 508.0, 40, timestamp_ns=2000)
        engine.submit_order(203, SIDE_SELL, 520.0, 80, timestamp_ns=3000)

        assert engine.get_best_buy_order().order_id == 102
        assert engine.get_best_buy_price() == 510.0
        assert engine.get_best_buy_price_cents() == 51000

        assert engine.get_best_sell_order().order_id == 202
        assert engine.get_best_sell_price() == 508.0
        assert engine.get_best_sell_price_cents() == 50800

        assert engine.has_crossing_prices() is True
        assert engine.crossing_prices() is True

    def test_day3_aliases_still_work(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        b = engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=100)
        s = engine.submit_order(2, SIDE_SELL, 110.0, 10, timestamp_ns=200)

        assert engine.best_bid() is b
        assert engine.best_ask() is s
        assert engine.best_buy_price() == 100.0
        assert engine.best_sell_price() == 110.0
        assert engine.has_crossing_prices() is False


# ---------------------------------------------------------------------------
# 28. Deterministic order selection when arrival timestamps are equal
# ---------------------------------------------------------------------------
class TestDeterministicEqualTimestamps:
    """Verify deterministic FIFO selection when arrival timestamps are identical."""

    def test_equal_timestamps_broken_by_engine_arrival_sequence(self):
        """When multiple orders have identical timestamps, engine sequence_num preserves FIFO."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        # All orders have the exact same timestamp_ns (e.g. within same clock tick)
        same_ts = 1_700_000_000_000
        o1 = engine.submit_order(101, SIDE_BUY, 500.0, 100, timestamp_ns=same_ts)
        o2 = engine.submit_order(102, SIDE_BUY, 500.0, 50, timestamp_ns=same_ts)
        o3 = engine.submit_order(103, SIDE_BUY, 500.0, 80, timestamp_ns=same_ts)

        assert o1.sequence_num == 1
        assert o2.sequence_num == 2
        assert o3.sequence_num == 3

        best = engine.get_best_buy_order()
        assert best is o1
        assert best.order_id == 101

        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [101, 102, 103]

    def test_equal_timestamps_sell_side_broken_by_engine_sequence(self):
        """SELL orders with identical timestamps preserve deterministic FIFO order."""
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()

        same_ts = 2_500_000_000_000
        o1 = engine.submit_order(201, SIDE_SELL, 350.0, 30, timestamp_ns=same_ts)
        o2 = engine.submit_order(202, SIDE_SELL, 350.0, 40, timestamp_ns=same_ts)
        o3 = engine.submit_order(203, SIDE_SELL, 350.0, 50, timestamp_ns=same_ts)

        assert engine.get_best_sell_order() is o1
        assert [o.order_id for o in engine.get_prioritized_asks()] == [201, 202, 203]

    def test_equal_timestamps_with_mixed_prices(self):
        """Equal timestamps across mixed prices: price takes priority, FIFO within price level."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        same_ts = 3_000_000_000_000
        o1 = engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=same_ts)  # seq 1
        o2 = engine.submit_order(2, SIDE_BUY, 105.0, 20, timestamp_ns=same_ts)  # seq 2
        o3 = engine.submit_order(3, SIDE_BUY, 105.0, 30, timestamp_ns=same_ts)  # seq 3
        o4 = engine.submit_order(4, SIDE_BUY, 100.0, 40, timestamp_ns=same_ts)  # seq 4

        # Expected priority: 105 level (o2 then o3), followed by 100 level (o1 then o4)
        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [2, 3, 1, 4]
        assert engine.get_best_buy_order() is o2


# ===========================================================================
# Day 5: Partial Order Matching Tests
# ===========================================================================

class TestPartialMatchImport:
    """Verify Day 5 classes and methods can be imported and are available."""

    def test_import_trade_result(self):
        from chronos.matching_engine import TradeResult
        assert TradeResult is not None

    def test_import_execute_partial_match(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert hasattr(engine, "execute_partial_match")
        assert callable(engine.execute_partial_match)


class TestCOrderRemainingQuantityField:
    """Verify COrder remaining_quantity initialization and properties."""

    def test_initial_remaining_quantity_equals_quantity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        order = engine.submit_order(100, SIDE_BUY, 25.50, 75, timestamp_ns=1000)
        assert hasattr(order, "remaining_quantity")
        assert order.remaining_quantity == 75
        assert order.quantity == 75

    def test_order_as_dict_contains_remaining_quantity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        order = engine.submit_order(101, SIDE_SELL, 30.00, 50, timestamp_ns=2000)
        d = order.as_dict()
        assert "remaining_quantity" in d
        assert d["remaining_quantity"] == 50
        assert d["quantity"] == 50


class TestPartialMatchBuyGreaterThanSell:
    """BUY qty > SELL qty: SELL fully fills, BUY partially fills."""

    def test_buy_100_sell_40_equal_price(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        sell = engine.submit_order(2, SIDE_SELL, 5.00, 40, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.executed_quantity == 40
        assert trade.buy_remaining_quantity == 60
        assert trade.sell_remaining_quantity == 0
        assert trade.buy_order_id == 1
        assert trade.sell_order_id == 2
        assert trade.execution_price_cents == 500
        assert trade.execution_price == 5.00

        # BUY remains in book with updated remaining_quantity; original quantity untouched
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert buy.remaining_quantity == 60
        assert buy.quantity == 100
        assert sell.remaining_quantity == 0
        assert sell.quantity == 40

    def test_buy_remaining_quantity_updated(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(10, SIDE_BUY, 10.00, 200, timestamp_ns=100)
        engine.submit_order(20, SIDE_SELL, 10.00, 50, timestamp_ns=200)

        trade = engine.execute_partial_match()
        assert trade.executed_quantity == 50
        assert buy.remaining_quantity == 150
        assert engine.bid_count() == 1


class TestPartialMatchSellGreaterThanBuy:
    """SELL qty > BUY qty: BUY fully fills, SELL partially fills."""

    def test_buy_30_sell_100_equal_price(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(1, SIDE_BUY, 5.00, 30, timestamp_ns=1000)
        sell = engine.submit_order(2, SIDE_SELL, 5.00, 100, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.executed_quantity == 30
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 70
        assert trade.buy_order_id == 1
        assert trade.sell_order_id == 2
        assert trade.execution_price_cents == 500

        # BUY fully filled (removed), SELL partially filled (remains in book)
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        assert sell.remaining_quantity == 70
        assert sell.quantity == 100
        assert buy.remaining_quantity == 0
        assert buy.quantity == 30


class TestPartialMatchEqualQuantities:
    """Equal quantities: both orders fully fill, both removed from book."""

    def test_equal_quantities_both_removed(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(1, SIDE_BUY, 5.00, 50, timestamp_ns=1000)
        sell = engine.submit_order(2, SIDE_SELL, 5.00, 50, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.executed_quantity == 50
        assert trade.buy_remaining_quantity == 0
        assert trade.sell_remaining_quantity == 0
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert buy.remaining_quantity == 0
        assert sell.remaining_quantity == 0


class TestPartialMatchCrossingPrice:
    """BUY price > SELL price: trade executes at resting SELL price."""

    def test_crossing_price_executes_at_sell_price(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 10.00, 100, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 9.00, 40, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.execution_price_cents == 900   # Resting SELL price
        assert trade.execution_price == 9.00
        assert trade.executed_quantity == 40

    def test_crossing_price_at_cent_precision(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 50.25, 10, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 50.10, 10, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.execution_price_cents == 5010
        assert trade.execution_price == 50.10


class TestNonCrossingPricesNoExecution:
    """BUY price < SELL price: no trade should occur."""

    def test_no_match_when_prices_dont_cross(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 6.00, 100, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is None
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1

    def test_no_match_empty_sell_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        trade = engine.execute_partial_match()
        assert trade is None

    def test_no_match_empty_buy_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(2, SIDE_SELL, 5.00, 100, timestamp_ns=1000)
        trade = engine.execute_partial_match()
        assert trade is None

    def test_no_match_empty_engine(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        trade = engine.execute_partial_match()
        assert trade is None


class TestNoNegativeQuantities:
    """Remaining quantities must never go negative."""

    def test_remaining_quantities_non_negative(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(1, SIDE_BUY, 5.00, 50, timestamp_ns=1000)
        sell = engine.submit_order(2, SIDE_SELL, 5.00, 50, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert buy.remaining_quantity >= 0
        assert sell.remaining_quantity >= 0
        assert trade.buy_remaining_quantity >= 0
        assert trade.sell_remaining_quantity >= 0


class TestTradeResultOrderIDs:
    """TradeResult must carry the correct BUY and SELL order IDs."""

    def test_correct_order_ids_in_trade_result(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(42, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        engine.submit_order(99, SIDE_SELL, 5.00, 30, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade.buy_order_id == 42
        assert trade.sell_order_id == 99


class TestPartialFillTimePriority:
    """Partially filled resting orders retain their original time priority."""

    def test_partially_filled_order_retains_sequence_num(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy1 = engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        buy2 = engine.submit_order(2, SIDE_BUY, 5.00, 50, timestamp_ns=2000)
        engine.submit_order(3, SIDE_SELL, 5.00, 40, timestamp_ns=3000)

        seq_before = buy1.sequence_num
        trade = engine.execute_partial_match()
        assert trade is not None
        assert buy1.sequence_num == seq_before   # sequence_num unchanged
        # buy1 is still in book with priority over buy2
        bids = engine.get_bids(priority=True)
        assert bids[0].order_id == 1   # buy1 still has first FIFO priority

    def test_partial_fill_does_not_change_priority_order(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy_early = engine.submit_order(10, SIDE_BUY, 5.00, 200, timestamp_ns=1000)
        buy_late  = engine.submit_order(20, SIDE_BUY, 5.00, 100, timestamp_ns=2000)
        engine.submit_order(30, SIDE_SELL, 5.00, 50, timestamp_ns=3000)

        # buy_early should be matched first (earlier FIFO)
        trade = engine.execute_partial_match()
        assert trade.buy_order_id == 10
        assert buy_early.remaining_quantity == 150
        # buy_early still top priority
        assert engine.get_best_buy_order().order_id == 10

    def test_ask_partially_filled_retains_sequence_num(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        sell1 = engine.submit_order(101, SIDE_SELL, 10.00, 200, timestamp_ns=1000)
        sell2 = engine.submit_order(102, SIDE_SELL, 10.00, 100, timestamp_ns=2000)
        engine.submit_order(201, SIDE_BUY, 10.00, 50, timestamp_ns=3000)

        seq_before = sell1.sequence_num
        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.sell_order_id == 101
        assert sell1.sequence_num == seq_before
        assert sell1.remaining_quantity == 150
        assert engine.get_best_sell_order().order_id == 101


class TestFullyFilledCounterpartRemoved:
    """Fully filled counterpart must be removed from the book."""

    def test_fully_filled_sell_removed(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        sell = engine.submit_order(2, SIDE_SELL, 5.00, 40, timestamp_ns=2000)

        engine.execute_partial_match()
        assert sell.remaining_quantity == 0
        assert all(o.order_id != 2 for o in engine.get_asks())

    def test_fully_filled_buy_removed(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(1, SIDE_BUY, 5.00, 30, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 5.00, 100, timestamp_ns=2000)

        engine.execute_partial_match()
        assert buy.remaining_quantity == 0
        assert all(o.order_id != 1 for o in engine.get_bids())


class TestPriceTimePriorityPreservedAfterPartialFill:
    """Price-time priority still selects the best order after partial fills."""

    def test_price_priority_still_selects_best_after_partial_fill(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy_high = engine.submit_order(1, SIDE_BUY, 10.00, 50, timestamp_ns=1000)
        buy_low  = engine.submit_order(2, SIDE_BUY, 9.00, 200, timestamp_ns=2000)
        engine.submit_order(3, SIDE_SELL, 9.00, 30, timestamp_ns=3000)

        trade = engine.execute_partial_match()
        # buy_high (price 10) has priority; trade executes against it
        assert trade.buy_order_id == 1
        assert buy_high.remaining_quantity == 20
        # After partial fill, buy_high (rem=20) still has price priority over buy_low
        assert engine.get_best_buy_order().order_id == 1


class TestTradeResultAsDictAndRepr:
    """TradeResult attributes, as_dict(), and __repr__()."""

    def test_trade_result_as_dict(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 5.00, 40, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        d = trade.as_dict()
        assert d["buy_order_id"] == 1
        assert d["sell_order_id"] == 2
        assert d["executed_quantity"] == 40
        assert d["execution_price_cents"] == 500
        assert d["execution_price"] == 5.00
        assert d["buy_remaining_quantity"] == 60
        assert d["sell_remaining_quantity"] == 0

    def test_trade_result_repr(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 5.00, 40, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        r = repr(trade)
        assert "TradeResult" in r
        assert "buy=1" in r
        assert "sell=2" in r
        assert "exec_qty=40" in r


