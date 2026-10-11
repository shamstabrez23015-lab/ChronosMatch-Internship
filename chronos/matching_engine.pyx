# cython: language_level=3
"""ChronosMatch Cython Matching Engine Foundation.

Provides a C-level order representation and a minimal matching-engine
skeleton.  This is the Week 2, Day 1 foundation — no order-book sorting,
price-time priority, trade execution, or partial-fill logic is included yet.

Price Representation
--------------------
The Week 1 binary protocol stores prices as ``double`` (64-bit IEEE 754
float).  Floating-point equality/comparison is unsafe for matching, so this
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
# C-level constants
# ---------------------------------------------------------------------------
DEF SIDE_BUY  = 1
DEF SIDE_SELL = 2


# ---------------------------------------------------------------------------
# C-level order struct (kept as a Cython extension type for convenience)
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
    """

    cdef public unsigned long long order_id
    cdef public int side
    cdef public long long price_cents
    cdef public unsigned int quantity
    cdef public unsigned long long timestamp_ns

    def __init__(
        self,
        unsigned long long order_id,
        int side,
        long long price_cents,
        unsigned int quantity,
        unsigned long long timestamp_ns,
    ):
        self.order_id = order_id
        self.side = side
        self.price_cents = price_cents
        self.quantity = quantity
        self.timestamp_ns = timestamp_ns

    def __repr__(self):
        side_str = "BUY" if self.side == SIDE_BUY else "SELL"
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
# Matching-engine skeleton
# ---------------------------------------------------------------------------
cdef class MatchingEngine:
    """Minimal matching-engine skeleton (Week 2, Day 1).

    Capabilities
    ------------
    * Initialise an empty engine.
    * Report readiness/status.
    * Accept **one validated order** at a time and return an acknowledgement.

    Not yet implemented
    -------------------
    * Order-book data structures (sorted buy/sell sides).
    * Price-time priority matching.
    * Trade execution / partial fills.
    * Ring-buffer integration.
    """

    cdef public unsigned long long _order_count
    cdef public bint _ready

    def __init__(self):
        """Initialise an empty matching engine."""
        self._order_count = 0
        self._ready = True

    # ---- status -----------------------------------------------------------

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

    # ---- order submission -------------------------------------------------

    cpdef COrder submit_order(
        self,
        unsigned long long order_id,
        int side,
        double price,
        unsigned int quantity,
        unsigned long long timestamp_ns,
    ):
        """Validate and accept a single order.

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
            The accepted order (with ``price_cents`` set).

        Raises
        ------
        ValueError
            If any field fails validation.
        """
        # --- validation ---
        if side != SIDE_BUY and side != SIDE_SELL:
            raise ValueError(
                f"Invalid side {side}: must be {SIDE_BUY} (BUY) or {SIDE_SELL} (SELL)"
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

        cdef COrder order = COrder(
            order_id=order_id,
            side=side,
            price_cents=cents,
            quantity=quantity,
            timestamp_ns=timestamp_ns,
        )

        self._order_count += 1
        return order
