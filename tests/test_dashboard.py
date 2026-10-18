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
    LABEL_ORDERS_PROCESSED,
    LABEL_THROUGHPUT,
    LABEL_LATENCY,
    DEMO_ORDERS_PROCESSED,
    BestBid,
    BestAsk,
    DashboardConfig,
    PriceLevel,
    SAMPLE_BUY_ORDERS,
    SAMPLE_SELL_ORDERS,
    TerminalDashboard,
    aggregate_orders_by_price,
    build_header_lines,
    build_market_summary_lines,
    build_order_book_lines,
    build_performance_lines,
    build_footer_lines,
    calculate_best_bid,
    calculate_best_ask,
    calculate_buy_depth,
    calculate_sell_depth,
    calculate_spread,
    format_best_bid_price,
    format_best_bid_qty,
    format_best_ask_price,
    format_best_ask_qty,
    format_depth_rows,
    format_orders_processed,
    format_price,
    format_spread,
    format_total_orders,
    get_sample_buy_orders,
    get_sample_sell_orders,
    get_sample_orders_processed,
    calculate_throughput,
    calculate_throughput_from_counts,
    format_throughput,
    get_sample_throughput,
    DEMO_THROUGHPUT,
    NO_SAMPLE_THROUGHPUT,
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


# ===========================================================================
# Day 5 - Order Book Depth (top 5 BUY and SELL price levels with aggregation)
# ===========================================================================


def test_buy_depth_single_price_level():
    """1. Verify BUY depth calculation with a single BUY price level."""
    orders = [{"price": 500.0, "quantity": 100}]
    depth = calculate_buy_depth(orders)

    assert len(depth) == 1
    assert depth[0] == (500.0, 100)
    assert depth[0].price == 500.0
    assert depth[0].quantity == 100
    assert isinstance(depth[0], PriceLevel)


def test_buy_depth_multiple_price_levels():
    """2. Verify BUY depth calculation with multiple distinct BUY price levels."""
    orders = [
        {"price": 500.0, "quantity": 100},
        {"price": 505.0, "quantity": 80},
        {"price": 510.0, "quantity": 150},
    ]
    depth = calculate_buy_depth(orders)

    assert len(depth) == 3
    assert depth == [
        PriceLevel(510.0, 150),
        PriceLevel(505.0, 80),
        PriceLevel(500.0, 100),
    ]


def test_buy_depth_descending_sorting():
    """3. Verify correct descending sorting for BUY depth (highest price first)."""
    # Spec example:
    # BUY 500, quantity 100
    # BUY 510, quantity 50
    # BUY 505, quantity 80
    # BUY 510, quantity 100
    # Expected: 510 (150), 505 (80), 500 (100)
    orders = [
        {"price": 500.0, "quantity": 100},
        {"price": 510.0, "quantity": 50},
        {"price": 505.0, "quantity": 80},
        {"price": 510.0, "quantity": 100},
    ]
    depth = calculate_buy_depth(orders)

    assert [lvl.price for lvl in depth] == [510.0, 505.0, 500.0]
    assert [lvl.quantity for lvl in depth] == [150, 80, 100]


def test_sell_depth_ascending_sorting():
    """4. Verify correct ascending sorting for SELL depth (lowest price first)."""
    # Spec example:
    # SELL 520, quantity 100
    # SELL 512, quantity 40
    # SELL 515, quantity 60
    # SELL 512, quantity 30
    # Expected: 512 (70), 515 (60), 520 (100)
    orders = [
        {"side": 2, "price": 520.0, "quantity": 100},
        {"side": 2, "price": 512.0, "quantity": 40},
        {"side": 2, "price": 515.0, "quantity": 60},
        {"side": 2, "price": 512.0, "quantity": 30},
    ]
    depth = calculate_sell_depth(orders)

    assert [lvl.price for lvl in depth] == [512.0, 515.0, 520.0]
    assert [lvl.quantity for lvl in depth] == [70, 60, 100]


def test_equal_price_quantity_aggregation():
    """5. Verify aggregation of quantities across multiple orders at identical prices."""
    buy_orders = [
        {"price": 500.0, "quantity": 50},
        {"price": 500.0, "quantity": 75},
        {"price": 500.0, "quantity": 25},
    ]
    buy_depth = calculate_buy_depth(buy_orders)
    assert len(buy_depth) == 1
    assert buy_depth[0].price == 500.0
    assert buy_depth[0].quantity == 150

    sell_orders = [
        {"side": 2, "price": 505.0, "quantity": 40},
        {"side": 2, "price": 505.0, "quantity": 60},
        {"side": 2, "price": 505.0, "quantity": 100},
    ]
    sell_depth = calculate_sell_depth(sell_orders)
    assert len(sell_depth) == 1
    assert sell_depth[0].price == 505.0
    assert sell_depth[0].quantity == 200


def test_buy_depth_more_than_five_levels_truncated():
    """6. Verify BUY depth limits display to top 5 distinct highest price levels."""
    orders = [
        {"price": 500.0, "quantity": 10},
        {"price": 501.0, "quantity": 20},
        {"price": 502.0, "quantity": 30},
        {"price": 503.0, "quantity": 40},
        {"price": 504.0, "quantity": 50},
        {"price": 505.0, "quantity": 60},
        {"price": 506.0, "quantity": 70},
    ]
    depth = calculate_buy_depth(orders, max_levels=5)

    assert len(depth) == 5
    # Must only contain the 5 highest prices in descending order
    assert [lvl.price for lvl in depth] == [506.0, 505.0, 504.0, 503.0, 502.0]
    assert [lvl.quantity for lvl in depth] == [70, 60, 50, 40, 30]


def test_sell_depth_more_than_five_levels_truncated():
    """7. Verify SELL depth limits display to top 5 distinct lowest price levels."""
    orders = [
        {"side": 2, "price": 520.0, "quantity": 70},
        {"side": 2, "price": 519.0, "quantity": 60},
        {"side": 2, "price": 518.0, "quantity": 50},
        {"side": 2, "price": 517.0, "quantity": 40},
        {"side": 2, "price": 516.0, "quantity": 30},
        {"side": 2, "price": 515.0, "quantity": 20},
        {"side": 2, "price": 514.0, "quantity": 10},
    ]
    depth = calculate_sell_depth(orders, max_levels=5)

    assert len(depth) == 5
    # Must only contain the 5 lowest prices in ascending order
    assert [lvl.price for lvl in depth] == [514.0, 515.0, 516.0, 517.0, 518.0]
    assert [lvl.quantity for lvl in depth] == [10, 20, 30, 40, 50]


def test_empty_buy_order_book_depth():
    """8. Verify empty BUY order book returns empty depth and formats with placeholders."""
    assert calculate_buy_depth([]) == []
    assert calculate_buy_depth(None) == []

    formatted = format_depth_rows([])
    assert len(formatted) == 5
    for p_str, q_str in formatted:
        assert p_str == PLACEHOLDER
        assert q_str == PLACEHOLDER


def test_empty_sell_order_book_depth():
    """9. Verify empty SELL order book returns empty depth and formats with placeholders."""
    assert calculate_sell_depth([]) == []
    assert calculate_sell_depth(None) == []

    formatted = format_depth_rows([])
    assert len(formatted) == 5
    for p_str, q_str in formatted:
        assert p_str == PLACEHOLDER
        assert q_str == PLACEHOLDER


def test_correct_order_book_rendering_with_depth():
    """10. Verify order book rendering with 5 price levels, formatting, and alignment."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    full_output = "\n".join(lines)

    # Order book headers
    assert SECTION_ORDER_BOOK in full_output
    assert SECTION_BUY_ORDERS in full_output
    assert SECTION_SELL_ORDERS in full_output

    # Check top 5 demonstration BUY levels are rendered
    assert "510.00" in full_output
    assert "505.00" in full_output
    assert "500.00" in full_output
    assert "495.00" in full_output
    assert "490.00" in full_output

    # Check top 5 demonstration SELL levels are rendered
    assert "505.00" in full_output
    assert "510.00" in full_output
    assert "515.00" in full_output
    assert "520.00" in full_output
    assert "525.00" in full_output

    # Verify mock curses render window receives order book depth lines
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    rendered_text = " ".join([call[2] for call in win.addstr_calls])

    assert "510.00" in rendered_text
    assert "490.00" in rendered_text
    assert "525.00" in rendered_text


def test_order_book_depth_alignment_with_best_bid_and_best_ask():
    """11. Verify the first BUY level matches Best Bid and first SELL level matches Best Ask."""
    # Test with default demonstration orders
    dashboard = TerminalDashboard()
    b_depth = calculate_buy_depth(dashboard.buy_orders)
    s_depth = calculate_sell_depth(dashboard.sell_orders)
    best_bid = calculate_best_bid(dashboard.buy_orders)
    best_ask = calculate_best_ask(dashboard.sell_orders)

    assert b_depth[0].price == best_bid.price
    assert b_depth[0].quantity == best_bid.quantity
    assert s_depth[0].price == best_ask.price
    assert s_depth[0].quantity == best_ask.quantity

    # Test with custom arbitrary orders
    custom_buys = [
        {"price": 400.0, "quantity": 10},
        {"price": 420.0, "quantity": 55},
        {"price": 410.0, "quantity": 25},
    ]
    custom_sells = [
        {"side": 2, "price": 450.0, "quantity": 30},
        {"side": 2, "price": 430.0, "quantity": 70},
        {"side": 2, "price": 440.0, "quantity": 40},
    ]
    custom_b_depth = calculate_buy_depth(custom_buys)
    custom_s_depth = calculate_sell_depth(custom_sells)
    custom_best_bid = calculate_best_bid(custom_buys)
    custom_best_ask = calculate_best_ask(custom_sells)

    assert custom_b_depth[0].price == custom_best_bid.price == 420.0
    assert custom_b_depth[0].quantity == custom_best_bid.quantity == 55
    assert custom_s_depth[0].price == custom_best_ask.price == 430.0
    assert custom_s_depth[0].quantity == custom_best_ask.quantity == 70


def test_preservation_of_all_existing_dashboard_behavior():
    """12. Verify all existing sections, controls, and features remain intact."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=40, cols=100)
    text = "\n".join(lines)

    # Header
    assert APP_TITLE in text
    assert APP_SUBTITLE in text
    assert "Demo: Sample Data" in text

    # Market Summary
    assert SECTION_MARKET_SUMMARY in text
    assert LABEL_BEST_BID in text
    assert LABEL_BID_QTY in text
    assert LABEL_BEST_ASK in text
    assert LABEL_ASK_QTY in text
    assert LABEL_SPREAD in text
    assert "510.00" in text
    assert "150" in text
    assert "505.00" in text
    assert "40" in text
    assert "-5.00" in text

    # Performance
    assert SECTION_PERFORMANCE in text
    assert LABEL_TOTAL_ORDERS in text
    assert LABEL_THROUGHPUT in text
    assert LABEL_LATENCY in text

    # Footer
    assert QUIT_MESSAGE in text

    # Q to quit input
    assert dashboard.handle_input(ord("q")) is False
    assert dashboard.handle_input(ord("Q")) is False
    assert dashboard.handle_input(ord("x")) is True

    # Small terminal message
    small_lines = dashboard.get_display_lines(rows=10, cols=30)
    small_text = "\n".join(small_lines)
    assert "too small" in small_text.lower()
    assert QUIT_MESSAGE in small_text


# ===========================================================================
# Day 6 - Orders Processed Counter tests
# ===========================================================================


def test_orders_processed_initial_count_is_zero():
    """1. Verify initial processed-order count is zero across all dashboard instantiations."""
    # Default instantiation
    dashboard = TerminalDashboard()
    assert dashboard.orders_processed == 0

    # With empty sample data
    dashboard_empty = TerminalDashboard(use_sample_data=False)
    assert dashboard_empty.orders_processed == 0

    # Display lines format 0 initially
    lines = dashboard.get_display_lines(rows=40, cols=100)
    perf_idx = next(i for i, line in enumerate(lines) if SECTION_PERFORMANCE in line)
    footer_idx = next(i for i, line in enumerate(lines) if QUIT_MESSAGE in line)
    perf_section = "\n".join(lines[perf_idx:footer_idx])
    assert LABEL_TOTAL_ORDERS in perf_section
    assert "       0" in perf_section or " 0" in perf_section


def test_orders_processed_increases_after_valid_event():
    """2. Verify processed-order count increases after a valid processed-order event."""
    dashboard = TerminalDashboard()
    assert dashboard.orders_processed == 0

    # Dictionary event
    event1 = {"order_id": 101, "side": 1, "price": 500.0, "quantity": 100}
    ret1 = dashboard.record_order_processed(event1)
    assert ret1 == 1
    assert dashboard.orders_processed == 1

    # Protocol Order object
    from chronos.protocol import Order, OrderType, Side

    order_obj = Order(102, 2000, 505.0, 50, 1001, Side.BUY, OrderType.LIMIT)
    ret2 = dashboard.record_order_processed(order_obj)
    assert ret2 == 2
    assert dashboard.orders_processed == 2

    # Callback alias on_order_processed
    order_dict = {"order_id": 103, "price": 510.0, "quantity": 75}
    ret3 = dashboard.on_order_processed(order_dict)
    assert ret3 == 3
    assert dashboard.orders_processed == 3


def test_orders_processed_multiple_events_and_fill_semantics():
    """3. Verify multiple events increase count and multiple fills for one order count as one."""
    dashboard = TerminalDashboard()

    # Ingestion of 10 distinct orders
    for i in range(1, 11):
        dashboard.record_order_processed({"order_id": i, "price": 500.0 + i, "quantity": 10})
    assert dashboard.orders_processed == 10

    # Multiple fills from a single order: should NOT increment processed-order counter again
    fill_event_1 = {"order_id": 5, "fill_id": 1, "price": 505.0, "quantity": 5}
    fill_event_2 = {"order_id": 5, "fill_id": 2, "price": 505.0, "quantity": 5}
    dashboard.record_order_processed(fill_event_1)
    assert dashboard.orders_processed == 10
    dashboard.record_order_processed(fill_event_2)
    assert dashboard.orders_processed == 10

    # Bulk increment
    dashboard.increment_orders_processed(15)
    assert dashboard.orders_processed == 25


def test_orders_processed_screen_redraw_does_not_increase_count():
    """4. Verify screen redraw / render calls do not increment the counter."""
    dashboard = TerminalDashboard(orders_processed=125)
    win = MockCursesWindow(rows=40, cols=100)

    # Re-rendering 5 times
    for _ in range(5):
        dashboard.render(win)
        dashboard.get_display_lines(rows=40, cols=100)

    assert dashboard.orders_processed == 125


def test_orders_processed_no_negative_counts():
    """5. Verify negative values are rejected across setters, increments, and initialization."""
    dashboard = TerminalDashboard()

    with pytest.raises(ValueError, match="cannot be negative"):
        dashboard.set_orders_processed(-1)

    with pytest.raises(ValueError, match="cannot be negative"):
        dashboard.orders_processed = -5

    with pytest.raises(ValueError, match="cannot be negative"):
        dashboard.increment_orders_processed(-3)

    with pytest.raises(ValueError, match="cannot be negative"):
        TerminalDashboard(orders_processed=-10)

    with pytest.raises(ValueError, match="cannot be negative"):
        format_orders_processed(-1)

    # Counter remains at 0
    assert dashboard.orders_processed == 0


def test_orders_processed_large_count_formatting():
    """6. Verify large values are formatted clearly with thousands separators."""
    assert format_orders_processed(0) == "0"
    assert format_orders_processed(125) == "125"
    assert format_orders_processed(12500) == "12,500"
    assert format_orders_processed(1000000) == "1,000,000"
    assert format_orders_processed(9876543210) == "9,876,543,210"
    assert format_orders_processed(None) == PLACEHOLDER
    assert format_total_orders(12500) == "12,500"

    # Formatting in build_performance_lines
    lines_int = build_performance_lines(width=68, total_orders=12500)
    assert "12,500" in "\n".join(lines_int)

    lines_alias = build_performance_lines(width=68, orders_processed=12500)
    assert "12,500" in "\n".join(lines_alias)

    # Formatted in dashboard lines
    dashboard = TerminalDashboard(orders_processed=12500)
    display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))
    assert "12,500" in display


def test_orders_processed_renders_in_intended_section():
    """7. Verify counter renders directly in the PERFORMANCE METRICS section."""
    dashboard = TerminalDashboard(orders_processed=125)
    lines = dashboard.get_display_lines(rows=40, cols=100)

    perf_idx = next(i for i, line in enumerate(lines) if SECTION_PERFORMANCE in line)
    footer_idx = next(i for i, line in enumerate(lines) if QUIT_MESSAGE in line)
    perf_section = "\n".join(lines[perf_idx:footer_idx])

    assert LABEL_TOTAL_ORDERS in perf_section
    assert LABEL_ORDERS_PROCESSED in perf_section
    assert "125" in perf_section

    # Verify MockCursesWindow addstr calls contain the counter in the performance row
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    perf_calls = [c[2] for c in win.addstr_calls if LABEL_TOTAL_ORDERS in c[2]]
    assert len(perf_calls) == 1
    assert "125" in perf_calls[0]


def test_orders_processed_updates_after_state_changes():
    """8. Verify dashboard display reflects updates when counter state changes."""
    dashboard = TerminalDashboard(orders_processed=0)
    assert " 0" in "\n".join(dashboard.get_display_lines(rows=40, cols=100))

    # Update via setter / update_orders_processed
    dashboard.update_orders_processed(125)
    assert "125" in "\n".join(dashboard.get_display_lines(rows=40, cols=100))

    # Update via increment
    dashboard.increment_orders_processed(75)
    assert "200" in "\n".join(dashboard.get_display_lines(rows=40, cols=100))

    # Reset
    dashboard.reset_orders_processed()
    assert " 0" in "\n".join(dashboard.get_display_lines(rows=40, cols=100))


def test_orders_processed_existing_market_summary_still_renders():
    """9. Verify Best Bid, Best Ask, and Spread still render accurately with counter active."""
    dashboard = TerminalDashboard(orders_processed=125)
    display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))

    # Market Summary headers and fields
    assert SECTION_MARKET_SUMMARY in display
    assert LABEL_BEST_BID in display
    assert LABEL_BID_QTY in display
    assert LABEL_BEST_ASK in display
    assert LABEL_ASK_QTY in display
    assert LABEL_SPREAD in display

    # Values for sample data
    assert "510.00" in display  # Best Bid
    assert "150" in display     # Bid Qty
    assert "505.00" in display  # Best Ask
    assert "40" in display      # Ask Qty
    assert "-5.00" in display   # Spread


def test_orders_processed_best_bid_ask_and_depth_still_function():
    """10. Verify order-book depth (top-5 levels) continues functioning with counter active."""
    dashboard = TerminalDashboard(orders_processed=125)
    display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))

    assert SECTION_ORDER_BOOK in display
    assert SECTION_BUY_ORDERS in display
    assert SECTION_SELL_ORDERS in display

    # Top 5 BUY depth levels
    assert "510.00" in display
    assert "505.00" in display
    assert "500.00" in display
    assert "495.00" in display
    assert "490.00" in display

    # Top 5 SELL depth levels
    assert "515.00" in display
    assert "520.00" in display
    assert "525.00" in display


def test_orders_processed_small_terminal_does_not_crash():
    """11. Verify small terminal fallback does not crash with counter values."""
    dashboard = TerminalDashboard(orders_processed=12500)
    win = MockCursesWindow(rows=5, cols=20)

    # Render on small window must not throw
    dashboard.render(win)

    assert win.erased is True
    assert win.refreshed is True
    rendered = " ".join([c[2] for c in win.addstr_calls])
    assert "too small" in rendered.lower()
    assert QUIT_MESSAGE in rendered


def test_orders_processed_refresh_and_quit_behavior_remain_intact():
    """12. Verify event loop refresh cycles, timeout, and Q-to-quit work with counter."""
    dashboard = TerminalDashboard(orders_processed=125)

    # Input handling
    assert dashboard.handle_input(ord("q")) is False
    assert dashboard.handle_input(ord("Q")) is False
    assert dashboard.handle_input(ord("r")) is True

    # Event loop run
    win = MockCursesWindow(rows=40, cols=100, keys=[-1, ord("q")])
    dashboard.run_curses(win, max_iterations=10)

    assert dashboard.is_running is False
    assert dashboard.frame_count == 2
    assert dashboard.orders_processed == 125


# ===========================================================================
# Day 7 - Throughput Metric tests
# ===========================================================================


class FakeClock:
    """Injectable fake monotonic clock for deterministic testing without sleeps."""

    def __init__(self, start: float = 100.0) -> None:
        self.current_time = start

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


def test_throughput_correct_calculation_for_known_delta_and_elapsed():
    """1. Correct throughput calculation for known count delta and elapsed interval."""
    # delta = 500 orders, elapsed = 1.0 second -> 500.0 orders/sec
    assert calculate_throughput(500, 1.0) == 500.0

    # delta = 1000 orders, elapsed = 2.0 seconds -> 500.0 orders/sec
    assert calculate_throughput(1000, 2.0) == 500.0

    # delta = 150 orders, elapsed = 0.5 seconds -> 300.0 orders/sec
    assert calculate_throughput(150, 0.5) == 300.0

    # delta = 1 order, elapsed = 0.001 seconds -> 1000.0 orders/sec
    assert calculate_throughput(1, 0.001) == 1000.0

    # delta = 100 orders, elapsed = 3.0 seconds -> 33.33 orders/sec (rounded to 2 decimal places)
    assert calculate_throughput(100, 3.0) == 33.33

    # Using calculate_throughput_from_counts helper
    assert calculate_throughput_from_counts(1500, 500, 2.0) == 500.0


def test_throughput_zero_elapsed_time_without_crashing():
    """2. Zero elapsed time without crashing or division by zero."""
    # Pure function with zero elapsed time returns None safely
    assert calculate_throughput(100, 0) is None
    assert calculate_throughput(0, 0.0) is None
    assert calculate_throughput_from_counts(100, 0, 0) is None

    # Dashboard state update with zero elapsed time
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=0)

    # Establish baseline
    dashboard.update_throughput()

    # Attempt to update again with zero elapsed time (clock did not advance)
    dashboard.increment_orders_processed(50)
    val = dashboard.update_throughput()
    # Does not crash or divide by zero; returns previous throughput (None)
    assert val is None

    # Render and get_display_lines calls with zero elapsed time must not crash
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    lines = dashboard.get_display_lines(rows=40, cols=100)
    assert len(lines) > 0


def test_throughput_no_new_orders_produces_zero_or_no_sample_state():
    """3. No new orders produces zero over an elapsed interval, or documented no-sample state."""
    # Zero orders over valid interval produces 0.0
    assert calculate_throughput(0, 1.0) == 0.0
    assert calculate_throughput(0, 5.0) == 0.0

    # In dashboard: counter value that does not advance over an elapsed interval produces 0.0
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=100)
    dashboard.update_throughput()  # baseline at t=100.0, count=100

    # 2 seconds pass, but no orders are added (delta = 0)
    clock.advance(2.0)
    tp = dashboard.update_throughput()
    assert tp == 0.0
    assert dashboard.get_throughput_display() == "0.00"

    # Initial state with no elapsed interval produces project's no-sample state
    fresh_dashboard = TerminalDashboard(use_sample_data=False)
    assert fresh_dashboard.throughput is None
    assert fresh_dashboard.get_throughput_display() == NO_SAMPLE_THROUGHPUT
    assert format_throughput(None) == NO_SAMPLE_THROUGHPUT


def test_throughput_increasing_processed_orders_updates_throughput():
    """4. Increasing processed-order counts update throughput across refresh cycles."""
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=0)
    dashboard.update_throughput()  # baseline at t=100.0, count=0

    # Interval 1: 500 orders processed in 1.0 second
    clock.advance(1.0)
    dashboard.increment_orders_processed(500)
    dashboard.update_throughput()
    assert dashboard.throughput == 500.0
    assert "500.00" in dashboard.get_throughput_display()

    # Interval 2: 250 orders processed in 1.0 second
    clock.advance(1.0)
    dashboard.increment_orders_processed(250)
    dashboard.update_throughput()
    assert dashboard.throughput == 250.0
    assert "250.00" in dashboard.get_throughput_display()

    # Interval 3: 2000 orders processed in 2.0 seconds -> 1000 orders/sec
    clock.advance(2.0)
    dashboard.increment_orders_processed(2000)
    dashboard.update_throughput()
    assert dashboard.throughput == 1000.0
    assert "1,000.00" in dashboard.get_throughput_display()


def test_throughput_redrawing_dashboard_does_not_change_order_count():
    """5. Redrawing the dashboard does not change the processed-order count."""
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=125)
    win = MockCursesWindow(rows=40, cols=100)

    # Establish baseline
    dashboard.update_throughput()
    clock.advance(1.0)

    # Redraw 10 times via render and get_display_lines
    for _ in range(10):
        dashboard.render(win)
        dashboard.get_display_lines(rows=40, cols=100)

    # Counter must remain exactly 125
    assert dashboard.orders_processed == 125


def test_throughput_deterministic_injected_clock_behavior():
    """6. Monotonic clock behavior or injected deterministic clock values."""
    import time

    # Verify default clock is time.monotonic
    default_dashboard = TerminalDashboard()
    assert default_dashboard._clock is time.monotonic

    # Injected deterministic clock
    clock = FakeClock(50.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=10)
    dashboard.update_throughput()

    # Step-by-step verification without sleep
    clock.advance(0.5)
    dashboard.increment_orders_processed(100)
    assert dashboard.update_throughput() == 200.0

    clock.advance(0.5)
    dashboard.increment_orders_processed(150)
    assert dashboard.update_throughput() == 300.0


def test_throughput_invalid_intervals_and_deltas_handled_safely():
    """7. Invalid or negative elapsed intervals and deltas are handled safely."""
    # Negative elapsed interval
    assert calculate_throughput(100, -1.0) is None
    assert calculate_throughput(100, -0.001) is None

    # Negative delta orders
    assert calculate_throughput(-50, 1.0) is None

    # None inputs
    assert calculate_throughput(None, 1.0) is None
    assert calculate_throughput(100, None) is None
    assert calculate_throughput(None, None) is None

    # Non-numeric or invalid types
    assert calculate_throughput("invalid", 1.0) is None
    assert calculate_throughput(100, "invalid") is None

    # Float NaN and Inf
    assert calculate_throughput(float("nan"), 1.0) is None
    assert calculate_throughput(100, float("nan")) is None
    assert calculate_throughput(100, float("inf")) is None

    # Dashboard clock backwards jump handled safely
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=50)
    dashboard.update_throughput()
    clock.advance(-10.0)  # clock moved backwards
    assert dashboard.update_throughput() is None  # Handled safely without crash


def test_throughput_large_value_formatting():
    """8. Large throughput values are formatted with thousands separators."""
    assert format_throughput(0) == "0.00"
    assert format_throughput(500) == "500.00"
    assert format_throughput(12500) == "12,500.00"
    assert format_throughput(1000000) == "1,000,000.00"
    assert format_throughput(9876543210.5) == "9,876,543,210.50"
    assert format_throughput(500, include_unit=True) == "500.00 orders/sec"
    assert format_throughput(500, decimals=0, include_unit=True) == "500 orders/sec"
    assert format_throughput("DEMO") == "DEMO"
    assert format_throughput("N/A") == "N/A"

    # Negative value raises ValueError
    with pytest.raises(ValueError, match="cannot be negative"):
        format_throughput(-1.0)

    # In build_performance_lines with large throughput
    lines = build_performance_lines(width=68, throughput=1000000)
    joined = "\n".join(lines)
    assert "1,000,000.00" in joined


def test_throughput_appears_in_dashboard_output():
    """9. Throughput metric field appears in the dashboard rendered output."""
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=0)
    dashboard.update_throughput()

    # Advance clock and orders
    clock.advance(1.0)
    dashboard.increment_orders_processed(500)

    display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))
    assert SECTION_PERFORMANCE in display
    assert LABEL_THROUGHPUT in display
    assert "500.00" in display

    # In MockCursesWindow
    win = MockCursesWindow(rows=40, cols=100)
    dashboard.render(win)
    tp_calls = [c[2] for c in win.addstr_calls if LABEL_THROUGHPUT in c[2]]
    assert len(tp_calls) == 1
    assert "500.00" in tp_calls[0]

    # Explicit DEMO mode labeling
    demo_dashboard = TerminalDashboard(use_sample_data=True)
    demo_display = "\n".join(demo_dashboard.get_display_lines(rows=40, cols=100))
    assert DEMO_THROUGHPUT in demo_display


def test_throughput_existing_orders_processed_counter_remains_correct():
    """10. Existing processed-order counter remains correct when throughput updates."""
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=50)

    # Process events
    dashboard.record_order_processed({"order_id": 999, "price": 500.0, "quantity": 10})
    assert dashboard.orders_processed == 51

    dashboard.increment_orders_processed(49)
    assert dashboard.orders_processed == 100

    clock.advance(1.0)
    dashboard.update_throughput()
    assert dashboard.orders_processed == 100

    # Formatted total orders string matches
    lines = dashboard.get_display_lines(rows=40, cols=100)
    perf_idx = next(i for i, line in enumerate(lines) if SECTION_PERFORMANCE in line)
    footer_idx = next(i for i, line in enumerate(lines) if QUIT_MESSAGE in line)
    perf_section = "\n".join(lines[perf_idx:footer_idx])
    assert "100" in perf_section


def test_throughput_existing_bid_ask_spread_and_depth_still_render():
    """11. Existing Best Bid/Ask, Spread, and 5-level Depth sections still render."""
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=125)
    clock.advance(1.0)
    dashboard.increment_orders_processed(500)

    display = "\n".join(dashboard.get_display_lines(rows=40, cols=100))

    # Market summary preserved
    assert SECTION_MARKET_SUMMARY in display
    assert LABEL_BEST_BID in display
    assert "510.00" in display
    assert LABEL_BEST_ASK in display
    assert "505.00" in display
    assert LABEL_SPREAD in display
    assert "-5.00" in display

    # Order book depth preserved
    assert SECTION_ORDER_BOOK in display
    assert SECTION_BUY_ORDERS in display
    assert SECTION_SELL_ORDERS in display
    assert "490.00" in display
    assert "525.00" in display


def test_throughput_small_terminal_and_quit_behavior_remain_intact():
    """12. Small terminal fallback and Q-to-quit behavior remain intact with throughput."""
    clock = FakeClock(100.0)
    dashboard = TerminalDashboard(clock=clock, orders_processed=125)

    # Small terminal window
    small_win = MockCursesWindow(rows=5, cols=20)
    dashboard.render(small_win)
    assert small_win.erased is True
    assert small_win.refreshed is True
    small_output = " ".join([c[2] for c in small_win.addstr_calls])
    assert "too small" in small_output.lower()
    assert QUIT_MESSAGE in small_output

    # Input handling
    assert dashboard.handle_input(ord("q")) is False
    assert dashboard.handle_input(ord("Q")) is False
    assert dashboard.handle_input(ord("z")) is True

    # Curses event loop with throughput active
    loop_win = MockCursesWindow(rows=40, cols=100, keys=[-1, ord("q")])
    dashboard.run_curses(loop_win, max_iterations=10)
    assert dashboard.is_running is False
    assert dashboard.frame_count == 2




