"""End-to-End Inter-Process Benchmark for ChronosMatch Zero-Copy IPC.

Launches both the Producer (Asyncio Market Firehose) and Consumer
across separate processes sharing the same memory-mapped ring buffer.
Measures true IPC throughput (orders/sec) and end-to-end latency (μs).
"""

import argparse
import asyncio
import ctypes
import multiprocessing as mp
import os
import sys
import tempfile
import time

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

from chronos.consumer import ZeroCopyConsumer
from chronos.firehose import MarketFirehose
from chronos.ring_buffer import MmapRingBuffer


def _producer_process(filepath: str, num_orders: int, target_rate: int, batch_size: int):
    """Producer worker process."""
    # Attach to already created ring buffer
    buffer = MmapRingBuffer(filepath, create=False)
    firehose = MarketFirehose(buffer, target_rate=target_rate, batch_size=batch_size)

    # Let consumer be ready
    time.sleep(0.05)

    stats = asyncio.run(
        firehose.blast(
            total_orders=num_orders,
            print_progress=False,
        )
    )
    buffer.close()
    print(f"\n[PRODUCER FINISHED] Sent {stats.total_orders_sent:,} orders in {stats.elapsed_time:.3f}s ({stats.avg_rate:,.0f} orders/sec)")


def _consumer_process(filepath: str, num_orders: int, batch_size: int, result_queue: mp.Queue):
    """Consumer worker process."""
    buffer = MmapRingBuffer(filepath, create=False)
    consumer = ZeroCopyConsumer(buffer, batch_size=batch_size)

    stats = consumer.run(
        total_orders=num_orders,
        print_progress=False,
    )
    buffer.close()
    result_queue.put({
        "read_count": stats.total_orders_read,
        "elapsed_time": stats.elapsed_time,
        "avg_rate": stats.avg_rate,
        "min_latency_us": stats.min_latency_us,
        "avg_latency_us": stats.avg_latency_us,
        "max_latency_us": stats.max_latency_us,
        "p99_latency_us": stats.p99_latency_us,
    })


def run_benchmark(num_orders: int = 500_000, target_rate: int = 100_000, batch_size: int = 500):
    print("\033[1;36m" + "=" * 75 + "\033[0m")
    print("\033[1;37m       CHRONOSMATCH :: ZERO-COPY IPC BENCHMARK SUITE (WEEK 1)\033[0m")
    print(f"  Target Orders : {num_orders:,}")
    print(f"  Target Rate   : {target_rate:,} orders/sec")
    print(f"  Batch Size    : {batch_size} orders/burst")
    print("\033[1;36m" + "=" * 75 + "\033[0m")

    # Create temporary ring buffer file
    fd, tmp_path = tempfile.mkstemp(prefix="chronos_bench_", suffix=".bin")
    os.close(fd)

    # Capacity: round to next power of 2, e.g. 524,288 slots (16 MB)
    capacity = 524_288
    ring_buf = MmapRingBuffer(tmp_path, capacity=capacity, create=True)
    ring_buf.close()

    result_queue = mp.Queue()

    consumer_p = mp.Process(
        target=_consumer_process,
        args=(tmp_path, num_orders, 1000, result_queue),
    )
    producer_p = mp.Process(
        target=_producer_process,
        args=(tmp_path, num_orders, target_rate, batch_size),
    )

    print("\n[+] Starting Zero-Copy Consumer process...")
    consumer_p.start()

    print("[+] Blasting Market Firehose Producer process...")
    producer_p.start()

    producer_p.join()
    consumer_p.join()

    res = result_queue.get()

    print("\n" + "\033[1;32m" + "=" * 75 + "\033[0m")
    print("\033[1;32m                     BENCHMARK RESULTS & METRICS\033[0m")
    print("\033[1;32m" + "=" * 75 + "\033[0m")
    print(f"  Total Orders Processed : \033[1;37m{res['read_count']:,}\033[0m")
    print(f"  End-to-End Elapsed     : \033[1;37m{res['elapsed_time']:.3f} seconds\033[0m")
    print(f"  Consumer Throughput    : \033[1;33m{res['avg_rate']:,.0f} orders/sec\033[0m")
    print(f"  Latency (Min)          : \033[1;35m{res['min_latency_us']:.2f} us\033[0m")
    print(f"  Latency (Mean)         : \033[1;35m{res['avg_latency_us']:.2f} us\033[0m")
    print(f"  Latency (P99)          : \033[1;35m{res['p99_latency_us']:.2f} us\033[0m")
    print(f"  Latency (Max)          : \033[1;35m{res['max_latency_us']:.2f} us\033[0m")
    print("\033[1;32m" + "=" * 75 + "\033[0m")

    # Clean up file
    try:
        os.remove(tmp_path)
    except OSError:
        pass


if __name__ == "__main__":
    # Windows multiprocessing fix
    mp.freeze_support()

    parser = argparse.ArgumentParser(description="ChronosMatch IPC Benchmark")
    parser.add_argument("--orders", type=int, default=300_000, help="Number of orders to test")
    parser.add_argument("--rate", type=int, default=100_000, help="Target orders/sec")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch burst size")
    args = parser.parse_args()

    run_benchmark(num_orders=args.orders, target_rate=args.rate, batch_size=args.batch_size)
