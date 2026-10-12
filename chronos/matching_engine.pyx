# cython: language_level=3
"""ChronosMatch Cython Matching Engine Foundation & Limit Order Book.

Provides a C-level order representation and Limit Order Book data structures
storing BUY (bid) and SELL (ask) orders separately.

Week 2, Day 2:
- BUY and SELL order storage (bids and asks).
- Deterministic arrival sequence preservation.
- Full inspection and count APIs for bids and asks.
- Safe order validation preventing corrupt book states.
- Clean order-book initialization and reset.

Price Representation
--------------------
The Week 1 binary protocol stores prices as ``double`` (64-bit IEEE 754
float). Floating-point equality/comparison is unsafe for matching, so this
module converts prices to **integer cent ticks**::

    price_cents = <long long>round(price_float * 100.0)

All downstream matching will operate on ``price_cents`` only.

Side Representation
-------------------
Reuses the Week 1 ``Side`` convention:

* ``1`` → BUY
* ``2`` → SELL
"""

# ---------------------------------------------------------------------------
# C-level and Python-level constants
# ---------------------------------------------------------------------------
DEF _SIDE_BUY  = 1
DEF _SIDE_SELL = 2

SIDE_BUY = 1
SIDE_SELL = 2


# ---------------------------------------------------------------------------
# Helper: callable list wrapper for dual property/method access
# ---------------------------------------------------------------------------
class _OrderListView(list):
    """List view wrapper supporting both list operations and callable syntax."""

    def __call__(self):
        return self


# ---------------------------------------------------------------------------
# C-level order struct (Cython extension type)
# ---------------------------------------------------------------------------
cdef class COrder:
    """Statically typed order representation for the matching engine.

    All fields are C-level typed for cache-friendly, branch-predictable
    processing inside the future hot-path.

    Attributes
    ----------
    order_id : unsigned long long
        Unique order identifier (uint64).
    side : int
        ``1`` = BUY, ``2`` = SELL (mirrors ``chronos.protocol.Side``).
    price_cents : long long
        Price expressed as **integer cents** (1 tick = $0.01).
        Converted from the protocol's ``double`` price via
        ``round(price * 100)``.
    quantity : unsigned int
        Number of shares/contracts (must be > 0).
    timestamp_ns : unsigned long long
        Arrival timestamp in nanoseconds (or sequence number).
    sequence_num : unsigned long long
        Deterministic arrival sequence assigned by the matching engine.
    """

    cdef public unsigned long long order_id
    cdef public int side
    cdef public long long price_cents
    cdef public unsigned int quantity
    cdef public unsigned long long timestamp_ns
    cdef public unsigned long long sequence_num

    def __init__(
        self,
        unsigned long long order_id,
        int side,
        long long price_cents,
        unsigned int quantity,
        unsigned long long timestamp_ns,
        unsigned long long sequence_num=0,
    ):
        self.order_id = order_id
        self.side = side
        self.price_cents = price_cents
        self.quantity = quantity
        self.timestamp_ns = timestamp_ns
        self.sequence_num = sequence_num

    @property
    def price(self):
        """Return the dollar price as a float."""
        return self.price_cents / 100.0

    def __repr__(self):
        side_str = "BUY" if self.side == _SIDE_BUY else "SELL"
        return (
            f"COrder(id={self.order_id}, side={side_str}, "
            f"price_cents={self.price_cents}, qty={self.quantity}, "
            f"ts={self.timestamp_ns})"
        )

    def as_dict(self):
        """Return a plain-Python dictionary snapshot of the order."""
        return {
            "order_id": self.order_id,
            "side": self.side,
            "price_cents": self.price_cents,
            "quantity": self.quantity,
            "timestamp_ns": self.timestamp_ns,
        }


# ---------------------------------------------------------------------------
# Helper: convert protocol float price → integer cents
# ---------------------------------------------------------------------------
cpdef long long price_to_cents(double price):
    """Convert a floating-point dollar price to integer cents.

    Parameters
    ----------
    price : double
        Dollar price (e.g. ``225.50``).

    Returns
    -------
    long long
        Price in cents (e.g. ``22550``).

    Examples
    --------
    >>> price_to_cents(225.50)
    22550
    """
    return <long long>round(price * 100.0)


# ---------------------------------------------------------------------------
# Limit Order Book & Matching Engine
# ---------------------------------------------------------------------------
cdef class MatchingEngine:
    """Cython Matching Engine and Limit Order Book (Week 2, Day 2).

    Capabilities
    ------------
    * Initialise an empty engine and order book.
    * Separate storage for BUY orders (bids) and SELL orders (asks).
    * Deterministic arrival sequence preservation.
    * Accept and validate orders.
    * Full inspection and order-counting for bids and asks.
    * Clear and re-initialize order book state.

    Not yet implemented (scheduled for later working days)
    ------------------------------------------------------
    * Price-time priority sorting.
    * Trade execution / partial fills.
    * Ring-buffer zero-copy IPC integration.
    """

    cdef public unsigned long long _order_count
    cdef public bint _ready
    cdef list _bids
    cdef list _asks
    cdef public unsigned long long _sequence_counter

    def __init__(self):
        """Initialise an empty matching engine with an empty order book."""
        self._order_count = 0
        self._ready = True
        self._bids = []
        self._asks = []
        self._sequence_counter = 0

    # ---- status & readiness -----------------------------------------------

    cpdef bint is_ready(self):
        """Return ``True`` if the engine is initialised and ready."""
        return self._ready

    cpdef unsigned long long order_count(self):
        """Return the total number of orders accepted so far."""
        return self._order_count

    cpdef dict status(self):
        """Return a snapshot of the engine state."""
        return {
            "ready": self._ready,
            "order_count": self._order_count,
        }

    # ---- order book initialization / reset --------------------------------

    cpdef void clear(self):
        """Reset the order book to an empty state."""
        self._bids = []
        self._asks = []
        self._order_count = 0
        self._sequence_counter = 0
        self._ready = True

    cpdef void reset(self):
        """Alias for ``clear()``."""
        self.clear()

    cpdef void init_order_book(self):
        """Initialise an empty order book."""
        self.clear()

    # ---- order counts -----------------------------------------------------

    cpdef unsigned long long bid_count(self):
        """Return the number of stored BUY orders (bids)."""
        return len(self._bids)

    cpdef unsigned long long ask_count(self):
        """Return the number of stored SELL orders (asks)."""
        return len(self._asks)

    cpdef unsigned long long get_bid_count(self):
        """Return the number of stored BUY orders (bids)."""
        return len(self._bids)

    cpdef unsigned long long get_ask_count(self):
        """Return the number of stored SELL orders (asks)."""
        return len(self._asks)

    # ---- order retrieval / inspection -------------------------------------

    cpdef list get_bids(self):
        """Return a list copy of currently stored BUY orders in arrival order."""
        return list(self._bids)

    cpdef list get_asks(self):
        """Return a list copy of currently stored SELL orders in arrival order."""
        return list(self._asks)

    cpdef list get_buy_orders(self):
        """Alias for ``get_bids()``."""
        return list(self._bids)

    cpdef list get_sell_orders(self):
        """Alias for ``get_asks()``."""
        return list(self._asks)

    property bids:
        def __get__(self):
            return _OrderListView(self._bids)

    property asks:
        def __get__(self):
            return _OrderListView(self._asks)

    # ---- order submission & storage ---------------------------------------

    cpdef COrder submit_order(
        self,
        unsigned long long order_id,
        int side,
        double price,
        unsigned int quantity,
        unsigned long long timestamp_ns,
    ):
        """Validate and accept a single order into the order book.

        Parameters
        ----------
        order_id : unsigned long long
            Unique order identifier.
        side : int
            ``1`` (BUY) or ``2`` (SELL).
        price : double
            Dollar price — will be converted to integer cents internally.
        quantity : unsigned int
            Must be > 0.
        timestamp_ns : unsigned long long
            Arrival timestamp or sequence number.

        Returns
        -------
        COrder
            The accepted order stored in the order book.

        Raises
        ------
        ValueError
            If any field fails validation.
        """
        # --- validation ---
        if side != _SIDE_BUY and side != _SIDE_SELL:
            raise ValueError(
                f"Invalid side {side}: must be {_SIDE_BUY} (BUY) or {_SIDE_SELL} (SELL)"
            )

        if price <= 0.0:
            raise ValueError(
                f"Invalid price {price}: must be positive"
            )

        if quantity == 0:
            raise ValueError(
                "Invalid quantity 0: must be positive"
            )

        cdef long long cents = price_to_cents(price)
        self._sequence_counter += 1

        cdef COrder order = COrder(
            order_id=order_id,
            side=side,
            price_cents=cents,
            quantity=quantity,
            timestamp_ns=timestamp_ns,
            sequence_num=self._sequence_counter,
        )

        if side == _SIDE_BUY:
            self._bids.append(order)
        elif side == _SIDE_SELL:
            self._asks.append(order)

        self._order_count += 1
        return order

    def add_buy_order(self, *args, **kwargs):
        """Validate and add a BUY order to bid storage.

        Can be called with ``(order_id, price, quantity[, timestamp_ns])``
        or with an existing ``COrder`` instance.
        """
        cdef COrder ord_obj
        cdef unsigned long long order_id
        cdef double price
        cdef unsigned int quantity
        cdef unsigned long long timestamp_ns = 0

        if len(args) == 1 and isinstance(args[0], COrder) and not kwargs:
            ord_obj = <COrder>args[0]
            if ord_obj.side != _SIDE_BUY:
                raise ValueError(f"Invalid side {ord_obj.side}: expected BUY ({_SIDE_BUY})")
            if ord_obj.price_cents <= 0:
                raise ValueError(f"Invalid price_cents {ord_obj.price_cents}: must be positive")
            if ord_obj.quantity == 0:
                raise ValueError("Invalid quantity 0: must be positive")
            self._sequence_counter += 1
            ord_obj.sequence_num = self._sequence_counter
            self._bids.append(ord_obj)
            self._order_count += 1
            return ord_obj

        if "order_id" in kwargs:
            if "side" in kwargs and kwargs["side"] != _SIDE_BUY:
                raise ValueError(f"Invalid side {kwargs['side']}: expected BUY ({_SIDE_BUY})")
            order_id = kwargs["order_id"]
            price = kwargs["price"]
            quantity = kwargs["quantity"]
            timestamp_ns = kwargs.get("timestamp_ns", 0)
        elif len(args) >= 3:
            # Handle possible positional (order_id, side, price, quantity[, ts])
            if len(args) >= 4 and args[1] == _SIDE_BUY:
                order_id = args[0]
                price = args[2]
                quantity = args[3]
                if len(args) >= 5:
                    timestamp_ns = args[4]
            else:
                order_id = args[0]
                price = args[1]
                quantity = args[2]
                if len(args) >= 4:
                    timestamp_ns = args[3]
        else:
            raise ValueError(
                "add_buy_order requires (order_id, price, quantity[, timestamp_ns]) or a COrder"
            )

        return self.submit_order(order_id, _SIDE_BUY, price, quantity, timestamp_ns)

    def add_sell_order(self, *args, **kwargs):
        """Validate and add a SELL order to ask storage.

        Can be called with ``(order_id, price, quantity[, timestamp_ns])``
        or with an existing ``COrder`` instance.
        """
        cdef COrder ord_obj
        cdef unsigned long long order_id
        cdef double price
        cdef unsigned int quantity
        cdef unsigned long long timestamp_ns = 0

        if len(args) == 1 and isinstance(args[0], COrder) and not kwargs:
            ord_obj = <COrder>args[0]
            if ord_obj.side != _SIDE_SELL:
                raise ValueError(f"Invalid side {ord_obj.side}: expected SELL ({_SIDE_SELL})")
            if ord_obj.price_cents <= 0:
                raise ValueError(f"Invalid price_cents {ord_obj.price_cents}: must be positive")
            if ord_obj.quantity == 0:
                raise ValueError("Invalid quantity 0: must be positive")
            self._sequence_counter += 1
            ord_obj.sequence_num = self._sequence_counter
            self._asks.append(ord_obj)
            self._order_count += 1
            return ord_obj

        if "order_id" in kwargs:
            if "side" in kwargs and kwargs["side"] != _SIDE_SELL:
                raise ValueError(f"Invalid side {kwargs['side']}: expected SELL ({_SIDE_SELL})")
            order_id = kwargs["order_id"]
            price = kwargs["price"]
            quantity = kwargs["quantity"]
            timestamp_ns = kwargs.get("timestamp_ns", 0)
        elif len(args) >= 3:
            # Handle possible positional (order_id, side, price, quantity[, ts])
            if len(args) >= 4 and args[1] == _SIDE_SELL:
                order_id = args[0]
                price = args[2]
                quantity = args[3]
                if len(args) >= 5:
                    timestamp_ns = args[4]
            else:
                order_id = args[0]
                price = args[1]
                quantity = args[2]
                if len(args) >= 4:
                    timestamp_ns = args[3]
        else:
            raise ValueError(
                "add_sell_order requires (order_id, price, quantity[, timestamp_ns]) or a COrder"
            )

        return self.submit_order(order_id, _SIDE_SELL, price, quantity, timestamp_ns)

    def add_order(self, *args, **kwargs):
        """Add an order (COrder or parameters) to the appropriate storage side."""
        cdef COrder ord_obj
        if len(args) == 1 and isinstance(args[0], COrder) and not kwargs:
            ord_obj = <COrder>args[0]
            if ord_obj.side == _SIDE_BUY:
                return self.add_buy_order(ord_obj)
            elif ord_obj.side == _SIDE_SELL:
                return self.add_sell_order(ord_obj)
            else:
                raise ValueError(f"Invalid side {ord_obj.side}")
        return self.submit_order(*args, **kwargs)


# Module-level alias for convenience and alternative naming conventions
OrderBook = MatchingEngine
