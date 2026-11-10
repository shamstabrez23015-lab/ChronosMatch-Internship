"""Tests for ChronosMatch Focused Cython Matching Engine Benchmark (Week 4, Day 9).

Verifies the mathematical correctness, data structures, workload generators,
latency statistics, post-benchmark book consistency, and engine-vs-pipeline
isolation of the Day 9 benchmark utilities.
"""

from __future__ import annotations

import math
import pytest
from typing import Dict, List, Tuple

from chronos.matching_engine import MatchingEngine, TradeResult, SIDE_BUY, SIDE_SELL
from scripts.benchmark_matching_engine import (
    calculate_percentile,
    compute_latency_stats,
    generate_crossing_orders,
    generate_multilevel_sweep_workload,
    generate_passive_book_workload,
    generate_balanced_market_workload,
    MatchingEngineBenchmarkRunner,
    run_pipeline_vs_engine_comparison,
    format_engine_benchmark_report,
)


# ==============================================================================
# Percentile and Latency Statistics Tests
# ==============================================================================

class TestLatencyStatistics:
    """Test percentile calculations and latency statistics aggregation."""

    def test_calculate_percentile_empty(self):
        assert calculate_percentile([], 50.0) == 0.0
        assert calculate_percentile([], 99.0) == 0.0

    def test_calculate_percentile_single(self):
        assert calculate_percentile([42.5], 0.0) == 42.5
        assert calculate_percentile([42.5], 50.0) == 42.5
        assert calculate_percentile([42.5], 100.0) == 42.5

    def test_calculate_percentile_exact_ranks(self):
        # 11 values from 0.0 to 10.0
        data = [float(i) for i in range(11)]
        assert calculate_percentile(data, 0.0) == pytest.approx(0.0)
        assert calculate_percentile(data, 50.0) == pytest.approx(5.0)
        assert calculate_percentile(data, 90.0) == pytest.approx(9.0)
        assert calculate_percentile(data, 100.0) == pytest.approx(10.0)

    def test_calculate_percentile_interpolation(self):
        # 2 values: 10.0 and 20.0
        data = [10.0, 20.0]
        assert calculate_percentile(data, 25.0) == pytest.approx(12.5)
        assert calculate_percentile(data, 50.0) == pytest.approx(15.0)
        assert calculate_percentile(data, 75.0) == pytest.approx(17.5)

    def test_compute_latency_stats_empty(self):
        stats = compute_latency_stats([])
        assert stats["count"] == 0
        assert stats["min_us"] == 0.0
        assert stats["mean_us"] == 0.0
        assert stats["median_us"] == 0.0
        assert stats["p90_us"] == 0.0
        assert stats["p95_us"] == 0.0
        assert stats["p99_us"] == 0.0
        assert stats["max_us"] == 0.0
        assert stats["sub_millisecond"] is True

    def test_compute_latency_stats_known_values(self):
        # 1,000 samples of 10,000 ns (10.0 µs)
        samples_ns = [10_000] * 1000
        stats = compute_latency_stats(samples_ns)
        assert stats["count"] == 1000
        assert stats["min_us"] == pytest.approx(10.0)
        assert stats["mean_us"] == pytest.approx(10.0)
        assert stats["median_us"] == pytest.approx(10.0)
        assert stats["p95_us"] == pytest.approx(10.0)
        assert stats["p99_us"] == pytest.approx(10.0)
        assert stats["max_us"] == pytest.approx(10.0)
        assert stats["sub_millisecond"] is True

    def test_compute_latency_stats_sub_millisecond_flag(self):
        # Latencies below 1,000 µs (1 ms)
        fast_samples_ns = [500_000] * 100  # 500 µs
        assert compute_latency_stats(fast_samples_ns)["sub_millisecond"] is True

        # P99 latency above 1,000 µs
        slow_samples_ns = [100_000] * 98 + [1_500_000] * 2  # P99 > 1000 µs
        assert compute_latency_stats(slow_samples_ns)["sub_millisecond"] is False


# ==============================================================================
# Workload Generator Tests
# ==============================================================================

class TestWorkloadGenerators:
    """Validate determinism, structure, and constraints of benchmark workload generators."""

    def test_generate_crossing_orders_count_and_fields(self):
        orders = generate_crossing_orders(num_pairs=50, seed=42)
        assert len(orders) == 100
        for oid, side, price, qty, ts in orders:
            assert isinstance(oid, int) and oid > 0
            assert side in (SIDE_BUY, SIDE_SELL)
            assert isinstance(price, float) and price > 0
            assert isinstance(qty, int) and qty > 0
            assert isinstance(ts, int) and ts > 0

    def test_generate_crossing_orders_crossing_behavior(self):
        # Ensure that every pair contains opposing sides with crossing prices
        orders = generate_crossing_orders(num_pairs=10, seed=123)
        for i in range(0, len(orders), 2):
            maker = orders[i]
            taker = orders[i + 1]
            assert maker[1] != taker[1]  # Opposing sides
            if maker[1] == SIDE_SELL:
                # Maker SELL, taker BUY -> BUY price >= SELL price
                assert taker[2] >= maker[2]
            else:
                # Maker BUY, taker SELL -> SELL price <= BUY price
                assert taker[2] <= maker[2]

    def test_generate_multilevel_sweep_workload(self):
        num_sweeps = 5
        levels = 4
        orders = generate_multilevel_sweep_workload(num_sweeps=num_sweeps, levels_per_sweep=levels, seed=777)
        # Each sweep has `levels` SELL orders + 1 aggressive BUY order
        assert len(orders) == num_sweeps * (levels + 1)
        for i in range(0, len(orders), levels + 1):
            swept_asks = orders[i:i + levels]
            sweep_buy = orders[i + levels]
            assert all(o[1] == SIDE_SELL for o in swept_asks)
            assert sweep_buy[1] == SIDE_BUY
            # Sweep buy price must be >= max ask price in the sweep
            max_ask_price = max(o[2] for o in swept_asks)
            assert sweep_buy[2] >= max_ask_price

    def test_generate_passive_book_workload(self):
        orders = generate_passive_book_workload(num_orders=100, seed=101)
        assert len(orders) == 100
        # Check that bids and asks never cross
        bids = [o for o in orders if o[1] == SIDE_BUY]
        asks = [o for o in orders if o[1] == SIDE_SELL]
        assert len(bids) > 0
        assert len(asks) > 0
        max_bid = max(o[2] for o in bids)
        min_ask = min(o[2] for o in asks)
        assert max_bid < min_ask  # Non-crossing invariant

    def test_generate_balanced_market_workload(self):
        orders = generate_balanced_market_workload(num_orders=200, seed=555)
        assert len(orders) == 200
        bids = [o for o in orders if o[1] == SIDE_BUY]
        asks = [o for o in orders if o[1] == SIDE_SELL]
        assert len(bids) > 0
        assert len(asks) > 0


# ==============================================================================
# Matching Engine Benchmark Runner & Order Book Consistency Tests
# ==============================================================================

class TestMatchingEngineBenchmarkRunner:
    """Verify execution of workloads through the benchmark runner and verify book consistency."""

    def test_run_workload_crossing_scenario(self):
        runner = MatchingEngineBenchmarkRunner()
        orders = generate_crossing_orders(num_pairs=50, seed=42)
        res = runner.run_workload(orders, is_warmup=False)

        assert res["orders_processed"] == 100
        assert res["elapsed_ns"] > 0
        assert res["throughput"] > 0.0
        assert res["total_trades"] > 0
        assert res["total_executed_qty"] > 0
        assert res["latency"]["count"] == 100
        assert res["latency"]["sub_millisecond"] is True

    def test_run_scenario_repetition_aggregation(self):
        runner = MatchingEngineBenchmarkRunner()
        orders = generate_crossing_orders(num_pairs=20, seed=99)
        summary = runner.run_scenario("Crossing-Test", orders, repeats=2, warmup=1)

        assert summary["scenario"] == "Crossing-Test"
        assert summary["orders_per_run"] == 40
        assert summary["repeats"] == 2
        assert summary["warmup_runs"] == 1
        assert len(summary["repetitions"]) == 2
        assert summary["mean_throughput"] > 0.0
        assert summary["latency_summary"]["min_us"] > 0.0
        assert summary["latency_summary"]["sub_millisecond_verified"] is True

    def test_post_benchmark_book_consistency_crossing(self):
        engine = MatchingEngine()
        orders = generate_crossing_orders(num_pairs=10, seed=12)
        for oid, side, price, qty, ts in orders:
            engine.match_order(oid, side, price, qty, ts)

        # Snapshot must be consistent
        snap = engine.get_order_book_snapshot()
        assert isinstance(snap["bids"], list)
        assert isinstance(snap["asks"], list)
        # Any resting orders must have remaining_quantity > 0
        for b in snap["bids"]:
            assert b.remaining_quantity > 0
        for a in snap["asks"]:
            assert a.remaining_quantity > 0

    def test_post_benchmark_passive_depth_invariants(self):
        engine = MatchingEngine()
        orders = generate_passive_book_workload(num_orders=50, seed=888)
        trades_total = 0
        for oid, side, price, qty, ts in orders:
            trades = engine.match_order(oid, side, price, qty, ts)
            trades_total += len(trades)

        # Passive orders should not match any trades
        assert trades_total == 0
        assert engine.order_count() == 50

        # Snapshot check: bids sorted descending, asks sorted ascending
        snap = engine.get_order_book_snapshot()
        bids = snap["bids"]
        asks = snap["asks"]
        assert len(bids) + len(asks) == 50

        for i in range(len(bids) - 1):
            assert bids[i].price_cents >= bids[i + 1].price_cents
        for i in range(len(asks) - 1):
            assert asks[i].price_cents <= asks[i + 1].price_cents

        # Best bid < best ask
        best_bid = engine.get_best_buy_order()
        best_ask = engine.get_best_sell_order()
        assert best_bid is not None
        assert best_ask is not None
        assert best_bid.price_cents < best_ask.price_cents

    def test_post_benchmark_multilevel_sweep_execution(self):
        engine = MatchingEngine()
        # 1 sweep with 4 levels
        orders = generate_multilevel_sweep_workload(num_sweeps=1, levels_per_sweep=4, seed=44)
        all_trades: List[TradeResult] = []
        for oid, side, price, qty, ts in orders:
            trades = engine.match_order(oid, side, price, qty, ts)
            all_trades.extend(trades)

        # The aggressive BUY sweep must match across multiple price levels
        assert len(all_trades) >= 2
        # Execution prices must strictly ascend (maker price policy & price priority)
        exec_prices = [t.execution_price for t in all_trades]
        assert exec_prices == sorted(exec_prices)
        for i in range(len(exec_prices) - 1):
            assert exec_prices[i] <= exec_prices[i + 1]

        # Verify buy_remaining_quantity decreases with each execution to 0
        total_exec = sum(t.executed_quantity for t in all_trades)
        sweep_buy_order = orders[-1]
        assert total_exec == sweep_buy_order[3]

    def test_exhaustive_multilevel_sweep_clears_all_levels(self):
        engine = MatchingEngine()
        # Place 4 resting SELL orders at distinct prices
        engine.match_order(1, SIDE_SELL, 100.0, 10, 1000)
        engine.match_order(2, SIDE_SELL, 101.0, 20, 2000)
        engine.match_order(3, SIDE_SELL, 102.0, 30, 3000)
        engine.match_order(4, SIDE_SELL, 103.0, 40, 4000)

        # Incoming BUY order with qty=150 and price=105.0 sweeps all 4 levels
        trades = engine.match_order(5, SIDE_BUY, 105.0, 150, 5000)
        assert len(trades) == 4
        assert [t.execution_price for t in trades] == [100.0, 101.0, 102.0, 103.0]
        assert [t.executed_quantity for t in trades] == [10, 20, 30, 40]
        assert len(engine.get_asks()) == 0
        # Residual 50 BUY quantity rests in bids
        bids = engine.get_bids()
        assert len(bids) == 1
        assert bids[0].remaining_quantity == 50


# ==============================================================================
# Pipeline Isolation and Reporting Tests
# ==============================================================================

class TestPipelineComparisonAndReporting:
    """Verify latency isolation helper and text reporting."""

    def test_pipeline_vs_engine_comparison_structure(self):
        comp = run_pipeline_vs_engine_comparison(order_count=100)
        assert comp["orders_tested"] == 100
        assert "engine_only" in comp
        assert "full_pipeline" in comp
        assert "engine_latency_ratio_pct" in comp

        eng = comp["engine_only"]
        pipe = comp["full_pipeline"]
        assert eng["throughput_ord_sec"] > 0.0
        assert eng["avg_latency_per_order_us"] > 0.0
        assert pipe["throughput_ord_sec"] > 0.0
        assert pipe["avg_latency_per_order_us"] > 0.0

    def test_format_engine_benchmark_report(self):
        fake_results = [
            {
                "scenario": "Crossing (Fills)",
                "orders_per_run": 1000,
                "repeats": 2,
                "warmup_runs": 1,
                "mean_throughput": 45000.0,
                "min_throughput": 44000.0,
                "max_throughput": 46000.0,
                "std_throughput": 1414.0,
                "mean_elapsed_sec": 0.022,
                "latency_summary": {
                    "min_us": 1.2,
                    "mean_us": 22.2,
                    "p95_us": 85.0,
                    "p99_us": 140.0,
                    "max_us": 550.0,
                    "sub_millisecond_verified": True,
                },
                "repetitions": [],
            }
        ]
        report_text = format_engine_benchmark_report(fake_results)
        assert "CHRONOSMATCH :: CYTHON MATCHING ENGINE PERFORMANCE BENCHMARK" in report_text
        assert "Crossing (Fills)" in report_text
        assert "YES" in report_text
        assert "Detailed Latency Metrics" in report_text
