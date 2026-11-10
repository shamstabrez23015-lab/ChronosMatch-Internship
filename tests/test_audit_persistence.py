"""End-to-End Audit Persistence Integration Tests for ChronosMatch (Week 4 Day 9).

Verifies the complete pipeline flow:
Market Firehose / Producer -> Protocol -> MmapRingBuffer -> ZeroCopyConsumer -> OrderAdapter -> MatchingEngine -> SQLiteAuditWorker -> SQLite Database.

Test Coverage:
1. End-to-end order processing across real project components.
2. SQLite persistence of trade executions, order references, prices, quantities, and timestamps.
3. Execution scenarios: full fills, partial fills, multi-level price sweeps (multiple executions from one order).
4. Prevention of record duplication or silent loss under high-frequency order bursts.
5. Reliability: pending records flushed on graceful shutdown, idempotent shutdown, database cleanup.
6. Database failure handling and dead-letter recovery without losing track of failed records.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from typing import Generator, List, Tuple

import pytest

from chronos.adapter import AdapterStats, OrderAdapter, TradeExecutionEvent
from chronos.audit import (
    AuditRecord,
    AuditRecordType,
    AuditStats,
    AuditWorker,
    SQLiteAuditWorker,
)
from chronos.consumer import ConsumerStats, ZeroCopyConsumer
from chronos.firehose import FastOrderGenerator
from chronos.matching_engine import MatchingEngine, TradeResult, price_to_cents
from chronos.protocol import (
    ORDER_SIZE,
    Order,
    OrderType,
    Side,
    SYMBOLS,
    pack_order_into,
    unpack_order_raw,
)
from chronos.ring_buffer import MmapRingBuffer


# ==============================================================================
# Pytest Fixtures
# ==============================================================================

@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create an isolated, temporary SQLite database file with guaranteed cleanup."""
    fd, path = tempfile.mkstemp(prefix="chronos_e2e_audit_", suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        for ext in ("-wal", "-shm"):
            wal_path = path + ext
            if os.path.exists(wal_path):
                try:
                    os.remove(wal_path)
                except OSError:
                    pass


@pytest.fixture
def isolated_ring_buffer() -> Generator[MmapRingBuffer, None, None]:
    """Create an isolated temporary memory-mapped ring buffer."""
    fd, path = tempfile.mkstemp(prefix="chronos_audit_ring_", suffix=".bin")
    os.close(fd)
    buf = MmapRingBuffer(filepath=path, capacity=1024, slot_size=ORDER_SIZE, create=True)
    try:
        yield buf
    finally:
        buf.close()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@pytest.fixture
def matching_engine() -> Generator[MatchingEngine, None, None]:
    """Provide a clean, verified MatchingEngine instance."""
    engine = MatchingEngine()
    assert engine.is_ready() is True
    yield engine
    engine.clear()


@pytest.fixture
def audit_worker(temp_db_path: str) -> Generator[SQLiteAuditWorker, None, None]:
    """Provide an active SQLiteAuditWorker instance configured for testing."""
    worker = SQLiteAuditWorker(
        db_path=temp_db_path,
        batch_size=10,
        flush_interval_s=0.05,
        queue_size=2000,
        auto_start=True,
    )
    try:
        yield worker
    finally:
        worker.shutdown(timeout=2.0)


@pytest.fixture
def order_adapter(
    isolated_ring_buffer: MmapRingBuffer,
    matching_engine: MatchingEngine,
    audit_worker: SQLiteAuditWorker,
) -> OrderAdapter:
    """Provide an OrderAdapter wired to buffer, engine, and audit worker with trade auditing enabled."""
    return OrderAdapter(
        ring_buffer=isolated_ring_buffer,
        engine=matching_engine,
        dispatch_mode="match",
        audit_worker=audit_worker,
        audit_trades=True,
    )


# ==============================================================================
# 1. End-to-End Pipeline Order Processing & Audit Flow
# ==============================================================================

class TestEndToEndPipelineAuditIntegration:
    """Verifies that orders flow from producer/buffer to engine and audit records persist in SQLite."""

    def test_full_pipeline_stream_persists_trades_to_sqlite(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Orders flow from binary ring buffer through consumer and adapter to matching engine,
        with all trade executions persisted in SQLite."""
        base_ts = 1_700_000_000_000_000_000
        sym_aapl = SYMBOLS["AAPL"]

        # Write 2 crossing orders into memory-mapped ring buffer
        # Order 1: SELL #101: 100 shares @ $150.00 (resting ask)
        # Order 2: BUY  #102: 100 shares @ $150.00 (crossing bid)
        orders = [
            (101, base_ts + 1000, 150.00, 100, sym_aapl, int(Side.SELL), int(OrderType.LIMIT)),
            (102, base_ts + 2000, 150.00, 100, sym_aapl, int(Side.BUY), int(OrderType.LIMIT)),
        ]
        written = isolated_ring_buffer.write_batch(orders)
        assert written == 2
        assert isolated_ring_buffer.available_to_read() == 2

        # Consumer drains from shared memory into adapter and matching engine
        consumer = ZeroCopyConsumer(
            ring_buffer=isolated_ring_buffer,
            batch_size=10,
            order_handler=order_adapter.dispatch_raw_order,
        )
        c_stats = consumer.run(total_orders=2, print_progress=False)
        assert c_stats.total_orders_read == 2
        assert isolated_ring_buffer.is_empty() is True

        # Matching engine generated 1 trade
        assert len(order_adapter.trades) == 1
        trade = order_adapter.trades[0]
        assert trade.buy_order_id == 102
        assert trade.sell_order_id == 101
        assert trade.executed_quantity == 100
        assert trade.execution_price_cents == 15000

        # Flush audit worker and verify SQLite persistence
        audit_worker.flush()

        # Query database directly using raw SQLite connection
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT record_type, order_id, price, executed_price, executed_quantity, details FROM audit_log WHERE record_type = 'TRADE';")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 1
        rec_type, o_id, px, exec_px, exec_qty, details = rows[0]
        assert rec_type == "TRADE"
        assert o_id == 102  # BUY order ID
        assert exec_px == 150.00
        assert exec_qty == 100
        assert "sell_order_id=101" in details

    def test_unmatched_and_non_crossing_orders_audit_fidelity(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Non-crossing orders rest in book, producing zero TRADE records and accurate EXECUTION records."""
        base_ts = 2_000_000_000_000_000_000
        sym_msft = SYMBOLS["MSFT"]

        # BUY @ $300.00 vs SELL @ $310.00 -> positive spread, no match
        orders = [
            (201, base_ts + 1000, 300.00, 50, sym_msft, int(Side.BUY), int(OrderType.LIMIT)),
            (202, base_ts + 2000, 310.00, 50, sym_msft, int(Side.SELL), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        order_adapter.drain_all()

        # Engine invariants
        assert matching_engine.bid_count() == 1
        assert matching_engine.ask_count() == 1
        assert len(order_adapter.trades) == 0

        audit_worker.flush()

        # Direct database verification
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        # Zero trade executions
        cursor.execute("SELECT COUNT(*) FROM audit_log WHERE record_type = 'TRADE';")
        trade_count = cursor.fetchone()[0]
        assert trade_count == 0

        # Two execution events recorded with matched=False
        cursor.execute("SELECT order_id, side, price, quantity, executed_quantity, details FROM audit_log WHERE record_type = 'EXECUTION' ORDER BY order_id ASC;")
        exec_rows = cursor.fetchall()
        conn.close()

        assert len(exec_rows) == 2
        # Order 201 (BUY)
        assert exec_rows[0][0] == 201
        assert exec_rows[0][1] == int(Side.BUY)
        assert exec_rows[0][2] == 300.00
        assert exec_rows[0][3] == 50
        assert exec_rows[0][4] == 0  # 0 executed volume
        assert "matched=False" in exec_rows[0][5]

        # Order 202 (SELL)
        assert exec_rows[1][0] == 202
        assert exec_rows[1][1] == int(Side.SELL)
        assert exec_rows[1][2] == 310.00
        assert exec_rows[1][3] == 50
        assert exec_rows[1][4] == 0
        assert "matched=False" in exec_rows[1][5]


# ==============================================================================
# 2. SQLite Schema and Persistence Fidelity
# ==============================================================================

class TestSQLiteTradePersistenceFidelity:
    """Verifies SQLite column schemas, prices, timestamps, and multi-symbol routing."""

    def test_schema_column_types_and_values(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Verifies all columns in audit_log adhere to expected schema and carry non-null timestamps."""
        t_now = time.time_ns()
        orders = [
            (301, t_now + 100, 225.50, 40, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (302, t_now + 200, 225.50, 40, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        order_adapter.drain_all()
        audit_worker.flush()

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp_ns, record_type, order_id, symbol_id, side, price, quantity, executed_price, executed_quantity, latency_ns, details, created_at FROM audit_log WHERE record_type = 'TRADE';")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        rec_id, ts_ns, r_type, ord_id, sym_id, side, px, qty, exec_px, exec_qty, lat_ns, details, created_at = row

        assert isinstance(rec_id, int) and rec_id >= 1
        assert isinstance(ts_ns, int) and ts_ns > 0
        assert r_type == "TRADE"
        assert ord_id == 302
        assert sym_id == SYMBOLS["AAPL"]
        assert exec_px == 225.50
        assert exec_qty == 40
        assert isinstance(lat_ns, int) and lat_ns >= 0
        assert "sell_order_id=301" in details
        assert created_at is not None

    def test_fractional_subpenny_prices_accuracy_in_sqlite(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Verify fractional and decimal dollar prices (e.g. $10.05, $49.99) persist without IEEE float drift."""
        test_cases = [
            (401, 402, 10.05, 10),
            (403, 404, 49.99, 20),
            (405, 406, 999.95, 15),
        ]

        t_base = 3_000_000_000_000_000_000
        for b_id, a_id, px, qty in test_cases:
            s_order = (b_id, t_base, px, qty, SYMBOLS["NVDA"], int(Side.SELL), int(OrderType.LIMIT))
            b_order = (a_id, t_base + 10, px, qty, SYMBOLS["NVDA"], int(Side.BUY), int(OrderType.LIMIT))
            isolated_ring_buffer.write_batch([s_order, b_order])

        order_adapter.drain_all()
        audit_worker.flush()

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT executed_price, executed_quantity FROM audit_log WHERE record_type = 'TRADE' ORDER BY id ASC;")
        stored_trades = cursor.fetchall()
        conn.close()

        assert len(stored_trades) == 3
        for idx, (b_id, a_id, exp_px, exp_qty) in enumerate(test_cases):
            stored_px, stored_qty = stored_trades[idx]
            assert abs(stored_px - exp_px) < 1e-4
            assert stored_qty == exp_qty


# ==============================================================================
# 3. Execution Scenarios Audit Persistence
# ==============================================================================

class TestExecutionScenariosAuditPersistence:
    """Verifies full fills, partial fills, multi-level sweeps, and deduplication."""

    def test_full_order_fill_audit_persistence(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Scenario: Exact full fill clears both sides and stores exact trade record."""
        t_base = 4_000_000
        orders = [
            (501, t_base + 100, 100.00, 50, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (502, t_base + 200, 100.00, 50, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        order_adapter.drain_all()
        audit_worker.flush()

        # Engine book state: both sides completely cleared
        assert matching_engine.bid_count() == 0
        assert matching_engine.ask_count() == 0

        trades = audit_worker.query_records(record_type=AuditRecordType.TRADE)
        assert len(trades) == 1
        t = trades[0]
        assert t.order_id == 502
        assert t.executed_price == 100.00
        assert t.executed_quantity == 50
        assert "sell_order_id=501" in t.details

    def test_partial_order_fill_audit_persistence(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Scenario: Partial fill executes for smaller quantity; remainder rests in book."""
        t_base = 5_000_000
        # Resting SELL has 100 shares; arriving BUY wants only 40
        orders = [
            (601, t_base + 100, 120.00, 100, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (602, t_base + 200, 120.00, 40, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        order_adapter.drain_all()
        audit_worker.flush()

        # Engine book: SELL 601 has 60 remaining in asks book
        assert matching_engine.ask_count() == 1
        assert matching_engine.bid_count() == 0
        best_ask = matching_engine.get_best_sell_order()
        assert best_ask.order_id == 601
        assert best_ask.remaining_quantity == 60

        trades = audit_worker.query_records(record_type=AuditRecordType.TRADE)
        assert len(trades) == 1
        t = trades[0]
        assert t.order_id == 602
        assert t.executed_price == 120.00
        assert t.executed_quantity == 40
        assert "sell_order_id=601" in t.details

    def test_multiple_executions_from_one_incoming_order(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Scenario: Single incoming BUY sweeps 3 resting SELL levels, generating 3 distinct trade records."""
        t_base = 6_000_000
        sym_id = SYMBOLS["AAPL"]

        # 3 resting SELL orders at advancing price levels:
        # #701: 30 @ $100.00
        # #702: 40 @ $101.00
        # #703: 50 @ $102.00
        resting_sells = [
            (701, t_base + 100, 100.00, 30, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
            (702, t_base + 200, 101.00, 40, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
            (703, t_base + 300, 102.00, 50, sym_id, int(Side.SELL), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(resting_sells)
        order_adapter.drain_all()
        assert matching_engine.ask_count() == 3

        # Incoming large BUY for 100 shares @ $102.00:
        # Sweeps #701 (30 @ $100), sweeps #702 (40 @ $101), and takes 30 of #703 (@ $102).
        sweep_buy = (704, t_base + 400, 102.00, 100, sym_id, int(Side.BUY), int(OrderType.LIMIT))
        isolated_ring_buffer.write_batch([sweep_buy])
        order_adapter.drain_all()
        audit_worker.flush()

        # Engine checks
        assert matching_engine.bid_count() == 0  # BUY completely filled
        assert matching_engine.ask_count() == 1  # 20 shares of #703 remain
        rem_ask = matching_engine.get_best_sell_order()
        assert rem_ask.order_id == 703
        assert rem_ask.remaining_quantity == 20

        # SQLite Audit verification: exactly 3 distinct TRADE records generated from order #704
        trades = audit_worker.query_records(record_type=AuditRecordType.TRADE)
        assert len(trades) == 3

        # Trade 1: against 701
        assert trades[0].order_id == 704
        assert trades[0].executed_price == 100.00
        assert trades[0].executed_quantity == 30
        assert "sell_order_id=701" in trades[0].details

        # Trade 2: against 702
        assert trades[1].order_id == 704
        assert trades[1].executed_price == 101.00
        assert trades[1].executed_quantity == 40
        assert "sell_order_id=702" in trades[1].details

        # Trade 3: against 703
        assert trades[2].order_id == 704
        assert trades[2].executed_price == 102.00
        assert trades[2].executed_quantity == 30
        assert "sell_order_id=703" in trades[2].details

        total_vol = sum(t.executed_quantity for t in trades)
        assert total_vol == 100

    def test_records_not_duplicated_or_lost_under_burst(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        order_adapter: OrderAdapter,
        audit_worker: SQLiteAuditWorker,
        temp_db_path: str,
    ):
        """Burst of 40 orders (20 matching pairs) through the pipeline without duplication or dropped records."""
        t_base = 7_000_000
        sym_id = SYMBOLS["AAPL"]

        orders = []
        for i in range(20):
            # SELL pair
            orders.append(
                (8000 + i * 2, t_base + i * 20, 150.00, 10, sym_id, int(Side.SELL), int(OrderType.LIMIT))
            )
            # BUY pair
            orders.append(
                (8000 + i * 2 + 1, t_base + i * 20 + 10, 150.00, 10, sym_id, int(Side.BUY), int(OrderType.LIMIT))
            )

        isolated_ring_buffer.write_batch(orders)
        assert isolated_ring_buffer.available_to_read() == 40

        consumer = ZeroCopyConsumer(
            ring_buffer=isolated_ring_buffer,
            batch_size=8,
            order_handler=order_adapter.dispatch_raw_order,
        )
        c_stats = consumer.run(total_orders=40, print_progress=False)
        assert c_stats.total_orders_read == 40

        audit_worker.flush()

        # Database checks
        trades = audit_worker.query_records(record_type=AuditRecordType.TRADE)
        assert len(trades) == 20
        total_qty = sum(t.executed_quantity for t in trades)
        assert total_qty == 200

        # No records dropped
        assert audit_worker.stats.dropped_records == 0
        assert audit_worker.stats.failed_records == 0
        assert matching_engine.bid_count() == 0
        assert matching_engine.ask_count() == 0


# ==============================================================================
# 4. Audit Persistence Reliability & Recovery Tests
# ==============================================================================

class TestAuditPersistenceReliabilityAndRecovery:
    """Verifies shutdown flushing, connection cleanup, and simulated database failures."""

    def test_pending_audit_records_flushed_during_graceful_shutdown(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        temp_db_path: str,
    ):
        """Pending unwritten audit records flush automatically to SQLite during worker shutdown."""
        # Worker with large batch_size and long interval so records sit buffered
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=100,
            flush_interval_s=2.0,
            auto_start=True,
        )
        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            engine=matching_engine,
            dispatch_mode="match",
            audit_worker=worker,
            audit_trades=True,
        )

        orders = [
            (9001, 1000, 100.0, 10, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (9002, 2000, 100.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        adapter.drain_all()

        # Shutdown immediately without manual flush
        worker.shutdown(timeout=3.0)

        # Inspect database from external connection
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM audit_log WHERE record_type = 'TRADE';")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1
        assert worker.is_shutdown is True
        assert worker.is_running is False

    def test_worker_shutdown_is_idempotent_and_cleans_resources(
        self, temp_db_path: str
    ):
        """Multiple shutdown calls do not crash or leak threads, and DB is safely closed."""
        worker = SQLiteAuditWorker(db_path=temp_db_path, auto_start=True)
        worker.record(AuditRecord(timestamp_ns=1000, record_type=AuditRecordType.SYSTEM))

        worker.shutdown()
        worker.shutdown()  # Second call
        worker.close()     # Third call

        assert worker.is_shutdown is True
        assert worker.is_running is False
        assert worker._conn is None

    def test_database_failure_handling_preserves_records_in_dead_letter(
        self,
        isolated_ring_buffer: MmapRingBuffer,
        matching_engine: MatchingEngine,
        temp_db_path: str,
    ):
        """When SQLite encounters an error, transaction is rolled back and records are retained in dead-letter."""
        worker = SQLiteAuditWorker(
            db_path=temp_db_path,
            batch_size=5,
            auto_start=False,  # Direct synchronous control
        )
        adapter = OrderAdapter(
            ring_buffer=isolated_ring_buffer,
            engine=matching_engine,
            dispatch_mode="match",
            audit_worker=worker,
            audit_trades=True,
        )

        # Intentionally drop the table to simulate database corruption / failure
        with worker._db_lock:
            worker._conn.execute("DROP TABLE audit_log;")
            worker._conn.commit()

        # Send orders through the pipeline
        orders = [
            (9501, 1000, 150.0, 10, SYMBOLS["AAPL"], int(Side.SELL), int(OrderType.LIMIT)),
            (9502, 2000, 150.0, 10, SYMBOLS["AAPL"], int(Side.BUY), int(OrderType.LIMIT)),
        ]
        isolated_ring_buffer.write_batch(orders)
        adapter.drain_all()

        # Attempt flush into broken DB
        worker.flush()

        # Verify failure tracking
        assert worker.stats.failed_writes >= 1
        assert worker.stats.failed_records >= 1
        assert worker.dead_letter_count >= 1

        # Re-initialize database schema
        worker._init_db()

        # Recover failed records via retry_dead_letter
        recovered = worker.retry_dead_letter()
        assert recovered >= 1
        assert worker.dead_letter_count == 0

        # Verify records are now safely committed to SQLite
        records = worker.query_records(record_type=AuditRecordType.TRADE)
        assert len(records) == 1
        assert records[0].order_id == 9502

        worker.shutdown()

