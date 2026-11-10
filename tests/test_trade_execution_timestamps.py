"""Comprehensive Unit and Integration Tests for Trade Execution Timestamps and Latency Tracking.

Week 3, Day 4 Testing Suite:
1. Trade entry and exit timestamps (TradeResult, TradeExecutionEvent, OrderAdapter).
2. Latency calculations using time.perf_counter_ns() and custom clocks.
3. Non-negative latency invariant and monotonic safety under clock anomalies.
4. Correctness of average, minimum, and maximum latency calculations across diverse sequences.
5. Boundary testing of zero trades and a single trade.
6. Multiple trades, multi-fill sweeps, and edge cases (non-crossing, submit mode, unhandled, unrouted).
7. Deterministic timestamp testing via mocked clocks and monkeypatching.
8. Incremental metrics updates, lifecycle management, and dashboard snapshot propagation.
9. Regression verification for zero-latency minimum calculation bugs in TradeLatencyTracker and AdapterStats.
"""

from __future__ import annotations

import time
from typing import Any, List
import pytest

from chronos.adapter import AdapterStats, OrderAdapter, TradeExecutionEvent
from chronos.dashboard import TerminalDashboard
from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL, TradeResult
from chronos.protocol import Order, OrderType, Side, SYMBOLS
from chronos.trade_latency import TradeLatencySnapshot, TradeLatencyTracker


# ==============================================================================
# 1. Trade Entry and Exit Timestamps
# ==============================================================================

class TestTradeResultTimestampsAndLatency:
    """Verifies nanosecond timestamp capture, latency calculation, and methods on TradeResult."""

    def test_trade_result_initialization_defaults(self):
        """Default TradeResult has zero timestamps and zero latency."""
        trade = TradeResult(
            buy_order_id=1,
            sell_order_id=2,
            executed_quantity=100,
            execution_price_cents=15000,
            buy_remaining_quantity=0,
            sell_remaining_quantity=50,
        )
        assert trade.entry_timestamp_ns == 0
        assert trade.exit_timestamp_ns == 0
        assert trade.latency_ns == 0
        assert trade.latency_us == 0.0

    def test_trade_result_explicit_timestamps(self):
        """Explicit entry and exit timestamps correctly compute latency."""
        t_entry = 1_000_000_000
        t_exit = 1_000_003_500  # delta = 3,500 ns
        trade = TradeResult(
            buy_order_id=1,
            sell_order_id=2,
            executed_quantity=50,
            execution_price_cents=20000,
            buy_remaining_quantity=0,
            sell_remaining_quantity=0,
            entry_timestamp_ns=t_entry,
            exit_timestamp_ns=t_exit,
        )
        assert trade.entry_timestamp_ns == t_entry
        assert trade.exit_timestamp_ns == t_exit
        assert trade.latency_ns == 3500
        assert trade.latency_us == 3.5

    def test_trade_result_set_timestamps_valid(self):
        """set_timestamps updates entry, exit, and calculated latency."""
        trade = TradeResult(1, 2, 10, 10000, 0, 0)
        trade.set_timestamps(entry_ns=500_000, exit_ns=501_250)
        assert trade.entry_timestamp_ns == 500_000
        assert trade.exit_timestamp_ns == 501_250
        assert trade.latency_ns == 1250
        assert trade.latency_us == 1.25

    def test_trade_result_set_timestamps_zero_delta(self):
        """Zero elapsed time (entry == exit) results in latency_ns == 0."""
        trade = TradeResult(1, 2, 10, 10000, 0, 0)
        trade.set_timestamps(entry_ns=700_000, exit_ns=700_000)
        assert trade.entry_timestamp_ns == 700_000
        assert trade.exit_timestamp_ns == 700_000
        assert trade.latency_ns == 0
        assert trade.latency_us == 0.0

    def test_trade_result_set_timestamps_negative_clamped_to_zero(self):
        """Non-monotonic clock anomaly (exit < entry) clamps latency to zero."""
        trade = TradeResult(1, 2, 10, 10000, 0, 0)
        trade.set_timestamps(entry_ns=900_000, exit_ns=800_000)
        assert trade.entry_timestamp_ns == 900_000
        assert trade.exit_timestamp_ns == 800_000
        assert trade.latency_ns == 0
        assert trade.latency_us == 0.0

    def test_trade_result_as_dict_timing_flags(self):
        """as_dict without flags omits timing for compatibility; include_timing=True includes them."""
        trade = TradeResult(1, 2, 10, 5000, 0, 0)
        trade.set_timestamps(1000, 1800)

        d_default = trade.as_dict()
        assert "entry_timestamp_ns" not in d_default
        assert "latency_ns" not in d_default

        d_timed = trade.as_dict(include_timing=True)
        assert d_timed["entry_timestamp_ns"] == 1000
        assert d_timed["exit_timestamp_ns"] == 1800
        assert d_timed["latency_ns"] == 800

    def test_trade_result_repr_formatting(self):
        """TradeResult __repr__ includes latency when latency_ns > 0."""
        trade = TradeResult(1, 2, 10, 5000, 0, 0)
        trade.set_timestamps(1000, 2400)
        r = repr(trade)
        assert "lat_ns=1400" in r
        assert "buy=1" in r
        assert "sell=2" in r


class TestTradeExecutionEventModel:
    """Verifies TradeExecutionEvent dataclass attributes, timestamps, and conversions."""

    def test_execution_event_fields_and_properties(self):
        event = TradeExecutionEvent(
            order_id=101,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            price=150.25,
            quantity=100,
            entry_timestamp_ns=1_000_000,
            exit_timestamp_ns=1_002_000,
            latency_ns=2000,
            trades=[],
            matched=False,
            volume_matched=0,
        )
        assert event.order_id == 101
        assert event.symbol_id == SYMBOLS["AAPL"]
        assert event.side == int(Side.BUY)
        assert event.price == 150.25
        assert event.quantity == 100
        assert event.entry_timestamp_ns == 1_000_000
        assert event.exit_timestamp_ns == 1_002_000
        assert event.latency_ns == 2000
        assert event.latency_us == 2.0
        assert event.matched is False
        assert event.volume_matched == 0
        assert event.trades == []

    def test_execution_event_with_trades(self):
        trade = TradeResult(1, 2, 50, 15000, 0, 0, 1000, 1800, 800)
        event = TradeExecutionEvent(
            order_id=1,
            symbol_id=SYMBOLS["AAPL"],
            side=int(Side.BUY),
            price=150.0,
            quantity=50,
            entry_timestamp_ns=1000,
            exit_timestamp_ns=1800,
            latency_ns=800,
            trades=[trade],
            matched=True,
            volume_matched=50,
        )
        assert event.matched is True
        assert event.volume_matched == 50
        assert len(event.trades) == 1
        assert event.trades[0] is trade


# ==============================================================================
# 2. Deterministic Latency Calculation With Controlled Clocks
# ==============================================================================

class TestDeterministicLatencyCalculationWithMockClock:
    """Uses controlled mock clocks and monkeypatching for deterministic latency testing."""

    def test_default_clock_is_perf_counter_ns(self):
        tracker = TradeLatencyTracker()
        assert tracker.clock is time.perf_counter_ns

    def test_injected_mock_clock_start_and_stop(self):
        """Injected clock sequence produces exact deterministic latency."""
        time_sequence = [10_000_000, 10_004_250]  # delta = 4,250 ns
        clock_iter = iter(time_sequence)

        tracker = TradeLatencyTracker(clock=lambda: next(clock_iter))
        t_entry = tracker.start_trade()
        assert t_entry == 10_000_000

        lat = tracker.stop_trade(t_entry)
        assert lat == 4250
        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 4250.0
        assert tracker.min_latency_ns == 4250
        assert tracker.max_latency_ns == 4250
        assert tracker.last_latency_ns == 4250

    def test_injected_mock_clock_measure_context_manager(self):
        """measure_trade context manager calculates deterministic latency with mock clock."""
        time_sequence = [50_000, 52_100]  # delta = 2,100 ns
        clock_iter = iter(time_sequence)

        tracker = TradeLatencyTracker(clock=lambda: next(clock_iter))
        with tracker.measure_trade(count=1) as timer:
            pass

        assert timer.entry_ns == 50_000
        assert timer.exit_ns == 52_100
        assert timer.latency_ns == 2100
        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 2100.0

    def test_adapter_dispatch_with_mocked_perf_counter_ns_adapter_fallback(self, monkeypatch):
        """When engine track_timestamps=False, OrderAdapter stamps trades with adapter timing window."""
        clock_values = [1_000_000_000, 1_000_001_800]  # delta = 1,800 ns
        clock_iter = iter(clock_values)
        monkeypatch.setattr(time, "perf_counter_ns", lambda: next(clock_iter))

        engine = MatchingEngine(track_timestamps=False)
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        buy_order = Order(2, 2000, 100.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

        trades = adapter.dispatch_raw_order(buy_order)
        assert len(trades) == 1
        trade = trades[0]

        # Trade timestamps assigned by OrderAdapter
        assert trade.entry_timestamp_ns == 1_000_000_000
        assert trade.exit_timestamp_ns == 1_000_001_800
        assert trade.latency_ns == 1800
        assert trade.latency_us == 1.8

        # Execution event matches adapter window
        assert len(adapter.execution_events) == 1
        event = adapter.execution_events[0]
        assert event.entry_timestamp_ns == 1_000_000_000
        assert event.exit_timestamp_ns == 1_000_001_800
        assert event.latency_ns == 1800
        assert event.latency_us == 1.8

        # Adapter latency tracker reflects 1800ns
        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == 1
        assert snap.avg_latency_ns == 1800.0
        assert snap.min_latency_ns == 1800
        assert snap.max_latency_ns == 1800

    def test_adapter_dispatch_with_mocked_perf_counter_ns_engine_window(self, monkeypatch):
        """When engine track_timestamps=True, trade captures engine window and event captures adapter window."""
        # 4 timestamps: [adapter_entry, engine_entry, engine_exit, adapter_exit]
        clock_values = [1_000_000_000, 1_000_000_200, 1_000_001_500, 1_000_001_800]
        clock_iter = iter(clock_values)
        monkeypatch.setattr(time, "perf_counter_ns", lambda: next(clock_iter))

        engine = MatchingEngine(track_timestamps=True)
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        buy_order = Order(2, 2000, 100.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

        trades = adapter.dispatch_raw_order(buy_order)
        assert len(trades) == 1
        trade = trades[0]

        # Trade captures inner engine matching execution
        assert trade.entry_timestamp_ns == 1_000_000_200
        assert trade.exit_timestamp_ns == 1_000_001_500
        assert trade.latency_ns == 1300

        # Adapter event captures outer dispatch window
        event = adapter.execution_events[0]
        assert event.entry_timestamp_ns == 1_000_000_000
        assert event.exit_timestamp_ns == 1_000_001_800
        assert event.latency_ns == 1800

        # Trade latency tracker accurately recorded the trade's 1300ns latency
        assert adapter.trade_latency.trade_count == 1
        assert adapter.trade_latency.avg_latency_ns == 1300.0
        assert adapter.trade_latency.min_latency_ns == 1300
        assert adapter.trade_latency.max_latency_ns == 1300

    def test_adapter_multi_fill_with_mocked_perf_counter_ns(self, monkeypatch):
        """Multi-fill sweep associates the same deterministic timestamps across all generated trades."""
        clock_values = [2_000_000_000, 2_000_000_500, 2_000_003_200, 2_000_004_000]
        clock_iter = iter(clock_values)
        monkeypatch.setattr(time, "perf_counter_ns", lambda: next(clock_iter))

        engine = MatchingEngine(track_timestamps=True)
        engine.submit_order(1, SIDE_SELL, 100.0, 20, 1000)
        engine.submit_order(2, SIDE_SELL, 101.0, 30, 2000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        sweep_order = Order(3, 3000, 105.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

        trades = adapter.dispatch_raw_order(sweep_order)
        assert len(trades) == 2

        for t in trades:
            assert t.entry_timestamp_ns == 2_000_000_500
            assert t.exit_timestamp_ns == 2_000_003_200
            assert t.latency_ns == 2700

        # Both trades recorded into trade latency tracker
        snap = adapter.trade_latency
        assert snap.trade_count == 2
        assert snap.avg_latency_ns == 2700.0
        assert snap.min_latency_ns == 2700
        assert snap.max_latency_ns == 2700
        assert snap.total_latency_ns == 5400

    def test_adapter_zero_latency_with_mocked_perf_counter_ns(self, monkeypatch):
        """Zero elapsed time during matching results in 0ns latency without error."""
        clock_values = [5_000_000, 5_000_000, 5_000_000, 5_000_000]  # delta = 0 ns
        clock_iter = iter(clock_values)
        monkeypatch.setattr(time, "perf_counter_ns", lambda: next(clock_iter))

        engine = MatchingEngine(track_timestamps=True)
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        buy_order = Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(buy_order)

        assert len(trades) == 1
        assert trades[0].latency_ns == 0
        assert adapter.execution_events[0].latency_ns == 0
        assert adapter.trade_latency.avg_latency_ns == 0.0
        assert adapter.trade_latency.min_latency_ns == 0
        assert adapter.trade_latency.max_latency_ns == 0

    def test_adapter_clock_skew_with_mocked_perf_counter_ns(self, monkeypatch):
        """Monotonic clock regression (exit < entry) clamps latency to zero."""
        clock_values = [6_000_000, 6_000_000, 5_000_000, 5_000_000]  # backwards jump
        clock_iter = iter(clock_values)
        monkeypatch.setattr(time, "perf_counter_ns", lambda: next(clock_iter))

        engine = MatchingEngine(track_timestamps=True)
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        buy_order = Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(buy_order)

        assert len(trades) == 1
        assert trades[0].latency_ns == 0
        assert adapter.execution_events[0].latency_ns == 0
        assert adapter.trade_latency.avg_latency_ns == 0.0


# ==============================================================================
# 3. Latency Correctness, Non-Negativity & Monotonic Safety
# ==============================================================================

class TestLatencyNonNegativityAndSafety:
    """Verifies that all latency calculations remain non-negative under all conditions."""

    def test_tracker_record_latency_negative_clamped(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(-500)
        assert tracker.trade_count == 1
        assert tracker.last_latency_ns == 0
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.total_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0

    def test_tracker_record_execution_exit_before_entry_clamped(self):
        tracker = TradeLatencyTracker()
        lat = tracker.record_execution(entry_timestamp_ns=1000, exit_timestamp_ns=500)
        assert lat == 0
        assert tracker.trade_count == 1
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0

    def test_tracker_record_trade_negative_latency_clamped(self):
        tracker = TradeLatencyTracker()
        trade_dict = {"latency_ns": -150}
        lat = tracker.record_trade(trade_dict)
        assert lat == 0
        assert tracker.trade_count == 1
        assert tracker.last_latency_ns == 0

    def test_adapter_stats_negative_latency_clamped(self):
        stats = AdapterStats()
        stats.record_latency(-250)
        assert stats.last_execution_latency_ns == 0
        assert stats.min_execution_latency_ns == 0
        assert stats.max_execution_latency_ns == 0
        assert stats.total_execution_latency_ns == 0

    def test_sub_nanosecond_precision_integrity(self):
        """Ensure latency arithmetic operates strictly on integers without float loss."""
        tracker = TradeLatencyTracker()
        tracker.record_latency(1)  # 1 nanosecond
        assert tracker.total_latency_ns == 1
        assert tracker.avg_latency_ns == 1.0
        assert tracker.avg_latency_us == 0.001


# ==============================================================================
# 4. Average, Minimum, and Maximum Latency Calculations
# ==============================================================================

class TestAverageMinMaxLatencyCalculations:
    """Verifies mathematical correctness of running aggregations across diverse sequences."""

    def test_all_identical_latencies(self):
        tracker = TradeLatencyTracker()
        for _ in range(10):
            tracker.record_latency(1500)

        assert tracker.trade_count == 10
        assert tracker.total_latency_ns == 15_000
        assert tracker.min_latency_ns == 1500
        assert tracker.max_latency_ns == 1500
        assert tracker.avg_latency_ns == 1500.0
        assert tracker.avg_latency_us == 1.5

    def test_strictly_increasing_latencies(self):
        tracker = TradeLatencyTracker()
        latencies = [100, 200, 300, 400, 500]
        for lat in latencies:
            tracker.record_latency(lat)

        assert tracker.trade_count == 5
        assert tracker.total_latency_ns == 1500
        assert tracker.min_latency_ns == 100
        assert tracker.max_latency_ns == 500
        assert tracker.avg_latency_ns == 300.0

    def test_strictly_decreasing_latencies(self):
        tracker = TradeLatencyTracker()
        latencies = [500, 400, 300, 200, 100]
        for lat in latencies:
            tracker.record_latency(lat)

        assert tracker.trade_count == 5
        assert tracker.total_latency_ns == 1500
        assert tracker.min_latency_ns == 100
        assert tracker.max_latency_ns == 500
        assert tracker.avg_latency_ns == 300.0

    def test_sequence_starting_with_zero_min_preserved(self):
        """Regression test for Bug 1: A stream starting with 0ns must preserve 0 as the minimum."""
        tracker = TradeLatencyTracker()
        tracker.record_latency(0)
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0

        tracker.record_latency(200)
        assert tracker.min_latency_ns == 0, "Minimum must stay 0 after a non-zero sample"
        assert tracker.max_latency_ns == 200
        assert tracker.avg_latency_ns == 100.0

        tracker.record_latency(500)
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 500
        assert tracker.avg_latency_ns == pytest.approx(700.0 / 3.0)

    def test_sequence_with_zero_in_middle_min_preserved(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(300)
        tracker.record_latency(0)
        tracker.record_latency(150)

        assert tracker.trade_count == 3
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 300
        assert tracker.avg_latency_ns == 150.0

    def test_adapter_stats_sequence_starting_with_zero_min_preserved(self):
        """Regression test for Bug 2: AdapterStats starting with 0ns must preserve 0 as minimum."""
        stats = AdapterStats()
        stats.total_orders_dispatched = 2
        stats.record_latency(0)
        assert stats.min_execution_latency_ns == 0

        stats.record_latency(400)
        assert stats.min_execution_latency_ns == 0, "AdapterStats min must remain 0"
        assert stats.max_execution_latency_ns == 400
        assert stats.avg_execution_latency_ns == 200.0

    def test_extreme_large_latency_no_overflow(self):
        """5 seconds in nanoseconds = 5,000,000,000 ns does not cause 32-bit overflow."""
        tracker = TradeLatencyTracker()
        tracker.record_latency(5_000_000_000)
        tracker.record_latency(1_000_000_000)

        assert tracker.trade_count == 2
        assert tracker.total_latency_ns == 6_000_000_000
        assert tracker.min_latency_ns == 1_000_000_000
        assert tracker.max_latency_ns == 5_000_000_000
        assert tracker.avg_latency_ns == 3_000_000_000.0
        assert tracker.avg_latency_us == 3_000_000.0

    def test_microsecond_conversions_consistency(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(1250)
        tracker.record_latency(2750)

        assert tracker.avg_latency_ns == 2000.0
        assert tracker.avg_latency_us == 2.0
        assert tracker.min_latency_us == 1.25
        assert tracker.max_latency_us == 2.75

        snap = tracker.get_snapshot()
        assert snap.avg_latency_us == 2.0
        assert snap.min_latency_us == 1.25
        assert snap.max_latency_us == 2.75

    def test_percentiles_calculation(self):
        tracker = TradeLatencyTracker()
        for i in range(1, 101):
            tracker.record_latency(i * 10)

        assert tracker.trade_count == 100
        assert tracker.percentile_latency_ns(50.0) in (500.0, 510.0)
        assert tracker.percentile_latency_ns(90.0) in (900.0, 910.0)
        assert tracker.percentile_latency_ns(99.0) in (990.0, 1000.0)


# ==============================================================================
# 5. Boundary Testing: Zero Trades and Single Trade
# ==============================================================================

class TestZeroTradesAndSingleTrade:
    """Verifies strict boundary conditions: zero trades and single trade."""

    def test_zero_trades_tracker_initial_state(self):
        tracker = TradeLatencyTracker()
        assert tracker.trade_count == 0
        assert tracker.total_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.last_latency_ns == 0
        assert tracker.avg_latency_us == 0.0
        assert tracker.min_latency_us == 0.0
        assert tracker.max_latency_us == 0.0
        assert tracker.percentile_latency_ns(50.0) == 0.0
        assert tracker.percentile_latency_ns(99.0) == 0.0

    def test_zero_trades_snapshot_state(self):
        snap = TradeLatencySnapshot()
        assert snap.trade_count == 0
        assert snap.avg_latency_ns == 0.0
        assert snap.min_latency_ns == 0
        assert snap.max_latency_ns == 0
        assert snap.total_latency_ns == 0
        assert snap.last_latency_ns == 0
        assert snap.avg_latency_us == 0.0
        assert snap.as_dict()["trade_count"] == 0

    def test_zero_trades_adapter_stats_state(self):
        stats = AdapterStats()
        assert stats.total_orders_dispatched == 0
        assert stats.total_trades_generated == 0
        assert stats.total_execution_latency_ns == 0
        assert stats.avg_execution_latency_ns == 0.0
        assert stats.min_execution_latency_ns == 0
        assert stats.max_execution_latency_ns == 0
        assert stats.avg_execution_latency_us == 0.0

    def test_zero_trades_order_adapter_state(self):
        adapter = OrderAdapter(engine=MatchingEngine())
        assert adapter.trade_latency.trade_count == 0
        assert adapter.trade_latency.avg_latency_ns == 0.0
        assert adapter.stats.total_trades_generated == 0
        assert len(adapter.execution_events) == 0

    def test_single_trade_tracker(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(2400)

        assert tracker.trade_count == 1
        assert tracker.total_latency_ns == 2400
        assert tracker.avg_latency_ns == 2400.0
        assert tracker.min_latency_ns == 2400
        assert tracker.max_latency_ns == 2400
        assert tracker.last_latency_ns == 2400
        assert tracker.avg_latency_us == 2.4
        assert tracker.min_latency_us == 2.4
        assert tracker.max_latency_us == 2.4
        assert tracker.percentile_latency_ns(50.0) == 2400.0
        assert tracker.percentile_latency_ns(99.0) == 2400.0

    def test_single_trade_with_zero_latency(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(0)

        assert tracker.trade_count == 1
        assert tracker.total_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.last_latency_ns == 0

    def test_single_trade_adapter_end_to_end(self):
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        buy_order = Order(2, 2000, 100.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(buy_order)

        assert len(trades) == 1
        snap = adapter.trade_latency
        assert snap.trade_count == 1
        assert snap.avg_latency_ns > 0.0
        assert snap.min_latency_ns == snap.max_latency_ns
        assert snap.last_latency_ns == snap.min_latency_ns
        assert adapter.stats.total_trades_generated == 1

    def test_single_trade_reset_restores_zero_state(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(3500)
        assert tracker.trade_count == 1

        tracker.reset()
        assert tracker.trade_count == 0
        assert tracker.total_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.last_latency_ns == 0


# ==============================================================================
# 6. Multiple Trades, Multi-Fills & Edge Cases
# ==============================================================================

class TestMultipleTradesAndEdgeCases:
    """Verifies multi-trade tracking, multi-fills, non-crossing, submit mode, and capacity limits."""

    def test_multiple_trades_exact_averaging(self):
        tracker = TradeLatencyTracker()
        samples = [1000, 2000, 3000, 4000, 5000]
        for s in samples:
            tracker.record_latency(s)

        assert tracker.trade_count == 5
        assert tracker.total_latency_ns == 15_000
        assert tracker.avg_latency_ns == 3000.0
        assert tracker.min_latency_ns == 1000
        assert tracker.max_latency_ns == 5000
        assert tracker.last_latency_ns == 5000

    def test_multiple_trades_batch_recording(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(1200, count=4)
        tracker.record_latency(1800, count=6)

        assert tracker.trade_count == 10
        assert tracker.total_latency_ns == 15_600
        assert tracker.avg_latency_ns == 1560.0
        assert tracker.min_latency_ns == 1200
        assert tracker.max_latency_ns == 1800

    def test_multi_fill_sweep_all_trades_recorded(self):
        """Incoming order sweeps across 3 resting orders; all 3 fills are recorded in trade latency."""
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)
        engine.submit_order(2, SIDE_SELL, 100.5, 20, 2000)
        engine.submit_order(3, SIDE_SELL, 101.0, 30, 3000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        sweep_buy = Order(4, 4000, 102.0, 60, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(sweep_buy)

        assert len(trades) == 3
        assert adapter.stats.total_trades_generated == 3
        assert adapter.stats.total_volume_matched == 60
        assert adapter.trade_latency.trade_count == 3
        assert adapter.trade_latency.total_latency_ns > 0

    def test_non_crossing_orders_do_not_create_trades(self):
        """Non-crossing order records execution event but zero trade latency entries."""
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        sell_order = Order(1, 1000, 150.0, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(sell_order)

        assert len(trades) == 0
        assert adapter.stats.total_orders_dispatched == 1
        assert adapter.stats.non_crossing_orders == 1
        assert adapter.stats.total_trades_generated == 0
        assert adapter.trade_latency.trade_count == 0

        assert len(adapter.execution_events) == 1
        ev = adapter.execution_events[0]
        assert ev.order_id == 1
        assert ev.matched is False
        assert ev.volume_matched == 0
        assert ev.latency_ns >= 0

    def test_submit_mode_does_not_create_trades(self):
        """Submit mode passively stores orders without trade execution."""
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="submit")

        sell = Order(1, 1000, 100.0, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        buy = Order(2, 2000, 100.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

        adapter.dispatch_raw_order(sell)
        adapter.dispatch_raw_order(buy)

        assert len(adapter.trades) == 0
        assert adapter.stats.total_trades_generated == 0
        assert adapter.trade_latency.trade_count == 0
        assert adapter.stats.non_crossing_orders == 2

    def test_unhandled_orders_do_not_create_trades(self):
        adapter = OrderAdapter(engine=MatchingEngine())
        cancel_order = Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.CANCEL))
        trades = adapter.dispatch_raw_order(cancel_order)

        assert trades == []
        assert adapter.stats.unhandled_order_types == 1
        assert adapter.trade_latency.trade_count == 0

    def test_unrouted_symbols_do_not_create_trades(self):
        adapter = OrderAdapter(symbol_engines={SYMBOLS["AAPL"]: MatchingEngine()})
        msft_order = Order(1, 1000, 100.0, 10, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(msft_order)

        assert trades == []
        assert adapter.stats.unrouted_symbols == 1
        assert adapter.trade_latency.trade_count == 0

    def test_multi_symbol_routing_trade_latency_tracking(self):
        """Trades generated across multiple symbol engines are unified in adapter trade latency."""
        eng_aapl = MatchingEngine()
        eng_msft = MatchingEngine()
        adapter = OrderAdapter(
            symbol_engines={
                SYMBOLS["AAPL"]: eng_aapl,
                SYMBOLS["MSFT"]: eng_msft,
            }
        )

        adapter.dispatch_raw_order(Order(1, 1000, 150.0, 20, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)))
        adapter.dispatch_raw_order(Order(2, 2000, 300.0, 30, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)))

        t1 = adapter.dispatch_raw_order(Order(3, 3000, 150.0, 20, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))
        assert len(t1) == 1

        t2 = adapter.dispatch_raw_order(Order(4, 4000, 300.0, 30, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)))
        assert len(t2) == 1

        assert adapter.stats.total_trades_generated == 2
        assert adapter.trade_latency.trade_count == 2
        assert adapter.trade_latency.avg_latency_ns > 0

    def test_sample_buffer_capacity_bounded(self):
        """Tracker sample list is bounded by max_samples while running counters aggregate everything."""
        tracker = TradeLatencyTracker(max_samples=50)
        for i in range(120):
            tracker.record_latency(100 + i)

        assert tracker.trade_count == 120
        assert len(tracker._samples) == 50
        assert tracker.total_latency_ns == sum(100 + i for i in range(120))


# ==============================================================================
# 7. Metrics Updates After Trades & Lifecycle
# ==============================================================================

class TestMetricsUpdateAfterTrades:
    """Verifies that metrics update accurately after each trade and survive clear/reset."""

    def test_incremental_metrics_update_step_by_step(self):
        tracker = TradeLatencyTracker()

        # Step 0: Initial
        assert tracker.trade_count == 0

        # Step 1: Add first trade
        tracker.record_latency(1000)
        assert tracker.trade_count == 1
        assert tracker.total_latency_ns == 1000
        assert tracker.min_latency_ns == 1000
        assert tracker.max_latency_ns == 1000
        assert tracker.avg_latency_ns == 1000.0

        # Step 2: Add higher latency trade
        tracker.record_latency(2000)
        assert tracker.trade_count == 2
        assert tracker.total_latency_ns == 3000
        assert tracker.min_latency_ns == 1000
        assert tracker.max_latency_ns == 2000
        assert tracker.avg_latency_ns == 1500.0

        # Step 3: Add lower latency trade
        tracker.record_latency(500)
        assert tracker.trade_count == 3
        assert tracker.total_latency_ns == 3500
        assert tracker.min_latency_ns == 500
        assert tracker.max_latency_ns == 2000
        assert tracker.avg_latency_ns == pytest.approx(3500.0 / 3.0)

    def test_adapter_trade_latency_snapshot_reflection(self):
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        assert adapter.get_trade_latency_snapshot().trade_count == 0

        adapter.dispatch_raw_order(Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))
        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == 1
        assert snap.avg_latency_ns > 0

    def test_adapter_clear_and_resume_lifecycle(self):
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        adapter.dispatch_raw_order(Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))
        assert adapter.trade_latency.trade_count == 1

        # Clear adapter
        adapter.clear()
        assert adapter.trade_latency.trade_count == 0
        assert adapter.trade_latency.avg_latency_ns == 0.0
        assert adapter.stats.total_trades_generated == 0
        assert len(adapter.trades) == 0
        assert len(adapter.execution_events) == 0

        # Resume with new orders
        engine.submit_order(3, SIDE_SELL, 100.0, 20, 3000)
        adapter.dispatch_raw_order(Order(4, 4000, 100.0, 20, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))
        assert adapter.trade_latency.trade_count == 1
        assert adapter.stats.total_trades_generated == 1

    def test_dashboard_update_from_adapter_snapshot(self):
        dash = TerminalDashboard(use_sample_data=False)
        assert dash.trade_count == 0

        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 10, 1000)

        adapter = OrderAdapter(engine=engine, dispatch_mode="match")
        adapter.dispatch_raw_order(Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))

        snapshot = adapter.get_trade_latency_snapshot()
        dash.update_trade_latency(snapshot)

        assert dash.trade_count == 1
        assert dash.trade_avg_latency_ns == snapshot.avg_latency_ns
        assert dash.trade_min_latency_ns == snapshot.min_latency_ns
        assert dash.trade_max_latency_ns == snapshot.max_latency_ns
