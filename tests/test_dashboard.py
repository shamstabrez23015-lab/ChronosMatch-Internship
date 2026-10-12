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
    LABEL_BEST_ASK,
    LABEL_SPREAD,
    LABEL_TOTAL_ORDERS,
    LABEL_THROUGHPUT,
    LABEL_LATENCY,
    DashboardConfig,
    TerminalDashboard,
    build_header_lines,
    build_market_summary_lines,
    build_order_book_lines,
    build_performance_lines,
    build_footer_lines,
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
