"""Unit tests for ChronosMatch Market Firehose."""

import asyncio
import os
import tempfile
import pytest
from chronos.firehose import FastOrderGenerator, MarketFirehose
from chronos.ring_buffer import MmapRingBuffer


def test_fast_order_generator():
    """Verify order generator produces correctly structured batches."""
    gen = FastOrderGenerator(initial_order_id=100)
    batch = gen.generate_batch(500)
    assert len(batch) == 500
    assert batch[0][0] == 100
    assert batch[-1][0] == 599

    # Check data fields: (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type)
    first = batch[0]
    assert isinstance(first[0], int)
    assert isinstance(first[1], int)
    assert isinstance(first[2], float)
    assert isinstance(first[3], int)
    assert first[3] in (10, 20, 50, 100, 200, 500, 1000)
    assert first[5] in (1, 2)  # Side BUY / SELL


def test_firehose_throughput_blast():
    """Test blasting 50,000 orders into ring buffer via asyncio."""
    fd, path = tempfile.mkstemp(prefix="chronos_firehose_test_", suffix=".bin")
    os.close(fd)

    # 131,072 slots capacity
    buf = MmapRingBuffer(path, capacity=131_072, create=True)
    firehose = MarketFirehose(buf, target_rate=200_000, batch_size=500)

    async def _runner():
        return await firehose.blast(total_orders=50_000, print_progress=False)

    try:
        stats = asyncio.run(_runner())
        assert stats.total_orders_sent >= 50_000
        assert buf.available_to_read() == stats.total_orders_sent
        assert stats.avg_rate > 50_000  # Verify high throughput
    finally:
        buf.close()
        if os.path.exists(path):
            os.remove(path)
