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
