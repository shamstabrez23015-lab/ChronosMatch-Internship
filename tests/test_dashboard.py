"""Unit tests for ChronosMatch Terminal Dashboard - Day 1 + Day 2.

Validates noninteractive dashboard logic, configuration, display strings,
input processing, layout helpers, section labels, small-terminal handling,
and mock window rendering without requiring a live terminal.
"""

from typing import Any, List, Tuple
from unittest.mock import MagicMock, patch
import pytest

from chronos.dashboard import (
    APP_SUBTITLE,
    APP_TITLE,
    DEFAULT_REFRESH_INTERVAL_MS,
    MIN_TERMINAL_COLS,
    MIN_TERMINAL_ROWS,
    PLACEHOLDER,
    QUIT_MESSAGE,
    STATUS_MESSAGE,
    SECTION_MARKET_SUMMARY,
    SECTION_ORDER_BOOK,
    SECTION_BUY_ORDERS,
    SECTION_SELL_ORDERS,
    SECTION_PERFORMANCE,
    LABEL_BEST_BID,
    LABEL_BID_QTY,
    LABEL_BEST_ASK,
    LABEL_ASK_QTY,
    LABEL_SPREAD,
    LABEL_TOTAL_ORDERS,
    LABEL_THROUGHPUT,
    LABEL_LATENCY,
    BestBid,
    BestAsk,
    DashboardConfig,
    SAMPLE_BUY_ORDERS,
    SAMPLE_SELL_ORDERS,
    TerminalDashboard,
    build_header_lines,
    build_market_summary_lines,
    build_order_book_lines,
    build_performance_lines,
    build_footer_lines,
    calculate_best_bid,
    calculate_best_ask,
    calculate_spread,
    format_best_bid_price,
    format_best_bid_qty,
    format_best_ask_price,
    format_best_ask_qty,
    format_price,
    format_spread,
    get_sample_buy_orders,
    get_sample_sell_orders,
)


class MockCursesWindow:
    """Mock curses window to inspect rendering and screen interactions."""

    def __init__(self, rows: int = 40, cols: int = 100, keys: List[int] = None) -> None:
        self.rows = rows
        self.cols = cols
        self.keys = keys or []
        self.key_index = 0
        self.erased = False
        self.refreshed = False
        self.timeout_val = None
        self.addstr_calls: List[Tuple[int, int, str, int]] = []

    def getmaxyx(self) -> Tuple[int, int]:
        return (self.rows, self.cols)

    def erase(self) -> None:
        self.erased = True

    def refresh(self) -> None:
        self.refreshed = True

    def timeout(self, delay: int) -> None:
        self.timeout_val = delay

    def getch(self) -> int:
        if self.key_index < len(self.keys):
            key = self.keys[self.key_index]
            self.key_index += 1
            return key
        return -1

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.addstr_calls.append((y, x, text, attr))


def test_dashboard_config_defaults():
    """Verify default dashboard configuration parameters."""
    config = DashboardConfig()
    assert config.refresh_interval_ms == DEFAULT_REFRESH_INTERVAL_MS
    assert config.min_rows == MIN_TERMINAL_ROWS
    assert config.min_cols == MIN_TERMINAL_COLS


def test_dashboard_config_custom():
    """Verify custom configuration overrides."""
    config = DashboardConfig(refresh_interval_ms=50, min_rows=15, min_cols=60)
    assert config.refresh_interval_ms == 50
    assert config.min_rows == 15
    assert config.min_cols == 60


def test_dashboard_initial_state():
    """Verify dashboard initial runtime state."""
    dashboard = TerminalDashboard()
    assert dashboard.is_running is False
    assert dashboard.frame_count == 0
    assert dashboard.config.min_rows == MIN_TERMINAL_ROWS


def test_is_terminal_size_sufficient():
    """Verify dimension threshold validation for various screen sizes."""
    dashboard = TerminalDashboard(DashboardConfig(min_rows=30, min_cols=72))

    # Equal to minimum
    assert dashboard.is_terminal_size_sufficient(30, 72) is True

    # Larger than minimum
    assert dashboard.is_terminal_size_sufficient(40, 120) is True

    # Too few rows
    assert dashboard.is_terminal_size_sufficient(29, 72) is False

    # Too few columns
    assert dashboard.is_terminal_size_sufficient(30, 71) is False

    # Both dimensions too small
    assert dashboard.is_terminal_size_sufficient(5, 20) is False


def test_get_display_lines_content():
    """Verify generated display text contains all section labels and placeholders."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    full_output = "\n".join(lines)

    # Header
    assert APP_TITLE in full_output
    assert APP_SUBTITLE in full_output
    assert STATUS_MESSAGE in full_output
    # Market Summary
    assert SECTION_MARKET_SUMMARY in full_output
    assert LABEL_BEST_BID in full_output
    assert LABEL_BEST_ASK in full_output
    assert LABEL_SPREAD in full_output
    # Order Book
    assert SECTION_ORDER_BOOK in full_output
    assert SECTION_BUY_ORDERS in full_output
    assert SECTION_SELL_ORDERS in full_output
    # Performance
    assert SECTION_PERFORMANCE in full_output
    assert LABEL_TOTAL_ORDERS in full_output
    assert LABEL_THROUGHPUT in full_output
    assert LABEL_LATENCY in full_output
    # Footer
    assert QUIT_MESSAGE in full_output


def test_get_display_lines_placeholders():
    """Verify placeholder values appear in the display lines."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    assert PLACEHOLDER in "\n".join(lines)


def test_get_display_lines_recovers_at_minimum():
    """Verify full layout at exactly minimum viable dimensions."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=MIN_TERMINAL_ROWS, cols=MIN_TERMINAL_COLS)
    full_output = "\n".join(lines)
    assert APP_TITLE in full_output
    assert SECTION_ORDER_BOOK in full_output


def test_get_display_lines_too_small():
    """Verify warning message when terminal dimensions are insufficient."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=5, cols=20)
    full_output = "\n".join(lines)

    assert "too small" in full_output.lower()
    assert QUIT_MESSAGE in full_output


def test_get_display_lines_small_terminal_reports_dimensions():
    """Verify small-terminal message includes min and current dimensions."""
    dashboard = TerminalDashboard(DashboardConfig(min_rows=30, min_cols=72))
    lines = dashboard.get_display_lines(rows=10, cols=40)
    text = "\n".join(lines)
    assert "72x30" in text   # min dimensions
    assert "40x10" in text   # current dimensions


def test_handle_input_quit_keys():
    """Verify that pressing 'q' or 'Q' halts the dashboard."""
    dashboard = TerminalDashboard()
    dashboard.is_running = True

    # Lowercase 'q'
    assert dashboard.handle_input(ord("q")) is False
    assert dashboard.is_running is False

    # Uppercase 'Q'
    dashboard.is_running = True
    assert dashboard.handle_input(ord("Q")) is False
    assert dashboard.is_running is False


def test_handle_input_other_keys():
    """Verify that other keys do not stop the dashboard."""
    dashboard = TerminalDashboard()
    dashboard.is_running = True

    assert dashboard.handle_input(ord("a")) is True
    assert dashboard.handle_input(ord("1")) is True
    assert dashboard.handle_input(-1) is True
    assert dashboard.is_running is True


def test_render_sufficient_window():
    """Verify render output on a normal sized mock window."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=40, cols=100)

    dashboard.render(win)

    assert win.erased is True
    assert win.refreshed is True

    # Aggregate all text written across addstr calls
    rendered_text = " ".join([call[2] for call in win.addstr_calls])
    assert APP_TITLE in rendered_text
    assert APP_SUBTITLE in rendered_text
    assert STATUS_MESSAGE in rendered_text
    assert QUIT_MESSAGE in rendered_text


def test_render_all_sections_present():
    """Verify all five dashboard sections are rendered."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=40, cols=100)

    dashboard.render(win)

    rendered_text = " ".join([call[2] for call in win.addstr_calls])
    assert SECTION_MARKET_SUMMARY in rendered_text
    assert SECTION_ORDER_BOOK in rendered_text
    assert SECTION_BUY_ORDERS in rendered_text
    assert SECTION_SELL_ORDERS in rendered_text
    assert SECTION_PERFORMANCE in rendered_text


def test_render_small_window():
    """Verify render fallback when window is too small."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=5, cols=20)

    dashboard.render(win)

    assert win.erased is True
    assert win.refreshed is True

    rendered_text = " ".join([call[2] for call in win.addstr_calls])
    assert "too small" in rendered_text.lower()
    assert QUIT_MESSAGE in rendered_text


def test_safe_addstr_handles_out_of_bounds():
    """Verify _safe_addstr avoids exceptions when coordinates exceed window."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=10, cols=20)

    # Negative coordinates
    dashboard._safe_addstr(win, -1, 0, "Test")
    # Coordinates exceeding bounds
    dashboard._safe_addstr(win, 10, 0, "Test")
    dashboard._safe_addstr(win, 0, 20, "Test")

    # None of these should have been added
    assert len(win.addstr_calls) == 0


def test_run_curses_event_loop_with_max_iterations():
    """Verify run_curses event loop executes and terminates under iteration limit."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=40, cols=100, keys=[-1, -1])

    dashboard.run_curses(win, max_iterations=2)

    assert dashboard.frame_count == 2
    assert win.timeout_val == dashboard.config.refresh_interval_ms
    assert win.refreshed is True


def test_run_curses_event_loop_quits_on_q():
    """Verify run_curses event loop terminates immediately when 'q' is pressed."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=40, cols=100, keys=[-1, ord("q"), -1])

    dashboard.run_curses(win, max_iterations=10)

    assert dashboard.is_running is False
    assert dashboard.frame_count == 2  # Terminated on second iteration


def test_run_missing_curses_raises_runtime_error():
    """Verify informative RuntimeError when curses module is unavailable."""
    dashboard = TerminalDashboard()

    with patch("chronos.dashboard.curses", None):
        with pytest.raises(RuntimeError, match="curses library is not available"):
            dashboard.run()


# ===========================================================================
# Day 2 - layout helper tests (pure functions, no curses needed)
# ===========================================================================


def test_build_header_lines_content():
    """Verify header lines contain title, subtitle, and status."""
    lines = build_header_lines(width=68)
    joined = "\n".join(lines)
    assert APP_TITLE in joined
    assert APP_SUBTITLE in joined
    assert STATUS_MESSAGE in joined


def test_build_header_lines_border_width():
    """Verify header border matches requested width exactly."""
    lines = build_header_lines(width=50)
    assert lines[0] == "=" * 50
    assert lines[-1] == "=" * 50


def test_build_market_summary_labels():
    """Verify market summary section contains all required labels."""
    lines = build_market_summary_lines(width=68)
    joined = "\n".join(lines)
    assert SECTION_MARKET_SUMMARY in joined
    assert LABEL_BEST_BID in joined
    assert LABEL_BEST_ASK in joined
    assert LABEL_SPREAD in joined


def test_build_market_summary_placeholders():
    """Verify market summary shows placeholder values by default."""
    lines = build_market_summary_lines(width=68)
    assert PLACEHOLDER in "\n".join(lines)


def test_build_market_summary_custom_values():
    """Verify market summary uses injected values when provided."""
    lines = build_market_summary_lines(
        width=68, best_bid="100.00", best_ask="100.50", spread="0.50"
    )
    joined = "\n".join(lines)
    assert "100.00" in joined
    assert "100.50" in joined
    assert "0.50" in joined


def test_build_order_book_section_labels():
    """Verify order book section contains BUY and SELL column headers."""
    lines = build_order_book_lines(width=68)
    joined = "\n".join(lines)
    assert SECTION_ORDER_BOOK in joined
    assert SECTION_BUY_ORDERS in joined
    assert SECTION_SELL_ORDERS in joined


def test_build_order_book_price_qty_headers():
    """Verify order book sub-headers include Price and Qty."""
    lines = build_order_book_lines(width=68)
    joined = "\n".join(lines)
    assert "Price" in joined
    assert "Qty" in joined


def test_build_order_book_placeholder_rows():
    """Verify order book renders placeholder rows by default."""
    lines = build_order_book_lines(width=68, num_placeholder_rows=3)
    assert PLACEHOLDER in "\n".join(lines)


def test_build_order_book_custom_rows():
    """Verify order book renders custom bid/ask row data correctly."""
    bids = [("99.50", "500"), ("99.00", "1000")]
    asks = [("100.00", "300"), ("100.50", "800")]
    lines = build_order_book_lines(width=68, bid_rows=bids, ask_rows=asks)
    joined = "\n".join(lines)
    assert "99.50" in joined
    assert "100.00" in joined
    assert "500" in joined
    assert "300" in joined


def test_build_performance_labels():
    """Verify performance section contains all metric labels."""
    lines = build_performance_lines(width=68)
    joined = "\n".join(lines)
    assert SECTION_PERFORMANCE in joined
    assert LABEL_TOTAL_ORDERS in joined
    assert LABEL_THROUGHPUT in joined
    assert LABEL_LATENCY in joined


def test_build_performance_placeholder_values():
    """Verify performance section shows placeholder values by default."""
    lines = build_performance_lines(width=68)
    assert PLACEHOLDER in "\n".join(lines)


def test_build_footer_contains_quit_message():
    """Verify footer includes the quit instruction."""
    lines = build_footer_lines(width=68)
    assert QUIT_MESSAGE in "\n".join(lines)


def test_build_footer_ends_with_border():
    """Verify footer is closed with an equals-sign border of exact width."""
    lines = build_footer_lines(width=60)
    assert lines[-1] == "=" * 60


def test_layout_helper_width_consistency():
    """Verify layout helpers produce borders of the requested width."""
    width = 55
    header = build_header_lines(width)
    market = build_market_summary_lines(width)
    performance = build_performance_lines(width)
    footer = build_footer_lines(width)

    assert header[0] == "=" * width
    assert market[1] == "-" * width
    assert performance[1] == "-" * width
    assert footer[-1] == "=" * width


# ===========================================================================
# Day 3 - Best Bid calculation, formatting, and dashboard rendering tests
# ===========================================================================


def test_calculate_best_bid_single_order():
    """Verify Best Bid calculation with a single BUY order."""
    orders = [{"order_id": 101, "price": 500.0, "quantity": 100}]
    result = calculate_best_bid(orders)

    assert isinstance(result, BestBid)
    assert result.price == 500.0
    assert result.quantity == 100
    assert result == (500.0, 100)


def test_calculate_best_bid_multiple_different_prices():
    """Verify Best Bid calculation selects the highest price among multiple distinct BUY orders."""
    orders = [
        {"order_id": 101, "price": 500.0, "quantity": 100},
        {"order_id": 102, "price": 505.0, "quantity": 50},
        {"order_id": 103, "price": 510.0, "quantity": 200},
    ]
    result = calculate_best_bid(orders)

    assert result.price == 510.0
    assert result.quantity == 200


def test_calculate_best_bid_unsorted_order():
    """Verify Best Bid calculation is invariant to the arrival order of orders."""
    orders = [
        {"order_id": 102, "price": 505.0, "quantity": 50},
        {"order_id": 103, "price": 510.0, "quantity": 200},
        {"order_id": 101, "price": 500.0, "quantity": 100},
    ]
    result = calculate_best_bid(orders)

    assert result.price == 510.0
    assert result.quantity == 200


def test_calculate_best_bid_aggregated_highest_price():
    """Verify quantities are aggregated across multiple BUY orders sharing the highest price."""
    orders = [
        {"order_id": 1, "price": 510.0, "quantity": 100},
        {"order_id": 2, "price": 510.0, "quantity": 50},
        {"order_id": 3, "price": 505.0, "quantity": 80},
    ]
    result = calculate_best_bid(orders)

    assert result.price == 510.0
    assert result.quantity == 150  # 100 + 50 aggregated


def test_calculate_best_bid_empty_order_book():
    """Verify calculation returns (None, 0) and formatting produces 'N/A' and '0' for empty book."""
    # Empty list
    res_empty = calculate_best_bid([])
    assert res_empty.price is None
    assert res_empty.quantity == 0

    # None input
    res_none = calculate_best_bid(None)
    assert res_none.price is None
    assert res_none.quantity == 0

    # Formatted output for empty book
    assert format_best_bid_price(res_empty.price) == "N/A"
    assert format_best_bid_qty(res_empty.quantity) == "0"


def test_best_bid_price_and_quantity_formatting():
    """Verify consistent two-decimal price formatting and quantity string conversion."""
    assert format_best_bid_price(510.0) == "510.00"
    assert format_best_bid_price(510) == "510.00"
    assert format_best_bid_price(505.5) == "505.50"
    assert format_best_bid_price(500.125) == "500.12" or format_best_bid_price(500.125) == "500.13"
    assert format_best_bid_price(None) == "N/A"

    assert format_best_bid_qty(150) == "150"
    assert format_best_bid_qty(0) == "0"
    assert format_best_bid_qty(10000) == "10000"


def test_dashboard_renders_best_bid_with_sample_data():
    """Verify dashboard displays Best Bid 510.00 and Bid Qty 150 with demonstration sample data."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    assert "510.00" in text
    assert "150" in text
    assert LABEL_BEST_BID in text
    assert LABEL_BID_QTY in text
    assert "Sample Data" in text

    # Verify mock curses render window output
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    rendered_text = " ".join([call[2] for call in win.addstr_calls])

    assert "510.00" in rendered_text
    assert "150" in rendered_text
    assert LABEL_BEST_BID in rendered_text
    assert LABEL_BID_QTY in rendered_text


def test_dashboard_renders_best_bid_empty_order_book():
    """Verify dashboard displays 'N/A' and '0' when BUY order book is empty."""
    dashboard = TerminalDashboard(buy_orders=[])
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    assert "N/A" in text
    assert "0" in text
    assert LABEL_BEST_BID in text
    assert LABEL_BID_QTY in text

    # Verify mock curses render window output
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    rendered_text = " ".join([call[2] for call in win.addstr_calls])

    assert "N/A" in rendered_text
    assert "0" in rendered_text


def test_dashboard_renders_custom_buy_orders():
    """Verify dashboard dynamically computes Best Bid for custom BUY orders."""
    custom_orders = [
        {"price": 420.75, "quantity": 300},
        {"price": 420.75, "quantity": 150},
        {"price": 415.00, "quantity": 500},
    ]
    dashboard = TerminalDashboard(buy_orders=custom_orders)
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    assert "420.75" in text
    assert "450" in text


def test_dashboard_preserves_other_sections_with_best_bid():
    """Verify all dashboard sections remain intact and placeholders are preserved."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    full_output = "\n".join(lines)

    # Header
    assert APP_TITLE in full_output
    assert APP_SUBTITLE in full_output
    assert STATUS_MESSAGE in full_output

    # Market Summary
    assert SECTION_MARKET_SUMMARY in full_output
    assert LABEL_BEST_BID in full_output
    assert LABEL_BID_QTY in full_output
    assert LABEL_BEST_ASK in full_output
    assert LABEL_SPREAD in full_output

    # Order Book
    assert SECTION_ORDER_BOOK in full_output
    assert SECTION_BUY_ORDERS in full_output
    assert SECTION_SELL_ORDERS in full_output
    assert "Price" in full_output
    assert "Qty" in full_output

    # Performance
    assert SECTION_PERFORMANCE in full_output
    assert LABEL_TOTAL_ORDERS in full_output
    assert LABEL_THROUGHPUT in full_output
    assert LABEL_LATENCY in full_output

    # Placeholders for unintegrated sections
    assert PLACEHOLDER in full_output

    # Footer
    assert QUIT_MESSAGE in full_output


def test_calculate_best_bid_with_protocol_orders():
    """Verify calculate_best_bid works with Order objects from chronos.protocol."""
    from chronos.protocol import Order, OrderType, Side

    orders = [
        Order(1, 1000, 500.0, 100, 1001, Side.BUY, OrderType.LIMIT),
        Order(2, 2000, 510.0, 120, 1001, Side.BUY, OrderType.LIMIT),
        Order(3, 3000, 510.0, 80, 1001, Side.BUY, OrderType.LIMIT),
    ]
    result = calculate_best_bid(orders)
    assert result.price == 510.0
    assert result.quantity == 200


def test_calculate_best_bid_filters_sell_orders():
    """Verify calculate_best_bid ignores SELL orders if mixed orders are passed."""
    orders = [
        {"order_id": 1, "side": 2, "price": 550.0, "quantity": 1000},  # SELL
        {"order_id": 2, "side": 1, "price": 500.0, "quantity": 100},   # BUY
        {"order_id": 3, "side": 1, "price": 510.0, "quantity": 250},   # BUY
    ]
    result = calculate_best_bid(orders)
    assert result.price == 510.0
    assert result.quantity == 250


def test_calculate_best_bid_with_tuples():
    """Verify calculate_best_bid handles (price, quantity) tuples."""
    orders = [(510.0, 100), (510.0, 50), (505.0, 80)]
    result = calculate_best_bid(orders)
    assert result.price == 510.0
    assert result.quantity == 150


# ===========================================================================
# Day 4 - Best Ask and Bid-Ask Spread calculation, formatting, and rendering
# ===========================================================================


def test_calculate_best_ask_single_order():
    """1. Verify Best Ask calculation with a single SELL order."""
    orders = [{"order_id": 201, "side": 2, "price": 505.0, "quantity": 40}]
    result = calculate_best_ask(orders)

    assert isinstance(result, BestAsk)
    assert result.price == 505.0
    assert result.quantity == 40
    assert result == (505.0, 40)


def test_calculate_best_ask_multiple_different_prices():
    """2. Verify Best Ask selects the LOWEST price among multiple SELL orders."""
    # Spec example: 515 (100), 505 (40), 510 (80) -> Best Ask = 505, Qty = 40
    orders = [
        {"order_id": 201, "price": 515.0, "quantity": 100},
        {"order_id": 202, "price": 505.0, "quantity": 40},
        {"order_id": 203, "price": 510.0, "quantity": 80},
    ]
    result = calculate_best_ask(orders)

    assert result.price == 505.0
    assert result.quantity == 40


def test_calculate_best_ask_unsorted_orders():
    """3. Verify Best Ask calculation is invariant to the arrival order of SELL orders."""
    orders = [
        {"order_id": 201, "price": 520.0, "quantity": 70},
        {"order_id": 202, "price": 515.0, "quantity": 100},
        {"order_id": 203, "price": 505.0, "quantity": 40},
        {"order_id": 204, "price": 510.0, "quantity": 80},
    ]
    result = calculate_best_ask(orders)

    assert result.price == 505.0
    assert result.quantity == 40


def test_calculate_best_ask_equal_lowest_prices_aggregate_quantity():
    """4. Verify quantities are aggregated when multiple SELL orders share the lowest price."""
    # Spec example: SELL at 505 qty 40, SELL at 505 qty 60 -> Best Ask = 505, Qty = 100
    orders = [
        {"order_id": 201, "price": 505.0, "quantity": 40},
        {"order_id": 202, "price": 505.0, "quantity": 60},
        {"order_id": 203, "price": 515.0, "quantity": 100},
    ]
    result = calculate_best_ask(orders)

    assert result.price == 505.0
    assert result.quantity == 100


def test_calculate_best_ask_empty_order_book():
    """5. Verify empty SELL collection returns (None, 0) and formats as N/A and 0."""
    res_empty = calculate_best_ask([])
    assert res_empty.price is None
    assert res_empty.quantity == 0

    res_none = calculate_best_ask(None)
    assert res_none.price is None
    assert res_none.quantity == 0

    assert format_best_ask_price(res_empty.price) == "N/A"
    assert format_best_ask_qty(res_empty.quantity) == "0"


def test_calculate_spread_correctness():
    """6. Verify Bid-Ask Spread calculation (Spread = Best Ask - Best Bid)."""
    # Spec example: Best Bid = 500, Best Ask = 505, Spread = 5
    spread = calculate_spread(best_ask=505.0, best_bid=500.0)
    assert spread == 5.0
    assert format_spread(spread) == "5.00"

    # With BestAsk and BestBid NamedTuples
    ask_obj = BestAsk(price=505.0, quantity=40)
    bid_obj = BestBid(price=500.0, quantity=100)
    assert calculate_spread(ask_obj, bid_obj) == 5.0

    # Locked market (Spread = 0)
    assert calculate_spread(505.0, 505.0) == 0.0
    assert format_spread(0.0) == "0.00"

    # Crossing / inverted market (Spread < 0)
    crossing_spread = calculate_spread(505.0, 510.0)
    assert crossing_spread == -5.0
    assert format_spread(crossing_spread) == "-5.00"

    # Avoid floating-point errors with small cents differences
    cents_spread = calculate_spread(500.10, 500.00)
    assert cents_spread == 0.10
    assert format_spread(cents_spread) == "0.10"


def test_spread_with_no_buy_orders():
    """7. When BUY orders are missing, Spread is N/A and Best Bid is N/A."""
    # Direct calculate_spread with missing bid
    assert calculate_spread(best_ask=505.0, best_bid=None) is None
    assert calculate_spread(BestAsk(505.0, 40), BestBid(None, 0)) is None
    assert format_spread(calculate_spread(505.0, None)) == "N/A"

    # Dashboard state with empty BUY orders
    sell_orders = [{"price": 505.0, "quantity": 40}]
    dashboard = TerminalDashboard(buy_orders=[], sell_orders=sell_orders)
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    assert LABEL_BEST_BID in text
    assert LABEL_BEST_ASK in text
    assert LABEL_SPREAD in text
    assert "505.00" in text  # Best Ask
    assert "40" in text      # Ask Qty
    assert "N/A" in text     # Best Bid and Spread
    assert "0" in text       # Bid Qty


def test_spread_with_no_sell_orders():
    """8. When SELL orders are missing, Spread is N/A and Best Ask is N/A."""
    # Direct calculate_spread with missing ask
    assert calculate_spread(best_ask=None, best_bid=500.0) is None
    assert calculate_spread(BestAsk(None, 0), BestBid(500.0, 100)) is None
    assert format_spread(calculate_spread(None, 500.0)) == "N/A"

    # Dashboard state with empty SELL orders
    buy_orders = [{"price": 500.0, "quantity": 100}]
    dashboard = TerminalDashboard(buy_orders=buy_orders, sell_orders=[])
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    assert LABEL_BEST_BID in text
    assert LABEL_BEST_ASK in text
    assert LABEL_SPREAD in text
    assert "500.00" in text  # Best Bid
    assert "100" in text     # Bid Qty
    assert "N/A" in text     # Best Ask and Spread
    assert "0" in text       # Ask Qty


def test_correct_price_and_spread_formatting():
    """9. Verify price, quantity, and spread string formatting."""
    assert format_best_ask_price(505.0) == "505.00"
    assert format_best_ask_price(505) == "505.00"
    assert format_best_ask_price(505.125) in ("505.12", "505.13")
    assert format_best_ask_price(None) == "N/A"

    assert format_best_ask_qty(40) == "40"
    assert format_best_ask_qty(0) == "0"
    assert format_best_ask_qty(12345) == "12345"

    assert format_spread(5.0) == "5.00"
    assert format_spread(0.0) == "0.00"
    assert format_spread(-5.0) == "-5.00"
    assert format_spread(None) == "N/A"

    assert format_price(100.5) == "100.50"
    assert format_price(None) == "N/A"


def test_dashboard_renders_best_ask_and_spread_sample_data():
    """10a. Verify dashboard displays Best Ask 505.00, Ask Qty 40, Spread -5.00 with sample data."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    # Market summary labels
    assert LABEL_BEST_BID in text
    assert LABEL_BID_QTY in text
    assert LABEL_BEST_ASK in text
    assert LABEL_ASK_QTY in text
    assert LABEL_SPREAD in text

    # Values for sample data (BUY: 510.00 qty 150, SELL: 505.00 qty 40, Spread: -5.00)
    assert "510.00" in text
    assert "150" in text
    assert "505.00" in text
    assert "40" in text
    assert "-5.00" in text

    # Mock curses render test
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    rendered_text = " ".join([call[2] for call in win.addstr_calls])

    assert LABEL_BEST_ASK in rendered_text
    assert LABEL_ASK_QTY in rendered_text
    assert LABEL_SPREAD in rendered_text
    assert "505.00" in rendered_text
    assert "40" in rendered_text
    assert "-5.00" in rendered_text


def test_dashboard_renders_spec_example_values():
    """10b. Verify dashboard displays exact spec example (Best Bid 500, Ask 505, Spread 5)."""
    custom_buys = [{"price": 500.0, "quantity": 100}]
    custom_sells = [
        {"order_id": 201, "price": 515.0, "quantity": 100},
        {"order_id": 202, "price": 505.0, "quantity": 40},
        {"order_id": 203, "price": 510.0, "quantity": 80},
    ]
    dashboard = TerminalDashboard(buy_orders=custom_buys, sell_orders=custom_sells)
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    assert "500.00" in text  # Best Bid
    assert "100" in text     # Bid Qty
    assert "505.00" in text  # Best Ask
    assert "40" in text      # Ask Qty
    assert "5.00" in text    # Spread


def test_calculate_best_ask_with_protocol_orders():
    """Verify calculate_best_ask works with Order objects from chronos.protocol."""
    from chronos.protocol import Order, OrderType, Side

    orders = [
        Order(1, 1000, 515.0, 100, 1001, Side.SELL, OrderType.LIMIT),
        Order(2, 2000, 505.0, 40, 1001, Side.SELL, OrderType.LIMIT),
        Order(3, 3000, 510.0, 80, 1001, Side.SELL, OrderType.LIMIT),
    ]
    result = calculate_best_ask(orders)
    assert result.price == 505.0
    assert result.quantity == 40


def test_calculate_best_ask_filters_buy_orders():
    """Verify calculate_best_ask ignores BUY orders if mixed orders are passed."""
    orders = [
        {"order_id": 1, "side": 1, "price": 490.0, "quantity": 500},   # BUY
        {"order_id": 2, "side": 2, "price": 520.0, "quantity": 100},   # SELL
        {"order_id": 3, "side": 2, "price": 505.0, "quantity": 60},    # SELL
    ]
    result = calculate_best_ask(orders)
    assert result.price == 505.0
    assert result.quantity == 60


def test_calculate_best_ask_with_tuples():
    """Verify calculate_best_ask handles (price, quantity) tuples."""
    orders = [(515.0, 100), (505.0, 40), (510.0, 80)]
    result = calculate_best_ask(orders)
    assert result.price == 505.0
    assert result.quantity == 40


def test_dashboard_set_and_update_sell_orders():
    """Verify dynamic updates to sell_orders via set_sell_orders and update_sell_orders."""
    dashboard = TerminalDashboard()
    new_sells = [{"price": 599.00, "quantity": 25}]

    dashboard.set_sell_orders(new_sells)
    assert dashboard.sell_orders == new_sells
    lines = dashboard.get_display_lines(rows=40, cols=100)
    assert "599.00" in "\n".join(lines)
    assert "25" in "\n".join(lines)

    updated_sells = [{"price": 600.00, "quantity": 50}]
    dashboard.update_sell_orders(updated_sells)
    assert dashboard.sell_orders == updated_sells
    lines2 = dashboard.get_display_lines(rows=40, cols=100)
    assert "600.00" in "\n".join(lines2)
    assert "50" in "\n".join(lines2)


def test_build_market_summary_includes_ask_qty():
    """Verify build_market_summary_lines formats ask_qty correctly."""
    lines = build_market_summary_lines(
        width=68,
        best_bid="500.00",
        best_ask="505.00",
        spread="5.00",
        bid_qty="100",
        ask_qty="40",
    )
    joined = "\n".join(lines)
    assert LABEL_BEST_BID in joined
    assert LABEL_BID_QTY in joined
    assert LABEL_BEST_ASK in joined
    assert LABEL_ASK_QTY in joined
    assert LABEL_SPREAD in joined
    assert "500.00" in joined
    assert "100" in joined
    assert "505.00" in joined
    assert "40" in joined
    assert "5.00" in joined


