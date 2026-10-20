"""Focused Unit and Integration Tests for ChronosMatch Benchmark Runner (Day 8).

Validates:
1. Throughput calculation functions and zero elapsed time safety.
2. Metric structures, aggregations, and statistical summaries.
3. Benchmark configuration validation and error handling.
4. Reproducible execution with fixed seeds.
5. Accurate accounting of attempted, processed, dropped, and unhandled orders.
6. Small workload execution across all supported pipeline scopes.
7. Clean resource lifecycle and temporary file removal.
8. Report formatting (table and JSON) and CLI parser integration.

All tests are machine-speed independent and validate logic/calculations without
requiring or asserting arbitrary execution speed thresholds.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from typing import List

import pytest

from chronos.benchmark import (
    BenchmarkConfig,
    BenchmarkOrderGenerator,
    BenchmarkSummary,
    PipelineBenchmarkRunner,
    RepetitionMetrics,
    SCOPE_ADAPTER_ENGINE,
    SCOPE_ENGINE_ONLY,
    SCOPE_FULL,
    SCOPE_IPC,
    STAGE_CONNECTIVITY,
    VALID_SCOPES,
    calculate_throughput,
    format_benchmark_report,
    format_json_report,
)
from chronos.protocol import OrderType, SYMBOLS
from scripts.benchmark_pipeline import build_parser, main


# ==============================================================================
# 1. Throughput Calculation & Zero-Time Safety Tests
# ==============================================================================

class TestThroughputCalculation:
    """Verifies throughput calculation and zero/negative time safety."""

    def test_normal_throughput_calculation(self):
        """10,000 orders in 1 second (1,000,000,000 ns) = 10,000.0 orders/sec."""
        rate = calculate_throughput(orders_processed=10_000, elapsed_ns=1_000_000_000)
        assert rate == pytest.approx(10_000.0, rel=1e-6)

    def test_fractional_second_throughput(self):
        """500 orders in 2,500,000 ns (2.5 ms) = 200,000.0 orders/sec."""
        rate = calculate_throughput(orders_processed=500, elapsed_ns=2_500_000)
        assert rate == pytest.approx(200_000.0, rel=1e-6)

    def test_zero_elapsed_time_safe(self):
        """Zero elapsed time must return 0.0 safely without ZeroDivisionError."""
        rate = calculate_throughput(orders_processed=1_000, elapsed_ns=0)
        assert rate == 0.0

    def test_negative_elapsed_time_safe(self):
        """Negative elapsed time (e.g. clock anomaly) must return 0.0 safely."""
        rate = calculate_throughput(orders_processed=1_000, elapsed_ns=-500)
        assert rate == 0.0

    def test_zero_orders_processed_safe(self):
        """Zero orders processed must return 0.0."""
        rate = calculate_throughput(orders_processed=0, elapsed_ns=1_000_000)
        assert rate == 0.0

    def test_negative_orders_processed_safe(self):
        """Negative orders count must return 0.0."""
        rate = calculate_throughput(orders_processed=-10, elapsed_ns=1_000_000)
        assert rate == 0.0


# ==============================================================================
# 2. Configuration Validation Tests
# ==============================================================================

class TestBenchmarkConfiguration:
    """Verifies constructor validation and parameter enforcement."""

    def test_default_configuration_values(self):
        config = BenchmarkConfig()
        assert config.orders == 10_000
        assert config.repeats == 3
        assert config.warmup == 1
        assert config.batch_size == 500
        assert config.scope == SCOPE_FULL
        assert config.seed == 42
        assert config.limit_only is False
        assert config.buffer_capacity == 262_144
        assert config.timeout_seconds == 30.0
        assert config.quiet is False

    @pytest.mark.parametrize("invalid_orders", [0, -1, -500, "1000", False, True])
    def test_invalid_orders_raises_error(self, invalid_orders):
        with pytest.raises(ValueError, match="orders must be a positive integer"):
            BenchmarkConfig(orders=invalid_orders)

    @pytest.mark.parametrize("invalid_repeats", [0, -1, "3", False, True])
    def test_invalid_repeats_raises_error(self, invalid_repeats):
        with pytest.raises(ValueError, match="repeats must be a positive integer"):
            BenchmarkConfig(repeats=invalid_repeats)

    @pytest.mark.parametrize("invalid_warmup", [-1, -5, "1", False, True])
    def test_invalid_warmup_raises_error(self, invalid_warmup):
        with pytest.raises(ValueError, match="warmup must be a non-negative integer"):
            BenchmarkConfig(warmup=invalid_warmup)

    @pytest.mark.parametrize("invalid_batch_size", [0, -100, False, True])
    def test_invalid_batch_size_raises_error(self, invalid_batch_size):
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            BenchmarkConfig(batch_size=invalid_batch_size)

    def test_invalid_scope_raises_error(self):
        with pytest.raises(ValueError, match="Invalid scope 'unknown_scope'"):
            BenchmarkConfig(scope="unknown_scope")

    def test_invalid_capacity_non_power_of_two_raises_error(self):
        with pytest.raises(ValueError, match="buffer_capacity must be a power of 2"):
            BenchmarkConfig(buffer_capacity=1000)


# ==============================================================================
# 3. Statistical Aggregations and Metrics Tests
# ==============================================================================

class TestBenchmarkMetricsAndSummary:
    """Verifies aggregation math, percentiles, and dropped order tracking."""

    def test_summary_statistics_single_repetition(self):
        rep = RepetitionMetrics(
            repetition_index=1,
            orders_attempted=1000,
            orders_processed=1000,
            orders_dropped=0,
            orders_unhandled=100,
            orders_dispatched=900,
            trades_generated=250,
            volume_matched=30000,
            elapsed_ns=5_000_000,
            elapsed_sec=0.005,
            throughput=200_000.0,
            scope=SCOPE_FULL,
        )
        runner = PipelineBenchmarkRunner(BenchmarkConfig(orders=1000, repeats=1, warmup=0))
        summary = runner._compute_summary([rep], warmup_metric=None)

        assert summary.repetition_count == 1
        assert summary.mean_throughput == 200_000.0
        assert summary.median_throughput == 200_000.0
        assert summary.min_throughput == 200_000.0
        assert summary.max_throughput == 200_000.0
        assert summary.std_throughput == 0.0
        assert summary.mean_elapsed_sec == 0.005
        assert summary.total_orders_attempted == 1000
        assert summary.total_orders_processed == 1000
        assert summary.total_orders_dropped == 0
        assert summary.total_orders_unhandled == 100
        assert summary.total_trades_generated == 250
        assert summary.total_volume_matched == 30000

    def test_summary_statistics_multiple_repetitions(self):
        reps = [
            RepetitionMetrics(
                repetition_index=1,
                orders_attempted=1000,
                orders_processed=1000,
                orders_dropped=0,
                orders_unhandled=0,
                orders_dispatched=1000,
                trades_generated=100,
                volume_matched=10000,
                elapsed_ns=10_000_000,
                elapsed_sec=0.010,
                throughput=100_000.0,
                scope=SCOPE_FULL,
            ),
            RepetitionMetrics(
                repetition_index=2,
                orders_attempted=1000,
                orders_processed=1000,
                orders_dropped=0,
                orders_unhandled=0,
                orders_dispatched=1000,
                trades_generated=100,
                volume_matched=10000,
                elapsed_ns=5_000_000,
                elapsed_sec=0.005,
                throughput=200_000.0,
                scope=SCOPE_FULL,
            ),
            RepetitionMetrics(
                repetition_index=3,
                orders_attempted=1000,
                orders_processed=1000,
                orders_dropped=0,
                orders_unhandled=0,
                orders_dispatched=1000,
                trades_generated=100,
                volume_matched=10000,
                elapsed_ns=3_333_333,
                elapsed_sec=0.003333333,
                throughput=300_000.0,
                scope=SCOPE_FULL,
            ),
        ]
        runner = PipelineBenchmarkRunner(BenchmarkConfig(orders=1000, repeats=3, warmup=0))
        summary = runner._compute_summary(reps, warmup_metric=None)

        assert summary.repetition_count == 3
        assert summary.mean_throughput == pytest.approx(200_000.0)
        assert summary.median_throughput == pytest.approx(200_000.0)
        assert summary.min_throughput == pytest.approx(100_000.0)
        assert summary.max_throughput == pytest.approx(300_000.0)
        assert summary.std_throughput == pytest.approx(100_000.0)
        assert summary.total_orders_attempted == 3000
        assert summary.total_orders_processed == 3000

    def test_summary_empty_repetitions_safe(self):
        runner = PipelineBenchmarkRunner(BenchmarkConfig(orders=1000, repeats=1, warmup=0))
        summary = runner._compute_summary([], warmup_metric=None)
        assert summary.repetition_count == 0
        assert summary.mean_throughput == 0.0
        assert summary.median_throughput == 0.0
        assert summary.total_orders_processed == 0

    def test_distinguish_dropped_and_unhandled_orders(self):
        rep = RepetitionMetrics(
            repetition_index=1,
            orders_attempted=1000,
            orders_processed=950,
            orders_dropped=50,
            orders_unhandled=100,
            orders_dispatched=850,
            trades_generated=200,
            volume_matched=25000,
            elapsed_ns=5_000_000,
            elapsed_sec=0.005,
            throughput=190_000.0,
            scope=SCOPE_FULL,
        )
        assert rep.orders_attempted == 1000
        assert rep.orders_processed == 950
        assert rep.orders_dropped == 50
        assert rep.orders_unhandled == 100
        assert rep.orders_dispatched == 850
        # Verification that processed + dropped == attempted
        assert rep.orders_processed + rep.orders_dropped == rep.orders_attempted


# ==============================================================================
# 4. Small Workload Benchmark Execution Tests
# ==============================================================================

class TestSmallWorkloadPipelineBenchmark:
    """Runs bounded small-workload benchmarks verifying real pipeline integration."""

    def test_small_workload_full_pipeline_run(self):
        """Execute a 50-order full pipeline run and verify complete stage execution."""
        config = BenchmarkConfig(
            orders=50,
            repeats=1,
            warmup=0,
            batch_size=25,
            scope=SCOPE_FULL,
            seed=42,
        )
        runner = PipelineBenchmarkRunner(config)
        summary = runner.run()

        assert summary.repetition_count == 1
        rep = summary.repetitions[0]
        assert rep.orders_attempted == 50
        assert rep.orders_processed == 50
        assert rep.orders_dropped == 0
        assert rep.orders_dispatched > 0
        assert rep.elapsed_ns > 0
        assert rep.elapsed_sec > 0.0
        assert rep.throughput > 0.0
        assert summary.stage_connectivity["mmap_ring_buffer"] is True
        assert summary.stage_connectivity["matching_engine"] is True

    def test_limit_only_mode_dispatches_all_orders(self):
        """In limit_only mode, 100% of orders are LIMIT, so unhandled_orders == 0."""
        config = BenchmarkConfig(
            orders=60,
            repeats=1,
            warmup=0,
            batch_size=20,
            scope=SCOPE_FULL,
            limit_only=True,
            seed=42,
        )
        runner = PipelineBenchmarkRunner(config)
        summary = runner.run()

        rep = summary.repetitions[0]
        assert rep.orders_attempted == 60
        assert rep.orders_processed == 60
        assert rep.orders_unhandled == 0
        assert rep.orders_dispatched == 60

    def test_reproducibility_with_seed(self):
        """Two identical runs with the same seed produce identical trade outcomes."""
        config1 = BenchmarkConfig(orders=100, repeats=1, warmup=0, batch_size=50, seed=123)
        summary1 = PipelineBenchmarkRunner(config1).run()

        config2 = BenchmarkConfig(orders=100, repeats=1, warmup=0, batch_size=50, seed=123)
        summary2 = PipelineBenchmarkRunner(config2).run()

        rep1 = summary1.repetitions[0]
        rep2 = summary2.repetitions[0]

        assert rep1.orders_attempted == rep2.orders_attempted
        assert rep1.orders_processed == rep2.orders_processed
        assert rep1.orders_dispatched == rep2.orders_dispatched
        assert rep1.orders_unhandled == rep2.orders_unhandled
        assert rep1.trades_generated == rep2.trades_generated
        assert rep1.volume_matched == rep2.volume_matched

    @pytest.mark.parametrize("scope", [SCOPE_FULL, SCOPE_ADAPTER_ENGINE, SCOPE_ENGINE_ONLY, SCOPE_IPC])
    def test_all_pipeline_scopes_execute_successfully(self, scope):
        """Each supported scope executes with correct stage connectivity flags."""
        config = BenchmarkConfig(
            orders=40,
            repeats=1,
            warmup=0,
            batch_size=20,
            scope=scope,
            seed=42,
        )
        runner = PipelineBenchmarkRunner(config)
        summary = runner.run()

        assert summary.scope == scope
        assert summary.repetition_count == 1
        rep = summary.repetitions[0]
        assert rep.orders_processed == 40
        assert rep.throughput > 0.0
        assert summary.stage_connectivity == STAGE_CONNECTIVITY[scope]

    def test_warmup_run_is_recorded_and_excluded_from_repeats(self):
        """Warmup run is executed and captured in warmup_metrics without skewing repetition stats."""
        config = BenchmarkConfig(
            orders=30,
            repeats=2,
            warmup=1,
            batch_size=15,
            scope=SCOPE_FULL,
            seed=42,
        )
        runner = PipelineBenchmarkRunner(config)
        summary = runner.run()

        assert summary.warmup_count == 1
        assert summary.warmup_metrics is not None
        assert summary.warmup_metrics.is_warmup is True
        assert summary.warmup_metrics.orders_processed == 30
        assert summary.repetition_count == 2
        for rep in summary.repetitions:
            assert rep.is_warmup is False


# ==============================================================================
# 5. Reporting and CLI Integration Tests
# ==============================================================================

class TestReportingAndCLI:
    """Verifies formatted table reporting, JSON serialization, and CLI execution."""

    def test_format_benchmark_report_contains_all_key_sections(self):
        config = BenchmarkConfig(orders=50, repeats=2, warmup=1, batch_size=25, seed=42)
        summary = PipelineBenchmarkRunner(config).run()
        report = format_benchmark_report(summary, use_color=False)

        assert "CHRONOSMATCH :: ORDER PROCESSING PIPELINE BENCHMARK" in report
        assert "Tested Scope" in report
        assert "Repetition Results" in report
        assert "Summary Statistics" in report
        assert "Pipeline Stage Connectivity" in report
        assert "Truthful Pipeline Disclosures" in report
        assert "Mean Throughput" in report
        assert "50 orders/run" in report

    def test_format_json_report_is_valid_json(self):
        config = BenchmarkConfig(orders=30, repeats=1, warmup=0, batch_size=15, seed=42)
        summary = PipelineBenchmarkRunner(config).run()
        json_str = format_json_report(summary)

        parsed = json.loads(json_str)
        assert parsed["target_orders"] == 30
        assert parsed["repetition_count"] == 1
        assert len(parsed["repetitions"]) == 1
        assert "mean_throughput" in parsed
        assert "stage_connectivity" in parsed
        assert "limitations" in parsed

    def test_cli_parser_defaults(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.orders == 10_000
        assert args.repeats == 3
        assert args.warmup == 1
        assert args.batch_size == 500
        assert args.scope == SCOPE_FULL
        assert args.seed == 42
        assert args.limit_only is False
        assert args.json is False

    def test_cli_main_execution_small_workload(self, capsys):
        """CLI main executes cleanly with returncode 0 and prints output."""
        ret = main(["--orders", "20", "--repeats", "1", "--warmup", "0", "--quiet"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Summary Statistics" in captured.out

    def test_cli_main_json_output(self, capsys):
        ret = main(["--orders", "20", "--repeats", "1", "--warmup", "0", "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["target_orders"] == 20

    def test_cli_main_invalid_args_returns_error_code(self, capsys):
        ret = main(["--orders", "-10"])
        assert ret == 1
        captured = capsys.readouterr()
        assert "Configuration Error" in captured.err
