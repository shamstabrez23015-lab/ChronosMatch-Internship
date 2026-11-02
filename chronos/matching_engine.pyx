# cython: language_level=3
"""ChronosMatch Cython Matching Engine Foundation & Limit Order Book.

Provides a C-level order representation, Limit Order Book data structures,
and Price Priority inspection.

Week 2, Day 2:
- BUY and SELL order storage (bids and asks).
- Deterministic arrival sequence preservation.
- Full inspection and count APIs for bids and asks.
- Safe order validation preventing corrupt book states.
- Clean order-book initialization and reset.

Week 2, Day 3:
- Price Priority: Highest BUY price has highest priority.
- Price Priority: Lowest SELL price has highest priority.
- Price Priority inspection methods for best BUY/SELL orders and prices.
- Deterministic arrival preservation for equal prices.
- Safe crossing-price detection using integer cent comparisons (best BUY >= best SELL).
- Full preservation of order data, arrival order, and book state.

Week 2, Day 4:
- Time Priority (FIFO) at equal price levels for BUY and SELL orders.
- Combined Price-Time Priority: price is primary, arrival time is secondary tie-breaker.
- Deterministic arrival sequence preservation using engine `sequence_num` and timestamps.
- Priority inspection APIs for best orders and prioritized order sequences (get_prioritized_bids, get_prioritized_asks).
- Safe, non-mutating inspection leaving book state and quantities intact.

Week 2, Day 5:
- Partial fill execution: ``execute_partial_match()`` matches the single highest-priority
  BUY against the single highest-priority SELL when prices cross.
- Executed quantity = min(buy_remaining_quantity, sell_remaining_quantity).
- Execution price policy: resting order's price (maker price = best SELL / lowest ask).
- Partially filled resting orders retain their original arrival sequence (no re-queue).
- Fully filled orders are removed from the order book.
Week 2, Day 6:
- Multi-order matching: ``match_order()`` sweeps an incoming order across multiple
  compatible resting orders using strict price-time priority.

Week 2, Day 7:

Week 3, Day 3:
- Best Bid / Best Ask Access and Order-Book State Management:
  * Best bid: Highest remaining BUY price and available quantity.
  * Best ask: Lowest remaining SELL price and available quantity.
  * Quantity accessors: ``get_best_bid_quantity()``, ``get_best_ask_quantity()`` (individual or aggregate).
  * Bid-ask spread inspection: ``get_spread()``, ``get_spread_cents()``, ``spread()``.
  * Top-of-book telemetry snapshot: ``get_top_of_book()``, ``top_of_book()``.
  * Order-book state consistency guarantees: FIFO preservation, zero-remaining-quantity active order exclusion.
  * 100% non-mutating inspection leaving book state and arrival sequence intact.

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

* ``1`` -> BUY
* ``2`` -> SELL
"""

# ---------------------------------------------------------------------------
# C-level and Python-level constants
# ---------------------------------------------------------------------------
from libc.math cimport round as c_round
from libc.stdlib cimport malloc, free

DEF _SIDE_BUY  = 1
DEF _SIDE_SELL = 2

SIDE_BUY = 1
SIDE_SELL = 2


# ---------------------------------------------------------------------------
# C-level fill record struct (zero-Python hot-path buffer)
# ---------------------------------------------------------------------------
# CTradeRecord: plain C struct; no Python heap allocation per fill event.
cdef struct CTradeRecord:
    unsigned long long buy_order_id
    unsigned long long sell_order_id
    unsigned int executed_quantity
    long long execution_price_cents
    unsigned int buy_remaining_quantity
    unsigned int sell_remaining_quantity


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
        Original number of shares/contracts submitted (must be > 0).
        This field is never modified after submission.
    remaining_quantity : unsigned int
        Live remaining shares/contracts available for matching.
        Equals ``quantity`` on submission; decremented on each partial fill.
        Fully filled orders have ``remaining_quantity == 0``.
    timestamp_ns : unsigned long long
        Arrival timestamp in nanoseconds (or sequence number).
    sequence_num : unsigned long long
        Deterministic arrival sequence assigned by the matching engine.
        Never modified after the order is accepted (no re-queue on partial fill).
    """

    cdef public unsigned long long order_id
    cdef public int side
    cdef public long long price_cents
    cdef public unsigned int quantity
    cdef public unsigned int remaining_quantity
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
        self.remaining_quantity = quantity  # starts equal to quantity; decremented on fills
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
            f"rem={self.remaining_quantity}, "
            f"ts={self.timestamp_ns})"
        )

    def as_dict(self):
        """Return a plain-Python dictionary snapshot of the order."""
        return {
            "order_id": self.order_id,
            "side": self.side,
            "price_cents": self.price_cents,
            "quantity": self.quantity,
            "remaining_quantity": self.remaining_quantity,
            "timestamp_ns": self.timestamp_ns,
        }


cdef inline COrder _create_corder(
    unsigned long long order_id,
    int side,
    long long price_cents,
    unsigned int quantity,
    unsigned int remaining_quantity,
    unsigned long long timestamp_ns,
    unsigned long long sequence_num,
):
    """Fast C-level factory for COrder bypassing Python __init__ and argument boxing."""
    cdef COrder o = COrder.__new__(COrder)
    o.order_id = order_id
    o.side = side
    o.price_cents = price_cents
    o.quantity = quantity
    o.remaining_quantity = remaining_quantity
    o.timestamp_ns = timestamp_ns
    o.sequence_num = sequence_num
    return o


# ---------------------------------------------------------------------------
# Trade result (Week 2, Day 5)
# ---------------------------------------------------------------------------
cdef class TradeResult:
    """Immutable record of a single partial or full fill execution.

    Created by ``MatchingEngine.execute_partial_match()`` on every successful
    trade.  All fields are C-level typed for cache-friendliness.

    Execution-price policy
    ----------------------
    The execution price is always the **resting SELL order's price** (lowest
    ask / maker price).  This is the standard exchange convention: the passive
    (resting) side sets the price; the aggressive (incoming) side accepts it.
    For the single-shot ``execute_partial_match()`` call both orders are in
    the book, so the best SELL price is used as the canonical execution price.

    Attributes
    ----------
    buy_order_id : unsigned long long
    sell_order_id : unsigned long long
    executed_quantity : unsigned int
        Shares actually transferred in this fill.
    execution_price_cents : long long
        Execution price in integer cents.
    buy_remaining_quantity : unsigned int
        Shares remaining in the BUY order after this fill.
    sell_remaining_quantity : unsigned int
        Shares remaining in the SELL order after this fill.
    """

    cdef public unsigned long long buy_order_id
    cdef public unsigned long long sell_order_id
    cdef public unsigned int executed_quantity
    cdef public long long execution_price_cents
    cdef public unsigned int buy_remaining_quantity
    cdef public unsigned int sell_remaining_quantity

    def __init__(
        self,
        unsigned long long buy_order_id,
        unsigned long long sell_order_id,
        unsigned int executed_quantity,
        long long execution_price_cents,
        unsigned int buy_remaining_quantity,
        unsigned int sell_remaining_quantity,
    ):
        self.buy_order_id = buy_order_id
        self.sell_order_id = sell_order_id
        self.executed_quantity = executed_quantity
        self.execution_price_cents = execution_price_cents
        self.buy_remaining_quantity = buy_remaining_quantity
        self.sell_remaining_quantity = sell_remaining_quantity

    @property
    def execution_price(self):
        """Return the execution price as a float dollar amount."""
        return self.execution_price_cents / 100.0

    def __repr__(self):
        return (
            f"TradeResult("
            f"buy={self.buy_order_id}, sell={self.sell_order_id}, "
            f"exec_qty={self.executed_quantity}, "
            f"price_cents={self.execution_price_cents}, "
            f"buy_rem={self.buy_remaining_quantity}, "
            f"sell_rem={self.sell_remaining_quantity})"
        )

    def as_dict(self):
        """Return a plain-Python dictionary snapshot of the trade result."""
        return {
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "executed_quantity": self.executed_quantity,
            "execution_price_cents": self.execution_price_cents,
            "execution_price": self.execution_price,
            "buy_remaining_quantity": self.buy_remaining_quantity,
            "sell_remaining_quantity": self.sell_remaining_quantity,
        }


cdef inline TradeResult _create_trade_result(
    unsigned long long buy_order_id,
    unsigned long long sell_order_id,
    unsigned int executed_quantity,
    long long execution_price_cents,
    unsigned int buy_remaining_quantity,
    unsigned int sell_remaining_quantity,
):
    """Fast C-level factory for TradeResult bypassing Python __init__ and argument boxing."""
    cdef TradeResult tr = TradeResult.__new__(TradeResult)
    tr.buy_order_id = buy_order_id
    tr.sell_order_id = sell_order_id
    tr.executed_quantity = executed_quantity
    tr.execution_price_cents = execution_price_cents
    tr.buy_remaining_quantity = buy_remaining_quantity
    tr.sell_remaining_quantity = sell_remaining_quantity
    return tr


# ---------------------------------------------------------------------------
# Helper: convert protocol float price -> integer cents
# ---------------------------------------------------------------------------
cdef inline long long _price_to_cents_c(double price) noexcept nogil:
    """C-level price conversion: dollar float -> integer cents.
    Uses libc c_round() with no Python object involvement.
    Called from the hot matching path to avoid cpdef dispatch overhead.
    """
    return <long long>c_round(price * 100.0)


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
    return _price_to_cents_c(price)


# ---------------------------------------------------------------------------
# C-level comparison helpers for Price-Time Priority (FIFO)
# ---------------------------------------------------------------------------
from functools import cmp_to_key

cdef inline bint _is_earlier_order(COrder a, COrder b):
    """Return True if order `a` has earlier arrival priority than order `b`.

    Deterministic arrival evaluation:
    1. Check `timestamp_ns` if both are non-zero and distinct.
    2. Check engine `sequence_num` if both are non-zero and distinct.
    3. Fallback checks on `sequence_num` and `timestamp_ns`.
    4. Deterministic final tie-breaker on `order_id`.
    """
    if a.timestamp_ns != 0 and b.timestamp_ns != 0 and a.timestamp_ns != b.timestamp_ns:
        return a.timestamp_ns < b.timestamp_ns
    if a.sequence_num != 0 and b.sequence_num != 0 and a.sequence_num != b.sequence_num:
        return a.sequence_num < b.sequence_num
    if a.sequence_num != b.sequence_num:
        return a.sequence_num < b.sequence_num
    if a.timestamp_ns != b.timestamp_ns:
        return a.timestamp_ns < b.timestamp_ns
    return a.order_id < b.order_id


cdef inline int _compare_buy_orders(COrder a, COrder b):
    """Compare two BUY orders for Price-Time Priority.

    Returns:
       1 if `a` has higher priority than `b`
      -1 if `b` has higher priority than `a`
       0 if identical priority
    """
    if a.price_cents > b.price_cents:
        return 1
    elif a.price_cents < b.price_cents:
        return -1
    else:
        # Equal price -> Time Priority (FIFO)
        if _is_earlier_order(a, b):
            return 1
        elif _is_earlier_order(b, a):
            return -1
        else:
            return 0


cdef inline int _compare_sell_orders(COrder a, COrder b):
    """Compare two SELL orders for Price-Time Priority.

    Returns:
       1 if `a` has higher priority than `b`
      -1 if `b` has higher priority than `a`
       0 if identical priority
    """
    if a.price_cents < b.price_cents:
        return 1
    elif a.price_cents > b.price_cents:
        return -1
    else:
        # Equal price -> Time Priority (FIFO)
        if _is_earlier_order(a, b):
            return 1
        elif _is_earlier_order(b, a):
            return -1
        else:
            return 0


def _buy_cmp(a, b):
    # For cmp_to_key: negative means a precedes b in sorted output (higher priority first)
    return -_compare_buy_orders(<COrder>a, <COrder>b)


def _sell_cmp(a, b):
    # For cmp_to_key: negative means a precedes b in sorted output (higher priority first)
    return -_compare_sell_orders(<COrder>a, <COrder>b)


_BUY_PRIORITY_KEY = cmp_to_key(_buy_cmp)
_SELL_PRIORITY_KEY = cmp_to_key(_sell_cmp)


# ---------------------------------------------------------------------------
# C-level sorting helpers (eliminating cmp_to_key overhead inside engine)
# ---------------------------------------------------------------------------
cdef void _insertion_sort_buy(list orders, Py_ssize_t low, Py_ssize_t high):
    cdef Py_ssize_t i, j
    cdef COrder key
    for i in range(low + 1, high + 1):
        key = <COrder>orders[i]
        j = i - 1
        while j >= low and _compare_buy_orders(key, <COrder>orders[j]) > 0:
            orders[j + 1] = orders[j]
            j -= 1
        orders[j + 1] = key


cdef void _quicksort_buy(list orders, Py_ssize_t low, Py_ssize_t high):
    if low >= high:
        return
    if high - low < 16:
        _insertion_sort_buy(orders, low, high)
        return
    cdef COrder pivot = <COrder>orders[(low + high) // 2]
    cdef Py_ssize_t i = low
    cdef Py_ssize_t j = high
    cdef COrder temp
    while i <= j:
        while _compare_buy_orders(<COrder>orders[i], pivot) > 0:
            i += 1
        while _compare_buy_orders(<COrder>orders[j], pivot) < 0:
            j -= 1
        if i <= j:
            temp = <COrder>orders[i]
            orders[i] = orders[j]
            orders[j] = temp
            i += 1
            j -= 1
    if low < j:
        _quicksort_buy(orders, low, j)
    if i < high:
        _quicksort_buy(orders, i, high)


cdef void _c_sort_buy_orders(list orders):
    """Sort a list of BUY orders in-place by Price-Time Priority using C comparisons."""
    cdef Py_ssize_t n = len(orders)
    if n <= 1:
        return
    if n < 32:
        _insertion_sort_buy(orders, 0, n - 1)
    else:
        _quicksort_buy(orders, 0, n - 1)


cdef void _insertion_sort_sell(list orders, Py_ssize_t low, Py_ssize_t high):
    cdef Py_ssize_t i, j
    cdef COrder key
    for i in range(low + 1, high + 1):
        key = <COrder>orders[i]
        j = i - 1
        while j >= low and _compare_sell_orders(key, <COrder>orders[j]) > 0:
            orders[j + 1] = orders[j]
            j -= 1
        orders[j + 1] = key


cdef void _quicksort_sell(list orders, Py_ssize_t low, Py_ssize_t high):
    if low >= high:
        return
    if high - low < 16:
        _insertion_sort_sell(orders, low, high)
        return
    cdef COrder pivot = <COrder>orders[(low + high) // 2]
    cdef Py_ssize_t i = low
    cdef Py_ssize_t j = high
    cdef COrder temp
    while i <= j:
        while _compare_sell_orders(<COrder>orders[i], pivot) > 0:
            i += 1
        while _compare_sell_orders(<COrder>orders[j], pivot) < 0:
            j -= 1
        if i <= j:
            temp = <COrder>orders[i]
            orders[i] = orders[j]
            orders[j] = temp
            i += 1
            j -= 1
    if low < j:
        _quicksort_sell(orders, low, j)
    if i < high:
        _quicksort_sell(orders, i, high)


cdef void _c_sort_sell_orders(list orders):
    """Sort a list of SELL orders in-place by Price-Time Priority using C comparisons."""
    cdef Py_ssize_t n = len(orders)
    if n <= 1:
        return
    if n < 32:
        _insertion_sort_sell(orders, 0, n - 1)
    else:
        _quicksort_sell(orders, 0, n - 1)


# ---------------------------------------------------------------------------
# Limit Order Book & Matching Engine
# ---------------------------------------------------------------------------
cdef class MatchingEngine:
    """Cython Matching Engine and Limit Order Book (Week 2, Day 6).

    Capabilities
    ------------
    * Initialise an empty engine and order book.
    * Separate storage for BUY orders (bids) and SELL orders (asks).
    * Deterministic arrival sequence preservation.
    * Accept and validate orders.
    * Full inspection and order-counting for bids and asks.
    * Price priority: Identify highest BUY and lowest SELL orders and prices.
    * Time priority: Deterministic FIFO ordering when prices are equal.
    * Price-Time priority: Combined priority with price as primary and FIFO as secondary.
    * Deterministic arrival preservation for equal prices.
    * Crossing-price detection (best BUY price >= best SELL price).
    * Clear and re-initialize order book state.
    * **Day 5**: Single partial-fill execution via ``execute_partial_match()``.
    * **Day 6**: Multi-order matching via ``match_order()``.  A single incoming
      order sweeps across multiple compatible resting orders using strict
      price-time priority, producing one ``TradeResult`` per fill.

    Not yet implemented (scheduled for later working days)
    ------------------------------------------------------
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

    cpdef list get_bids(self, bint priority=False):
        """Return a list copy of currently stored BUY orders.

        Parameters
        ----------
        priority : bint, default False
            If ``True``, orders are returned sorted by Price-Time Priority
            (highest price first; earlier arrival first at equal prices).
            If ``False``, orders are returned in raw arrival sequence.
        """
        if priority:
            return self.get_prioritized_bids()
        return list(self._bids)

    cpdef list get_asks(self, bint priority=False):
        """Return a list copy of currently stored SELL orders.

        Parameters
        ----------
        priority : bint, default False
            If ``True``, orders are returned sorted by Price-Time Priority
            (lowest price first; earlier arrival first at equal prices).
            If ``False``, orders are returned in raw arrival sequence.
        """
        if priority:
            return self.get_prioritized_asks()
        return list(self._asks)

    cpdef list get_buy_orders(self, bint priority=False):
        """Alias for ``get_bids(priority=priority)``."""
        return self.get_bids(priority=priority)

    cpdef list get_sell_orders(self, bint priority=False):
        """Alias for ``get_asks(priority=priority)``."""
        return self.get_asks(priority=priority)

    cpdef list get_prioritized_bids(self):
        """Return a new list copy of BUY orders sorted in Price-Time Priority order.

        Primary rule: Highest price.
        Secondary rule: Earlier arrival (FIFO).
        Only active resting orders with remaining_quantity > 0 are included.
        Stored book state is NOT modified.
        """
        cdef Py_ssize_t n = len(self._bids)
        if n == 0:
            return []
        cdef list active = []
        cdef Py_ssize_t i
        cdef COrder ord_item
        for i in range(n):
            ord_item = <COrder>self._bids[i]
            if ord_item.remaining_quantity > 0:
                active.append(ord_item)
        cdef Py_ssize_t active_len = len(active)
        if active_len <= 1:
            return active
        _c_sort_buy_orders(active)
        return active

    cpdef list get_prioritized_asks(self):
        """Return a new list copy of SELL orders sorted in Price-Time Priority order.

        Primary rule: Lowest price.
        Secondary rule: Earlier arrival (FIFO).
        Only active resting orders with remaining_quantity > 0 are included.
        Stored book state is NOT modified.
        """
        cdef Py_ssize_t n = len(self._asks)
        if n == 0:
            return []
        cdef list active = []
        cdef Py_ssize_t i
        cdef COrder ord_item
        for i in range(n):
            ord_item = <COrder>self._asks[i]
            if ord_item.remaining_quantity > 0:
                active.append(ord_item)
        cdef Py_ssize_t active_len = len(active)
        if active_len <= 1:
            return active
        _c_sort_sell_orders(active)
        return active

    cpdef list get_bids_by_priority(self):
        """Alias for ``get_prioritized_bids()``."""
        return self.get_prioritized_bids()

    cpdef list get_asks_by_priority(self):
        """Alias for ``get_prioritized_asks()``."""
        return self.get_prioritized_asks()

    cpdef list get_buy_orders_by_priority(self):
        """Alias for ``get_prioritized_bids()``."""
        return self.get_prioritized_bids()

    cpdef list get_sell_orders_by_priority(self):
        """Alias for ``get_prioritized_asks()``."""
        return self.get_prioritized_asks()

    cpdef list prioritized_bids(self):
        """Alias for ``get_prioritized_bids()``."""
        return self.get_prioritized_bids()

    cpdef list prioritized_asks(self):
        """Alias for ``get_prioritized_asks()``."""
        return self.get_prioritized_asks()

    property bids:
        def __get__(self):
            return _OrderListView(self._bids)

    property asks:
        def __get__(self):
            return _OrderListView(self._asks)

    # ---- price priority & best order retrieval (Week 2, Day 3 & Day 4 & Day 7) ----

    cpdef COrder get_best_buy_order(self):
        """Return the BUY order with the highest price-time priority.

        Primary rule: Highest price.
        Secondary rule: At equal prices, earlier arrival (FIFO) has priority.
        Only considers active resting orders with remaining_quantity > 0.
        Returns ``None`` if the BUY book is empty or has no active orders.
        """
        cdef Py_ssize_t n = len(self._bids)
        if n == 0:
            return None
        cdef COrder best = None
        cdef COrder current
        cdef bint has_best = False
        cdef Py_ssize_t i
        for i in range(n):
            current = <COrder>self._bids[i]
            if current.remaining_quantity == 0:
                continue
            if not has_best or _compare_buy_orders(current, best) > 0:
                best = current
                has_best = True
        return best

    cpdef COrder get_best_sell_order(self):
        """Return the SELL order with the lowest price-time priority.

        Primary rule: Lowest price.
        Secondary rule: At equal prices, earlier arrival (FIFO) has priority.
        Only considers active resting orders with remaining_quantity > 0.
        Returns ``None`` if the SELL book is empty or has no active orders.
        """
        cdef Py_ssize_t n = len(self._asks)
        if n == 0:
            return None
        cdef COrder best = None
        cdef COrder current
        cdef bint has_best = False
        cdef Py_ssize_t i
        for i in range(n):
            current = <COrder>self._asks[i]
            if current.remaining_quantity == 0:
                continue
            if not has_best or _compare_sell_orders(current, best) > 0:
                best = current
                has_best = True
        return best

    # Aliases for best order retrieval
    cpdef COrder get_best_bid(self):
        """Alias for ``get_best_buy_order()``."""
        return self.get_best_buy_order()

    cpdef COrder get_best_bid_order(self):
        """Alias for ``get_best_buy_order()``."""
        return self.get_best_buy_order()

    cpdef COrder best_buy_order(self):
        """Alias for ``get_best_buy_order()``."""
        return self.get_best_buy_order()

    cpdef COrder best_bid(self):
        """Alias for ``get_best_buy_order()``."""
        return self.get_best_buy_order()

    cpdef COrder get_best_ask(self):
        """Alias for ``get_best_sell_order()``."""
        return self.get_best_sell_order()

    cpdef COrder get_best_ask_order(self):
        """Alias for ``get_best_sell_order()``."""
        return self.get_best_sell_order()

    cpdef COrder best_sell_order(self):
        """Alias for ``get_best_sell_order()``."""
        return self.get_best_sell_order()

    cpdef COrder best_ask(self):
        """Alias for ``get_best_sell_order()``."""
        return self.get_best_sell_order()

    # Best price inspection (dollar float)
    cpdef object get_best_buy_price(self):
        """Return the highest BUY price as a float, or ``None`` if empty."""
        cdef COrder best = self.get_best_buy_order()
        if best is None:
            return None
        return best.price

    cpdef object get_best_bid_price(self):
        """Alias for ``get_best_buy_price()``."""
        return self.get_best_buy_price()

    cpdef object best_buy_price(self):
        """Alias for ``get_best_buy_price()``."""
        return self.get_best_buy_price()

    cpdef object best_bid_price(self):
        """Alias for ``get_best_buy_price()``."""
        return self.get_best_buy_price()

    cpdef object get_best_sell_price(self):
        """Return the lowest SELL price as a float, or ``None`` if empty."""
        cdef COrder best = self.get_best_sell_order()
        if best is None:
            return None
        return best.price

    cpdef object get_best_ask_price(self):
        """Alias for ``get_best_sell_price()``."""
        return self.get_best_sell_price()

    cpdef object best_sell_price(self):
        """Alias for ``get_best_sell_price()``."""
        return self.get_best_sell_price()

    cpdef object best_ask_price(self):
        """Alias for ``get_best_sell_price()``."""
        return self.get_best_sell_price()

    # Best price inspection (integer cents)
    cpdef object get_best_buy_price_cents(self):
        """Return the highest BUY price in integer cents, or ``None`` if empty."""
        cdef COrder best = self.get_best_buy_order()
        if best is None:
            return None
        return best.price_cents

    cpdef object get_best_bid_price_cents(self):
        """Alias for ``get_best_buy_price_cents()``."""
        return self.get_best_buy_price_cents()

    cpdef object get_best_sell_price_cents(self):
        """Return the lowest SELL price in integer cents, or ``None`` if empty."""
        cdef COrder best = self.get_best_sell_order()
        if best is None:
            return None
        return best.price_cents

    cpdef object get_best_ask_price_cents(self):
        """Alias for ``get_best_sell_price_cents()``."""
        return self.get_best_sell_price_cents()

    # Best quantity inspection (Day 7)
    cpdef unsigned int get_best_buy_quantity(self, bint aggregate=True):
        """Return the available quantity at the best BUY price level.

        Parameters
        ----------
        aggregate : bint, default True
            If True, returns the sum of remaining quantities for all active BUY
            orders sharing the highest price.
            If False, returns the remaining quantity of the single highest-priority
            BUY order.

        Returns
        -------
        unsigned int
            Total remaining quantity (0 if empty).
        """
        cdef COrder best = self.get_best_buy_order()
        if best is None:
            return 0
        if not aggregate:
            return best.remaining_quantity

        cdef unsigned int total_qty = 0
        cdef COrder order
        cdef long long best_cents = best.price_cents
        cdef Py_ssize_t i, n = len(self._bids)
        for i in range(n):
            order = <COrder>self._bids[i]
            if order.price_cents == best_cents and order.remaining_quantity > 0:
                total_qty += order.remaining_quantity
        return total_qty

    cpdef unsigned int get_best_bid_quantity(self, bint aggregate=True):
        """Alias for ``get_best_buy_quantity(aggregate=aggregate)``."""
        return self.get_best_buy_quantity(aggregate=aggregate)

    cpdef unsigned int get_best_bid_qty(self, bint aggregate=True):
        """Alias for ``get_best_buy_quantity(aggregate=aggregate)``."""
        return self.get_best_buy_quantity(aggregate=aggregate)

    cpdef unsigned int best_bid_quantity(self, bint aggregate=True):
        """Alias for ``get_best_buy_quantity(aggregate=aggregate)``."""
        return self.get_best_buy_quantity(aggregate=aggregate)

    cpdef unsigned int best_bid_qty(self, bint aggregate=True):
        """Alias for ``get_best_buy_quantity(aggregate=aggregate)``."""
        return self.get_best_buy_quantity(aggregate=aggregate)

    cpdef unsigned int best_buy_quantity(self, bint aggregate=True):
        """Alias for ``get_best_buy_quantity(aggregate=aggregate)``."""
        return self.get_best_buy_quantity(aggregate=aggregate)

    cpdef unsigned int get_best_sell_quantity(self, bint aggregate=True):
        """Return the available quantity at the best SELL price level.

        Parameters
        ----------
        aggregate : bint, default True
            If True, returns the sum of remaining quantities for all active SELL
            orders sharing the lowest price.
            If False, returns the remaining quantity of the single lowest-priority
            SELL order.

        Returns
        -------
        unsigned int
            Total remaining quantity (0 if empty).
        """
        cdef COrder best = self.get_best_sell_order()
        if best is None:
            return 0
        if not aggregate:
            return best.remaining_quantity

        cdef unsigned int total_qty = 0
        cdef COrder order
        cdef long long best_cents = best.price_cents
        cdef Py_ssize_t i, n = len(self._asks)
        for i in range(n):
            order = <COrder>self._asks[i]
            if order.price_cents == best_cents and order.remaining_quantity > 0:
                total_qty += order.remaining_quantity
        return total_qty

    cpdef unsigned int get_best_ask_quantity(self, bint aggregate=True):
        """Alias for ``get_best_sell_quantity(aggregate=aggregate)``."""
        return self.get_best_sell_quantity(aggregate=aggregate)

    cpdef unsigned int get_best_ask_qty(self, bint aggregate=True):
        """Alias for ``get_best_sell_quantity(aggregate=aggregate)``."""
        return self.get_best_sell_quantity(aggregate=aggregate)

    cpdef unsigned int best_ask_quantity(self, bint aggregate=True):
        """Alias for ``get_best_sell_quantity(aggregate=aggregate)``."""
        return self.get_best_sell_quantity(aggregate=aggregate)

    cpdef unsigned int best_ask_qty(self, bint aggregate=True):
        """Alias for ``get_best_sell_quantity(aggregate=aggregate)``."""
        return self.get_best_sell_quantity(aggregate=aggregate)

    cpdef unsigned int best_sell_quantity(self, bint aggregate=True):
        """Alias for ``get_best_sell_quantity(aggregate=aggregate)``."""
        return self.get_best_sell_quantity(aggregate=aggregate)

    # Spread inspection (Day 7)
    cpdef object get_spread(self):
        """Return the bid-ask spread (best ask price - best bid price) as a float, or None if either side is empty."""
        cdef COrder best_buy = self.get_best_buy_order()
        cdef COrder best_sell = self.get_best_sell_order()
        if best_buy is None or best_sell is None:
            return None
        cdef long long spread_cents = best_sell.price_cents - best_buy.price_cents
        return round(spread_cents / 100.0, 6)

    cpdef object get_spread_cents(self):
        """Return the bid-ask spread in integer cents, or None if either side is empty."""
        cdef COrder best_buy = self.get_best_buy_order()
        cdef COrder best_sell = self.get_best_sell_order()
        if best_buy is None or best_sell is None:
            return None
        cdef long long spread_cents = best_sell.price_cents - best_buy.price_cents
        return spread_cents

    cpdef object spread(self):
        """Alias for ``get_spread()``."""
        return self.get_spread()

    # Top-of-book snapshot (Day 7)
    cpdef dict get_top_of_book(self):
        """Return a dictionary snapshot of top-of-book (best bid, best ask, spread)."""
        cdef COrder bb = self.get_best_buy_order()
        cdef COrder ba = self.get_best_sell_order()
        cdef object bid_price = bb.price if bb is not None else None
        cdef object ask_price = ba.price if ba is not None else None
        cdef unsigned int bid_qty = self.get_best_buy_quantity(aggregate=True) if bb is not None else 0
        cdef unsigned int ask_qty = self.get_best_sell_quantity(aggregate=True) if ba is not None else 0
        cdef object sp = None
        if bb is not None and ba is not None:
            sp = round((ba.price_cents - bb.price_cents) / 100.0, 6)
        return {
            "best_bid_price": bid_price,
            "best_bid_quantity": bid_qty,
            "best_ask_price": ask_price,
            "best_ask_quantity": ask_qty,
            "spread": sp,
        }

    cpdef dict top_of_book(self):
        """Alias for ``get_top_of_book()``."""
        return self.get_top_of_book()

    # Crossing price detection
    cpdef bint has_crossing_prices(self):
        """Return True if highest BUY price >= lowest SELL price.

        Returns False if either book side is empty, or if best BUY < best SELL.
        """
        cdef Py_ssize_t n_bids = len(self._bids)
        cdef Py_ssize_t n_asks = len(self._asks)
        if n_bids == 0 or n_asks == 0:
            return False
        cdef COrder best_buy = self.get_best_buy_order()
        cdef COrder best_sell = self.get_best_sell_order()
        if best_buy is None or best_sell is None:
            return False
        return best_buy.price_cents >= best_sell.price_cents

    cpdef bint has_crossing_price(self):
        """Alias for ``has_crossing_prices()``."""
        return self.has_crossing_prices()

    cpdef bint crossing_prices(self):
        """Alias for ``has_crossing_prices()``."""
        return self.has_crossing_prices()

    cpdef bint is_crossed(self):
        """Alias for ``has_crossing_prices()``."""
        return self.has_crossing_prices()

    cpdef bint can_match(self):
        """Alias for ``has_crossing_prices()``."""
        return self.has_crossing_prices()

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
            Dollar price -- will be converted to integer cents internally.
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

        cdef long long cents = _price_to_cents_c(price)
        self._sequence_counter += 1

        cdef COrder order = _create_corder(
            order_id,
            side,
            cents,
            quantity,
            quantity,
            timestamp_ns,
            self._sequence_counter,
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
            if ord_obj.remaining_quantity == 0:
                raise ValueError("Invalid remaining_quantity 0: order is already fully filled")
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
            if len(args) == 5:
                if args[1] != _SIDE_BUY:
                    raise ValueError(f"Invalid side {args[1]}: expected BUY ({_SIDE_BUY})")
                order_id = args[0]
                price = args[2]
                quantity = args[3]
                timestamp_ns = args[4]
            elif len(args) == 4 and type(args[1]) is int and args[1] in (_SIDE_BUY, _SIDE_SELL):
                if args[1] != _SIDE_BUY:
                    raise ValueError(f"Invalid side {args[1]}: expected BUY ({_SIDE_BUY})")
                order_id = args[0]
                price = args[2]
                quantity = args[3]
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
            if ord_obj.remaining_quantity == 0:
                raise ValueError("Invalid remaining_quantity 0: order is already fully filled")
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
            if len(args) == 5:
                if args[1] != _SIDE_SELL:
                    raise ValueError(f"Invalid side {args[1]}: expected SELL ({_SIDE_SELL})")
                order_id = args[0]
                price = args[2]
                quantity = args[3]
                timestamp_ns = args[4]
            elif len(args) == 4 and type(args[1]) is int and args[1] in (_SIDE_BUY, _SIDE_SELL):
                if args[1] != _SIDE_SELL:
                    raise ValueError(f"Invalid side {args[1]}: expected SELL ({_SIDE_SELL})")
                order_id = args[0]
                price = args[2]
                quantity = args[3]
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

    # ---- partial-fill execution (Week 2, Day 5) ---------------------------

    cpdef object execute_partial_match(self):
        """Execute one partial fill between the best BUY and best SELL orders.

        Partial-fill algorithm
        ----------------------
        1. Retrieve the best BUY (highest price, FIFO tie-break) and the best
           SELL (lowest price, FIFO tie-break).
        2. Check that prices cross: ``buy.price_cents >= sell.price_cents``.
           If not, return ``None`` -- no trade is possible.
        3. Compute ``executed_quantity = min(buy.remaining_quantity,
           sell.remaining_quantity)``.  Both are unsigned; the minimum is always
           >= 1 since orders with remaining_quantity == 0 are never kept in the
           book.
        4. Execution price = best SELL's ``price_cents`` (resting maker price).
        5. Decrement ``remaining_quantity`` on both orders by ``executed_quantity``.
           C-level unsigned arithmetic; exec_qty <= each remaining_quantity by
           construction, so no underflow occurs.
        6. Remove any fully filled order (``remaining_quantity == 0``) from its
           book side.  A partially filled resting order stays with its original
           ``sequence_num`` intact (no re-queue, no priority change).
        7. Return a ``TradeResult`` describing the fill.

        Price-time priority is preserved because:
        * Selection always uses get_best_buy_order / get_best_sell_order.
        * A partially filled order's sequence_num is never updated.
        * Fully filled orders are immediately removed.

        Returns
        -------
        TradeResult
            On a successful match.
        None
            If either book side is empty or prices do not cross.
        """
        # Guard: both sides must be non-empty
        cdef Py_ssize_t n_bids = len(self._bids)
        cdef Py_ssize_t n_asks = len(self._asks)
        if n_bids == 0 or n_asks == 0:
            return None

        # Select the single highest-priority orders on each side
        cdef COrder best_buy = self.get_best_buy_order()
        cdef COrder best_sell = self.get_best_sell_order()

        if best_buy is None or best_sell is None:
            return None

        # Price-crossing check using integer cents (no float equality risk)
        if best_buy.price_cents < best_sell.price_cents:
            return None

        # Executed quantity: minimum of the two remaining quantities
        cdef unsigned int exec_qty
        if best_buy.remaining_quantity <= best_sell.remaining_quantity:
            exec_qty = best_buy.remaining_quantity
        else:
            exec_qty = best_sell.remaining_quantity

        # Execution price: resting SELL order's price (lowest ask / maker price)
        cdef long long exec_price_cents = best_sell.price_cents

        # Update remaining quantities (exec_qty <= each remaining_quantity by construction)
        best_buy.remaining_quantity = best_buy.remaining_quantity - exec_qty
        best_sell.remaining_quantity = best_sell.remaining_quantity - exec_qty

        # Capture post-fill remaining quantities for the trade result
        cdef unsigned int buy_rem = best_buy.remaining_quantity
        cdef unsigned int sell_rem = best_sell.remaining_quantity
        cdef unsigned long long buy_id = best_buy.order_id
        cdef unsigned long long sell_id = best_sell.order_id

        # Remove fully filled orders via compaction scan
        # (eliminates O(N) linear-search + memmove of list.remove)
        cdef Py_ssize_t _pm_j, _pm_n
        cdef list _pm_remaining
        cdef COrder _pm_scan
        if buy_rem == 0:
            _pm_n = len(self._bids)
            _pm_remaining = []
            for _pm_j in range(_pm_n):
                _pm_scan = <COrder>self._bids[_pm_j]
                if _pm_scan.remaining_quantity > 0:
                    _pm_remaining.append(_pm_scan)
            self._bids[:] = _pm_remaining

        if sell_rem == 0:
            _pm_n = len(self._asks)
            _pm_remaining = []
            for _pm_j in range(_pm_n):
                _pm_scan = <COrder>self._asks[_pm_j]
                if _pm_scan.remaining_quantity > 0:
                    _pm_remaining.append(_pm_scan)
            self._asks[:] = _pm_remaining

        return _create_trade_result(
            buy_id,
            sell_id,
            exec_qty,
            exec_price_cents,
            buy_rem,
            sell_rem,
        )

    # ---- multi-order matching (Week 2 Day 6 / Week 3 Day 3 refactor) ------

    cdef int _c_match_loop(
        self,
        unsigned long long order_id,
        int side,
        long long incoming_price_cents,
        unsigned int quantity,
        unsigned long long timestamp_ns,
        unsigned long long incoming_seq,
        CTradeRecord *out_buf,
        Py_ssize_t buf_capacity,
        unsigned int *out_remaining,
    ) except -1:
        """C-level matching loop: zero Python object allocation inside the loop.

        Week 3 Day 3 optimisation
        -------------------------
        Replaces the former inline loop inside match_order.  Writes fill
        records directly into a pre-allocated CTradeRecord C array supplied
        by the caller.  Returns the number of fills recorded.

        All arithmetic is on statically typed C integers:
        * remaining_quantity decremented via unsigned C subtraction.
        * price crossing tested with integer cent comparison.
        * No TradeResult / COrder heap allocation in the inner loop.

        Book compaction (removing zero-quantity resting orders) is deferred
        to after the loop and is done in a single O(N) compaction pass.

        Parameters
        ----------
        order_id            : id of the incoming order
        side                : _SIDE_BUY or _SIDE_SELL
        incoming_price_cents: already-converted integer price
        quantity            : original order quantity
        timestamp_ns        : arrival timestamp
        incoming_seq        : engine sequence number assigned before call
        out_buf             : caller-allocated CTradeRecord array
        buf_capacity        : max fills that fit in out_buf
        out_remaining       : written with remaining qty after matching

        Returns
        -------
        int : number of fills written into out_buf  (-1 on exception)
        """
        cdef unsigned int incoming_remaining = quantity
        cdef list opposite_sorted
        cdef COrder resting
        cdef COrder new_order
        cdef COrder scan_ord
        cdef unsigned int exec_qty
        cdef long long exec_price_cents
        cdef Py_ssize_t i, n, j, total_orders, num_filled
        cdef list remaining_orders
        cdef int fill_count = 0

        if side == _SIDE_BUY:
            # ---- Incoming BUY sweeps resting SELLs (ascending price) ----
            if self._asks:
                opposite_sorted = self.get_prioritized_asks()
                n = len(opposite_sorted)
                num_filled = 0
                for i in range(n):
                    if incoming_remaining == 0:
                        break
                    if fill_count >= buf_capacity:
                        break
                    resting = <COrder>opposite_sorted[i]
                    # Price crossing: BUY price >= SELL price
                    if incoming_price_cents < resting.price_cents:
                        break  # sorted asc; no more matches
                    # Fill quantity: min of remaining quantities
                    if incoming_remaining <= resting.remaining_quantity:
                        exec_qty = incoming_remaining
                    else:
                        exec_qty = resting.remaining_quantity
                    exec_price_cents = resting.price_cents  # maker price
                    # Decrement – pure C unsigned arithmetic, no underflow
                    incoming_remaining = incoming_remaining - exec_qty
                    resting.remaining_quantity = resting.remaining_quantity - exec_qty
                    # Write fill record directly into C buffer (no Python alloc)
                    out_buf[fill_count].buy_order_id = order_id
                    out_buf[fill_count].sell_order_id = resting.order_id
                    out_buf[fill_count].executed_quantity = exec_qty
                    out_buf[fill_count].execution_price_cents = exec_price_cents
                    out_buf[fill_count].buy_remaining_quantity = incoming_remaining
                    out_buf[fill_count].sell_remaining_quantity = resting.remaining_quantity
                    fill_count += 1
                    if resting.remaining_quantity == 0:
                        num_filled += 1

                # Single-pass compaction: remove fully filled SELL resting orders
                if num_filled > 0:
                    total_orders = len(self._asks)
                    remaining_orders = []
                    for j in range(total_orders):
                        scan_ord = <COrder>self._asks[j]
                        if scan_ord.remaining_quantity > 0:
                            remaining_orders.append(scan_ord)
                    self._asks[:] = remaining_orders

            # Residual incoming BUY rests in the bid book
            if incoming_remaining > 0:
                new_order = _create_corder(
                    order_id, _SIDE_BUY, incoming_price_cents,
                    quantity, incoming_remaining, timestamp_ns, incoming_seq,
                )
                self._bids.append(new_order)
                self._order_count += 1

        else:
            # ---- Incoming SELL sweeps resting BUYs (descending price) ---
            if self._bids:
                opposite_sorted = self.get_prioritized_bids()
                n = len(opposite_sorted)
                num_filled = 0
                for i in range(n):
                    if incoming_remaining == 0:
                        break
                    if fill_count >= buf_capacity:
                        break
                    resting = <COrder>opposite_sorted[i]
                    # Price crossing: SELL price <= BUY price
                    if incoming_price_cents > resting.price_cents:
                        break  # sorted desc; no more matches
                    # Fill quantity
                    if incoming_remaining <= resting.remaining_quantity:
                        exec_qty = incoming_remaining
                    else:
                        exec_qty = resting.remaining_quantity
                    exec_price_cents = resting.price_cents  # maker price
                    incoming_remaining = incoming_remaining - exec_qty
                    resting.remaining_quantity = resting.remaining_quantity - exec_qty
                    # Write fill record directly into C buffer
                    out_buf[fill_count].buy_order_id = resting.order_id
                    out_buf[fill_count].sell_order_id = order_id
                    out_buf[fill_count].executed_quantity = exec_qty
                    out_buf[fill_count].execution_price_cents = exec_price_cents
                    out_buf[fill_count].buy_remaining_quantity = resting.remaining_quantity
                    out_buf[fill_count].sell_remaining_quantity = incoming_remaining
                    fill_count += 1
                    if resting.remaining_quantity == 0:
                        num_filled += 1

                # Single-pass compaction: remove fully filled BUY resting orders
                if num_filled > 0:
                    total_orders = len(self._bids)
                    remaining_orders = []
                    for j in range(total_orders):
                        scan_ord = <COrder>self._bids[j]
                        if scan_ord.remaining_quantity > 0:
                            remaining_orders.append(scan_ord)
                    self._bids[:] = remaining_orders

            # Residual incoming SELL rests in the ask book
            if incoming_remaining > 0:
                new_order = _create_corder(
                    order_id, _SIDE_SELL, incoming_price_cents,
                    quantity, incoming_remaining, timestamp_ns, incoming_seq,
                )
                self._asks.append(new_order)
                self._order_count += 1

        out_remaining[0] = incoming_remaining
        return fill_count


    cpdef list match_order(
        self,
        unsigned long long order_id,
        int side,
        double price,
        unsigned int quantity,
        unsigned long long timestamp_ns,
    ):
        """Match a single incoming order against multiple compatible resting orders.

        Multi-order matching algorithm (Day 6 / Week 3 Day 3 optimised)
        -----------------------------------------------------------------
        1. Validate the incoming order (side, price, quantity).
        2. Convert the incoming float price to integer cents via C-level helper.
        3. Sort the opposite-side book by price-time priority (one sort per call).
        4. Delegate the hot matching loop to ``_c_match_loop``, which writes
           fill records directly into a malloc'd C buffer with no Python
           object allocation inside the loop.
        5. Convert C fill records to TradeResult PyObjects in a single pass
           after the loop (boundary conversion).
        6. Return the list of ``TradeResult`` records in execution order.

        Execution price policy
        ----------------------
        Each fill uses the **resting order's price** (maker price):
        * Incoming BUY sweeping SELL orders -> each fill uses the SELL price.
        * Incoming SELL sweeping BUY orders -> each fill uses the BUY price.

        Parameters
        ----------
        order_id : unsigned long long
        side : int  (``1`` BUY, ``2`` SELL)
        price : double
        quantity : unsigned int  (must be > 0)
        timestamp_ns : unsigned long long

        Returns
        -------
        list[TradeResult]

        Raises
        ------
        ValueError  if side, price, or quantity is invalid.
        """
        # ---- validation ------------------------------------------------
        if side != _SIDE_BUY and side != _SIDE_SELL:
            raise ValueError(
                f"Invalid side {side}: must be {_SIDE_BUY} (BUY) or {_SIDE_SELL} (SELL)"
            )
        if price <= 0.0:
            raise ValueError(f"Invalid price {price}: must be positive")
        if quantity == 0:
            raise ValueError("Invalid quantity 0: must be positive")

        # C-level price conversion (no Python round() call)
        cdef long long incoming_price_cents = _price_to_cents_c(price)

        # Sequence number assigned before the loop so residual orders
        # preserve their original arrival priority (no re-queue).
        self._sequence_counter += 1
        cdef unsigned long long incoming_seq = self._sequence_counter

        # ---- delegate to C-level matching loop -------------------------
        # Allocate a fixed-size fill buffer on the C heap.
        # MAX_FILLS_PER_ORDER caps the buffer: an order cannot fill more
        # opposite-side orders than the book holds, and realistic books
        # rarely exceed a few thousand levels.
        cdef Py_ssize_t MAX_FILLS = max(len(self._bids), len(self._asks), 1) + 1
        cdef CTradeRecord *fill_buf = <CTradeRecord *>malloc(
            MAX_FILLS * sizeof(CTradeRecord)
        )
        if fill_buf == NULL:
            raise MemoryError("Failed to allocate fill buffer")

        cdef unsigned int remaining_after = 0
        cdef int fill_count = 0
        cdef list trades = []
        cdef Py_ssize_t k
        try:
            fill_count = self._c_match_loop(
                order_id,
                side,
                incoming_price_cents,
                quantity,
                timestamp_ns,
                incoming_seq,
                fill_buf,
                MAX_FILLS,
                &remaining_after,
            )

            # ---- boundary: convert C records -> Python TradeResult objects
            for k in range(fill_count):
                trades.append(_create_trade_result(
                    fill_buf[k].buy_order_id,
                    fill_buf[k].sell_order_id,
                    fill_buf[k].executed_quantity,
                    fill_buf[k].execution_price_cents,
                    fill_buf[k].buy_remaining_quantity,
                    fill_buf[k].sell_remaining_quantity,
                ))
        finally:
            free(fill_buf)

        return trades


# Module-level alias for convenience and alternative naming conventions
OrderBook = MatchingEngine
