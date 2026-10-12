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

