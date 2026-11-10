"""Unit and Integration Tests for Nanosecond Trade Entry/Exit Timestamp Capture and Latency Calculation.

Week 3, Day 2 Tests:
1. TradeResult timestamp fields, latency calculation, set_timestamps, and latency_us property.
2. MatchingEngine nanosecond entry and exit timestamp capture during match_order and execute_partial_match.
3. Multi-fill trade timestamp association with the triggering execution event.
4. OrderAdapter nanosecond execution boundaries (dispatch_raw_order).
5. TradeExecutionEvent records with correct trade and order associations.
6. AdapterStats latency aggregation (min, max, avg, percentiles) and reset behavior.
7. PipelineBenchmarkRunner latency metrics integration across scopes.
8. Zero/monotonic safety checks (no underflows or negative latency).
"""

from __future__ import annotations

import time
import pytest

from chronos.adapter import AdapterStats, OrderAdapter, TradeExecutionEvent
from chronos.benchmark import (
    BenchmarkConfig,
    PipelineBenchmarkRunner,
    RepetitionMetrics,
    SCOPE_ADAPTER_ENGINE,
    SCOPE_ENGINE_ONLY,
    SCOPE_FULL,
)
from chronos.matching_engine import MatchingEngine, SIDE_BUY, SIDE_SELL, TradeResult
from chronos.protocol import Order, OrderType, Side, SYMBOLS


# ==============================================================================
# 1. TradeResult Nanosecond Timestamp and Latency Tests
# ==============================================================================

class TestTradeResultTimestamps:
    """Verifies TradeResult nanosecond timestamp fields and latency computation."""

    def test_trade_result_default_timestamps(self):
        trade = TradeResult(
            buy_order_id=1,
            sell_order_id=2,
            executed_quantity=100,
            execution_price_cents=10000,
            buy_remaining_quantity=0,
            sell_remaining_quantity=0,
        )
        assert trade.entry_timestamp_ns == 0
        assert trade.exit_timestamp_ns == 0
        assert trade.latency_ns == 0
        assert trade.latency_us == 0.0

    def test_trade_result_with_explicit_timestamps(self):
        t_entry = 1_000_000_000
        t_exit = 1_000_002_500  # 2,500 ns = 2.5 µs
        trade = TradeResult(
            buy_order_id=10,
            sell_order_id=20,
            executed_quantity=50,
            execution_price_cents=15000,
            buy_remaining_quantity=0,
            sell_remaining_quantity=0,
            entry_timestamp_ns=t_entry,
            exit_timestamp_ns=t_exit,
        )
        assert trade.entry_timestamp_ns == t_entry
        assert trade.exit_timestamp_ns == t_exit
        assert trade.latency_ns == 2500
        assert trade.latency_us == 2.5

    def test_trade_result_set_timestamps(self):
        trade = TradeResult(1, 2, 10, 5000, 0, 0)
        trade.set_timestamps(entry_ns=100_000, exit_ns=105_200)
        assert trade.entry_timestamp_ns == 100_000
        assert trade.exit_timestamp_ns == 105_200
        assert trade.latency_ns == 5200
        assert trade.latency_us == 5.2

    def test_trade_result_monotonic_clock_anomaly_safety(self):
        """If exit_timestamp < entry_timestamp, latency_ns must be 0 (no unsigned underflow)."""
        trade = TradeResult(1, 2, 10, 5000, 0, 0)
        trade.set_timestamps(entry_ns=200_000, exit_ns=100_000)
        assert trade.latency_ns == 0
        assert trade.latency_us == 0.0

    def test_trade_result_as_dict_timing_option(self):
        trade = TradeResult(1, 2, 10, 5000, 0, 0)
        trade.set_timestamps(1_000, 1_500)

        # Default preserves backward compatibility (7 keys)
        d_compat = trade.as_dict()
        assert "entry_timestamp_ns" not in d_compat
        assert len(d_compat) == 7

        # include_timing=True includes timing keys
        d_timed = trade.as_dict(include_timing=True)
        assert d_timed["entry_timestamp_ns"] == 1_000
        assert d_timed["exit_timestamp_ns"] == 1_500
        assert d_timed["latency_ns"] == 500

    def test_trade_result_repr_shows_latency_when_present(self):
        trade = TradeResult(1, 2, 10, 5000, 0, 0)
        assert "lat_ns=" not in repr(trade)

        trade.set_timestamps(1000, 2500)
        r = repr(trade)
        assert "lat_ns=1500" in r
        assert "TradeResult" in r


# ==============================================================================
# 2. MatchingEngine Timestamp Capture and Latency Tracking Tests
# ==============================================================================

class TestMatchingEngineTimestamps:
    """Verifies that MatchingEngine captures entry and exit timestamps using time.perf_counter_ns()."""

    def test_match_order_captures_entry_and_exit_timestamps(self):
        engine = MatchingEngine()
        # Seed resting SELL order
        engine.submit_order(1, SIDE_SELL, 100.0, 50, timestamp_ns=1000)

        t_before = time.perf_counter_ns()
        trades = engine.match_order(2, SIDE_BUY, 100.0, 50, timestamp_ns=2000)
        t_after = time.perf_counter_ns()

        assert len(trades) == 1
        trade = trades[0]
        # Timestamps must fall within the execution window
        assert t_before <= trade.entry_timestamp_ns <= trade.exit_timestamp_ns <= t_after
        assert trade.latency_ns == trade.exit_timestamp_ns - trade.entry_timestamp_ns
        assert trade.latency_ns >= 0
        assert engine.last_latency_ns == trade.latency_ns
        assert engine.matching_events_count == 1
        assert engine.get_avg_matching_latency_ns() == float(trade.latency_ns)

    def test_execute_partial_match_captures_timestamps(self):
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_BUY, 50.0, 10, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 50.0, 10, timestamp_ns=2000)

        t_before = time.perf_counter_ns()
        trade = engine.execute_partial_match()
        t_after = time.perf_counter_ns()

        assert trade is not None
        assert t_before <= trade.entry_timestamp_ns <= trade.exit_timestamp_ns <= t_after
        assert trade.latency_ns == trade.exit_timestamp_ns - trade.entry_timestamp_ns
        assert engine.last_latency_ns == trade.latency_ns
        assert engine.matching_events_count == 1

    def test_multi_fill_trades_share_execution_event_timestamps(self):
        """When an incoming order sweeps across multiple resting orders, all fills carry the event timestamps."""
        engine = MatchingEngine()
        # Resting asks at $100.00 and $101.00
        engine.submit_order(1, SIDE_SELL, 100.0, 25, timestamp_ns=1000)
        engine.submit_order(2, SIDE_SELL, 101.0, 25, timestamp_ns=2000)

        t_before = time.perf_counter_ns()
        trades = engine.match_order(3, SIDE_BUY, 102.0, 50, timestamp_ns=3000)
        t_after = time.perf_counter_ns()

        assert len(trades) == 2
        t1, t2 = trades[0], trades[1]
        assert t1.entry_timestamp_ns == t2.entry_timestamp_ns
        assert t1.exit_timestamp_ns == t2.exit_timestamp_ns
        assert t1.latency_ns == t2.latency_ns
        assert t_before <= t1.entry_timestamp_ns <= t1.exit_timestamp_ns <= t_after

    def test_engine_clear_resets_latency_metrics(self):
        engine = MatchingEngine()
        engine.submit_order(1, SIDE_SELL, 100.0, 50, 1000)
        engine.match_order(2, SIDE_BUY, 100.0, 50, 2000)
        assert engine.matching_events_count == 1
        assert engine.last_latency_ns > 0

        engine.clear()
        assert engine.matching_events_count == 0
        assert engine.last_latency_ns == 0
        assert engine.total_matching_latency_ns == 0
        assert engine.get_avg_matching_latency_ns() == 0.0

    def test_track_timestamps_disabled_mode(self):
        """When track_timestamps=False, timestamps are omitted for maximum raw execution."""
        engine = MatchingEngine(track_timestamps=False)
        assert engine.track_timestamps is False

        engine.submit_order(1, SIDE_SELL, 100.0, 50, 1000)
        trades = engine.match_order(2, SIDE_BUY, 100.0, 50, 2000)
        assert len(trades) == 1
        assert trades[0].entry_timestamp_ns == 0
        assert trades[0].exit_timestamp_ns == 0
        assert trades[0].latency_ns == 0
        assert engine.last_latency_ns == 0


# ==============================================================================
# 3. OrderAdapter Timestamp Capture and TradeExecutionEvent Tests
# ==============================================================================

class TestOrderAdapterLatencyCapture:
    """Verifies that OrderAdapter measures nanosecond execution latency and logs TradeExecutionEvent."""

    def test_adapter_captures_trade_execution_event(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        # Resting SELL
        sell_order = Order(1, 1000, 150.0, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(sell_order)

        # Incoming crossing BUY
        buy_order = Order(2, 2000, 150.0, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        t_before = time.perf_counter_ns()
        trades = adapter.dispatch_raw_order(buy_order)
        t_after = time.perf_counter_ns()

        assert len(trades) == 1
        assert len(adapter.execution_events) == 2

        # Inspect the matching execution event
        match_event = adapter.execution_events[1]
        assert isinstance(match_event, TradeExecutionEvent)
        assert match_event.order_id == 2
        assert match_event.symbol_id == SYMBOLS["AAPL"]
        assert match_event.side == int(Side.BUY)
        assert match_event.price == 150.0
        assert match_event.quantity == 50
        assert match_event.matched is True
        assert match_event.volume_matched == 50
        assert len(match_event.trades) == 1
        assert t_before <= match_event.entry_timestamp_ns <= match_event.exit_timestamp_ns <= t_after
        assert match_event.latency_ns == match_event.exit_timestamp_ns - match_event.entry_timestamp_ns
        assert match_event.latency_us == match_event.latency_ns / 1_000.0

    def test_adapter_non_crossing_execution_event(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match")

        order = Order(1, 1000, 100.0, 20, SYMBOLS["MSFT"], int(Side.BUY), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(order)

        assert len(adapter.execution_events) == 1
        ev = adapter.execution_events[0]
        assert ev.order_id == 1
        assert ev.matched is False
        assert ev.volume_matched == 0
        assert ev.trades == []
        assert ev.latency_ns >= 0
        assert ev.entry_timestamp_ns > 0
        assert ev.exit_timestamp_ns >= ev.entry_timestamp_ns

    def test_adapter_stats_latency_aggregations(self):
        stats = AdapterStats()
        stats.total_orders_dispatched = 3
        stats.record_latency(1000)
        stats.record_latency(2000)
        stats.record_latency(3000)

        assert stats.total_execution_latency_ns == 6000
        assert stats.min_execution_latency_ns == 1000
        assert stats.max_execution_latency_ns == 3000
        assert stats.last_execution_latency_ns == 3000
        assert stats.avg_execution_latency_ns == 2000.0
        assert stats.avg_execution_latency_us == 2.0
        assert stats.p50_execution_latency_ns == 2000.0
        assert stats.p90_execution_latency_ns == 3000.0
        assert stats.p99_execution_latency_ns == 3000.0

    def test_adapter_stats_reset_clears_latency(self):
        stats = AdapterStats()
        stats.record_latency(1500)
        assert stats.total_execution_latency_ns == 1500

        stats.reset()
        assert stats.total_execution_latency_ns == 0
        assert stats.min_execution_latency_ns == 0
        assert stats.max_execution_latency_ns == 0
        assert stats.last_execution_latency_ns == 0
        assert stats.avg_execution_latency_ns == 0.0
        assert stats.execution_latencies_ns == []

    def test_adapter_clear_clears_execution_events(self):
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine)
        order = Order(1, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))
        adapter.dispatch_raw_order(order)
        assert len(adapter.execution_events) == 1

        adapter.clear()
        assert len(adapter.execution_events) == 0
        assert adapter.stats.total_execution_latency_ns == 0


# ==============================================================================
# 4. Pipeline Benchmark Runner Latency Integration Tests
# ==============================================================================

class TestBenchmarkPipelineLatencyIntegration:
    """Verifies that PipelineBenchmarkRunner records nanosecond latency across scopes."""

    def test_full_pipeline_records_execution_latency(self):
        config = BenchmarkConfig(orders=50, repeats=1, warmup=0, batch_size=25, scope=SCOPE_FULL, seed=42)
        summary = PipelineBenchmarkRunner(config).run()

        rep = summary.repetitions[0]
        assert rep.avg_latency_ns > 0.0
        assert rep.min_latency_ns > 0
        assert rep.max_latency_ns >= rep.min_latency_ns
        assert rep.p50_latency_ns > 0.0
        assert rep.p99_latency_ns >= rep.p50_latency_ns

        assert summary.mean_latency_ns > 0.0
        assert summary.median_latency_ns > 0.0
        assert summary.p99_latency_ns >= summary.median_latency_ns

    def test_adapter_engine_scope_records_execution_latency(self):
        config = BenchmarkConfig(orders=40, repeats=1, warmup=0, batch_size=20, scope=SCOPE_ADAPTER_ENGINE, seed=42)
        summary = PipelineBenchmarkRunner(config).run()

        rep = summary.repetitions[0]
        assert rep.avg_latency_ns > 0.0
        assert summary.mean_latency_ns > 0.0

    def test_engine_only_scope_records_execution_latency(self):
        config = BenchmarkConfig(orders=40, repeats=1, warmup=0, batch_size=20, scope=SCOPE_ENGINE_ONLY, seed=42)
        summary = PipelineBenchmarkRunner(config).run()

        rep = summary.repetitions[0]
        assert rep.avg_latency_ns > 0.0
        assert summary.mean_latency_ns > 0.0
