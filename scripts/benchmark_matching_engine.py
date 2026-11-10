#!/usr/bin/env python3
"""ChronosMatch -- Focused Cython Matching Engine Benchmark (Week 4, Day 9).

Benchmarks pure matching-engine operations using high-resolution monotonic timing
(time.perf_counter_ns) across multiple scenarios and order volumes:
1. Crossing Orders (Full & Partial Fills)
2. Multi-Level Sweeps (Deep Liquidity Exhaustion)
3. Passive Book Building (Non-Crossing Limit Orders)
4. Balanced Continuous Market (Two-Sided Trading Flow)

Measures and reports:
- Throughput (orders/second)
- Average, minimum, maximum, and P50/P90/P95/P99 latency
- Sub-millisecond verification (< 1.0 ms)
- Comparison of pure matching-engine latency vs. end-to-end pipeline latency
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import random
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Enable 1ms timer resolution on Windows if available
if sys.platform == "win32":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

# Ensure UTF-8 output handles formatting smoothly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chronos.matching_engine import MatchingEngine, TradeResult, SIDE_BUY, SIDE_SELL


# ==============================================================================
# Latency and Percentile Utilities
# ==============================================================================

def calculate_percentile(sorted_values: List[float], percentile: float) -> float:
    """Calculate the given percentile (0 to 100) from a sorted list of floats."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = (percentile / 100.0) * (n - 1)
    k = int(rank)
    d = rank - k
    if k + 1 < n:
        return sorted_values[k] + d * (sorted_values[k + 1] - sorted_values[k])
    return sorted_values[-1]


def compute_latency_stats(latencies_ns: List[int]) -> Dict[str, float]:
    """Compute comprehensive latency statistics in microseconds from nanosecond samples."""
    if not latencies_ns:
        return {
            "count": 0,
            "min_us": 0.0,
            "mean_us": 0.0,
            "median_us": 0.0,
            "p90_us": 0.0,
            "p95_us": 0.0,
            "p99_us": 0.0,
            "max_us": 0.0,
            "sub_millisecond": True,
        }

    # Convert to microseconds
    latencies_us = [ns / 1_000.0 for ns in latencies_ns]
    latencies_us.sort()

    mean_val = statistics.mean(latencies_us)
    median_val = statistics.median(latencies_us)
    min_val = latencies_us[0]
    max_val = latencies_us[-1]
    p90_val = calculate_percentile(latencies_us, 90.0)
    p95_val = calculate_percentile(latencies_us, 95.0)
    p99_val = calculate_percentile(latencies_us, 99.0)

    # Sub-millisecond check (< 1000.0 microseconds)
    sub_ms = p99_val < 1000.0

    return {
        "count": len(latencies_us),
        "min_us": round(min_val, 3),
        "mean_us": round(mean_val, 3),
        "median_us": round(median_val, 3),
        "p90_us": round(p90_val, 3),
        "p95_us": round(p95_val, 3),
        "p99_us": round(p99_val, 3),
        "max_us": round(max_val, 3),
        "sub_millisecond": sub_ms,
    }


# ==============================================================================
# Synthetic Order Workloads for Realistic Matching Engine Scenarios
# ==============================================================================

def generate_passive_orders(num_orders: int, seed: int = 42) -> List[Tuple[int, int, float, int, int]]:
    """Generate non-crossing resting limit orders that build book depth."""
    rng = random.Random(seed)
    orders = []
    base_bid = 100.0
    base_ask = 101.0
    for i in range(1, num_orders + 1):
        side = SIDE_BUY if rng.random() < 0.5 else SIDE_SELL
        if side == SIDE_BUY:
            price = round(base_bid - rng.uniform(0.01, 10.0), 2)
        else:
            price = round(base_ask + rng.uniform(0.01, 10.0), 2)
        qty = rng.randint(10, 200)
        ts = i * 1000
        orders.append((i, side, price, qty, ts))
    return orders


# Alias for explicit workload naming
generate_passive_book_workload = generate_passive_orders


def generate_crossing_orders(num_pairs: int, seed: int = 123) -> List[Tuple[int, int, float, int, int]]:
    """Generate pairs of matching orders (resting order followed immediately by crossing order)."""
    rng = random.Random(seed)
    orders = []
    oid = 1
    for _ in range(num_pairs):
        price = round(rng.uniform(50.0, 250.0), 2)
        qty_resting = rng.randint(20, 100)
        # Alternate maker side
        if rng.random() < 0.5:
            # Maker is SELL, taker is BUY
            orders.append((oid, SIDE_SELL, price, qty_resting, oid * 1000))
            oid += 1
            # Taker crosses at same or better price
            taker_price = round(price + rng.uniform(0.0, 2.0), 2)
            taker_qty = rng.randint(10, 150)
            orders.append((oid, SIDE_BUY, taker_price, taker_qty, oid * 1000))
            oid += 1
        else:
            # Maker is BUY, taker is SELL
            orders.append((oid, SIDE_BUY, price, qty_resting, oid * 1000))
            oid += 1
            taker_price = round(price - rng.uniform(0.0, 2.0), 2)
            taker_qty = rng.randint(10, 150)
            orders.append((oid, SIDE_SELL, taker_price, taker_qty, oid * 1000))
            oid += 1
    return orders


def generate_multilevel_sweep_workload(
    num_sweeps: int, levels_per_sweep: int = 5, seed: int = 999
) -> List[Tuple[int, int, float, int, int]]:
    """Generate orders where multiple passive levels are placed, followed by an aggressive sweeping order."""
    rng = random.Random(seed)
    orders = []
    oid = 1
    for _ in range(num_sweeps):
        base_price = round(rng.uniform(100.0, 200.0), 2)
        total_resting_qty = 0
        # Place N resting SELL levels
        for level in range(levels_per_sweep):
            price = round(base_price + (level * 0.25), 2)
            qty = rng.randint(20, 50)
            total_resting_qty += qty
            orders.append((oid, SIDE_SELL, price, qty, oid * 1000))
            oid += 1
        # Aggressive sweeping BUY order
        sweep_price = round(base_price + (levels_per_sweep * 0.50), 2)
        sweep_qty = int(total_resting_qty * rng.uniform(0.7, 1.2))
        orders.append((oid, SIDE_BUY, sweep_price, sweep_qty, oid * 1000))
        oid += 1
    return orders


def generate_balanced_market_workload(num_orders: int, seed: int = 777) -> List[Tuple[int, int, float, int, int]]:
    """Generate realistic balanced two-sided market flow with fluctuating spread and natural crossings."""
    rng = random.Random(seed)
    orders = []
    mid_price = 150.0
    for i in range(1, num_orders + 1):
        # Drift mid price slightly
        mid_price += rng.uniform(-0.10, 0.10)
        mid_price = max(10.0, round(mid_price, 2))

        side = SIDE_BUY if rng.random() < 0.5 else SIDE_SELL
        is_aggressive = rng.random() < 0.35  # 35% crossing orders

        if side == SIDE_BUY:
            if is_aggressive:
                price = round(mid_price + rng.uniform(0.00, 0.50), 2)
            else:
                price = round(mid_price - rng.uniform(0.01, 1.50), 2)
        else:
            if is_aggressive:
                price = round(mid_price - rng.uniform(0.00, 0.50), 2)
            else:
                price = round(mid_price + rng.uniform(0.01, 1.50), 2)

        qty = rng.randint(10, 100)
        orders.append((i, side, price, qty, i * 1000))
    return orders


# ==============================================================================
# Matching Engine Benchmark Runner
# ==============================================================================

class MatchingEngineBenchmarkRunner:
    """Benchmark runner measuring matching-engine throughput, latency, and correctness."""

    def __init__(self, record_individual_latencies: bool = True):
        self.record_latencies = record_individual_latencies

    def run_workload(
        self,
        orders: List[Tuple[int, int, float, int, int]],
        is_warmup: bool = False,
    ) -> Dict[str, Any]:
        """Execute a batch of orders on a pristine MatchingEngine and record performance."""
        engine = MatchingEngine()
        trades_count = 0
        volume_count = 0
        latencies_ns: List[int] = []

        # Monotonic high-resolution timer
        t_batch_start = time.perf_counter_ns()

        if self.record_latencies and not is_warmup:
            for oid, side, price, qty, ts in orders:
                t0 = time.perf_counter_ns()
                trades = engine.match_order(oid, side, price, qty, ts)
                t1 = time.perf_counter_ns()
                latencies_ns.append(max(0, t1 - t0))
                trades_count += len(trades)
                for t in trades:
                    volume_count += t.executed_quantity
        else:
            for oid, side, price, qty, ts in orders:
                trades = engine.match_order(oid, side, price, qty, ts)
                trades_count += len(trades)
                for t in trades:
                    volume_count += t.executed_quantity

        t_batch_end = time.perf_counter_ns()

        elapsed_ns = max(0, t_batch_end - t_batch_start)
        elapsed_sec = elapsed_ns / 1_000_000_000.0
        orders_count = len(orders)
        throughput = round(orders_count / elapsed_sec, 2) if elapsed_sec > 0 else 0.0

        latency_stats = compute_latency_stats(latencies_ns) if latencies_ns else {
            "mean_us": round((elapsed_sec * 1_000_000.0) / orders_count, 3) if orders_count else 0.0,
            "min_us": 0.0,
            "max_us": 0.0,
            "median_us": 0.0,
            "p90_us": 0.0,
            "p95_us": 0.0,
            "p99_us": 0.0,
            "sub_millisecond": True,
        }

        # Snapshot consistency validation post-benchmark
        snap = engine.get_order_book_snapshot()

        return {
            "orders": orders_count,
            "orders_processed": orders_count,
            "trades": trades_count,
            "total_trades": trades_count,
            "volume": volume_count,
            "total_executed_qty": volume_count,
            "elapsed_sec": round(elapsed_sec, 5),
            "elapsed_ns": elapsed_ns,
            "throughput": throughput,
            "latency": latency_stats,
            "book_state": {
                "bid_count": snap["bid_count"],
                "ask_count": snap["ask_count"],
                "best_bid": snap["best_bid_price"],
                "best_ask": snap["best_ask_price"],
                "spread": snap["spread"],
            },
            "is_warmup": is_warmup,
        }

    def run_scenario(
        self,
        name: str,
        orders: List[Tuple[int, int, float, int, int]],
        repeats: int = 3,
        warmup: int = 1,
    ) -> Dict[str, Any]:
        """Execute warmup and measured repetitions for a specific scenario."""
        # 1. Warm-up runs (isolated from metrics)
        for _ in range(warmup):
            self.run_workload(orders, is_warmup=True)

        # 2. Measured repetitions
        reps = []
        all_latencies_ns: List[int] = []
        for i in range(repeats):
            rep_res = self.run_workload(orders, is_warmup=False)
            reps.append(rep_res)

        throughputs = [r["throughput"] for r in reps]
        elapsed_times = [r["elapsed_sec"] for r in reps]

        mean_tp = round(statistics.mean(throughputs), 2)
        min_tp = round(min(throughputs), 2)
        max_tp = round(max(throughputs), 2)
        std_tp = round(statistics.stdev(throughputs), 2) if len(throughputs) > 1 else 0.0

        # Aggregate latency metrics across measured runs
        avg_mean_lat = round(statistics.mean(r["latency"]["mean_us"] for r in reps), 3)
        avg_p95_lat = round(statistics.mean(r["latency"]["p95_us"] for r in reps), 3)
        avg_p99_lat = round(statistics.mean(r["latency"]["p99_us"] for r in reps), 3)
        min_lat = round(min(r["latency"]["min_us"] for r in reps), 3)
        max_lat = round(max(r["latency"]["max_us"] for r in reps), 3)
        all_sub_ms = all(r["latency"]["sub_millisecond"] for r in reps)

        return {
            "scenario": name,
            "orders_per_run": len(orders),
            "repeats": repeats,
            "warmup_runs": warmup,
            "mean_throughput": mean_tp,
            "min_throughput": min_tp,
            "max_throughput": max_tp,
            "std_throughput": std_tp,
            "mean_elapsed_sec": round(statistics.mean(elapsed_times), 5),
            "latency_summary": {
                "min_us": min_lat,
                "mean_us": avg_mean_lat,
                "p95_us": avg_p95_lat,
                "p99_us": avg_p99_lat,
                "max_us": max_lat,
                "sub_millisecond_verified": all_sub_ms,
            },
            "repetitions": reps,
        }


# ==============================================================================
# Pipeline vs. Engine Latency Comparison
# ==============================================================================

def run_pipeline_vs_engine_comparison(order_count: int = 5000) -> Dict[str, Any]:
    """Measure and contrast pure matching-engine latency against full end-to-end pipeline latency."""
    from chronos.benchmark import BenchmarkConfig, PipelineBenchmarkRunner, SCOPE_FULL, SCOPE_ENGINE_ONLY

    # 1. Full pipeline (Generator -> Binary Protocol -> IPC Ring Buffer -> OrderAdapter -> MatchingEngine)
    cfg_full = BenchmarkConfig(orders=order_count, repeats=2, warmup=1, scope=SCOPE_FULL)
    runner_full = PipelineBenchmarkRunner(cfg_full)
    summary_full = runner_full.run()

    # 2. Pure engine only
    cfg_engine = BenchmarkConfig(orders=order_count, repeats=2, warmup=1, scope=SCOPE_ENGINE_ONLY)
    runner_engine = PipelineBenchmarkRunner(cfg_engine)
    summary_engine = runner_engine.run()

    engine_tp = summary_engine.mean_throughput
    pipeline_tp = summary_full.mean_throughput

    engine_per_order_us = round((1_000_000.0 / engine_tp), 3) if engine_tp > 0 else 0.0
    pipeline_per_order_us = round((1_000_000.0 / pipeline_tp), 3) if pipeline_tp > 0 else 0.0

    return {
        "orders_tested": order_count,
        "engine_only": {
            "throughput_ord_sec": engine_tp,
            "avg_latency_per_order_us": engine_per_order_us,
        },
        "full_pipeline": {
            "throughput_ord_sec": pipeline_tp,
            "avg_latency_per_order_us": pipeline_per_order_us,
        },
        "engine_latency_ratio_pct": round((engine_per_order_us / pipeline_per_order_us * 100.0), 2)
        if pipeline_per_order_us > 0 else 0.0,
    }


# ==============================================================================
# Reporting Formatter
# ==============================================================================

def format_engine_benchmark_report(results: List[Dict[str, Any]], comparison: Optional[Dict[str, Any]] = None) -> str:
    """Format matching-engine benchmark results into a clean, human-readable ASCII report."""
    lines = [
        "=" * 82,
        "   CHRONOSMATCH :: CYTHON MATCHING ENGINE PERFORMANCE BENCHMARK (DAY 9)",
        "=" * 82,
        f"  Monotonic Timer   : time.perf_counter_ns() [High-Resolution]",
        f"  Target Latency    : < 1.000 ms (1,000 µs) per matching operation",
        "=" * 82,
        "",
        "Scenario Benchmark Results:",
        "-" * 82,
        f"{'Scenario':<22} | {'Orders':>8} | {'Throughput (ord/s)':>18} | {'Mean (µs)':>10} | {'P95 (µs)':>9} | {'P99 (µs)':>9} | {'< 1ms':>5}",
        "-" * 82,
    ]

    for res in results:
        sc_name = res["scenario"]
        orders = f"{res['orders_per_run']:,}"
        tp = f"{res['mean_throughput']:,.1f}"
        lat = res["latency_summary"]
        mean_lat = f"{lat['mean_us']:.2f}"
        p95_lat = f"{lat['p95_us']:.2f}"
        p99_lat = f"{lat['p99_us']:.2f}"
        sub_ms = "YES" if lat["sub_millisecond_verified"] else "NO"
        lines.append(
            f"{sc_name:<22} | {orders:>8} | {tp:>18} | {mean_lat:>10} | {p95_lat:>9} | {p99_lat:>9} | {sub_ms:>5}"
        )

    lines.extend([
        "-" * 82,
        "",
        "Detailed Latency Metrics (Microseconds):",
        "-" * 82,
        f"{'Scenario':<22} | {'Min (µs)':>9} | {'Mean (µs)':>9} | {'P95 (µs)':>9} | {'P99 (µs)':>9} | {'Max (µs)':>10}",
        "-" * 82,
    ])

    for res in results:
        sc_name = res["scenario"]
        lat = res["latency_summary"]
        lines.append(
            f"{sc_name:<22} | {lat['min_us']:>9.2f} | {lat['mean_us']:>9.2f} | {lat['p95_us']:>9.2f} | {lat['p99_us']:>9.2f} | {lat['max_us']:>10.2f}"
        )

    lines.append("-" * 82)

    if comparison:
        eng = comparison["engine_only"]
        pipe = comparison["full_pipeline"]
        lines.extend([
            "",
            "=" * 82,
            "Latency Isolation: Matching Engine vs. Full End-to-End Pipeline:",
            "=" * 82,
            f"  Orders Tested                : {comparison['orders_tested']:,} orders",
            f"  Pure Matching Engine Latency : {eng['avg_latency_per_order_us']:.2f} µs/order  ({eng['throughput_ord_sec']:,.0f} orders/sec)",
            f"  End-to-End Pipeline Latency  : {pipe['avg_latency_per_order_us']:.2f} µs/order  ({pipe['throughput_ord_sec']:,.0f} orders/sec)",
            f"  Matching Share of Pipeline   : {comparison['engine_latency_ratio_pct']:.1f}%",
            f"  Note: Pipeline includes Generator + Binary Packing + Mmap IPC Ring Buffer + Adapter.",
            "=" * 82,
        ])

    return "\n".join(lines)


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ChronosMatch Cython Matching Engine Performance Benchmark (Day 9)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-n", "--orders", type=int, default=10_000, help="Orders per benchmark scenario")
    parser.add_argument("-r", "--repeats", type=int, default=3, help="Measured repetitions per scenario")
    parser.add_argument("-w", "--warmup", type=int, default=1, help="Warmup iterations")
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=["all", "crossing", "multilevel", "passive", "balanced"],
        help="Scenario to benchmark",
    )
    parser.add_argument("--compare-pipeline", action="store_true", help="Include pipeline vs engine latency comparison")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    runner = MatchingEngineBenchmarkRunner(record_individual_latencies=True)
    results = []

    order_n = args.orders

    if args.scenario in ("all", "crossing"):
        orders = generate_crossing_orders(order_n // 2)
        res = runner.run_scenario("Crossing (Fills)", orders, repeats=args.repeats, warmup=args.warmup)
        results.append(res)

    if args.scenario in ("all", "multilevel"):
        orders = generate_multilevel_sweep_workload(order_n // 6, levels_per_sweep=5)
        res = runner.run_scenario("Multi-Level Sweeps", orders, repeats=args.repeats, warmup=args.warmup)
        results.append(res)

    if args.scenario in ("all", "passive"):
        orders = generate_passive_orders(order_n)
        res = runner.run_scenario("Passive Book Depth", orders, repeats=args.repeats, warmup=args.warmup)
        results.append(res)

    if args.scenario in ("all", "balanced"):
        orders = generate_balanced_market_workload(order_n)
        res = runner.run_scenario("Balanced Continuous", orders, repeats=args.repeats, warmup=args.warmup)
        results.append(res)

    comparison = None
    if args.compare_pipeline:
        comparison = run_pipeline_vs_engine_comparison(order_count=min(order_n, 10_000))

    if args.json:
        output_data = {"scenarios": results}
        if comparison:
            output_data["pipeline_comparison"] = comparison
        print(json.dumps(output_data, indent=2))
    else:
        print(format_engine_benchmark_report(results, comparison))


if __name__ == "__main__":
    main()
