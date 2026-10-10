"""Unit tests for ChronosMatch MmapRingBuffer."""

import os
import tempfile
import pytest
from chronos.protocol import Order, Side, OrderType, SYMBOLS
from chronos.ring_buffer import MmapRingBuffer


@pytest.fixture
def temp_buffer():
    fd, path = tempfile.mkstemp(prefix="chronos_test_", suffix=".bin")
    os.close(fd)
    buf = MmapRingBuffer(path, capacity=1024, create=True)
    yield buf
    buf.close()
    if os.path.exists(path):
        os.remove(path)


def test_buffer_creation_and_header(temp_buffer):
    """Test buffer initialization and header values."""
    buf = temp_buffer
    assert buf.capacity == 1024
    assert buf.mask == 1023
    assert buf.write_head == 0
    assert buf.read_tail == 0
    assert buf.available_to_read() == 0
    assert buf.available_to_write() == 1024
    assert buf.is_empty() is True
    assert buf.is_full() is False


def test_single_write_and_read(temp_buffer):
    """Test writing and reading a single order."""
    buf = temp_buffer
    ok = buf.write(
        order_id=42,
        timestamp_ns=100_000,
        price=150.25,
        quantity=300,
        symbol_id=SYMBOLS["AAPL"],
        side=Side.BUY,
        order_type=OrderType.LIMIT,
    )
    assert ok is True
    assert buf.write_head == 1
    assert buf.read_tail == 0
    assert buf.available_to_read() == 1
    assert buf.is_empty() is False

    read_order = buf.read_order()
    assert read_order is not None
    assert read_order.order_id == 42
    assert read_order.price == 150.25
    assert read_order.quantity == 300
    assert read_order.symbol_str == "AAPL"
    assert read_order.side_str == "BUY"

    assert buf.read_tail == 1
    assert buf.is_empty() is True
    assert buf.read_order() is None


def test_batch_write_and_batch_read(temp_buffer):
    """Test high-throughput batch writes and reads."""
    buf = temp_buffer
    batch = [
        (i, 1000 + i, 100.0 + (i * 0.1), 10 * i, SYMBOLS["NVDA"], int(Side.BUY), int(OrderType.LIMIT))
        for i in range(1, 101)
    ]

    written = buf.write_batch(batch)
    assert written == 100
    assert buf.available_to_read() == 100

    read_batch = buf.read_batch_orders(max_items=150)
    assert len(read_batch) == 100
    assert read_batch[0].order_id == 1
    assert read_batch[-1].order_id == 100
    assert buf.is_empty() is True


def test_circular_wrap_around(temp_buffer):
    """Verify that buffer wraps around capacity seamlessly without data corruption."""
    buf = temp_buffer
    # Buffer capacity is 1024. Write and read 5000 items in chunks.
    chunk_size = 200
    for chunk in range(25):
        items = [
            (chunk * chunk_size + i, 12345, 50.0, 100, SYMBOLS["TSLA"], 1, 1)
            for i in range(chunk_size)
        ]
        written = buf.write_batch(items)
        assert written == chunk_size

        read_items = buf.read_batch_raw(chunk_size)
        assert len(read_items) == chunk_size
        assert read_items[0][0] == chunk * chunk_size
        assert read_items[-1][0] == chunk * chunk_size + (chunk_size - 1)

    assert buf.write_head == 5000
    assert buf.read_tail == 5000
    assert buf.is_empty() is True


def test_buffer_full_and_overwrite(temp_buffer):
    """Test behavior when buffer is full with overwrite_on_full=True."""
    buf = temp_buffer
    # Capacity is 1024. Fill it completely.
    fill_items = [(i, 1000, 10.0, 100, SYMBOLS["AAPL"], 1, 1) for i in range(1024)]
    written = buf.write_batch(fill_items)
    assert written == 1024
    assert buf.is_full() is True

    # Try to write with overwrite_on_full=False
    ok = buf.write(9999, 1000, 10.0, 100, SYMBOLS["AAPL"], 1, 1, overwrite_on_full=False)
    assert ok is False

    # Write with overwrite_on_full=True
    ok = buf.write(9999, 1000, 10.0, 100, SYMBOLS["AAPL"], 1, 1, overwrite_on_full=True)
    assert ok is True
    assert buf.messages_dropped == 1

    # Oldest item (order_id 0) was discarded, next is 1
    first_read = buf.read_order()
    assert first_read.order_id == 1
