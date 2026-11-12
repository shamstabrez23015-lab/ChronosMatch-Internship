"""CLI launcher for the ChronosMatch Terminal Dashboard."""

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chronos.dashboard import DashboardConfig, TerminalDashboard

# Default ring buffer path, relative to the repository root (same as run_firehose.py)
_DEFAULT_BUFFER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "chronos_ring.bin")
)

# Module-level imports for testability (patchable via scripts.run_dashboard.*)
try:
    from chronos.ring_buffer import MmapRingBuffer
    from chronos.live_feed import LiveFeedBridge
except Exception:  # pragma: no cover – extension not compiled or missing
    MmapRingBuffer = None  # type: ignore[assignment,misc]
    LiveFeedBridge = None  # type: ignore[assignment,misc]


def setup_dashboard(
    buffer_path: str = _DEFAULT_BUFFER_PATH,
    demo: bool = False,
    config: "DashboardConfig | None" = None,
    batch_size: int = 1000,
    poll_interval_s: float = 0.05,
):
    """Create and wire up a TerminalDashboard with optional live feed.

    Args:
        buffer_path: Absolute path to the memory-mapped ring buffer file.
        demo:        When True, use built-in sample data instead of live feed.
        config:      DashboardConfig instance; created with defaults if None.
        batch_size:  Orders to drain per poll iteration (live mode only).
        poll_interval_s: Background poll sleep interval (live mode only).

    Returns:
        (dashboard, bridge, ring_buffer) — bridge and ring_buffer are None in demo mode.

    Raises:
        FileNotFoundError: If live mode is requested and the ring buffer file is absent.
    """
    if config is None:
        config = DashboardConfig()

    if demo:
        dashboard = TerminalDashboard(config=config)
        return dashboard, None, None

    # --- Live mode ---
    if MmapRingBuffer is None or LiveFeedBridge is None:
        raise RuntimeError(
            "Live mode requires MmapRingBuffer and LiveFeedBridge. "
            "Please ensure Cython extensions and dependencies are built, "
            "or run with --demo for sample data."
        )

    if not os.path.exists(buffer_path):
        raise FileNotFoundError(
            f"Ring buffer not found: {buffer_path}\n"
            "Start the Market Firehose first:\n"
            "    python scripts/run_firehose.py\n"
            "Or use --demo for sample data."
        )

    ring_buffer = MmapRingBuffer(buffer_path, create=False)

    bridge = LiveFeedBridge(
        ring_buffer=ring_buffer,
        batch_size=batch_size,
        poll_interval_s=poll_interval_s,
    )

    dashboard = TerminalDashboard(config=config, live_feed=bridge)
    return dashboard, bridge, ring_buffer


def main() -> None:
    """Entry point for running the ChronosMatch curses terminal dashboard."""
    parser = argparse.ArgumentParser(
        description="ChronosMatch Terminal Dashboard - Low-latency curses monitor"
    )
    parser.add_argument(
        "--file",
        "--buffer-path",
        dest="buffer_path",
        default=_DEFAULT_BUFFER_PATH,
        help=f"Path to the ring buffer file (default: {_DEFAULT_BUFFER_PATH})",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run with built-in sample data instead of a live ring buffer",
    )
    parser.add_argument(
        "--refresh-ms",
        type=int,
        default=100,
        help="Dashboard refresh interval in milliseconds (default: 100ms)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Orders drained per poll iteration in live mode (default: 1000)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.05,
        help="Background poll sleep interval in seconds in live mode (default: 0.05)",
    )
    parser.add_argument(
        "--trade-latency-unit",
        type=str,
        choices=["us", "ns"],
        default="us",
        help="Trade execution latency display unit: 'us' or 'ns' (default: 'us')",
    )
    parser.add_argument(
        "--whale-threshold",
        type=int,
        default=2,
        help="Whale order minimum price levels sweep threshold (default: 2)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Print a single dashboard frame to stdout without curses "
            "(useful for headless/CI environments)"
        ),
    )
    args = parser.parse_args()

    config = DashboardConfig(
        refresh_interval_ms=args.refresh_ms,
        trade_latency_unit=args.trade_latency_unit,
        whale_min_levels=args.whale_threshold,
    )

    try:
        dashboard, bridge, ring_buffer = setup_dashboard(
            buffer_path=args.buffer_path,
            demo=args.demo,
            config=config,
            batch_size=args.batch_size,
            poll_interval_s=args.poll_interval,
        )
    except FileNotFoundError as exc:
        print(f"\n[!] {exc}", file=sys.stderr)
        sys.exit(1)

    if args.non_interactive:
        try:
            if bridge is not None:
                bridge.poll_once()
            for line in dashboard.get_display_lines(rows=40, cols=100):
                print(line)
        finally:
            if bridge is not None:
                bridge.stop()
            if ring_buffer is not None:
                ring_buffer.close()
        return

    # Interactive curses mode
    try:
        if bridge is not None:
            bridge.start()
        dashboard.run()
    except RuntimeError as err:
        print(f"\n[!] Dashboard Error: {err}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        if bridge is not None:
            bridge.stop()
        if ring_buffer is not None:
            ring_buffer.close()


if __name__ == "__main__":
    main()
