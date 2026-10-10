"""CLI runner for the ChronosMatch Market Firehose."""

import argparse
import asyncio
import ctypes
import os
import sys

if sys.platform == "win32":
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chronos.firehose import MarketFirehose
from chronos.ring_buffer import MmapRingBuffer

DEFAULT_BUFFER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chronos_ring.bin")


def main():
    parser = argparse.ArgumentParser(
        description="ChronosMatch Market Firehose - 100,000 orders/sec IPC Blaster"
    )
    parser.add_argument(
        "--file",
        type=str,
        default=DEFAULT_BUFFER_PATH,
        help="Path to memory-mapped buffer file",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=100_000,
        help="Target orders per second (default: 100,000)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size per burst (default: 500)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Duration to run in seconds (default: run until Ctrl+C)",
    )
    parser.add_argument(
        "--total-orders",
        type=int,
        default=None,
        help="Total orders to send (default: unlimited)",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=262_144,
        help="Ring buffer capacity in slots if creating (default: 262,144)",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        default=True,
        help="Create and initialize the ring buffer file",
    )
    args = parser.parse_args()

    print("\033[1;35m" + "=" * 70 + "\033[0m")
    print("\033[1;37m  CHRONOSMATCH :: ZERO-COPY MARKET FIREHOSE (WEEK 1)\033[0m")
    print(f"  Buffer Path : {args.file}")
    print(f"  Target Rate : {args.rate:,} orders/sec")
    print(f"  Batch Size  : {args.batch_size} orders/burst")
    print(f"  Capacity    : {args.capacity:,} slots")
    print("\033[1;35m" + "=" * 70 + "\033[0m")

    # Initialize shared memory ring buffer
    buffer = MmapRingBuffer(args.file, capacity=args.capacity, create=args.create)
    firehose = MarketFirehose(buffer, target_rate=args.rate, batch_size=args.batch_size)

    try:
        asyncio.run(
            firehose.blast(
                duration_seconds=args.duration,
                total_orders=args.total_orders,
                print_progress=True,
            )
        )
    except KeyboardInterrupt:
        print("\n[!] Received stop signal (Ctrl+C). Terminating gracefully...")
        firehose.stop()
    finally:
        head_val = buffer.write_head
        buffer.close()
        print("\n\033[1;32m[+] Final Summary:\033[0m")
        print(f"    Total Orders Blast : {firehose.stats.total_orders_sent:,}")
        print(f"    Elapsed Time       : {firehose.stats.elapsed_time:.2f}s")
        print(f"    Average Throughput : {firehose.stats.avg_rate:,.0f} orders/sec")
        print(f"    Ring Buffer Head   : {head_val:,}")


if __name__ == "__main__":
    main()
