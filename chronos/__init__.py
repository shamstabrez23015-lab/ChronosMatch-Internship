"""ChronosMatch: Zero-Copy High-Frequency Trading Engine (Week 1 Part)."""

from chronos.protocol import (
    ORDER_SIZE,
    ORDER_STRUCT,
    ORDER_STRUCT_FORMAT,
    Order,
    OrderType,
    Side,
    SYMBOLS,
    SYMBOL_ID_TO_TICKER,
    pack_order_into,
    unpack_order_raw,
)
from chronos.ring_buffer import MmapRingBuffer, RingBufferFullError
from chronos.dashboard import DashboardConfig, TerminalDashboard
from chronos.adapter import AdapterStats, OrderAdapter
from chronos.config import (
    ChronosConfig,
    SystemConfig,
    DEFAULT_BUFFER_CAPACITY,
    DEFAULT_PRODUCER_BATCH_SIZE,
    DEFAULT_CONSUMER_BATCH_SIZE,
    DEFAULT_TARGET_RATE,
    DEFAULT_BENCHMARK_ORDERS,
    DEFAULT_REFRESH_INTERVAL_MS,
    DEFAULT_BUFFER_PATH,
)
from chronos.benchmark import (
    BenchmarkConfig,
    BenchmarkSummary,
    PipelineBenchmarkRunner,
    RepetitionMetrics,
    calculate_throughput,
)

__all__ = [
    "ORDER_SIZE",
    "ORDER_STRUCT",
    "ORDER_STRUCT_FORMAT",
    "Order",
    "OrderType",
    "Side",
    "SYMBOLS",
    "SYMBOL_ID_TO_TICKER",
    "pack_order_into",
    "unpack_order_raw",
    "MmapRingBuffer",
    "RingBufferFullError",
    "DashboardConfig",
    "TerminalDashboard",
    "OrderAdapter",
    "AdapterStats",
    "ChronosConfig",
    "SystemConfig",
    "DEFAULT_BUFFER_CAPACITY",
    "DEFAULT_PRODUCER_BATCH_SIZE",
    "DEFAULT_CONSUMER_BATCH_SIZE",
    "DEFAULT_TARGET_RATE",
    "DEFAULT_BENCHMARK_ORDERS",
    "DEFAULT_REFRESH_INTERVAL_MS",
    "DEFAULT_BUFFER_PATH",
    "BenchmarkConfig",
    "BenchmarkSummary",
    "PipelineBenchmarkRunner",
    "RepetitionMetrics",
    "calculate_throughput",
]

