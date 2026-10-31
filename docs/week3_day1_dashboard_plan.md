# ChronosMatch — Week 3 Day 1: Terminal Dashboard & Whale Order Visualization Architecture Plan

## 1. Executive Summary & Goals

### 1.1 Context
**ChronosMatch** is a Zero-Copy High-Frequency Trading (HFT) Engine engineered in Python, C, and compiled Cython. The system architecture divides pipeline responsibilities across distinct operating system processes:
1. **Market Firehose (Producer)**: Generates and streams synthetic order ticks at target rates exceeding 100,000 orders/sec into a memory-mapped ring buffer.
2. **Shared Memory Ring Buffer (IPC)**: SPSC lock-free shared ring buffer backed by an OS-managed memory-mapped file (`mmap`) with 32-byte cache-line-aligned binary order slots.
3. **Matching Engine (Consumer & Core)**: A high-performance compiled Cython Limit Order Book (LOB) executing orders with deterministic price-time priority (FIFO).
4. **Order Adapter & Live Feed**: Bridges the IPC ring buffer to the matching engine, transforming raw binary protocol tuples into order book actions.
5. **Terminal Dashboard (UI & Telemetry)**: An interactive curses-based monitoring dashboard visualizing real-time Depth of Market (L2 book), spreads, throughput, and latency.

### 1.2 Week 3 Day 1 Objectives
The primary objective of **Week 3, Day 1** is to perform a comprehensive architectural inspection of the existing terminal dashboard and establish an authoritative, non-breaking design plan for:
1. A **dedicated, multi-dimensional metrics section** displaying trade execution latency, orders processed, matching engine health, and trade entry/exit timestamps.
2. A **Whale order visualization feature** highlighting massive institutional orders that consume liquidity across multiple price levels (multi-level sweeps) and resting liquidity walls.
3. An end-to-end **telemetry data flow** connecting Cython matching engine outputs (`TradeResult`), adapter statistics (`AdapterStats`), and transit latency metrics (`ConsumerStats`) directly into the dashboard without latency degradation.

### 1.3 Key Governance & Quality Rules
- **Inspection & Planning Only**: Day 1 establishes the blueprint; no production dashboard code is refactored prematurely.
- **Preserve Existing Architecture**: The functional separation between pure, stateless layout helpers and the curses rendering lifecycle must remain 100% intact.
- **Zero Invention of Phantom Metrics**: All planned metrics must be strictly grounded in telemetry already exposed or computable by `chronos/matching_engine.pyx`, `chronos/adapter.py`, `chronos/consumer.py`, and `chronos/protocol.py`.
- **Configurable Whale Thresholds**: Whale order criteria must be dynamic and user-configurable via CLI flags, environment variables, and `ChronosConfig`, avoiding arbitrary hardcoded constants.
- **Backward Compatibility**: All 154 existing dashboard unit and property tests in `tests/test_dashboard.py` must continue passing without regression.

---

## 2. Existing Dashboard Architecture Analysis

### 2.1 Component Structure & Design Pattern
The existing dashboard implementation (`chronos/dashboard.py`, 1,737 lines) follows a **Decoupled Model-View-Presenter (MVP)** / **Functional Presentation** architectural pattern:

```
+----------------------------------------------------------------------------------------------------+
|                                     chronos/dashboard.py                                           |
|                                                                                                    |
|  +-----------------------------------------------------------------------------------------------+ |
|  | LAYER 1: PURE COMPUTATION & DATA FORMATTING (Stateless, 100% Testable in Headless CI)         | |
|  |  - calculate_best_bid(), calculate_best_ask(), calculate_spread()                             | |
|  |  - calculate_buy_depth(), calculate_sell_depth(), format_depth_rows()                           | |
|  |  - calculate_throughput(), calculate_latency_stats()                                          | |
|  |  - format_price(), format_orders_processed(), format_throughput(), format_latency()            | |
|  +-----------------------------------------------------------------------------------------------+ |
|                                                 │                                                  |
|                                                 ▼                                                  |
|  +-----------------------------------------------------------------------------------------------+ |
|  | LAYER 2: PURE LAYOUT COMPOSITION (Produces List[str] text buffers without curses hardware)    | |
|  |  - build_header_lines(width, status)                                                          | |
|  |  - build_market_summary_lines(width, best_bid, best_ask, spread, bid_qty, ask_qty)              | |
|  |  - build_order_book_lines(width, bid_rows, ask_rows, num_placeholder_rows)                      | |
|  |  - build_performance_lines(width, total_orders, throughput, latency, latency_avg)             | |
|  |  - build_footer_lines(width)                                                                  | |
|  +-----------------------------------------------------------------------------------------------+ |
|                                                 │                                                  |
|                                                 ▼                                                  |
|  +-----------------------------------------------------------------------------------------------+ |
|  | LAYER 3: STATE & CURSES LIFECYCLE MANAGEMENT (TerminalDashboard)                              | |
|  |  - Orders state: buy_orders, sell_orders, orders_processed, throughput                         | |
|  |  - Latency state: _latency_last_ns, _latency_samples (rolling reservoir buffer)                 | |
|  |  - Curses rendering: run_curses(), render(), _safe_addstr(), _init_colors(), _build_attrs()   | |
|  |  - Event loop & Input: handle_input() [Q to quit], non-blocking getch() timeout               | |
|  |  - Fallback logic: is_terminal_size_sufficient(), get_display_lines() (headless/CI)             | |
|  +-----------------------------------------------------------------------------------------------+ |
+----------------------------------------------------------------------------------------------------+
```

### 2.2 Current Dashboard Sections & Screen Budget
The current dashboard renders 5 distinct sections in a single vertical stack. With default configuration, the layout consumes a minimum of **30 rows** and **72 columns**:

| Section # | Section Name | Content / Fields Displayed | Current Line Budget |
| :--- | :--- | :--- | :--- |
| **Section 1** | **Header** | Application Title (`CHRONOSMATCH`), Subtitle (`Zero-Copy High-Frequency Trading Engine`), Connection / Engine Status badge (`[Dashboard Initialized]`, `[Live: Connected]`, or `[Demo: Sample Data]`). Enclosed in double-line borders (`=`). | 5 lines + 1 blank line = **6 lines** |
| **Section 2** | **Market Summary** | Best Bid Price, Best Bid Aggregated Quantity, Best Ask Price, Best Ask Aggregated Quantity, Bid-Ask Spread ($). | 7 lines + 1 blank line = **8 lines** |
| **Section 3** | **Order Book** | Side-by-side two-column Depth of Market (Top 5 price levels):<br>• Left Column: `BUY ORDERS (BIDS)` (Price, Qty)<br>• Right Column: `SELL ORDERS (ASKS)` (Price, Qty) | 8 lines + 1 blank line = **9 lines** |
| **Section 4** | **Performance Metrics** | Total Orders Processed, Throughput (`orders/sec`), Last Inter-event Latency (`us`), Rolling Average Inter-event Latency (`us`). | 6 lines + 1 blank line = **7 lines** |
| **Section 5** | **Footer** | Quit instruction (`Press Q to Quit`) and closing double-line border. | **2 lines** |
| **Total** | **Full Display** | Combined vertical footprint of current layout. | **32 lines** (Fits 72x30+ terminal) |

### 2.3 Current Market Information Display
1. **Best Bid & Best Ask**:
   - Calculated via `calculate_best_bid(orders)` and `calculate_best_ask(orders)` which inspect the order collection.
   - Extracts price and quantity using `_extract_order_price_qty()`, which supports dicts, tuples, objects (`COrder`), and protocols.
   - Aggregates quantity across identical prices.
2. **Bid-Ask Spread**:
   - Evaluated as $\text{Spread} = \text{Best Ask} - \text{Best Bid}$.
   - Rounded to 6 decimal places and formatted to 2 decimal places. Displays `N/A` or `--` when either side is empty or uncrossed.
3. **Order Book Depth**:
   - Formats up to 5 price levels per side (`calculate_buy_depth`, `calculate_sell_depth`).
   - Bids are sorted descending (highest price first); Asks are sorted ascending (lowest price first).
   - If fewer than 5 levels exist, padded with placeholder rows (`--`).
4. **Color Coding**:
   - Bids are colored Cyan (`curses.COLOR_CYAN`, Color Pair 6).
   - Asks are colored Red (`curses.COLOR_RED`, Color Pair 7).
   - Section headers are Bold Magenta (`curses.COLOR_MAGENTA`, Color Pair 5).
   - Values are Green (`curses.COLOR_GREEN`, Color Pair 2).
   - Borders and subtitles are White/Dim (`curses.COLOR_WHITE`, Color Pair 4).

### 2.4 Existing Latency & Throughput Mechanics
- **Throughput**:
  - Measured via `update_throughput()`.
  - Calculates $\Delta \text{orders} / \Delta \text{time}$ using monotonic clock (`time.monotonic`).
  - Guards against zero elapsed time, negative time jumps, and negative counter deltas.
- **Latency**:
  - Measured via `_record_latency_sample()` using nanosecond clock (`time.perf_counter_ns`).
  - **Important Architectural Finding**: The current latency metric measures the **inter-event arrival interval** between consecutive `record_order_processed()` invocations at the dashboard boundary. As documented in `chronos/dashboard.py` lines 58–66:
    > *"Measures inter-event elapsed time between consecutive record_order_processed() calls recorded by the dashboard. This reflects the spacing between processing events observed at the dashboard boundary, NOT full end-to-end network or engine dispatch latency."*
  - The dashboard maintains a rolling reservoir of up to 1,000 latency samples, computing `last`, `avg`, `max`, and `p95` (when $\ge 20$ samples exist).

---

## 3. Backend Data Availability Audit (Ground Truth)

A critical rule of this task is: **Do not invent metrics that are not available from the backend.**
Below is the definitive audit of data fields physically exposed by the underlying engine and pipeline components.

### 3.1 Cython Matching Engine (`chronos/matching_engine.pyx`)

#### Order Object (`COrder`)
```python
cdef class COrder:
    cdef public unsigned long long order_id          # uint64 unique order ID
    cdef public int side                            # 1 = BUY, 2 = SELL
    cdef public long long price_cents               # Integer cents ($1.00 = 100)
    cdef public unsigned int quantity               # Initial quantity submitted
    cdef public unsigned int remaining_quantity     # Live remaining quantity
    cdef public unsigned long long timestamp_ns     # Order entry timestamp (ns)
    cdef public unsigned long long sequence_num     # Deterministic arrival sequence
```

#### Trade Result (`TradeResult`)
```python
cdef class TradeResult:
    cdef public unsigned long long buy_order_id     # Matching BUY order ID
    cdef public unsigned long long sell_order_id    # Matching SELL order ID
    cdef public unsigned int executed_quantity      # Shares executed in this fill
    cdef public long long execution_price_cents     # Execution price in cents (maker price)
    cdef public unsigned int buy_remaining_quantity # Post-fill BUY remaining quantity
    cdef public unsigned int sell_remaining_quantity# Post-fill SELL remaining quantity
```

#### Engine Inspection APIs
- `order_count()`: Total orders accepted by the engine (`unsigned long long`).
- `bid_count()`, `ask_count()`: Number of resting BUY and SELL orders in book.
- `get_prioritized_bids()`, `get_prioritized_asks()`: Orders sorted by price-time priority.
- `get_best_buy_order()`, `get_best_sell_order()`: Top-of-book order references.
- `get_best_buy_quantity(aggregate=True)`, `get_best_sell_quantity(aggregate=True)`: Available volume at top-of-book.
- `get_spread()`, `get_spread_cents()`: Difference between best ask and best bid.
- `match_order(order_id, side, price, quantity, timestamp_ns)`: Returns `list[TradeResult]`. A single incoming order can sweep multiple resting levels, producing multiple `TradeResult` records.

### 3.2 Order Adapter (`chronos/adapter.py`)
- `AdapterStats`:
  * `total_orders_read`: Orders pulled from the ring buffer.
  * `total_orders_dispatched`: Orders submitted to the matching engine.
  * `total_trades_generated`: Cumulative execution count (`len(trades)`).
  * `total_volume_matched`: Sum of all `executed_quantity`.
  * `non_crossing_orders`: Orders that rested in the book without immediate fills.
  * `unhandled_order_types`: Count of unsupported non-limit orders.
  * `unrouted_symbols`: Count of unmapped ticker IDs.
- `trades`: Bounded or historical list of `TradeResult` records generated during runtime.

### 3.3 Zero-Copy Consumer (`chronos/consumer.py`)
- `ConsumerStats`:
  * `total_orders_read`: Total count of orders consumed from IPC ring buffer.
  * `current_rate`, `avg_rate`: Instantaneous and lifetime consumption rate (orders/sec).
  * `min_latency_us`, `max_latency_us`, `avg_latency_us`, `p99_latency_us`: **Transit Latency** calculated directly from binary slot timestamps:
    $$\text{transit\_latency\_us} = \frac{\text{now\_ns} - \text{order.timestamp\_ns}}{1000.0}$$

### 3.4 Telemetry Capability Matrix

| Telemetry Category | Metric Name | Backend Source | Availability Status |
| :--- | :--- | :--- | :--- |
| **Order Throughput** | Total Orders Ingested | `LiveFeedBridge._orders_processed` / `consumer.stats.total_orders_read` | **Fully Available** |
| **Order Throughput** | Total Orders Matched | `adapter.stats.total_orders_dispatched` | **Fully Available** |
| **Order Throughput** | Ingestion Rate (ord/s) | `TerminalDashboard.throughput` / `consumer.stats.current_rate` | **Fully Available** |
| **Engine Health** | Resting Bids / Asks Count | `engine.bid_count()`, `engine.ask_count()` | **Fully Available** |
| **Engine Health** | Active Order Count | `engine.order_count()` | **Fully Available** |
| **Trade Execution** | Total Trades Generated | `adapter.stats.total_trades_generated` | **Fully Available** |
| **Trade Execution** | Total Matched Volume (Shares) | `adapter.stats.total_volume_matched` | **Fully Available** |
| **Trade Execution** | Last Trade Fill Price & Qty | Last `TradeResult` in `adapter.trades` | **Fully Available** |
| **Latency: Transit** | Transit Latency (Min/Avg/P99) | `consumer.stats` ($\text{now\_ns} - \text{timestamp\_ns}$) | **Fully Available** |
| **Latency: Engine Match** | Match Execution Duration ($\mu s$) | Time elapsed inside `engine.match_order()` | **Computable via LiveFeed** |
| **Latency: Boundary** | Inter-Event Dispatch Interval | `TerminalDashboard._latency_samples` | **Fully Available** |
| **Timestamps** | Order Entry Timestamp | `COrder.timestamp_ns` / binary protocol slot | **Fully Available** |
| **Timestamps** | Trade Execution Timestamp | `time.time_ns()` captured upon `TradeResult` generation | **Available via Adapter / LiveFeed** |

---

## 4. Proposed Dedicated Metrics Section

### 4.1 Shortcomings of Current Performance Section
The existing Section 4 (`PERFORMANCE METRICS`) has several structural gaps:
1. It combines inter-event boundary pacing into generic "Latency", which users may mistake for engine matching latency.
2. It does not report total trades executed or volume matched.
3. It does not display matching engine book inventory (active resting bids/asks).
4. It lacks trade timestamps (entry time, match completion time).
5. It does not provide percentile distributions (P95, P99) for latency.

### 4.2 Enhanced Metrics Architecture
The planned Metrics Section will be structured into three functional telemetry blocks:

```
+-----------------------------------------------------------------------+
|  PERFORMANCE & ENGINE METRICS                                         |
|-----------------------------------------------------------------------|
|  [THROUGHPUT & ENGINE HEALTH]                                         |
|  Total Orders Ingested :  1,250,400    Throughput : 104,210 ord/s     |
|  Active Resting Orders :         84    (Bids: 42 | Asks: 42)          |
|  Total Trades Executed :     12,450    Matched Vol: 1,840,200 shares  |
|-----------------------------------------------------------------------|
|  [EXECUTION & PIPELINE LATENCY (microseconds)]                        |
|  Transit Latency (IPC) : Last:   1.2 | Avg:   1.4 | P95:   2.1 | Max: 8.4|
|  Match Execution (LOB) : Last:   0.4 | Avg:   0.5 | P95:   0.8 | Max: 2.1|
|  Event Spacing (GUI)   : Last:  95.2 | Avg: 100.1 | Max: 120.4        |
|-----------------------------------------------------------------------|
|  [TIMESTAMPS & ENGINE CLOCK]                                          |
|  Last Order Entry Time : 18:54:20.104928 UTC  (ts_ns: 1729864460...)   |
|  Last Trade Exec Time  : 18:54:20.104932 UTC  (Execution Delta: 4.0us)|
+-----------------------------------------------------------------------+
```

### 4.3 Proposed Pure Layout Functions
To preserve 100% testability, new layout helpers will be implemented as pure functions in `chronos/dashboard.py`:

```python
def format_timestamp_ns(timestamp_ns: Optional[int]) -> str:
    """Format nanosecond integer timestamp to UTC HH:MM:SS.ffffff string."""
    if not timestamp_ns or timestamp_ns <= 0:
        return PLACEHOLDER
    # Convert ns to datetime string without external heavy dependencies
    ...

def build_engine_health_lines(
    width: int,
    total_orders: int,
    active_bids: int,
    active_asks: int,
    total_trades: int,
    matched_volume: int,
    throughput: Union[float, str],
) -> List[str]:
    """Pure function generating Engine Health sub-panel lines."""
    ...

def build_latency_breakdown_lines(
    width: int,
    transit_stats: Optional[Dict[str, float]],
    match_stats: Optional[Dict[str, float]],
    interval_stats: Optional[Dict[str, float]],
) -> List[str]:
    """Pure function generating multi-tier latency metrics lines."""
    ...

def build_enhanced_metrics_lines(
    width: int,
    metrics: DashboardMetricsSnapshot,
) -> List[str]:
    """Pure function assembling the complete dedicated metrics section."""
    ...
```

---

## 5. Whale Order Visualization Design

### 5.1 What Defines a Whale Order in ChronosMatch?
In quantitative market making and HFT execution, a **Whale Order** represents an order whose size or aggression exerts substantial market impact:
1. **Resting Liquidity Wall (Passive Whale)**: A limit order sitting in the book whose size exceeds standard market depth, representing significant support or resistance.
2. **Aggressive Liquidity Sweep (Sweeping Whale)**: A massive market or crossing limit order that exhausts the top-of-book level and sweeps across multiple ascending ask levels or descending bid levels.

### 5.2 Configurable Whale Threshold Architecture
To strictly honor the requirement: **"Use a configurable Whale order threshold rather than assuming an arbitrary fixed production threshold"**, the threshold will be configured hierarchically:

1. **Global Configuration (`chronos/config.py`)**:
   ```python
   DEFAULT_WHALE_ORDER_THRESHOLD: int = 1_000      # Contracts / shares
   DEFAULT_WHALE_SWEEP_LEVELS: int = 2             # Distinct price levels touched
   DEFAULT_WHALE_FEED_CAPACITY: int = 5            # Max recent whale events retained
   ```
2. **Dashboard Configuration Dataclass (`chronos/dashboard.py`)**:
   ```python
   @dataclass(frozen=True)
   class DashboardConfig:
       refresh_interval_ms: int = DEFAULT_REFRESH_INTERVAL_MS
       min_rows: int = MIN_TERMINAL_ROWS
       min_cols: int = MIN_TERMINAL_COLS
       whale_order_threshold: int = DEFAULT_WHALE_ORDER_THRESHOLD
       whale_sweep_levels: int = DEFAULT_WHALE_SWEEP_LEVELS
       max_whale_events: int = DEFAULT_WHALE_FEED_CAPACITY
   ```
3. **CLI Launcher Option (`scripts/run_dashboard.py`)**:
   ```bash
   python scripts/run_dashboard.py --whale-threshold 2500 --refresh-ms 100
   ```
4. **Dynamic Relative Thresholding (Optional Mode)**:
   In addition to absolute contract size, the system will support a relative multiplier:
   $$\text{Threshold}_{\text{dynamic}} = k \times \text{Average Level Depth}$$
   where $k$ defaults to $3.0$ (3x standard depth).

### 5.3 Multi-Level Liquidity Sweep Detection
When an order is submitted to `engine.match_order()`, the Cython engine returns a `list[TradeResult]`.
A multi-level sweep is detected if and only if:
1. `len(trades) > 1`: Multiple resting orders were filled.
2. Distinct price levels filled $\ge \text{whale\_sweep\_levels}$ (default 2):
   $$\text{Distinct Prices} = \left|\{ t.\text{execution\_price\_cents} \text{ for } t \in \text{trades} \}\right| \ge 2$$
3. Or cumulative matched volume $\ge \text{whale\_order\_threshold}$:
   $$\sum_{t \in \text{trades}} t.\text{executed\_quantity} \ge \text{whale\_order\_threshold}$$

#### Sweep Event Record Structure
```python
@dataclass(frozen=True)
class WhaleEvent:
    """Immutable record of an identified Whale order or multi-level liquidity sweep."""
    order_id: int
    side: int                            # 1 = BUY, 2 = SELL
    quantity: int                        # Total incoming order quantity
    executed_volume: int                 # Volume filled during sweep
    remaining_quantity: int              # Unfilled volume resting in book
    levels_swept: int                    # Number of distinct price levels consumed
    start_price: float                   # Initial execution price
    end_price: float                     # Final execution price
    slippage_cents: int                  # Price slippage incurred during sweep
    timestamp_ns: int                    # Arrival timestamp
    is_sweep: bool                       # True if swept multiple levels
```

### 5.4 Visual Highlighting & Color Strategy

#### Color Pairs & Attributes
Curses attributes must differentiate BUY vs SELL and accentuate Whale alerts:

| Element | Curses Attribute | Color Pair | Visual Appearance | Fallback (Monochrome) |
| :--- | :--- | :--- | :--- | :--- |
| **Normal BUY (Bid)** | `A_NORMAL` | Pair 6 (Cyan/Default) | Cyan Text | Standard Text |
| **Normal SELL (Ask)** | `A_NORMAL` | Pair 7 (Red/Default) | Red Text | Standard Text |
| **Whale BUY Order** | `A_BOLD` | Pair 2 (Green) on Black | Bright Bold Green `▲` | `[WHALE-B]` + `A_BOLD` |
| **Whale SELL Order** | `A_BOLD` | Pair 7 (Red) on Black | Bright Bold Red `▼` | `[WHALE-S]` + `A_BOLD` |
| **Resting Whale Wall** | `A_REVERSE` | Pair 3 (Yellow/Black) | Inverted Highlight | `[WALL]` + `A_REVERSE` |
| **Multi-Level Sweep** | `A_BOLD \| A_STANDOUT` | Pair 1 / Pair 3 | Flash Alert Badge `⚡` | `[⚡ SWEEP ALERT]` |

#### Order Book Depth Table Integration
In the two-column Order Book table, price levels with aggregated quantities meeting or exceeding `whale_order_threshold` will display a dynamic visual badge:
```
  BUY ORDERS (BIDS)                          SELL ORDERS (ASKS)
  Price       Qty  Tag                       Price       Qty  Tag
 150.00     1,250  [WHALE]                  150.25       120
 149.95       450                           150.30     3,400  [WHALE]
 149.90       800                           150.35       250
```

#### Dedicated Whale Activity Log / Alert Banner
Positioned immediately below the Order Book or integrated into the Market Summary:
```
+-----------------------------------------------------------------------+
|  RECENT WHALE & LIQUIDITY SWEEP EVENTS                                |
|-----------------------------------------------------------------------|
|  [18:45:12.104] ⚡ BUY SWEEP  #10921 Qty: 5,000 swept 3 levels         |
|                 $150.00 -> $150.10 | Exec: 3,800 | Resting: 1,200     |
|  [18:45:11.850] ▲ BUY WALL   #10840 Qty: 2,500 resting @ $149.90     |
|  [18:45:09.320] ⚡ SELL SWEEP #10412 Qty: 4,000 swept 2 levels         |
|                 $150.15 -> $150.05 | Exec: 4,000 (100% Filled)        |
+-----------------------------------------------------------------------+
```

---

## 6. End-to-End Suggested Data Flow

### 6.1 Telemetry Pipeline Architecture
To ensure zero latency impact on the critical matching path, telemetry aggregation follows an asynchronous, lock-free observer pattern:

```
PRODUCER PROCESS                                CONSUMER / MATCHING PROCESS
+----------------------+                        +-------------------------------------------------------+
| Market Firehose      |                        | ZeroCopyConsumer                                      |
| (fast order stream)  |                        |   - Drains raw 32-byte binary slots                   |
+----------+-----------+                        |   - Computes Transit Latency (now_ns - order_ts_ns)   |
           │                                    +---------------------------+---------------------------+
           │ Direct Byte Writes                                             │
           v                                                                v raw_order tuple
+-------------------------------------------------------+       +---------------------------------------+
| Shared Memory IPC Ring Buffer (chronos_ring.bin)      |       | OrderAdapter.dispatch_raw_order()     |
+-------------------------------------------------------+       +-------------------+-------------------+
                                                                                    │
                                                                                    ▼ match_order()
                                                                +---------------------------------------+
                                                                | Cython MatchingEngine                 |
                                                                |   - Executes price-time priority LOB  |
                                                                |   - Produces list[TradeResult]        |
                                                                +-------------------+-------------------+
                                                                                    │
                                                                                    ▼ trades list
                                                                +---------------------------------------+
                                                                | LiveFeedBridge                        |
                                                                |   1. Measure match duration           |
                                                                |   2. Check Whale / Sweep Criteria     |
                                                                |   3. Update rolling stats buffers     |
                                                                +-------------------+-------------------+
                                                                                    │
                                                                                    ▼ atomic state sync
                                                                +---------------------------------------+
                                                                | TerminalDashboard                     |
                                                                |   - Reads cached metrics snapshot     |
                                                                |   - Pure layout evaluation            |
                                                                |   - Curses double-buffered render     |
                                                                +---------------------------------------+
```

### 6.2 Step-by-Step Data Flow Sequence
1. **Order Dispatch & Timing**:
   - `LiveFeedBridge._handle_raw_order(raw_order)` receives the 7-tuple.
   - Measures timestamp: $t_{\text{start}} = \text{time.perf\_counter\_ns}()$.
   - Calls `self.adapter.dispatch_raw_order(raw_order)` which invokes `engine.match_order(...)`.
   - Measures completion: $t_{\text{end}} = \text{time.perf\_counter\_ns}()$.
   - Execution latency $\Delta t_{\text{match}} = (t_{\text{end}} - t_{\text{start}}) / 1000.0$ ($\mu s$).
2. **Whale Detection Hook**:
   - If `quantity >= whale_threshold` or `len(distinct_prices) >= 2`:
     * Instantiate `WhaleEvent`.
     * Push to bounded `deque(maxlen=max_whale_events)`.
3. **Dashboard State Update**:
   - `LiveFeedBridge.sync_to_dashboard()` copies active bids, active asks, recent whale events, and latency snapshots to the dashboard.
   - Operations are atomic pointer/reference swaps in Python, avoiding lock contention with the curses render loop.
4. **Rendering Cycle**:
   - Every `refresh_interval_ms` (100 ms), the curses loop calls `dashboard.render(stdscr)`.
   - `render()` strictly formats and prints pre-calculated data; it never performs heavy aggregations or IPC reads.

---

## 7. Terminal Width, Refresh Rate, and Readability Plan

### 7.1 Screen Geometry & Responsive Layout
To prevent terminal truncation across various window sizes:

1. **Standard Mode ($72 \le \text{cols} < 100$, $\text{rows} \ge 34$)**:
   - Single vertical column format.
   - Market Summary $\to$ Order Book (Top 5) $\to$ Whale Alerts (Top 3) $\to$ Dedicated Metrics $\to$ Footer.
2. **Widescreen Mode ($\text{cols} \ge 100$, $\text{rows} \ge 32$)**:
   - Dual-column side-by-side layout:
     * **Left Half (Cols 0..48)**: Market Summary & Order Book Depth with Whale tags.
     * **Right Half (Cols 50..98)**: Performance Metrics Panel & Live Whale Sweep Event Log.
   - Maximizes information density without forcing vertical scrolling.
3. **Compact / Minimum Mode Fallback ($\text{rows} < 30$ or $\text{cols} < 72$)**:
   - Existing robust "Screen too small!" warning is preserved.

### 7.2 Screen Refresh Rate & Curses Performance
- **Optimal Refresh Cadence**: 100 ms (10 Hz).
  * 10 FPS is ideal for terminal emulators: fluid for human eyes, zero terminal buffering lag, negligible CPU usage (< 1% core).
- **Flicker-Free Rendering Principles**:
  * Utilize `stdscr.erase()` instead of `clear()` to prevent full-screen redraw strobe.
  * Use double buffering via `stdscr.refresh()` or `curses.doupdate()`.
  * Pre-allocate strings; avoid line-wrapping beyond `max_x - 1`.
  * Guard against bottom-right corner writing bug in curses (`max_y - 1, max_x - 1`).

---

## 8. Proposed Implementation Steps (Days 2–5)

### Day 2: Telemetry & Event Pipeline Integration
- **Objective**: Connect backend trade execution metrics and timestamps to the dashboard data layer.
- **Deliverables**:
  1. Update `LiveFeedBridge` to capture `TradeResult` records returned by `OrderAdapter.dispatch_raw_order()`.
  2. Implement transit latency and match execution latency sampling in `LiveFeedBridge`.
  3. Create `WhaleEvent` dataclass and bounded event buffer in `chronos/dashboard.py`.
  4. Implement pure helper functions for timestamp formatting (`format_timestamp_ns`) and latency percentiles.
  5. Unit tests covering metric calculations and latency statistics.

### Day 3: Dedicated Metrics Section Implementation
- **Objective**: Construct the dedicated metrics layout and curses rendering components.
- **Deliverables**:
  1. Implement `build_enhanced_metrics_lines()` pure layout function.
  2. Integrate Throughput, Engine Health (resting bid/ask counts), Latency Tiers (transit, matching, spacing), and Timestamps.
  3. Update `TerminalDashboard.render()` to draw the dedicated metrics panel.
  4. Add unit tests verifying formatted string outputs and small-screen resilience.

### Day 4: Whale Order & Multi-Level Sweep Detection
- **Objective**: Implement configurable Whale order detection, sweep tracking, and alert data structures.
- **Deliverables**:
  1. Add `DEFAULT_WHALE_ORDER_THRESHOLD` and `DEFAULT_WHALE_SWEEP_LEVELS` to `chronos/config.py`.
  2. Implement multi-level sweep detection logic in `LiveFeedBridge` / `OrderAdapter`.
  3. Implement `build_whale_alerts_lines()` pure layout function.
  4. Integrate Whale tagging into `calculate_buy_depth()` and `calculate_sell_depth()`.
  5. Unit tests verifying multi-level sweep detection across known test fixtures.

### Day 5: Visual Styling, Highlighting & End-to-End Validation
- **Objective**: Polish visual presentation, color pairs, CLI configuration, and end-to-end testing.
- **Deliverables**:
  1. Configure curses color pairs (reverse video for walls, bold green/red for whale orders, standout yellow for sweeps).
  2. Add `--whale-threshold` argument to `scripts/run_dashboard.py`.
  3. Validate terminal resize stability on Windows (`windows-curses`).
  4. Execute full regression suite (all 755+ existing tests + new dashboard tests).
  5. Update documentation with final operational guide and screenshots.

---

## 9. Potential Integration Challenges & Mitigations

| Challenge | Impact | Technical Root Cause | Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **GIL & Thread Contention** | GUI stutter or dropped frames | Live feed worker thread and curses render loop running in same Python process. | Live feed thread updates internal state atomically; dashboard takes atomic snapshot via shallow copy or namedtuple. No heavy processing inside `render()`. |
| **Windows Curses Quirks** | Crashes on terminal resize | `windows-curses` handles `curses.error` and window resize signals differently than POSIX ncurses. | Retain all `_safe_addstr()` boundary checks; swallow terminal writing errors during rapid resize transitions. |
| **Observer Effect on Latency** | Synthetic latency inflation | Calling high-resolution clocks on every order in hot path can add 20–50 ns per order. | Sample latency systematically or sample every $N$-th order in ultra-high throughput mode; compute execution delta at batch boundary. |
| **Rapid Event Flooding** | Whale alert buffer overflow | Firehose producer generating thousands of whale orders can flood dashboard. | Enforce a strict bounded ring-buffer (`deque(maxlen=5)`) for whale events; drop older alerts gracefully. |
| **Monochrome Terminals** | Loss of visual whale distinction | User terminal lacking color support (`has_colors() == False`). | Implement explicit ASCII textual tags (`[WHALE-B]`, `[WHALE-S]`, `[⚡ SWEEP]`) and `curses.A_BOLD` / `curses.A_REVERSE` attributes that work without color. |

---

## 10. Conclusion & Next Steps

This plan establishes a comprehensive, mathematically rigorous, and backward-compatible blueprint for the ChronosMatch dashboard enhancements.
- **No breaking changes**: All existing layout functions, constants, and test cases remain functional.
- **True-to-hardware**: Relies entirely on verified metrics exposed by `MatchingEngine`, `OrderAdapter`, and `ZeroCopyConsumer`.
- **Ready for Day 2**: Ready to commence Day 2 implementation focusing on the backend telemetry pipeline integration.
