"""ChronosMatch Zero-Copy SPSC Memory-Mapped Ring Buffer.

High-performance Single Producer Single Consumer (SPSC) lock-free ring buffer
implemented over Python's mmap and memoryview modules.

Architectural Highlights:
- Page-Aligned (4096 bytes) data storage segment.
- 64-byte Cache-Line Separation: Write Head and Read Tail are stored at separate
  64-byte offsets (64 and 128) to eliminate CPU false sharing between producer
  and consumer processes.
- Power-of-2 Capacity: Slot indexing is computed via bitwise mask `seq & (capacity - 1)`
  rather than slow integer division / modulo arithmetic.
- Zero-Copy Buffer Access: Uses `memoryview` and `struct.pack_into`/`unpack_from`
  directly targeting RAM addresses, avoiding Python byte allocations and GC pauses.
"""

from __future__ import annotations
import math
import mmap
import os
import struct
import time
from typing import Generator, List, Optional, Tuple

from chronos.protocol import ORDER_SIZE, ORDER_STRUCT, Order, pack_order_into, unpack_order_raw

# Header Layout Offsets (in bytes)
MAGIC_OFFSET = 0         # 8 bytes: b"CHRONOS1"
VERSION_OFFSET = 8       # 4 bytes: uint32
SLOT_SIZE_OFFSET = 12    # 4 bytes: uint32
CAPACITY_OFFSET = 16     # 8 bytes: uint64
RESERVED_OFFSET = 24     # 40 bytes padding

WRITE_HEAD_OFFSET = 64   # 8 bytes: uint64 (Cache-line 1)
READ_TAIL_OFFSET = 128   # 8 bytes: uint64 (Cache-line 2)

METRICS_WRITTEN_OFFSET = 192  # 8 bytes: uint64
METRICS_READ_OFFSET = 200     # 8 bytes: uint64
METRICS_DROPPED_OFFSET = 208  # 8 bytes: uint64

HEADER_PAGE_SIZE = 4096  # Slots start at 4KB page boundary
MAGIC_BYTES = b"CHRONOS1"
HEADER_VERSION = 1

# Struct formats for atomic header updates
_U64 = struct.Struct("<Q")
_U32 = struct.Struct("<I")


class RingBufferFullError(Exception):
    """Raised when attempting to write to a saturated ring buffer in strict mode."""
    pass


class MmapRingBuffer:
    """Zero-copy memory-mapped SPSC ring buffer for inter-process order book streaming."""

    def __init__(
        self,
        filepath: str,
        capacity: int = 262_144,  # 2^18 = 262,144 orders (~8.4 MB)
        slot_size: int = ORDER_SIZE,
        create: bool = False,
    ):
        """Initialize or connect to a memory-mapped ring buffer.

        Args:
            filepath: Path to the backing file on disk.
            capacity: Number of slots (must be a power of 2). Ignored if attaching.
            slot_size: Size in bytes of each slot (default 32 bytes). Ignored if attaching.
            create: True to initialize/truncate the file and header; False to attach.
        """
        self.filepath = os.path.abspath(filepath)
        self.is_owner = create
        self._is_closed = False

        if create:
            # Ensure capacity is a power of 2
            if capacity <= 0 or (capacity & (capacity - 1)) != 0:
                # Round up to next power of 2
                capacity = 1 << math.ceil(math.log2(max(capacity, 16)))

            self.capacity = capacity
            self.slot_size = slot_size
            self.mask = self.capacity - 1
            self.total_size = HEADER_PAGE_SIZE + (self.capacity * self.slot_size)

            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            self._file = open(self.filepath, "w+b")
            self._file.truncate(self.total_size)
            self._file.flush()

            self._mmap = mmap.mmap(self._file.fileno(), self.total_size, access=mmap.ACCESS_WRITE)
            self._view = memoryview(self._mmap)

            # Initialize Header
            self._init_header()
        else:
            if not os.path.exists(self.filepath):
                raise FileNotFoundError(f"Ring buffer file not found: {self.filepath}")

            self._file = open(self.filepath, "r+b")
            # First read header to verify size
            self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_WRITE)
            self._view = memoryview(self._mmap)

            # Validate header
            magic = bytes(self._view[MAGIC_OFFSET : MAGIC_OFFSET + 8])
            if magic != MAGIC_BYTES:
                raise ValueError(f"Invalid ring buffer magic: {magic} (expected {MAGIC_BYTES})")

            version = _U32.unpack_from(self._view, VERSION_OFFSET)[0]
            if version != HEADER_VERSION:
                raise ValueError(f"Unsupported ring buffer version: {version}")

            self.slot_size = _U32.unpack_from(self._view, SLOT_SIZE_OFFSET)[0]
            self.capacity = _U64.unpack_from(self._view, CAPACITY_OFFSET)[0]
            self.mask = self.capacity - 1
            self.total_size = len(self._mmap)

        self._data_offset = HEADER_PAGE_SIZE

    def _init_header(self) -> None:
        """Initialize the header in shared memory."""
        # Magic bytes
        self._view[MAGIC_OFFSET : MAGIC_OFFSET + 8] = MAGIC_BYTES
        # Version
        _U32.pack_into(self._view, VERSION_OFFSET, HEADER_VERSION)
        # Slot size
        _U32.pack_into(self._view, SLOT_SIZE_OFFSET, self.slot_size)
        # Capacity
        _U64.pack_into(self._view, CAPACITY_OFFSET, self.capacity)
        # Write Head & Read Tail
        _U64.pack_into(self._view, WRITE_HEAD_OFFSET, 0)
        _U64.pack_into(self._view, READ_TAIL_OFFSET, 0)
        # Metrics
        _U64.pack_into(self._view, METRICS_WRITTEN_OFFSET, 0)
        _U64.pack_into(self._view, METRICS_READ_OFFSET, 0)
        _U64.pack_into(self._view, METRICS_DROPPED_OFFSET, 0)

    # --------------------------------------------------------------------------
    # Sequence Accessors (Volatile / Fast Struct Unpack)
    # --------------------------------------------------------------------------
    @property
    def write_head(self) -> int:
        return _U64.unpack_from(self._view, WRITE_HEAD_OFFSET)[0]

    @write_head.setter
    def write_head(self, val: int) -> None:
        _U64.pack_into(self._view, WRITE_HEAD_OFFSET, val)

    @property
    def read_tail(self) -> int:
        return _U64.unpack_from(self._view, READ_TAIL_OFFSET)[0]

    @read_tail.setter
    def read_tail(self, val: int) -> None:
        _U64.pack_into(self._view, READ_TAIL_OFFSET, val)

    @property
    def messages_written(self) -> int:
        return _U64.unpack_from(self._view, METRICS_WRITTEN_OFFSET)[0]

    @property
    def messages_read(self) -> int:
        return _U64.unpack_from(self._view, METRICS_READ_OFFSET)[0]

    @property
    def messages_dropped(self) -> int:
        return _U64.unpack_from(self._view, METRICS_DROPPED_OFFSET)[0]

    def available_to_read(self) -> int:
        """Returns the number of unread slots currently in the buffer."""
        return self.write_head - self.read_tail

    def available_to_write(self) -> int:
        """Returns the number of free slots currently in the buffer."""
        return self.capacity - (self.write_head - self.read_tail)

    def is_empty(self) -> bool:
        return self.write_head == self.read_tail

    def is_full(self) -> bool:
        return (self.write_head - self.read_tail) >= self.capacity

    # --------------------------------------------------------------------------
    # Producer API (Write)
    # --------------------------------------------------------------------------
    def write(
        self,
        order_id: int,
        timestamp_ns: int,
        price: float,
        quantity: int,
        symbol_id: int,
        side: int,
        order_type: int = 1,
        overwrite_on_full: bool = False,
    ) -> bool:
        """Write a single order directly into the ring buffer.

        Zero-copy serialization using `pack_into` straight into the mmap buffer.

        Args:
            overwrite_on_full: If True, overwrite oldest entry when full and increment dropped count.
                               If False, returns False when full.
        Returns:
            True if written, False if full (when overwrite_on_full is False).
        """
        head = self.write_head
        tail = self.read_tail

        if (head - tail) >= self.capacity:
            if not overwrite_on_full:
                return False
            # Advance tail to discard oldest slot
            self.read_tail = tail + 1
            dropped = _U64.unpack_from(self._view, METRICS_DROPPED_OFFSET)[0]
            _U64.pack_into(self._view, METRICS_DROPPED_OFFSET, dropped + 1)

        offset = self._data_offset + ((head & self.mask) * self.slot_size)
        pack_order_into(
            self._view,
            offset,
            order_id,
            timestamp_ns,
            price,
            quantity,
            symbol_id,
            side,
            order_type,
        )

        # Update write head and written metric
        self.write_head = head + 1
        return True

    def write_order(self, order: Order, overwrite_on_full: bool = False) -> bool:
        """Convenience method to write an Order tuple/instance."""
        return self.write(
            order.order_id,
            order.timestamp_ns,
            order.price,
            order.quantity,
            order.symbol_id,
            order.side,
            order.order_type,
            overwrite_on_full=overwrite_on_full,
        )

    def write_batch(
        self,
        orders: List[Tuple[int, int, float, int, int, int, int]],
        overwrite_on_full: bool = False,
    ) -> int:
        """Write a batch of raw order tuples in a tight loop.

        Crucial for high-throughput market firehoses: batches amortize head/tail
        sync overhead.

        Returns:
            Number of orders successfully written.
        """
        batch_len = len(orders)
        if batch_len == 0:
            return 0

        head = self.write_head
        tail = self.read_tail
        available = self.capacity - (head - tail)

        if available < batch_len:
            if not overwrite_on_full:
                batch_len = max(0, available)
                if batch_len == 0:
                    return 0
            else:
                # Advance tail to accommodate batch
                overflow = batch_len - available
                self.read_tail = tail + overflow
                dropped = _U64.unpack_from(self._view, METRICS_DROPPED_OFFSET)[0]
                _U64.pack_into(self._view, METRICS_DROPPED_OFFSET, dropped + overflow)

        mask = self.mask
        slot_size = self.slot_size
        data_offset = self._data_offset
        view = self._view

        for i in range(batch_len):
            order = orders[i]
            offset = data_offset + (((head + i) & mask) * slot_size)
            pack_order_into(
                view,
                offset,
                order[0],  # order_id
                order[1],  # timestamp_ns
                order[2],  # price
                order[3],  # quantity
                order[4],  # symbol_id
                order[5],  # side
                order[6],  # order_type
            )

        self.write_head = head + batch_len
        return batch_len

    # --------------------------------------------------------------------------
    # Consumer API (Read)
    # --------------------------------------------------------------------------
    def read_raw(self) -> Optional[Tuple[int, int, float, int, int, int, int]]:
        """Read a single order as raw tuple (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type).

        Returns None if buffer is empty.
        """
        tail = self.read_tail
        head = self.write_head

        if tail >= head:
            return None

        offset = self._data_offset + ((tail & self.mask) * self.slot_size)
        raw_order = unpack_order_raw(self._view, offset)
        self.read_tail = tail + 1
        return raw_order

    def read_order(self) -> Optional[Order]:
        """Read a single order deserialized as an Order namedtuple.

        Returns None if buffer is empty.
        """
        raw = self.read_raw()
        if raw is None:
            return None
        return Order(*raw)

    def read_batch_raw(
        self, max_items: int = 1000
    ) -> List[Tuple[int, int, float, int, int, int, int]]:
        """Read up to `max_items` raw orders in a batch for high throughput.

        Returns:
            List of raw order tuples.
        """
        tail = self.read_tail
        head = self.write_head
        count = min(max_items, max(0, head - tail))
        if count <= 0:
            return []

        results = []
        mask = self.mask
        slot_size = self.slot_size
        data_offset = self._data_offset
        view = self._view

        for i in range(count):
            offset = data_offset + (((tail + i) & mask) * slot_size)
            results.append(unpack_order_raw(view, offset))

        self.read_tail = tail + count
        return results

    def read_batch_orders(self, max_items: int = 1000) -> List[Order]:
        """Read up to `max_items` orders as Order instances."""
        raws = self.read_batch_raw(max_items)
        return [Order(*r) for r in raws]

    # --------------------------------------------------------------------------
    # Resource Lifecycle
    # --------------------------------------------------------------------------
    def flush(self) -> None:
        """Flush memory-mapped changes to disk."""
        if not self._is_closed and hasattr(self, "_mmap"):
            self._mmap.flush()

    def close(self) -> None:
        """Release memory map and file handles."""
        if self._is_closed:
            return
        self._is_closed = True

        if hasattr(self, "_view"):
            self._view.release()
        if hasattr(self, "_mmap"):
            self._mmap.close()
        if hasattr(self, "_file"):
            self._file.close()

    def unlink(self) -> None:
        """Close and delete the backing file."""
        self.close()
        if os.path.exists(self.filepath):
            try:
                os.remove(self.filepath)
            except OSError:
                pass

    def __enter__(self) -> MmapRingBuffer:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
