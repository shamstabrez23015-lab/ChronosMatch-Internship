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
LABEL_THROUGHPUT = "Throughput (orders/sec)"
LABEL_LATENCY = "Latency (microseconds)"

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
    {"order_id": 102, "side": 1, "price": 505.0, "quantity": 80, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 103, "side": 1, "price": 510.0, "quantity": 100, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 104, "side": 1, "price": 510.0, "quantity": 50, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 105, "side": 1, "price": 495.0, "quantity": 120, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 106, "side": 1, "price": 490.0, "quantity": 150, "source": "DEMO_SAMPLE_DATA"},
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

        qty_val = order.get("quantity", order.get("qty", 0))
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
        if len(order) == 4:
            side = order[1]
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
    if hasattr(order, "quantity"):
        try:
            qty = int(getattr(order, "quantity"))
        except (ValueError, TypeError):
            return None
    elif hasattr(order, "qty"):
        try:
            qty = int(getattr(order, "qty"))
        except (ValueError, TypeError):
            return None
    else:
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
            if p > 0 and q > 0:
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
    depth: Optional[List[PriceLevel]],
    max_levels: int = 5,
    placeholder: str = PLACEHOLDER,
) -> List[Tuple[str, str]]:
    """Format price depth levels into string (price, quantity) tuples for display.

    If depth contains fewer than max_levels, remaining rows are padded with placeholder.

    Args:
        depth: List of PriceLevel instances.
        max_levels: Target number of display rows (default: 5).
        placeholder: String to display for empty levels (default: PLACEHOLDER).

    Returns:
        List of (price_str, quantity_str) tuples of length max_levels.
    """
    rows: List[Tuple[str, str]] = []
    levels = depth or []
    for level in levels[:max_levels]:
        rows.append((format_price(level.price), str(level.quantity)))

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
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration parameters for the terminal dashboard."""

    refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS
    min_rows: int = MIN_TERMINAL_ROWS
    min_cols: int = MIN_TERMINAL_COLS


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
    orders_processed: Optional[Union[str, int]] = None,
) -> List[str]:
    """Return Performance Metrics section lines.

    Args:
        width: Available content width in characters.
        total_orders: Total processed orders (integer, formatted string, or PLACEHOLDER).
        throughput: Throughput metric (number, formatted string, or PLACEHOLDER).
        latency: Latency metric string.
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
        throughput: Optional[Union[float, int, str]] = None,
    ) -> None:
        """Initialize the dashboard with optional configuration, order data, counter, clock, and throughput."""
        self.config = config or DashboardConfig()
        self.is_running = False
        self.frame_count = 0
        self.use_sample_data = use_sample_data

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
        self._last_throughput_time: Optional[float] = None
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

    def record_order_processed(self, order: Optional[Any] = None) -> int:
        """Record a single processed order event.

        The counter represents the number of orders accepted or processed by the engine,
        not the number of trades executed. A single order creating multiple fills counts
        as one processed order.

        Args:
            order: Optional order representation (dict, object, tuple, or None).
                   If an order_id is present, duplicate events for the same order are ignored.

        Returns:
            The updated orders_processed count.
        """
        order_id = _extract_order_id(order)
        if order_id is not None:
            if order_id in self._processed_order_ids:
                return self.orders_processed
            self._processed_order_ids.add(order_id)

        self.increment_orders_processed(1)
        return self.orders_processed

    def on_order_processed(self, order: Optional[Any] = None) -> int:
        """Event handler callback for order processed events (alias for record_order_processed)."""
        return self.record_order_processed(order)

    def reset_orders_processed(self) -> None:
        """Reset the processed orders counter and seen order IDs to zero/empty."""
        self._orders_processed = 0
        self._processed_order_ids.clear()
        self.reset_throughput()

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

    def update_throughput(self, current_time: Optional[float] = None) -> Optional[float]:
        """Calculate and update throughput based on processed orders delta and elapsed time.

        Args:
            current_time: Optional timestamp override in seconds. If None, uses self._clock().

        Returns:
            The updated throughput value, or current value if elapsed time is zero.
        """
        if self._throughput_override is not None:
            return self._throughput

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
        self._last_orders_count = None

    @property
    def status_message(self) -> str:
        """Return the status message, clearly labeling demo sample data when active."""
        if self.is_sample_data:
            return f"{STATUS_MESSAGE} (Demo: Sample Data)"
        return STATUS_MESSAGE

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
    ) -> List[str]:
        """Generate all display lines for the current state.

        Useful for noninteractive testing and headless validation.
        """
        if not self.is_terminal_size_sufficient(rows, cols):
            return [
                "Screen too small!",
                f"Min: {self.config.min_cols}x{self.config.min_rows}",
                f"Current: {cols}x{rows}",
                QUIT_MESSAGE,
            ]

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
        lines += build_performance_lines(
            width,
            total_orders=total_orders_str,
            throughput=throughput_str,
        )
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
        if curses is None:
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
            )
            for idx, line in enumerate(lines):
                self._safe_addstr(stdscr, idx, 0, line)
            try:
                stdscr.refresh()
            except Exception:
                pass
            return

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

        # ---- Performance Metrics ----
        put(f"  {SECTION_PERFORMANCE}", attrs["section"])
        put(divider, attrs["border"])
        put(f"  {LABEL_TOTAL_ORDERS:<{col_w - 10}} {total_orders_str:>8}", attrs["label"])
        put(f"  {LABEL_THROUGHPUT:<{col_w - 10}} {throughput_str:>8}", attrs["label"])
        put(f"  {LABEL_LATENCY:<{col_w - 10}} {PLACEHOLDER:>8}", attrs["label"])
        put(divider, attrs["border"])
        blank()

        # ---- Footer ----
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

        self.is_running = True
        self.frame_count = 0

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
