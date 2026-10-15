"""ChronosMatch Shared Configuration Module.

Provides centralized configuration constants, a structured dataclass (`ChronosConfig`),
and validation helpers for the ChronosMatch High-Frequency Trading Engine.

This module unifies parameters across the IPC ring buffer, producer (firehose),
consumer, terminal dashboard, and benchmark suite without altering existing defaults.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import os
from typing import Any, Dict


# ==============================================================================
# Canonical Project Defaults (matching existing components)
# ==============================================================================

# Ring Buffer Defaults (chronos/ring_buffer.py, scripts/run_firehose.py)
DEFAULT_BUFFER_CAPACITY: int = 262_144  # 2^18 slots (~8.4 MB with 32B slots)
DEFAULT_BENCHMARK_CAPACITY: int = 524_288  # 2^19 slots (~16.8 MB for stress tests)
DEFAULT_SLOT_SIZE: int = 32  # 32 bytes (ORDER_SIZE in chronos/protocol.py)
HEADER_PAGE_SIZE: int = 4096  # 4 KB page-aligned header

# Default Backing IPC Ring Buffer Path (scripts/run_firehose.py, run_consumer.py)
DEFAULT_BUFFER_PATH: str = os.path.join("data", "chronos_ring.bin")

# Producer / Market Firehose Defaults (chronos/firehose.py, scripts/run_firehose.py)
DEFAULT_TARGET_RATE: int = 100_000  # 100,000 orders/sec
DEFAULT_PRODUCER_BATCH_SIZE: int = 500  # 500 orders per burst
DEFAULT_OVERWRITE_ON_FULL: bool = True  # Ring buffer overwrite policy

# Consumer Defaults (chronos/consumer.py, scripts/run_consumer.py)
DEFAULT_CONSUMER_BATCH_SIZE: int = 1_000  # 1,000 orders per read batch
DEFAULT_LATENCY_MAX_SAMPLES: int = 50_000  # Latency reservoir sample size

# Benchmark Defaults (scripts/benchmark_ipc.py)
DEFAULT_BENCHMARK_ORDERS: int = 300_000  # Default total benchmark orders

# Terminal Dashboard Defaults (chronos/dashboard.py, scripts/run_dashboard.py)
DEFAULT_REFRESH_INTERVAL_MS: int = 100  # 100 ms (10 frames/sec)
MIN_TERMINAL_ROWS: int = 30  # Minimum terminal height
MIN_TERMINAL_COLS: int = 72  # Minimum terminal width


# ==============================================================================
# Validation Helpers
# ==============================================================================

def is_power_of_two(value: int) -> bool:
    """Check if a positive integer is a power of two."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0 and (value & (value - 1)) == 0


def validate_positive_int(value: Any, name: str = "Value") -> int:
    """Validate that a value is a strictly positive integer (> 0).

    Args:
        value: The value to validate.
        name: Parameter name for informative error messages.

    Returns:
        The validated integer.

    Raises:
        TypeError: If value is a boolean or not an integer.
        ValueError: If value is less than or equal to zero.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, got {type(value).__name__} ({value!r})")
    if value <= 0:
        raise ValueError(f"{name} must be positive (> 0), got {value}")
    return value


def validate_buffer_capacity(capacity: Any, require_power_of_two: bool = False) -> int:
    """Validate ring buffer slot capacity.

    Args:
        capacity: Number of slots in the ring buffer.
        require_power_of_two: If True, enforces power-of-two capacity.

    Returns:
        The validated capacity integer.

    Raises:
        TypeError: If capacity is not an integer.
        ValueError: If capacity is <= 0 or not a power of 2 when required.
    """
    val = validate_positive_int(capacity, "Buffer capacity")
    if require_power_of_two and not is_power_of_two(val):
        raise ValueError(f"Buffer capacity must be a power of 2, got {val}")
    return val


def validate_batch_size(batch_size: Any, name: str = "Batch size") -> int:
    """Validate producer or consumer batch size.

    Args:
        batch_size: Number of orders per batch/burst.
        name: Parameter label (e.g. 'Producer batch size').

    Returns:
        The validated batch size integer.

    Raises:
        TypeError: If batch_size is not an integer.
        ValueError: If batch_size is <= 0.
    """
    return validate_positive_int(batch_size, name)


def validate_refresh_interval_ms(refresh_interval_ms: Any) -> int:
    """Validate terminal dashboard refresh interval in milliseconds.

    Args:
        refresh_interval_ms: Refresh interval in milliseconds.

    Returns:
        The validated integer interval.

    Raises:
        TypeError: If refresh_interval_ms is a boolean or not a numeric type.
        ValueError: If refresh_interval_ms is <= 0.
    """
    if isinstance(refresh_interval_ms, bool) or not isinstance(refresh_interval_ms, (int, float)):
        raise TypeError(
            f"Refresh interval must be a positive integer or float, got {type(refresh_interval_ms).__name__} ({refresh_interval_ms!r})"
        )
    if refresh_interval_ms <= 0:
        raise ValueError(f"Refresh interval must be positive (> 0), got {refresh_interval_ms}")
    return int(refresh_interval_ms)


def validate_target_rate(target_rate: Any) -> int:
    """Validate target order generation rate (orders per second)."""
    return validate_positive_int(target_rate, "Target rate")


def validate_benchmark_orders(orders: Any) -> int:
    """Validate benchmark order count."""
    return validate_positive_int(orders, "Benchmark orders")


# ==============================================================================
# Shared Configuration Dataclass
# ==============================================================================

@dataclass
class ChronosConfig:
    """Central configuration container for ChronosMatch components.

    Holds settings for the ring buffer, producer, consumer, benchmark suite,
    and dashboard. Automatically validates all numeric values on creation.
    """

    # Ring Buffer
    buffer_capacity: int = DEFAULT_BUFFER_CAPACITY
    buffer_path: str = DEFAULT_BUFFER_PATH
    slot_size: int = DEFAULT_SLOT_SIZE

    # Producer (Market Firehose)
    producer_batch_size: int = DEFAULT_PRODUCER_BATCH_SIZE
    target_rate: int = DEFAULT_TARGET_RATE
    overwrite_on_full: bool = DEFAULT_OVERWRITE_ON_FULL

    # Consumer
    consumer_batch_size: int = DEFAULT_CONSUMER_BATCH_SIZE

    # Benchmark
    benchmark_orders: int = DEFAULT_BENCHMARK_ORDERS

    # Dashboard
    refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS
    min_terminal_rows: int = MIN_TERMINAL_ROWS
    min_terminal_cols: int = MIN_TERMINAL_COLS

    def __post_init__(self) -> None:
        """Validate all parameters after initialization."""
        self.validate()

    def validate(self) -> ChronosConfig:
        """Validate all configuration attributes.

        Returns:
            self if all settings are valid.

        Raises:
            TypeError: If any numeric attribute is of an invalid type.
            ValueError: If any numeric attribute is non-positive or invalid.
        """
        self.buffer_capacity = validate_buffer_capacity(self.buffer_capacity)
        self.producer_batch_size = validate_batch_size(self.producer_batch_size, "Producer batch size")
        self.consumer_batch_size = validate_batch_size(self.consumer_batch_size, "Consumer batch size")
        self.target_rate = validate_target_rate(self.target_rate)
        self.benchmark_orders = validate_benchmark_orders(self.benchmark_orders)
        self.refresh_interval_ms = validate_refresh_interval_ms(self.refresh_interval_ms)
        self.slot_size = validate_positive_int(self.slot_size, "Slot size")
        self.min_terminal_rows = validate_positive_int(self.min_terminal_rows, "Minimum terminal rows")
        self.min_terminal_cols = validate_positive_int(self.min_terminal_cols, "Minimum terminal cols")
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to a dictionary."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChronosConfig:
        """Create a ChronosConfig instance from a dictionary."""
        return cls(**data)

    def copy(self) -> ChronosConfig:
        """Create an independent copy of this configuration."""
        return ChronosConfig(**self.to_dict())


# Convenient alias for backward/forward compatibility
SystemConfig = ChronosConfig
