"""ChronosMatch Benchmark Pipeline Runner and Metrics Engine.

Provides a reproducible, multi-stage performance benchmark for the actual
ChronosMatch order-processing pipeline:
  1. Order Generation (FastOrderGenerator / deterministic synthetic feed)
  2. Binary Protocol Serialization (32-byte cache-aligned struct)
  3. Shared Memory-Mapped IPC Ring Buffer (MmapRingBuffer lock-free SPSC)
  4. Zero-Copy Consumer Ring Buffer Ingestion (ZeroCopyConsumer)
  5. Protocol-to-Engine Order Adapter (OrderAdapter)
  6. Cython Limit Order Book Matching Engine (MatchingEngine)

Measures throughput (orders/sec), execution latency, trade generation,
and fill volume across configurable repetitions using time.perf_counter_ns().
Safely handles zero elapsed time and truthfully distinguishes processed,
dropped, and unhandled orders.
"""

from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass, field
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union

if sys.platform == "win32":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

from chronos.adapter import AdapterStats, OrderAdapter
from chronos.consumer import ConsumerStats, ZeroCopyConsumer
from chronos.firehose import (
    BASE_PRICES,
    FastOrderGenerator,
    ID_TO_BASE_PRICE,
    SYMBOL_IDS,
    SYMBOL_WEIGHTS,
)
from chronos.matching_engine import MatchingEngine, TradeResult
from chronos.protocol import (
    ORDER_SIZE,
    Order,
    OrderType,
    Side,
    SYMBOLS,
    SYMBOL_ID_TO_TICKER,
)
from chronos.ring_buffer import MmapRingBuffer

# ==============================================================================
# Pipeline Scope Constants
# ==============================================================================

SCOPE_FULL = "full"
SCOPE_ADAPTER_ENGINE = "adapter-engine"
SCOPE_ENGINE_ONLY = "engine-only"
SCOPE_IPC = "ipc"

VALID_SCOPES = (SCOPE_FULL, SCOPE_ADAPTER_ENGINE, SCOPE_ENGINE_ONLY, SCOPE_IPC)

SCOPE_DESCRIPTIONS = {
    SCOPE_FULL: "Full Pipeline (Generator -> Protocol -> MmapRingBuffer -> OrderAdapter -> MatchingEngine)",
    SCOPE_ADAPTER_ENGINE: "Adapter & Engine (Direct Protocol Orders -> OrderAdapter -> MatchingEngine)",
    SCOPE_ENGINE_ONLY: "Matching Engine Only (Direct MatchingEngine.match_order calls)",
    SCOPE_IPC: "Zero-Copy IPC (Generator -> MmapRingBuffer -> ZeroCopyConsumer)",
}

STAGE_CONNECTIVITY = {
    SCOPE_FULL: {
        "generator": True,
        "binary_protocol": True,
        "mmap_ring_buffer": True,
        "consumer_ingest": True,
        "order_adapter": True,
        "matching_engine": True,
    },
    SCOPE_ADAPTER_ENGINE: {
        "generator": True,
        "binary_protocol": True,
        "mmap_ring_buffer": False,
        "consumer_ingest": False,
        "order_adapter": True,
        "matching_engine": True,
    },
    SCOPE_ENGINE_ONLY: {
        "generator": True,
        "binary_protocol": False,
        "mmap_ring_buffer": False,
        "consumer_ingest": False,
        "order_adapter": False,
        "matching_engine": True,
    },
    SCOPE_IPC: {
        "generator": True,
        "binary_protocol": True,
        "mmap_ring_buffer": True,
        "consumer_ingest": True,
        "order_adapter": False,
        "matching_engine": False,
    },
}

PIPELINE_LIMITATIONS = [
    "Cython MatchingEngine natively supports LIMIT orders with Price-Time Priority.",
    "Non-LIMIT order types (MARKET, CANCEL) are intercepted and tracked as unhandled by OrderAdapter.",
    "Multi-symbol routing connects 8 independent MatchingEngine limit order books (one per ticker symbol).",
]


# ==============================================================================
# Throughput Calculation (Zero Elapsed Time Safety)
# ==============================================================================

def calculate_throughput(orders_processed: int, elapsed_ns: int) -> float:
    """Calculate throughput in orders/second safely.

    Handles zero or negative elapsed time without ZeroDivisionError.
    If elapsed_ns <= 0 or orders_processed <= 0, returns 0.0.

    Args:
        orders_processed: Number of orders successfully processed.
        elapsed_ns: Elapsed time in nanoseconds measured by time.perf_counter_ns().

    Returns:
        Orders per second as a float.
    """
    if elapsed_ns <= 0 or orders_processed <= 0:
        return 0.0
    elapsed_sec = elapsed_ns / 1_000_000_000.0
    return orders_processed / elapsed_sec


# ==============================================================================
# Configuration Dataclass
# ==============================================================================

@dataclass
class BenchmarkConfig:
    """Configuration options for the ChronosMatch Benchmark Runner."""

    orders: int = 10_000
    repeats: int = 3
    warmup: int = 1
    batch_size: int = 500
    scope: str = SCOPE_FULL
    seed: Optional[int] = 42
    limit_only: bool = False
    buffer_capacity: int = 262_144
    timeout_seconds: float = 30.0
    quiet: bool = False

    def __post_init__(self) -> None:
        """Validate benchmark parameters."""
        if isinstance(self.orders, bool) or not isinstance(self.orders, int) or self.orders <= 0:
            raise ValueError(f"orders must be a positive integer, got {self.orders!r}")
        if isinstance(self.repeats, bool) or not isinstance(self.repeats, int) or self.repeats <= 0:
            raise ValueError(f"repeats must be a positive integer, got {self.repeats!r}")
        if isinstance(self.warmup, bool) or not isinstance(self.warmup, int) or self.warmup < 0:
            raise ValueError(f"warmup must be a non-negative integer, got {self.warmup!r}")
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int) or self.batch_size <= 0:
            raise ValueError(f"batch_size must be a positive integer, got {self.batch_size!r}")
        if self.scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope '{self.scope}'. Must be one of {VALID_SCOPES}")
        if isinstance(self.buffer_capacity, bool) or not isinstance(self.buffer_capacity, int) or self.buffer_capacity <= 0:
            raise ValueError(f"buffer_capacity must be a positive integer, got {self.buffer_capacity!r}")
        if (self.buffer_capacity & (self.buffer_capacity - 1)) != 0:
            raise ValueError(f"buffer_capacity must be a power of 2, got {self.buffer_capacity}")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive, got {self.timeout_seconds}")


# ==============================================================================
# Metric Results Dataclasses
# ==============================================================================

@dataclass
class RepetitionMetrics:
    """Detailed operational metrics for a single benchmark repetition."""

    repetition_index: int
    orders_attempted: int
    orders_processed: int
    orders_dropped: int
    orders_unhandled: int
    orders_dispatched: int
    trades_generated: int
    volume_matched: int
    elapsed_ns: int
    elapsed_sec: float
    throughput: float
    scope: str
    is_warmup: bool = False


@dataclass
class BenchmarkSummary:
    """Aggregated results across all benchmark repetitions."""

    scope: str
    scope_description: str
    target_orders: int
    batch_size: int
    repetition_count: int
    warmup_count: int
    limit_only: bool
    seed: Optional[int]
    repetitions: List[RepetitionMetrics]
    warmup_metrics: Optional[RepetitionMetrics]
    mean_throughput: float
    median_throughput: float
    min_throughput: float
    max_throughput: float
    std_throughput: float
    mean_elapsed_sec: float
    min_elapsed_sec: float
    max_elapsed_sec: float
    total_orders_attempted: int
    total_orders_processed: int
    total_orders_dropped: int
    total_orders_unhandled: int
    total_trades_generated: int
    total_volume_matched: int
    stage_connectivity: Dict[str, bool]
    limitations: List[str]


# ==============================================================================
# Benchmark Order Generator (Reproducible with Seed and Limit-Only Support)
# ==============================================================================

class BenchmarkOrderGenerator(FastOrderGenerator):
    """Reproducible fast mock order generator for benchmark runs.

    Supports seed initialization for deterministic multi-run repeatability
    and limit_only mode to target 100% LIMIT orders.
    """

    def __init__(
        self,
        initial_order_id: int = 1,
        seed: Optional[int] = None,
        limit_only: bool = False,
    ):
        if seed is not None:
            random.seed(seed)
        super().__init__(initial_order_id=initial_order_id)
        if limit_only:
            # Override pool entries to be 100% LIMIT orders
            new_pool = []
            for price, qty, sym_id, side, _ in self._pool:
                new_pool.append((price, qty, sym_id, side, int(OrderType.LIMIT)))
            self._pool = new_pool


# ==============================================================================
# Benchmark Runner
# ==============================================================================

class PipelineBenchmarkRunner:
    """Executes configurable, reproducible benchmarks of the ChronosMatch pipeline."""

    def __init__(self, config: Optional[BenchmarkConfig] = None):
        self.config = config or BenchmarkConfig()

    def run(self) -> BenchmarkSummary:
        """Execute the configured benchmark suite.

        Performs:
        1. Warmup run (if warmup > 0) to prime JIT/caches without polluting stats.
        2. Configured repetition runs, recording high-resolution monotonic timestamps.
        3. Statistical aggregation across repetitions.
        """
        warmup_metric: Optional[RepetitionMetrics] = None
        if self.config.warmup > 0:
            warmup_metric = self._run_single_repetition(
                repetition_index=0,
                is_warmup=True,
            )

        repetitions: List[RepetitionMetrics] = []
        for rep in range(1, self.config.repeats + 1):
            metric = self._run_single_repetition(
                repetition_index=rep,
                is_warmup=False,
            )
            repetitions.append(metric)

        return self._compute_summary(repetitions, warmup_metric)

    def _run_single_repetition(
        self, repetition_index: int, is_warmup: bool
    ) -> RepetitionMetrics:
        """Dispatch a single repetition based on the configured scope."""
        scope = self.config.scope
        if scope == SCOPE_FULL:
            return self._run_full_pipeline(repetition_index, is_warmup)
        elif scope == SCOPE_ADAPTER_ENGINE:
            return self._run_adapter_engine(repetition_index, is_warmup)
        elif scope == SCOPE_ENGINE_ONLY:
            return self._run_engine_only(repetition_index, is_warmup)
        elif scope == SCOPE_IPC:
            return self._run_ipc_only(repetition_index, is_warmup)
        else:
            raise ValueError(f"Unsupported scope: {scope}")

    def _run_full_pipeline(
        self, repetition_index: int, is_warmup: bool
    ) -> RepetitionMetrics:
        """Run the full end-to-end pipeline.

        Stages: Generator -> Binary Protocol -> MmapRingBuffer -> OrderAdapter -> MatchingEngine.
        """
        target_orders = self.config.orders
        batch_size = self.config.batch_size
        seed = None if self.config.seed is None else self.config.seed + repetition_index

        # Create temporary ring buffer file with safe cleanup
        fd, tmp_path = tempfile.mkstemp(prefix="chronos_bench_ring_", suffix=".bin")
        os.close(fd)

        buffer_capacity = max(
            self.config.buffer_capacity,
            1 << math.ceil(math.log2(max(batch_size * 4, 256))),
        )
        ring_buffer = MmapRingBuffer(
            filepath=tmp_path,
            capacity=buffer_capacity,
            slot_size=ORDER_SIZE,
            create=True,
        )

        try:
            # Setup symbol engines and adapter
            symbol_engines = {sym_id: MatchingEngine() for sym_id in SYMBOLS.values()}
            adapter = OrderAdapter(
                ring_buffer=ring_buffer,
                symbol_engines=symbol_engines,
                dispatch_mode="match",
            )
            generator = BenchmarkOrderGenerator(
                initial_order_id=1,
                seed=seed,
                limit_only=self.config.limit_only,
            )

            # High-resolution monotonic timing
            t_start = time.perf_counter_ns()

            written = 0
            while written < target_orders:
                batch_count = min(batch_size, target_orders - written)
                batch = generator.generate_batch(batch_count)
                ring_buffer.write_batch(batch, overwrite_on_full=True)
                written += len(batch)
                adapter.drain_all()

            # Ensure any leftover unread slots are drained
            if ring_buffer.available_to_read() > 0:
                adapter.drain_all()

            t_end = time.perf_counter_ns()
            elapsed_ns = max(0, t_end - t_start)
            elapsed_sec = elapsed_ns / 1_000_000_000.0

            orders_processed = adapter.stats.total_orders_read
            orders_dropped = ring_buffer.messages_dropped
            orders_unhandled = adapter.stats.unhandled_order_types
            orders_dispatched = adapter.stats.total_orders_dispatched
            trades_generated = adapter.stats.total_trades_generated
            volume_matched = adapter.stats.total_volume_matched
            throughput = calculate_throughput(orders_processed, elapsed_ns)

            return RepetitionMetrics(
                repetition_index=repetition_index,
                orders_attempted=target_orders,
                orders_processed=orders_processed,
                orders_dropped=orders_dropped,
                orders_unhandled=orders_unhandled,
                orders_dispatched=orders_dispatched,
                trades_generated=trades_generated,
                volume_matched=volume_matched,
                elapsed_ns=elapsed_ns,
                elapsed_sec=elapsed_sec,
                throughput=throughput,
                scope=SCOPE_FULL,
                is_warmup=is_warmup,
            )

        finally:
            ring_buffer.close()
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _run_adapter_engine(
        self, repetition_index: int, is_warmup: bool
    ) -> RepetitionMetrics:
        """Run Adapter & Engine directly (bypassing ring buffer IPC)."""
        target_orders = self.config.orders
        batch_size = self.config.batch_size
        seed = None if self.config.seed is None else self.config.seed + repetition_index

        generator = BenchmarkOrderGenerator(
            initial_order_id=1,
            seed=seed,
            limit_only=self.config.limit_only,
        )
        symbol_engines = {sym_id: MatchingEngine() for sym_id in SYMBOLS.values()}
        adapter = OrderAdapter(
            ring_buffer=None,
            symbol_engines=symbol_engines,
            dispatch_mode="match",
        )

        t_start = time.perf_counter_ns()
        processed = 0
        while processed < target_orders:
            batch_count = min(batch_size, target_orders - processed)
            batch = generator.generate_batch(batch_count)
            for raw_order in batch:
                adapter.dispatch_raw_order(raw_order)
            processed += len(batch)
        t_end = time.perf_counter_ns()

        elapsed_ns = max(0, t_end - t_start)
        elapsed_sec = elapsed_ns / 1_000_000_000.0

        orders_processed = processed
        orders_dropped = 0
        orders_unhandled = adapter.stats.unhandled_order_types
        orders_dispatched = adapter.stats.total_orders_dispatched
        trades_generated = adapter.stats.total_trades_generated
        volume_matched = adapter.stats.total_volume_matched
        throughput = calculate_throughput(orders_processed, elapsed_ns)

        return RepetitionMetrics(
            repetition_index=repetition_index,
            orders_attempted=target_orders,
            orders_processed=orders_processed,
            orders_dropped=orders_dropped,
            orders_unhandled=orders_unhandled,
            orders_dispatched=orders_dispatched,
            trades_generated=trades_generated,
            volume_matched=volume_matched,
            elapsed_ns=elapsed_ns,
            elapsed_sec=elapsed_sec,
            throughput=throughput,
            scope=SCOPE_ADAPTER_ENGINE,
            is_warmup=is_warmup,
        )

    def _run_engine_only(
        self, repetition_index: int, is_warmup: bool
    ) -> RepetitionMetrics:
        """Run pure MatchingEngine match_order calls directly."""
        target_orders = self.config.orders
        batch_size = self.config.batch_size
        seed = None if self.config.seed is None else self.config.seed + repetition_index

        generator = BenchmarkOrderGenerator(
            initial_order_id=1,
            seed=seed,
            limit_only=True,  # Engine only supports LIMIT orders
        )
        symbol_engines = {sym_id: MatchingEngine() for sym_id in SYMBOLS.values()}

        # Pre-generate orders to measure pure matching execution
        all_orders: List[Tuple[int, int, float, int, int, int, int]] = []
        while len(all_orders) < target_orders:
            batch_count = min(batch_size, target_orders - len(all_orders))
            all_orders.extend(generator.generate_batch(batch_count))

        trades_count = 0
        volume_count = 0

        t_start = time.perf_counter_ns()
        for ord_tup in all_orders:
            order_id = ord_tup[0]
            timestamp_ns = ord_tup[1]
            price = ord_tup[2]
            quantity = ord_tup[3]
            symbol_id = ord_tup[4]
            side = ord_tup[5]
            eng = symbol_engines.get(symbol_id)
            if eng is not None:
                trades = eng.match_order(
                    order_id=order_id,
                    side=side,
                    price=price,
                    quantity=quantity,
                    timestamp_ns=timestamp_ns,
                )
                trades_count += len(trades)
                volume_count += sum(t.executed_quantity for t in trades)
        t_end = time.perf_counter_ns()

        elapsed_ns = max(0, t_end - t_start)
        elapsed_sec = elapsed_ns / 1_000_000_000.0
        orders_processed = len(all_orders)
        throughput = calculate_throughput(orders_processed, elapsed_ns)

        return RepetitionMetrics(
            repetition_index=repetition_index,
            orders_attempted=target_orders,
            orders_processed=orders_processed,
            orders_dropped=0,
            orders_unhandled=0,
            orders_dispatched=orders_processed,
            trades_generated=trades_count,
            volume_matched=volume_count,
            elapsed_ns=elapsed_ns,
            elapsed_sec=elapsed_sec,
            throughput=throughput,
            scope=SCOPE_ENGINE_ONLY,
            is_warmup=is_warmup,
        )

    def _run_ipc_only(
        self, repetition_index: int, is_warmup: bool
    ) -> RepetitionMetrics:
        """Run pure zero-copy ring buffer IPC without matching engine dispatch."""
        target_orders = self.config.orders
        batch_size = self.config.batch_size
        seed = None if self.config.seed is None else self.config.seed + repetition_index

        fd, tmp_path = tempfile.mkstemp(prefix="chronos_ipc_bench_", suffix=".bin")
        os.close(fd)

        buffer_capacity = max(
            self.config.buffer_capacity,
            1 << math.ceil(math.log2(max(batch_size * 4, 256))),
        )
        ring_buffer = MmapRingBuffer(
            filepath=tmp_path,
            capacity=buffer_capacity,
            slot_size=ORDER_SIZE,
            create=True,
        )

        try:
            generator = BenchmarkOrderGenerator(
                initial_order_id=1,
                seed=seed,
                limit_only=self.config.limit_only,
            )

            read_count = 0
            t_start = time.perf_counter_ns()
            written = 0
            while written < target_orders:
                batch_count = min(batch_size, target_orders - written)
                batch = generator.generate_batch(batch_count)
                ring_buffer.write_batch(batch, overwrite_on_full=True)
                written += len(batch)

                # Drain raw batch from ring buffer
                drained = ring_buffer.read_batch_raw(batch_size)
                read_count += len(drained)

            # Drain any remaining slots
            while ring_buffer.available_to_read() > 0:
                drained = ring_buffer.read_batch_raw(batch_size)
                read_count += len(drained)

            t_end = time.perf_counter_ns()
            elapsed_ns = max(0, t_end - t_start)
            elapsed_sec = elapsed_ns / 1_000_000_000.0

            orders_processed = read_count
            orders_dropped = ring_buffer.messages_dropped
            throughput = calculate_throughput(orders_processed, elapsed_ns)

            return RepetitionMetrics(
                repetition_index=repetition_index,
                orders_attempted=target_orders,
                orders_processed=orders_processed,
                orders_dropped=orders_dropped,
                orders_unhandled=0,
                orders_dispatched=0,
                trades_generated=0,
                volume_matched=0,
                elapsed_ns=elapsed_ns,
                elapsed_sec=elapsed_sec,
                throughput=throughput,
                scope=SCOPE_IPC,
                is_warmup=is_warmup,
            )
        finally:
            ring_buffer.close()
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _compute_summary(
        self,
        repetitions: List[RepetitionMetrics],
        warmup_metric: Optional[RepetitionMetrics],
    ) -> BenchmarkSummary:
        """Aggregate statistical metrics across repetitions."""
        if not repetitions:
            return BenchmarkSummary(
                scope=self.config.scope,
                scope_description=SCOPE_DESCRIPTIONS.get(self.config.scope, self.config.scope),
                target_orders=self.config.orders,
                batch_size=self.config.batch_size,
                repetition_count=0,
                warmup_count=self.config.warmup,
                limit_only=self.config.limit_only,
                seed=self.config.seed,
                repetitions=[],
                warmup_metrics=warmup_metric,
                mean_throughput=0.0,
                median_throughput=0.0,
                min_throughput=0.0,
                max_throughput=0.0,
                std_throughput=0.0,
                mean_elapsed_sec=0.0,
                min_elapsed_sec=0.0,
                max_elapsed_sec=0.0,
                total_orders_attempted=0,
                total_orders_processed=0,
                total_orders_dropped=0,
                total_orders_unhandled=0,
                total_trades_generated=0,
                total_volume_matched=0,
                stage_connectivity=STAGE_CONNECTIVITY.get(self.config.scope, {}),
                limitations=PIPELINE_LIMITATIONS,
            )

        throughputs = [r.throughput for r in repetitions]
        elapsed_times = [r.elapsed_sec for r in repetitions]

        mean_tp = statistics.mean(throughputs)
        median_tp = statistics.median(throughputs)
        min_tp = min(throughputs)
        max_tp = max(throughputs)
        std_tp = statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0

        mean_el = statistics.mean(elapsed_times)
        min_el = min(elapsed_times)
        max_el = max(elapsed_times)

        total_attempted = sum(r.orders_attempted for r in repetitions)
        total_processed = sum(r.orders_processed for r in repetitions)
        total_dropped = sum(r.orders_dropped for r in repetitions)
        total_unhandled = sum(r.orders_unhandled for r in repetitions)
        total_trades = sum(r.trades_generated for r in repetitions)
        total_volume = sum(r.volume_matched for r in repetitions)

        return BenchmarkSummary(
            scope=self.config.scope,
            scope_description=SCOPE_DESCRIPTIONS.get(self.config.scope, self.config.scope),
            target_orders=self.config.orders,
            batch_size=self.config.batch_size,
            repetition_count=len(repetitions),
            warmup_count=self.config.warmup,
            limit_only=self.config.limit_only,
            seed=self.config.seed,
            repetitions=repetitions,
            warmup_metrics=warmup_metric,
            mean_throughput=mean_tp,
            median_throughput=median_tp,
            min_throughput=min_tp,
            max_throughput=max_tp,
            std_throughput=std_tp,
            mean_elapsed_sec=mean_el,
            min_elapsed_sec=min_el,
            max_elapsed_sec=max_el,
            total_orders_attempted=total_attempted,
            total_orders_processed=total_processed,
            total_orders_dropped=total_dropped,
            total_orders_unhandled=total_unhandled,
            total_trades_generated=total_trades,
            total_volume_matched=total_volume,
            stage_connectivity=STAGE_CONNECTIVITY.get(self.config.scope, {}),
            limitations=PIPELINE_LIMITATIONS,
        )


# ==============================================================================
# Terminal Report Formatting Helpers
# ==============================================================================

def format_benchmark_report(summary: BenchmarkSummary, use_color: bool = True) -> str:
    """Render a clean, formatted ASCII/ANSI terminal report."""
    c_cyan = "\033[1;36m" if use_color else ""
    c_white = "\033[1;37m" if use_color else ""
    c_green = "\033[1;32m" if use_color else ""
    c_yellow = "\033[1;33m" if use_color else ""
    c_magenta = "\033[1;35m" if use_color else ""
    c_red = "\033[1;31m" if use_color else ""
    c_reset = "\033[0m" if use_color else ""

    lines = []
    lines.append(f"{c_cyan}{'=' * 80}{c_reset}")
    lines.append(f"{c_white}        CHRONOSMATCH :: ORDER PROCESSING PIPELINE BENCHMARK (DAY 8){c_reset}")
    lines.append(f"{c_cyan}{'=' * 80}{c_reset}")
    lines.append(f"  Tested Scope      : {c_white}{summary.scope_description}{c_reset}")
    lines.append(f"  Target Orders     : {c_white}{summary.target_orders:,} orders/run{c_reset}")
    lines.append(f"  Repetitions       : {c_white}{summary.repetition_count} runs{c_reset} (with {summary.warmup_count} warmup)")
    lines.append(f"  Batch Size        : {summary.batch_size} orders/burst")
    order_type_str = "LIMIT only (100% engine connected)" if summary.limit_only else "Mixed (90% LIMIT, 10% MARKET/truthfully unhandled)"
    lines.append(f"  Order Types       : {order_type_str}")
    lines.append(f"  Clock Mechanism   : time.perf_counter_ns() [High-Resolution Monotonic]")
    lines.append(f"{c_cyan}{'=' * 80}{c_reset}")

    if summary.warmup_metrics is not None:
        wm = summary.warmup_metrics
        lines.append(
            f"  [Warmup] Processed {wm.orders_processed:,} orders in {wm.elapsed_sec:.4f}s "
            f"({c_yellow}{wm.throughput:,.0f} orders/sec{c_reset})"
        )
        lines.append("")

    lines.append(f"{c_white}Repetition Results:{c_reset}")
    lines.append("-" * 80)
    lines.append(
        f" {'Run':>4} | {'Attempted':>9} | {'Processed':>9} | {'Dropped':>7} | {'Trades':>8} | {'Elapsed (s)':>11} | {'Throughput (ord/s)':>18}"
    )
    lines.append("-" * 80)

    for rep in summary.repetitions:
        dropped_str = f"{c_red}{rep.orders_dropped:>7,}{c_reset}" if rep.orders_dropped > 0 else f"{rep.orders_dropped:>7,}"
        lines.append(
            f" {rep.repetition_index:>4} | "
            f"{rep.orders_attempted:>9,} | "
            f"{rep.orders_processed:>9,} | "
            f"{dropped_str} | "
            f"{rep.trades_generated:>8,} | "
            f"{rep.elapsed_sec:>11.4f} | "
            f"{c_green}{rep.throughput:>18,.0f}{c_reset}"
        )
    lines.append("-" * 80)

    lines.append("")
    lines.append(f"{c_green}{'=' * 80}{c_reset}")
    lines.append(f"{c_white}Summary Statistics ({summary.repetition_count} repetitions):{c_reset}")
    lines.append(f"{c_green}{'=' * 80}{c_reset}")
    lines.append(f"  Mean Throughput   : {c_yellow}{summary.mean_throughput:,.0f} orders/sec{c_reset}")
    lines.append(f"  Median Throughput : {c_yellow}{summary.median_throughput:,.0f} orders/sec{c_reset}")
    lines.append(f"  Min Throughput    : {summary.min_throughput:,.0f} orders/sec")
    lines.append(f"  Max Throughput    : {summary.max_throughput:,.0f} orders/sec")
    lines.append(f"  Std Deviation     : {summary.std_throughput:,.0f} orders/sec")
    lines.append(f"  Mean Elapsed Time : {summary.mean_elapsed_sec:.4f} seconds")
    lines.append(f"  Total Processed   : {c_white}{summary.total_orders_processed:,} orders{c_reset}")
    lines.append(f"  Total Trades Fills: {c_magenta}{summary.total_trades_generated:,} trades{c_reset}")
    lines.append(f"  Total Volume      : {c_magenta}{summary.total_volume_matched:,} shares{c_reset}")
    if summary.total_orders_dropped > 0:
        lines.append(f"  Total Dropped     : {c_red}{summary.total_orders_dropped:,} orders{c_reset}")
    if summary.total_orders_unhandled > 0:
        lines.append(f"  Total Unhandled   : {c_yellow}{summary.total_orders_unhandled:,} non-LIMIT orders{c_reset}")

    lines.append(f"{c_green}{'=' * 80}{c_reset}")
    lines.append(f"{c_white}Pipeline Stage Connectivity & Limitations:{c_reset}")
    for stage, connected in summary.stage_connectivity.items():
        status = f"{c_green}[CONNECTED]{c_reset}" if connected else f"{c_yellow}[BYPASS/N/A]{c_reset}"
        lines.append(f"  * {stage:<20}: {status}")

    lines.append(f"\n{c_white}Truthful Pipeline Disclosures:{c_reset}")
    for limitation in summary.limitations:
        lines.append(f"  - {limitation}")
    lines.append(f"{c_cyan}{'=' * 80}{c_reset}\n")

    return "\n".join(lines)


def format_json_report(summary: BenchmarkSummary) -> str:
    """Serialize benchmark summary metrics to formatted JSON."""
    return json.dumps(asdict(summary), indent=2)
