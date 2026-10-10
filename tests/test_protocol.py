"""Unit tests for ChronosMatch Binary Order Protocol."""

import struct
import time
import pytest
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


def test_order_struct_size_and_alignment():
    """Verify struct is exactly 32 bytes for cache alignment."""
    assert ORDER_SIZE == 32
    assert ORDER_STRUCT.size == 32


def test_order_packing_unpacking_roundtrip():
    """Verify order serialization fidelity."""
    order_id = 12345678901234
    ts_ns = time.time_ns()
    price = 225.50
    qty = 500
    sym_id = SYMBOLS["AAPL"]
    side = Side.BUY
    order_type = OrderType.LIMIT

    order = Order(
        order_id=order_id,
        timestamp_ns=ts_ns,
        price=price,
        quantity=qty,
        symbol_id=sym_id,
        side=side,
        order_type=order_type,
    )

    # Pack to bytes
    raw_bytes = order.pack()
    assert len(raw_bytes) == 32

    # Unpack from bytes
    unpacked = Order.unpack(raw_bytes)
    assert unpacked.order_id == order_id
    assert unpacked.timestamp_ns == ts_ns
    assert abs(unpacked.price - price) < 1e-6
    assert unpacked.quantity == qty
    assert unpacked.symbol_id == sym_id
    assert unpacked.side == Side.BUY
    assert unpacked.order_type == OrderType.LIMIT
    assert unpacked.symbol_str == "AAPL"
    assert unpacked.side_str == "BUY"
    assert unpacked.order_type_str == "LIMIT"


def test_zero_copy_pack_into_and_unpack_from():
    """Verify zero-copy pack_into using bytearray and memoryview."""
    buf = bytearray(64)
    view = memoryview(buf)

    order_id = 999
    ts_ns = 1700000000000000000
    price = 128.45
    qty = 200
    sym_id = SYMBOLS["NVDA"]
    side = Side.SELL
    order_type = OrderType.MARKET

    # Pack at offset 32
    pack_order_into(view, 32, order_id, ts_ns, price, qty, sym_id, side, order_type)

    # Direct raw unpack
    raw = unpack_order_raw(view, 32)
    assert raw[0] == order_id
    assert raw[1] == ts_ns
    assert abs(raw[2] - price) < 1e-6
    assert raw[3] == qty
    assert raw[4] == sym_id
    assert raw[5] == side
    assert raw[6] == order_type

    # Unpack to Order
    ord_obj = Order.unpack_from(view, 32)
    assert ord_obj.symbol_str == "NVDA"
    assert ord_obj.side_str == "SELL"
    assert ord_obj.order_type_str == "MARKET"
