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
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple, Union

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
LABEL_THROUGHPUT = "Throughput (orders/sec)"
LABEL_LATENCY = "Latency (microseconds)"

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


# Clearly labeled demonstration BUY orders (fixed sample data for testing & demo mode)
SAMPLE_BUY_ORDERS: List[Dict[str, Any]] = [
    {"order_id": 101, "side": 1, "price": 500.0, "quantity": 100, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 102, "side": 1, "price": 505.0, "quantity": 80, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 103, "side": 1, "price": 510.0, "quantity": 100, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 104, "side": 1, "price": 510.0, "quantity": 50, "source": "DEMO_SAMPLE_DATA"},
]

# Clearly labeled demonstration SELL orders (fixed sample data for testing & demo mode)
SAMPLE_SELL_ORDERS: List[Dict[str, Any]] = [
    {"order_id": 201, "side": 2, "price": 515.0, "quantity": 100, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 202, "side": 2, "price": 505.0, "quantity": 40, "source": "DEMO_SAMPLE_DATA"},
    {"order_id": 203, "side": 2, "price": 510.0, "quantity": 80, "source": "DEMO_SAMPLE_DATA"},
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


def calculate_best_bid(orders: Optional[Iterable[Any]]) -> BestBid:
    """Calculate the Best Bid (highest BUY price and aggregated quantity).

    Finds the highest BUY price available in the collection of BUY orders and sums
    the quantities of all orders posted at that exact highest price level.

    Args:
        orders: An iterable collection of BUY orders in dict, tuple, or object form.

    Returns:
        BestBid(price=None, quantity=0) if collection is empty or contains no valid bids.
        BestBid(price=highest_price, quantity=aggregated_quantity) otherwise.
    """
    if orders is None:
        return BestBid(price=None, quantity=0)

    extracted: List[Tuple[float, int]] = []
    for order in orders:
        parsed = _extract_order_price_qty(order, expected_side=1)
        if parsed is not None:
            p, q = parsed
            if p > 0 and q > 0:
                extracted.append((p, q))

    if not extracted:
        return BestBid(price=None, quantity=0)

    # Find highest buy price
    max_price = max(p for p, _ in extracted)

    # Aggregate quantities for all orders matching highest price (within float precision)
    aggregated_qty = sum(
        q for p, q in extracted
        if abs(p - max_price) < 1e-6
    )

    return BestBid(price=max_price, quantity=aggregated_qty)


def calculate_best_ask(orders: Optional[Iterable[Any]]) -> BestAsk:
    """Calculate the Best Ask (lowest SELL price and aggregated quantity).

    Finds the lowest SELL price available in the collection of SELL orders and sums
    the quantities of all orders posted at that exact lowest price level.

    Args:
        orders: An iterable collection of SELL orders in dict, tuple, or object form.

    Returns:
        BestAsk(price=None, quantity=0) if collection is empty or contains no valid asks.
        BestAsk(price=lowest_price, quantity=aggregated_quantity) otherwise.
    """
    if orders is None:
        return BestAsk(price=None, quantity=0)

    extracted: List[Tuple[float, int]] = []
    for order in orders:
        parsed = _extract_order_price_qty(order, expected_side=2)
        if parsed is not None:
            p, q = parsed
            if p > 0 and q > 0:
                extracted.append((p, q))

    if not extracted:
        return BestAsk(price=None, quantity=0)

    # Find lowest sell price
    min_price = min(p for p, _ in extracted)

    # Aggregate quantities for all orders matching lowest price (within float precision)
    aggregated_qty = sum(
        q for p, q in extracted
        if abs(p - min_price) < 1e-6
    )

    return BestAsk(price=min_price, quantity=aggregated_qty)


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
    num_placeholder_rows: int = 3,
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
    total_orders: str = PLACEHOLDER,
    throughput: str = PLACEHOLDER,
    latency: str = PLACEHOLDER,
) -> List[str]:
    """Return Performance Metrics section lines."""
    divider = "-" * width
    col_w = max(width - 4, 10)
    return [
        f"  {SECTION_PERFORMANCE}",
        divider,
        f"  {LABEL_TOTAL_ORDERS:<{col_w - 10}} {total_orders:>8}",
        f"  {LABEL_THROUGHPUT:<{col_w - 10}} {throughput:>8}",
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
    ) -> None:
        """Initialize the dashboard with optional configuration and order data."""
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
        lines += build_order_book_lines(width)
        lines.append("")
        lines += build_performance_lines(width)
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
                max_y, max_x, buy_orders=buy_orders, sell_orders=sell_orders
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

        for _ in range(3):
            bid_cell = f"  {PLACEHOLDER:>8}  {PLACEHOLDER:>6}"
            ask_cell = f"  {PLACEHOLDER:>8}  {PLACEHOLDER:>6}"
            self._safe_addstr(stdscr, y, start_x, f"{bid_cell:<{half + 2}}", attrs["bid"])
            self._safe_addstr(stdscr, y, start_x + half + 2, ask_cell, attrs["ask"])
            y += 1

        put(divider, attrs["border"])
        blank()

        # ---- Performance Metrics ----
        put(f"  {SECTION_PERFORMANCE}", attrs["section"])
        put(divider, attrs["border"])
        put(f"  {LABEL_TOTAL_ORDERS:<{col_w - 10}} {PLACEHOLDER:>8}", attrs["label"])
        put(f"  {LABEL_THROUGHPUT:<{col_w - 10}} {PLACEHOLDER:>8}", attrs["label"])
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
