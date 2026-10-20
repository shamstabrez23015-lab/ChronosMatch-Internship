#!/usr/bin/env python3
"""ChronosMatch Reproducible Order-Processing Pipeline Benchmark Runner (Day 8).

Runs configurable, multi-stage performance benchmarks for the ChronosMatch
trading engine and order-processing pipeline:
  1. Generator: FastOrderGenerator / deterministic synthetic market feed
  2. Binary Protocol: 32-byte cache-aligned order tick serialization
  3. IPC Ring Buffer: Lock-free SPSC shared memory-mapped ring buffer
  4. Consumer / Adapter: ZeroCopyConsumer & OrderAdapter translation
  5. Matching Engine: Cython Limit Order Book Price-Time Priority matching

Example Usage:
  python scripts/benchmark_pipeline.py --orders 10000 --repeats 3
  python scripts/benchmark_pipeline.py --orders 50000 --repeats 5 --limit-only
  python scripts/benchmark_pipeline.py --scope adapter-engine --orders 20000
  python scripts/benchmark_pipeline.py --orders 10000 --json
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys

# Enable 1ms timer resolution on Windows if available
if sys.platform == "win32":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

# Ensure standard output handles UTF-8 / ANSI smoothly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chronos.benchmark import (
    BenchmarkConfig,
    BenchmarkSummary,
    PipelineBenchmarkRunner,
    SCOPE_ADAPTER_ENGINE,
    SCOPE_ENGINE_ONLY,
    SCOPE_FULL,
    SCOPE_IPC,
    VALID_SCOPES,
    format_benchmark_report,
    format_json_report,
)


def build_parser() -> argparse.ArgumentParser:
    """Build and return command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="ChronosMatch Order-Processing Pipeline Benchmark Runner (Day 8)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-n",
        "--orders",
        type=int,
        default=10_000,
        help="Number of orders to process per benchmark repetition",
    )
    parser.add_argument(
        "-r",
        "--repeats",
        type=int,
        default=3,
        help="Number of benchmark repetitions to execute",
    )
    parser.add_argument(
        "-w",
        "--warmup",
        type=int,
        default=1,
        help="Number of warmup runs before recording metrics",
    )
    parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=500,
        help="Number of orders per burst batch through ring buffer",
    )
    parser.add_argument(
        "-s",
        "--scope",
        type=str,
        default=SCOPE_FULL,
        choices=VALID_SCOPES,
        help="Pipeline stages to include in the benchmark",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible order generation (use -1 for unseeded)",
    )
    parser.add_argument(
        "--limit-only",
        action="store_true",
        help="Force 100%% LIMIT orders (all orders dispatched to MatchingEngine)",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=262_144,
        help="Backing ring buffer slot capacity (must be power of 2)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Maximum timeout in seconds per benchmark repetition",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON summary results instead of formatted table",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors in terminal report output",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational header lines during run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the pipeline benchmark runner."""
    parser = build_parser()
    args = parser.parse_args(argv)

    seed_val = None if args.seed == -1 else args.seed

    try:
        config = BenchmarkConfig(
            orders=args.orders,
            repeats=args.repeats,
            warmup=args.warmup,
            batch_size=args.batch_size,
            scope=args.scope,
            seed=seed_val,
            limit_only=args.limit_only,
            buffer_capacity=args.capacity,
            timeout_seconds=args.timeout,
            quiet=args.quiet,
        )
    except ValueError as exc:
        sys.stderr.write(f"Configuration Error: {exc}\n")
        return 1

    if not args.quiet and not args.json:
        sys.stdout.write(f"[+] Starting ChronosMatch Pipeline Benchmark ({config.orders:,} orders x {config.repeats} runs)...\n")
        sys.stdout.flush()

    runner = PipelineBenchmarkRunner(config)
    summary: BenchmarkSummary = runner.run()

    if args.json:
        sys.stdout.write(format_json_report(summary) + "\n")
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        sys.stdout.write(format_benchmark_report(summary, use_color=use_color) + "\n")
    sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
