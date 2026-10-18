# ChronosMatch — Week 2 System Integration Architecture

## 1. Project Overview

### High-Frequency Trading & Low-Latency Processing
In high-frequency trading (HFT) and quantitative market making, execution priority is strictly determined by arrival latency. Orders that reach an exchange or matching venue microseconds—or nanoseconds—ahead of competitors secure fills at favorable price levels, whereas slower participants suffer adverse selection. 

Building a low-latency trading engine in Python introduces three core bottlenecks:
1. **Garbage Collection (GC) Jitter**: Stop-the-world GC sweeps introduce non-deterministic microsecond-to-millisecond latency spikes.
2. **Serialization Overhead**: Inter-process communication (IPC) through traditional formats (JSON, Pickle, Protocol Buffers) forces intensive CPU serialization, heap allocation, and memory copying.
3. **Global Interpreter Lock (GIL)**: A single Python process cannot execute CPU-bound order matching, market feed generation, and visual monitoring concurrently across multi-core systems.

### ChronosMatch Architecture
**ChronosMatch** addresses these challenges by separating pipeline concerns into dedicated operating system processes communicating over a **Zero-Copy Memory-Mapped Ring Buffer**:
* **Market Firehose (Producer)**: Generates and streams synthetic order ticks at high rates.
* **Shared Memory Ring Buffer**: SPSC lock-free shared ring buffer backed by an OS-managed memory-mapped file (`mmap`), providing zero-copy byte serialization directly to RAM.
* **Matching Engine (Consumer & Core)**: A high-performance compiled Cython Limit Order Book (LOB) executing orders with C-level efficiency.
* **Terminal Dashboard (UI & Telemetry)**: A non-blocking curses dashboard visualizing real-time Depth of Market (L2 book), spreads, throughput, and latency distributions.

```
+-----------------------------------------------------------------------------------+
|                                ChronosMatch System                                |
|                                                                                   |
|  +-------------------+        +--------------------+        +------------------+  |
|  |  Market Firehose  | -----> | Mmap Ring Buffer   | -----> | Matching Engine  |  |
|  |  (Producer)       | Direct | (32B Binary Slots) | Direct | (Cython LOB)     |  |
|  +-------------------+ Memory +--------------------+ Memory +--------+---------+  |
|                                                                       | Telemetry |
|                                                                       v Snapshot  |
|                                                             +------------------+  |
|                                                             | Curses Dashboard |  |
|                                                             | (Terminal UI)    |  |
|                                                             +------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 2. Existing Week 1 Architecture

The Week 1 foundation (developed by Faizan) establishes the inter-process communication backbone and binary order protocol.

```
PRODUCER PROCESS                                           CONSUMER PROCESS
+-----------------------------------------+                +-----------------------------------------+
| chronos/firehose.py                     |                | chronos/consumer.py                     |
|                                         |                |                                         |
| FastOrderGenerator                      |                | ZeroCopyConsumer                        |
|   - Pre-allocated 4,096 param pool      |                |   - Drains raw tuples via unpack_from   |
|   - AAPL, NVDA, TSLA, MSFT, AMZN, etc.  |                |   - Tracks min, max, avg, p99 latency   |
|                                         |                |   - Baseline consumer loop              |
| MarketFirehose                          |                +--------------------+--------------------+
|   - Drift-free rate pacing (100k ord/s) |                                     ^
|   - Micro-burst batching (500 ord/burst)|                                     |
|   - struct.pack_into via memoryview     |                                     | Direct Byte Reads
+--------------------+--------------------+                                     |
                     | Direct Byte Writes                                       |
                     v                                                          |
+--------------------+----------------------------------------------------------+--------------------+
| chronos/ring_buffer.py : MmapRingBuffer (Backing file: data/chronos_ring.bin)                      |
|                                                                                                    |
| 4 KB PAGE-ALIGNED HEADER                                                                           |
| [0..7]: MAGIC b"CHRONOS1" | [8..11]: VERSION (1) | [12..15]: SLOT_SIZE (32) | [16..23]: CAPACITY   |
| [64..71]: WRITE_HEAD (Cache Line 1)              | [128..135]: READ_TAIL (Cache Line 2)            |
| [192..215]: METRICS (written: 192, read: 200, dropped: 208)                                       |
|                                                                                                    |
| CIRCULAR SLOTS DATA SEGMENT (Starts at byte offset 4096)                                           |
| Slot 0 (32B) | Slot 1 (32B) | Slot 2 (32B) | ... | Slot N-1 (32B)                                  |
+----------------------------------------------------------------------------------------------------+
```

### Components Summary

1. **Binary Order Protocol (`chronos/protocol.py`)**:
   * Uses Python's standard `struct` module configured with format string `<QQdIHBB` (32 bytes total).
   * Cache-aligned to 32 bytes (half of a standard 64-byte CPU cache line, power-of-2 aligned).
   * Fields: `order_id` (uint64), `timestamp_ns` (uint64), `price` (double), `quantity` (uint32), `symbol_id` (uint16), `side` (uint8: 1=BUY, 2=SELL), `order_type` (uint8: 1=LIMIT, 2=MARKET, 3=CANCEL).
   * Zero-copy helpers: `pack_order_into(buffer, offset, ...)` and `unpack_order_raw(buffer, offset)` directly operate on memory buffers without allocating intermediate Python objects.

2. **Zero-Copy SPSC Memory-Mapped Ring Buffer (`chronos/ring_buffer.py`)**:
   * Implements a Single Producer Single Consumer (SPSC) circular queue over `mmap` and `memoryview`.
   * **Cache-Line Separation**: `WRITE_HEAD` (offset 64) and `READ_TAIL` (offset 128) reside on separate 64-byte hardware cache lines to prevent CPU false sharing between cores.
   * **Power-of-2 Masking**: Slot indexing uses bitwise AND (`head & (capacity - 1)`) instead of integer modulo arithmetic.
   * **Page Alignment**: Order slots start at byte offset 4,096, aligning with OS virtual memory pages.

3. **Market Firehose Generator (`chronos/firehose.py`)**:
   * `FastOrderGenerator`: Pre-allocates a randomized pool of 4,096 order configurations (price offsets, quantities, sides, symbol IDs) to bypass Python runtime RNG overhead in the hot loop.
   * `MarketFirehose`: Asyncio producer delivering micro-bursts of orders with drift-free timing (`time.perf_counter()` + spin-wait pacing).

4. **Zero-Copy Consumer (`chronos/consumer.py`)**:
   * Batches raw order tuples directly from the shared buffer (`read_batch_raw`).
   * Measures transit latency by calculating `(now_ns - order.timestamp_ns) / 1000.0` in microseconds.

---

## 3. Week 2 Cython Matching Engine

The matching engine foundation and Limit Order Book (LOB) data structures are implemented in `chronos/matching_engine.pyx` (developed by Albert).

### Current Cython Architecture

```
+-----------------------------------------------------------------------+
| chronos/matching_engine.pyx                                           |
|                                                                       |
|  COrder (Cython Extension Type)                                       |
|    - order_id     : unsigned long long (uint64)                       |
|    - side         : int (1 = BUY, 2 = SELL)                           |
|    - price_cents  : long long (Integer ticks: round(price * 100))      |
|    - quantity     : unsigned int (uint32)                             |
|    - timestamp_ns : unsigned long long (uint64)                       |
|    - sequence_num : unsigned long long (Monotonic arrival order)       |
|                                                                       |
|  MatchingEngine / OrderBook (Cython Extension Type)                   |
|    - _ready            : bint                                         |
|    - _order_count      : unsigned long long                           |
|    - _sequence_counter : unsigned long long                           |
|    - _bids             : list (stores BUY COrder instances)           |
|    - _asks             : list (stores SELL COrder instances)          |
+-----------------------------------------------------------------------+
```

### Price Representation: Fixed-Point Cents
The binary protocol transmits prices as 64-bit IEEE 754 floating-point numbers (`double`). Comparing floats in financial matching engines causes rounding inaccuracies. The Cython engine converts floating-point dollar prices to integer cent ticks:
```cython
cpdef long long price_to_cents(double price):
    return <long long>round(price * 100.0)
```
All internal book operations and comparisons use `price_cents` (e.g., `$225.50` -> `22550`).

### BUY and SELL Order Storage
The `MatchingEngine` class segregates incoming orders:
* `_bids`: Internal list storing BUY orders.
* `_asks`: Internal list storing SELL orders.
* `_sequence_counter`: Monotonically incremented counter assigned to each accepted order (`sequence_num`), preserving arrival order.
* APIs provided:
  * Ingestion: `submit_order(order_id, side, price, quantity, timestamp_ns)`, `add_buy_order(...)`, `add_sell_order(...)`, `add_order(...)`.
  * Inspection: `get_bids()`, `get_asks()`, `get_buy_orders()`, `get_sell_orders()`, property `bids`, property `asks`.
  * Metrics: `bid_count()`, `ask_count()`, `order_count()`, `status()`.
  * Lifecycle: `clear()`, `reset()`, `init_order_book()`.
  * Validation: Rejects invalid sides (`side not in (1, 2)`), non-positive prices (`price <= 0`), and zero quantities (`quantity == 0`).

### Price-Time Priority Matching Algorithm (Planned vs Implemented)

| Feature | Status | Implementation Details |
| :--- | :--- | :--- |
| **`COrder` C Struct** | **Implemented** | Statically typed fields: ID, side, price_cents, quantity, timestamp, sequence_num. |
| **Fixed-Point Conversion** | **Implemented** | `price_to_cents` converts float prices to integer cents. |
| **Bids / Asks Separation** | **Implemented** | Separate `_bids` and `_asks` lists. |
| **Input Validation** | **Implemented** | Raises `ValueError` on invalid side, non-positive price, or zero quantity. |
| **Sequence Numbering** | **Implemented** | Monotonic counter tracking exact order arrival sequence. |
| **Price-Time Priority Sorting** | *Planned (Day 4)* | Bids must be sorted descending by price (highest bid first); Asks sorted ascending (lowest ask first). Secondary sort by `sequence_num` / timestamp. Currently stored in insertion order. |
| **Trade Execution / Matching** | *Planned (Day 4)* | Crossing logic: Match if `buy_price >= best_ask` or `sell_price <= best_bid`. Deduct quantity for partial fills, remove resting orders on complete fills. |
| **Order Cancellation** | *Planned (Day 5)* | Locate and remove resting orders matching `order_id` when `order_type == CANCEL`. |
| **Multi-Symbol Support** | *Planned (Week 3)* | `COrder` currently lacks `symbol_id`. Order book must either track symbol per book or map symbol IDs to separate `MatchingEngine` instances. |

---

## 4. Week 2 Terminal Dashboard

The real-time latency and order book dashboard is implemented in `chronos/dashboard.py` (developed by Taniya).

### Dashboard Architecture
* Built with Python's standard `curses` library (supporting `windows-curses` on Windows).
* Pure layout helpers decoupled from curses window objects to allow headless execution and complete unit testing without a TTY.
* Non-interactive CLI mode (`python scripts/run_dashboard.py --non-interactive`) prints a static snapshot directly to stdout.

### Layout Sections

```
========================================================================
  CHRONOSMATCH
  Zero-Copy High-Frequency Trading Engine
  [Dashboard Initialized]
========================================================================

  MARKET SUMMARY
------------------------------------------------------------------------
  Best Bid                                                         --
  Best Ask                                                         --
  Bid-Ask Spread                                                   --
------------------------------------------------------------------------

  ORDER BOOK
------------------------------------------------------------------------
  BUY ORDERS (BIDS)                   SELL ORDERS (ASKS)
     Price     Qty                     Price     Qty
        --      --                          --      --
        --      --                          --      --
        --      --                          --      --
------------------------------------------------------------------------

  PERFORMANCE METRICS
------------------------------------------------------------------------
  Total Orders Processed                                           --
  Throughput (orders/sec)                                          --
  Latency (microseconds)                                           --
------------------------------------------------------------------------

  Press Q to Quit
========================================================================
```

1. **Header**: Application title, subtitle, and engine status message.
2. **Market Summary**: Best Bid price, Best Ask price, and computed Bid-Ask Spread (`best_ask - best_bid`).
3. **Order Book**: Side-by-side Depth of Market (Level 2) displaying bid price/quantity on the left and ask price/quantity on the right.
4. **Performance Metrics**: Cumulative orders processed, real-time throughput (orders/sec), and pipeline latency (μs).
5. **Footer**: Quit prompt (`Press Q to Quit`).

### Live Integrations vs Placeholders

| Section | Display Field | Current State | Planned Week 2 Integration |
| :--- | :--- | :--- | :--- |
| **Market Summary** | Best Bid | Placeholder (`"--"`) | Top bid price from `MatchingEngine` (`_bids[0].price`). |
| **Market Summary** | Best Ask | Placeholder (`"--"`) | Top ask price from `MatchingEngine` (`_asks[0].price`). |
| **Market Summary** | Spread | Placeholder (`"--"`) | Difference: `best_ask - best_bid`. |
| **Order Book** | Depth Rows | 3 Placeholder rows | Top 5-10 aggregated price levels from bids and asks. |
| **Performance** | Total Orders | Placeholder (`"--"`) | `MatchingEngine.order_count()` or `ConsumerStats.total_orders_read`. |
| **Performance** | Throughput | Placeholder (`"--"`) | Orders ingested per second over a sliding 500ms window. |
| **Performance** | Latency | Placeholder (`"--"`) | Microsecond latency: Mean and P99 percentiles from consumer timing. |

---

## 5. Complete System Data Flow

```
+-------------------------------------------------------------------+
| 1. Fake Order Generator (FastOrderGenerator)                     |
|    Generates synthetic orders (symbol, price, qty, side, type)    |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 2. Binary Order Protocol (chronos.protocol)                       |
|    Encodes parameters into 32-byte struct format (<QQdIHBB)       |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 3. Memory-Mapped Ring Buffer (chronos.ring_buffer)                |
|    Direct zero-copy write into RAM page via pack_order_into       |
|    Single Producer Single Consumer (SPSC) lock-free queue         |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 4. Consumer / Integration Adapter (ZeroCopyConsumer / Adapter)   |
|    Drains batches of 32-byte slots via unpack_order_raw           |
|    Calculates transit latency: (now_ns - timestamp_ns) / 1000.0   |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 5. Cython Matching Engine (chronos.matching_engine)               |
|    Converts double price -> integer cents (price_to_cents)        |
|    Validates order, assigns monotonic sequence_num                |
|    Price-Time Priority matching against resting book (Planned)    |
|    Maintains active bids and asks collections                     |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 6. Telemetry & State Snapshot Buffer                             |
|    Extracts top-of-book (best bid, best ask, spread),             |
|    order book depth, throughput rates, and latency metrics        |
+---------------------------------+---------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 7. Terminal Dashboard (chronos.dashboard)                         |
|    Refreshes curses display at configured interval (e.g., 100ms)  |
|    Renders Market Summary, L2 Order Book, and Performance Metrics |
+-------------------------------------------------------------------+
```

---

## 6. Module Responsibilities & Implementation Status

| Module File | Component | Primary Responsibility | Current Implementation Status |
| :--- | :--- | :--- | :--- |
| `chronos/protocol.py` | Binary Protocol | 32-byte binary struct definition, symbol mappings, `pack_order_into`, `unpack_order_raw`. | **Completed (Week 1)**: Fully functional and verified with unit tests. |
| `chronos/ring_buffer.py` | Ring Buffer | SPSC memory-mapped ring buffer with cache-line separated head/tail and page alignment. | **Completed (Week 1)**: Fully functional and verified with unit tests. |
| `chronos/firehose.py` | Market Firehose | High-throughput order generator and asyncio producer stream. | **Completed (Week 1)**: Fully functional and verified with unit tests. |
| `chronos/consumer.py` | IPC Consumer | Shared memory reader draining order batches and tracking transit latency. | **Completed (Week 1)**: Fully functional and verified with IPC benchmarks. |
| `chronos/matching_engine.pyx` | Cython Engine | C-level order representation (`COrder`), price conversion, bid/ask order storage, price-time priority matching, multi-order execution (`match_order`). | **Completed (Week 2, Days 2–6)**: Core LOB storage, price-time priority, partial fills, and multi-order sweep matching implemented and verified. |
| `chronos/dashboard.py` | Curses Dashboard | Terminal monitoring UI, layout helper functions, color themes, resize handling. | **Partially Implemented (Week 2, Day 2)**: Visual layout complete with placeholder values. Live telemetry ingestion is planned. |
| `scripts/run_firehose.py` | Producer CLI | CLI runner to configure and launch the firehose stream. | **Completed (Week 1)** |
| `scripts/run_consumer.py` | Consumer CLI | CLI runner to attach to ring buffer and measure consumer throughput. | **Completed (Week 1)** |
| `scripts/run_dashboard.py` | Dashboard CLI | CLI launcher supporting interactive curses mode and headless `--non-interactive` mode. | **Completed (Week 2, Day 2)** |
| `scripts/benchmark_ipc.py` | Benchmark Suite | Multi-process end-to-end benchmark measuring true IPC throughput and latency. | **Completed (Week 1)** |
| `chronos/adapter.py` | Pipeline Adapter | `OrderAdapter` bridges binary protocol / ring buffer stream to `MatchingEngine`, routes by symbol, and tracks execution metrics. | **Completed (Week 2, Day 7)**: Implemented and verified via end-to-end integration test suite. |

---

## 7. Integration Interfaces & Data Structures

### 1. Week 1 Binary Protocol -> Consumer Interface
In `chronos/protocol.py`:
```python
ORDER_STRUCT_FORMAT = "<QQdIHBB"
# Byte size: exactly 32 bytes
```
Unpacking from shared memory:
```python
def unpack_order_raw(buffer: memoryview | bytes | bytearray, offset: int = 0) -> Tuple[int, int, float, int, int, int, int]:
    # Returns: (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type)
    return ORDER_STRUCT.unpack_from(buffer, offset)
```
In `chronos/ring_buffer.py`:
```python
def read_batch_raw(self, max_items: int = 1000) -> List[Tuple[int, int, float, int, int, int, int]]:
    # Drains up to max_items tuples directly from mmap memoryview
```

### 2. Consumer -> Cython Matching Engine Interface
In `chronos/matching_engine.pyx`:
```cython
cdef class MatchingEngine:
    cpdef COrder submit_order(
        self,
        unsigned long long order_id,
        int side,
        double price,
        unsigned int quantity,
        unsigned long long timestamp_ns,
    )
```

#### Identified Interface Gaps
1. **Missing Fields in `COrder` / `submit_order`**:
   * The binary protocol produces a 7-tuple: `(order_id, timestamp_ns, price, quantity, symbol_id, side, order_type)`.
   * `MatchingEngine.submit_order` accepts 5 parameters: `(order_id, side, price, quantity, timestamp_ns)`.
   * `symbol_id` and `order_type` are currently omitted from `COrder`. To handle cancellations (`order_type == 3`) and market orders (`order_type == 2`), `submit_order` must be extended or an adapter must route cancellations appropriately.
2. **Object Conversion Overhead**:
   * The ring buffer unpacks raw Python tuples (`Tuple[int, int, float, int, int, int, int]`). Passing these tuples into `submit_order` involves Python object handling.
   * Future optimization: Provide a C-level buffer intake method (`submit_raw_batch`) accepting a memory buffer pointer directly inside Cython to maintain zero-copy efficiency.

### 3. Matching Engine -> Dashboard Interface
In `chronos/dashboard.py`:
```python
def build_market_summary_lines(width: int, best_bid: str = "--", best_ask: str = "--", spread: str = "--") -> List[str]
def build_order_book_lines(width: int, bid_rows: Optional[List[Tuple[str, str]]] = None, ask_rows: Optional[List[Tuple[str, str]]] = None, num_placeholder_rows: int = 3) -> List[str]
def build_performance_lines(width: int, total_orders: str = "--", throughput: str = "--", latency: str = "--") -> List[str]
```

#### Identified Interface Gaps
* The layout functions expect formatted strings (e.g., `"$225.50"`, `"100"`).
* The `MatchingEngine` currently exposes raw order lists via `get_bids()` and `get_asks()`.
* **Required Adapter**: A snapshot utility must extract:
  * Best bid: `engine.get_bids()[0].price` (once sorted).
  * Best ask: `engine.get_asks()[0].price` (once sorted).
  * Spread: `best_ask - best_bid`.
  * Top N depth levels formatted as `(price_str, qty_str)`.
  * Total orders: `engine.order_count()`.
  * Throughput and latency from the consumer statistics.

### Direct Shared Memory vs Process Boundaries

```
+-------------------+                          +--------------------+
|  PRODUCER PROCESS |                          |  CONSUMER PROCESS  |
|                   |                          |                    |
|  MarketFirehose   |                          |  Matching Engine   |
+---------+---------+                          +---------^----------+
          |                                              |
          | pack_order_into (Direct RAM write)           | unpack_order_raw
          v                                              | (In-process C calls)
+--------------------------------------------------------+----------+
|            SHARED MEMORY (OS Memory-Mapped File)                  |
|  - Zero-copy lock-free ring buffer                                |
|  - No socket, no IPC pipes, no serialization formatting          |
+-------------------------------------------------------------------+
          |
          | In-Process Decoupled Snapshot (Thread/Queue)
          v
+-------------------+
| TerminalDashboard |
| (10 - 100 Hz UI)  |
+-------------------+
```

* **Shared Memory Boundary**: Producer and consumer run in separate operating system processes. Communication occurs exclusively via raw bytes in the memory-mapped file (`mmap`). No serialization, sockets, or pipes are used.
* **Engine-to-Dashboard Boundary**: The matching engine executes in a high-frequency loop (100k+ orders/sec). In contrast, the terminal curses UI refreshes at human visual rates (10–100 ms). Rendering directly in the matching loop would severely degrade engine throughput. A decoupled snapshot mechanism (atomic state reference or thread-safe queue) is required to bridge the engine and dashboard.

---

## 8. Shared Project Configuration (Week 2 — Day 4)

To support seamless end-to-end integration across decoupled sub-processes, ChronosMatch introduces a centralized configuration module in `chronos/config.py`.

### Purpose & Architecture
Previously, operational parameters (buffer capacities, batch chunk sizes, order generation rates, refresh frequencies) were independently declared as defaults in individual constructors and CLI argument parsers. The shared configuration module unifies these values into a single source of truth without altering existing runtime defaults or disrupting working components.

Key architectural features:
1. **Canonical Constants**: Named project-wide constants matching existing component defaults.
2. **`ChronosConfig` Dataclass**: A lightweight configuration container holding all shared parameters, supporting dictionary export/import (`to_dict()`, `from_dict()`), deep copying (`copy()`), and independent instantiation across processes.
3. **Strict Validation Helpers**: Dedicated validation helpers (`validate_buffer_capacity`, `validate_batch_size`, `validate_refresh_interval_ms`, `validate_target_rate`, etc.) enforcing:
   * Strictly positive values (`> 0`) for capacities, batch sizes, rates, and intervals.
   * Type rejection (disallowing booleans, non-integers, strings, and `None`).
   * Optional power-of-two enforcement for ring buffer sizing (`is_power_of_two`).
   * Automatic execution upon dataclass initialization via `__post_init__` and on-demand via `.validate()`.

### Configuration Settings & Integration Status

| Setting | Type | Canonical Default | Currently In Use By | Prepared For Future Integration |
| :--- | :--- | :--- | :--- | :--- |
| `buffer_capacity` | `int` | `262_144` (2^18 slots) | `MmapRingBuffer`, `scripts/run_firehose.py` | Unified IPC buffer factory |
| `slot_size` | `int` | `32` bytes | `chronos/protocol.py` (`ORDER_SIZE`) | Dynamic binary protocol assertions |
| `buffer_path` | `str` | `"data/chronos_ring.bin"` | `scripts/run_firehose.py`, `run_consumer.py` | Centralized data directory manager |
| `producer_batch_size` | `int` | `500` orders | `MarketFirehose`, `benchmark_ipc.py` | Coordinated burst tuning |
| `target_rate` | `int` | `100_000` orders/sec | `MarketFirehose`, `benchmark_ipc.py` | Load generator pacing |
| `overwrite_on_full` | `bool` | `True` | `MarketFirehose` | Ring buffer saturation policy |
| `consumer_batch_size` | `int` | `1_000` orders | `ZeroCopyConsumer`, `benchmark_ipc.py` | Matching engine reader loop batching |
| `benchmark_orders` | `int` | `300_000` orders | `scripts/benchmark_ipc.py` | Automated stress testing harness |
| `refresh_interval_ms` | `int` | `100` ms | `chronos/dashboard.py` (`DashboardConfig`) | Live engine telemetry refresh rate |
| `min_terminal_rows` | `int` | `30` rows | `chronos/dashboard.py` (`MIN_TERMINAL_ROWS`) | Dynamic layout resizing |
| `min_terminal_cols` | `int` | `72` cols | `chronos/dashboard.py` (`MIN_TERMINAL_COLS`) | Dynamic layout resizing |

> [!NOTE]
> **Component Integration Boundary**: Running components (`firehose.py`, `consumer.py`, `dashboard.py`, `matching_engine.pyx`) currently retain their local defaults, which match the values in `chronos/config.py` identically. The new configuration module does not disrupt any existing working code and is prepared for direct injection during the upcoming Day 5 end-to-end pipeline integration.

---

## 9. Team Responsibilities

| Team Member | Role | Key Contributions & Scope |
| :--- | :--- | :--- |
| **Faizan** *(Team Leader)* | System Architecture & Foundation | * Week 1 Foundation: Binary protocol (`protocol.py`), SPSC memory-mapped ring buffer (`ring_buffer.py`), mock order generator (`firehose.py`), consumer (`consumer.py`).<br>* IPC benchmark suite (`benchmark_ipc.py`).<br>* Week 2 Day 4: Centralized project configuration module (`chronos/config.py`, `tests/test_config.py`).<br>* System integration architecture, CI configuration, pytest test suite maintenance, and repository documentation. |
| **Albert** | Matching Engine Core | * Cython matching engine foundation (`matching_engine.pyx`).<br>* `COrder` C-level data structures and integer cent price representation.<br>* BUY and SELL order-book storage (`_bids` and `_asks`).<br>* Next: Price-Time Priority matching algorithm, order fills, and cancellation handling. |
| **Taniya** | Monitoring & Dashboard | * Curses terminal dashboard (`dashboard.py`, `run_dashboard.py`).<br>* Multi-section UI: Market Summary, Order Book, Performance Metrics.<br>* Pure layout formatting functions and dimension checks.<br>* Next: Ingestion of live engine telemetry, top-of-book depth rendering, and dynamic latency percentiles. |

---

## 10. Remaining Integration Tasks

Connecting the completed Week 1 foundation with the Week 2 modules requires the following planned engineering tasks:

1. **Implement Price-Time Priority Sorting in Matching Engine (Albert)**:
   * Maintain `_bids` sorted in descending price order (`price_cents`), breaking ties with earliest `sequence_num`.
   * Maintain `_asks` sorted in ascending price order (`price_cents`), breaking ties with earliest `sequence_num`.
2. **Implement Order Matching & Execution Logic (Albert)**:
   * Evaluate incoming BUY orders against top of `_asks`; match if `buy_price >= best_ask`.
   * Evaluate incoming SELL orders against top of `_bids`; match if `sell_price <= best_bid`.
   * Deduct filled quantities; generate execution trade events.
3. **Incorporate Order Types & Symbol Routing (Albert & Faizan)**:
   * Extend `COrder` to support `symbol_id` and handle `OrderType.CANCEL` / `OrderType.MARKET`.
4. **Develop Consumer-to-Engine Integration Pipeline (Faizan)**:
   * Create an integrated worker connecting `ZeroCopyConsumer` to `MatchingEngine.submit_order`.
5. **Implement Decoupled Telemetry Snapshot Provider (Faizan & Taniya)**:
   * Build a lightweight snapshot provider that samples engine state (best bid, best ask, spread, depth, throughput, latency) without stalling the matching loop.
6. **Connect Dashboard to Live Telemetry (Taniya)**:
   * Replace `PLACEHOLDER` references in `chronos/dashboard.py` with live state supplied by the snapshot provider.
7. **End-to-End Integration Tests (Faizan)**:
   * Implement automated tests verifying end-to-end data flow: synthetic orders written to ring buffer -> consumed and matched by Cython engine -> telemetry reflected in dashboard output.

---

## 11. How to Verify Current Components

### 1. Build Cython Extension
The Cython matching engine extension must be compiled before running Cython-dependent tests or applications:
```powershell
# From repository root in activated virtual environment:
pip install -r requirements.txt
python setup.py build_ext --inplace
```
*Expected behavior*: Cython compiles `chronos/matching_engine.pyx` and generates a platform-specific binary extension (e.g., `chronos/matching_engine.cp313-win_amd64.pyd` on Windows).

### 2. Run Unit Tests
Execute the pytest suite across components:

* **Shared Configuration Tests** (Configuration & Validation):
  ```powershell
  python -m pytest tests/test_config.py -v
  ```
  *Expected behavior*: 52 passed tests validating configuration defaults, strict types, positive boundary validations, power-of-two checks, and independent dataclass instances.

* **Week 1 Foundation Tests** (Protocol, Ring Buffer, Firehose):
  ```powershell
  python -m pytest tests/test_protocol.py tests/test_ring_buffer.py tests/test_firehose.py -v
  ```
  *Expected behavior*: 10 passed tests verifying struct sizes, pack/unpack accuracy, ring buffer sequence wrapping, cache-line separation, and firehose generator logic.

* **Cython Matching Engine Tests** (requires compiled extension):
  ```powershell
  python -m pytest tests/test_matching_engine.py -v
  ```
  *Expected behavior*: 64 unit tests validating engine initialization, valid order submission, rejection of invalid sides/prices/quantities, integer cent conversion, sequence order preservation, bid/ask separation, price priority, and crossing detection.

* **Terminal Dashboard Tests** (requires `windows-curses` on Windows):
  ```powershell
  python -m pytest tests/test_dashboard.py -v
  ```
  *Expected behavior*: 45 unit tests verifying layout builders, header/summary/book/performance formatting, terminal size checking, and input handling.

* **Full Test Suite**:
  ```powershell
  python -m pytest -v
  ```
  *Expected behavior*: 171 passed unit tests covering configuration, protocol, ring buffer, firehose, matching engine, and terminal dashboard.

### 3. Run Standalone Scripts

* **Non-Interactive Dashboard Snapshot**:
  ```powershell
  python scripts/run_dashboard.py --non-interactive
  ```
  *Expected behavior*: Prints the complete formatted dashboard frame directly to stdout, including Market Summary, Order Book, and Performance Metrics with placeholders.

* **Interactive Curses Dashboard**:
  ```powershell
  python scripts/run_dashboard.py --refresh-ms 100
  ```
  *Expected behavior*: Launches full-screen interactive curses terminal UI. Press `q` or `Q` to exit.

* **Market Firehose Producer**:
  ```powershell
  python scripts/run_firehose.py --rate 100000 --batch-size 500 --duration 5
  ```
  *Expected behavior*: Creates the shared memory file (`data/chronos_ring.bin`) and streams mock orders at ~100,000 orders/sec for 5 seconds with live console telemetry.

* **Zero-Copy Consumer**:
  ```powershell
  python scripts/run_consumer.py --batch-size 1000 --duration 5
  ```
  *Expected behavior*: Attaches to the shared memory file, drains orders, and outputs read counts and transit latency metrics.

* **End-to-End Inter-Process Benchmark**:
  ```powershell
  python scripts/benchmark_ipc.py --orders 300000 --rate 100000
  ```
  *Expected behavior*: Spawns concurrent producer and consumer processes over a temporary ring buffer, reporting end-to-end elapsed time, throughput (~100,000 orders/sec), and microsecond latency statistics.

---

## 12. Day 6 Integration Test Foundation & Boundary Analysis

Working Day 6 establishes an automated integration test foundation in `tests/test_pipeline_integration.py` to systematically verify subsystem boundaries linking the Week 1 IPC pipeline and the Week 2 Cython matching engine before executing Day 7 full end-to-end order-flow testing.

### 12.1 Overview of Integration Test Suite

The integration test suite (`tests/test_pipeline_integration.py`) defines 19 executable tests grouped into six subsystem boundary classes using real components without mock objects or placeholder assertions:

| Test Boundary Class | Subsystem Scope | Test Count | Key Invariants Verified |
| :--- | :--- | :---: | :--- |
| `TestBinaryProtocolBoundary` | Binary Serialization / Struct Layout | 4 | 32-byte cache alignment (`ORDER_SIZE`), bi-directional packing/unpacking fidelity, zero-copy buffer offset packing, boundary values (uint64 order IDs, nanosecond timestamps, floating-point prices). |
| `TestRingBufferBoundary` | SPSC Shared Memory Ring Buffer | 3 | Single order write/read preservation, multi-order sequential FIFO transfer, batch write/read (`write_batch`, `read_batch_raw`, `read_batch_orders`), slot indexing and buffer capacity tracking. |
| `TestConsumerComponentBoundary` | Real Consumer Process Component | 2 | `ZeroCopyConsumer` draining real memory-mapped ring buffer, progress metrics calculation, duration-bounded and count-bounded safe loop termination. |
| `TestBinaryToEngineAdaptationBoundary` | Binary Protocol to Engine Ingestion | 4 | Mapping decoded `Order` NamedTuples and raw tuples to `MatchingEngine.submit_order`, float dollar price conversion to integer cents (`price_to_cents`), price priority sorting (`get_best_buy_order`), FIFO time priority preservation at identical prices. |
| `TestDay5ScenariosCompatibilityBoundary` | Day 5 Trading Scenarios Integration | 5 | All 10 deterministic scenarios verified for 32-byte protocol serialization, scenario transfer through ring buffer, exact-match execution (`SCENARIO_1_EXACT_MATCH`), partial-fill execution (`SCENARIO_4_PARTIAL_FILL_BUY_LARGER`), non-crossing spread preservation (`SCENARIO_3_NO_TRADE`). |
| `TestIntegratedOrderFlowPipeline` | Multi-Step Boundary Flow | 1 | Complete 4-step pipeline: Raw batch creation -> Ring buffer batch write -> Raw batch drain -> MatchingEngine ingestion -> Price priority verification -> Trade execution (`execute_partial_match`) -> Post-match book state verification. |

### 12.2 Working Integration Boundaries

The following subsystem boundaries are fully implemented, verified, and operational:

1. **Binary Protocol Boundary (`chronos/protocol.py`)**:
   - `Order.pack()` compiles exactly to 32 bytes (`<QQdIHBB`).
   - `Order.unpack(buffer)` and `unpack_order_raw(view, offset)` faithfully decode all seven fields (`order_id`, `timestamp_ns`, `price`, `quantity`, `symbol_id`, `side`, `order_type`).
   - String properties (`symbol_str`, `side_str`, `order_type_str`) correctly resolve symbol registry IDs and enumeration types.
2. **Shared Memory Ring Buffer Boundary (`chronos/ring_buffer.py`)**:
   - `MmapRingBuffer` correctly writes and reads orders in lock-free single-producer single-consumer mode.
   - Sequential writes preserve strict arrival order (FIFO queue semantics).
   - Zero-copy batch writing (`write_batch`) and reading (`read_batch_raw`) amortize CPU synchronization overhead.
   - Resource isolation via temporary files, page-aligned headers (4,096 bytes), and cache-line separation (offset 64 for write head, offset 128 for read tail) functions reliably across Windows and POSIX environments.
3. **Consumer Component Boundary (`chronos/consumer.py`)**:
   - `ZeroCopyConsumer` drains raw order tuples from `MmapRingBuffer` in configurable batch sizes.
   - Tracks real-time elapsed time, total orders processed, throughput rate, and min/max/average transit latencies.
4. **Binary Decoded Order to Matching Engine Adaptation**:
   - Real unpacked orders adapt directly into `MatchingEngine.submit_order(order_id, side, price, quantity, timestamp_ns)`.
   - Floating-point prices are safely converted into integer cent ticks via `price_to_cents()`.
   - Engine assigns monotonic `sequence_num` and segregates orders into `_bids` and `_asks`.
   - Engine price priority (`get_best_buy_order()`, `get_best_sell_order()`) and FIFO time priority operate accurately on binary-decoded orders.
5. **Day 5 Reusable Trading Scenarios Compatibility (`tests/trading_scenarios.py`)**:
   - All 10 deterministic trading scenarios serialize into valid 32-byte protocol frames.
   - Scenarios transferred through the ring buffer execute correctly in `MatchingEngine.execute_partial_match()`, yielding trade results and remaining quantities identical to Day 5 mathematical specifications.

### 12.3 Incomplete Integration Boundaries & Identified Gaps

The Day 6 integration test foundation identified the following specific architectural gaps required for full end-to-end operation:

1. **Protocol vs. Engine Field Mismatch (`symbol_id` and `order_type`)**:
   - **Current State**: The binary protocol defines 7 fields (`order_id`, `timestamp_ns`, `price`, `quantity`, `symbol_id`, `side`, `order_type`). `COrder` and `MatchingEngine.submit_order` accept only 5 parameters (`order_id`, `side`, `price`, `quantity`, `timestamp_ns`).
   - **Gap**: `symbol_id` and `order_type` are not stored in `COrder`. The matching engine currently acts as a single-symbol limit book. Ingestion of multi-ticker streams requires a multi-symbol router (mapping `symbol_id -> MatchingEngine`).
   - **Cancellation & Market Orders**: `order_type == 3` (CANCEL) and `order_type == 2` (MARKET) cannot be processed directly by `submit_order` today without dedicated dispatching logic.
2. **Missing Formal Integration Adapter Component (`chronos/adapter.py`)**:
   - **Current State**: In the Day 6 integration tests, adaptation between the ring buffer consumer and the matching engine is performed directly via Python argument mapping:
     ```python
     matching_engine.submit_order(
         order_id=raw[0],
         side=raw[5],
         price=raw[2],
         quantity=raw[3],
         timestamp_ns=raw[1],
     )
     ```
   - **Gap**: An operational adapter service is needed to continuously drain the buffer in a background worker, route orders by symbol, dispatch cancellations, and feed `MatchingEngine` instances.
3. **Decoupled Telemetry Snapshot Provider for Terminal Dashboard**:
   - **Current State**: `TerminalDashboard` (`chronos/dashboard.py`) currently renders demonstration sample data or placeholder rows.
   - **Gap**: `MatchingEngine` executes at 100k+ orders/sec and does not maintain an atomic telemetry snapshot buffer. To drive the 10–100Hz curses dashboard without slowing down the matching loop, a thread-safe snapshot provider (sampling `best_bid`, `best_ask`, `spread`, depth levels, throughput, latency) must be implemented.

### 12.4 Scheduled Next Steps

The remaining milestones for subsequent days include:
1. Continuous pipeline runner daemon (`chronos/pipeline.py` / `scripts/run_pipeline.py`).
2. Order cancellation and market order execution support inside the Cython engine (`cancel_order`).
3. Decoupled telemetry snapshot bridge connecting `MatchingEngine` to `TerminalDashboard`.

---

## 13. Day 7 Truthful End-to-End Order-Flow Integration & Adapter Verification

Working Day 7 implements a deterministic, truthful end-to-end integration test suite (`tests/test_end_to_end_order_flow.py`) and introduces the minimal pipeline integration adapter (`chronos/adapter.py`).

### 13.1 Components Genuinely Exercised

The Day 7 integration tests genuinely exercise the following real subsystem components without mock objects or placeholder assertions:

1. **Binary Order Protocol (`chronos/protocol.py`)**:
   - Cache-aligned 32-byte struct layout (`<QQdIHBB`).
   - Real parameter encoding: `order_id` (uint64), `timestamp_ns` (uint64), `price` (double), `quantity` (uint32), `symbol_id` (uint16), `side` (uint8: 1=BUY, 2=SELL), `order_type` (uint8: 1=LIMIT, 2=MARKET, 3=CANCEL).
   - Zero-copy serialization via `pack_order_into()` and deserialization via `unpack_order_raw()`.

2. **Memory-Mapped IPC Ring Buffer (`chronos/ring_buffer.py`)**:
   - Isolated `MmapRingBuffer` instances backed by temporary files.
   - Cache-line separation between write head (offset 64) and read tail (offset 128) preventing CPU false sharing.
   - Sequential write/read (`write_order`, `read_raw`, `read_batch_raw`) preserving arrival sequence.
   - Resource cleanup closing views, file descriptors, and deleting backing storage.

3. **IPC Consumer Component (`chronos/consumer.py`)**:
   - `ZeroCopyConsumer` draining batches of raw tuples directly from shared memory.
   - Microsecond latency measurement (`time.time_ns() - order.timestamp_ns`) and throughput calculation.
   - Connected via the new optional `order_handler` callback to forward drained tuples directly to the matching engine.

4. **Integration Adapter (`chronos/adapter.py`)**:
   - `OrderAdapter`: Maps the 7-parameter binary protocol (`order_id`, `timestamp_ns`, `price`, `quantity`, `symbol_id`, `side`, `order_type`) to the 5-parameter Cython `MatchingEngine` C interface (`order_id`, `side`, `price`, `quantity`, `timestamp_ns`).
   - Supports active matching mode (`match_order`) and passive submission mode (`submit_order`).
   - Provides symbol routing across multiple `MatchingEngine` instances (`symbol_engines: Dict[int, MatchingEngine]`).
   - Records comprehensive throughput, fill, and unhandled order metrics (`AdapterStats`).

5. **Cython Matching Engine (`chronos/matching_engine.pyx`)**:
   - Limit Order Book storage (`_bids` and `_asks` holding statically typed `COrder` instances).
   - Integer cent tick arithmetic (`price_to_cents`) preventing float comparison errors.
   - Continuous multi-order matching (`match_order`) adhering to strict Price-Time Priority (FIFO).
   - Exchange execution-price policy: resting maker price (lowest ask for incoming BUY, highest bid for incoming SELL).
   - Generation of immutable `TradeResult` records with exact fill quantities and post-match remaining quantities.

6. **Day 5 Deterministic Trading Scenarios (`tests/trading_scenarios.py`)**:
   - Scenarios (`SCENARIO_1_EXACT_MATCH`, `SCENARIO_3_NO_TRADE`, `SCENARIO_4_PARTIAL_FILL_BUY_LARGER`, etc.) encoded into 32-byte frames, streamed through the ring buffer, and matched to verify mathematical exactness.

---

### 13.2 The Verified Order Flow

The canonical end-to-end integration test (`TestDeterministicCrossingAndNonCrossingOrderFlow.test_deterministic_order_flow_crossing_and_non_crossing`) executes a deterministic 5-order stream through the real ring buffer into the matching engine:

```
[Order 1: SELL #101] -> Ring Buffer -> Adapter -> Engine -> Rests in Asks (100 @ $150.00)
[Order 2: BUY  #102] -> Ring Buffer -> Adapter -> Engine -> Rests in Bids (50 @ $148.00) [Non-crossing]
[Order 3: BUY  #103] -> Ring Buffer -> Adapter -> Engine -> Matches 40 @ $150.00 (SELL #101 rem: 60)
[Order 4: BUY  #104] -> Ring Buffer -> Adapter -> Engine -> Matches 60 @ $150.00 (SELL #101 cleared)
                                                            Remainder 20 rests in Bids @ $152.00
[Order 5: SELL #105] -> Ring Buffer -> Adapter -> Engine -> Rests in Asks (30 @ $155.00) [Non-crossing]
```

#### Detailed Invariants Verified:
1. **Arrival Sequence Preservation**: Orders enter the ring buffer sequentially and are processed in identical FIFO arrival order. Engine sequence counters increment monotonically (1 through 5).
2. **Deterministic Crossing Match**: Compatible BUY and SELL orders match accurately.
   - **Trade 1**: Incoming BUY #103 (40 @ $150.00) matches resting SELL #101 (100 @ $150.00). Executed quantity = 40. Execution price = $150.00 (15000 cents). BUY remaining = 0; SELL remaining = 60.
   - **Trade 2**: Incoming BUY #104 (80 @ $152.00) matches resting SELL #101 (rem 60 @ $150.00). Executed quantity = 60. Execution price = $150.00. BUY remaining = 20; SELL remaining = 0.
3. **Execution Price Policy (Maker Price)**:
   - The execution price is set by the resting maker order ($150.00), not the incoming taker price ($152.00).
4. **Partial Fill Remainder Preservation**:
   - Partially filled resting orders retain their original arrival sequence and remaining quantity.
   - After Trade 1, SELL #101 retained exactly 60 shares.
   - After Trade 2, BUY #104 retained exactly 20 shares and rested at the top of the bid book.
5. **Full Fill Book Removal**:
   - When an order's remaining quantity reaches 0, it is automatically removed from the book.
   - SELL #101 was removed from asks after Trade 2 (`ask_count() == 0`).
   - Fully matched incoming order BUY #103 never entered the resting bids book.
6. **Non-Crossing Order Safety**:
   - Non-crossing orders BUY #102 ($148.00 < $150.00) and SELL #105 ($155.00 > $152.00) rested in their respective books without spurious execution.
7. **No Order Loss or Duplication**:
   - Exactly 5 orders written to the ring buffer; exactly 5 orders read by the adapter; 0 lost, 0 duplicate executions. Ring buffer is completely empty upon test completion.

---

### 13.3 Introduced Pipeline Adapter (`chronos/adapter.py`)

To bridge the architectural gap between the 7-parameter binary protocol / IPC buffer and the 5-parameter Cython `MatchingEngine` without modifying the core matching algorithm or ring buffer internals, `chronos/adapter.py` was introduced.

```
+-----------------------------------------------------------------------------------------+
| chronos/adapter.py : OrderAdapter                                                       |
|                                                                                         |
|  Inputs:                                                                                |
|    - MmapRingBuffer (Shared Memory) or ZeroCopyConsumer batches                         |
|    - Raw 7-tuple: (order_id, timestamp_ns, price, quantity, symbol_id, side, order_type)|
|                                                                                         |
|  Responsibilities:                                                                      |
|    1. Symbol Routing: Maps symbol_id -> target MatchingEngine instance                  |
|    2. Protocol Translation: Extracts (order_id, side, price, quantity, timestamp_ns)    |
|    3. Order Type Dispatching:                                                           |
|       - LIMIT (1)  -> Dispatches to target_engine.match_order()                         |
|       - CANCEL (3) -> Records in unhandled_orders / stats.unhandled_order_types         |
|       - MARKET (2) -> Records in unhandled_orders / stats.unhandled_order_types         |
|    4. Execution Telemetry: Collects TradeResult records and tracks fill statistics      |
|    5. Bounded Drain APIs: process_next(), process_available(max_orders), drain_all()    |
+-----------------------------------------------------------------------------------------+
```

#### Key APIs:
- `OrderAdapter(ring_buffer, engine, symbol_engines, dispatch_mode="match")`
- `adapter.dispatch_raw_order(tuple_or_order) -> List[TradeResult]`
- `adapter.process_next() -> Tuple[Optional[Tuple], List[TradeResult]]`
- `adapter.process_available(max_orders=None) -> List[TradeResult]`
- `adapter.drain_all() -> List[TradeResult]`
- `adapter.run_consumer(consumer, total_orders, duration_seconds) -> AdapterStats`
- `adapter.stats -> AdapterStats` (total_orders_read, total_trades_generated, total_volume_matched, non_crossing_orders, unhandled_order_types, unrouted_symbols)

---

### 13.4 Truthful Assessment of Remaining Integration Gaps

While the end-to-end order flow from binary protocol through shared memory to Cython execution is fully functional and verified, the following boundaries remain intentionally disconnected or require future expansion:

1. **Order Cancellation Handling (`OrderType.CANCEL = 3`)**:
   - **Current State**: The binary protocol defines `OrderType.CANCEL`, but the Cython `MatchingEngine` currently only accepts order submissions and matches; it does not provide an `order_cancel(order_id)` API.
   - **How Handled Today**: `OrderAdapter` inspects `order_type`. If an order is a cancellation, it records `stats.unhandled_order_types += 1` and logs it to `adapter.unhandled_orders` rather than silently failing or corrupting book state.
   - **Required Future Work**: Implement `cancel_order(order_id)` inside `chronos/matching_engine.pyx` to locate and remove resting orders.

2. **Market Order Pricing Policy (`OrderType.MARKET = 2`)**:
   - **Current State**: `MatchingEngine.match_order` validates `price > 0.0`. Market orders typically submit with price 0.0 or require special execution bounds.
   - **Required Future Work**: Add market order pricing logic (sweeping opposite book regardless of price or up to depth limit).

3. **Multi-Process Pipeline Daemon (`scripts/run_pipeline.py`)**:
   - **Current State**: Producer (`scripts/run_firehose.py`) and consumer (`scripts/run_consumer.py`) run as standalone CLIs. Day 7 verifies integration via automated test processes (`tests/test_end_to_end_order_flow.py`).
   - **Required Future Work**: Build a unified daemon process coordinating background producer, consumer adapter, and matching engine threads.

4. **Terminal Dashboard Live Ingestion (`chronos/dashboard.py`)**:
   - **Current State**: `TerminalDashboard` demonstrates visual rendering using sample or mock data.
   - **Required Future Work**: Implement a thread-safe snapshot provider sampling `MatchingEngine` state (`best_bid`, `best_ask`, `spread`, depth rows) at 10–100Hz and feeding the curses UI.

---

### 13.5 How to Run the Integration Tests

To run the Day 7 end-to-end integration test suite and the full test suite:

```powershell
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Recompile Cython extension if necessary
python setup.py build_ext --inplace

# 3. Run the Day 7 End-to-End Order-Flow Integration Test Suite
python -m pytest tests/test_end_to_end_order_flow.py -v

# 4. Run the Day 6 Integration Test Foundation
python -m pytest tests/test_pipeline_integration.py -v

# 5. Run the Full Project Test Suite
python -m pytest -v
```

*Verification Results*:
- `tests/test_end_to_end_order_flow.py`: 11 passed in 0.15s.
- `tests/test_pipeline_integration.py`: 19 passed in 0.18s.
- Full Suite (`tests/`): 486 passed in 1.05s.

