"""Unit and integration tests for ChronosMatch SQLite Audit Worker.

Tests cover:
1. Batch SQLite writes (full batches, partial batches, flush thresholds).
2. Error handling & transaction rollback (simulated DB failures, dead-letter retention, retry).
3. Graceful worker shutdown (stops accepting, drains queue, flushes partial, idempotent repeated calls, thread cleanup).
4. Connection lifecycle and database cleanup.
5. Integration with OrderAdapter without blocking matching execution.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from typing import Generator, List

import pytest

from chronos.adapter import OrderAdapter
from chronos.audit import (
    AuditRecord,
    AuditRecordType,
    AuditStats,
    AuditWorker,
    SQLiteAuditWorker,
)
from chronos.matching_engine import MatchingEngine, TradeResult
from chronos.protocol import Order, OrderType, Side, SYMBOLS
from chronos.ring_buffer import MmapRingBuffer


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Provide a temporary SQLite database file path with cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_test_audit_", suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        # Also clean up potential WAL and SHM files
        for ext in ("-wal", "-shm"):
            wal_file = path + ext
            if os.path.exists(wal_file):
                try:
                    os.remove(wal_file)
                except OSError:
                    pass


@pytest.fixture
def audit_worker(temp_db_path: str) -> Generator[SQLiteAuditWorker, None, None]:
    """Provide an active SQLiteAuditWorker instance configured for testing."""
    worker = SQLiteAuditWorker(
        db_path=temp_db_path,
        batch_size=10,
        flush_interval_s=0.05,
        queue_size=1000,
        auto_start=True,
    )
    try:
        yield worker
    finally:
        worker.shutdown(timeout=2.0)


# ==============================================================================
# 1. Batch Writing Tests
# ==============================================================================

class TestAuditWorkerBatching:
    """Verifies batched write operations, threshold commits, and partial flushing."""

    def test_batch_writing_threshold_triggers_database_commit(
        self, audit_worker: SQLiteAuditWorker
    ):
        """Enqueueing exactly batch_size records triggers an atomic batch write."""
        batch_size = audit_worker.batch_size
        assert batch_size == 10

        # Enqueue exactly 10 records
        for i in range(batch_size):
            audit_worker.record(
                AuditRecord(
                    timestamp_ns=1_000_000 + i,
                    record_type=AuditRecordType.ORDER,
                    order_id=100 + i,
                    symbol_id=SYMBOLS["AAPL"],
                    side=int(Side.BUY),
                    price=150.0 + i,
                    quantity=10,
                )
            )

        # Allow worker thread time to process
        audit_worker.flush(timeout=2.0)

        # Invariants:
        assert audit_worker.stats.total_records_received == 10
        assert audit_worker.stats.total_records_written == 10
        assert audit_worker.stats.total_batches_written >= 1
        assert audit_worker.stats.failed_writes == 0
        assert audit_worker.get_record_count() == 10

    def test_large_multi_batch_writes(self, audit_worker: SQLiteAuditWorker):
        """Multiple batches are processed sequentially without losing records."""
        total_records = 75  # 7.5 batches with batch_size=10
        for i in range(total_records):
            audit_worker.record(
                AuditRecord(
                    timestamp_ns=2_000_000 + i,
                    record_type=AuditRecordType.ORDER,
                    order_id=200 + i,
                    symbol_id=SYMBOLS["MSFT"],
                    side=int(Side.SELL),
                    price=400.0,
                    quantity=5,
                )
            )

        audit_worker.flush(timeout=2.0)

        assert audit_worker.stats.total_records_written == total_records
        assert audit_worker.stats.total_batches_written >= 7
        assert audit_worker.get_record_count() == total_records

    def test_partial_batch_flushed_on_interval_or_explicit_flush(
        self, temp_db_path: str
    ):
        """Fewer than batch_size records are written on timeout or explicit flush."""
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=50,
            flush_interval_s=0.05,
            auto_start=True,
        )
        try:
            # Enqueue 3 records (far below batch_size of 50)
            for i in range(3):
                worker.record(
                    AuditRecord(
                        timestamp_ns=3_000_000 + i,
                        record_type=AuditRecordType.ORDER,
                        order_id=300 + i,
                    )
                )

            # Wait for flush_interval_s to trigger automatic partial flush
            time.sleep(0.15)

            assert worker.get_record_count() == 3
            assert worker.stats.total_records_written == 3
        finally:
            worker.shutdown()

    def test_record_batch_helper_enqueues_all(self, audit_worker: SQLiteAuditWorker):
        """record_batch helper enqueues multiple records efficiently."""
        records = [
            AuditRecord(timestamp_ns=i * 100, record_type=AuditRecordType.SYSTEM, order_id=i)
            for i in range(25)
        ]
        accepted = audit_worker.record_batch(records)
        assert accepted == 25

        audit_worker.flush()
        assert audit_worker.get_record_count() == 25


# ==============================================================================
# 2. Error Handling & Transaction Rollback Tests
# ==============================================================================

class TestAuditWorkerErrorHandling:
    """Verifies database write failures, transaction rollback, and dead-letter retention."""

    def test_write_failure_rolls_back_and_tracks_metrics(self, temp_db_path: str):
        """Simulated DB failure rolls back transaction and updates error metrics."""
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=5,
            auto_start=False,  # Control execution directly
        )
        try:
            # Corrupt the database by dropping the table
            with worker._db_lock:
                worker._conn.execute("DROP TABLE audit_log;")
                worker._conn.commit()

            # Enqueue records
            for i in range(5):
                worker.record(
                    AuditRecord(timestamp_ns=4_000_000 + i, record_type=AuditRecordType.ORDER, order_id=i)
                )

            # Attempt to write batch
            worker.flush()

            # Invariants:
            assert worker.stats.failed_writes >= 1
            assert worker.stats.failed_records == 5
            assert worker.stats.total_records_written == 0
            assert worker.stats.last_error is not None
            assert "no such table" in worker.stats.last_error.lower()

            # Records were NOT silently lost: saved in dead-letter list
            assert worker.dead_letter_count == 5
            dead_letter = worker.get_dead_letter_records()
            assert len(dead_letter) == 5
            assert dead_letter[0].order_id == 0
        finally:
            worker.shutdown()

    def test_dead_letter_recovery_when_database_restored(self, temp_db_path: str):
        """Failed records retained in dead-letter queue can be recovered after DB repair."""
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=5,
            auto_start=False,
        )
        try:
            # Drop table to cause failure
            with worker._db_lock:
                worker._conn.execute("DROP TABLE audit_log;")
                worker._conn.commit()

            for i in range(5):
                worker.record(
                    AuditRecord(timestamp_ns=5_000_000 + i, record_type=AuditRecordType.ORDER, order_id=500 + i)
                )
            worker.flush()
            assert worker.dead_letter_count == 5

            # Restore the table
            worker._init_db()

            # Retry writing dead letter records
            recovered = worker.retry_dead_letter()
            assert recovered == 5
            assert worker.dead_letter_count == 0
            assert worker.stats.retried_records_recovered == 5
            assert worker.get_record_count() == 5
        finally:
            worker.shutdown()

    def test_dead_letter_capacity_limit_enforced(self, temp_db_path: str):
        """Dead letter queue bounds memory to prevent unconstrained growth on permanent DB outages."""
        limit = 5
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=10,
            dead_letter_limit=limit,
            auto_start=False,
        )
        try:
            with worker._db_lock:
                worker._conn.execute("DROP TABLE audit_log;")
                worker._conn.commit()

            # Enqueue 10 records (exceeding limit of 5)
            for i in range(10):
                worker.record(AuditRecord(timestamp_ns=i, record_type=AuditRecordType.ORDER, order_id=i))
            worker.flush()

            # Invariants: exactly 5 retained, remaining 5 tracked as dropped
            assert worker.dead_letter_count == limit
            assert worker.stats.dropped_records == 5
        finally:
            worker.shutdown()


# ==============================================================================
# 3. Graceful Worker Shutdown Tests
# ==============================================================================

class TestAuditWorkerShutdown:
    """Verifies shutdown guarantees: stopping acceptance, queue draining, idempotency, cleanup."""

    def test_shutdown_stops_accepting_new_records(self, audit_worker: SQLiteAuditWorker):
        """Worker immediately stops accepting new records when shutdown begins."""
        assert audit_worker.is_accepting is True
        audit_worker.shutdown()

        assert audit_worker.is_accepting is False
        assert audit_worker.is_shutdown is True

        # New records are rejected
        accepted = audit_worker.record(
            AuditRecord(timestamp_ns=6_000_000, record_type=AuditRecordType.ORDER, order_id=601)
        )
        assert accepted is False
        assert audit_worker.stats.total_records_received == 0

    def test_shutdown_flushes_all_pending_and_queued_records(self, temp_db_path: str):
        """All records in queue and pending batch are committed before DB connection closes."""
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=20,
            flush_interval_s=1.0,  # Long interval to ensure shutdown triggers the flush
            auto_start=True,
        )
        # Rapidly enqueue 35 records
        for i in range(35):
            worker.record(
                AuditRecord(
                    timestamp_ns=7_000_000 + i,
                    record_type=AuditRecordType.ORDER,
                    order_id=700 + i,
                )
            )

        # Immediately call shutdown without explicit flush
        worker.shutdown(timeout=3.0)

        assert worker.is_shutdown is True
        assert worker.is_running is False

        # Re-open database with a new connection to verify disk contents
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_log;")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 35

    def test_repeated_shutdown_calls_are_safe_and_idempotent(
        self, audit_worker: SQLiteAuditWorker
    ):
        """Calling shutdown multiple times is safe, does not raise errors, and does not deadlock."""
        audit_worker.record(
            AuditRecord(timestamp_ns=8_000_000, record_type=AuditRecordType.SYSTEM, details="test")
        )

        # Call shutdown 3 consecutive times
        audit_worker.shutdown()
        audit_worker.shutdown()
        audit_worker.shutdown()
        audit_worker.close()  # Alias call

        assert audit_worker.is_shutdown is True
        assert audit_worker.is_running is False

    def test_thread_and_database_connection_cleanup(self, temp_db_path: str):
        """Worker thread terminates cleanly and database connection is closed."""
        worker = SQLiteAuditWorker(db_path=temp_db_path, auto_start=True)
        assert worker.is_running is True
        thread = worker._worker_thread
        assert thread is not None
        assert thread.is_alive() is True

        worker.shutdown()

        assert worker.is_running is False
        assert not thread.is_alive()
        assert worker._conn is None

    def test_context_manager_lifecycle(self, temp_db_path: str):
        """Context manager initializes worker and auto-shuts down cleanly on scope exit."""
        with SQLiteAuditWorker(db_path=temp_db_path, batch_size=5) as worker:
            assert worker.is_running is True
            for i in range(8):
                worker.record(
                    AuditRecord(timestamp_ns=9_000_000 + i, record_type=AuditRecordType.ORDER, order_id=i)
                )

        # After exiting context
        assert worker.is_shutdown is True
        assert worker.is_running is False

        # Verify all records persisted
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_log;")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 8


# ==============================================================================
# 4. Adapter Integration & Non-Blocking Flow Tests
# ==============================================================================

class TestAuditAdapterIntegration:
    """Verifies seamless integration with OrderAdapter without blocking order processing."""

    def test_adapter_with_audit_worker_persists_execution_events(
        self, temp_db_path: str
    ):
        """OrderAdapter dispatches orders and audit worker records executions into SQLite."""
        worker = SQLiteAuditWorker(db_path=temp_db_path, batch_size=5, auto_start=True)
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, dispatch_mode="match", audit_worker=worker)

        try:
            # Dispatch 2 crossing orders: SELL 100 @ 150.00, BUY 100 @ 150.00
            order1 = Order(1001, 1000, 150.00, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT))
            order2 = Order(1002, 2000, 150.00, 100, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT))

            trades1 = adapter.dispatch_order(order1)
            assert len(trades1) == 0  # Resting

            trades2 = adapter.dispatch_order(order2)
            assert len(trades2) == 1  # Matched

            # Flush audit worker
            worker.flush()

            # Query persisted audit records
            records = worker.query_records()
            assert len(records) == 2

            # First record: resting SELL
            rec1 = records[0]
            assert rec1.order_id == 1001
            assert rec1.side == int(Side.SELL)
            assert rec1.price == 150.00
            assert rec1.quantity == 100
            assert rec1.executed_quantity == 0

            # Second record: crossing BUY
            rec2 = records[1]
            assert rec2.order_id == 1002
            assert rec2.side == int(Side.BUY)
            assert rec2.price == 150.00
            assert rec2.executed_quantity == 100
            assert rec2.latency_ns >= 0
        finally:
            worker.shutdown()

    def test_adapter_cleans_up_without_affecting_unhandled_orders(
        self, temp_db_path: str
    ):
        """Unhandled CANCEL and MARKET orders are safely audited without engine errors."""
        worker = SQLiteAuditWorker(db_path=temp_db_path, batch_size=5, auto_start=True)
        engine = MatchingEngine()
        adapter = OrderAdapter(engine=engine, audit_worker=worker)

        try:
            cancel_order = Order(
                2001, 1000, 100.00, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.CANCEL)
            )
            adapter.dispatch_order(cancel_order)

            worker.flush()

            records = worker.query_records()
            assert len(records) == 1
            assert records[0].order_id == 2001
            assert adapter.stats.unhandled_order_types == 1
        finally:
            worker.shutdown()


# ==============================================================================
# 5. Conversion & Query Helpers Tests
# ==============================================================================

class TestAuditHelpersAndQueries:
    """Verifies helper conversions, queries, and dictionary serialization."""

    def test_audit_record_from_trade(self, audit_worker: SQLiteAuditWorker):
        """AuditRecord.from_trade accurately captures trade attributes."""
        trade = TradeResult(
            buy_order_id=10,
            sell_order_id=20,
            executed_quantity=50,
            execution_price_cents=15000,
            buy_remaining_quantity=0,
            sell_remaining_quantity=0,
            latency_ns=450,
        )
        rec = AuditRecord.from_trade(trade, symbol_id=SYMBOLS["AAPL"])
        assert rec.record_type == AuditRecordType.TRADE
        assert rec.order_id == 10
        assert rec.executed_price == 150.00
        assert rec.executed_quantity == 50
        assert rec.latency_ns == 450
        assert "sell_order_id=20" in rec.details

    def test_query_records_filters_by_type_and_order_id(
        self, audit_worker: SQLiteAuditWorker
    ):
        """query_records correctly filters by record_type and order_id."""
        audit_worker.record(AuditRecord(timestamp_ns=1, record_type=AuditRecordType.ORDER, order_id=50))
        audit_worker.record(AuditRecord(timestamp_ns=2, record_type=AuditRecordType.TRADE, order_id=50))
        audit_worker.record(AuditRecord(timestamp_ns=3, record_type=AuditRecordType.ORDER, order_id=60))
        audit_worker.flush()

        # Filter by record_type
        orders = audit_worker.query_records(record_type=AuditRecordType.ORDER)
        assert len(orders) == 2

        # Filter by order_id
        trades_50 = audit_worker.query_records(order_id=50)
        assert len(trades_50) == 2

        # Filter by both
        order_50 = audit_worker.query_records(record_type=AuditRecordType.ORDER, order_id=50)
        assert len(order_50) == 1
        assert order_50[0].order_id == 50

    def test_stats_to_dict_and_reset(self, audit_worker: SQLiteAuditWorker):
        """AuditStats.to_dict and reset functions as expected."""
        stats = audit_worker.stats
        stats.total_records_written = 100
        stats.failed_records = 0
        assert stats.write_success_rate == 1.0

        d = stats.to_dict()
        assert d["total_records_written"] == 100
        assert d["write_success_rate"] == 1.0

        stats.reset()
        assert stats.total_records_written == 0
        assert stats.write_success_rate == 1.0

    def test_queue_saturation_increments_dropped_records(self, temp_db_path: str):
        """When queue capacity is reached, new records return False and increment dropped count."""
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=10,
            queue_size=5,  # Tiny queue
            auto_start=False,
        )
        try:
            # Fill the queue
            for i in range(5):
                assert worker.record(AuditRecord(timestamp_ns=i, record_type=AuditRecordType.ORDER, order_id=i)) is True

            # Next record should be dropped without exception
            rejected = worker.record(AuditRecord(timestamp_ns=999, record_type=AuditRecordType.ORDER, order_id=999))
            assert rejected is False
            assert worker.stats.dropped_records == 1
        finally:
            worker.shutdown()

    def test_invalid_init_parameters_raise(self):
        """Invalid configuration values raise ValueError."""
        with pytest.raises(ValueError, match="batch_size must be positive"):
            SQLiteAuditWorker(batch_size=0)

        with pytest.raises(ValueError, match="flush_interval_s must be positive"):
            SQLiteAuditWorker(flush_interval_s=-0.5)

        with pytest.raises(ValueError, match="queue_size must be positive"):
            SQLiteAuditWorker(queue_size=0)

    def test_cannot_restart_after_shutdown(self, temp_db_path: str):
        """Attempting to restart an already shut down worker raises RuntimeError."""
        worker = SQLiteAuditWorker(db_path=temp_db_path, auto_start=True)
        worker.shutdown()

        with pytest.raises(RuntimeError, match="already been shut down"):
            worker.start()

    def test_high_volume_concurrent_enqueuing(self, temp_db_path: str):
        """Multiple threads concurrently recording events do not lose records or crash."""
        with SQLiteAuditWorker(db_path=temp_db_path, batch_size=25, queue_size=2000) as worker:
            threads = []
            records_per_thread = 50
            num_threads = 4

            def _producer(thread_id: int):
                for i in range(records_per_thread):
                    oid = thread_id * 1000 + i
                    worker.record(
                        AuditRecord(
                            timestamp_ns=time.time_ns(),
                            record_type=AuditRecordType.ORDER,
                            order_id=oid,
                            price=100.0,
                            quantity=10,
                        )
                    )

            for t_idx in range(num_threads):
                t = threading.Thread(target=_producer, args=(t_idx,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            worker.flush()

        # After shutdown via context manager
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_log;")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == num_threads * records_per_thread
