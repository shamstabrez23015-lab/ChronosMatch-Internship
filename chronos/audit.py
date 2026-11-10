"""ChronosMatch SQLite Audit Worker: Asynchronous, Non-Blocking Trade & Order Auditing.

Provides high-throughput, transactional audit logging for financial orders, trades,
and engine execution events without blocking the high-frequency matching hot path:
1. Thread-safe in-memory FIFO queue decoupling the hot path from disk writes.
2. Micro-batched transactional SQLite writes with atomic commits.
3. Transaction rollback on failure with a dead-letter retention queue.
4. Comprehensive operational metrics tracking (batches, writes, failures, dropped).
5. Graceful and idempotent multi-stage worker shutdown.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import os
import queue
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from chronos.matching_engine import TradeResult
from chronos.protocol import Order, OrderType, Side


# ==============================================================================
# Record Types
# ==============================================================================

class AuditRecordType:
    """Standardized record type identifiers for audit log entries."""

    ORDER = "ORDER"
    TRADE = "TRADE"
    EXECUTION = "EXECUTION"
    CANCEL = "CANCEL"
    UNHANDLED = "UNHANDLED"
    SYSTEM = "SYSTEM"


# ==============================================================================
# Audit Record Data Structure
# ==============================================================================

@dataclass
class AuditRecord:
    """Immutable representation of a single auditable event in ChronosMatch.

    Attributes:
        timestamp_ns: Nanosecond arrival or execution timestamp.
        record_type: Categorical identifier (ORDER, TRADE, EXECUTION, etc.).
        order_id: Numeric order identifier.
        symbol_id: Numeric symbol identifier (e.g. 1001 for AAPL).
        side: 1 for BUY, 2 for SELL.
        price: Order price in floating-point dollars.
        quantity: Order quantity in shares/contracts.
        executed_price: Execution price if a trade occurred.
        executed_quantity: Executed volume if a trade occurred.
        latency_ns: Execution latency in nanoseconds.
        details: Optional serialized metadata or JSON string.
        id: Auto-increment primary key assigned by SQLite (None prior to insert).
    """

    timestamp_ns: int
    record_type: str
    order_id: Optional[int] = None
    symbol_id: Optional[int] = None
    side: Optional[int] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    executed_price: Optional[float] = None
    executed_quantity: Optional[int] = None
    latency_ns: Optional[int] = None
    details: Optional[str] = None
    id: Optional[int] = None

    def to_tuple(self) -> Tuple[Any, ...]:
        """Convert to tuple layout matching the SQLite INSERT statement."""
        return (
            self.timestamp_ns,
            self.record_type,
            self.order_id,
            self.symbol_id,
            self.side,
            self.price,
            self.quantity,
            self.executed_price,
            self.executed_quantity,
            self.latency_ns,
            self.details,
        )

    @classmethod
    def from_tuple(cls, row: Tuple[Any, ...]) -> AuditRecord:
        """Construct an AuditRecord from a database query row.

        Expected row layout:
            (id, timestamp_ns, record_type, order_id, symbol_id, side,
             price, quantity, executed_price, executed_quantity, latency_ns, details, created_at)
        """
        return cls(
            id=row[0],
            timestamp_ns=row[1],
            record_type=row[2],
            order_id=row[3],
            symbol_id=row[4],
            side=row[5],
            price=row[6],
            quantity=row[7],
            executed_price=row[8],
            executed_quantity=row[9],
            latency_ns=row[10],
            details=row[11],
        )

    @classmethod
    def from_order(
        cls,
        order: Order,
        timestamp_ns: Optional[int] = None,
        details: Optional[str] = None,
    ) -> AuditRecord:
        """Create an AuditRecord from a chronos.protocol.Order NamedTuple."""
        ts = timestamp_ns if timestamp_ns is not None else order.timestamp_ns
        return cls(
            timestamp_ns=ts,
            record_type=AuditRecordType.ORDER,
            order_id=order.order_id,
            symbol_id=order.symbol_id,
            side=order.side,
            price=order.price,
            quantity=order.quantity,
            details=details,
        )

    @classmethod
    def from_raw_order(
        cls,
        raw_order: Union[Tuple[int, int, float, int, int, int, int], Order],
        details: Optional[str] = None,
    ) -> AuditRecord:
        """Create an AuditRecord from a 7-tuple or Order instance."""
        if isinstance(raw_order, Order):
            return cls.from_order(raw_order, details=details)
        return cls(
            timestamp_ns=int(raw_order[1]),
            record_type=AuditRecordType.ORDER,
            order_id=int(raw_order[0]),
            price=float(raw_order[2]),
            quantity=int(raw_order[3]),
            symbol_id=int(raw_order[4]),
            side=int(raw_order[5]),
            details=details,
        )

    @classmethod
    def from_trade(
        cls,
        trade: TradeResult,
        symbol_id: Optional[int] = None,
        timestamp_ns: Optional[int] = None,
        details: Optional[str] = None,
    ) -> AuditRecord:
        """Create an AuditRecord from a TradeResult instance."""
        ts = timestamp_ns if timestamp_ns is not None else getattr(trade, "entry_timestamp_ns", 0)
        if ts == 0:
            ts = time.time_ns()
        return cls(
            timestamp_ns=ts,
            record_type=AuditRecordType.TRADE,
            order_id=getattr(trade, "buy_order_id", None),
            symbol_id=symbol_id,
            price=getattr(trade, "execution_price", None),
            executed_price=getattr(trade, "execution_price", None),
            executed_quantity=getattr(trade, "executed_quantity", None),
            latency_ns=getattr(trade, "latency_ns", None),
            details=details or f"sell_order_id={getattr(trade, 'sell_order_id', None)}",
        )

    @classmethod
    def from_execution_event(
        cls,
        event: Any,
        details: Optional[str] = None,
    ) -> AuditRecord:
        """Create an AuditRecord from a TradeExecutionEvent instance."""
        exec_price = None
        trades = getattr(event, "trades", [])
        if trades:
            exec_price = trades[0].execution_price
        return cls(
            timestamp_ns=getattr(event, "entry_timestamp_ns", time.time_ns()),
            record_type=AuditRecordType.EXECUTION,
            order_id=getattr(event, "order_id", None),
            symbol_id=getattr(event, "symbol_id", None),
            side=getattr(event, "side", None),
            price=getattr(event, "price", None),
            quantity=getattr(event, "quantity", None),
            executed_price=exec_price,
            executed_quantity=getattr(event, "volume_matched", 0),
            latency_ns=getattr(event, "latency_ns", None),
            details=details or (f"matched={getattr(event, 'matched', False)}" if details is None else details),
        )


# ==============================================================================
# Audit Statistics
# ==============================================================================

@dataclass
class AuditStats:
    """Operational telemetry counters and metrics for the SQLite audit worker."""

    total_records_received: int = 0
    total_records_written: int = 0
    total_batches_written: int = 0
    failed_writes: int = 0
    failed_records: int = 0
    batch_flushes: int = 0
    dropped_records: int = 0
    retried_records_recovered: int = 0
    last_error: Optional[str] = None
    last_flush_timestamp_ns: int = 0
    queue_high_watermark: int = 0

    @property
    def write_success_rate(self) -> float:
        """Return ratio of successfully written records to total attempted writes."""
        total = self.total_records_written + self.failed_records
        return (self.total_records_written / total) if total > 0 else 1.0

    def reset(self) -> None:
        """Reset all metric counters."""
        self.total_records_received = 0
        self.total_records_written = 0
        self.total_batches_written = 0
        self.failed_writes = 0
        self.failed_records = 0
        self.batch_flushes = 0
        self.dropped_records = 0
        self.retried_records_recovered = 0
        self.last_error = None
        self.last_flush_timestamp_ns = 0
        self.queue_high_watermark = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert statistics to a dictionary."""
        d = dataclasses.asdict(self)
        d["write_success_rate"] = self.write_success_rate
        return d


# ==============================================================================
# SQLite Audit Worker
# ==============================================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ns INTEGER NOT NULL,
    record_type TEXT NOT NULL,
    order_id INTEGER,
    symbol_id INTEGER,
    side INTEGER,
    price REAL,
    quantity INTEGER,
    executed_price REAL,
    executed_quantity INTEGER,
    latency_ns INTEGER,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_audit_order_id ON audit_log(order_id);",
    "CREATE INDEX IF NOT EXISTS idx_audit_record_type ON audit_log(record_type);",
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp_ns);",
]

INSERT_SQL = """
INSERT INTO audit_log (
    timestamp_ns, record_type, order_id, symbol_id, side,
    price, quantity, executed_price, executed_quantity, latency_ns, details
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


# Sentinel objects for worker thread synchronization
_FLUSH_SENTINEL = object()
_STOP_SENTINEL = object()


class SQLiteAuditWorker:
    """Asynchronous, batch-oriented SQLite audit worker for ChronosMatch.

    Features:
    - Non-blocking FIFO queue for orders and execution events.
    - Transactional batch insertions using `executemany` with commit safety.
    - Safe rollback on failure with uncommitted records saved to a dead-letter queue.
    - Automatic periodic flushing when batch_size threshold is not met.
    - Multi-stage graceful shutdown: stops accepting records, drains queue, flushes, closes DB.
    - Safe and idempotent if shutdown() is called multiple times.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        batch_size: int = 100,
        flush_interval_s: float = 0.1,
        queue_size: int = 10_000,
        dead_letter_limit: int = 5_000,
        wal_mode: bool = True,
        auto_start: bool = True,
    ) -> None:
        """Initialize the SQLite audit worker.

        Args:
            db_path: Path to the SQLite database file, or ':memory:'.
            batch_size: Number of records per batched database insert.
            flush_interval_s: Maximum time in seconds before flushing a partial batch.
            queue_size: Maximum capacity of the in-memory queue.
            dead_letter_limit: Maximum number of failed records to retain in memory.
            wal_mode: Enable Write-Ahead Logging (WAL) for file-backed databases.
            auto_start: If True, automatically launches the background worker thread.
        """
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive (> 0), got {batch_size}")
        if flush_interval_s <= 0:
            raise ValueError(f"flush_interval_s must be positive (> 0), got {flush_interval_s}")
        if queue_size <= 0:
            raise ValueError(f"queue_size must be positive (> 0), got {queue_size}")

        self.db_path = db_path
        self.batch_size = int(batch_size)
        self.flush_interval_s = float(flush_interval_s)
        self.queue_size = int(queue_size)
        self.dead_letter_limit = int(dead_letter_limit)
        self.wal_mode = bool(wal_mode)

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self.queue_size)
        self._current_batch: List[AuditRecord] = []
        self._dead_letter: List[AuditRecord] = []

        self.stats = AuditStats()

        # Threading and lifecycle synchronization
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._db_lock = threading.RLock()

        self._is_accepting: bool = True
        self._is_shutdown: bool = False
        self._is_running: bool = False

        self._conn: Optional[sqlite3.Connection] = None

        # Initialize database schema
        self._init_db()

        if auto_start:
            self.start()

    @property
    def is_running(self) -> bool:
        """Return True if background worker thread is active."""
        return self._is_running and self._worker_thread is not None and self._worker_thread.is_alive()

    @property
    def is_accepting(self) -> bool:
        """Return True if worker is accepting new audit records."""
        with self._state_lock:
            return self._is_accepting and not self._is_shutdown

    @property
    def is_shutdown(self) -> bool:
        """Return True if worker has completed shutdown."""
        with self._state_lock:
            return self._is_shutdown

    @property
    def pending_queue_size(self) -> int:
        """Return number of records currently queued in memory."""
        return self._queue.qsize()

    @property
    def dead_letter_count(self) -> int:
        """Return count of uncommitted records retained in dead-letter storage."""
        with self._state_lock:
            return len(self._dead_letter)

    # --------------------------------------------------------------------------
    # Database Initialization & Connection
    # --------------------------------------------------------------------------

    def _init_db(self) -> None:
        """Initialize database connection and ensure tables and indexes exist."""
        with self._db_lock:
            if self._conn is None:
                # check_same_thread=False allows worker thread and manual flush from caller
                if self.db_path != ":memory:":
                    db_dir = os.path.dirname(self.db_path)
                    if db_dir and not os.path.exists(db_dir):
                        os.makedirs(db_dir, exist_ok=True)

                self._conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=10.0,
                    isolation_level=None,  # Explicit transaction control
                )

                if self.wal_mode and self.db_path != ":memory:":
                    try:
                        self._conn.execute("PRAGMA journal_mode=WAL;")
                        self._conn.execute("PRAGMA synchronous=NORMAL;")
                    except Exception:
                        pass

            cursor = self._conn.cursor()
            cursor.execute(CREATE_TABLE_SQL)
            for idx_sql in CREATE_INDEXES_SQL:
                cursor.execute(idx_sql)
            self._conn.commit()

    def _close_db(self) -> None:
        """Safely commit and close the database connection."""
        with self._db_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                finally:
                    self._conn = None

    # --------------------------------------------------------------------------
    # Public Ingestion Interface (Non-Blocking)
    # --------------------------------------------------------------------------

    def record(
        self,
        record: Union[AuditRecord, Order, TradeResult, Any, Dict[str, Any], Tuple[Any, ...]],
    ) -> bool:
        """Enqueue an audit record without blocking the order execution path.

        Args:
            record: AuditRecord instance, Order, TradeResult, TradeExecutionEvent,
                    raw order tuple, or dict.

        Returns:
            True if record was accepted into the queue; False if rejected
            (due to shutdown or queue saturation).
        """
        with self._state_lock:
            if not self._is_accepting or self._is_shutdown:
                return False

        # Convert to standardized AuditRecord
        audit_rec = self._normalize_record(record)
        if audit_rec is None:
            return False

        try:
            self._queue.put_nowait(audit_rec)
            self.stats.total_records_received += 1
            curr_q = self._queue.qsize()
            if curr_q > self.stats.queue_high_watermark:
                self.stats.queue_high_watermark = curr_q
            return True
        except queue.Full:
            self.stats.dropped_records += 1
            return False

    def record_batch(self, records: List[Any]) -> int:
        """Enqueue multiple records in sequence.

        Returns:
            Count of records successfully accepted into queue.
        """
        accepted = 0
        for r in records:
            if self.record(r):
                accepted += 1
            else:
                break
        return accepted

    def _normalize_record(self, item: Any) -> Optional[AuditRecord]:
        """Convert arbitrary input types into an AuditRecord."""
        if isinstance(item, AuditRecord):
            return item
        if isinstance(item, Order):
            return AuditRecord.from_order(item)
        if isinstance(item, TradeResult):
            return AuditRecord.from_trade(item)
        if hasattr(item, "entry_timestamp_ns") and hasattr(item, "latency_ns"):
            return AuditRecord.from_execution_event(item)
        if isinstance(item, (tuple, list)) and len(item) >= 7:
            return AuditRecord.from_raw_order(item)
        if isinstance(item, dict):
            return AuditRecord(
                timestamp_ns=item.get("timestamp_ns", time.time_ns()),
                record_type=item.get("record_type", AuditRecordType.SYSTEM),
                order_id=item.get("order_id"),
                symbol_id=item.get("symbol_id"),
                side=item.get("side"),
                price=item.get("price"),
                quantity=item.get("quantity"),
                executed_price=item.get("executed_price"),
                executed_quantity=item.get("executed_quantity"),
                latency_ns=item.get("latency_ns"),
                details=item.get("details"),
            )
        return None

    # --------------------------------------------------------------------------
    # Worker Thread Lifecycle
    # --------------------------------------------------------------------------

    def start(self) -> None:
        """Start the background audit worker thread (idempotent)."""
        with self._state_lock:
            if self._is_shutdown:
                raise RuntimeError("Cannot start an AuditWorker that has already been shut down.")
            if self._is_running and self._worker_thread is not None and self._worker_thread.is_alive():
                return

            self._stop_event.clear()
            self._is_running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="ChronosAuditWorker",
                daemon=True,
            )
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Background worker thread draining queue and writing batches to SQLite."""
        while not self._stop_event.is_set():
            try:
                # Wait up to flush_interval_s for next record
                item = self._queue.get(timeout=self.flush_interval_s)
            except queue.Empty:
                # Interval elapsed: flush partial batch if any
                if self._current_batch:
                    self._write_batch_to_db(self._current_batch)
                    self._current_batch.clear()
                continue

            # Check for sentinels
            if isinstance(item, tuple) and len(item) == 2 and item[0] is _FLUSH_SENTINEL:
                if self._current_batch:
                    self._write_batch_to_db(self._current_batch)
                    self._current_batch.clear()
                self._queue.task_done()
                item[1].set()
                continue

            if item is _STOP_SENTINEL:
                self._queue.task_done()
                break

            self._current_batch.append(item)
            self._queue.task_done()

            # Drain available items up to batch_size in a non-blocking loop
            while len(self._current_batch) < self.batch_size:
                try:
                    next_item = self._queue.get_nowait()
                except queue.Empty:
                    break

                if isinstance(next_item, tuple) and len(next_item) == 2 and next_item[0] is _FLUSH_SENTINEL:
                    if self._current_batch:
                        self._write_batch_to_db(self._current_batch)
                        self._current_batch.clear()
                    self._queue.task_done()
                    next_item[1].set()
                    break

                if next_item is _STOP_SENTINEL:
                    self._queue.task_done()
                    self._stop_event.set()
                    break

                self._current_batch.append(next_item)
                self._queue.task_done()

            if len(self._current_batch) >= self.batch_size:
                self._write_batch_to_db(self._current_batch)
                self._current_batch.clear()

        # Draining phase when stopping: process all remaining items
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                self._queue.task_done()
                if isinstance(item, tuple) and len(item) == 2 and item[0] is _FLUSH_SENTINEL:
                    if self._current_batch:
                        self._write_batch_to_db(self._current_batch)
                        self._current_batch.clear()
                    item[1].set()
                elif item is not _STOP_SENTINEL:
                    self._current_batch.append(item)
                    if len(self._current_batch) >= self.batch_size:
                        self._write_batch_to_db(self._current_batch)
                        self._current_batch.clear()
            except queue.Empty:
                break

        if self._current_batch:
            self._write_batch_to_db(self._current_batch)
            self._current_batch.clear()

    # --------------------------------------------------------------------------
    # Database Batch Writing, Transactions & Error Handling
    # --------------------------------------------------------------------------

    def _write_batch_to_db(self, batch: List[AuditRecord]) -> bool:
        """Write a batch of records inside a single SQLite transaction with rollback safety.

        Args:
            batch: List of AuditRecord instances to persist.

        Returns:
            True if transaction succeeded; False if an error occurred.
        """
        if not batch:
            return True

        with self._db_lock:
            if self._conn is None:
                try:
                    self._init_db()
                except Exception as e:
                    self._handle_write_failure(batch, e)
                    return False

            rows = [rec.to_tuple() for rec in batch]
            try:
                cursor = self._conn.cursor()
                cursor.execute("BEGIN TRANSACTION;")
                cursor.executemany(INSERT_SQL, rows)
                self._conn.commit()

                # Update success metrics
                self.stats.total_records_written += len(batch)
                self.stats.total_batches_written += 1
                self.stats.batch_flushes += 1
                self.stats.last_flush_timestamp_ns = time.time_ns()
                return True

            except sqlite3.Error as e:
                # Safe transaction rollback on failure
                try:
                    if self._conn is not None:
                        self._conn.rollback()
                except Exception:
                    pass
                self._handle_write_failure(batch, e)
                return False
            except Exception as e:
                try:
                    if self._conn is not None:
                        self._conn.rollback()
                except Exception:
                    pass
                self._handle_write_failure(batch, e)
                return False

    def _handle_write_failure(self, batch: List[AuditRecord], error: Exception) -> None:
        """Handle batch write error: update failure counters and retain unwritten records."""
        self.stats.failed_writes += 1
        self.stats.failed_records += len(batch)
        self.stats.last_error = str(error)

        # Do not silently lose audit records: save to dead-letter queue
        with self._state_lock:
            for rec in batch:
                if len(self._dead_letter) < self.dead_letter_limit:
                    self._dead_letter.append(rec)
                else:
                    self.stats.dropped_records += 1

    # --------------------------------------------------------------------------
    # Dead-Letter Queue Inspection & Recovery
    # --------------------------------------------------------------------------

    def get_dead_letter_records(self) -> List[AuditRecord]:
        """Return a copy of all uncommitted records currently retained in dead-letter queue."""
        with self._state_lock:
            return list(self._dead_letter)

    def clear_dead_letter(self) -> None:
        """Clear dead-letter records."""
        with self._state_lock:
            self._dead_letter.clear()

    def retry_dead_letter(self) -> int:
        """Re-attempt writing all dead-letter records to the database.

        Returns:
            Count of successfully recovered records.
        """
        with self._state_lock:
            if not self._dead_letter:
                return 0
            to_retry = list(self._dead_letter)
            self._dead_letter.clear()

        # Write in chunks of batch_size
        recovered = 0
        for i in range(0, len(to_retry), self.batch_size):
            chunk = to_retry[i : i + self.batch_size]
            success = self._write_batch_to_db(chunk)
            if success:
                recovered += len(chunk)
                self.stats.retried_records_recovered += len(chunk)
            else:
                # Re-append remaining to dead letter
                with self._state_lock:
                    remaining = to_retry[i:]
                    for rec in remaining:
                        if len(self._dead_letter) < self.dead_letter_limit:
                            self._dead_letter.append(rec)
                break

        return recovered

    # --------------------------------------------------------------------------
    # Explicit Flush & Shutdown
    # --------------------------------------------------------------------------

    def flush(self, timeout: float = 5.0) -> None:
        """Synchronously flush all queued records and pending batch into the database.

        Blocks until all currently queued items are processed and committed.
        """
        if self.is_running:
            evt = threading.Event()
            try:
                self._queue.put((_FLUSH_SENTINEL, evt), timeout=timeout)
                evt.wait(timeout=timeout)
            except (queue.Full, Exception):
                pass
        else:
            # Worker thread is not running: drain directly
            drained: List[AuditRecord] = []
            while not self._queue.empty():
                try:
                    item = self._queue.get_nowait()
                    self._queue.task_done()
                    if isinstance(item, tuple) and len(item) == 2 and item[0] is _FLUSH_SENTINEL:
                        item[1].set()
                    elif item is not _STOP_SENTINEL:
                        drained.append(item)
                except queue.Empty:
                    break

            if drained or self._current_batch:
                all_records = self._current_batch + drained
                self._current_batch = []
                for i in range(0, len(all_records), self.batch_size):
                    self._write_batch_to_db(all_records[i : i + self.batch_size])

    def shutdown(self, timeout: float = 5.0) -> None:
        """Gracefully shut down the audit worker.

        Guarantees:
        1. Stops accepting new records immediately.
        2. Drains all queued records.
        3. Flushes remaining records to SQLite with safe commit.
        4. Terminates background thread cleanly (no leaks).
        5. Closes the database connection.
        6. Is completely safe and idempotent if called multiple times.
        """
        with self._state_lock:
            # Step 1: Stop accepting new records
            self._is_accepting = False
            if self._is_shutdown:
                # Already shut down: return safely without error
                return

        # Step 2: Signal background thread to stop via sentinel and event
        if self._worker_thread is not None and self._worker_thread.is_alive():
            try:
                self._queue.put(_STOP_SENTINEL, timeout=1.0)
            except Exception:
                self._stop_event.set()

            # Step 3: Wait for worker thread to finish draining and writing
            self._worker_thread.join(timeout=timeout)
        self._worker_thread = None

        # Step 4: Ensure any remaining queued or pending items are flushed
        self.flush(timeout=timeout)

        # Step 5: Close database connection
        self._close_db()

        with self._state_lock:
            self._is_running = False
            self._is_shutdown = True

    def close(self) -> None:
        """Alias for shutdown()."""
        self.shutdown()

    # --------------------------------------------------------------------------
    # Query & Inspection Helpers
    # --------------------------------------------------------------------------

    def get_record_count(self) -> int:
        """Return the total number of records currently committed in the database."""
        with self._db_lock:
            if self._conn is None:
                self._init_db()
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM audit_log;")
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def query_records(
        self,
        record_type: Optional[str] = None,
        order_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[AuditRecord]:
        """Query committed audit records by record_type or order_id.

        Args:
            record_type: Filter by record_type (e.g. ORDER, TRADE).
            order_id: Filter by order_id.
            limit: Maximum number of rows to return.

        Returns:
            List of matching AuditRecord instances.
        """
        with self._db_lock:
            if self._conn is None:
                self._init_db()
            cursor = self._conn.cursor()
            query = "SELECT id, timestamp_ns, record_type, order_id, symbol_id, side, price, quantity, executed_price, executed_quantity, latency_ns, details, created_at FROM audit_log"
            clauses = []
            params = []
            if record_type is not None:
                clauses.append("record_type = ?")
                params.append(record_type)
            if order_id is not None:
                clauses.append("order_id = ?")
                params.append(order_id)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += f" ORDER BY id ASC LIMIT {int(limit)};"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [AuditRecord.from_tuple(r) for r in rows]

    # --------------------------------------------------------------------------
    # Context Manager
    # --------------------------------------------------------------------------

    def __enter__(self) -> SQLiteAuditWorker:
        if not self.is_running and not self._is_shutdown:
            self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown()


# Standard alias
AuditWorker = SQLiteAuditWorker
