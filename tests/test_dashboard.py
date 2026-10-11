"""Unit tests for ChronosMatch Terminal Dashboard Foundation.

Validates noninteractive dashboard logic, configuration, display strings,
input processing, and mock window rendering without requiring a live terminal.
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
    QUIT_MESSAGE,
    STATUS_MESSAGE,
    DashboardConfig,
    TerminalDashboard,
)


class MockCursesWindow:
    """Mock curses window to inspect rendering and screen interactions."""

    def __init__(self, rows: int = 24, cols: int = 80, keys: List[int] = None) -> None:
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
    dashboard = TerminalDashboard(DashboardConfig(min_rows=8, min_cols=50))

    # Equal to minimum
    assert dashboard.is_terminal_size_sufficient(8, 50) is True

    # Larger than minimum
    assert dashboard.is_terminal_size_sufficient(24, 80) is True

    # Too few rows
    assert dashboard.is_terminal_size_sufficient(7, 50) is False

    # Too few columns
    assert dashboard.is_terminal_size_sufficient(8, 49) is False

    # Both dimensions too small
    assert dashboard.is_terminal_size_sufficient(5, 20) is False


def test_get_display_lines_content():
    """Verify generated display text contains required titles, status, and quit hint."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=24, cols=80)
    full_output = "\n".join(lines)

    assert APP_TITLE in full_output
    assert APP_SUBTITLE in full_output
    assert STATUS_MESSAGE in full_output
    assert QUIT_MESSAGE in full_output


def test_get_display_lines_too_small():
    """Verify warning message when terminal dimensions are insufficient."""
    dashboard = TerminalDashboard()
    lines = dashboard.get_display_lines(rows=5, cols=20)
    full_output = "\n".join(lines)

    assert "too small" in full_output.lower()
    assert QUIT_MESSAGE in full_output


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
    win = MockCursesWindow(rows=24, cols=80)

    dashboard.render(win)

    assert win.erased is True
    assert win.refreshed is True

    # Aggregate all text written across addstr calls
    rendered_text = " ".join([call[2] for call in win.addstr_calls])
    assert APP_TITLE in rendered_text
    assert APP_SUBTITLE in rendered_text
    assert STATUS_MESSAGE in rendered_text
    assert QUIT_MESSAGE in rendered_text


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
    win = MockCursesWindow(rows=24, cols=80, keys=[-1, -1])

    dashboard.run_curses(win, max_iterations=2)

    assert dashboard.frame_count == 2
    assert win.timeout_val == dashboard.config.refresh_interval_ms
    assert win.refreshed is True


def test_run_curses_event_loop_quits_on_q():
    """Verify run_curses event loop terminates immediately when 'q' is pressed."""
    dashboard = TerminalDashboard()
    win = MockCursesWindow(rows=24, cols=80, keys=[-1, ord("q"), -1])

    dashboard.run_curses(win, max_iterations=10)

    assert dashboard.is_running is False
    assert dashboard.frame_count == 2  # Terminated on second iteration


def test_run_missing_curses_raises_runtime_error():
    """Verify informative RuntimeError when curses module is unavailable."""
    dashboard = TerminalDashboard()

    with patch("chronos.dashboard.curses", None):
        with pytest.raises(RuntimeError, match="curses library is not available"):
            dashboard.run()
