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
from chronos.adapter import AdapterStats, OrderAdapter, TradeExecutionEvent
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
from chronos.trade_latency import TradeLatencySnapshot, TradeLatencyTracker
from chronos.audit import AuditRecord, AuditStats, AuditWorker, SQLiteAuditWorker
from chronos.config import (
    DEFAULT_AUDIT_DB_PATH,
    DEFAULT_AUDIT_BATCH_SIZE,
    DEFAULT_AUDIT_FLUSH_INTERVAL_S,
    DEFAULT_AUDIT_QUEUE_SIZE,
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
    "TradeExecutionEvent",
    "AuditRecord",
    "AuditStats",
    "AuditWorker",
    "SQLiteAuditWorker",
    "ChronosConfig",
    "SystemConfig",
    "DEFAULT_BUFFER_CAPACITY",
    "DEFAULT_PRODUCER_BATCH_SIZE",
    "DEFAULT_CONSUMER_BATCH_SIZE",
    "DEFAULT_TARGET_RATE",
    "DEFAULT_BENCHMARK_ORDERS",
    "DEFAULT_REFRESH_INTERVAL_MS",
    "DEFAULT_BUFFER_PATH",
    "DEFAULT_AUDIT_DB_PATH",
    "DEFAULT_AUDIT_BATCH_SIZE",
    "DEFAULT_AUDIT_FLUSH_INTERVAL_S",
    "DEFAULT_AUDIT_QUEUE_SIZE",
    "BenchmarkConfig",
    "BenchmarkSummary",
    "PipelineBenchmarkRunner",
    "RepetitionMetrics",
    "calculate_throughput",
    "TradeLatencySnapshot",
    "TradeLatencyTracker",
]

