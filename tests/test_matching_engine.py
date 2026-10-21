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


# ===========================================================================
# Day 6: Multi-Order Matching Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 29. match_order import and availability
# ---------------------------------------------------------------------------
class TestMatchOrderImport:
    """Verify match_order method is available on the engine."""

    def test_match_order_method_exists(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert hasattr(engine, "match_order")
        assert callable(engine.match_order)


# ---------------------------------------------------------------------------
# 30. Incoming BUY matching multiple resting SELL orders (Step 6 spec example)
# ---------------------------------------------------------------------------
class TestIncomingBuyMultipleSells:
    """Incoming BUY sweeps across multiple resting SELL orders."""

    def test_spec_example_buy_sweeps_three_sells(self):
        """Spec example from Step 6:
        Resting SELL #201: price 500, quantity 30
        Resting SELL #202: price 505, quantity 40
        Resting SELL #203: price 510, quantity 50

        Incoming BUY: price 510, quantity 100.

        Expected:
        - Fill 30 against #201 at 500
        - Fill 40 against #202 at 505
        - Fill 30 against #203 at 510
        - 20 of SELL #203 left in book
        - No remaining BUY quantity
        """
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(201, SIDE_SELL, 5.00, 30, timestamp_ns=1000)
        engine.submit_order(202, SIDE_SELL, 5.05, 40, timestamp_ns=2000)
        engine.submit_order(203, SIDE_SELL, 5.10, 50, timestamp_ns=3000)

        trades = engine.match_order(
            order_id=301, side=SIDE_BUY, price=5.10, quantity=100, timestamp_ns=4000
        )

        assert len(trades) == 3

        # First fill: against #201 at 500 cents
        assert trades[0].buy_order_id == 301
        assert trades[0].sell_order_id == 201
        assert trades[0].executed_quantity == 30
        assert trades[0].execution_price_cents == 500

        # Second fill: against #202 at 505 cents
        assert trades[1].buy_order_id == 301
        assert trades[1].sell_order_id == 202
        assert trades[1].executed_quantity == 40
        assert trades[1].execution_price_cents == 505

        # Third fill: against #203 at 510 cents
        assert trades[2].buy_order_id == 301
        assert trades[2].sell_order_id == 203
        assert trades[2].executed_quantity == 30
        assert trades[2].execution_price_cents == 510

        # SELL #203 partially filled: 50 - 30 = 20 left
        asks = engine.get_asks()
        assert len(asks) == 1
        assert asks[0].order_id == 203
        assert asks[0].remaining_quantity == 20

        # No incoming BUY resting in book (fully filled)
        assert engine.bid_count() == 0

    def test_buy_sweeps_two_sells_exact_fill(self):
        """Incoming BUY exactly matches total resting SELL quantity."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 50, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.50, 50, timestamp_ns=200)

        trades = engine.match_order(
            order_id=10, side=SIDE_BUY, price=10.50, quantity=100, timestamp_ns=300
        )

        assert len(trades) == 2
        total_exec = sum(t.executed_quantity for t in trades)
        assert total_exec == 100
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0


# ---------------------------------------------------------------------------
# 31. Incoming SELL matching multiple resting BUY orders
# ---------------------------------------------------------------------------
class TestIncomingSellMultipleBuys:
    """Incoming SELL sweeps across multiple resting BUY orders."""

    def test_sell_sweeps_three_buys(self):
        """Mirror of the spec example for incoming SELL.
        Resting BUY #101: price 510, quantity 30
        Resting BUY #102: price 505, quantity 40
        Resting BUY #103: price 500, quantity 50

        Incoming SELL: price 500, quantity 100.

        Expected:
        - Fill 30 against #101 at 510 (highest buy first)
        - Fill 40 against #102 at 505
        - Fill 30 against #103 at 500
        - 20 of BUY #103 left in book
        """
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(101, SIDE_BUY, 5.10, 30, timestamp_ns=1000)
        engine.submit_order(102, SIDE_BUY, 5.05, 40, timestamp_ns=2000)
        engine.submit_order(103, SIDE_BUY, 5.00, 50, timestamp_ns=3000)

        trades = engine.match_order(
            order_id=401, side=SIDE_SELL, price=5.00, quantity=100, timestamp_ns=4000
        )

        assert len(trades) == 3

        # First fill: against #101 at 510 cents (highest BUY price)
        assert trades[0].sell_order_id == 401
        assert trades[0].buy_order_id == 101
        assert trades[0].executed_quantity == 30
        assert trades[0].execution_price_cents == 510

        # Second fill: against #102 at 505 cents
        assert trades[1].buy_order_id == 102
        assert trades[1].executed_quantity == 40
        assert trades[1].execution_price_cents == 505

        # Third fill: against #103 at 500 cents
        assert trades[2].buy_order_id == 103
        assert trades[2].executed_quantity == 30
        assert trades[2].execution_price_cents == 500

        # BUY #103 partially filled
        bids = engine.get_bids()
        assert len(bids) == 1
        assert bids[0].order_id == 103
        assert bids[0].remaining_quantity == 20

        # No incoming SELL resting
        assert engine.ask_count() == 0


# ---------------------------------------------------------------------------
# 32. Highest BUY and lowest SELL price priority
# ---------------------------------------------------------------------------
class TestMultiMatchPricePriority:
    """Verify price priority in multi-order matching."""

    def test_buy_matches_lowest_sell_first(self):
        """Incoming BUY should match lowest SELL price first."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        # Insert in non-price order
        engine.submit_order(3, SIDE_SELL, 12.00, 10, timestamp_ns=100)
        engine.submit_order(1, SIDE_SELL, 10.00, 10, timestamp_ns=200)
        engine.submit_order(2, SIDE_SELL, 11.00, 10, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=12.00, quantity=30, timestamp_ns=400
        )
        assert len(trades) == 3
        assert trades[0].execution_price_cents == 1000  # $10.00 first
        assert trades[1].execution_price_cents == 1100  # $11.00 second
        assert trades[2].execution_price_cents == 1200  # $12.00 third

    def test_sell_matches_highest_buy_first(self):
        """Incoming SELL should match highest BUY price first."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 10.00, 10, timestamp_ns=100)
        engine.submit_order(3, SIDE_BUY, 12.00, 10, timestamp_ns=200)
        engine.submit_order(2, SIDE_BUY, 11.00, 10, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_SELL, price=10.00, quantity=30, timestamp_ns=400
        )
        assert len(trades) == 3
        assert trades[0].execution_price_cents == 1200  # $12.00 first
        assert trades[1].execution_price_cents == 1100  # $11.00 second
        assert trades[2].execution_price_cents == 1000  # $10.00 third


# ---------------------------------------------------------------------------
# 33. FIFO across multiple orders at equal prices
# ---------------------------------------------------------------------------
class TestMultiMatchFIFOEqualPrices:
    """Verify FIFO ordering within the same price level during multi-match."""

    def test_buy_fifo_at_equal_sell_prices(self):
        """Earlier SELL at the same price matches first."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 20, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.00, 20, timestamp_ns=200)
        engine.submit_order(3, SIDE_SELL, 10.00, 20, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.00, quantity=50, timestamp_ns=400
        )
        assert len(trades) == 3
        # FIFO: order 1 first, then 2, then 3
        assert trades[0].sell_order_id == 1
        assert trades[0].executed_quantity == 20
        assert trades[1].sell_order_id == 2
        assert trades[1].executed_quantity == 20
        assert trades[2].sell_order_id == 3
        assert trades[2].executed_quantity == 10  # partial
        # Order 3 partially filled remains
        asks = engine.get_asks()
        assert len(asks) == 1
        assert asks[0].order_id == 3
        assert asks[0].remaining_quantity == 10

    def test_sell_fifo_at_equal_buy_prices(self):
        """Earlier BUY at the same price matches first."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 10.00, 25, timestamp_ns=100)
        engine.submit_order(2, SIDE_BUY, 10.00, 25, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_SELL, price=10.00, quantity=40, timestamp_ns=300
        )
        assert len(trades) == 2
        assert trades[0].buy_order_id == 1
        assert trades[0].executed_quantity == 25
        assert trades[1].buy_order_id == 2
        assert trades[1].executed_quantity == 15


# ---------------------------------------------------------------------------
# 34. Exact quantity match across multiple orders
# ---------------------------------------------------------------------------
class TestMultiMatchExactQuantity:
    """Incoming quantity exactly equals total compatible resting quantity."""

    def test_exact_total_quantity_match(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 30, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.00, 40, timestamp_ns=200)
        engine.submit_order(3, SIDE_SELL, 10.00, 30, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.00, quantity=100, timestamp_ns=400
        )
        total = sum(t.executed_quantity for t in trades)
        assert total == 100
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0


# ---------------------------------------------------------------------------
# 35. Incoming quantity larger than total compatible resting quantity
# ---------------------------------------------------------------------------
class TestMultiMatchIncomingLarger:
    """Incoming order quantity exceeds total resting compatible quantity."""

    def test_incoming_buy_larger_than_all_sells(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 20, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.50, 30, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=11.00, quantity=100, timestamp_ns=300
        )
        total = sum(t.executed_quantity for t in trades)
        assert total == 50  # 20 + 30
        # Remaining 50 should rest in bid book
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        resting = engine.get_bids()[0]
        assert resting.order_id == 100
        assert resting.remaining_quantity == 50

    def test_incoming_sell_larger_than_all_buys(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 10.00, 15, timestamp_ns=100)
        engine.submit_order(2, SIDE_BUY, 9.50, 10, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_SELL, price=9.50, quantity=50, timestamp_ns=300
        )
        total = sum(t.executed_quantity for t in trades)
        assert total == 25  # 15 + 10
        assert engine.ask_count() == 1
        assert engine.bid_count() == 0
        resting = engine.get_asks()[0]
        assert resting.order_id == 100
        assert resting.remaining_quantity == 25


# ---------------------------------------------------------------------------
# 36. Incoming quantity smaller than total compatible resting quantity
# ---------------------------------------------------------------------------
class TestMultiMatchIncomingSmaller:
    """Incoming order quantity is less than total resting compatible quantity."""

    def test_incoming_buy_smaller_fills_partially(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 60, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.50, 60, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.50, quantity=40, timestamp_ns=300
        )
        assert len(trades) == 1  # Only first sell needed
        assert trades[0].executed_quantity == 40
        assert engine.bid_count() == 0
        # First sell partially filled
        asks = engine.get_asks(priority=True)
        assert len(asks) == 2
        assert asks[0].order_id == 1
        assert asks[0].remaining_quantity == 20


# ---------------------------------------------------------------------------
# 37. Remaining incoming order stored correctly
# ---------------------------------------------------------------------------
class TestMultiMatchResidualIncomingStored:
    """Residual incoming quantity should rest in the book with original priority."""

    def test_residual_buy_stored_in_bid_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 30, timestamp_ns=100)

        trades = engine.match_order(
            order_id=50, side=SIDE_BUY, price=10.00, quantity=80, timestamp_ns=200
        )
        assert len(trades) == 1
        assert trades[0].executed_quantity == 30
        assert engine.bid_count() == 1
        resting = engine.get_bids()[0]
        assert resting.order_id == 50
        assert resting.remaining_quantity == 50
        assert resting.quantity == 80  # original quantity preserved
        assert resting.price_cents == 1000

    def test_residual_sell_stored_in_ask_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 10.00, 20, timestamp_ns=100)

        trades = engine.match_order(
            order_id=50, side=SIDE_SELL, price=10.00, quantity=60, timestamp_ns=200
        )
        assert len(trades) == 1
        assert trades[0].executed_quantity == 20
        assert engine.ask_count() == 1
        resting = engine.get_asks()[0]
        assert resting.order_id == 50
        assert resting.remaining_quantity == 40
        assert resting.quantity == 60


# ---------------------------------------------------------------------------
# 38. Partially filled resting order retains original priority
# ---------------------------------------------------------------------------
class TestMultiMatchRestingPriorityPreserved:
    """Partially filled resting orders keep their original sequence_num."""

    def test_partially_filled_sell_retains_priority(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        s1 = engine.submit_order(1, SIDE_SELL, 10.00, 100, timestamp_ns=100)
        s2 = engine.submit_order(2, SIDE_SELL, 10.00, 50, timestamp_ns=200)
        seq_before = s1.sequence_num

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.00, quantity=30, timestamp_ns=300
        )
        assert len(trades) == 1
        assert trades[0].sell_order_id == 1  # s1 matched first (FIFO)
        assert s1.remaining_quantity == 70
        assert s1.sequence_num == seq_before  # priority preserved
        # s1 still has priority over s2
        best = engine.get_best_sell_order()
        assert best.order_id == 1

    def test_partially_filled_buy_retains_priority(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        b1 = engine.submit_order(1, SIDE_BUY, 10.00, 100, timestamp_ns=100)
        b2 = engine.submit_order(2, SIDE_BUY, 10.00, 50, timestamp_ns=200)
        seq_before = b1.sequence_num

        trades = engine.match_order(
            order_id=100, side=SIDE_SELL, price=10.00, quantity=40, timestamp_ns=300
        )
        assert len(trades) == 1
        assert trades[0].buy_order_id == 1
        assert b1.remaining_quantity == 60
        assert b1.sequence_num == seq_before
        assert engine.get_best_buy_order().order_id == 1


# ---------------------------------------------------------------------------
# 39. Non-crossing orders remain unmatched
# ---------------------------------------------------------------------------
class TestMultiMatchNonCrossingPrices:
    """No trades when prices do not cross."""

    def test_buy_below_all_sells(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 11.00, 50, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 12.00, 50, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.00, quantity=100, timestamp_ns=300
        )
        assert len(trades) == 0
        # Incoming BUY should rest in book
        assert engine.bid_count() == 1
        assert engine.ask_count() == 2
        assert engine.get_bids()[0].order_id == 100

    def test_sell_above_all_buys(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 9.00, 50, timestamp_ns=100)
        engine.submit_order(2, SIDE_BUY, 8.00, 50, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_SELL, price=10.00, quantity=100, timestamp_ns=300
        )
        assert len(trades) == 0
        assert engine.ask_count() == 1
        assert engine.bid_count() == 2
        assert engine.get_asks()[0].order_id == 100


# ---------------------------------------------------------------------------
# 40. Empty opposite order book
# ---------------------------------------------------------------------------
class TestMultiMatchEmptyOppositeBook:
    """Matching against an empty opposite-side book adds to the appropriate side."""

    def test_buy_into_empty_sell_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        trades = engine.match_order(
            order_id=1, side=SIDE_BUY, price=10.00, quantity=50, timestamp_ns=100
        )
        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        assert engine.get_bids()[0].order_id == 1
        assert engine.get_bids()[0].remaining_quantity == 50

    def test_sell_into_empty_buy_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        trades = engine.match_order(
            order_id=1, side=SIDE_SELL, price=10.00, quantity=50, timestamp_ns=100
        )
        assert len(trades) == 0
        assert engine.ask_count() == 1
        assert engine.bid_count() == 0
        assert engine.get_asks()[0].order_id == 1
        assert engine.get_asks()[0].remaining_quantity == 50


# ---------------------------------------------------------------------------
# 41. Correct execution price per fill
# ---------------------------------------------------------------------------
class TestMultiMatchExecutionPrice:
    """Each fill uses the resting order's price (maker price)."""

    def test_buy_fills_at_different_resting_sell_prices(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 10, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.25, 10, timestamp_ns=200)
        engine.submit_order(3, SIDE_SELL, 10.50, 10, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.50, quantity=30, timestamp_ns=400
        )
        assert trades[0].execution_price_cents == 1000
        assert trades[0].execution_price == 10.00
        assert trades[1].execution_price_cents == 1025
        assert trades[1].execution_price == 10.25
        assert trades[2].execution_price_cents == 1050
        assert trades[2].execution_price == 10.50

    def test_sell_fills_at_different_resting_buy_prices(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 10.50, 10, timestamp_ns=100)
        engine.submit_order(2, SIDE_BUY, 10.25, 10, timestamp_ns=200)
        engine.submit_order(3, SIDE_BUY, 10.00, 10, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_SELL, price=10.00, quantity=30, timestamp_ns=400
        )
        assert trades[0].execution_price_cents == 1050
        assert trades[1].execution_price_cents == 1025
        assert trades[2].execution_price_cents == 1000


# ---------------------------------------------------------------------------
# 42. Correct trade result ordering
# ---------------------------------------------------------------------------
class TestMultiMatchTradeResultOrdering:
    """Trade results must be in execution order (first fill first in list)."""

    def test_trade_results_in_execution_order(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(10, SIDE_SELL, 5.00, 10, timestamp_ns=100)
        engine.submit_order(20, SIDE_SELL, 5.05, 10, timestamp_ns=200)
        engine.submit_order(30, SIDE_SELL, 5.10, 10, timestamp_ns=300)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=5.10, quantity=30, timestamp_ns=400
        )
        sell_ids = [t.sell_order_id for t in trades]
        assert sell_ids == [10, 20, 30]  # Lowest price first


# ---------------------------------------------------------------------------
# 43. Quantity conservation across all fills
# ---------------------------------------------------------------------------
class TestMultiMatchQuantityConservation:
    """Sum of executed quantities must equal the incoming quantity consumed."""

    def test_quantity_conservation_full_fill(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 30, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.50, 40, timestamp_ns=200)
        engine.submit_order(3, SIDE_SELL, 11.00, 30, timestamp_ns=300)

        incoming_qty = 100
        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=11.00, quantity=incoming_qty, timestamp_ns=400
        )
        total_exec = sum(t.executed_quantity for t in trades)
        assert total_exec == incoming_qty
        assert engine.bid_count() == 0

    def test_quantity_conservation_partial_fill(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 25, timestamp_ns=100)

        incoming_qty = 60
        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.00, quantity=incoming_qty, timestamp_ns=200
        )
        total_exec = sum(t.executed_quantity for t in trades)
        residual = engine.get_bids()[0].remaining_quantity if engine.bid_count() > 0 else 0
        assert total_exec + residual == incoming_qty

    def test_resting_quantity_conservation(self):
        """Original resting quantities minus fills should equal remaining."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 50, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.50, 60, timestamp_ns=200)

        trades = engine.match_order(
            order_id=100, side=SIDE_BUY, price=10.50, quantity=80, timestamp_ns=300
        )
        # Sell #1 (50) fully consumed, Sell #2 (60) partially consumed by 30
        assert trades[0].executed_quantity == 50
        assert trades[1].executed_quantity == 30
        remaining_asks = engine.get_asks()
        assert len(remaining_asks) == 1
        assert remaining_asks[0].order_id == 2
        assert remaining_asks[0].remaining_quantity == 30  # 60 - 30


# ---------------------------------------------------------------------------
# 44. Validation: zero/negative quantities and invalid side
# ---------------------------------------------------------------------------
class TestMultiMatchValidation:
    """match_order rejects invalid inputs like submit_order does."""

    def test_reject_zero_quantity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        import pytest
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.match_order(1, SIDE_BUY, 10.00, 0, 100)

    def test_reject_invalid_side(self):
        from chronos.matching_engine import MatchingEngine
        import pytest
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid side"):
            engine.match_order(1, 0, 10.00, 50, 100)
        with pytest.raises(ValueError, match="Invalid side"):
            engine.match_order(1, 3, 10.00, 50, 100)

    def test_reject_negative_price(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        import pytest
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid price"):
            engine.match_order(1, SIDE_BUY, -5.00, 50, 100)

    def test_reject_zero_price(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        import pytest
        engine = MatchingEngine()
        with pytest.raises(ValueError, match="Invalid price"):
            engine.match_order(1, SIDE_SELL, 0.0, 50, 100)


# ---------------------------------------------------------------------------
# 45. Day 5 partial-fill tests still pass (regression check)
# ---------------------------------------------------------------------------
class TestDay5RegressionAfterDay6:
    """Verify Day 5 execute_partial_match() still works after Day 6 changes."""

    def test_single_partial_match_still_works(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        sell = engine.submit_order(2, SIDE_SELL, 5.00, 40, timestamp_ns=2000)

        trade = engine.execute_partial_match()
        assert trade is not None
        assert trade.executed_quantity == 40
        assert trade.buy_remaining_quantity == 60
        assert trade.sell_remaining_quantity == 0
        assert buy.remaining_quantity == 60
        assert sell.remaining_quantity == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0

    def test_no_match_when_prices_dont_cross(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 5.00, 100, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 6.00, 100, timestamp_ns=2000)
        trade = engine.execute_partial_match()
        assert trade is None

    def test_empty_engine_returns_none(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.execute_partial_match() is None


# ---------------------------------------------------------------------------
# 46. match_order with partially pre-filled resting orders
# ---------------------------------------------------------------------------
class TestMultiMatchWithPreFilledRestingOrders:
    """Verify match_order works correctly when resting orders already have partial fills."""

    def test_match_against_pre_filled_sells(self):
        """Resting SELLs that were partially filled via execute_partial_match()
        should still be matchable by match_order with their remaining quantity."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 10.00, 100, timestamp_ns=100)
        engine.submit_order(2, SIDE_SELL, 10.50, 50, timestamp_ns=200)
        # Pre-fill: submit a small BUY to partial-fill sell #1
        engine.submit_order(99, SIDE_BUY, 10.00, 30, timestamp_ns=300)
        trade0 = engine.execute_partial_match()
        assert trade0 is not None
        assert trade0.sell_order_id == 1
        assert trade0.executed_quantity == 30
        # sell #1 now has remaining_quantity = 70

        # Now use match_order to sweep
        trades = engine.match_order(
            order_id=200, side=SIDE_BUY, price=10.50, quantity=100, timestamp_ns=400
        )
        total = sum(t.executed_quantity for t in trades)
        assert total == 100  # 70 from sell#1 + 30 from sell#2
        assert engine.ask_count() == 1  # sell#2 has 20 remaining
        remaining = engine.get_asks()[0]
        assert remaining.order_id == 2
        assert remaining.remaining_quantity == 20


# ===========================================================================
# 47. Day 7 — Best Bid from Multiple BUY Prices
# ===========================================================================
class TestDay7BestBidMultiplePrices:
    """Verify Best Bid selection across multiple BUY orders with distinct price levels."""

    def test_best_bid_from_multiple_ascending_prices(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 105.0, 40, 200)
        engine.submit_order(3, SIDE_BUY, 110.0, 30, 300)

        best = engine.get_best_bid()
        assert best is not None
        assert best.order_id == 3
        assert best.price == 110.0
        assert best.price_cents == 11000
        assert engine.get_best_bid_price() == 110.0
        assert engine.get_best_bid_price_cents() == 11000

    def test_best_bid_from_multiple_descending_prices(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 110.0, 30, 100)
        engine.submit_order(2, SIDE_BUY, 105.0, 40, 200)
        engine.submit_order(3, SIDE_BUY, 100.0, 50, 300)

        best = engine.get_best_bid()
        assert best is not None
        assert best.order_id == 1
        assert best.price == 110.0
        assert engine.get_best_bid_price() == 110.0

    def test_best_bid_from_multiple_random_prices(self):
        import random
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        rng = random.Random(123)
        prices = [round(rng.uniform(50.0, 250.0), 2) for _ in range(30)]
        max_p = max(prices)

        engine = MatchingEngine()
        for i, p in enumerate(prices, start=1):
            engine.submit_order(i, SIDE_BUY, p, 10, i * 1000)

        assert engine.get_best_bid_price() == max_p
        assert engine.get_best_bid().price == max_p

    def test_best_bid_quantity_single_and_aggregate(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 105.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 105.0, 75, 200)
        engine.submit_order(3, SIDE_BUY, 102.0, 30, 300)

        # Top order has quantity 50
        assert engine.get_best_bid_quantity(aggregate=False) == 50
        # Aggregated quantity at price level 105.0 is 50 + 75 = 125
        assert engine.get_best_bid_quantity(aggregate=True) == 125
        assert engine.get_best_bid_qty() == 125


# ===========================================================================
# 48. Day 7 — Best Ask from Multiple SELL Prices
# ===========================================================================
class TestDay7BestAskMultiplePrices:
    """Verify Best Ask selection across multiple SELL orders with distinct price levels."""

    def test_best_ask_from_multiple_ascending_prices(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 200.0, 25, 100)
        engine.submit_order(2, SIDE_SELL, 205.0, 35, 200)
        engine.submit_order(3, SIDE_SELL, 210.0, 45, 300)

        best = engine.get_best_ask()
        assert best is not None
        assert best.order_id == 1
        assert best.price == 200.0
        assert best.price_cents == 20000
        assert engine.get_best_ask_price() == 200.0
        assert engine.get_best_ask_price_cents() == 20000

    def test_best_ask_from_multiple_descending_prices(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 210.0, 45, 100)
        engine.submit_order(2, SIDE_SELL, 205.0, 35, 200)
        engine.submit_order(3, SIDE_SELL, 200.0, 25, 300)

        best = engine.get_best_ask()
        assert best is not None
        assert best.order_id == 3
        assert best.price == 200.0
        assert engine.get_best_ask_price() == 200.0

    def test_best_ask_from_multiple_random_prices(self):
        import random
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        rng = random.Random(456)
        prices = [round(rng.uniform(100.0, 300.0), 2) for _ in range(30)]
        min_p = min(prices)

        engine = MatchingEngine()
        for i, p in enumerate(prices, start=1):
            engine.submit_order(i, SIDE_SELL, p, 15, i * 1000)

        assert engine.get_best_ask_price() == min_p
        assert engine.get_best_ask().price == min_p

    def test_best_ask_quantity_single_and_aggregate(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 150.0, 40, 100)
        engine.submit_order(2, SIDE_SELL, 150.0, 60, 200)
        engine.submit_order(3, SIDE_SELL, 155.0, 80, 300)

        assert engine.get_best_ask_quantity(aggregate=False) == 40
        assert engine.get_best_ask_quantity(aggregate=True) == 100
        assert engine.get_best_ask_qty() == 100


# ===========================================================================
# 49. Day 7 — Empty Sides Handling
# ===========================================================================
class TestDay7EmptySidesHandling:
    """Verify safe and consistent behavior when either or both book sides are empty."""

    def test_empty_engine_both_sides(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None
        assert engine.get_best_bid_price() is None
        assert engine.get_best_ask_price() is None
        assert engine.get_best_bid_price_cents() is None
        assert engine.get_best_ask_price_cents() is None
        assert engine.get_best_bid_quantity() == 0
        assert engine.get_best_ask_quantity() == 0
        assert engine.get_spread() is None
        assert engine.get_spread_cents() is None
        assert engine.has_crossing_prices() is False

    def test_empty_buy_side_with_active_asks(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 100)

        assert engine.get_best_bid() is None
        assert engine.get_best_bid_price() is None
        assert engine.get_best_bid_quantity() == 0
        assert engine.get_best_ask() is not None
        assert engine.get_best_ask_price() == 100.0
        assert engine.get_best_ask_quantity() == 50
        assert engine.get_spread() is None

    def test_empty_sell_side_with_active_bids(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 99.0, 40, 100)

        assert engine.get_best_bid() is not None
        assert engine.get_best_bid_price() == 99.0
        assert engine.get_best_bid_quantity() == 40
        assert engine.get_best_ask() is None
        assert engine.get_best_ask_price() is None
        assert engine.get_best_ask_quantity() == 0
        assert engine.get_spread() is None


# ===========================================================================
# 50. Day 7 — Best Prices After Better-Priced Order Inserted
# ===========================================================================
class TestDay7BetterPricedOrderInsertion:
    """Verify best prices immediately update when a better-priced order is inserted."""

    def test_better_buy_price_becomes_top_of_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        assert engine.get_best_bid_price() == 100.0

        # Insert a better BUY (higher price)
        engine.submit_order(2, SIDE_BUY, 102.50, 30, 200)
        assert engine.get_best_bid_price() == 102.50
        assert engine.get_best_bid().order_id == 2
        assert engine.get_best_bid_quantity(aggregate=False) == 30

        # Insert a worse BUY (lower price) - best remains order 2
        engine.submit_order(3, SIDE_BUY, 101.0, 40, 300)
        assert engine.get_best_bid_price() == 102.50
        assert engine.get_best_bid().order_id == 2

    def test_better_sell_price_becomes_top_of_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 110.0, 50, 100)
        assert engine.get_best_ask_price() == 110.0

        # Insert a better SELL (lower price)
        engine.submit_order(2, SIDE_SELL, 107.50, 25, 200)
        assert engine.get_best_ask_price() == 107.50
        assert engine.get_best_ask().order_id == 2
        assert engine.get_best_ask_quantity(aggregate=False) == 25

        # Insert a worse SELL (higher price) - best remains order 2
        engine.submit_order(3, SIDE_SELL, 109.0, 35, 300)
        assert engine.get_best_ask_price() == 107.50
        assert engine.get_best_ask().order_id == 2


# ===========================================================================
# 51. Day 7 — Best Prices and Quantities After Partial Fill
# ===========================================================================
class TestDay7BestPricesAfterPartialFill:
    """Verify top-of-book price and quantity state after partial executions."""

    def test_best_bid_retained_with_decremented_quantity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 100, 100)
        engine.submit_order(2, SIDE_BUY, 98.0, 50, 200)

        # Incoming SELL for 40 @ 100.0 partially fills BUY #1
        trades = engine.match_order(
            order_id=10, side=SIDE_SELL, price=100.0, quantity=40, timestamp_ns=300
        )
        assert len(trades) == 1
        assert trades[0].executed_quantity == 40

        # Best bid is still order #1 at 100.0, but with remaining_quantity = 60
        best = engine.get_best_bid()
        assert best.order_id == 1
        assert best.price == 100.0
        assert best.remaining_quantity == 60
        assert best.quantity == 100  # original quantity preserved
        assert engine.get_best_bid_quantity() == 60

    def test_best_ask_retained_with_decremented_quantity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 105.0, 80, 100)
        engine.submit_order(2, SIDE_SELL, 108.0, 40, 200)

        # Incoming BUY for 50 @ 105.0 partially fills SELL #1
        trades = engine.match_order(
            order_id=20, side=SIDE_BUY, price=105.0, quantity=50, timestamp_ns=300
        )
        assert len(trades) == 1
        assert trades[0].executed_quantity == 50

        # Best ask is still order #1 at 105.0, with remaining_quantity = 30
        best = engine.get_best_ask()
        assert best.order_id == 1
        assert best.price == 105.0
        assert best.remaining_quantity == 30
        assert best.quantity == 80  # original quantity preserved
        assert engine.get_best_ask_quantity() == 30


# ===========================================================================
# 52. Day 7 — Best Prices After Full Fill Removes Top Order
# ===========================================================================
class TestDay7BestPricesAfterFullFillRemovesTopOrder:
    """Verify next priority order seamlessly becomes top-of-book after full fills."""

    def test_full_fill_promotes_next_best_buy(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 95.0, 70, 200)

        # Incoming SELL matches exactly 50 @ 100.0, fully removing order #1
        trades = engine.match_order(
            order_id=10, side=SIDE_SELL, price=100.0, quantity=50, timestamp_ns=300
        )
        assert len(trades) == 1

        # Order #1 is removed; Order #2 @ 95.0 is now top-of-book
        assert engine.bid_count() == 1
        best = engine.get_best_bid()
        assert best.order_id == 2
        assert best.price == 95.0
        assert best.remaining_quantity == 70
        assert engine.get_best_bid_price() == 95.0
        assert engine.get_best_bid_quantity() == 70

    def test_full_fill_promotes_next_best_sell(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 110.0, 30, 100)
        engine.submit_order(2, SIDE_SELL, 115.0, 60, 200)

        # Incoming BUY matches exactly 30 @ 110.0, fully removing order #1
        trades = engine.match_order(
            order_id=20, side=SIDE_BUY, price=110.0, quantity=30, timestamp_ns=300
        )
        assert len(trades) == 1

        # Order #1 is removed; Order #2 @ 115.0 is now top-of-book
        assert engine.ask_count() == 1
        best = engine.get_best_ask()
        assert best.order_id == 2
        assert best.price == 115.0
        assert best.remaining_quantity == 60
        assert engine.get_best_ask_price() == 115.0
        assert engine.get_best_ask_quantity() == 60

    def test_exhausting_all_orders_leaves_side_safely_empty(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)

        engine.match_order(
            order_id=10, side=SIDE_SELL, price=100.0, quantity=50, timestamp_ns=200
        )

        assert engine.bid_count() == 0
        assert engine.get_best_bid() is None
        assert engine.get_best_bid_price() is None
        assert engine.get_best_bid_quantity() == 0


# ===========================================================================
# 53. Day 7 — Equal-Price FIFO Priority Behavior
# ===========================================================================
class TestDay7EqualPriceFIFOBehavior:
    """Verify strict FIFO time priority at equal price levels."""

    def test_equal_price_bids_fifo_arrival_sequence(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(101, SIDE_BUY, 150.0, 20, 1000)
        engine.submit_order(102, SIDE_BUY, 150.0, 30, 2000)
        engine.submit_order(103, SIDE_BUY, 150.0, 40, 3000)

        # Earliest arrival (101) must be best bid
        assert engine.get_best_bid().order_id == 101

        # Aggregated quantity is 20 + 30 + 40 = 90
        assert engine.get_best_bid_quantity(aggregate=True) == 90
        assert engine.get_best_bid_quantity(aggregate=False) == 20

    def test_equal_price_bids_fifo_advancement_on_fills(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(101, SIDE_BUY, 150.0, 20, 1000)
        engine.submit_order(102, SIDE_BUY, 150.0, 30, 2000)
        engine.submit_order(103, SIDE_BUY, 150.0, 40, 3000)

        # Fill 101 completely
        engine.match_order(1, SIDE_SELL, 150.0, 20, 4000)
        assert engine.get_best_bid().order_id == 102
        assert engine.get_best_bid_quantity(aggregate=True) == 70

        # Fill 102 partially (10 remaining)
        engine.match_order(2, SIDE_SELL, 150.0, 20, 5000)
        assert engine.get_best_bid().order_id == 102
        assert engine.get_best_bid().remaining_quantity == 10
        assert engine.get_best_bid_quantity(aggregate=True) == 50

        # Fill 102 completely
        engine.match_order(3, SIDE_SELL, 150.0, 10, 6000)
        assert engine.get_best_bid().order_id == 103
        assert engine.get_best_bid_quantity(aggregate=True) == 40

    def test_equal_price_asks_fifo_advancement_on_fills(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(201, SIDE_SELL, 160.0, 15, 1000)
        engine.submit_order(202, SIDE_SELL, 160.0, 25, 2000)
        engine.submit_order(203, SIDE_SELL, 160.0, 35, 3000)

        assert engine.get_best_ask().order_id == 201
        assert engine.get_best_ask_quantity(aggregate=True) == 75

        # Fill 201 completely
        engine.match_order(1, SIDE_BUY, 160.0, 15, 4000)
        assert engine.get_best_ask().order_id == 202
        assert engine.get_best_ask_quantity(aggregate=True) == 60


# ===========================================================================
# 54. Day 7 — Non-Mutating Order-Book Inspection
# ===========================================================================
class TestDay7NonMutatingInspection:
    """Verify that inspecting top-of-book and depth never mutates book state."""

    def test_repeated_inspection_calls_leave_state_identical(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 99.0, 30, 200)
        engine.submit_order(3, SIDE_SELL, 105.0, 40, 300)

        for _ in range(10):
            _ = engine.get_best_bid()
            _ = engine.get_best_ask()
            _ = engine.get_best_bid_price()
            _ = engine.get_best_ask_price()
            _ = engine.get_best_bid_quantity()
            _ = engine.get_best_ask_quantity()
            _ = engine.get_spread()
            _ = engine.get_spread_cents()
            _ = engine.get_top_of_book()
            _ = engine.get_prioritized_bids()
            _ = engine.get_prioritized_asks()

        assert engine.bid_count() == 2
        assert engine.ask_count() == 1
        assert engine.order_count() == 3
        assert engine.get_best_bid().remaining_quantity == 50
        assert engine.get_best_ask().remaining_quantity == 40

    def test_mutating_returned_prioritized_list_does_not_mutate_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 102.0, 30, 200)

        bids = engine.get_prioritized_bids()
        bids.clear()

        # Internal book remains intact
        assert engine.bid_count() == 2
        assert engine.get_best_bid().order_id == 2


# ===========================================================================
# 55. Day 7 — Consistency After Multi-Order Matching
# ===========================================================================
class TestDay7ConsistencyAfterMultiOrderMatching:
    """Verify top-of-book and depth consistency after multi-order sweeps."""

    def test_buy_sweeps_multiple_sells_leaving_correct_top_ask(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 30, 100)
        engine.submit_order(2, SIDE_SELL, 101.0, 40, 200)
        engine.submit_order(3, SIDE_SELL, 102.0, 50, 300)

        # Incoming BUY sweeps all of #1 and 20 of #2
        trades = engine.match_order(
            order_id=99, side=SIDE_BUY, price=101.50, quantity=50, timestamp_ns=400
        )
        assert len(trades) == 2

        # #1 is removed; #2 now has 20 remaining at 101.0
        assert engine.ask_count() == 2
        best_ask = engine.get_best_ask()
        assert best_ask.order_id == 2
        assert best_ask.price == 101.0
        assert best_ask.remaining_quantity == 20
        assert engine.get_best_ask_quantity(aggregate=False) == 20

    def test_incoming_residual_rests_as_new_top_of_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 30, 100)

        # Incoming BUY for 80 @ 102.0 matches 30 @ 100.0, leaving 50 residual @ 102.0
        trades = engine.match_order(
            order_id=99, side=SIDE_BUY, price=102.0, quantity=80, timestamp_ns=200
        )
        assert len(trades) == 1
        assert trades[0].executed_quantity == 30

        # Asks are now empty
        assert engine.ask_count() == 0
        assert engine.get_best_ask() is None

        # Bids has the residual 50 @ 102.0 as top-of-book
        assert engine.bid_count() == 1
        best_bid = engine.get_best_bid()
        assert best_bid.order_id == 99
        assert best_bid.price == 102.0
        assert best_bid.remaining_quantity == 50
        assert engine.get_best_bid_quantity() == 50


# ===========================================================================
# 56. Day 7 — Zero Remaining Quantity Safety
# ===========================================================================
class TestDay7ZeroRemainingQuantitySafety:
    """Verify that zero-remaining-quantity orders never persist as active resting orders."""

    def test_reject_adding_corder_with_zero_remaining_quantity(self):
        from chronos.matching_engine import COrder, MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        cord = COrder(
            order_id=1, side=SIDE_BUY, price_cents=10000, quantity=50, timestamp_ns=100
        )
        cord.remaining_quantity = 0  # simulate already-filled order

        with pytest.raises(ValueError, match="Invalid remaining_quantity 0"):
            engine.add_buy_order(cord)

        cord_sell = COrder(
            order_id=2, side=SIDE_SELL, price_cents=10500, quantity=30, timestamp_ns=200
        )
        cord_sell.remaining_quantity = 0

        with pytest.raises(ValueError, match="Invalid remaining_quantity 0"):
            engine.add_sell_order(cord_sell)

    def test_get_best_orders_ignores_any_zero_remaining_quantity(self):
        from chronos.matching_engine import COrder, MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        o1 = engine.submit_order(1, SIDE_BUY, 105.0, 50, 100)
        o2 = engine.submit_order(2, SIDE_BUY, 100.0, 30, 200)

        # Manually set o1 remaining_quantity to 0
        o1.remaining_quantity = 0

        # get_best_bid must skip o1 and select active order o2
        best = engine.get_best_bid()
        assert best.order_id == 2
        assert best.price == 100.0


# ===========================================================================
# 57. Day 7 — Top of Book and Spread API
# ===========================================================================
class TestDay7TopOFBookAndSpreadAPI:
    """Verify Top-of-Book snapshot and spread calculation APIs."""

    def test_spread_calculation_normal_market(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 150.0, 100, 100)
        engine.submit_order(2, SIDE_SELL, 152.50, 50, 200)

        assert engine.get_spread() == 2.50
        assert engine.get_spread_cents() == 250
        assert engine.spread() == 2.50
        assert engine.has_crossing_prices() is False

    def test_spread_calculation_crossing_market(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 155.0, 100, 100)
        engine.submit_order(2, SIDE_SELL, 152.0, 50, 200)

        assert engine.get_spread() == -3.0
        assert engine.get_spread_cents() == -300
        assert engine.has_crossing_prices() is True

    def test_top_of_book_dict_snapshot(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 100.0, 75, 200)
        engine.submit_order(3, SIDE_SELL, 102.0, 40, 300)

        tob = engine.get_top_of_book()
        assert tob["best_bid_price"] == 100.0
        assert tob["best_bid_quantity"] == 125
        assert tob["best_ask_price"] == 102.0
        assert tob["best_ask_quantity"] == 40
        assert tob["spread"] == 2.0


# ===========================================================================
# DAY 9: COMPREHENSIVE MATCHING ENGINE TEST SUITE
# ===========================================================================

# ---------------------------------------------------------------------------
# 58. Day 9 — BUY and SELL Order Storage & Bid/Ask Isolation
# ---------------------------------------------------------------------------
class TestDay9BuySellOrderCoverage:
    """Comprehensive coverage of BUY and SELL order storage, attributes, and side isolation."""

    def test_submit_buy_and_sell_orders_basic_attributes(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        buy = engine.submit_order(101, SIDE_BUY, 125.75, 50, timestamp_ns=1_000_000)
        assert buy.order_id == 101
        assert buy.side == SIDE_BUY
        assert buy.price == 125.75
        assert buy.price_cents == 12575
        assert buy.quantity == 50
        assert buy.remaining_quantity == 50
        assert buy.timestamp_ns == 1_000_000
        assert buy.sequence_num == 1

        sell = engine.submit_order(202, SIDE_SELL, 126.50, 75, timestamp_ns=2_000_000)
        assert sell.order_id == 202
        assert sell.side == SIDE_SELL
        assert sell.price == 126.50
        assert sell.price_cents == 12650
        assert sell.quantity == 75
        assert sell.remaining_quantity == 75
        assert sell.timestamp_ns == 2_000_000
        assert sell.sequence_num == 2

    def test_bids_and_asks_storage_isolation(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        for i in range(1, 6):
            engine.submit_order(i, SIDE_BUY, 100.0 + i, 10 * i, 1000 * i)
            assert engine.bid_count() == i
            assert engine.ask_count() == 0

        for i in range(6, 11):
            engine.submit_order(i, SIDE_SELL, 200.0 + i, 10 * i, 1000 * i)
            assert engine.bid_count() == 5
            assert engine.ask_count() == i - 5

        assert engine.order_count() == 10
        assert len(engine.get_bids()) == 5
        assert len(engine.get_asks()) == 5

    def test_interleaved_bulk_submissions(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        for i in range(50):
            engine.submit_order(i * 2 + 1, SIDE_BUY, 90.0 + (i % 10), 10, i * 100)
            engine.submit_order(i * 2 + 2, SIDE_SELL, 110.0 + (i % 10), 10, i * 100 + 50)

        assert engine.bid_count() == 50
        assert engine.ask_count() == 50
        assert engine.order_count() == 100

    def test_corder_as_dict_fidelity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        buy = engine.submit_order(1, SIDE_BUY, 50.25, 100, 1000)
        d_buy = buy.as_dict()
        assert d_buy == {
            "order_id": 1,
            "side": 1,
            "price_cents": 5025,
            "quantity": 100,
            "remaining_quantity": 100,
            "timestamp_ns": 1000,
        }

        sell = engine.submit_order(2, SIDE_SELL, 55.75, 200, 2000)
        d_sell = sell.as_dict()
        assert d_sell == {
            "order_id": 2,
            "side": 2,
            "price_cents": 5575,
            "quantity": 200,
            "remaining_quantity": 200,
            "timestamp_ns": 2000,
        }

    def test_corder_repr_fidelity(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()
        buy = engine.submit_order(10, SIDE_BUY, 10.0, 50, 100)
        sell = engine.submit_order(20, SIDE_SELL, 20.0, 30, 200)

        assert "COrder" in repr(buy)
        assert "BUY" in repr(buy)
        assert "id=10" in repr(buy)
        assert "rem=50" in repr(buy)

        assert "COrder" in repr(sell)
        assert "SELL" in repr(sell)
        assert "id=20" in repr(sell)
        assert "rem=30" in repr(sell)


# ---------------------------------------------------------------------------
# 59. Day 9 — Best-Price Selection and Price Priority Across Deep Books
# ---------------------------------------------------------------------------
class TestDay9BestPriceSelectionAndPriceTimePriority:
    """Verifies best-price selection and price-time priority across deep, randomized order books."""

    def test_deep_bid_book_best_price_selection(self):
        import random
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        rng = random.Random(42)
        prices = [round(rng.uniform(10.0, 500.0), 2) for _ in range(30)]
        max_p = max(prices)

        engine = MatchingEngine()
        for i, p in enumerate(prices, start=1):
            engine.submit_order(i, SIDE_BUY, p, 10, i * 100)

        best_bid = engine.get_best_bid()
        assert best_bid.price == max_p
        assert engine.get_best_bid_price() == max_p

    def test_deep_ask_book_best_price_selection(self):
        import random
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        rng = random.Random(99)
        prices = [round(rng.uniform(10.0, 500.0), 2) for _ in range(30)]
        min_p = min(prices)

        engine = MatchingEngine()
        for i, p in enumerate(prices, start=1):
            engine.submit_order(i, SIDE_SELL, p, 10, i * 100)

        best_ask = engine.get_best_ask()
        assert best_ask.price == min_p
        assert engine.get_best_ask_price() == min_p

    def test_price_priority_overrides_earlier_arrival_bids(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        o1 = engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=1_000)
        o2 = engine.submit_order(2, SIDE_BUY, 102.0, 10, timestamp_ns=2_000)
        o3 = engine.submit_order(3, SIDE_BUY, 105.0, 10, timestamp_ns=10_000)  # arrives much later

        best = engine.get_best_bid()
        assert best.order_id == 3  # highest price wins despite arriving latest
        assert best.price == 105.0

        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [3, 2, 1]

    def test_price_priority_overrides_earlier_arrival_asks(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()

        o1 = engine.submit_order(1, SIDE_SELL, 200.0, 10, timestamp_ns=1_000)
        o2 = engine.submit_order(2, SIDE_SELL, 198.0, 10, timestamp_ns=2_000)
        o3 = engine.submit_order(3, SIDE_SELL, 195.0, 10, timestamp_ns=10_000)  # arrives much later

        best = engine.get_best_ask()
        assert best.order_id == 3  # lowest price wins despite arriving latest
        assert best.price == 195.0

        prioritized = engine.get_prioritized_asks()
        assert [o.order_id for o in prioritized] == [3, 2, 1]

    def test_prioritized_bids_descending_with_fifo_ties(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_BUY, 100.0, 10, 100)
        engine.submit_order(2, SIDE_BUY, 105.0, 10, 200)
        engine.submit_order(3, SIDE_BUY, 100.0, 10, 300)
        engine.submit_order(4, SIDE_BUY, 105.0, 10, 400)
        engine.submit_order(5, SIDE_BUY, 102.0, 10, 500)

        # Expected priority: 105.0 (orders 2, then 4), 102.0 (order 5), 100.0 (orders 1, then 3)
        prioritized = engine.get_prioritized_bids()
        assert [o.order_id for o in prioritized] == [2, 4, 5, 1, 3]

    def test_prioritized_asks_ascending_with_fifo_ties(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 110.0, 10, 100)
        engine.submit_order(2, SIDE_SELL, 105.0, 10, 200)
        engine.submit_order(3, SIDE_SELL, 110.0, 10, 300)
        engine.submit_order(4, SIDE_SELL, 105.0, 10, 400)
        engine.submit_order(5, SIDE_SELL, 108.0, 10, 500)

        # Expected priority: 105.0 (orders 2, then 4), 108.0 (order 5), 110.0 (orders 1, then 3)
        prioritized = engine.get_prioritized_asks()
        assert [o.order_id for o in prioritized] == [2, 4, 5, 1, 3]


# ---------------------------------------------------------------------------
# 60. Day 9 — Strict FIFO Time Priority at Equal Prices
# ---------------------------------------------------------------------------
class TestDay9StrictFIFOEqualPrices:
    """Verifies deterministic FIFO queuing when orders share identical prices."""

    def test_equal_price_bids_fifo_match_order(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Submit 4 bids with identical price 50.00
        engine.submit_order(101, SIDE_BUY, 50.0, 20, timestamp_ns=100)
        engine.submit_order(102, SIDE_BUY, 50.0, 30, timestamp_ns=200)
        engine.submit_order(103, SIDE_BUY, 50.0, 40, timestamp_ns=300)
        engine.submit_order(104, SIDE_BUY, 50.0, 50, timestamp_ns=400)

        # Incoming SELL for 65 @ 50.00 matches 101 (20), 102 (30), 103 (15)
        trades = engine.match_order(999, SIDE_SELL, 50.0, 65, timestamp_ns=500)
        assert len(trades) == 3
        assert [t.buy_order_id for t in trades] == [101, 102, 103]
        assert [t.executed_quantity for t in trades] == [20, 30, 15]

        # 101 and 102 fully consumed; 103 has 25 remaining; 104 has 50 remaining
        assert engine.bid_count() == 2
        assert engine.get_best_bid().order_id == 103
        assert engine.get_best_bid().remaining_quantity == 25
        assert engine.get_best_bid_quantity(aggregate=True) == 75

    def test_equal_price_asks_fifo_match_order(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Submit 4 asks with identical price 60.00
        engine.submit_order(201, SIDE_SELL, 60.0, 15, timestamp_ns=100)
        engine.submit_order(202, SIDE_SELL, 60.0, 25, timestamp_ns=200)
        engine.submit_order(203, SIDE_SELL, 60.0, 35, timestamp_ns=300)
        engine.submit_order(204, SIDE_SELL, 60.0, 45, timestamp_ns=400)

        # Incoming BUY for 50 @ 60.00 matches 201 (15), 202 (25), 203 (10)
        trades = engine.match_order(888, SIDE_BUY, 60.0, 50, timestamp_ns=500)
        assert len(trades) == 3
        assert [t.sell_order_id for t in trades] == [201, 202, 203]
        assert [t.executed_quantity for t in trades] == [15, 25, 10]

        # 201 and 202 fully consumed; 203 has 25 remaining; 204 has 45 remaining
        assert engine.ask_count() == 2
        assert engine.get_best_ask().order_id == 203
        assert engine.get_best_ask().remaining_quantity == 25
        assert engine.get_best_ask_quantity(aggregate=True) == 70

    def test_equal_timestamps_resolved_by_engine_sequence_num(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Same timestamp for all 3 orders
        same_ts = 1_700_000_000_000
        engine.submit_order(1, SIDE_BUY, 100.0, 10, timestamp_ns=same_ts)
        engine.submit_order(2, SIDE_BUY, 100.0, 20, timestamp_ns=same_ts)
        engine.submit_order(3, SIDE_BUY, 100.0, 30, timestamp_ns=same_ts)

        trades = engine.match_order(99, SIDE_SELL, 100.0, 25, timestamp_ns=same_ts + 1)
        assert len(trades) == 2
        assert trades[0].buy_order_id == 1
        assert trades[0].executed_quantity == 10
        assert trades[1].buy_order_id == 2
        assert trades[1].executed_quantity == 15

        # Order 2 has 5 left, order 3 has 30 left
        assert engine.get_best_bid().order_id == 2
        assert engine.get_best_bid().remaining_quantity == 5

    def test_partially_filled_order_retains_fifo_head_of_line(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Orders A and B at price 50.00
        o_a = engine.submit_order(1, SIDE_BUY, 50.0, 100, timestamp_ns=100)
        o_b = engine.submit_order(2, SIDE_BUY, 50.0, 50, timestamp_ns=200)

        # Incoming SELL of 40 partially fills A (60 left)
        trades1 = engine.match_order(10, SIDE_SELL, 50.0, 40, timestamp_ns=300)
        assert len(trades1) == 1
        assert trades1[0].buy_order_id == 1
        assert trades1[0].executed_quantity == 40
        assert o_a.remaining_quantity == 60

        # Best bid MUST still be order 1
        assert engine.get_best_bid().order_id == 1

        # Next incoming SELL of 30 MUST still match order 1 (leaving 30)
        trades2 = engine.match_order(20, SIDE_SELL, 50.0, 30, timestamp_ns=400)
        assert len(trades2) == 1
        assert trades2[0].buy_order_id == 1
        assert trades2[0].executed_quantity == 30
        assert o_a.remaining_quantity == 30
        assert engine.get_best_bid().order_id == 1

        # Next incoming SELL of 50 consumes the remaining 30 of A, and 20 of B
        trades3 = engine.match_order(30, SIDE_SELL, 50.0, 50, timestamp_ns=500)
        assert len(trades3) == 2
        assert trades3[0].buy_order_id == 1
        assert trades3[0].executed_quantity == 30
        assert trades3[1].buy_order_id == 2
        assert trades3[1].executed_quantity == 20

        # Order A is removed, Order B has 30 left
        assert engine.bid_count() == 1
        assert engine.get_best_bid().order_id == 2
        assert engine.get_best_bid().remaining_quantity == 30


# ---------------------------------------------------------------------------
# 61. Day 9 — Partial Fills, Complete Fills, and Multi-Order Sweeps
# ---------------------------------------------------------------------------
class TestDay9FillsPartialCompleteAndMultiSweep:
    """Covers complete fills, partial fills, and complex multi-order sweeps across levels."""

    def test_exact_quantity_match_full_fill(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 100.0, 50, 100)
        trades = engine.match_order(2, SIDE_BUY, 100.0, 50, 200)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 50
        assert trades[0].buy_order_id == 2
        assert trades[0].sell_order_id == 1
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 0
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0

    def test_incoming_smaller_than_resting_partial_fill(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 100.0, 80, 100)
        trades = engine.match_order(2, SIDE_BUY, 100.0, 30, 200)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 30
        assert trades[0].buy_remaining_quantity == 0
        assert trades[0].sell_remaining_quantity == 50
        assert engine.bid_count() == 0
        assert engine.ask_count() == 1
        assert engine.get_best_ask().remaining_quantity == 50
        assert engine.get_best_ask().quantity == 80  # original size

    def test_incoming_larger_than_resting_sweep_and_rest(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 100.0, 40, 100)
        trades = engine.match_order(2, SIDE_BUY, 100.0, 90, 200)

        assert len(trades) == 1
        assert trades[0].executed_quantity == 40
        assert trades[0].buy_remaining_quantity == 50
        assert trades[0].sell_remaining_quantity == 0
        assert engine.ask_count() == 0
        assert engine.bid_count() == 1
        assert engine.get_best_bid().remaining_quantity == 50
        assert engine.get_best_bid().quantity == 90

    def test_multi_order_sweep_buy_across_five_levels(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        for i, price in enumerate([10.0, 10.10, 10.20, 10.30, 10.40], start=1):
            engine.submit_order(i, SIDE_SELL, price, 20, i * 100)

        # Incoming BUY for 75 @ 10.35 sweeps levels 1, 2, 3 fully (60 qty), and 15 of level 4
        trades = engine.match_order(100, SIDE_BUY, 10.35, 75, timestamp_ns=1000)
        assert len(trades) == 4
        assert [t.sell_order_id for t in trades] == [1, 2, 3, 4]
        assert [t.executed_quantity for t in trades] == [20, 20, 20, 15]
        assert [t.execution_price for t in trades] == [10.0, 10.10, 10.20, 10.30]

        # Sells 1, 2, 3 are gone; Sell 4 has 5 remaining @ 10.30; Sell 5 has 20 @ 10.40
        assert engine.ask_count() == 2
        assert engine.bid_count() == 0
        best_ask = engine.get_best_ask()
        assert best_ask.order_id == 4
        assert best_ask.remaining_quantity == 5
        assert best_ask.price == 10.30

    def test_multi_order_sweep_sell_across_five_levels(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        for i, price in enumerate([10.40, 10.30, 10.20, 10.10, 10.00], start=1):
            engine.submit_order(i, SIDE_BUY, price, 20, i * 100)

        # Incoming SELL for 75 @ 10.05 sweeps levels 1, 2, 3 fully (60 qty), and 15 of level 4 (10.10)
        trades = engine.match_order(200, SIDE_SELL, 10.05, 75, timestamp_ns=1000)
        assert len(trades) == 4
        assert [t.buy_order_id for t in trades] == [1, 2, 3, 4]
        assert [t.executed_quantity for t in trades] == [20, 20, 20, 15]
        assert [t.execution_price for t in trades] == [10.40, 10.30, 10.20, 10.10]

        # Buys 1, 2, 3 are gone; Buy 4 has 5 remaining @ 10.10; Buy 5 has 20 @ 10.00
        assert engine.bid_count() == 2
        assert engine.ask_count() == 0
        best_bid = engine.get_best_bid()
        assert best_bid.order_id == 4
        assert best_bid.remaining_quantity == 5
        assert best_bid.price == 10.10

    def test_multi_order_sweep_same_price_multiple_orders(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 50.0, 10, 100)
        engine.submit_order(2, SIDE_SELL, 50.0, 20, 200)
        engine.submit_order(3, SIDE_SELL, 50.0, 30, 300)

        trades = engine.match_order(99, SIDE_BUY, 50.0, 45, 400)
        assert len(trades) == 3
        assert [t.sell_order_id for t in trades] == [1, 2, 3]
        assert [t.executed_quantity for t in trades] == [10, 20, 15]
        assert engine.ask_count() == 1
        assert engine.get_best_ask().order_id == 3
        assert engine.get_best_ask().remaining_quantity == 15


# ---------------------------------------------------------------------------
# 62. Day 9 — Residual Quantity and Order-Book Consistency
# ---------------------------------------------------------------------------
class TestDay9ResidualQuantityAndBookState:
    """Verifies that residual quantities and book state remain exact across multiple match rounds."""

    def test_original_quantity_immutable_on_fills(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        o = engine.submit_order(1, SIDE_SELL, 100.0, 100, 100)
        assert o.quantity == 100
        assert o.remaining_quantity == 100

        # Partial fill 1
        engine.match_order(2, SIDE_BUY, 100.0, 30, 200)
        assert o.quantity == 100
        assert o.remaining_quantity == 70

        # Partial fill 2
        engine.match_order(3, SIDE_BUY, 100.0, 40, 300)
        assert o.quantity == 100
        assert o.remaining_quantity == 30

    def test_residual_incoming_order_stored_with_correct_state(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 50.0, 20, 100)
        trades = engine.match_order(2, SIDE_BUY, 50.0, 50, 200)
        assert len(trades) == 1

        # Residual 30 in BUY book
        assert engine.bid_count() == 1
        assert engine.ask_count() == 0
        b = engine.get_best_bid()
        assert b.order_id == 2
        assert b.side == SIDE_BUY
        assert b.price == 50.0
        assert b.price_cents == 5000
        assert b.quantity == 50
        assert b.remaining_quantity == 30
        assert b.timestamp_ns == 200

    def test_subsequent_match_of_residual_order(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Step 1: Incoming BUY of 50 against resting SELL of 20 -> residual BUY of 30 rests
        engine.submit_order(1, SIDE_SELL, 50.0, 20, 100)
        trades1 = engine.match_order(2, SIDE_BUY, 50.0, 50, 200)
        assert len(trades1) == 1
        assert engine.bid_count() == 1

        # Step 2: Next incoming SELL of 30 matches against the resting residual BUY of 30!
        trades2 = engine.match_order(3, SIDE_SELL, 50.0, 30, 300)
        assert len(trades2) == 1
        assert trades2[0].buy_order_id == 2
        assert trades2[0].sell_order_id == 3
        assert trades2[0].executed_quantity == 30
        assert trades2[0].buy_remaining_quantity == 0
        assert trades2[0].sell_remaining_quantity == 0

        # Step 3: Book is completely clean and empty
        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None

    def test_multi_round_matching_quantity_conservation(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        total_exec = 0
        # Round 1: Asks at 100, 101, 102 (total 300 shares)
        engine.submit_order(1, SIDE_SELL, 100.0, 100, 100)
        engine.submit_order(2, SIDE_SELL, 101.0, 100, 200)
        engine.submit_order(3, SIDE_SELL, 102.0, 100, 300)

        # Round 2: Incoming BUY for 150 @ 101.0
        t1 = engine.match_order(10, SIDE_BUY, 101.0, 150, 400)
        total_exec += sum(t.executed_quantity for t in t1)

        # Round 3: Incoming BUY for 80 @ 102.0
        t2 = engine.match_order(20, SIDE_BUY, 102.0, 80, 500)
        total_exec += sum(t.executed_quantity for t in t2)

        # Total executed must be 150 + 80 = 230
        assert total_exec == 230
        # Remaining asks must be 300 - 230 = 70
        rem_asks = sum(o.remaining_quantity for o in engine.get_asks())
        assert rem_asks == 70
        assert total_exec + rem_asks == 300


# ---------------------------------------------------------------------------
# 63. Day 9 — Best Bid / Best Ask and Empty Side Handling
# ---------------------------------------------------------------------------
class TestDay9BestBidAskBothSidesAndEmptySides:
    """Verifies best bid and best ask queries when sides are populated, empty, or transitional."""

    def test_both_sides_populated_spread_and_quantities(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_BUY, 99.50, 40, 100)
        engine.submit_order(2, SIDE_BUY, 99.50, 60, 200)
        engine.submit_order(3, SIDE_BUY, 98.00, 100, 300)
        engine.submit_order(4, SIDE_SELL, 100.50, 25, 400)
        engine.submit_order(5, SIDE_SELL, 100.50, 75, 500)
        engine.submit_order(6, SIDE_SELL, 102.00, 50, 600)

        assert engine.get_best_bid_price() == 99.50
        assert engine.get_best_ask_price() == 100.50
        assert engine.get_spread() == 1.00
        assert engine.get_spread_cents() == 100
        assert engine.get_best_bid_quantity(aggregate=True) == 100
        assert engine.get_best_bid_quantity(aggregate=False) == 40
        assert engine.get_best_ask_quantity(aggregate=True) == 100
        assert engine.get_best_ask_quantity(aggregate=False) == 25
        assert engine.has_crossing_prices() is False

    def test_empty_bids_side(self):
        from chronos.matching_engine import MatchingEngine, SIDE_SELL
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 100)

        assert engine.get_best_bid() is None
        assert engine.get_best_bid_price() is None
        assert engine.get_best_bid_price_cents() is None
        assert engine.get_best_bid_quantity() == 0
        assert engine.get_spread() is None
        assert engine.get_spread_cents() is None
        assert engine.has_crossing_prices() is False

        assert engine.get_best_ask() is not None
        assert engine.get_best_ask_price() == 100.0

    def test_empty_asks_side(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)

        assert engine.get_best_ask() is None
        assert engine.get_best_ask_price() is None
        assert engine.get_best_ask_price_cents() is None
        assert engine.get_best_ask_quantity() == 0
        assert engine.get_spread() is None
        assert engine.get_spread_cents() is None
        assert engine.has_crossing_prices() is False

        assert engine.get_best_bid() is not None
        assert engine.get_best_bid_price() == 100.0

    def test_completely_empty_book_state(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        assert engine.bid_count() == 0
        assert engine.ask_count() == 0
        assert engine.order_count() == 0
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None
        assert engine.get_best_bid_price() is None
        assert engine.get_best_ask_price() is None
        assert engine.get_best_bid_quantity() == 0
        assert engine.get_best_ask_quantity() == 0
        assert engine.get_spread() is None
        assert engine.get_spread_cents() is None
        assert engine.has_crossing_prices() is False

    def test_lifecycle_from_empty_to_populated_to_exhausted(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # 1. Initially empty
        assert engine.get_top_of_book()["best_bid_price"] is None

        # 2. Add bid
        engine.submit_order(1, SIDE_BUY, 50.0, 20, 100)
        assert engine.get_best_bid_price() == 50.0
        assert engine.get_spread() is None

        # 3. Add ask
        engine.submit_order(2, SIDE_SELL, 55.0, 20, 200)
        assert engine.get_spread() == 5.0

        # 4. Exhaust book with crossing order
        engine.match_order(3, SIDE_SELL, 50.0, 20, 300)
        assert engine.bid_count() == 0

        engine.match_order(4, SIDE_BUY, 55.0, 20, 400)
        assert engine.ask_count() == 0

        # 5. Clean return to empty state
        assert engine.get_best_bid() is None
        assert engine.get_best_ask() is None
        assert engine.get_spread() is None


# ---------------------------------------------------------------------------
# 64. Day 9 — Non-Crossing Orders Remain on Book
# ---------------------------------------------------------------------------
class TestDay9NonCrossingOrders:
    """Verifies that non-crossing orders correctly rest in the book without executing."""

    def test_non_crossing_buy_below_best_ask_rests(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 100.0, 50, 100)
        trades = engine.match_order(2, SIDE_BUY, 99.0, 40, 200)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 99.0
        assert engine.get_best_ask_price() == 100.0
        assert engine.get_spread() == 1.0

    def test_non_crossing_sell_above_best_bid_rests(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        trades = engine.match_order(2, SIDE_SELL, 101.0, 40, 200)

        assert len(trades) == 0
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 100.0
        assert engine.get_best_ask_price() == 101.0
        assert engine.get_spread() == 1.0

    def test_partial_sweep_followed_by_non_crossing_rest(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Resting sells at 10.00 and 10.50
        engine.submit_order(1, SIDE_SELL, 10.0, 20, 100)
        engine.submit_order(2, SIDE_SELL, 10.50, 20, 200)

        # Incoming BUY for 50 @ 10.25 matches 20 @ 10.00, but cannot cross 10.50!
        trades = engine.match_order(99, SIDE_BUY, 10.25, 50, timestamp_ns=300)
        assert len(trades) == 1
        assert trades[0].executed_quantity == 20

        # Remaining 30 of incoming BUY rests at 10.25
        assert engine.bid_count() == 1
        assert engine.ask_count() == 1
        assert engine.get_best_bid_price() == 10.25
        assert engine.get_best_bid_quantity() == 30
        assert engine.get_best_ask_price() == 10.50
        assert engine.get_best_ask_quantity() == 20
        assert engine.get_spread() == 0.25


# ---------------------------------------------------------------------------
# 65. Day 9 — Input Validation & Duplicate Order IDs
# ---------------------------------------------------------------------------
class TestDay9InputValidationAndDuplicateHandling:
    """Verifies rejection of invalid inputs and correct handling of duplicate order IDs."""

    def test_reject_invalid_side_in_all_entrypoints(self):
        import pytest
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        for invalid_side in [0, 3, -1, 99]:
            with pytest.raises(ValueError, match="Invalid side"):
                engine.submit_order(1, invalid_side, 10.0, 10, 100)
            with pytest.raises(ValueError, match="Invalid side"):
                engine.match_order(1, invalid_side, 10.0, 10, 100)

    def test_reject_invalid_price_in_all_entrypoints(self):
        import pytest
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        for invalid_price in [0.0, -10.0, -0.01]:
            with pytest.raises(ValueError, match="Invalid price"):
                engine.submit_order(1, SIDE_BUY, invalid_price, 10, 100)
            with pytest.raises(ValueError, match="Invalid price"):
                engine.match_order(1, SIDE_BUY, invalid_price, 10, 100)

    def test_reject_invalid_quantity_in_all_entrypoints(self):
        import pytest
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.submit_order(1, SIDE_BUY, 100.0, 0, 100)
        with pytest.raises(ValueError, match="Invalid quantity"):
            engine.match_order(1, SIDE_BUY, 100.0, 0, 100)

    def test_reject_invalid_corder_instances(self):
        import pytest
        from chronos.matching_engine import COrder, MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Zero quantity
        with pytest.raises(ValueError, match="Invalid quantity 0"):
            cord = COrder(1, SIDE_BUY, 10000, 0, 100)
            engine.add_buy_order(cord)

        # Zero price_cents
        with pytest.raises(ValueError, match="Invalid price_cents"):
            cord = COrder(1, SIDE_BUY, 0, 10, 100)
            engine.add_buy_order(cord)

        # Zero remaining_quantity
        with pytest.raises(ValueError, match="Invalid remaining_quantity 0"):
            cord = COrder(1, SIDE_BUY, 10000, 10, 100)
            cord.remaining_quantity = 0
            engine.add_buy_order(cord)

    def test_duplicate_order_ids_independent_tracking(self):
        """Verifies duplicate order IDs receive independent sequence numbers and fills."""
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        o1 = engine.submit_order(500, SIDE_BUY, 100.0, 10, 100)
        o2 = engine.submit_order(500, SIDE_BUY, 100.0, 20, 200)

        assert o1.sequence_num == 1
        assert o2.sequence_num == 2
        assert engine.bid_count() == 2

        # Partial fill matches o1 first
        trades = engine.match_order(999, SIDE_SELL, 100.0, 15, 300)
        assert len(trades) == 2
        assert trades[0].buy_order_id == 500
        assert trades[0].executed_quantity == 10
        assert trades[1].buy_order_id == 500
        assert trades[1].executed_quantity == 5

        # o1 removed, o2 has 15 remaining
        assert engine.bid_count() == 1
        assert engine.get_best_bid().remaining_quantity == 15

    def test_large_integer_boundaries(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        max_u64 = 18_446_744_073_709_551_615
        max_u32 = 4_294_967_295

        o = engine.submit_order(
            order_id=max_u64,
            side=SIDE_BUY,
            price=1_000_000.00,
            quantity=max_u32,
            timestamp_ns=max_u64,
        )
        assert o.order_id == max_u64
        assert o.quantity == max_u32
        assert o.timestamp_ns == max_u64
        assert o.price_cents == 100_000_000


# ---------------------------------------------------------------------------
# 66. Day 9 — TradeResult Fields and Executed Quantities
# ---------------------------------------------------------------------------
class TestDay9TradeResultFieldsAndQuantities:
    """Verifies all fields and attributes of TradeResult instances."""

    def test_trade_result_order_ids_correctly_mapped(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Resting BUY, incoming SELL
        engine.submit_order(111, SIDE_BUY, 10.0, 50, 100)
        t_sell = engine.match_order(222, SIDE_SELL, 10.0, 50, 200)[0]
        assert t_sell.buy_order_id == 111
        assert t_sell.sell_order_id == 222

        # Resting SELL, incoming BUY
        engine.submit_order(333, SIDE_SELL, 20.0, 50, 300)
        t_buy = engine.match_order(444, SIDE_BUY, 20.0, 50, 400)[0]
        assert t_buy.buy_order_id == 444
        assert t_buy.sell_order_id == 333

    def test_trade_result_maker_pricing(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        # Maker is resting BUY @ 105.00
        engine.submit_order(1, SIDE_BUY, 105.0, 10, 100)
        t1 = engine.match_order(2, SIDE_SELL, 100.0, 10, 200)[0]
        assert t1.execution_price == 105.0
        assert t1.execution_price_cents == 10500

        # Maker is resting SELL @ 108.00
        engine.submit_order(3, SIDE_SELL, 108.0, 10, 300)
        t2 = engine.match_order(4, SIDE_BUY, 115.0, 10, 400)[0]
        assert t2.execution_price == 108.0
        assert t2.execution_price_cents == 10800

    def test_trade_result_as_dict_and_repr(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_SELL, 50.0, 20, 100)
        t = engine.match_order(2, SIDE_BUY, 50.0, 20, 200)[0]

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


# ---------------------------------------------------------------------------
# 67. Day 9 — Read-Only Queries Never Mutate Book State
# ---------------------------------------------------------------------------
class TestDay9ReadOnlyQueriesNoMutation:
    """Verifies that inspecting order-book state is 100% side-effect free."""

    def test_repeated_queries_do_not_mutate_book(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 99.0, 30, 200)
        engine.submit_order(3, SIDE_SELL, 105.0, 40, 300)

        for _ in range(50):
            _ = engine.get_best_bid()
            _ = engine.get_best_ask()
            _ = engine.get_best_bid_price()
            _ = engine.get_best_ask_price()
            _ = engine.get_best_bid_quantity()
            _ = engine.get_best_ask_quantity()
            _ = engine.get_spread()
            _ = engine.get_spread_cents()
            _ = engine.get_top_of_book()
            _ = engine.has_crossing_prices()
            _ = engine.get_bids()
            _ = engine.get_asks()
            _ = engine.get_prioritized_bids()
            _ = engine.get_prioritized_asks()
            _ = engine.status()
            _ = engine.order_count()

        assert engine.bid_count() == 2
        assert engine.ask_count() == 1
        assert engine.order_count() == 3
        assert engine.get_best_bid().remaining_quantity == 50
        assert engine.get_best_ask().remaining_quantity == 40

    def test_returned_lists_and_views_mutation_isolation(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()

        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)
        engine.submit_order(2, SIDE_BUY, 102.0, 30, 200)

        bids_copy = engine.get_bids()
        bids_copy.clear()
        assert engine.bid_count() == 2

        prioritized_copy = engine.get_prioritized_bids()
        prioritized_copy.pop()
        assert engine.bid_count() == 2

        prop_bids = engine.bids
        prop_bids.clear()
        assert engine.bid_count() == 2

    def test_snapshot_dicts_mutation_isolation(self):
        from chronos.matching_engine import MatchingEngine, SIDE_BUY
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 100.0, 50, 100)

        tob = engine.get_top_of_book()
        tob["best_bid_price"] = 9999.99
        tob["best_bid_quantity"] = 0

        # Engine state unaffected
        assert engine.get_best_bid_price() == 100.0
        assert engine.get_best_bid_quantity() == 50


# ---------------------------------------------------------------------------
# 68. Day 9 — Regression Tests for Discovered Bugs
# ---------------------------------------------------------------------------
class TestDay9DiscoveredBugsRegression:
    """Regression tests for bugs identified during code inspection."""

    def test_add_buy_order_float_price_one_dollar_bug(self):
        """Fix bug where add_buy_order(id, 1.0, qty, ts) evaluated 1.0 == _SIDE_BUY (1)."""
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        o = engine.add_buy_order(101, 1.0, 10, 1000)
        assert o.order_id == 101
        assert o.side == 1
        assert o.price == 1.0
        assert o.quantity == 10
        assert o.remaining_quantity == 10
        assert o.timestamp_ns == 1000

    def test_add_sell_order_float_price_two_dollars_bug(self):
        """Fix bug where add_sell_order(id, 2.0, qty, ts) evaluated 2.0 == _SIDE_SELL (2)."""
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        o = engine.add_sell_order(202, 2.0, 20, 2000)
        assert o.order_id == 202
        assert o.side == 2
        assert o.price == 2.0
        assert o.quantity == 20
        assert o.remaining_quantity == 20
        assert o.timestamp_ns == 2000

    def test_add_buy_order_rejects_wrong_side_positionally(self):
        import pytest
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        with pytest.raises(ValueError, match="Invalid side 2: expected BUY"):
            engine.add_buy_order(1, 2, 100.0, 10)

    def test_add_sell_order_rejects_wrong_side_positionally(self):
        import pytest
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        with pytest.raises(ValueError, match="Invalid side 1: expected SELL"):
            engine.add_sell_order(1, 1, 100.0, 10)

    def test_add_buy_order_five_args_positional(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        o = engine.add_buy_order(10, 1, 150.0, 30, 5000)
        assert o.order_id == 10
        assert o.price == 150.0
        assert o.quantity == 30
        assert o.timestamp_ns == 5000

    def test_add_sell_order_five_args_positional(self):
        from chronos.matching_engine import MatchingEngine
        engine = MatchingEngine()

        o = engine.add_sell_order(20, 2, 160.0, 40, 6000)
        assert o.order_id == 20
        assert o.price == 160.0
        assert o.quantity == 40
        assert o.timestamp_ns == 6000


