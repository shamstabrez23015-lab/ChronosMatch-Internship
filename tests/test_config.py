"""Unit tests for ChronosMatch Shared Configuration Module.

Tests cover:
- Default configuration values and constants.
- Correct field types.
- Valid custom configurations.
- Validation helper functions and boundary conditions.
- Rejection of invalid numeric values and incorrect types.
- Independent configuration instances.
- Serialization and dictionary conversion helpers.
"""

from typing import Any
import pytest

from chronos.config import (
    DEFAULT_BENCHMARK_CAPACITY,
    DEFAULT_BENCHMARK_ORDERS,
    DEFAULT_BUFFER_CAPACITY,
    DEFAULT_BUFFER_PATH,
    DEFAULT_CONSUMER_BATCH_SIZE,
    DEFAULT_LATENCY_MAX_SAMPLES,
    DEFAULT_OVERWRITE_ON_FULL,
    DEFAULT_PRODUCER_BATCH_SIZE,
    DEFAULT_REFRESH_INTERVAL_MS,
    DEFAULT_SLOT_SIZE,
    DEFAULT_TARGET_RATE,
    HEADER_PAGE_SIZE,
    MIN_TERMINAL_COLS,
    MIN_TERMINAL_ROWS,
    ChronosConfig,
    SystemConfig,
    is_power_of_two,
    validate_batch_size,
    validate_benchmark_orders,
    validate_buffer_capacity,
    validate_positive_int,
    validate_refresh_interval_ms,
    validate_target_rate,
)


# ==============================================================================
# 1. Default Configuration Tests
# ==============================================================================

def test_config_defaults_match_project_constants():
    """Verify ChronosConfig default values match canonical project constants."""
    config = ChronosConfig()

    assert config.buffer_capacity == DEFAULT_BUFFER_CAPACITY
    assert config.buffer_capacity == 262_144
    assert config.buffer_path == DEFAULT_BUFFER_PATH
    assert config.slot_size == DEFAULT_SLOT_SIZE
    assert config.slot_size == 32

    assert config.producer_batch_size == DEFAULT_PRODUCER_BATCH_SIZE
    assert config.producer_batch_size == 500
    assert config.target_rate == DEFAULT_TARGET_RATE
    assert config.target_rate == 100_000
    assert config.overwrite_on_full is True

    assert config.consumer_batch_size == DEFAULT_CONSUMER_BATCH_SIZE
    assert config.consumer_batch_size == 1_000

    assert config.benchmark_orders == DEFAULT_BENCHMARK_ORDERS
    assert config.benchmark_orders == 300_000

    assert config.refresh_interval_ms == DEFAULT_REFRESH_INTERVAL_MS
    assert config.refresh_interval_ms == 100
    assert config.min_terminal_rows == MIN_TERMINAL_ROWS
    assert config.min_terminal_rows == 30
    assert config.min_terminal_cols == MIN_TERMINAL_COLS
    assert config.min_terminal_cols == 72


def test_alias_system_config():
    """Verify SystemConfig is an alias for ChronosConfig."""
    assert SystemConfig is ChronosConfig
    cfg = SystemConfig()
    assert isinstance(cfg, ChronosConfig)


def test_constants_definitions():
    """Verify standalone constants reflect expected architecture values."""
    assert DEFAULT_BUFFER_CAPACITY == 262_144
    assert DEFAULT_BENCHMARK_CAPACITY == 524_288
    assert DEFAULT_SLOT_SIZE == 32
    assert HEADER_PAGE_SIZE == 4096
    assert DEFAULT_TARGET_RATE == 100_000
    assert DEFAULT_PRODUCER_BATCH_SIZE == 500
    assert DEFAULT_CONSUMER_BATCH_SIZE == 1_000
    assert DEFAULT_LATENCY_MAX_SAMPLES == 50_000
    assert DEFAULT_REFRESH_INTERVAL_MS == 100
    assert MIN_TERMINAL_ROWS == 30
    assert MIN_TERMINAL_COLS == 72


# ==============================================================================
# 2. Type Checking Tests
# ==============================================================================

def test_config_field_types():
    """Verify all configuration fields have strictly correct types."""
    config = ChronosConfig()

    assert type(config.buffer_capacity) is int
    assert type(config.slot_size) is int
    assert type(config.producer_batch_size) is int
    assert type(config.target_rate) is int
    assert type(config.consumer_batch_size) is int
    assert type(config.benchmark_orders) is int
    assert type(config.refresh_interval_ms) is int
    assert type(config.min_terminal_rows) is int
    assert type(config.min_terminal_cols) is int
    assert type(config.overwrite_on_full) is bool
    assert isinstance(config.buffer_path, str)


# ==============================================================================
# 3. Valid Custom Configurations
# ==============================================================================

def test_custom_valid_configuration():
    """Verify custom valid configuration parameters are set correctly."""
    config = ChronosConfig(
        buffer_capacity=65_536,
        producer_batch_size=250,
        consumer_batch_size=500,
        target_rate=50_000,
        benchmark_orders=100_000,
        refresh_interval_ms=50,
        buffer_path="custom/path.bin",
        overwrite_on_full=False,
    )

    assert config.buffer_capacity == 65_536
    assert config.producer_batch_size == 250
    assert config.consumer_batch_size == 500
    assert config.target_rate == 50_000
    assert config.benchmark_orders == 100_000
    assert config.refresh_interval_ms == 50
    assert config.buffer_path == "custom/path.bin"
    assert config.overwrite_on_full is False


def test_refresh_interval_accepts_float_and_converts_to_int():
    """Verify float refresh interval (e.g. 50.0) is validated and converted."""
    config = ChronosConfig(refresh_interval_ms=50.0)
    assert config.refresh_interval_ms == 50
    assert type(config.refresh_interval_ms) is int


# ==============================================================================
# 4. Rejection of Invalid Values & Types
# ==============================================================================

@pytest.mark.parametrize("invalid_capacity", [0, -1, -262_144])
def test_reject_non_positive_buffer_capacity(invalid_capacity: int):
    """Buffer capacity must be strictly positive."""
    with pytest.raises(ValueError, match="Buffer capacity must be positive"):
        ChronosConfig(buffer_capacity=invalid_capacity)


@pytest.mark.parametrize("invalid_type", ["262144", 3.14, None, True, False, []])
def test_reject_invalid_type_buffer_capacity(invalid_type: Any):
    """Buffer capacity must be an integer, not string/float/bool/None."""
    with pytest.raises(TypeError, match="Buffer capacity must be an integer"):
        ChronosConfig(buffer_capacity=invalid_type)


@pytest.mark.parametrize("invalid_batch", [0, -1, -500])
def test_reject_non_positive_producer_batch_size(invalid_batch: int):
    """Producer batch size must be strictly positive."""
    with pytest.raises(ValueError, match="Producer batch size must be positive"):
        ChronosConfig(producer_batch_size=invalid_batch)


@pytest.mark.parametrize("invalid_type", ["500", 2.5, None, True, False])
def test_reject_invalid_type_producer_batch_size(invalid_type: Any):
    """Producer batch size must reject non-integers."""
    with pytest.raises(TypeError, match="Producer batch size must be an integer"):
        ChronosConfig(producer_batch_size=invalid_type)


@pytest.mark.parametrize("invalid_batch", [0, -1, -1000])
def test_reject_non_positive_consumer_batch_size(invalid_batch: int):
    """Consumer batch size must be strictly positive."""
    with pytest.raises(ValueError, match="Consumer batch size must be positive"):
        ChronosConfig(consumer_batch_size=invalid_batch)


@pytest.mark.parametrize("invalid_type", ["1000", 1.5, None, True, False])
def test_reject_invalid_type_consumer_batch_size(invalid_type: Any):
    """Consumer batch size must reject non-integers."""
    with pytest.raises(TypeError, match="Consumer batch size must be an integer"):
        ChronosConfig(consumer_batch_size=invalid_type)


@pytest.mark.parametrize("invalid_rate", [0, -1, -100_000])
def test_reject_non_positive_target_rate(invalid_rate: int):
    """Target order generation rate must be strictly positive."""
    with pytest.raises(ValueError, match="Target rate must be positive"):
        ChronosConfig(target_rate=invalid_rate)


@pytest.mark.parametrize("invalid_orders", [0, -1, -10_000])
def test_reject_non_positive_benchmark_orders(invalid_orders: int):
    """Benchmark orders count must be strictly positive."""
    with pytest.raises(ValueError, match="Benchmark orders must be positive"):
        ChronosConfig(benchmark_orders=invalid_orders)


@pytest.mark.parametrize("invalid_refresh", [0, -1, -100])
def test_reject_non_positive_refresh_interval(invalid_refresh: int):
    """Dashboard refresh interval must be strictly positive."""
    with pytest.raises(ValueError, match="Refresh interval must be positive"):
        ChronosConfig(refresh_interval_ms=invalid_refresh)


@pytest.mark.parametrize("invalid_type", ["100", None, True, False, [100]])
def test_reject_invalid_type_refresh_interval(invalid_type: Any):
    """Dashboard refresh interval must reject booleans and strings."""
    with pytest.raises(TypeError, match="Refresh interval must be a positive integer or float"):
        ChronosConfig(refresh_interval_ms=invalid_type)


def test_post_mutation_validation():
    """Verify that calling validate() on an instance after mutating an attribute detects invalid values."""
    config = ChronosConfig()
    config.producer_batch_size = -99
    with pytest.raises(ValueError, match="Producer batch size must be positive"):
        config.validate()


# ==============================================================================
# 5. Independent Instances Tests
# ==============================================================================

def test_independent_instances():
    """Verify separate ChronosConfig instances do not share state."""
    config_a = ChronosConfig()
    config_b = ChronosConfig()

    assert config_a is not config_b

    # Mutate instance A
    config_a.producer_batch_size = 250
    config_a.refresh_interval_ms = 50

    # Instance B must remain unaffected with original defaults
    assert config_a.producer_batch_size == 250
    assert config_b.producer_batch_size == DEFAULT_PRODUCER_BATCH_SIZE
    assert config_a.refresh_interval_ms == 50
    assert config_b.refresh_interval_ms == DEFAULT_REFRESH_INTERVAL_MS


def test_copy_creates_independent_instance():
    """Verify copy() creates an independent deep duplicate."""
    orig = ChronosConfig(producer_batch_size=750, refresh_interval_ms=200)
    cloned = orig.copy()

    assert cloned is not orig
    assert cloned.producer_batch_size == 750
    assert cloned.refresh_interval_ms == 200

    cloned.producer_batch_size = 100
    assert orig.producer_batch_size == 750
    assert cloned.producer_batch_size == 100


def test_dict_serialization_roundtrip():
    """Verify to_dict and from_dict roundtrip correctly."""
    original = ChronosConfig(
        buffer_capacity=131_072,
        producer_batch_size=300,
        consumer_batch_size=600,
    )
    data = original.to_dict()
    assert isinstance(data, dict)
    assert data["buffer_capacity"] == 131_072
    assert data["producer_batch_size"] == 300

    reconstructed = ChronosConfig.from_dict(data)
    assert reconstructed is not original
    assert reconstructed == original


# ==============================================================================
# 6. Direct Validator Function Tests
# ==============================================================================

def test_is_power_of_two():
    """Verify power-of-two helper logic."""
    assert is_power_of_two(1) is True
    assert is_power_of_two(2) is True
    assert is_power_of_two(4) is True
    assert is_power_of_two(16) is True
    assert is_power_of_two(262_144) is True
    assert is_power_of_two(524_288) is True

    assert is_power_of_two(0) is False
    assert is_power_of_two(-16) is False
    assert is_power_of_two(3) is False
    assert is_power_of_two(100) is False
    assert is_power_of_two(True) is False  # bool must not qualify
    assert is_power_of_two("16") is False  # str must not qualify


def test_validate_buffer_capacity_power_of_two_enforcement():
    """Verify require_power_of_two flag in validate_buffer_capacity."""
    assert validate_buffer_capacity(262_144, require_power_of_two=True) == 262_144
    assert validate_buffer_capacity(100, require_power_of_two=False) == 100

    with pytest.raises(ValueError, match="must be a power of 2"):
        validate_buffer_capacity(100, require_power_of_two=True)


def test_validate_positive_int():
    """Verify generic positive integer validator."""
    assert validate_positive_int(10, "Count") == 10

    with pytest.raises(ValueError, match="Count must be positive"):
        validate_positive_int(0, "Count")

    with pytest.raises(TypeError, match="Count must be an integer"):
        validate_positive_int(True, "Count")

    with pytest.raises(TypeError, match="Count must be an integer"):
        validate_positive_int("10", "Count")
