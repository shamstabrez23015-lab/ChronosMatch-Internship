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


def main() -> None:
    """Entry point for running the ChronosMatch curses terminal dashboard."""
    parser = argparse.ArgumentParser(
        description="ChronosMatch Terminal Dashboard - Low-latency curses monitor"
    )
    parser.add_argument(
        "--refresh-ms",
        type=int,
        default=100,
        help="Dashboard refresh interval in milliseconds (default: 100ms)",
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
        help="Print dashboard frame to stdout without curses (useful for headless/CI environments)",
    )
    args = parser.parse_args()

    config = DashboardConfig(
        refresh_interval_ms=args.refresh_ms,
        trade_latency_unit=args.trade_latency_unit,
        whale_min_levels=args.whale_threshold,
    )
    dashboard = TerminalDashboard(
        config=config,
        trade_latency_unit=args.trade_latency_unit,
    )

    if args.non_interactive:
        for line in dashboard.get_display_lines(rows=40, cols=100):
            print(line)
        return

    try:
        dashboard.run()
    except RuntimeError as err:
        print(f"\n[!] Dashboard Error: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
