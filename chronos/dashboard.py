"""Terminal latency dashboard foundation for ChronosMatch.

Provides an interactive curses-based monitoring dashboard adhering to
safe terminal restoration and low-CPU event loops.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, List, Optional

try:
    import curses
except ImportError:  # pragma: no cover
    curses = None  # type: ignore[assignment]


# Core display constants
APP_TITLE = "CHRONOSMATCH"
APP_SUBTITLE = "Zero-Copy High-Frequency Trading Engine"
STATUS_MESSAGE = "Dashboard Initialized"
QUIT_MESSAGE = "Press Q to Quit"

# Default terminal constraints
DEFAULT_REFRESH_INTERVAL_MS = 100
MIN_TERMINAL_ROWS = 8
MIN_TERMINAL_COLS = 50


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration parameters for the terminal dashboard."""

    refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS
    min_rows: int = MIN_TERMINAL_ROWS
    min_cols: int = MIN_TERMINAL_COLS


class TerminalDashboard:
    """Curses-based terminal dashboard foundation for ChronosMatch."""

    def __init__(self, config: Optional[DashboardConfig] = None) -> None:
        """Initialize the dashboard with optional configuration."""
        self.config = config or DashboardConfig()
        self.is_running = False
        self.frame_count = 0

    def is_terminal_size_sufficient(self, rows: int, cols: int) -> bool:
        """Verify whether the terminal window meets minimum required dimensions."""
        return rows >= self.config.min_rows and cols >= self.config.min_cols

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

    def get_display_lines(self, rows: int, cols: int) -> List[str]:
        """Generate lines of text for rendering.

        Useful for noninteractive testing and headless validation.
        """
        if not self.is_terminal_size_sufficient(rows, cols):
            return [
                "Screen too small!",
                f"Min: {self.config.min_cols}x{self.config.min_rows}",
                f"Current: {cols}x{rows}",
                QUIT_MESSAGE,
            ]

        border = "=" * min(cols - 2, 68)
        divider = "-" * min(cols - 2, 68)

        return [
            border,
            f"  {APP_TITLE}",
            f"  {APP_SUBTITLE}",
            divider,
            f"  {STATUS_MESSAGE}",
            divider,
            f"  {QUIT_MESSAGE}",
            border,
        ]

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

            curses.init_pair(1, curses.COLOR_CYAN, bg)    # Title
            curses.init_pair(2, curses.COLOR_GREEN, bg)   # Status
            curses.init_pair(3, curses.COLOR_YELLOW, bg)  # Quit instruction
            curses.init_pair(4, curses.COLOR_WHITE, bg)   # Subtitle & borders
        except Exception:
            pass

    def render(self, stdscr: Any) -> None:
        """Render a single frame of the dashboard onto the curses window."""
        try:
            stdscr.erase()
        except Exception:
            pass

        try:
            max_y, max_x = stdscr.getmaxyx()
        except Exception:
            return

        if not self.is_terminal_size_sufficient(max_y, max_x):
            lines = self.get_display_lines(max_y, max_x)
            for idx, line in enumerate(lines):
                self._safe_addstr(stdscr, idx, 0, line)
            try:
                stdscr.refresh()
            except Exception:
                pass
            return

        # Prepare formatting attributes
        title_attr = 0
        subtitle_attr = 0
        status_attr = 0
        quit_attr = 0
        border_attr = 0

        if curses is not None:
            bold = getattr(curses, "A_BOLD", 0)
            dim = getattr(curses, "A_DIM", 0)

            title_attr = bold
            status_attr = bold
            subtitle_attr = 0
            quit_attr = dim
            border_attr = dim

            if self._has_colors_safe():
                try:
                    title_attr |= curses.color_pair(1)
                    subtitle_attr |= curses.color_pair(4)
                    status_attr |= curses.color_pair(2)
                    quit_attr |= curses.color_pair(3)
                    border_attr |= curses.color_pair(4)
                except Exception:
                    pass

        width = min(max_x - 4, 70)
        border = "=" * width
        divider = "-" * width

        start_y = 1
        start_x = 2

        self._safe_addstr(stdscr, start_y + 0, start_x, border, border_attr)
        self._safe_addstr(stdscr, start_y + 1, start_x, f"  {APP_TITLE}", title_attr)
        self._safe_addstr(stdscr, start_y + 2, start_x, f"  {APP_SUBTITLE}", subtitle_attr)
        self._safe_addstr(stdscr, start_y + 3, start_x, divider, border_attr)
        self._safe_addstr(stdscr, start_y + 4, start_x, f"  [+] {STATUS_MESSAGE}", status_attr)
        self._safe_addstr(stdscr, start_y + 5, start_x, divider, border_attr)
        self._safe_addstr(stdscr, start_y + 6, start_x, f"  {QUIT_MESSAGE}", quit_attr)
        self._safe_addstr(stdscr, start_y + 7, start_x, border, border_attr)

        try:
            stdscr.refresh()
        except Exception:
            pass

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
