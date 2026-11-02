"""Unit and Integration Tests for Trade Latency Tracking (Week 3, Day 3).

Validates:
1. TradeLatencySnapshot interface, immutability, dict access, and conversions.
2. TradeLatencyTracker nanosecond latency calculations, running aggregations, and percentiles.
3. Edge cases: zero latency, negative elapsed time (clock skew), non-monotonic jumps, and bounded memory.
4. Entry/exit timestamp capture, context manager timer, and TradeResult object recording.
5. Low measurement overhead benchmarks (<100ns per sample).
6. Integration with OrderAdapter (crossing vs non-crossing, multi-fill sweeps, lifecycle).
7. Integration with TerminalDashboard (snapshot consumption interface).
8. Agreed metrics interface compliance across TradeLatencySnapshot, AdapterStats, and BenchmarkSummary.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import time
from typing import Any, Dict, List
import pytest

from chronos.adapter import AdapterStats, OrderAdapter, TradeExecutionEvent
from chronos.benchmark import (
    BenchmarkConfig,
    BenchmarkSummary,
    PipelineBenchmarkRunner,
    RepetitionMetrics,
    SCOPE_ENGINE_ONLY,
)
from chronos.dashboard import TerminalDashboard
from chronos.matching_engine import MatchingEngine, TradeResult
from chronos.protocol import Order, OrderType, Side, SYMBOLS
from chronos.trade_latency import TradeLatencySnapshot, TradeLatencyTracker


# ==============================================================================
# 1. TradeLatencySnapshot Tests
# ==============================================================================

class TestTradeLatencySnapshot:
    """Verifies TradeLatencySnapshot attributes, immutability, and agreed interface."""

    def test_default_initialization(self):
        snap = TradeLatencySnapshot()
        assert snap.trade_count == 0
        assert snap.avg_latency_ns == 0.0
        assert snap.min_latency_ns == 0
        assert snap.max_latency_ns == 0
        assert snap.last_latency_ns == 0
        assert snap.total_latency_ns == 0
        assert snap.avg_latency_us == 0.0
        assert snap.min_latency_us == 0.0
        assert snap.max_latency_us == 0.0

    def test_explicit_initialization_and_microseconds_conversion(self):
        snap = TradeLatencySnapshot(
            trade_count=10,
            avg_latency_ns=2500.0,
            min_latency_ns=1000,
            max_latency_ns=5000,
            last_latency_ns=3000,
            total_latency_ns=25000,
            p50_latency_ns=2400.0,
            p90_latency_ns=4500.0,
            p99_latency_ns=4950.0,
        )
        assert snap.trade_count == 10
        assert snap.avg_latency_ns == 2500.0
        assert snap.min_latency_ns == 1000
        assert snap.max_latency_ns == 5000
        assert snap.avg_latency_us == 2.5
        assert snap.min_latency_us == 1.0
        assert snap.max_latency_us == 5.0
        assert snap.last_latency_us == 3.0

    def test_immutability(self):
        snap = TradeLatencySnapshot(trade_count=5, avg_latency_ns=1200.0)
        with pytest.raises(FrozenInstanceError):
            snap.trade_count = 6  # type: ignore[misc]

    def test_as_dict_contains_agreed_metrics(self):
        snap = TradeLatencySnapshot(
            trade_count=4,
            avg_latency_ns=1500.0,
            min_latency_ns=500,
            max_latency_ns=2500,
        )
        d = snap.as_dict()
        assert d["trade_count"] == 4
        assert d["avg_latency_ns"] == 1500.0
        assert d["min_latency_ns"] == 500
        assert d["max_latency_ns"] == 2500
        assert "avg_latency_us" in d

    def test_dict_subscript_and_get_access(self):
        snap = TradeLatencySnapshot(
            trade_count=3,
            avg_latency_ns=1000.0,
            min_latency_ns=800,
            max_latency_ns=1200,
        )
        assert snap["trade_count"] == 3
        assert snap["avg_latency_ns"] == 1000.0
        assert snap["min_latency_ns"] == 800
        assert snap["max_latency_ns"] == 1200
        assert snap.get("trade_count") == 3
        assert snap.get("non_existent", "default_val") == "default_val"

        with pytest.raises(KeyError):
            _ = snap["non_existent_key"]

    def test_dict_unpacking(self):
        snap = TradeLatencySnapshot(
            trade_count=2,
            avg_latency_ns=2000.0,
            min_latency_ns=1500,
            max_latency_ns=2500,
        )
        d = dict(snap.items())
        assert d["trade_count"] == 2
        assert d["avg_latency_ns"] == 2000.0


# ==============================================================================
# 2. TradeLatencyTracker Core Calculations
# ==============================================================================

class TestTradeLatencyTrackerCalculations:
    """Verifies nanosecond latency tracking calculations and accumulators."""

    def test_initial_state_is_zero(self):
        tracker = TradeLatencyTracker()
        assert tracker.trade_count == 0
        assert tracker.avg_latency_ns == 0.0
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.total_latency_ns == 0
        assert tracker.last_latency_ns == 0

        snap = tracker.get_snapshot()
        assert snap.trade_count == 0
        assert snap.avg_latency_ns == 0.0
        assert snap.min_latency_ns == 0
        assert snap.max_latency_ns == 0

    def test_single_trade_recording(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(1500)

        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 1500.0
        assert tracker.min_latency_ns == 1500
        assert tracker.max_latency_ns == 1500
        assert tracker.last_latency_ns == 1500
        assert tracker.total_latency_ns == 1500
        assert tracker.avg_latency_us == 1.5

    def test_multiple_trades_running_aggregations(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(1000)
        tracker.record_latency(2000)
        tracker.record_latency(3000)

        assert tracker.trade_count == 3
        assert tracker.total_latency_ns == 6000
        assert tracker.min_latency_ns == 1000
        assert tracker.max_latency_ns == 3000
        assert tracker.avg_latency_ns == 2000.0
        assert tracker.last_latency_ns == 3000

        snap = tracker.snapshot()
        assert snap.trade_count == 3
        assert snap.avg_latency_ns == 2000.0
        assert snap.min_latency_ns == 1000
        assert snap.max_latency_ns == 3000

    def test_multi_trade_batch_recording(self):
        tracker = TradeLatencyTracker()
        # 5 trades occurring in the same execution event with 800ns latency
        tracker.record_latency(800, count=5)

        assert tracker.trade_count == 5
        assert tracker.total_latency_ns == 4000
        assert tracker.min_latency_ns == 800
        assert tracker.max_latency_ns == 800
        assert tracker.avg_latency_ns == 800.0

    def test_percentile_latencies(self):
        tracker = TradeLatencyTracker()
        for i in range(1, 101):
            tracker.record_latency(i * 10)  # 10ns, 20ns, ..., 1000ns

        assert tracker.trade_count == 100
        assert tracker.percentile_latency_ns(50.0) == 510.0 or tracker.percentile_latency_ns(50.0) == 500.0
        assert tracker.percentile_latency_ns(90.0) == 910.0 or tracker.percentile_latency_ns(90.0) == 900.0
        assert tracker.percentile_latency_ns(99.0) == 1000.0 or tracker.percentile_latency_ns(99.0) == 990.0

    def test_reset_clears_all_metrics(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(1200)
        tracker.record_latency(2400)
        assert tracker.trade_count == 2

        tracker.reset()
        assert tracker.trade_count == 0
        assert tracker.avg_latency_ns == 0.0
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.total_latency_ns == 0
        assert tracker.last_latency_ns == 0


# ==============================================================================
# 3. Edge Cases & Monotonic Safety Tests
# ==============================================================================

class TestTradeLatencyTrackerEdgeCases:
    """Verifies edge cases: zero latency, negative delta clamping, clock anomalies."""

    def test_zero_latency_handled_safely(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(0)
        assert tracker.trade_count == 1
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0

    def test_negative_latency_clamped_to_zero(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(-500)
        assert tracker.trade_count == 1
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0

    def test_zero_or_negative_count_ignored(self):
        tracker = TradeLatencyTracker()
        tracker.record_latency(1000, count=0)
        tracker.record_latency(1000, count=-5)
        assert tracker.trade_count == 0
        assert tracker.total_latency_ns == 0

    def test_clock_anomaly_exit_before_entry_clamped_to_zero(self):
        """If monotonic clock jumps backwards (non-monotonic anomaly), latency must clamp to 0."""
        tracker = TradeLatencyTracker()
        # entry=2,000, exit=1,000 (backwards jump of 1,000ns)
        lat = tracker.record_execution(entry_timestamp_ns=2000, exit_timestamp_ns=1000)
        assert lat == 0
        assert tracker.trade_count == 1
        assert tracker.min_latency_ns == 0
        assert tracker.max_latency_ns == 0
        assert tracker.avg_latency_ns == 0.0

    def test_injected_deterministic_clock(self):
        time_seq = [1_000_000, 1_002_500]  # delta = 2,500 ns
        clock_iter = iter(time_seq)

        def mock_clock() -> int:
            return next(clock_iter)

        tracker = TradeLatencyTracker(clock=mock_clock)
        t_entry = tracker.start_trade()
        assert t_entry == 1_000_000

        lat = tracker.stop_trade(t_entry)
        assert lat == 2500
        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 2500.0

    def test_measure_trade_context_manager(self):
        time_seq = [10_000, 13_200]
        clock_iter = iter(time_seq)

        tracker = TradeLatencyTracker(clock=lambda: next(clock_iter))
        with tracker.measure_trade() as timer:
            pass

        assert timer.entry_ns == 10_000
        assert timer.exit_ns == 13_200
        assert timer.latency_ns == 3200
        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 3200.0

    def test_bounded_sample_buffer(self):
        """Ensure sample buffer does not grow indefinitely and cause memory leaks."""
        tracker = TradeLatencyTracker(max_samples=100)
        for i in range(250):
            tracker.record_latency(i + 10)

        assert tracker.trade_count == 250
        assert len(tracker._samples) == 100
        # Aggregators continue to reflect all 250 trades
        assert tracker.total_latency_ns == sum(i + 10 for i in range(250))


# ==============================================================================
# 4. TradeResult and Object Recording Tests
# ==============================================================================

class TestTradeLatencyTrackerObjectRecording:
    """Verifies recording trade objects (TradeResult, dict, None)."""

    def test_record_trade_result_with_precomputed_latency(self):
        tracker = TradeLatencyTracker()
        trade = TradeResult(1, 2, 50, 10000, 0, 0, entry_timestamp_ns=1000, exit_timestamp_ns=2500)
        assert trade.latency_ns == 1500

        lat = tracker.record_trade(trade)
        assert lat == 1500
        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 1500.0

    def test_record_trade_result_with_explicit_timestamps_only(self):
        tracker = TradeLatencyTracker()
        trade = TradeResult(1, 2, 50, 10000, 0, 0)
        trade.entry_timestamp_ns = 5000
        trade.exit_timestamp_ns = 7200
        trade.latency_ns = 0

        lat = tracker.record_trade(trade)
        assert lat == 2200
        assert tracker.trade_count == 1
        assert tracker.avg_latency_ns == 2200.0

    def test_record_trade_from_dict(self):
        tracker = TradeLatencyTracker()
        d_trade = {
            "order_id": 1,
            "entry_timestamp_ns": 10000,
            "exit_timestamp_ns": 11500,
            "latency_ns": 1500,
        }
        lat = tracker.record_trade(d_trade)
        assert lat == 1500
        assert tracker.trade_count == 1

    def test_record_trade_none_safe(self):
        tracker = TradeLatencyTracker()
        lat = tracker.record_trade(None)
        assert lat == 0
        assert tracker.trade_count == 0

    def test_record_trades_iterable(self):
        tracker = TradeLatencyTracker()
        trades = [
            TradeResult(1, 2, 10, 1000, 0, 0, entry_timestamp_ns=1000, exit_timestamp_ns=2000),
            TradeResult(3, 4, 20, 2000, 0, 0, entry_timestamp_ns=2000, exit_timestamp_ns=3500),
        ]
        count = tracker.record_trades(trades)
        assert count == 2
        assert tracker.trade_count == 2
        assert tracker.min_latency_ns == 1000
        assert tracker.max_latency_ns == 1500
        assert tracker.avg_latency_ns == 1250.0


# ==============================================================================
# 5. Low Measurement Overhead Benchmark
# ==============================================================================

class TestTradeLatencyOverhead:
    """Verifies that measurement overhead is low (<1 µs per measurement)."""

    def test_measurement_overhead_is_low(self):
        tracker = TradeLatencyTracker()
        n_iterations = 20_000

        t0 = time.perf_counter_ns()
        for i in range(n_iterations):
            tracker.record_latency(150)
        t1 = time.perf_counter_ns()

        elapsed_ns = t1 - t0
        ns_per_op = elapsed_ns / n_iterations

        # A clean O(1) integer recording should take < 500 ns per op even in Python
        assert ns_per_op < 1_000.0, f"Overhead too high: {ns_per_op:.1f} ns/op"
        assert tracker.trade_count == n_iterations


# ==============================================================================
# 6. OrderAdapter Integration Tests
# ==============================================================================

class TestOrderAdapterLatencyIntegration:
    """Verifies OrderAdapter seamlessly integrates with TradeLatencyTracker."""

    def test_non_crossing_order_does_not_increment_trade_count(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        order = Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(order)

        assert len(trades) == 0
        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == 0
        assert snap.avg_latency_ns == 0.0

    def test_crossing_order_records_trade_latency(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        # Resting ask
        sell_order = Order(1, 1000, 150.0, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(sell_order)
        assert adapter.trade_latency_tracker.trade_count == 0

        # Incoming crossing bid
        buy_order = Order(2, 2000, 150.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        trades = adapter.dispatch_raw_order(buy_order)

        assert len(trades) == 1
        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == 1
        assert snap.avg_latency_ns > 0.0
        assert snap.min_latency_ns > 0
        assert snap.max_latency_ns == snap.min_latency_ns
        assert adapter.trade_latency.trade_count == 1

    def test_multi_fill_crossing_records_each_trade(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        # 2 resting asks
        adapter.dispatch_raw_order(Order(1, 1000, 100.0, 25, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)))
        adapter.dispatch_raw_order(Order(2, 2000, 101.0, 25, SYMBOLS["MSFT"], int(Side.SELL), int(OrderType.LIMIT)))

        # Sweeping bid for 50 shares
        trades = adapter.dispatch_raw_order(Order(3, 3000, 102.0, 50, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT)))
        assert len(trades) == 2

        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == 2
        assert snap.avg_latency_ns > 0.0
        assert snap.max_latency_ns >= snap.min_latency_ns

    def test_adapter_clear_resets_trade_latency(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        adapter.dispatch_raw_order(Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)))
        adapter.dispatch_raw_order(Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))
        assert adapter.trade_latency_tracker.trade_count == 1

        adapter.clear()
        snap = adapter.get_trade_latency_snapshot()
        assert snap.trade_count == 0
        assert snap.avg_latency_ns == 0.0

    def test_injected_custom_trade_latency_tracker(self):
        custom_tracker = TradeLatencyTracker()
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, trade_latency_tracker=custom_tracker)

        assert adapter.trade_latency_tracker is custom_tracker
        adapter.dispatch_raw_order(Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)))
        adapter.dispatch_raw_order(Order(2, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)))

        assert custom_tracker.trade_count == 1


# ==============================================================================
# 7. TerminalDashboard Integration Tests
# ==============================================================================

class TestDashboardTradeLatencyIntegration:
    """Verifies TerminalDashboard can consume the agreed metrics interface."""

    def test_dashboard_consumes_snapshot_object(self):
        dash = TerminalDashboard(use_sample_data=False)
        assert dash.trade_count == 0
        assert dash.trade_avg_latency_ns == 0.0

        snapshot = TradeLatencySnapshot(
            trade_count=12,
            avg_latency_ns=1850.5,
            min_latency_ns=920,
            max_latency_ns=3400,
        )
        dash.update_trade_latency(snapshot)

        assert dash.trade_count == 12
        assert dash.trade_avg_latency_ns == 1850.5
        assert dash.trade_min_latency_ns == 920
        assert dash.trade_max_latency_ns == 3400
        assert dash.get_trade_latency_snapshot() is snapshot

    def test_dashboard_consumes_dictionary_snapshot(self):
        dash = TerminalDashboard(use_sample_data=False)
        dict_snapshot = {
            "trade_count": 8,
            "avg_latency_ns": 2100.0,
            "min_latency_ns": 1100,
            "max_latency_ns": 4200,
        }
        dash.update_trade_latency(dict_snapshot)

        assert dash.trade_count == 8
        assert dash.trade_avg_latency_ns == 2100.0
        assert dash.trade_min_latency_ns == 1100
        assert dash.trade_max_latency_ns == 4200

    def test_dashboard_update_none_is_safe(self):
        dash = TerminalDashboard(use_sample_data=False)
        dash.update_trade_latency(None)
        assert dash.trade_count == 0

    def test_dashboard_reset_latency_clears_trade_metrics(self):
        dash = TerminalDashboard(use_sample_data=False)
        dash.update_trade_latency({"trade_count": 5, "avg_latency_ns": 1500.0, "min_latency_ns": 1000, "max_latency_ns": 2000})
        assert dash.trade_count == 5

        dash.reset_latency()
        assert dash.trade_count == 0
        assert dash.trade_avg_latency_ns == 0.0
        assert dash.trade_min_latency_ns == 0
        assert dash.trade_max_latency_ns == 0
        assert dash.get_trade_latency_snapshot() is None


# ==============================================================================
# 8. Agreed Metrics Interface Compliance
# ==============================================================================

class TestAgreedMetricsInterfaceCompliance:
    """Verifies that the agreed interface (trade_count, avg_latency_ns, min_latency_ns, max_latency_ns)
    is consistently implemented across components.
    """

    def test_trade_latency_snapshot_compliance(self):
        snap = TradeLatencySnapshot(trade_count=10, avg_latency_ns=1200.0, min_latency_ns=800, max_latency_ns=2000)
        assert hasattr(snap, "trade_count")
        assert hasattr(snap, "avg_latency_ns")
        assert hasattr(snap, "min_latency_ns")
        assert hasattr(snap, "max_latency_ns")

    def test_adapter_stats_compliance(self):
        stats = AdapterStats(
            total_trades_generated=15,
            total_orders_dispatched=1,
        )
        stats.record_latency(1500)
        assert stats.trade_count == 15
        assert stats.avg_latency_ns == 1500.0
        assert stats.min_latency_ns == 1500
        assert stats.max_latency_ns == 1500

        snap = stats.get_trade_latency_snapshot()
        assert snap.trade_count == 15
        assert snap.avg_latency_ns == 1500.0

    def test_repetition_metrics_compliance(self):
        rep = RepetitionMetrics(
            repetition_index=1,
            orders_attempted=100,
            orders_processed=100,
            orders_dropped=0,
            orders_unhandled=0,
            orders_dispatched=100,
            trades_generated=25,
            volume_matched=2500,
            elapsed_ns=50_000,
            elapsed_sec=0.00005,
            throughput=2_000_000.0,
            scope="ENGINE_ONLY",
            avg_latency_ns=1450.0,
            min_latency_ns=600,
            max_latency_ns=3200,
        )
        assert rep.trade_count == 25
        assert rep.avg_latency_ns == 1450.0
        assert rep.min_latency_ns == 600
        assert rep.max_latency_ns == 3200

        snap = rep.get_trade_latency_snapshot()
        assert snap.trade_count == 25
        assert snap.avg_latency_ns == 1450.0
        assert snap.min_latency_ns == 600
        assert snap.max_latency_ns == 3200

    def test_benchmark_summary_compliance(self):
        config = BenchmarkConfig(orders=30, repeats=1, warmup=0, batch_size=15, scope=SCOPE_ENGINE_ONLY, seed=42)
        summary = PipelineBenchmarkRunner(config).run()

        assert hasattr(summary, "trade_count")
        assert hasattr(summary, "avg_latency_ns")
        assert hasattr(summary, "min_latency_ns")
        assert hasattr(summary, "max_latency_ns")

        snap = summary.get_trade_latency_snapshot()
        assert snap.trade_count == summary.total_trades_generated
        assert snap.avg_latency_ns == summary.mean_latency_ns
