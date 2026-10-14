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
| `chronos/matching_engine.pyx` | Cython Engine | C-level order representation (`COrder`), price conversion, bid/ask order storage, validation. | **Partially Implemented (Week 2, Day 2)**: Order structures and storage complete. Price-time priority matching and fills are planned. |
| `chronos/dashboard.py` | Curses Dashboard | Terminal monitoring UI, layout helper functions, color themes, resize handling. | **Partially Implemented (Week 2, Day 2)**: Visual layout complete with placeholder values. Live telemetry ingestion is planned. |
| `scripts/run_firehose.py` | Producer CLI | CLI runner to configure and launch the firehose stream. | **Completed (Week 1)** |
| `scripts/run_consumer.py` | Consumer CLI | CLI runner to attach to ring buffer and measure consumer throughput. | **Completed (Week 1)** |
| `scripts/run_dashboard.py` | Dashboard CLI | CLI launcher supporting interactive curses mode and headless `--non-interactive` mode. | **Completed (Week 2, Day 2)** |
| `scripts/benchmark_ipc.py` | Benchmark Suite | Multi-process end-to-end benchmark measuring true IPC throughput and latency. | **Completed (Week 1)** |
| *Integration Adapter* | Pipeline Bridge | Ingests from ring buffer consumer, feeds `MatchingEngine`, and provides snapshots to `TerminalDashboard`. | **Planned (Week 2, Day 4-5)**: Not yet implemented. |

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

## 8. Team Responsibilities

| Team Member | Role | Key Contributions & Scope |
| :--- | :--- | :--- |
| **Faizan** *(Team Leader)* | System Architecture & Foundation | * Week 1 Foundation: Binary protocol (`protocol.py`), SPSC memory-mapped ring buffer (`ring_buffer.py`), mock order generator (`firehose.py`), consumer (`consumer.py`).<br>* IPC benchmark suite (`benchmark_ipc.py`).<br>* System integration architecture, CI configuration, pytest test suite maintenance, and repository documentation. |
| **Albert** | Matching Engine Core | * Cython matching engine foundation (`matching_engine.pyx`).<br>* `COrder` C-level data structures and integer cent price representation.<br>* BUY and SELL order-book storage (`_bids` and `_asks`).<br>* Next: Price-Time Priority matching algorithm, order fills, and cancellation handling. |
| **Taniya** | Monitoring & Dashboard | * Curses terminal dashboard (`dashboard.py`, `run_dashboard.py`).<br>* Multi-section UI: Market Summary, Order Book, Performance Metrics.<br>* Pure layout formatting functions and dimension checks.<br>* Next: Ingestion of live engine telemetry, top-of-book depth rendering, and dynamic latency percentiles. |

---

## 9. Remaining Integration Tasks

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

## 10. How to Verify Current Components

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

* **Week 1 Foundation Tests** (Protocol, Ring Buffer, Firehose):
  ```powershell
  python -m pytest tests/test_protocol.py tests/test_ring_buffer.py tests/test_firehose.py -v
  ```
  *Expected behavior*: 10 passed tests verifying struct sizes, pack/unpack accuracy, ring buffer sequence wrapping, cache-line separation, and firehose generator logic.

* **Cython Matching Engine Tests** (requires compiled extension):
  ```powershell
  python -m pytest tests/test_matching_engine.py -v
  ```
  *Expected behavior*: 44 unit tests validating engine initialization, valid order submission, rejection of invalid sides/prices/quantities, integer cent conversion, sequence order preservation, and bid/ask separation.

* **Terminal Dashboard Tests** (requires `windows-curses` on Windows):
  ```powershell
  python -m pytest tests/test_dashboard.py -v
  ```
  *Expected behavior*: 29 unit tests verifying layout builders, header/summary/book/performance formatting, terminal size checking, and input handling.

* **Full Test Suite**:
  ```powershell
  python -m pytest -v
  ```

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
