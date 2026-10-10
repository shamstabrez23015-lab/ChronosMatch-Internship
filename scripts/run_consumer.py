"""CLI runner for the ChronosMatch Zero-Copy Consumer."""

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

from chronos.consumer import ZeroCopyConsumer
from chronos.ring_buffer import MmapRingBuffer

DEFAULT_BUFFER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chronos_ring.bin")


def main():
    parser = argparse.ArgumentParser(
        description="ChronosMatch Zero-Copy Consumer - Reads directly from mmap ring buffer"
    )
    parser.add_argument(
        "--file",
        type=str,
        default=DEFAULT_BUFFER_PATH,
        help="Path to memory-mapped buffer file",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch read chunk size (default: 1000)",
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
        help="Total orders to read before stopping",
    )
    args = parser.parse_args()

    print("\033[1;32m" + "=" * 70 + "\033[0m")
    print("\033[1;37m  CHRONOSMATCH :: ZERO-COPY CONSUMER (WEEK 1)\033[0m")
    print(f"  Buffer Path : {args.file}")
    print(f"  Batch Read  : {args.batch_size} orders/batch")
    print("\033[1;32m" + "=" * 70 + "\033[0m")

    # Connect to existing shared memory ring buffer
    buffer = MmapRingBuffer(args.file, create=False)
    consumer = ZeroCopyConsumer(buffer, batch_size=args.batch_size)

    try:
        consumer.run(
            duration_seconds=args.duration,
            total_orders=args.total_orders,
            print_progress=True,
        )
    except KeyboardInterrupt:
        print("\n[!] Received stop signal (Ctrl+C). Exiting...")
        consumer.stop()
    finally:
        buffer.close()
        print("\n\033[1;32m[+] Consumer Final Summary:\033[0m")
        print(f"    Total Orders Read  : {consumer.stats.total_orders_read:,}")
        print(f"    Elapsed Time       : {consumer.stats.elapsed_time:.2f}s")
        print(f"    Average Throughput : {consumer.stats.avg_rate:,.0f} orders/sec")
        print(f"    Average Latency    : {consumer.stats.avg_latency_us:,.1f} us")
        print(f"    P99 Latency        : {consumer.stats.p99_latency_us:,.1f} us")


if __name__ == "__main__":
    main()
