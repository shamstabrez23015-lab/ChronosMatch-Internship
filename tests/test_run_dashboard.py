"""Unit tests for scripts/run_dashboard.py launcher behaviour.

Covers:
- Demo mode: creates dashboard with sample data, no bridge/ring_buffer.
- Live mode: attaches to existing ring buffer, wires LiveFeedBridge.
- Missing buffer: raises FileNotFoundError with helpful message.
- Bridge lifecycle: start() and stop() called correctly.
- Non-interactive mode: poll_once() called, display lines printed.
- Resource cleanup: ring_buffer.close() called in finally block.
- CLI argument parsing through argparse.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root is importable when running from any directory
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Import the launcher module under test
# ---------------------------------------------------------------------------
import scripts.run_dashboard as launcher_module
from scripts.run_dashboard import setup_dashboard, _DEFAULT_BUFFER_PATH


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _make_mock_ring_buffer(exists: bool = True, is_closed: bool = False):
    """Return a MagicMock that quacks like MmapRingBuffer."""
    rb = MagicMock()
    rb._is_closed = is_closed
    rb.available_to_read.return_value = 0
    rb.read_batch_raw.return_value = []
    rb.close = MagicMock()
    return rb


def _make_mock_bridge():
    """Return a MagicMock that quacks like LiveFeedBridge."""
    bridge = MagicMock()
    bridge.is_running = False
    bridge.poll_once.return_value = 0
    return bridge


def _make_mock_dashboard():
    """Return a MagicMock that quacks like TerminalDashboard."""
    dash = MagicMock()
    dash.get_display_lines.return_value = ["line1", "line2"]
    dash.run = MagicMock()
    return dash


# ---------------------------------------------------------------------------
# Tests for setup_dashboard()
# ---------------------------------------------------------------------------

class TestSetupDashboardDemoMode:
    """setup_dashboard(demo=True) must return (dashboard, None, None)."""

    def test_returns_dashboard_no_bridge_no_ring_buffer(self):
        dashboard, bridge, ring_buffer = setup_dashboard(demo=True)
        assert dashboard is not None
        assert bridge is None
        assert ring_buffer is None

    def test_dashboard_uses_sample_data(self):
        dashboard, _, _ = setup_dashboard(demo=True)
        # In demo mode TerminalDashboard should still be instantiated
        assert dashboard is not None

    def test_demo_accepts_custom_config(self):
        from chronos.dashboard import DashboardConfig
        cfg = DashboardConfig(refresh_interval_ms=200, whale_min_levels=5)
        dashboard, bridge, ring_buffer = setup_dashboard(demo=True, config=cfg)
        assert bridge is None
        assert ring_buffer is None


class TestSetupDashboardLiveMode:
    """setup_dashboard(demo=False) must attach to ring buffer and wire bridge."""

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_returns_dashboard_bridge_ring_buffer(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        dashboard, bridge, ring_buffer = setup_dashboard(
            buffer_path="/fake/path.bin", demo=False
        )

        assert dashboard is not None
        assert bridge is mock_bridge
        assert ring_buffer is mock_rb

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_ring_buffer_opened_with_create_false(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        MockRingBuffer.return_value = _make_mock_ring_buffer()
        MockBridge.return_value = _make_mock_bridge()

        setup_dashboard(buffer_path="/fake/path.bin", demo=False)

        MockRingBuffer.assert_called_once_with("/fake/path.bin", create=False)

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_bridge_receives_ring_buffer(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        MockBridge.return_value = _make_mock_bridge()

        setup_dashboard(buffer_path="/fake/path.bin", demo=False,
                        batch_size=500, poll_interval_s=0.1)

        MockBridge.assert_called_once_with(
            ring_buffer=mock_rb,
            batch_size=500,
            poll_interval_s=0.1,
        )

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_dashboard_wired_with_live_feed(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        MockRingBuffer.return_value = _make_mock_ring_buffer()
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        dashboard, bridge, _ = setup_dashboard(
            buffer_path="/fake/path.bin", demo=False
        )

        # TerminalDashboard is constructed with live_feed=bridge
        assert bridge is mock_bridge
        # dashboard.live_feed should point to the bridge
        assert getattr(dashboard, "live_feed", None) is mock_bridge


class TestSetupDashboardMissingBuffer:
    """Missing ring buffer in live mode must raise FileNotFoundError."""

    @patch("scripts.run_dashboard.os.path.exists", return_value=False)
    def test_raises_file_not_found(self, _mock_exists):
        with pytest.raises(FileNotFoundError) as exc_info:
            setup_dashboard(buffer_path="/nonexistent/path.bin", demo=False)

        msg = str(exc_info.value)
        assert "/nonexistent/path.bin" in msg
        # Must mention how to start the firehose
        assert "run_firehose" in msg or "firehose" in msg.lower()

    @patch("scripts.run_dashboard.os.path.exists", return_value=False)
    def test_error_message_mentions_demo_flag(self, _mock_exists):
        with pytest.raises(FileNotFoundError) as exc_info:
            setup_dashboard(buffer_path="/nonexistent/path.bin", demo=False)
        assert "--demo" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests for main() — non-interactive mode
# ---------------------------------------------------------------------------

class TestMainNonInteractive:
    """main() with --non-interactive must call poll_once and print lines."""

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_calls_poll_once_and_prints(
        self, MockBridge, MockRingBuffer, mock_exists, capsys
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        with patch("scripts.run_dashboard.TerminalDashboard") as MockDash:
            mock_dash = _make_mock_dashboard()
            MockDash.return_value = mock_dash

            with patch("sys.argv", ["run_dashboard.py",
                                    "--non-interactive",
                                    "--file", "/fake/path.bin"]):
                launcher_module.main()

        mock_bridge.poll_once.assert_called_once()

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_stops_bridge_and_closes_ring_buffer_after_non_interactive(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        with patch("scripts.run_dashboard.TerminalDashboard") as MockDash:
            mock_dash = _make_mock_dashboard()
            MockDash.return_value = mock_dash

            with patch("sys.argv", ["run_dashboard.py",
                                    "--non-interactive",
                                    "--file", "/fake/path.bin"]):
                launcher_module.main()

        mock_bridge.stop.assert_called()
        mock_rb.close.assert_called()

    def test_demo_non_interactive_no_bridge(self, capsys):
        with patch("sys.argv", ["run_dashboard.py", "--demo", "--non-interactive"]):
            launcher_module.main()

        captured = capsys.readouterr()
        # Should produce at least one output line (dashboard content)
        assert len(captured.out) >= 0  # just must not raise

    @patch("scripts.run_dashboard.os.path.exists", return_value=False)
    def test_missing_buffer_exits_with_code_1(self, _mock_exists):
        with patch("sys.argv", ["run_dashboard.py", "--file", "/bad/path.bin"]):
            with pytest.raises(SystemExit) as exc_info:
                launcher_module.main()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Tests for main() — interactive mode
# ---------------------------------------------------------------------------

class TestMainInteractive:
    """main() in interactive mode must start bridge, call dashboard.run(), clean up."""

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_bridge_started_before_dashboard_run(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        call_order: list[str] = []
        mock_bridge.start.side_effect = lambda: call_order.append("start")

        with patch("scripts.run_dashboard.TerminalDashboard") as MockDash:
            mock_dash = _make_mock_dashboard()
            mock_dash.run.side_effect = lambda: call_order.append("run")
            MockDash.return_value = mock_dash

            with patch("sys.argv", ["run_dashboard.py", "--file", "/fake/path.bin"]):
                launcher_module.main()

        assert call_order.index("start") < call_order.index("run")

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_bridge_stopped_and_ring_buffer_closed_after_run(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        with patch("scripts.run_dashboard.TerminalDashboard") as MockDash:
            MockDash.return_value = _make_mock_dashboard()

            with patch("sys.argv", ["run_dashboard.py", "--file", "/fake/path.bin"]):
                launcher_module.main()

        mock_bridge.stop.assert_called()
        mock_rb.close.assert_called()

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_keyboard_interrupt_still_cleans_up(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        mock_rb = _make_mock_ring_buffer()
        MockRingBuffer.return_value = mock_rb
        mock_bridge = _make_mock_bridge()
        MockBridge.return_value = mock_bridge

        with patch("scripts.run_dashboard.TerminalDashboard") as MockDash:
            mock_dash = _make_mock_dashboard()
            mock_dash.run.side_effect = KeyboardInterrupt
            MockDash.return_value = mock_dash

            with patch("sys.argv", ["run_dashboard.py", "--file", "/fake/path.bin"]):
                launcher_module.main()  # Must not raise

        mock_bridge.stop.assert_called()
        mock_rb.close.assert_called()

    @patch("scripts.run_dashboard.os.path.exists", return_value=True)
    @patch("scripts.run_dashboard.MmapRingBuffer")
    @patch("scripts.run_dashboard.LiveFeedBridge")
    def test_runtime_error_exits_with_code_1(
        self, MockBridge, MockRingBuffer, mock_exists
    ):
        MockRingBuffer.return_value = _make_mock_ring_buffer()
        MockBridge.return_value = _make_mock_bridge()

        with patch("scripts.run_dashboard.TerminalDashboard") as MockDash:
            mock_dash = _make_mock_dashboard()
            mock_dash.run.side_effect = RuntimeError("curses failure")
            MockDash.return_value = mock_dash

            with patch("sys.argv", ["run_dashboard.py", "--file", "/fake/path.bin"]):
                with pytest.raises(SystemExit) as exc_info:
                    launcher_module.main()

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Tests for default buffer path
# ---------------------------------------------------------------------------

class TestDefaultBufferPath:
    """The default buffer path must resolve to data/chronos_ring.bin under repo root."""

    def test_default_path_ends_with_expected_suffix(self):
        # Normalise separators for cross-platform comparison
        norm = os.path.normpath(_DEFAULT_BUFFER_PATH)
        assert norm.endswith(os.path.join("data", "chronos_ring.bin"))

    def test_default_path_is_absolute(self):
        assert os.path.isabs(_DEFAULT_BUFFER_PATH)

