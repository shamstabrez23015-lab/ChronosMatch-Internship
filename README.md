# ChronosMatch: Zero-Copy High-Frequency Trading Engine (Week 1)

> **FinTech & Low-Latency Systems**: Zero-serialization, memory-mapped IPC ring buffer & high-throughput market firehose.

---

## 📌 Project Overview

In High-Frequency Trading (HFT) and quantitative market making, microsecond latencies directly dictate execution quality and risk. Traditional Python implementations face three primary architectural bottlenecks:
- **Garbage Collection (GC) Jitter**: Stop-the-world GC cycles introduce unpredictable latency spikes.
- **Serialization Bottlenecks**: Passing data across processes via JSON, Pickle, or Protocol Buffers incurs CPU overhead from encoding and decoding.
- **Global Interpreter Lock (GIL)**: A single Python process cannot execute CPU-bound work concurrently across multiple threads.

**ChronosMatch** resolves these issues using a **Zero-Copy Memory-Mapped Ring Buffer** for Inter-Process Communication (IPC). Built with Python's standard `mmap`, `memoryview`, and fixed-size binary structures (`struct`), ChronosMatch streams raw order data across independent processes with zero serialization overhead and zero object allocation in the hot loop.

> [!IMPORTANT]
> **Implementation Scope (Week 1 Only)**
> This repository contains only the **Week 1 implementation**:
> - ✅ **Implemented**: Zero-Copy SPSC `mmap` Ring Buffer, 32-Byte Packed Binary Order Protocol (`<QQdIHBB`), `asyncio` Market Firehose Generator, Zero-Copy Consumer, Unit Test Suite, and IPC Benchmark Suite.
> - ❌ **Not Implemented Yet**: The **Cython matching engine** (Limit Order Book matching algorithm) and the **Curses dashboard** (terminal DOM/L2 visualizer) are scheduled for subsequent phases and are **not yet implemented**.

---

## 🏗️ Week 1 Architecture

The Week 1 system architecture separates the market feed generator (Producer) and the reader (Consumer) into isolated operating system processes communicating solely through a shared memory-mapped binary file.

```
┌────────────────────────────────────────────────────────┐
│             PRODUCER PROCESS (Python / Asyncio)        │
│  FastOrderGenerator                                   │
│    └─► Pre-allocated randomized pool (4,096 entries)  │
│  MarketFirehose                                        │
│    └─► Micro-burst pacing loop (time.perf_counter)     │
│    └─► Zero-copy struct.pack_into via memoryview      │
└──────────────────────────┬─────────────────────────────┘
                           │ Direct Byte Writes (Zero-Copy)
                           ▼
┌────────────────────────────────────────────────────────┐
│            SHARED MEMORY-MAPPED FILE (mmap)            │
│  File: data/chronos_ring.bin (Default: 524,288 slots)  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 4 KB HEADER PAGE                                 │  │
│  │  Offset   0: b"CHRONOS1" Magic | Ver | Slot Size │  │
│  │  Offset  64: write_head (Cache Line 1)           │  │
│  │  Offset 128: read_tail  (Cache Line 2)           │  │
│  │  Offset 192: Atomic Metrics (Written/Read/Drops) │  │
│  ├──────────────────────────────────────────────────┤  │
│  │ SLOTS DATA SEGMENT (Starts at Offset 4096)       │  │
│  │  [Slot 0: 32B] [Slot 1: 32B] ... [Slot N-1: 32B] │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────┬─────────────────────────────┘
                           │ Direct Byte Reads (Zero-Copy)
                           ▼
┌────────────────────────────────────────────────────────┐
│             CONSUMER PROCESS (Zero-Copy Reader)        │
│  ZeroCopyConsumer                                      │
│    └─► Batch reads raw tuples (struct.unpack_from)     │
│    └─► Microsecond latency tracking (time.time_ns)     │
│    └─► Entry point for future Cython Order Book        │
└────────────────────────────────────────────────────────┘
```

### Architectural Properties
- **Process Isolation**: Producer and consumer execute as distinct operating system processes, eliminating Python GIL contention.
- **Cache-Line Isolated Pointers**: `write_head` and `read_tail` are placed on distinct 64-byte hardware cache lines to prevent CPU false sharing.
- **Power-of-2 Slot Masking**: Ring buffer capacity is strictly a power of 2, allowing sequence mapping via bitwise AND (`seq & (capacity - 1)`) rather than integer division.

---

## 💾 Memory-Mapped (`mmap`) Ring Buffer

The shared IPC ring buffer is implemented in [chronos/ring_buffer.py](file:///c:/Users/shams/OneDrive/Desktop/ChronosMatch%20Zero-Copy%20High-Frequency%20Trading/chronos/ring_buffer.py) by the `MmapRingBuffer` class.

### 1. Header Page Layout (4,096 Bytes)
The buffer reserves a 4,096-byte header so that data slots align cleanly to a 4 KB memory page boundary:

| Offset Range | Size | Field | Format | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `0 - 7` | 8 bytes | `MAGIC` | `8s` | Magic identification bytes (`b"CHRONOS1"`) |
| `8 - 11` | 4 bytes | `VERSION` | `uint32` | Header format version (`1`) |
| `12 - 15` | 4 bytes | `SLOT_SIZE` | `uint32` | Size per slot in bytes (`32`) |
| `16 - 23` | 8 bytes | `CAPACITY` | `uint64` | Total order slots ($2^k$) |
| `24 - 63` | 40 bytes| `RESERVED` | `padding` | Padding to 64-byte boundary |
| **`64 - 71`** | 8 bytes | **`WRITE_HEAD`** | `uint64` | Producer sequence position (**Cache-Line 1**) |
| `72 - 127`| 56 bytes| `PADDING` | `padding` | Separation padding (56 bytes) |
| **`128 - 135`** | 8 bytes | **`READ_TAIL`** | `uint64` | Consumer sequence position (**Cache-Line 2**) |
| `136 - 191`| 56 bytes| `PADDING` | `padding` | Separation padding (56 bytes) |
| `192 - 199`| 8 bytes | `METRICS_WRITTEN` | `uint64` | Total orders written |
| `200 - 207`| 8 bytes | `METRICS_READ` | `uint64` | Total orders read |
| `208 - 215`| 8 bytes | `METRICS_DROPPED` | `uint64` | Total orders dropped |
| `216 - 4095`| 3880 B | `PADDING` | `padding` | Header page padding up to byte 4096 |
| **`4096+`** | *N* × 32B | **`SLOTS DATA`** | Raw bytes | Memory-mapped circular slots array |

### 2. Elimination of False Sharing
When two CPU cores concurrently write to different variables residing on the same 64-byte cache line, the CPU cache coherency protocol continuously invalidates that cache line across cores (false sharing). To prevent this:
- `WRITE_HEAD` resides at byte offset `64`.
- `READ_TAIL` resides at byte offset `128`.
- The two pointers never share a cache line.

### 3. Bitwise Circular Masking
Because buffer capacity $C$ is constrained to a power of two ($C = 2^k$):
$$\text{slot\_index} = \text{sequence} \ \& \ (C - 1)$$
$$\text{byte\_offset} = 4096 + (\text{slot\_index} \times 32)$$
This replaces modulo arithmetic (`%`) with a single-cycle bitwise AND operation.

---

## 📦 Struct Binary Order Format

The binary protocol is defined in [chronos/protocol.py](file:///c:/Users/shams/OneDrive/Desktop/ChronosMatch%20Zero-Copy%20High-Frequency%20Trading/chronos/protocol.py). Every order tick is represented by a fixed **32-byte struct** using standard little-endian byte ordering (`<QQdIHBB`):

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       order_id (uint64)                       |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     timestamp_ns (uint64)                     |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         price (double)                        |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       quantity (uint32)                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         symbol_id (uint16)    |   side (uint8) |order_type(u8)|
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Field Breakdown

| Offset | Field | Format | C Type | Size | Values / Description |
| :---: | :--- | :---: | :--- | :---: | :--- |
| `0 - 7` | `order_id` | `Q` | `uint64_t` | 8 bytes | Monotonic order sequence number |
| `8 - 15` | `timestamp_ns` | `Q` | `uint64_t` | 8 bytes | Nanosecond epoch timestamp (`time.time_ns()`) |
| `16 - 23` | `price` | `d` | `double` | 8 bytes | IEEE 754 64-bit float |
| `24 - 27` | `quantity` | `I` | `uint32_t` | 4 bytes | Order share quantity |
| `28 - 29` | `symbol_id` | `H` | `uint16_t` | 2 bytes | Numerical symbol ID (`AAPL`=1001, `NVDA`=1002, etc.) |
| `30` | `side` | `B` | `uint8_t` | 1 byte | `1` = BUY (`Side.BUY`), `2` = SELL (`Side.SELL`) |
| `31` | `order_type` | `B` | `uint8_t` | 1 byte | `1` = LIMIT, `2` = MARKET, `3` = CANCEL |
| **Total** | | | | **32 bytes** | **Exact power-of-2 size (half of a 64-byte cache line)** |

### Zero-Copy Hot Path
- Serialization is performed with `ORDER_STRUCT.pack_into(buffer, offset, ...)` directly into the `memoryview` of the mapped file.
- Deserialization is performed with `ORDER_STRUCT.unpack_from(buffer, offset)` directly from memory without copying intermediate `bytes` objects.

---

## ⚡ Market Firehose (`asyncio`)

Implemented in [chronos/firehose.py](file:///c:/Users/shams/OneDrive/Desktop/ChronosMatch%20Zero-Copy%20High-Frequency%20Trading/chronos/firehose.py), the Market Firehose simulates a high-throughput order feed targeting **100,000 orders/second**.

### 1. `FastOrderGenerator`
To eliminate `random` module overhead in the hot path:
- The generator pre-allocates an in-memory pool of 4,096 randomized `(price, quantity, symbol_id, side, order_type)` tuples.
- During generation, the hot path simply indexes through this pre-generated pool, attaching the sequential `order_id` and the current `time.time_ns()` timestamp.

### 2. Drift-Free Micro-Burst Pacing
- Orders are transmitted in batches (default: 500 orders per burst).
- For a target rate of 100,000 orders/sec, each 500-order burst is dispatched every 5.0 milliseconds.
- The loop records target timestamps with `time.perf_counter()` and adjusts each sleep duration dynamically, eliminating timing drift across bursts.
- On Windows, `ctypes.windll.winmm.timeBeginPeriod(1)` is invoked to set the OS timer interrupt resolution to 1 millisecond.

---

## 💻 Producer & Consumer Commands

The producer and consumer can be executed as standalone processes in separate terminal windows using the backing file `data/chronos_ring.bin`.

### 1. Start the Consumer (Terminal 1)
```bash
python scripts/run_consumer.py --batch-size 1000
```

#### Consumer CLI Arguments
| Argument | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `--file` | `str` | `data/chronos_ring.bin` | Path to backing memory-mapped buffer file |
| `--batch-size` | `int` | `1000` | Number of orders drained per batch read |
| `--duration` | `float` | `None` | Max duration to run in seconds |
| `--total-orders` | `int` | `None` | Total orders to consume before exiting |

### 2. Start the Market Firehose Producer (Terminal 2)
```bash
python scripts/run_firehose.py --rate 100000 --batch-size 500
```

#### Producer CLI Arguments
| Argument | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `--file` | `str` | `data/chronos_ring.bin` | Path to backing memory-mapped buffer file |
| `--rate` | `int` | `100000` | Target rate in orders per second |
| `--batch-size` | `int` | `500` | Batch size per micro-burst |
| `--duration` | `float` | `None` | Duration to run in seconds |
| `--total-orders` | `int` | `None` | Total orders to send before exiting |

---

## 🧪 Pytest Suite & Test Results

The test suite validates binary struct packing, zero-copy buffer operations, batch reading/writing, and circular wrap-around semantics.

### Run Pytest
```bash
python -m pytest -v
```

### Actual Pytest Results
```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-8.4.2, pluggy-1.6.0 -- C:\Python313\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\shams\OneDrive\Desktop\ChronosMatch Zero-Copy High-Frequency Trading
plugins: anyio-4.13.0
collecting ... collected 10 items

tests/test_firehose.py::test_fast_order_generator PASSED                 [ 10%]
tests/test_firehose.py::test_firehose_throughput_blast PASSED            [ 20%]
tests/test_protocol.py::test_order_struct_size_and_alignment PASSED      [ 30%]
tests/test_protocol.py::test_order_packing_unpacking_roundtrip PASSED    [ 40%]
tests/test_protocol.py::test_zero_copy_pack_into_and_unpack_from PASSED  [ 50%]
tests/test_ring_buffer.py::test_buffer_creation_and_header PASSED        [ 60%]
tests/test_ring_buffer.py::test_single_write_and_read PASSED             [ 70%]
tests/test_ring_buffer.py::test_batch_write_and_batch_read PASSED        [ 80%]
tests/test_ring_buffer.py::test_circular_wrap_around PASSED              [ 90%]
tests/test_ring_buffer.py::test_buffer_full_and_overwrite PASSED         [100%]

============================= 10 passed in 0.36s ==============================
```

---

## 📊 Benchmark Command & Measured Results

The benchmark script [scripts/benchmark_ipc.py](file:///c:/Users/shams/OneDrive/Desktop/ChronosMatch%20Zero-Copy%20High-Frequency%20Trading/scripts/benchmark_ipc.py) launches producer and consumer worker processes via `multiprocessing`, measuring real cross-process throughput and end-to-end latency.

### Benchmark Command
```bash
python scripts/benchmark_ipc.py
```

### Actual Measured Output
```text
[PRODUCER FINISHED] Sent 300,000 orders in 2.996s (100,149 orders/sec)
===========================================================================
       CHRONOSMATCH :: ZERO-COPY IPC BENCHMARK SUITE (WEEK 1)
  Target Orders : 300,000
  Target Rate   : 100,000 orders/sec
  Batch Size    : 500 orders/burst
===========================================================================

[+] Starting Zero-Copy Consumer process...
[+] Blasting Market Firehose Producer process...

===========================================================================
                     BENCHMARK RESULTS & METRICS
===========================================================================
  Total Orders Processed : 300,000
  End-to-End Elapsed     : 3.054 seconds
  Consumer Throughput    : 98,234 orders/sec
  Latency (Min)          : 388.40 us
  Latency (Mean)         : 1074.56 us
  Latency (P99)          : 2118.90 us
  Latency (Max)          : 2145.90 us
===========================================================================
```

### Measured Performance Summary

| Metric | Target Specification | Measured Result |
| :--- | :--- | :--- |
| **Producer Paced Throughput** | 100,000 orders/sec | **100,149 orders/sec** |
| **Consumer Throughput** | Real-time drain | **98,234 orders/sec** |
| **Total Orders Tested** | 300,000 | **300,000 orders** |
| **Dropped Orders** | Zero | **0 orders dropped** |
| **Latency (Min)** | Low microsecond | **388.40 μs** |
| **Latency (Mean)** | Sub-millisecond target | **1,074.56 μs** |
| **Latency (P99)** | Bound tail latency | **2,118.90 μs** |
| **Latency (Max)** | Outlier bound | **2,145.90 μs** |
| **Order Struct Size** | 32 bytes | **32 bytes** |

---

## 🎯 Achieved Throughput: 100,000 Orders/Sec

The system achieves the Week 1 milestone:
- **Producer Generation & Pacing**: Sustained **100,149 orders/sec** across a 300,000-order run (2.996 seconds).
- **Zero-Copy IPC Ingestion**: The consumer drained orders at **98,234 orders/sec** with zero packet loss (**0 dropped orders**).

---

## ⚠️ Current Limitations

1. **Single Producer Single Consumer (SPSC) Only**:
   - The ring buffer synchronization relies on non-atomic integer writes to `write_head` and `read_tail`. It supports exactly one producer process and one consumer process. Supporting multiple producers would require atomic Compare-And-Swap (CAS) instructions or spinlocks.
2. **Pure Python Consumer Overhead**:
   - The reader currently unpacks orders using Python's `struct.unpack_from`. Object instantiation in Python space limits consumer drain speed compared to compiled C routines.
3. **OS Timer Granularity**:
   - Even with Windows 1ms timer resolution (`timeBeginPeriod(1)`), sub-millisecond sleeps rely on micro-burst batching rather than continuous single-tick scheduling.
4. **File-Backed mmap**:
   - The shared memory file is backed by a disk path. While the OS keeps active pages in the page cache, latency spikes can occur during OS background page writeback unless hosted on a RAM disk (`/dev/shm` or tmpfs).
5. **No Matching Engine / Dashboard in Week 1**:
   - Limit order book matching and live terminal UI visualization are not yet implemented.

---

## Week 2 Integration Plan

### Week 1 Completion Status
Week 1 is already completed and tested at approximately 100,000 mock orders per second (benchmarked at ~100,149 orders/sec producer rate and ~98,234 orders/sec consumer drain with zero dropped orders across 300,000 orders).

### Scope of Week 2
Week 2 consists of:
1. **Cython Limit Order Book using Price-Time Priority**: A high-performance, compiled order matching engine implementing Price-Time Priority (FIFO) matching semantics for limit, market, and cancellation orders with direct pointer access to avoid Python object allocation.
2. **Curses real-time latency/order-book dashboard**: A terminal-based real-time dashboard visualizing Depth of Market (Level 2 order book) alongside live system latency distributions and throughput metrics.

### Expected Connection & Dataflow
The expected connection across the pipeline is:
`Week 1 mmap consumer → Cython matching engine → dashboard metrics`

```
┌───────────────────────────────┐
│     Week 1 mmap Consumer      │   Drains 32-byte binary order structs zero-copy from ring buffer
└───────────────┬───────────────┘
                │ Direct in-memory order stream
                ▼
┌───────────────────────────────┐
│    Cython Matching Engine     │   Maintains Price-Time Priority LOB (Bids/Asks, Matches, Cancels)
└───────────────┬───────────────┘
                │ Live book state & performance telemetry
                ▼
┌───────────────────────────────┐
│       Dashboard Metrics       │   Curses terminal UI (Real-time DOM, latency percentiles, rates)
└───────────────────────────────┘
```

- **Ingestion**: The Week 1 `mmap` consumer reads 32-byte binary packed orders directly from shared memory.
- **Matching**: Orders are passed directly to the Cython Limit Order Book matching engine for execution and book updates using Price-Time Priority.
- **Metrics Emission**: The matching engine continuously aggregates and emits live book state and telemetry to the Curses dashboard.

### Information Exposed to the Dashboard
The Cython matching engine exposes the following real-time market data and telemetry to the Curses dashboard:
- **Best Bid**: Top-of-book highest buy price and aggregate quantity at that price level.
- **Best Ask**: Top-of-book lowest sell price and aggregate quantity at that price level.
- **Spread**: Difference between the best ask and best bid (`best_ask - best_bid`).
- **Total Processed Orders**: Cumulative count of orders ingested and processed (matched or placed on the book).
- **Throughput**: Real-time order processing rate expressed in orders per second.
- **Latency Measurements**: Microsecond-level latency tracking across the pipeline, including minimum, mean, P99 percentile, and maximum latency.

---

## 🔮 Roadmap: Upcoming Implementations

- [ ] **Week 2**: **Cython Matching Engine & Curses Dashboard**
  - Implement price-time priority Limit Order Book (LOB) in Cython/C.
  - Terminal-based real-time DOM (Depth of Market) Level 2 book viewer with live latency/throughput metrics.
- [ ] **Week 3**: **Multi-Symbol & Lock-Free Multi-Producer Extensions**
  - Multi-symbol routing and advanced lock-free concurrency structures.

