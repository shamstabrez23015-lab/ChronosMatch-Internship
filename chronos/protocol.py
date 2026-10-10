"""ChronosMatch Protocol: Binary Order Specification for Zero-Copy IPC.

Defines the binary layout, constants, and packing/unpacking routines for
high-frequency order tick messages. Uses pre-compiled struct definitions
and memoryview / pack_into for zero-copy byte serialization.
"""

from __future__ import annotations
import enum
import struct
import time
from typing import NamedTuple, Tuple

# ==============================================================================
# Binary Struct Specification (32 Bytes Cache-Aligned)
# ==============================================================================
# Layout:
# Field        | Type            | Size    | Offset
# --------------------------------------------------
# order_id     | uint64 (Q)      | 8 bytes | 0
# timestamp_ns | uint64 (Q)      | 8 bytes | 8
# price        | double (d)      | 8 bytes | 16
# quantity     | uint32 (I)      | 4 bytes | 24
# symbol_id    | uint16 (H)      | 2 bytes | 28
# side         | uint8  (B)      | 1 byte  | 30 (1=BUY, 2=SELL)
# order_type   | uint8  (B)      | 1 byte  | 31 (1=LIMIT, 2=MARKET, 3=CANCEL)
# --------------------------------------------------
# Total: 32 bytes (Half cache-line, power of 2 aligned)

ORDER_STRUCT_FORMAT = "<QQdIHBB"
ORDER_STRUCT = struct.Struct(ORDER_STRUCT_FORMAT)
ORDER_SIZE = ORDER_STRUCT.size
assert ORDER_SIZE == 32, f"ORDER_SIZE must be exactly 32 bytes, got {ORDER_SIZE}"


class Side(enum.IntEnum):
    BUY = 1
    SELL = 2

    @classmethod
    def from_str(cls, s: str) -> Side:
        s = s.upper()
        if s in ("B", "BUY"):
            return cls.BUY
        elif s in ("S", "SELL"):
            return cls.SELL
        raise ValueError(f"Unknown side: {s}")


class OrderType(enum.IntEnum):
    LIMIT = 1
    MARKET = 2
    CANCEL = 3


# Standard ticker symbol registry mapping string symbols to 16-bit IDs
SYMBOLS = {
    "AAPL": 1001,
    "NVDA": 1002,
    "TSLA": 1003,
    "MSFT": 1004,
    "AMZN": 1005,
    "GOOGL": 1006,
    "META": 1007,
    "AMD": 1008,
}
SYMBOL_ID_TO_TICKER = {v: k for k, v in SYMBOLS.items()}


class Order(NamedTuple):
    order_id: int
    timestamp_ns: int
    price: float
    quantity: int
    symbol_id: int
    side: int
    order_type: int

    @property
    def symbol_str(self) -> str:
        return SYMBOL_ID_TO_TICKER.get(self.symbol_id, f"ID_{self.symbol_id}")

    @property
    def side_str(self) -> str:
        return "BUY" if self.side == Side.BUY else "SELL"

    @property
    def order_type_str(self) -> str:
        if self.order_type == OrderType.LIMIT:
            return "LIMIT"
        elif self.order_type == OrderType.MARKET:
            return "MARKET"
        elif self.order_type == OrderType.CANCEL:
            return "CANCEL"
        return f"TYPE_{self.order_type}"

    def pack(self) -> bytes:
        """Pack order into raw 32 bytes."""
        return ORDER_STRUCT.pack(
            self.order_id,
            self.timestamp_ns,
            self.price,
            self.quantity,
            self.symbol_id,
            self.side,
            self.order_type,
        )

    def pack_into(self, buffer: memoryview | bytearray, offset: int = 0) -> None:
        """Zero-copy pack into an existing memory buffer."""
        ORDER_STRUCT.pack_into(
            buffer,
            offset,
            self.order_id,
            self.timestamp_ns,
            self.price,
            self.quantity,
            self.symbol_id,
            self.side,
            self.order_type,
        )

    @classmethod
    def unpack(cls, buffer: bytes) -> Order:
        """Unpack an Order from raw bytes."""
        return cls(*ORDER_STRUCT.unpack(buffer))

    @classmethod
    def unpack_from(cls, buffer: memoryview | bytes | bytearray, offset: int = 0) -> Order:
        """Zero-copy unpack from an existing memory buffer."""
        return cls(*ORDER_STRUCT.unpack_from(buffer, offset))


def pack_order_into(
    buffer: memoryview | bytearray,
    offset: int,
    order_id: int,
    timestamp_ns: int,
    price: float,
    quantity: int,
    symbol_id: int,
    side: int,
    order_type: int,
) -> None:
    """Direct fast pack_into without instantiating an intermediate Order tuple."""
    ORDER_STRUCT.pack_into(
        buffer,
        offset,
        order_id,
        timestamp_ns,
        price,
        quantity,
        symbol_id,
        side,
        order_type,
    )


def unpack_order_raw(
    buffer: memoryview | bytes | bytearray, offset: int = 0
) -> Tuple[int, int, float, int, int, int, int]:
    """Direct unpack returning a raw tuple without object instantiation overhead."""
    return ORDER_STRUCT.unpack_from(buffer, offset)
