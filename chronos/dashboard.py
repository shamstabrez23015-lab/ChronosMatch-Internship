"""Terminal latency dashboard for ChronosMatch - Day 2 layout.

Provides an interactive curses-based monitoring dashboard with five sections:
  - Header: application title and subtitle.
  - Market Summary: Best Bid, Best Ask, Spread (placeholder values).
  - Order Book: BUY ORDERS (Bids) and SELL ORDERS (Asks) side-by-side columns.
  - Performance Metrics: orders processed, throughput, latency (placeholder values).
  - Footer: quit instruction.

Layout helpers are pure functions and fully testable without a live terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple, Union

try:
    import curses
except ImportError:  # pragma: no cover
    curses = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Core display constants
# ---------------------------------------------------------------------------

APP_TITLE = "CHRONOSMATCH"
APP_SUBTITLE = "Zero-Copy High-Frequency Trading Engine"
STATUS_MESSAGE = "Dashboard Initialized"
QUIT_MESSAGE = "Press Q to Quit"

# Section labels
SECTION_MARKET_SUMMARY = "MARKET SUMMARY"
SECTION_ORDER_BOOK = "ORDER BOOK"
SECTION_BUY_ORDERS = "BUY ORDERS (BIDS)"
SECTION_SELL_ORDERS = "SELL ORDERS (ASKS)"
SECTION_PERFORMANCE = "PERFORMANCE METRICS"
SECTION_TRADE_EXECUTION = "TRADE EXECUTION METRICS"
SECTION_TRADE_METRICS = SECTION_TRADE_EXECUTION
SECTION_TRADE_LATENCY = "TRADE EXECUTION LATENCY"
SECTION_TRADE_EXECUTION_LATENCY = "TRADE EXECUTION LATENCY"

# Market summary field labels
LABEL_BEST_BID = "Best Bid"
LABEL_BID_QTY = "Bid Qty"
LABEL_BID_QUANTITY = LABEL_BID_QTY
LABEL_BEST_ASK = "Best Ask"
LABEL_ASK_QTY = "Ask Qty"
LABEL_ASK_QUANTITY = LABEL_ASK_QTY
LABEL_SPREAD = "Bid-Ask Spread"
LABEL_BID_ASK_SPREAD = LABEL_SPREAD

# Performance field labels
LABEL_TOTAL_ORDERS = "Total Orders Processed"
LABEL_ORDERS_PROCESSED = LABEL_TOTAL_ORDERS
LABEL_PROCESSED_ORDERS = LABEL_TOTAL_ORDERS
LABEL_THROUGHPUT = "Throughput (orders/sec)"
LABEL_ORDER_THROUGHPUT = LABEL_THROUGHPUT
LABEL_THROUGHPUT_ORDERS_PER_SEC = LABEL_THROUGHPUT
LABEL_PROCESSED_ORDERS_PER_SEC = LABEL_THROUGHPUT
LABEL_ORDERS_PER_SECOND = LABEL_THROUGHPUT
LABEL_ORDER_PROCESSING_THROUGHPUT = LABEL_THROUGHPUT
LABEL_LATENCY = "Latency (microseconds)"

# Trade execution field labels
LABEL_TRADES_PROCESSED = "Processed Trades"
LABEL_TOTAL_TRADES = LABEL_TRADES_PROCESSED
LABEL_TRADE_COUNT = "Trade Count"
LABEL_TRADE_LATENCY = "Last Execution Latency (us)"
LABEL_TRADE_LATENCY_LAST = LABEL_TRADE_LATENCY
LABEL_TRADE_LATENCY_AVG = "Avg Execution Latency (us)"
LABEL_TRADE_LATENCY_MIN = "Min Execution Latency (us)"
LABEL_TRADE_LATENCY_MAX = "Max Execution Latency (us)"
LABEL_AVG_LATENCY = "Average Latency"
LABEL_MIN_LATENCY = "Minimum Latency"
LABEL_MAX_LATENCY = "Maximum Latency"
DEFAULT_TRADE_LATENCY_UNIT = "us"

# Agreed metric field names for latency tracking interface
METRIC_FIELD_TRADE_COUNT = "trade_count"
METRIC_FIELD_AVG_LATENCY_NS = "avg_latency_ns"
METRIC_FIELD_MIN_LATENCY_NS = "min_latency_ns"
METRIC_FIELD_MAX_LATENCY_NS = "max_latency_ns"

# Latency label detail: measures inter-event elapsed time between consecutive
# record_order_processed() calls recorded by the dashboard. This reflects the
# spacing between processing events observed at the dashboard boundary, NOT
# full end-to-end network or engine dispatch latency.
LABEL_LATENCY_LAST = "Last Event Interval (us)"
LABEL_LATENCY_AVG  = "Avg Event Interval (us)"
LABEL_LATENCY_MAX  = "Max Event Interval (us)"
LABEL_LATENCY_P95  = "P95 Event Interval (us)"

# Latency demo/sample constants
DEMO_LATENCY = "DEMO"
NO_SAMPLE_LATENCY = "N/A"
# Minimum samples required before p95/max are considered accurate
_LATENCY_MIN_SAMPLES_FOR_P95 = 20

# Demonstration / sample constants
DEMO_ORDERS_PROCESSED = 125
SAMPLE_ORDERS_PROCESSED = DEMO_ORDERS_PROCESSED
DEMO_THROUGHPUT = "DEMO"
NO_SAMPLE_THROUGHPUT = "N/A"
DEMO_SAMPLE_THROUGHPUT = 500.0

# Placeholder value used when data is not yet available
PLACEHOLDER = "--"

# Default terminal constraints
DEFAULT_REFRESH_INTERVAL_MS = 100
MIN_TERMINAL_ROWS = 30
MIN_TERMINAL_COLS = 72


# ---------------------------------------------------------------------------
# Best Bid, Best Ask, and Spread structures and calculations
# (pure functions, independent of Cython)
# ---------------------------------------------------------------------------


class BestBid(NamedTuple):
    """Container representing the best bid price and aggregated quantity."""

    price: Optional[float]
    quantity: int


class BestAsk(NamedTuple):
    """Container representing the best ask price and aggregated quantity."""

    price: Optional[float]
    quantity: int


class PriceLevel(NamedTuple):
    """Container representing a single price level and its aggregated quantity."""

    price: float
    quantity: int


# Clearly labeled demonstration BUY orders (fixed sample data for testing & demo mode)
SAMPLE_BUY_ORDERS: List[Dict[str, Any]] = [
    {"order_id": 101, "side": 1, "price": 500.0, "quantity": 100, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 102, "side": 1, "price": 495.0, "quantity": 80, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 103, "side": 1, "price": 490.0, "quantity": 120, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 104, "side": 1, "price": 485.0, "quantity": 150, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 105, "side": 1, "price": 480.0, "quantity": 200, "source": "DEMO_SAMPLE_DATA"},
]

# Clearly labeled demonstration SELL orders (fixed sample data for testing & demo mode)
SAMPLE_SELL_ORDERS: List[Dict[str, Any]] = [
    {"order_id": 201, "side": 2, "price": 515.0, "quantity": 100, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 202, "side": 2, "price": 505.0, "quantity": 40, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 203, "side": 2, "price": 510.0, "quantity": 80, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 204, "side": 2, "price": 520.0, "quantity": 70, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 205, "side": 2, "price": 525.0, "quantity": 90, "source": "DEMO_SAMPLE_DATA"},
]


def get_sample_buy_orders() -> List[Dict[str, Any]]:
    """Return a fresh copy of the demonstration BUY orders collection."""
    return [dict(order) for order in SAMPLE_BUY_ORDERS]


def get_sample_sell_orders() -> List[Dict[str, Any]]:
    """Return a fresh copy of the demonstration SELL orders collection."""
    return [dict(order) for order in SAMPLE_SELL_ORDERS]


def _extract_order_price_qty(
    order: Any, expected_side: Optional[Union[int, str]] = 1
) -> Optional[Tuple[float, int]]:
    """Extract (price, quantity) from various order representations.

    Supports:
      - dict: keys 'price' (or 'price_cents'), 'quantity' (or 'qty'), optional 'side'
      - tuple / list: (price, quantity), (order_id, price, quantity), or (order_id, side, price, quantity)
      - objects: attributes .price (or .price_cents), .quantity (or .qty), optional .side

    Args:
        order: The order object, dict, or tuple.
        expected_side: 1 for BUY, 2 for SELL, or None to accept any side.

    Returns:
      (price, quantity) tuple or None if invalid or side does not match.
    """
    if order is None:
        return None

    buy_sides = (1, "BUY", "buy", "B", "b")
    sell_sides = (2, "SELL", "sell", "S", "s", "ASK", "ask", "A", "a")

    # Handle dictionary
    if isinstance(order, dict):
        if "side" in order:
            side = order["side"]
            if expected_side in buy_sides and side not in buy_sides:
                return None
            if expected_side in sell_sides and side not in sell_sides:
                return None

        qty_val = order.get("remaining_quantity", order.get("quantity", order.get("qty", 0)))
        try:
            qty = int(qty_val)
        except (ValueError, TypeError):
            return None

        if "price" in order:
            try:
                price = float(order["price"])
            except (ValueError, TypeError):
                return None
        elif "price_cents" in order:
            try:
                price = float(order["price_cents"]) / 100.0
            except (ValueError, TypeError):
                return None
        else:
            return None

        return (price, qty)

    # Handle tuple / list
    if isinstance(order, (tuple, list)):
        if len(order) == 2:
            try:
                return (float(order[0]), int(order[1]))
            except (ValueError, TypeError):
                return None
        if len(order) == 3:
            try:
                return (float(order[1]), int(order[2]))
            except (ValueError, TypeError):
                return None
        if len(order) in (4, 5, 6):
            side = order[1]
            if expected_side in buy_sides and side not in buy_sides:
                return None
            if expected_side in sell_sides and side not in sell_sides:
                return None
            try:
                return (float(order[2]), int(order[3]))
            except (ValueError, TypeError):
                return None
        if len(order) >= 7:
            # Layout: (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type, ...)
            side = order[5]
            if expected_side in buy_sides and side not in buy_sides:
                return None
            if expected_side in sell_sides and side not in sell_sides:
                return None
            try:
                return (float(order[2]), int(order[3]))
            except (ValueError, TypeError):
                return None

    # Handle objects (dataclasses, NamedTuples, Cython COrder, protocol Order)
    if hasattr(order, "side"):
        side = getattr(order, "side")
        if expected_side in buy_sides and side not in buy_sides:
            return None
        if expected_side in sell_sides and side not in sell_sides:
            return None

    qty = None
    if hasattr(order, "remaining_quantity"):
        try:
            qty = int(getattr(order, "remaining_quantity"))
        except (ValueError, TypeError):
            qty = None
    if qty is None and hasattr(order, "quantity"):
        try:
            qty = int(getattr(order, "quantity"))
        except (ValueError, TypeError):
            return None
    elif qty is None and hasattr(order, "qty"):
        try:
            qty = int(getattr(order, "qty"))
        except (ValueError, TypeError):
            return None
    elif qty is None:
        return None

    price = None
    if hasattr(order, "price"):
        try:
            price = float(getattr(order, "price"))
        except (ValueError, TypeError):
            return None
    elif hasattr(order, "price_cents"):
        try:
            price = float(getattr(order, "price_cents")) / 100.0
        except (ValueError, TypeError):
            return None
    else:
        return None

    return (price, qty)


def _extract_order_id(order: Any) -> Optional[Any]:
    """Extract order ID from various order representations (dict, object, tuple).

    Args:
        order: The order object, dict, or tuple.

    Returns:
        The extracted order ID, or None if not present or cannot be determined.
    """
    if order is None:
        return None
    if isinstance(order, dict):
        return order.get("order_id", order.get("id"))
    if hasattr(order, "order_id"):
        return getattr(order, "order_id")
    if hasattr(order, "id"):
        return getattr(order, "id")
    if isinstance(order, (tuple, list)) and len(order) >= 3:
        if isinstance(order[0], int):
            return order[0]
    return None


def aggregate_orders_by_price(
    orders: Optional[Iterable[Any]],
    expected_side: Optional[Union[int, str]] = None,
) -> Dict[float, int]:
    """Aggregate total quantities by distinct price for the given orders and side.

    Prices are normalized (rounded to 6 decimal places) to avoid floating-point representation drift.
    Orders with non-positive price or quantity are ignored.

    Args:
        orders: Iterable of order objects, dicts, or tuples.
        expected_side: 1 for BUY, 2 for SELL, or None for any side.

    Returns:
        Dictionary mapping distinct float price to aggregated integer quantity.
    """
    if orders is None:
        return {}

    aggregated: Dict[float, int] = {}
    for order in orders:
        parsed = _extract_order_price_qty(order, expected_side=expected_side)
        if parsed is not None:
            p, q = parsed
            if p > 0 and q > 0 and not math.isnan(p) and not math.isinf(p):
                norm_p = round(p, 6)
                aggregated[norm_p] = aggregated.get(norm_p, 0) + q

    return aggregated


def calculate_buy_depth(
    orders: Optional[Iterable[Any]],
    max_levels: int = 5,
) -> List[PriceLevel]:
    """Calculate BUY order-book depth up to max_levels distinct prices.

    Price levels are sorted in descending order (highest price first).
    Orders at the same price level have their quantities aggregated.

    Args:
        orders: An iterable collection of BUY orders.
        max_levels: Maximum number of distinct price levels to return (default: 5).

    Returns:
        List of PriceLevel(price, quantity) sorted descending by price.
    """
    if orders is None or max_levels <= 0:
        return []

    agg = aggregate_orders_by_price(orders, expected_side=1)
    if not agg:
        return []

    sorted_prices = sorted(agg.keys(), reverse=True)
    return [PriceLevel(price=p, quantity=agg[p]) for p in sorted_prices[:max_levels]]


def calculate_sell_depth(
    orders: Optional[Iterable[Any]],
    max_levels: int = 5,
) -> List[PriceLevel]:
    """Calculate SELL order-book depth up to max_levels distinct prices.

    Price levels are sorted in ascending order (lowest price first).
    Orders at the same price level have their quantities aggregated.

    Args:
        orders: An iterable collection of SELL orders.
        max_levels: Maximum number of distinct price levels to return (default: 5).

    Returns:
        List of PriceLevel(price, quantity) sorted ascending by price.
    """
    if orders is None or max_levels <= 0:
        return []

    agg = aggregate_orders_by_price(orders, expected_side=2)
    if not agg:
        return []

    sorted_prices = sorted(agg.keys(), reverse=False)
    return [PriceLevel(price=p, quantity=agg[p]) for p in sorted_prices[:max_levels]]


def format_depth_rows(
    depth: Optional[List[Any]],
    max_levels: int = 5,
    placeholder: str = PLACEHOLDER,
) -> List[Tuple[str, str]]:
    """Format price depth levels into string (price, quantity) tuples for display.

    If depth contains fewer than max_levels, remaining rows are padded with placeholder.

    Args:
        depth: List of PriceLevel instances, tuples, or dicts.
        max_levels: Target number of display rows (default: 5).
        placeholder: String to display for empty levels (default: PLACEHOLDER).

    Returns:
        List of (price_str, quantity_str) tuples of length max_levels.
    """
    if max_levels <= 0:
        return []

    rows: List[Tuple[str, str]] = []
    levels = depth or []
    for level in levels[:max_levels]:
        if hasattr(level, "price") and hasattr(level, "quantity"):
            p = getattr(level, "price")
            q = getattr(level, "quantity")
        elif isinstance(level, (tuple, list)) and len(level) >= 2:
            p = level[0]
            q = level[1]
        elif isinstance(level, dict):
            p = level.get("price", level.get("price_cents", 0))
            q = level.get("quantity", level.get("qty", 0))
        else:
            continue
        try:
            rows.append((format_price(p), str(int(q))))
        except (ValueError, TypeError):
            rows.append((format_price(p), str(q)))

    while len(rows) < max_levels:
        rows.append((placeholder, placeholder))

    return rows


def calculate_best_bid(orders: Optional[Iterable[Any]]) -> BestBid:
    """Calculate the Best Bid (highest BUY price and aggregated quantity).

    Reuses calculate_buy_depth to maintain strict consistency with order-book depth.

    Args:
        orders: An iterable collection of BUY orders in dict, tuple, or object form.

    Returns:
        BestBid(price=None, quantity=0) if collection is empty or contains no valid bids.
        BestBid(price=highest_price, quantity=aggregated_quantity) otherwise.
    """
    depth = calculate_buy_depth(orders, max_levels=1)
    if not depth:
        return BestBid(price=None, quantity=0)
    return BestBid(price=depth[0].price, quantity=depth[0].quantity)


def calculate_best_ask(orders: Optional[Iterable[Any]]) -> BestAsk:
    """Calculate the Best Ask (lowest SELL price and aggregated quantity).

    Reuses calculate_sell_depth to maintain strict consistency with order-book depth.

    Args:
        orders: An iterable collection of SELL orders in dict, tuple, or object form.

    Returns:
        BestAsk(price=None, quantity=0) if collection is empty or contains no valid asks.
        BestAsk(price=lowest_price, quantity=aggregated_quantity) otherwise.
    """
    depth = calculate_sell_depth(orders, max_levels=1)
    if not depth:
        return BestAsk(price=None, quantity=0)
    return BestAsk(price=depth[0].price, quantity=depth[0].quantity)


def calculate_spread(
    best_ask: Optional[Union[float, int, BestAsk]],
    best_bid: Optional[Union[float, int, BestBid]],
) -> Optional[float]:
    """Calculate the Bid-Ask Spread (Best Ask - Best Bid).

    Args:
        best_ask: Best Ask price or BestAsk namedtuple.
        best_bid: Best Bid price or BestBid namedtuple.

    Returns:
        Spread (Best Ask - Best Bid) rounded to 6 decimal places,
        or None if either side is missing or invalid.
    """
    ask_price = best_ask.price if isinstance(best_ask, BestAsk) else best_ask
    bid_price = best_bid.price if isinstance(best_bid, BestBid) else best_bid

    if ask_price is None or bid_price is None:
        return None

    try:
        ask_f = float(ask_price)
        bid_f = float(bid_price)
    except (ValueError, TypeError):
        return None

    return round(ask_f - bid_f, 6)


def format_price(price: Optional[Union[float, int]]) -> str:
    """Format price or spread to two decimal places, or 'N/A' if empty/None."""
    if price is None:
        return "N/A"
    return f"{float(price):.2f}"


def format_best_bid_price(price: Optional[Union[float, int]]) -> str:
    """Format Best Bid price to two decimal places, or 'N/A' if empty."""
    return format_price(price)


def format_best_bid_qty(quantity: int) -> str:
    """Format Best Bid aggregated quantity as a string."""
    return str(int(quantity))


def format_best_ask_price(price: Optional[Union[float, int]]) -> str:
    """Format Best Ask price to two decimal places, or 'N/A' if empty."""
    return format_price(price)


def format_best_ask_qty(quantity: int) -> str:
    """Format Best Ask aggregated quantity as a string."""
    return str(int(quantity))


def format_spread(spread: Optional[Union[float, int]]) -> str:
    """Format Bid-Ask Spread to two decimal places, or 'N/A' if empty."""
    return format_price(spread)


def format_orders_processed(count: Optional[Union[int, str]]) -> str:
    """Format processed-orders counter with thousands separators, or PLACEHOLDER if None.

    Args:
        count: Non-negative integer count, integer-convertible string, or None.

    Returns:
        Formatted string with commas (e.g., '125', '12,500', '0') or PLACEHOLDER ('--').

    Raises:
        ValueError: If count is negative.
    """
    if count is None:
        return PLACEHOLDER
    try:
        val = int(count)
    except (ValueError, TypeError):
        return PLACEHOLDER
    if val < 0:
        raise ValueError(f"Orders processed count cannot be negative: {val}")
    return f"{val:,}"


# Alias matching total orders label
format_total_orders = format_orders_processed
format_processed_orders = format_orders_processed


def get_sample_orders_processed() -> int:
    """Return the demonstration count of processed orders based on sample data."""
    return DEMO_ORDERS_PROCESSED


def calculate_throughput(
    delta_orders: Union[int, float],
    elapsed_seconds: Union[int, float],
) -> Optional[float]:
    """Calculate throughput as processed orders divided by elapsed seconds.

    Args:
        delta_orders: Change in processed order count (must be non-negative).
        elapsed_seconds: Elapsed interval in seconds (must be strictly positive).

    Returns:
        Throughput in orders/sec rounded to 2 decimal places, or None if
        elapsed_seconds <= 0, delta_orders < 0, or either input is invalid.
    """
    if delta_orders is None or elapsed_seconds is None:
        return None

    try:
        d_orders = float(delta_orders)
        d_time = float(elapsed_seconds)
    except (ValueError, TypeError):
        return None

    if math.isnan(d_orders) or math.isinf(d_orders) or math.isnan(d_time) or math.isinf(d_time):
        return None

    if d_time <= 0 or d_orders < 0:
        return None

    if d_orders == 0.0:
        return 0.0

    return round(d_orders / d_time, 2)


def calculate_throughput_from_counts(
    current_count: Union[int, float],
    previous_count: Union[int, float],
    elapsed_seconds: Union[int, float],
) -> Optional[float]:
    """Calculate throughput from current and previous order counts over elapsed seconds."""
    if current_count is None or previous_count is None:
        return None
    try:
        c_curr = float(current_count)
        c_prev = float(previous_count)
    except (ValueError, TypeError):
        return None
    delta = c_curr - c_prev
    return calculate_throughput(delta, elapsed_seconds)


def calculate_throughput_ns(
    delta_orders: Union[int, float],
    elapsed_ns: Union[int, float],
) -> Optional[float]:
    """Calculate throughput as processed orders divided by elapsed nanoseconds.

    Args:
        delta_orders: Change in processed order count (must be non-negative).
        elapsed_ns: Elapsed interval in nanoseconds (must be strictly positive).

    Returns:
        Throughput in orders/sec rounded to 2 decimal places, or None if
        elapsed_ns <= 0, delta_orders < 0, or either input is invalid.
    """
    if delta_orders is None or elapsed_ns is None:
        return None

    try:
        d_orders = float(delta_orders)
        d_ns = float(elapsed_ns)
    except (ValueError, TypeError):
        return None

    if math.isnan(d_orders) or math.isinf(d_orders) or math.isnan(d_ns) or math.isinf(d_ns):
        return None

    if d_ns <= 0 or d_orders < 0:
        return None

    if d_orders == 0.0:
        return 0.0

    elapsed_seconds = d_ns / 1_000_000_000.0
    return calculate_throughput(d_orders, elapsed_seconds)


def calculate_throughput_from_counts_ns(
    current_count: Union[int, float],
    previous_count: Union[int, float],
    elapsed_ns: Union[int, float],
) -> Optional[float]:
    """Calculate throughput from current and previous order counts over elapsed nanoseconds."""
    if current_count is None or previous_count is None:
        return None
    try:
        c_curr = float(current_count)
        c_prev = float(previous_count)
    except (ValueError, TypeError):
        return None
    delta = c_curr - c_prev
    return calculate_throughput_ns(delta, elapsed_ns)


def format_throughput(
    throughput: Optional[Union[float, int, str]],
    is_demo: bool = False,
    include_unit: bool = False,
    decimals: int = 2,
) -> str:
    """Format throughput metric for display.

    Args:
        throughput: Numeric throughput value, string value, or None.
        is_demo: If True and throughput is None, return DEMO_THROUGHPUT ('DEMO').
        include_unit: If True and value is numeric, append ' orders/sec'.
        decimals: Number of decimal places for numeric values (default: 2).

    Returns:
        Formatted throughput string (e.g. '500.00', '1,000,000.00', 'DEMO', 'N/A').

    Raises:
        ValueError: If throughput is a negative number.
    """
    if throughput is None:
        return DEMO_THROUGHPUT if is_demo else NO_SAMPLE_THROUGHPUT

    if isinstance(throughput, bool):
        return DEMO_THROUGHPUT if is_demo else NO_SAMPLE_THROUGHPUT

    if isinstance(throughput, str):
        return throughput

    try:
        val = float(throughput)
    except (ValueError, TypeError):
        return NO_SAMPLE_THROUGHPUT

    if math.isnan(val) or math.isinf(val):
        return NO_SAMPLE_THROUGHPUT

    if val < 0:
        raise ValueError(f"Throughput cannot be negative: {val}")

    if decimals > 0:
        formatted = f"{val:,.{decimals}f}"
    else:
        formatted = f"{round(val):,}"

    if include_unit:
        return f"{formatted} orders/sec"
    return formatted


def get_sample_throughput() -> float:
    """Return demonstration throughput rate based on sample specification."""
    return DEMO_SAMPLE_THROUGHPUT


# ---------------------------------------------------------------------------
# Latency helpers (pure functions, no curses dependency)
# ---------------------------------------------------------------------------


def calculate_latency_stats(
    samples_us: List[float],
) -> Optional[Dict[str, float]]:
    """Calculate latency statistics from a list of microsecond samples.

    Args:
        samples_us: List of non-negative float latency measurements in microseconds.

    Returns:
        Dict with keys 'last', 'avg', 'max', and optionally 'p95' (when >= 20 samples),
        or None if samples is empty or None.
    """
    if not samples_us:
        return None
    try:
        valid = [float(s) for s in samples_us if s is not None and float(s) >= 0]
    except (ValueError, TypeError):
        return None
    if not valid:
        return None

    result: Dict[str, float] = {
        "last": valid[-1],
        "avg": sum(valid) / len(valid),
        "max": max(valid),
    }
    if len(valid) >= _LATENCY_MIN_SAMPLES_FOR_P95:
        sorted_vals = sorted(valid)
        p95_idx = max(0, int(math.ceil(len(sorted_vals) * 0.95)) - 1)
        result["p95"] = sorted_vals[p95_idx]
    return result


def format_latency(
    value_us: Optional[Union[float, int]],
    decimals: int = 1,
    is_demo: bool = False,
) -> str:
    """Format a latency value in microseconds for display.

    Args:
        value_us: Latency in microseconds (non-negative float or int), or None.
        decimals: Decimal places for the formatted value (default: 1).
        is_demo: If True and value_us is None, return DEMO_LATENCY ('DEMO').

    Returns:
        Formatted string like '123.4', or 'DEMO'/'N/A' when no value is available.
    """
    if value_us is None:
        return DEMO_LATENCY if is_demo else NO_SAMPLE_LATENCY
    try:
        val = float(value_us)
    except (ValueError, TypeError):
        return NO_SAMPLE_LATENCY
    if math.isnan(val) or math.isinf(val) or val < 0:
        return NO_SAMPLE_LATENCY
    return f"{val:.{decimals}f}"


def calculate_trade_latency_stats(
    samples: Optional[List[Union[float, int]]],
) -> Optional[Dict[str, float]]:
    """Calculate trade execution latency statistics from recorded samples.

    Args:
        samples: List of non-negative latency measurements.

    Returns:
        Dict with keys 'last', 'avg', 'min', 'max' (and 'p95' when >= 20 samples),
        or None if samples is empty, None, or contains no valid values.
    """
    if not samples:
        return None
    try:
        valid = [
            float(s)
            for s in samples
            if s is not None
            and not math.isnan(float(s))
            and not math.isinf(float(s))
            and float(s) >= 0
        ]
    except (ValueError, TypeError):
        return None
    if not valid:
        return None

    result: Dict[str, float] = {
        "last": valid[-1],
        "avg": sum(valid) / len(valid),
        "min": min(valid),
        "max": max(valid),
    }
    if len(valid) >= _LATENCY_MIN_SAMPLES_FOR_P95:
        sorted_vals = sorted(valid)
        p95_idx = max(0, int(math.ceil(len(sorted_vals) * 0.95)) - 1)
        result["p95"] = sorted_vals[p95_idx]
    return result


def format_trade_latency(
    value: Optional[Union[float, int]],
    unit: str = "us",
    decimals: int = 1,
) -> str:
    """Format a trade execution latency value for display.

    Args:
        value: Latency in microseconds or nanoseconds (float, int), or None.
        unit: Unit string ('us' or 'ns', default 'us').
        decimals: Decimal places for microsecond formatting (default: 1).

    Returns:
        Formatted string (e.g., '123.4', '450', '1,200') or 'N/A' if None or invalid.
    """
    if value is None:
        return NO_SAMPLE_LATENCY
    try:
        val = float(value)
    except (ValueError, TypeError):
        return NO_SAMPLE_LATENCY
    if math.isnan(val) or math.isinf(val) or val < 0:
        return NO_SAMPLE_LATENCY

    if unit.lower() == "ns":
        return f"{int(round(val)):,}"
    return f"{val:.{decimals}f}"


def format_trades_processed(count: Optional[Union[int, str]]) -> str:
    """Format processed trades counter with thousands separators, or 'N/A' if None.

    Args:
        count: Non-negative integer count, integer-convertible string, or None.

    Returns:
        Formatted string (e.g., '0', '125', '12,500') or 'N/A' if None.

    Raises:
        ValueError: If count is negative.
    """
    if count is None:
        return NO_SAMPLE_LATENCY
    try:
        val = int(count)
    except (ValueError, TypeError):
        return NO_SAMPLE_LATENCY
    if val < 0:
        raise ValueError(f"Trades processed count cannot be negative: {val}")
    return f"{val:,}"


@dataclass
class TradeLatencyMetrics:
    """Container representing agreed trade execution latency metrics.

    Fields:
      trade_count: Total count of executed trades.
      avg_latency_ns: Mean execution latency in nanoseconds.
      min_latency_ns: Minimum execution latency in nanoseconds.
      max_latency_ns: Maximum execution latency in nanoseconds.
      last_latency_ns: Last execution latency in nanoseconds.
    """

    trade_count: int = 0
    avg_latency_ns: Optional[float] = None
    min_latency_ns: Optional[float] = None
    max_latency_ns: Optional[float] = None
    last_latency_ns: Optional[float] = None


def extract_trade_latency_metrics(tracker: Any) -> Optional[Dict[str, Any]]:
    """Extract agreed trade latency metric fields from a latency tracking interface.

    Accepts:
      - Objects with trade_count, avg_latency_ns, min_latency_ns, max_latency_ns
      - Objects with get_metrics() or get_stats() methods
      - Dictionaries with agreed keys
      - Callables returning metrics objects or dicts

    Agreed fields:
      trade_count (int)
      avg_latency_ns (float / int)
      min_latency_ns (float / int)
      max_latency_ns (float / int)

    Returns:
      Dict with 'trade_count', 'avg_latency_ns', 'min_latency_ns', 'max_latency_ns',
      'last_latency_ns', or None if tracker is None or unavailable.
    """
    if tracker is None:
        return None

    obj = tracker
    if callable(obj) and not hasattr(obj, "trade_count") and not hasattr(obj, "avg_latency_ns"):
        try:
            obj = obj()
        except Exception:
            return None

    if obj is None:
        return None

    if hasattr(obj, "get_metrics") and callable(getattr(obj, "get_metrics")):
        try:
            obj = obj.get_metrics()
        except Exception:
            return None
    elif hasattr(obj, "get_stats") and callable(getattr(obj, "get_stats")):
        try:
            obj = obj.get_stats()
        except Exception:
            return None

    if obj is None:
        return None

    def _get_val(source: Any, *keys: str) -> Any:
        if isinstance(source, dict):
            for k in keys:
                if k in source and source[k] is not None:
                    return source[k]
        else:
            for k in keys:
                if hasattr(source, k):
                    val = getattr(source, k)
                    if val is not None:
                        return val
        return None

    raw_count = _get_val(obj, "trade_count", "trades_processed", "total_trades")
    raw_avg = _get_val(obj, "avg_latency_ns", "avg_execution_latency_ns", "mean_latency_ns")
    raw_min = _get_val(obj, "min_latency_ns", "min_execution_latency_ns")
    raw_max = _get_val(obj, "max_latency_ns", "max_execution_latency_ns")
    raw_last = _get_val(obj, "last_latency_ns", "last_execution_latency_ns", "latency_ns")

    # Fallback to microsecond equivalents if nanosecond metrics are omitted
    if raw_avg is None:
        avg_us = _get_val(obj, "avg_latency_us", "avg_execution_latency_us", "avg_latency")
        if avg_us is not None:
            try:
                raw_avg = float(avg_us) * 1000.0
            except (ValueError, TypeError):
                pass
    if raw_min is None:
        min_us = _get_val(obj, "min_latency_us", "min_execution_latency_us", "min_latency")
        if min_us is not None:
            try:
                raw_min = float(min_us) * 1000.0
            except (ValueError, TypeError):
                pass
    if raw_max is None:
        max_us = _get_val(obj, "max_latency_us", "max_execution_latency_us", "max_latency")
        if max_us is not None:
            try:
                raw_max = float(max_us) * 1000.0
            except (ValueError, TypeError):
                pass
    if raw_last is None:
        last_us = _get_val(obj, "last_latency_us", "last_execution_latency_us", "latency_us", "latency")
        if last_us is not None:
            try:
                raw_last = float(last_us) * 1000.0
            except (ValueError, TypeError):
                pass

    trade_count = 0
    if raw_count is not None:
        try:
            trade_count = max(0, int(raw_count))
        except (ValueError, TypeError):
            trade_count = 0

    def _clean_lat(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            f = float(val)
        except (ValueError, TypeError):
            return None
        if math.isnan(f) or math.isinf(f) or f < 0:
            return None
        return f

    avg_ns = _clean_lat(raw_avg)
    min_ns = _clean_lat(raw_min)
    max_ns = _clean_lat(raw_max)
    last_ns = _clean_lat(raw_last)

    # When no trades have been processed, latency metrics are unavailable (N/A)
    if trade_count == 0:
        avg_ns = None
        min_ns = None
        max_ns = None
        last_ns = None

    return {
        "trade_count": trade_count,
        "avg_latency_ns": avg_ns,
        "min_latency_ns": min_ns,
        "max_latency_ns": max_ns,
        "last_latency_ns": last_ns,
    }


# ---------------------------------------------------------------------------
# Whale Order Detection
# ---------------------------------------------------------------------------

WHALE_MIN_PRICE_LEVELS: int = 2  # Minimum distinct price levels swept for whale classification

SECTION_WHALE_ALERT: str = "\u26a1 WHALE ORDER DETECTED"
LABEL_WHALE_LEVELS: str = "Price Levels Swept"
LABEL_WHALE_VOLUME: str = "Volume Matched"
LABEL_WHALE_ORDER_ID: str = "Order ID"
LABEL_WHALE_SIDE: str = "Side"


@dataclass
class WhaleOrderEvent:
    """Represents a detected whale order that swept multiple price levels.

    A whale order is defined as a single aggressive order that executes
    against two or more distinct price levels in the order book.
    No arbitrary size threshold is used -- detection is based solely on
    multi-level execution.

    Fields:
        order_id: ID of the aggressor order.
        side: Aggressor side (1=BUY, 2=SELL, 0=unknown).
        total_quantity: Sum of all executed quantities.
        price_levels_cleared: Number of distinct price levels swept.
        prices: Ordered list of distinct prices at which trades executed.
        volume_matched: Total executed volume.
        timestamp_ns: Optional nanosecond timestamp of detection.
    """

    order_id: int
    side: int
    total_quantity: int
    price_levels_cleared: int
    prices: List[float]
    volume_matched: int
    timestamp_ns: Optional[int] = None

    @property
    def is_whale(self) -> bool:
        """Return True when this event meets the multi-level whale threshold."""
        return self.price_levels_cleared >= WHALE_MIN_PRICE_LEVELS


def detect_whale_order(
    order_id: int,
    trades: Optional[List[Any]],
    side: Optional[int] = None,
) -> Optional[WhaleOrderEvent]:
    """Detect if an order executed across multiple price levels (whale sweep).

    Detection is based exclusively on whether trades from a single order span
    two or more distinct price levels.  No order-size threshold is applied.

    Args:
        order_id: ID of the order that was submitted.
        trades: List of TradeResult objects from the matching engine.
                Each item must expose a ``price`` attribute (or index 2) and
                an ``executed_quantity`` attribute (or index 3).
        side: Optional aggressor side (1=BUY, 2=SELL); stored for display only.

    Returns:
        A :class:`WhaleOrderEvent` if 2+ distinct price levels were swept,
        otherwise ``None``.
    """
    if not trades:
        return None

    prices: List[float] = []
    total_volume: int = 0
    for t in trades:
        try:
            p = float(t.price) if hasattr(t, "price") else float(t.execution_price) if hasattr(t, "execution_price") else float(t[2])
            q = int(t.executed_quantity) if hasattr(t, "executed_quantity") else int(t[3])
        except (AttributeError, IndexError, TypeError, ValueError):
            continue
        prices.append(p)
        total_volume += q

    # Deduplicate while preserving execution order
    seen: dict = {}
    for p in prices:
        seen[p] = None
    distinct_prices = list(seen.keys())

    if len(distinct_prices) < WHALE_MIN_PRICE_LEVELS:
        return None

    return WhaleOrderEvent(
        order_id=order_id,
        side=side if side is not None else 0,
        total_quantity=total_volume,
        price_levels_cleared=len(distinct_prices),
        prices=distinct_prices,
        volume_matched=total_volume,
    )


def build_whale_alert_lines(
    width: int,
    whale: Optional[WhaleOrderEvent] = None,
) -> List[str]:
    """Return whale order alert section lines, or an empty list if no whale.

    Args:
        width: Available content width in characters.
        whale: A detected whale order event, or None.

    Returns:
        List of formatted strings to display the alert, or [] when *whale* is None.
    """
    if whale is None:
        return []

    divider = "-" * width
    col_w = max(width - 4, 10)
    side_str = "BUY" if whale.side == 1 else "SELL" if whale.side == 2 else "?"
    levels_str = str(whale.price_levels_cleared)
    prices_str = " -> ".join(f"{p:.2f}" for p in whale.prices[:5])
    if len(whale.prices) > 5:
        prices_str += " ..."

    return [
        f"  {SECTION_WHALE_ALERT}",
        divider,
        f"  {LABEL_WHALE_ORDER_ID:<{col_w - 10}} {whale.order_id:>8}",
        f"  {LABEL_WHALE_SIDE:<{col_w - 10}} {side_str:>8}",
        f"  {LABEL_WHALE_LEVELS:<{col_w - 10}} {levels_str:>8}",
        f"  {LABEL_WHALE_VOLUME:<{col_w - 10}} {whale.volume_matched:>8,}",
        f"  Swept: {prices_str}",
        divider,
    ]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration parameters for the terminal dashboard."""

    refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS
    min_rows: int = MIN_TERMINAL_ROWS
    min_cols: int = MIN_TERMINAL_COLS
    trade_latency_unit: str = DEFAULT_TRADE_LATENCY_UNIT


# ---------------------------------------------------------------------------
# Layout helpers (pure functions - no curses dependency, fully testable)
# ---------------------------------------------------------------------------


def build_header_lines(width: int, status: str = STATUS_MESSAGE) -> List[str]:
    """Return header text lines for the given content width."""
    border = "=" * width
    return [
        border,
        f"  {APP_TITLE}",
        f"  {APP_SUBTITLE}",
        f"  [{status}]",
        border,
    ]


def build_market_summary_lines(
    width: int,
    best_bid: str = PLACEHOLDER,
    best_ask: str = PLACEHOLDER,
    spread: str = PLACEHOLDER,
    bid_qty: str = PLACEHOLDER,
    ask_qty: str = PLACEHOLDER,
) -> List[str]:
    """Return Market Summary section lines."""
    divider = "-" * width
    col_w = max(width - 4, 10)
    return [
        f"  {SECTION_MARKET_SUMMARY}",
        divider,
        f"  {LABEL_BEST_BID:<{col_w - 10}} {best_bid:>8}",
        f"  {LABEL_BID_QTY:<{col_w - 10}} {bid_qty:>8}",
        f"  {LABEL_BEST_ASK:<{col_w - 10}} {best_ask:>8}",
        f"  {LABEL_ASK_QTY:<{col_w - 10}} {ask_qty:>8}",
        f"  {LABEL_SPREAD:<{col_w - 10}} {spread:>8}",
        divider,
    ]


def build_order_book_lines(
    width: int,
    bid_rows: Optional[List[Tuple[str, str]]] = None,
    ask_rows: Optional[List[Tuple[str, str]]] = None,
    num_placeholder_rows: int = 5,
) -> List[str]:
    """Return Order Book section lines with two columns (Bids | Asks).

    Args:
        width: Available content width in characters.
        bid_rows: List of (price, quantity) tuples for bid side.
        ask_rows: List of (price, quantity) tuples for ask side.
        num_placeholder_rows: Placeholder row count when no real data is given.
    """
    if bid_rows is None:
        bid_rows = [(PLACEHOLDER, PLACEHOLDER)] * num_placeholder_rows
    if ask_rows is None:
        ask_rows = [(PLACEHOLDER, PLACEHOLDER)] * num_placeholder_rows

    divider = "-" * width
    half = max((width - 3) // 2, 20)

    buy_hdr = f"  {SECTION_BUY_ORDERS}"
    header_row = f"{buy_hdr:<{half + 2}}  {SECTION_SELL_ORDERS}"
    spacing = max(half - 18, 0)
    sub_hdr = (
        f"  {'Price':>8}  {'Qty':>6}"
        + " " * spacing
        + f"  {'Price':>8}  {'Qty':>6}"
    )

    lines: List[str] = [
        f"  {SECTION_ORDER_BOOK}",
        divider,
        header_row,
        sub_hdr,
    ]

    max_rows = max(len(bid_rows), len(ask_rows))
    for i in range(max_rows):
        bp, bq = bid_rows[i] if i < len(bid_rows) else (PLACEHOLDER, PLACEHOLDER)
        ap, aq = ask_rows[i] if i < len(ask_rows) else (PLACEHOLDER, PLACEHOLDER)
        bid_cell = f"  {bp:>8}  {bq:>6}"
        ask_cell = f"  {ap:>8}  {aq:>6}"
        lines.append(f"{bid_cell:<{half + 2}}{ask_cell}")

    lines.append(divider)
    return lines


def build_performance_lines(
    width: int,
    total_orders: Union[str, int] = PLACEHOLDER,
    throughput: Union[str, int, float] = PLACEHOLDER,
    latency: str = PLACEHOLDER,
    latency_avg: str = PLACEHOLDER,
    orders_processed: Optional[Union[str, int]] = None,
) -> List[str]:
    """Return Performance Metrics section lines.

    Latency values reflect the inter-event elapsed time between consecutive
    record_order_processed() calls as observed by the dashboard. This is NOT
    full end-to-end network or engine dispatch latency.

    Args:
        width: Available content width in characters.
        total_orders: Total processed orders (integer, formatted string, or PLACEHOLDER).
        throughput: Throughput metric (number, formatted string, or PLACEHOLDER).
        latency: Last inter-event interval string (microseconds).
        latency_avg: Average inter-event interval string (microseconds).
        orders_processed: Optional alias for total_orders.
    """
    raw_val = orders_processed if orders_processed is not None else total_orders
    if isinstance(raw_val, int):
        orders_str = format_orders_processed(raw_val)
    elif raw_val is None:
        orders_str = PLACEHOLDER
    else:
        orders_str = str(raw_val)

    if isinstance(throughput, (int, float)) and not isinstance(throughput, bool):
        throughput_str = format_throughput(throughput)
    elif throughput is None:
        throughput_str = PLACEHOLDER
    else:
        throughput_str = str(throughput)

    divider = "-" * width
    col_w = max(width - 4, 10)
    return [
        f"  {SECTION_PERFORMANCE}",
        divider,
        f"  {LABEL_TOTAL_ORDERS:<{col_w - 10}} {orders_str:>8}",
        f"  {LABEL_THROUGHPUT:<{col_w - 10}} {throughput_str:>8}",
        f"  {LABEL_LATENCY:<{col_w - 10}} {latency:>8}",
        f"  {LABEL_LATENCY_AVG:<{col_w - 10}} {latency_avg:>8}",
        divider,
    ]


def build_trade_execution_lines(
    width: int,
    trades_processed: Optional[Union[str, int]] = 0,
    latency: Optional[Union[str, float, int]] = None,
    latency_avg: Optional[Union[str, float, int]] = None,
    latency_min: Optional[Union[str, float, int]] = None,
    latency_max: Optional[Union[str, float, int]] = None,
    unit: str = DEFAULT_TRADE_LATENCY_UNIT,
) -> List[str]:
    """Return Trade Execution Metrics section lines.

    Displays trade execution times, processed trade counts, and summary statistics.
    When metrics are not available (None), displays NO_SAMPLE_LATENCY ('N/A').

    Args:
        width: Available content width in characters.
        trades_processed: Total processed trades (integer, formatted string, or None).
        latency: Last trade execution latency (number, formatted string, or None).
        latency_avg: Average trade execution latency (number, formatted string, or None).
        latency_min: Minimum trade execution latency (number, formatted string, or None).
        latency_max: Maximum trade execution latency (number, formatted string, or None).
        unit: Latency measurement unit ('us' for microseconds, 'ns' for nanoseconds).
    """
    if isinstance(trades_processed, int):
        trades_str = format_trades_processed(trades_processed)
    elif trades_processed is None:
        trades_str = NO_SAMPLE_LATENCY
    else:
        trades_str = str(trades_processed)

    def _fmt(val: Optional[Union[str, float, int]]) -> str:
        if val is None:
            return NO_SAMPLE_LATENCY
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return format_trade_latency(val, unit=unit)
        return str(val)

    last_str = _fmt(latency)
    avg_str = _fmt(latency_avg)
    min_str = _fmt(latency_min)
    max_str = _fmt(latency_max)

    if unit.lower() == "us":
        lbl_last = LABEL_TRADE_LATENCY
        lbl_avg = LABEL_TRADE_LATENCY_AVG
        lbl_min = LABEL_TRADE_LATENCY_MIN
        lbl_max = LABEL_TRADE_LATENCY_MAX
    else:
        lbl_last = f"Last Execution Latency ({unit})"
        lbl_avg = f"Avg Execution Latency ({unit})"
        lbl_min = f"Min Execution Latency ({unit})"
        lbl_max = f"Max Execution Latency ({unit})"

    divider = "-" * width
    col_w = max(width - 4, 10)
    return [
        f"  {SECTION_TRADE_EXECUTION}",
        divider,
        f"  {LABEL_TRADES_PROCESSED:<{col_w - 10}} {trades_str:>8}",
        f"  {lbl_last:<{col_w - 10}} {last_str:>8}",
        f"  {lbl_avg:<{col_w - 10}} {avg_str:>8}",
        f"  {lbl_min:<{col_w - 10}} {min_str:>8}",
        f"  {lbl_max:<{col_w - 10}} {max_str:>8}",
        divider,
    ]


def build_footer_lines(width: int) -> List[str]:
    """Return footer lines."""
    return [
        f"  {QUIT_MESSAGE}",
        "=" * width,
    ]


# ---------------------------------------------------------------------------
# Main dashboard class
# ---------------------------------------------------------------------------


class TerminalDashboard:
    """Curses-based terminal dashboard for ChronosMatch."""

    def __init__(
        self,
        config: Optional[DashboardConfig] = None,
        buy_orders: Optional[List[Any]] = None,
        sell_orders: Optional[List[Any]] = None,
        use_sample_data: bool = True,
        orders_processed: int = 0,
        clock: Optional[Callable[[], float]] = None,
        ns_clock: Optional[Callable[[], int]] = None,
        throughput: Optional[Union[float, int, str]] = None,
        live_feed: Optional[Any] = None,
        trades_processed: Optional[int] = None,
        trade_latency_unit: Optional[str] = None,
    ) -> None:
        """Initialize the dashboard.

        Args:
            config: Dashboard configuration.
            buy_orders: Initial buy orders list.
            sell_orders: Initial sell orders list.
            use_sample_data: Whether to use sample data when no real data provided.
            orders_processed: Initial processed orders count.
            clock: Monotonic clock callable (seconds) for throughput; defaults to time.monotonic.
            ns_clock: Nanosecond clock callable for latency measurement; defaults to time.perf_counter_ns.
                      Inject a deterministic clock in tests.
            throughput: Optional initial throughput override.
            live_feed: Optional LiveFeedBridge instance for live order-flow and engine metrics.
        """
        self.config = config or DashboardConfig()
        self.is_running = False
        self.frame_count = 0
        self.use_sample_data = use_sample_data
        self.live_feed: Optional[Any] = live_feed
        self._status_message_override: Optional[str] = None

        if live_feed is not None:
            if getattr(live_feed, "dashboard", None) is None:
                live_feed.dashboard = self
            self.use_sample_data = False
            self.is_buy_sample_data = False
            self.is_sell_sample_data = False
            self.is_sample_data = False
            self.buy_orders = list(buy_orders) if buy_orders is not None else []
            self.sell_orders = list(sell_orders) if sell_orders is not None else []
            try:
                live_feed.sync_to_dashboard()
            except Exception:
                pass
        else:
            if buy_orders is not None:
                self.buy_orders: List[Any] = list(buy_orders)
                self.is_buy_sample_data = False
            elif use_sample_data:
                self.buy_orders = list(SAMPLE_BUY_ORDERS)
                self.is_buy_sample_data = True
            else:
                self.buy_orders = []
                self.is_buy_sample_data = False

            if sell_orders is not None:
                self.sell_orders: List[Any] = list(sell_orders)
                self.is_sell_sample_data = False
            elif use_sample_data:
                self.sell_orders = list(SAMPLE_SELL_ORDERS)
                self.is_sell_sample_data = True
            else:
                self.sell_orders = []
                self.is_sell_sample_data = False

            self.is_sample_data = self.is_buy_sample_data or self.is_sell_sample_data

        try:
            init_val = int(orders_processed)
        except (ValueError, TypeError) as err:
            raise ValueError(
                f"Orders processed count must be an integer, got: {orders_processed}"
            ) from err
        if init_val < 0:
            raise ValueError(f"Orders processed count cannot be negative: {orders_processed}")
        self._orders_processed: int = init_val
        self._processed_order_ids: set = set()

        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._ns_clock: Callable[[], int] = ns_clock if ns_clock is not None else time.perf_counter_ns
        self._has_custom_clock: bool = clock is not None
        self._has_custom_ns_clock: bool = ns_clock is not None
        self._last_throughput_time: Optional[float] = None
        self._last_throughput_time_ns: Optional[int] = None
        self._last_orders_count: Optional[int] = None
        self._throughput: Optional[float] = None
        self._throughput_override: Optional[str] = None
        if throughput is not None:
            if isinstance(throughput, str):
                self._throughput_override = throughput
            else:
                try:
                    init_tp = float(throughput)
                except (ValueError, TypeError) as err:
                    raise ValueError(f"Throughput must be a number, got: {throughput}") from err
                if init_tp < 0:
                    raise ValueError(f"Throughput cannot be negative: {throughput}")
                self._throughput = init_tp

        # Latency tracking state
        # Measures elapsed nanoseconds between consecutive record_order_processed() calls.
        # This reflects inter-event spacing at the dashboard boundary — not full
        # end-to-end or engine dispatch latency.
        self._latency_last_ns: Optional[int] = None   # ns timestamp of last event
        self._latency_last_us: Optional[float] = None  # last interval in microseconds
        self._latency_samples: List[float] = []        # rolling sample buffer (microseconds)
        _MAX_LATENCY_SAMPLES = 1000
        self._max_latency_samples: int = _MAX_LATENCY_SAMPLES

        # Trade execution metrics tracking state
        self._trade_latency_unit: str = (
            trade_latency_unit
            if trade_latency_unit is not None
            else getattr(self.config, "trade_latency_unit", DEFAULT_TRADE_LATENCY_UNIT)
        )
        self._trades_processed: int = 0
        if trades_processed is not None:
            self.trades_processed = trades_processed

        self._trade_latency_last_us: Optional[float] = None
        self._trade_latency_samples: List[float] = []
        _MAX_TRADE_LATENCY_SAMPLES = 1000
        self._max_trade_latency_samples: int = _MAX_TRADE_LATENCY_SAMPLES

        # Whale order detection state
        self._last_whale_event: Optional[WhaleOrderEvent] = None
        self._whale_history: List[WhaleOrderEvent] = []
        self._max_whale_history: int = 10

    @property
    def orders_processed(self) -> int:
        """Return the current number of processed orders."""
        return self._orders_processed

    @orders_processed.setter
    def orders_processed(self, value: int) -> None:
        """Set the processed orders counter, rejecting negative values."""
        try:
            int_val = int(value)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Orders processed count must be an integer, got: {value}") from err
        if int_val < 0:
            raise ValueError(f"Orders processed count cannot be negative: {value}")
        self._orders_processed = int_val

    def set_orders_processed(self, count: int) -> None:
        """Explicitly set the processed orders count.

        Args:
            count: Non-negative integer count.

        Raises:
            ValueError: If count is negative.
        """
        self.orders_processed = count

    def update_orders_processed(self, count: int) -> None:
        """Alias for set_orders_processed, ready for live engine snapshot integration."""
        self.set_orders_processed(count)

    def get_orders_processed(self) -> int:
        """Return the current number of processed orders."""
        return self.orders_processed

    def get_orders_processed_display(self) -> str:
        """Return the formatted processed orders count for display."""
        return format_orders_processed(self.orders_processed)

    def increment_orders_processed(self, delta: int = 1) -> int:
        """Increment the processed orders counter by delta.

        Args:
            delta: Non-negative integer to increment by (default: 1).

        Returns:
            The updated counter value.

        Raises:
            ValueError: If delta is negative.
        """
        try:
            int_delta = int(delta)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Increment delta must be an integer, got: {delta}") from err
        if int_delta < 0:
            raise ValueError(f"Increment delta cannot be negative: {delta}")
        self.orders_processed += int_delta
        return self.orders_processed

    def record_order_processed(
        self,
        order: Optional[Any] = None,
        timestamp_ns: Optional[int] = None,
    ) -> int:
        """Record a single processed order event and update latency metrics.

        The counter represents the number of orders accepted or processed by the engine,
        not the number of trades executed. A single order creating multiple fills counts
        as one processed order.

        Latency measurement: records the inter-event elapsed time between consecutive
        calls to this method using the injected nanosecond clock. This reflects the
        spacing between processing events observed at the dashboard boundary — it is
        NOT full end-to-end or engine dispatch latency.

        Args:
            order: Optional order representation (dict, object, tuple, or None).
                   If an order_id is present, duplicate events for the same order are ignored.
            timestamp_ns: Optional nanosecond timestamp of processing event.

        Returns:
            The updated orders_processed count.
        """
        order_id = _extract_order_id(order)
        if order_id is not None:
            if order_id in self._processed_order_ids:
                return self.orders_processed
            self._processed_order_ids.add(order_id)

        # Measure inter-event latency BEFORE incrementing the counter.
        # Done on real processing events, not in the render loop.
        self._record_latency_sample(timestamp_ns=timestamp_ns)

        self.increment_orders_processed(1)
        return self.orders_processed

    def on_order_processed(
        self,
        order: Optional[Any] = None,
        timestamp_ns: Optional[int] = None,
    ) -> int:
        """Event handler callback for order processed events (alias for record_order_processed)."""
        return self.record_order_processed(order, timestamp_ns=timestamp_ns)

    def _record_latency_sample(self, timestamp_ns: Optional[int] = None) -> None:
        """Record one inter-event latency sample using the nanosecond clock.

        Called only from record_order_processed() — never from the render loop.
        Safe when ns_clock raises or returns invalid values.
        """
        try:
            now_ns = int(timestamp_ns) if timestamp_ns is not None else int(self._ns_clock())
        except Exception:
            return

        if self._latency_last_ns is not None:
            elapsed_ns = now_ns - self._latency_last_ns
            # Guard against clock skew / backwards jumps
            if elapsed_ns > 0:
                elapsed_us = elapsed_ns / 1_000.0
                self._latency_last_us = elapsed_us
                if len(self._latency_samples) >= self._max_latency_samples:
                    # Drop oldest sample to keep buffer bounded
                    self._latency_samples.pop(0)
                self._latency_samples.append(elapsed_us)

        self._latency_last_ns = now_ns

    def get_latency_stats(self) -> Optional[Dict[str, float]]:
        """Return latency statistics computed from recorded samples.

        Returns:
            Dict with 'last', 'avg', 'max' (and 'p95' when >= 20 samples),
            all in microseconds. Returns None if no samples have been recorded.
        """
        return calculate_latency_stats(self._latency_samples)

    def get_latency_display(self) -> str:
        """Return formatted last inter-event latency for display (microseconds).

        Returns DEMO_LATENCY when using sample data and no real events recorded.
        Returns NO_SAMPLE_LATENCY when live data but no events yet.
        """
        if self._latency_last_us is not None:
            return format_latency(self._latency_last_us)
        return DEMO_LATENCY if self.is_sample_data else NO_SAMPLE_LATENCY

    def get_latency_avg_display(self) -> str:
        """Return formatted average inter-event latency for display (microseconds)."""
        stats = self.get_latency_stats()
        if stats is not None:
            return format_latency(stats.get("avg"))
        return DEMO_LATENCY if self.is_sample_data else NO_SAMPLE_LATENCY

    def reset_latency(self) -> None:
        """Reset all latency tracking state."""
        self._latency_last_ns = None
        self._latency_last_us = None
        self._latency_samples.clear()

    def reset_orders_processed(self) -> None:
        """Reset the processed orders counter, seen order IDs, and latency state."""
        self._orders_processed = 0
        self._processed_order_ids.clear()
        self.reset_throughput()
        self.reset_latency()
        self.reset_trade_metrics()

    # ------------------------------------------------------------------
    # Trade execution metrics management
    # ------------------------------------------------------------------

    @property
    def trades_processed(self) -> int:
        """Return the current number of processed trades."""
        return self._trades_processed

    @trades_processed.setter
    def trades_processed(self, value: int) -> None:
        """Set the processed trades counter, rejecting negative values."""
        try:
            int_val = int(value)
        except (ValueError, TypeError) as err:
            raise ValueError(
                f"Trades processed count must be an integer, got: {value}"
            ) from err
        if int_val < 0:
            raise ValueError(f"Trades processed count cannot be negative: {value}")
        self._trades_processed = int_val

    def set_trades_processed(self, count: int) -> None:
        """Explicitly set the processed trades count.

        Args:
            count: Non-negative integer count.

        Raises:
            ValueError: If count is negative.
        """
        self.trades_processed = count

    def update_trades_processed(self, count: int) -> None:
        """Update processed trades count from live engine/adapter snapshot."""
        self.set_trades_processed(count)

    def increment_trades_processed(self, delta: int = 1) -> int:
        """Increment the processed trades counter by delta.

        Args:
            delta: Non-negative integer to increment by (default: 1).

        Returns:
            The updated counter value.

        Raises:
            ValueError: If delta is negative.
        """
        try:
            int_delta = int(delta)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Increment delta must be an integer, got: {delta}") from err
        if int_delta < 0:
            raise ValueError(f"Increment delta cannot be negative: {delta}")
        self.trades_processed += int_delta
        return self.trades_processed

    def record_trade_execution(
        self,
        latency_us: Optional[Union[float, int]] = None,
        latency_ns: Optional[Union[float, int]] = None,
        count: int = 1,
    ) -> int:
        """Record a trade execution event and optional execution latency sample.

        Args:
            latency_us: Measured trade execution latency in microseconds.
            latency_ns: Measured trade execution latency in nanoseconds.
            count: Number of executed trades (default: 1).

        Returns:
            The updated trades_processed count.
        """
        self.increment_trades_processed(count)

        sample_us: Optional[float] = None
        if latency_us is not None:
            try:
                sample_us = float(latency_us)
            except (ValueError, TypeError):
                sample_us = None
        elif latency_ns is not None:
            try:
                sample_us = float(latency_ns) / 1000.0
            except (ValueError, TypeError):
                sample_us = None

        if sample_us is not None and sample_us >= 0 and not (math.isnan(sample_us) or math.isinf(sample_us)):
            self._trade_latency_last_us = sample_us
            if len(self._trade_latency_samples) >= self._max_trade_latency_samples:
                self._trade_latency_samples.pop(0)
            self._trade_latency_samples.append(sample_us)

        return self.trades_processed

    def get_trade_latency_stats(self) -> Optional[Dict[str, float]]:
        """Return trade execution latency statistics computed from recorded samples.

        Returns:
            Dict with 'last', 'avg', 'min', 'max' (and 'p95' when >= 20 samples),
            all in microseconds. Returns None if no samples have been recorded.
        """
        return calculate_trade_latency_stats(self._trade_latency_samples)

    def get_trade_latency_display(self, decimals: int = 1) -> str:
        """Return formatted last trade execution latency for display."""
        if self._trade_latency_last_us is not None:
            val = (
                self._trade_latency_last_us * 1000.0
                if self._trade_latency_unit.lower() == "ns"
                else self._trade_latency_last_us
            )
            return format_trade_latency(val, unit=self._trade_latency_unit, decimals=decimals)
        return NO_SAMPLE_LATENCY

    def get_trade_latency_avg_display(self, decimals: int = 1) -> str:
        """Return formatted average trade execution latency for display."""
        stats = self.get_trade_latency_stats()
        if stats is not None and "avg" in stats:
            val = (
                stats["avg"] * 1000.0
                if self._trade_latency_unit.lower() == "ns"
                else stats["avg"]
            )
            return format_trade_latency(val, unit=self._trade_latency_unit, decimals=decimals)
        return NO_SAMPLE_LATENCY

    # ------------------------------------------------------------------
    # Whale order detection state management
    # ------------------------------------------------------------------

    def record_whale_order(self, whale: "WhaleOrderEvent") -> None:
        """Record a detected whale order event for dashboard display.

        Keeps the most recent event plus a bounded history ring.

        Args:
            whale: The whale order event to record.
        """
        self._last_whale_event = whale
        if len(self._whale_history) >= self._max_whale_history:
            self._whale_history.pop(0)
        self._whale_history.append(whale)

    def get_last_whale_event(self) -> "Optional[WhaleOrderEvent]":
        """Return the most recently detected whale order event, or None."""
        return self._last_whale_event

    def clear_whale_history(self) -> None:
        """Clear the whale order tracking state (last event and full history)."""
        self._last_whale_event = None
        self._whale_history.clear()

    def get_trade_latency_min_display(self, decimals: int = 1) -> str:
        """Return formatted minimum trade execution latency for display."""
        stats = self.get_trade_latency_stats()
        if stats is not None and "min" in stats:
            val = (
                stats["min"] * 1000.0
                if self._trade_latency_unit.lower() == "ns"
                else stats["min"]
            )
            return format_trade_latency(val, unit=self._trade_latency_unit, decimals=decimals)
        return NO_SAMPLE_LATENCY

    def get_trade_latency_max_display(self, decimals: int = 1) -> str:
        """Return formatted maximum trade execution latency for display."""
        stats = self.get_trade_latency_stats()
        if stats is not None and "max" in stats:
            val = (
                stats["max"] * 1000.0
                if self._trade_latency_unit.lower() == "ns"
                else stats["max"]
            )
            return format_trade_latency(val, unit=self._trade_latency_unit, decimals=decimals)
        return NO_SAMPLE_LATENCY

    def reset_trade_metrics(self) -> None:
        """Reset trade metrics and recorded trade latency samples."""
        self._trades_processed = 0
        self._trade_latency_last_us = None
        self._trade_latency_samples.clear()

    @property
    def throughput(self) -> Optional[float]:
        """Return the current throughput in orders/sec, or None if not yet sampled."""
        return self._throughput

    @throughput.setter
    def throughput(self, value: Optional[Union[float, int]]) -> None:
        """Set the throughput value directly.

        Raises:
            ValueError: If value is negative.
        """
        if value is None:
            self._throughput = None
            self._throughput_override = None
            return
        try:
            val = float(value)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Throughput must be a number, got: {value}") from err
        if val < 0:
            raise ValueError(f"Throughput cannot be negative: {value}")
        self._throughput = val
        self._throughput_override = None

    def set_throughput(self, value: Optional[Union[float, int, str]]) -> None:
        """Explicitly set throughput (number, string like 'DEMO' or 'N/A', or None)."""
        if isinstance(value, str):
            self._throughput = None
            self._throughput_override = value
        else:
            self.throughput = value

    def _update_throughput_ns(self, now_ns: int) -> Optional[float]:
        """Internal helper to calculate throughput using nanosecond timestamps."""
        if self._last_throughput_time_ns is None:
            self._last_throughput_time_ns = now_ns
            self._last_orders_count = self.orders_processed
            return self._throughput

        elapsed_ns = now_ns - self._last_throughput_time_ns

        # Invalid interval (e.g. clock jumped backwards): handle safely without crashing
        if elapsed_ns < 0:
            self._last_throughput_time_ns = now_ns
            self._last_orders_count = self.orders_processed
            return self._throughput

        # Zero elapsed time: avoid division by zero, return current value unchanged
        if elapsed_ns == 0:
            return self._throughput

        # Elapsed > 0: compute delta orders
        last_count = self._last_orders_count if self._last_orders_count is not None else 0
        delta_orders = self.orders_processed - last_count
        if delta_orders < 0:
            # Counter was reset or moved backwards; reset reference point safely
            self._last_orders_count = self.orders_processed
            self._last_throughput_time_ns = now_ns
            return self._throughput

        calc = calculate_throughput_ns(delta_orders, elapsed_ns)
        self._throughput = calc
        self._last_orders_count = self.orders_processed
        self._last_throughput_time_ns = now_ns
        return self._throughput

    def update_throughput_ns(self, current_time_ns: Optional[int] = None) -> Optional[float]:
        """Update throughput using monotonic nanosecond timestamps.

        Args:
            current_time_ns: Optional nanosecond timestamp override. If None, uses self._ns_clock().

        Returns:
            Updated throughput in orders/sec, or current throughput if elapsed_ns == 0.
        """
        if self._throughput_override is not None:
            return self._throughput

        try:
            now_ns = int(current_time_ns) if current_time_ns is not None else int(self._ns_clock())
        except Exception:
            return self._throughput

        return self._update_throughput_ns(now_ns)

    def update_throughput(
        self,
        current_time: Optional[Union[float, int]] = None,
        current_time_ns: Optional[int] = None,
    ) -> Optional[float]:
        """Calculate and update throughput based on processed orders delta and elapsed time.

        Args:
            current_time: Optional timestamp override in seconds (or nanoseconds if large integer).
            current_time_ns: Optional timestamp override in nanoseconds.

        Returns:
            The updated throughput value, or current value if elapsed time is zero.
        """
        if self._throughput_override is not None:
            return self._throughput

        if current_time_ns is not None:
            return self.update_throughput_ns(current_time_ns)

        if current_time is not None and isinstance(current_time, int) and current_time > 100_000_000_000:
            return self.update_throughput_ns(current_time)

        if self._has_custom_ns_clock and not self._has_custom_clock and current_time is None:
            return self.update_throughput_ns()

        try:
            now = float(current_time) if current_time is not None else float(self._clock())
        except Exception:
            return self._throughput

        if self._last_throughput_time is None:
            self._last_throughput_time = now
            self._last_orders_count = self.orders_processed
            return self._throughput

        elapsed = now - self._last_throughput_time

        # Invalid interval (e.g. clock jumped backwards): handle safely without crashing
        if elapsed < 0:
            self._last_throughput_time = now
            self._last_orders_count = self.orders_processed
            return self._throughput

        # Zero elapsed time: avoid division by zero, return current value unchanged
        if elapsed == 0:
            return self._throughput

        # Elapsed > 0: compute delta orders
        last_count = self._last_orders_count if self._last_orders_count is not None else 0
        delta_orders = self.orders_processed - last_count
        if delta_orders < 0:
            # Counter was reset or moved backwards; reset reference point safely
            self._last_orders_count = self.orders_processed
            self._last_throughput_time = now
            return self._throughput

        calc = calculate_throughput(delta_orders, elapsed)
        self._throughput = calc
        self._last_orders_count = self.orders_processed
        self._last_throughput_time = now
        return self._throughput

    def update_throughput_from_metrics(
        self,
        orders_count: int,
        timestamp_ns: Optional[int] = None,
        timestamp_s: Optional[float] = None,
    ) -> Optional[float]:
        """Update processed orders count and calculate throughput from supplied timestamp.

        Args:
            orders_count: Current cumulative count of processed orders.
            timestamp_ns: Optional nanosecond monotonic timestamp.
            timestamp_s: Optional second monotonic timestamp.

        Returns:
            Updated throughput in orders/sec.
        """
        self.set_orders_processed(orders_count)
        if timestamp_ns is not None:
            return self.update_throughput_ns(timestamp_ns)
        if timestamp_s is not None:
            return self.update_throughput(current_time=timestamp_s)
        return self.update_throughput()

    def update_from_consumer_stats(self, stats: Any) -> Optional[float]:
        """Update orders processed and throughput from consumer or adapter stats.

        Accepts objects or dicts exposing total_orders_read / orders_processed and
        rate or timestamp information.
        """
        if stats is None:
            return self._throughput

        orders = None
        if isinstance(stats, dict):
            orders = stats.get("total_orders_read", stats.get("orders_processed", stats.get("total_orders")))
        else:
            for attr in ("total_orders_read", "orders_processed", "total_orders"):
                if hasattr(stats, attr):
                    orders = getattr(stats, attr)
                    break

        if orders is not None:
            try:
                self.set_orders_processed(int(orders))
            except (ValueError, TypeError):
                pass

        rate = None
        if isinstance(stats, dict):
            rate = stats.get("current_rate", stats.get("throughput", stats.get("avg_rate")))
        else:
            for attr in ("current_rate", "throughput", "avg_rate"):
                if hasattr(stats, attr):
                    rate = getattr(stats, attr)
                    break

        if rate is not None:
            try:
                f_rate = float(rate)
                if f_rate >= 0 and not (math.isnan(f_rate) or math.isinf(f_rate)):
                    self.throughput = round(f_rate, 2)
                    return self._throughput
            except (ValueError, TypeError):
                pass

        return self.update_throughput()

    def get_throughput(self) -> Optional[float]:
        """Return the current throughput in orders/sec."""
        return self._throughput

    def get_throughput_display(self, include_unit: bool = False) -> str:
        """Return the formatted throughput string for display."""
        if self._throughput_override is not None:
            return self._throughput_override

        if self._throughput is not None:
            return format_throughput(self._throughput, include_unit=include_unit)

        return DEMO_THROUGHPUT if self.is_sample_data else NO_SAMPLE_THROUGHPUT

    def reset_throughput(self) -> None:
        """Reset throughput calculation state and baseline clock."""
        self._throughput = None
        self._throughput_override = None
        self._last_throughput_time = None
        self._last_throughput_time_ns = None
        self._last_orders_count = None

    @property
    def status_message(self) -> str:
        """Return the status message, reflecting override, live feed status, or demo mode."""
        if self._status_message_override is not None:
            return self._status_message_override
        if self.live_feed is not None:
            if getattr(self.live_feed, "is_connected", False):
                return "Live: Connected"
            return "Live: Disconnected"
        if self.is_sample_data:
            return f"{STATUS_MESSAGE} (Demo: Sample Data)"
        return STATUS_MESSAGE

    @status_message.setter
    def status_message(self, value: Optional[str]) -> None:
        """Explicitly override the status message."""
        self._status_message_override = value

    def set_buy_orders(self, orders: List[Any], is_sample: bool = False) -> None:
        """Update the buy orders collection and data source flag."""
        self.buy_orders = list(orders)
        self.is_buy_sample_data = is_sample
        self.is_sample_data = self.is_buy_sample_data or self.is_sell_sample_data

    def update_buy_orders(self, orders: List[Any], is_sample: bool = False) -> None:
        """Alias for set_buy_orders, ready for live engine snapshot integration."""
        self.set_buy_orders(orders, is_sample=is_sample)

    def set_sell_orders(self, orders: List[Any], is_sample: bool = False) -> None:
        """Update the sell orders collection and data source flag."""
        self.sell_orders = list(orders)
        self.is_sell_sample_data = is_sample
        self.is_sample_data = self.is_buy_sample_data or self.is_sell_sample_data

    def update_sell_orders(self, orders: List[Any], is_sample: bool = False) -> None:
        """Alias for set_sell_orders, ready for live engine snapshot integration."""
        self.set_sell_orders(orders, is_sample=is_sample)

    def get_buy_depth(self, max_levels: int = 5) -> List[PriceLevel]:
        """Return the current top BUY order-book depth up to max_levels levels (highest price first)."""
        return calculate_buy_depth(self.buy_orders, max_levels=max_levels)

    def get_sell_depth(self, max_levels: int = 5) -> List[PriceLevel]:
        """Return the current top SELL order-book depth up to max_levels levels (lowest price first)."""
        return calculate_sell_depth(self.sell_orders, max_levels=max_levels)

    def get_depth_rows(
        self, max_levels: int = 5
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """Return formatted (bid_rows, ask_rows) for the top max_levels depth."""
        return (
            format_depth_rows(self.get_buy_depth(max_levels=max_levels), max_levels=max_levels),
            format_depth_rows(self.get_sell_depth(max_levels=max_levels), max_levels=max_levels),
        )

    # ------------------------------------------------------------------
    # Size checking
    # ------------------------------------------------------------------

    def is_terminal_size_sufficient(self, rows: int, cols: int) -> bool:
        """Verify whether the terminal window meets minimum required dimensions."""
        return rows >= self.config.min_rows and cols >= self.config.min_cols

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def handle_input(self, key: int) -> bool:
        """Process a single keyboard input.

        Args:
            key: The character code returned by curses getch().

        Returns:
            True if the dashboard should continue running, False if it should quit.
        """
        if key in (ord("q"), ord("Q")):
            self.is_running = False
            return False
        return True

    # ------------------------------------------------------------------
    # Noninteractive text generation (used by launcher --non-interactive)
    # ------------------------------------------------------------------

    def get_display_lines(
        self,
        rows: int,
        cols: int,
        buy_orders: Optional[List[Any]] = None,
        sell_orders: Optional[List[Any]] = None,
        orders_processed: Optional[int] = None,
        throughput: Optional[Union[float, int, str]] = None,
        trades_processed: Optional[Union[int, str]] = None,
        trade_latency: Optional[Union[float, int, str]] = None,
        trade_latency_avg: Optional[Union[float, int, str]] = None,
        trade_latency_min: Optional[Union[float, int, str]] = None,
        trade_latency_max: Optional[Union[float, int, str]] = None,
        trade_latency_unit: Optional[str] = None,
    ) -> List[str]:
        """Generate all display lines for the current state.

        Useful for noninteractive testing and headless validation.
        Latency values reflect inter-event spacing between record_order_processed()
        calls — not full end-to-end latency.
        """
        if not self.is_terminal_size_sufficient(rows, cols):
            return [
                "Screen too small!",
                f"Min: {self.config.min_cols}x{self.config.min_rows}",
                f"Current: {cols}x{rows}",
                QUIT_MESSAGE,
            ]

        if self.live_feed is not None and buy_orders is None and sell_orders is None:
            try:
                self.live_feed.sync_to_dashboard()
            except Exception:
                pass

        b_orders = self.buy_orders if buy_orders is None else buy_orders
        s_orders = self.sell_orders if sell_orders is None else sell_orders

        best_bid_obj = calculate_best_bid(b_orders)
        best_bid_str = format_best_bid_price(best_bid_obj.price)
        bid_qty_str = format_best_bid_qty(best_bid_obj.quantity)

        best_ask_obj = calculate_best_ask(s_orders)
        best_ask_str = format_best_ask_price(best_ask_obj.price)
        ask_qty_str = format_best_ask_qty(best_ask_obj.quantity)

        spread_val = calculate_spread(best_ask_obj, best_bid_obj)
        spread_str = format_spread(spread_val)

        # Order book depth (top 5 levels)
        buy_depth = calculate_buy_depth(b_orders, max_levels=5)
        sell_depth = calculate_sell_depth(s_orders, max_levels=5)
        bid_rows = format_depth_rows(buy_depth, max_levels=5)
        ask_rows = format_depth_rows(sell_depth, max_levels=5)

        orders_cnt = self.orders_processed if orders_processed is None else orders_processed
        total_orders_str = format_orders_processed(orders_cnt)

        if throughput is not None:
            if isinstance(throughput, (int, float)) and not isinstance(throughput, bool):
                throughput_str = format_throughput(throughput)
            else:
                throughput_str = str(throughput)
        else:
            self.update_throughput()
            throughput_str = self.get_throughput_display()

        # Latency strings — read from state, never updated here
        latency_str = self.get_latency_display()
        latency_avg_str = self.get_latency_avg_display()

        width = min(cols - 4, 72)
        lines: List[str] = []
        lines += build_header_lines(width, status=self.status_message)
        lines.append("")
        lines += build_market_summary_lines(
            width,
            best_bid=best_bid_str,
            best_ask=best_ask_str,
            spread=spread_str,
            bid_qty=bid_qty_str,
            ask_qty=ask_qty_str,
        )
        lines.append("")
        lines += build_order_book_lines(width, bid_rows=bid_rows, ask_rows=ask_rows)
        lines.append("")
        # Trade execution metrics
        trades_cnt = self.trades_processed if trades_processed is None else trades_processed
        if isinstance(trades_cnt, int):
            trades_str = format_trades_processed(trades_cnt)
        elif trades_cnt is None:
            trades_str = NO_SAMPLE_LATENCY
        else:
            trades_str = str(trades_cnt)

        t_unit = trade_latency_unit or self._trade_latency_unit
        if trade_latency is not None:
            trade_lat_str = (
                format_trade_latency(trade_latency, unit=t_unit)
                if isinstance(trade_latency, (int, float)) and not isinstance(trade_latency, bool)
                else str(trade_latency)
            )
        else:
            trade_lat_str = self.get_trade_latency_display()

        if trade_latency_avg is not None:
            trade_lat_avg_str = (
                format_trade_latency(trade_latency_avg, unit=t_unit)
                if isinstance(trade_latency_avg, (int, float)) and not isinstance(trade_latency_avg, bool)
                else str(trade_latency_avg)
            )
        else:
            trade_lat_avg_str = self.get_trade_latency_avg_display()

        if trade_latency_min is not None:
            trade_lat_min_str = (
                format_trade_latency(trade_latency_min, unit=t_unit)
                if isinstance(trade_latency_min, (int, float)) and not isinstance(trade_latency_min, bool)
                else str(trade_latency_min)
            )
        else:
            trade_lat_min_str = self.get_trade_latency_min_display()

        if trade_latency_max is not None:
            trade_lat_max_str = (
                format_trade_latency(trade_latency_max, unit=t_unit)
                if isinstance(trade_latency_max, (int, float)) and not isinstance(trade_latency_max, bool)
                else str(trade_latency_max)
            )
        else:
            trade_lat_max_str = self.get_trade_latency_max_display()

        lines += build_performance_lines(
            width,
            total_orders=total_orders_str,
            throughput=throughput_str,
            latency=latency_str,
            latency_avg=latency_avg_str,
        )
        lines.append("")
        lines += build_trade_execution_lines(
            width,
            trades_processed=trades_str,
            latency=trade_lat_str,
            latency_avg=trade_lat_avg_str,
            latency_min=trade_lat_min_str,
            latency_max=trade_lat_max_str,
            unit=t_unit,
        )
        lines.append("")
        whale_lines = build_whale_alert_lines(width, whale=self._last_whale_event)
        if whale_lines:
            lines += whale_lines
            lines.append("")
        lines += build_footer_lines(width)
        return lines

    # ------------------------------------------------------------------
    # Curses helpers
    # ------------------------------------------------------------------

    def _safe_addstr(
        self,
        stdscr: Any,
        y: int,
        x: int,
        text: str,
        attr: int = 0,
    ) -> None:
        """Safely write a string to the curses window, preventing edge crashes."""
        if curses is None and not hasattr(stdscr, "addstr"):
            return
        try:
            max_y, max_x = stdscr.getmaxyx()
            if y < 0 or y >= max_y or x < 0 or x >= max_x:
                return

            available_space = max_x - x
            if available_space <= 0:
                return

            # Avoid writing to the very bottom-right cell in curses, which raises error
            if y == max_y - 1 and len(text) >= available_space:
                clipped = text[: available_space - 1]
            else:
                clipped = text[:available_space]

            if clipped:
                stdscr.addstr(y, x, clipped, attr)
        except Exception:
            # Swallow any terminal writing exception on rapid resize
            pass

    def _has_colors_safe(self) -> bool:
        """Safely check if curses has color support without crashing uninitialized sessions."""
        if curses is None:
            return False
        try:
            return bool(curses.has_colors())
        except Exception:
            return False

    def _init_colors(self) -> None:
        """Initialize curses color pairs safely if supported by terminal."""
        if not self._has_colors_safe():
            return

        try:
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except Exception:
                bg = curses.COLOR_BLACK

            curses.init_pair(1, curses.COLOR_CYAN, bg)      # Title
            curses.init_pair(2, curses.COLOR_GREEN, bg)     # Status / values
            curses.init_pair(3, curses.COLOR_YELLOW, bg)    # Quit / footer
            curses.init_pair(4, curses.COLOR_WHITE, bg)     # Subtitle & borders
            curses.init_pair(5, curses.COLOR_MAGENTA, bg)   # Section headers
            curses.init_pair(6, curses.COLOR_CYAN, bg)      # BID column
            curses.init_pair(7, curses.COLOR_RED, bg)       # ASK column
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _build_attrs(self) -> Dict[str, int]:
        """Build rendering attribute map for curses text styles."""
        attrs: Dict[str, int] = {
            "title": 0, "subtitle": 0, "border": 0,
            "section": 0, "label": 0, "value": 0,
            "bid": 0, "ask": 0, "quit": 0,
        }
        if curses is None:
            return attrs

        bold = getattr(curses, "A_BOLD", 0)
        dim = getattr(curses, "A_DIM", 0)
        attrs["title"] = bold
        attrs["section"] = bold
        attrs["border"] = dim
        attrs["quit"] = dim

        if self._has_colors_safe():
            try:
                attrs["title"] = bold | curses.color_pair(1)
                attrs["subtitle"] = curses.color_pair(4)
                attrs["border"] = dim | curses.color_pair(4)
                attrs["section"] = bold | curses.color_pair(5)
                attrs["value"] = curses.color_pair(2)
                attrs["bid"] = curses.color_pair(6)
                attrs["ask"] = curses.color_pair(7)
                attrs["quit"] = dim | curses.color_pair(3)
            except Exception:
                pass
        return attrs

    def render(
        self,
        stdscr: Any,
        buy_orders: Optional[List[Any]] = None,
        sell_orders: Optional[List[Any]] = None,
        orders_processed: Optional[int] = None,
        throughput: Optional[Union[float, int, str]] = None,
        trades_processed: Optional[Union[int, str]] = None,
        trade_latency: Optional[Union[float, int, str]] = None,
        trade_latency_avg: Optional[Union[float, int, str]] = None,
        trade_latency_min: Optional[Union[float, int, str]] = None,
        trade_latency_max: Optional[Union[float, int, str]] = None,
        trade_latency_unit: Optional[str] = None,
    ) -> None:
        """Render a single frame of the dashboard onto the curses window."""
        try:
            stdscr.erase()
        except Exception:
            pass

        try:
            max_y, max_x = stdscr.getmaxyx()
        except Exception:
            return

        # Small-terminal fallback
        if not self.is_terminal_size_sufficient(max_y, max_x):
            lines = self.get_display_lines(
                max_y,
                max_x,
                buy_orders=buy_orders,
                sell_orders=sell_orders,
                orders_processed=orders_processed,
                throughput=throughput,
                trades_processed=trades_processed,
                trade_latency=trade_latency,
                trade_latency_avg=trade_latency_avg,
                trade_latency_min=trade_latency_min,
                trade_latency_max=trade_latency_max,
                trade_latency_unit=trade_latency_unit,
            )
            for idx, line in enumerate(lines):
                self._safe_addstr(stdscr, idx, 0, line)
            try:
                stdscr.refresh()
            except Exception:
                pass
            return

        if self.live_feed is not None and buy_orders is None and sell_orders is None:
            try:
                self.live_feed.sync_to_dashboard()
            except Exception:
                pass

        b_orders = self.buy_orders if buy_orders is None else buy_orders
        s_orders = self.sell_orders if sell_orders is None else sell_orders

        best_bid_obj = calculate_best_bid(b_orders)
        best_bid_str = format_best_bid_price(best_bid_obj.price)
        bid_qty_str = format_best_bid_qty(best_bid_obj.quantity)

        best_ask_obj = calculate_best_ask(s_orders)
        best_ask_str = format_best_ask_price(best_ask_obj.price)
        ask_qty_str = format_best_ask_qty(best_ask_obj.quantity)

        spread_val = calculate_spread(best_ask_obj, best_bid_obj)
        spread_str = format_spread(spread_val)

        # Order book depth (top 5 levels)
        buy_depth = calculate_buy_depth(b_orders, max_levels=5)
        sell_depth = calculate_sell_depth(s_orders, max_levels=5)
        bid_rows = format_depth_rows(buy_depth, max_levels=5)
        ask_rows = format_depth_rows(sell_depth, max_levels=5)

        attrs = self._build_attrs()
        width = min(max_x - 4, 72)
        start_x = 2
        y = 0

        def put(text: str, attr: int = 0) -> None:
            nonlocal y
            self._safe_addstr(stdscr, y, start_x, text, attr)
            y += 1

        def blank() -> None:
            nonlocal y
            if max_y >= 45:
                y += 1

        border = "=" * width
        divider = "-" * width
        col_w = max(width - 4, 10)
        half = max((width - 3) // 2, 20)

        # ---- Header ----
        put(border, attrs["border"])
        put(f"  {APP_TITLE}", attrs["title"])
        put(f"  {APP_SUBTITLE}", attrs["subtitle"])
        put(f"  [{self.status_message}]", attrs["value"])
        put(border, attrs["border"])
        blank()

        # ---- Market Summary ----
        put(f"  {SECTION_MARKET_SUMMARY}", attrs["section"])
        put(divider, attrs["border"])
        put(f"  {LABEL_BEST_BID:<{col_w - 10}} {best_bid_str:>8}", attrs["label"])
        put(f"  {LABEL_BID_QTY:<{col_w - 10}} {bid_qty_str:>8}", attrs["label"])
        put(f"  {LABEL_BEST_ASK:<{col_w - 10}} {best_ask_str:>8}", attrs["label"])
        put(f"  {LABEL_ASK_QTY:<{col_w - 10}} {ask_qty_str:>8}", attrs["label"])
        put(f"  {LABEL_SPREAD:<{col_w - 10}} {spread_str:>8}", attrs["label"])
        put(divider, attrs["border"])
        blank()

        # ---- Order Book ----
        put(f"  {SECTION_ORDER_BOOK}", attrs["section"])
        put(divider, attrs["border"])
        buy_hdr = f"  {SECTION_BUY_ORDERS}"
        put(f"{buy_hdr:<{half + 2}}  {SECTION_SELL_ORDERS}", attrs["section"])
        spacing = max(half - 18, 0)
        sub_hdr = (
            f"  {'Price':>8}  {'Qty':>6}"
            + " " * spacing
            + f"  {'Price':>8}  {'Qty':>6}"
        )
        put(sub_hdr, attrs["label"])

        max_rows = max(len(bid_rows), len(ask_rows))
        for i in range(max_rows):
            bp, bq = bid_rows[i] if i < len(bid_rows) else (PLACEHOLDER, PLACEHOLDER)
            ap, aq = ask_rows[i] if i < len(ask_rows) else (PLACEHOLDER, PLACEHOLDER)
            bid_cell = f"  {bp:>8}  {bq:>6}"
            ask_cell = f"  {ap:>8}  {aq:>6}"
            self._safe_addstr(stdscr, y, start_x, f"{bid_cell:<{half + 2}}", attrs["bid"])
            self._safe_addstr(stdscr, y, start_x + half + 2, ask_cell, attrs["ask"])
            y += 1

        put(divider, attrs["border"])
        blank()

        orders_cnt = self.orders_processed if orders_processed is None else orders_processed
        total_orders_str = format_orders_processed(orders_cnt)

        if throughput is not None:
            if isinstance(throughput, (int, float)) and not isinstance(throughput, bool):
                throughput_str = format_throughput(throughput)
            else:
                throughput_str = str(throughput)
        else:
            self.update_throughput()
            throughput_str = self.get_throughput_display()

        # Latency strings — read from state, never updated in the render loop
        latency_str = self.get_latency_display()
        latency_avg_str = self.get_latency_avg_display()

        # Trade execution strings
        trades_cnt = self.trades_processed if trades_processed is None else trades_processed
        if isinstance(trades_cnt, int):
            trades_str = format_trades_processed(trades_cnt)
        elif trades_cnt is None:
            trades_str = NO_SAMPLE_LATENCY
        else:
            trades_str = str(trades_cnt)

        t_unit = trade_latency_unit or self._trade_latency_unit
        if trade_latency is not None:
            trade_lat_str = (
                format_trade_latency(trade_latency, unit=t_unit)
                if isinstance(trade_latency, (int, float)) and not isinstance(trade_latency, bool)
                else str(trade_latency)
            )
        else:
            trade_lat_str = self.get_trade_latency_display()

        if trade_latency_avg is not None:
            trade_lat_avg_str = (
                format_trade_latency(trade_latency_avg, unit=t_unit)
                if isinstance(trade_latency_avg, (int, float)) and not isinstance(trade_latency_avg, bool)
                else str(trade_latency_avg)
            )
        else:
            trade_lat_avg_str = self.get_trade_latency_avg_display()

        if trade_latency_min is not None:
            trade_lat_min_str = (
                format_trade_latency(trade_latency_min, unit=t_unit)
                if isinstance(trade_latency_min, (int, float)) and not isinstance(trade_latency_min, bool)
                else str(trade_latency_min)
            )
        else:
            trade_lat_min_str = self.get_trade_latency_min_display()

        if trade_latency_max is not None:
            trade_lat_max_str = (
                format_trade_latency(trade_latency_max, unit=t_unit)
                if isinstance(trade_latency_max, (int, float)) and not isinstance(trade_latency_max, bool)
                else str(trade_latency_max)
            )
        else:
            trade_lat_max_str = self.get_trade_latency_max_display()

        if t_unit.lower() == "us":
            lbl_trade_last = LABEL_TRADE_LATENCY
            lbl_trade_avg = LABEL_TRADE_LATENCY_AVG
            lbl_trade_min = LABEL_TRADE_LATENCY_MIN
            lbl_trade_max = LABEL_TRADE_LATENCY_MAX
        else:
            lbl_trade_last = f"Last Execution Latency ({t_unit})"
            lbl_trade_avg = f"Avg Execution Latency ({t_unit})"
            lbl_trade_min = f"Min Execution Latency ({t_unit})"
            lbl_trade_max = f"Max Execution Latency ({t_unit})"

        # ---- Performance Metrics ----
        put(f"  {SECTION_PERFORMANCE}", attrs["section"])
        put(divider, attrs["border"])
        put(f"  {LABEL_TOTAL_ORDERS:<{col_w - 10}} {total_orders_str:>8}", attrs["label"])
        put(f"  {LABEL_THROUGHPUT:<{col_w - 10}} {throughput_str:>8}", attrs["label"])
        put(f"  {LABEL_LATENCY:<{col_w - 10}} {latency_str:>8}", attrs["label"])
        put(f"  {LABEL_LATENCY_AVG:<{col_w - 10}} {latency_avg_str:>8}", attrs["label"])
        put(divider, attrs["border"])
        blank()

        # ---- Trade Execution Metrics ----
        put(f"  {SECTION_TRADE_EXECUTION}", attrs["section"])
        put(divider, attrs["border"])
        put(f"  {LABEL_TRADES_PROCESSED:<{col_w - 10}} {trades_str:>8}", attrs["label"])
        put(f"  {lbl_trade_last:<{col_w - 10}} {trade_lat_str:>8}", attrs["label"])
        put(f"  {lbl_trade_avg:<{col_w - 10}} {trade_lat_avg_str:>8}", attrs["label"])
        put(f"  {lbl_trade_min:<{col_w - 10}} {trade_lat_min_str:>8}", attrs["label"])
        put(f"  {lbl_trade_max:<{col_w - 10}} {trade_lat_max_str:>8}", attrs["label"])
        put(divider, attrs["border"])
        blank()

        # ---- Whale Order Alert ----
        _whale = self._last_whale_event
        if _whale is not None:
            _whale_lines = build_whale_alert_lines(width, whale=_whale)
            for _wl in _whale_lines:
                _stripped = _wl.strip()
                if _stripped.startswith("\u26a1"):
                    put(_wl, attrs["quit"] | (curses.A_BOLD if curses is not None else 0))
                elif _stripped.startswith("-") or _stripped.startswith("="):
                    put(_wl, attrs["border"])
                else:
                    put(_wl, attrs["value"])
            blank()

        # ---- Footer ----
        if y + 2 > max_y:
            y = max_y - 2
        put(f"  {QUIT_MESSAGE}", attrs["quit"])
        put(border, attrs["border"])

        try:
            stdscr.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------

    def run_curses(self, stdscr: Any, max_iterations: Optional[int] = None) -> None:
        """Main event and rendering loop executed inside curses wrapper.

        Args:
            stdscr: Curses standard screen window.
            max_iterations: Optional limit on loops, useful for testing or timeouts.
        """
        if curses is not None:
            try:
                curses.curs_set(0)
            except Exception:
                pass

        self._init_colors()

        if hasattr(stdscr, "timeout"):
            stdscr.timeout(self.config.refresh_interval_ms)

        if self.live_feed is not None and not getattr(self.live_feed, "is_running", False):
            self.live_feed.start()

        self.is_running = True
        self.frame_count = 0

        try:
            while self.is_running:
                self.render(stdscr)
                self.frame_count += 1

                if max_iterations is not None and self.frame_count >= max_iterations:
                    break

                try:
                    key = stdscr.getch() if hasattr(stdscr, "getch") else -1
                except Exception:
                    key = -1

                if key != -1:
                    self.handle_input(key)
        finally:
            if self.live_feed is not None:
                try:
                    self.live_feed.stop()
                except Exception:
                    pass
            self.is_running = False

    def close(self) -> None:
        """Shut down the dashboard and stop attached live feed."""
        self.is_running = False
        if self.live_feed is not None:
            try:
                self.live_feed.stop()
            except Exception:
                pass

    def __enter__(self) -> TerminalDashboard:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def run(self, max_iterations: Optional[int] = None) -> None:
        """Launch the dashboard with automatic curses terminal lifecycle management."""
        if curses is None:
            msg = (
                "The curses library is not available in this Python environment.\n"
                "On Windows, please install windows-curses:\n"
                "    pip install windows-curses"
            )
            raise RuntimeError(msg)

        try:
            curses.wrapper(lambda stdscr: self.run_curses(stdscr, max_iterations=max_iterations))
        except KeyboardInterrupt:
            # Exit gracefully on Ctrl+C
            self.is_running = False
        except curses.error as err:
            raise RuntimeError(f"Curses terminal initialization error: {err}") from err
