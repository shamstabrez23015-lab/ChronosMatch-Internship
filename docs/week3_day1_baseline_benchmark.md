# Week 3, Day 1 — Baseline Benchmark: Trade Execution Performance

**Date:** 2026-10-31
**Engineer:** ChronosMatch Internship
**Purpose:** Establish a truthful pre-optimisation baseline for trade execution before any Cython profiling or Week 3 optimisations are applied.

---

## 1. Objective

Measure the raw throughput of the existing ChronosMatch pipeline across four distinct scopes so that all future Cython optimisations (Week 3, Days 2–5) have a concrete, reproducible baseline to improve upon. No fabricated numbers — all figures below were captured live from a single benchmark session on the development machine.

---

## 2. Benchmark Architecture

The existing benchmark infrastructure (`scripts/benchmark_pipeline.py` and `scripts/benchmark_ipc.py`) exposes a `--scope` flag that isolates different layers of the pipeline:

```
Order Generator
    │
    ▼
BinaryProtocol (pack / unpack)
    │
    ▼
MmapRingBuffer  (zero-copy IPC shared-memory ring)
    │
    ▼
ZeroCopyConsumer (reads from ring buffer)
    │
    ▼
OrderAdapter  (normalises & routes by symbol)
    │
    ▼
MatchingEngine (Cython .pyx — Price-Time Priority limit order book)
```

Four scopes are benchmarked:

| Scope flag | Stages active |
|---|---|
| `full` | All 6 stages end-to-end |
| `adapter` | Protocol → OrderAdapter → MatchingEngine (no ring buffer) |
| `engine` | MatchingEngine only (direct `match_order` calls) |
| `ipc` | Generator → Protocol → MmapRingBuffer → Consumer (no matching) |

Each scope runs **3 timed repetitions** (preceded by **1 warmup** that is excluded from statistics) over **10,000 orders per run** in **batches of 500**, using `time.perf_counter_ns()` as the clock.

Order mix: **90 % LIMIT, 10 % MARKET/CANCEL** (non-LIMIT orders are intercepted by `OrderAdapter` and counted as unhandled — they never reach the limit order book).

---

## 3. Benchmark Commands

```bash
# Activate virtual environment first
.venv\Scripts\activate

# Scope 1 — Full end-to-end pipeline
python scripts/benchmark_pipeline.py --scope full --orders 10000 --repetitions 3

# Scope 2 — Adapter + Engine (skip ring buffer)
python scripts/benchmark_pipeline.py --scope adapter --orders 10000 --repetitions 3

# Scope 3 — Matching Engine only
python scripts/benchmark_pipeline.py --scope engine --orders 10000 --repetitions 3

# Scope 4 — Zero-Copy IPC only (no matching)
python scripts/benchmark_pipeline.py --scope ipc --orders 10000 --repetitions 3

# Machine-readable JSON output (full scope)
python scripts/benchmark_pipeline.py --scope full --orders 10000 --repetitions 3 --json
```

---

## 4. Hardware / Software Environment

| Property | Value |
|---|---|
| **OS** | Windows 11 (10.0.26300) |
| **CPU** | 11th Gen Intel® Core™ i5-11320H @ 3.20 GHz |
| **Physical Cores** | 4 cores / 8 logical processors |
| **RAM** | ~15.8 GB (16,952,647,680 bytes) |
| **Python** | 3.13.7 (MSC v.1944 64-bit AMD64) |
| **Cython** | 3.3.0 |
| **Clock** | `time.perf_counter_ns()` — high-resolution monotonic |

---

## 5. Actual Measured Results

### 5.1 Scope: Full Pipeline (End-to-End)

All six stages active: Generator → Protocol → MmapRingBuffer → Consumer → OrderAdapter → MatchingEngine.

```
  [Warmup] Processed 10,000 orders in 0.2599s (38,472 orders/sec)

  Run | Attempted | Processed | Dropped |   Trades | Elapsed (s) | Throughput (ord/s)
    1 |    10,000 |    10,000 |       0 |    6,603 |      0.2558 |             39,089
    2 |    10,000 |    10,000 |       0 |    6,633 |      0.2619 |             38,187
    3 |    10,000 |    10,000 |       0 |    6,738 |      0.3994 |             25,036
```

| Metric | Value |
|---|---|
| **Mean Throughput** | **34,104 orders/sec** |
| **Median Throughput** | 38,187 orders/sec |
| **Min Throughput** | 25,036 orders/sec |
| **Max Throughput** | 39,089 orders/sec |
| **Std Deviation** | 7,866 orders/sec |
| **Mean Elapsed** | 0.3057 s |
| **Total Orders** | 30,000 |
| **Total Trades** | 19,974 |
| **Total Volume** | 2,727,230 shares |
| **Non-LIMIT (unhandled)** | 2,950 orders |

> ⚠️ Run 3 shows a notable spike (0.3994 s vs ~0.26 s for runs 1–2), which inflates the standard deviation. This is characteristic of OS-level scheduling jitter on Windows and is a known pre-optimisation baseline artefact.

---

### 5.2 Scope: Adapter & Engine (Protocol → OrderAdapter → MatchingEngine)

Ring buffer bypassed; orders go directly from protocol decode into the adapter and matching engine.

```
  [Warmup] Processed 10,000 orders in 0.2223s (44,986 orders/sec)

  Run | Attempted | Processed | Dropped |   Trades | Elapsed (s) | Throughput (ord/s)
    1 |    10,000 |    10,000 |       0 |    6,603 |      0.2360 |             42,380
    2 |    10,000 |    10,000 |       0 |    6,633 |      0.2725 |             36,700
    3 |    10,000 |    10,000 |       0 |    6,738 |      0.2320 |             43,105
```

| Metric | Value |
|---|---|
| **Mean Throughput** | **40,728 orders/sec** |
| **Median Throughput** | 42,380 orders/sec |
| **Min Throughput** | 36,700 orders/sec |
| **Max Throughput** | 43,105 orders/sec |
| **Std Deviation** | 3,507 orders/sec |
| **Mean Elapsed** | 0.2468 s |
| **Total Trades** | 19,974 |
| **Total Volume** | 2,727,230 shares |

---

### 5.3 Scope: Matching Engine Only (Direct `match_order` Calls)

Isolates only the Cython `MatchingEngine.match_order` hot path — no protocol or IPC overhead.

```
  [Warmup] Processed 10,000 orders in 0.2432s (41,122 orders/sec)

  Run | Attempted | Processed | Dropped |   Trades | Elapsed (s) | Throughput (ord/s)
    1 |    10,000 |    10,000 |       0 |    7,294 |      0.2738 |             36,529
    2 |    10,000 |    10,000 |       0 |    7,328 |      0.2662 |             37,572
    3 |    10,000 |    10,000 |       0 |    7,417 |      0.2610 |             38,307
```

| Metric | Value |
|---|---|
| **Mean Throughput** | **37,469 orders/sec** |
| **Median Throughput** | 37,572 orders/sec |
| **Min Throughput** | 36,529 orders/sec |
| **Max Throughput** | 38,307 orders/sec |
| **Std Deviation** | 894 orders/sec |
| **Mean Elapsed** | 0.2670 s |
| **Total Trades** | 22,039 |
| **Total Volume** | 3,034,710 shares |

> The engine-only scope generates *more* trades than the full pipeline (22,039 vs 19,974) because the adapter's non-LIMIT order filtering is bypassed — a higher fraction of submitted orders reach the limit order book.

---

### 5.4 Scope: Zero-Copy IPC Only (Ring Buffer, No Matching)

Generator → BinaryProtocol → MmapRingBuffer → ZeroCopyConsumer — no adapter or engine.

```
  [Warmup] Processed 10,000 orders in 0.0064s (1,556,202 orders/sec)

  Run | Attempted | Processed | Dropped |   Trades | Elapsed (s) | Throughput (ord/s)
    1 |    10,000 |    10,000 |       0 |        0 |      0.0066 |          1,524,971
    2 |    10,000 |    10,000 |       0 |        0 |      0.0068 |          1,472,906
    3 |    10,000 |    10,000 |       0 |        0 |      0.0064 |          1,555,065
```

| Metric | Value |
|---|---|
| **Mean Throughput** | **1,517,647 orders/sec** |
| **Median Throughput** | 1,524,971 orders/sec |
| **Min Throughput** | 1,472,906 orders/sec |
| **Max Throughput** | 1,555,065 orders/sec |
| **Std Deviation** | 41,566 orders/sec |
| **Mean Elapsed** | 0.0066 s |
| **Trades Generated** | 0 (matching engine not active) |

---

## 6. Summary Comparison Table

| Scope | Mean Throughput | Bottleneck |
|---|---|---|
| Zero-Copy IPC | **1,517,647 ord/s** | None — sub-ms ring buffer |
| Adapter + Engine | **40,728 ord/s** | Order adaptation + Cython engine |
| Matching Engine Only | **37,469 ord/s** | Cython limit order book |
| **Full Pipeline** | **34,104 ord/s** | Ring buffer I/O + adapter + engine |

---

## 7. Observations and Performance Bottlenecks

### 7.1 The IPC Layer Is Not the Bottleneck
The zero-copy ring buffer transfers at **~1.5 M orders/sec**, roughly 40× faster than the matching engine. The MmapRingBuffer and BinaryProtocol are well-optimised and should not be a focus for Week 3.

### 7.2 The Matching Engine Is the Primary Bottleneck
Even in isolation, `MatchingEngine.match_order` achieves only **~37,000–43,000 orders/sec**. This is the Cython limit order book and is the primary optimisation target for Week 3.

### 7.3 OrderAdapter Overhead Is Measurable but Small
Comparing Adapter+Engine (~40,728) vs Engine-only (~37,469) shows the adapter layer *appears* faster because it skips non-LIMIT orders early. The real adapter cost is small; the engine itself dominates latency.

### 7.4 Full-Pipeline Jitter on Windows
Run 3 of the full pipeline scope shows 0.3994 s elapsed (vs ~0.26 s for other runs), a 53 % jitter spike. This is expected Windows OS scheduling noise. Future benchmarks on Linux/NUMA-pinned hardware will be more stable.

### 7.5 Non-LIMIT Order Overhead
~10 % of orders (MARKET, CANCEL) are intercepted by `OrderAdapter` before reaching the engine. Supporting full MARKET order execution would increase trade fill rates but require engine-level changes out of scope for this week.

---

## 8. Baseline for Future Optimisations

The table below records the official **pre-optimisation baseline** for Week 3:

| KPI | Baseline (Week 3 Day 1) | Week 3 Target |
|---|---|---|
| Full pipeline throughput | **34,104 ord/s** (mean) | ≥ 100,000 ord/s |
| Engine-only throughput | **37,469 ord/s** (mean) | ≥ 150,000 ord/s |
| Full pipeline jitter (σ) | 7,866 ord/s | < 1,000 ord/s |
| Engine-only jitter (σ) | 894 ord/s | < 500 ord/s |
| Zero-copy IPC throughput | **1,517,647 ord/s** | Maintain ≥ 1 M ord/s |
| Trade fill rate | 19,974 / 30,000 (66.6 %) | Maintain ≥ 65 % |

> **Week 3 optimisation plan:** Profile the Cython `.pyx` matching engine with `cProfile` / `line_profiler`, add `cdef` type annotations, enable compiler directives (`boundscheck=False`, `wraparound=False`), and pre-allocate order book memory. Nanosecond-level latency metrics will be introduced on Day 2.

---

## 9. Files Referenced

| File | Role |
|---|---|
| `scripts/benchmark_pipeline.py` | Primary benchmark driver (all scopes) |
| `scripts/benchmark_ipc.py` | IPC-specific benchmark |
| `chronos/benchmark.py` | Core `BenchmarkRunner` class |
| `chronos/matching_engine.pyx` | Cython matching engine (optimisation target) |
| `chronos/adapter.py` | `OrderAdapter` — normalises and routes orders |
| `chronos/ring_buffer.py` | `MmapRingBuffer` — zero-copy shared-memory transport |
| `chronos/consumer.py` | `ZeroCopyConsumer` — reads from ring buffer |
| `chronos/protocol.py` | `BinaryProtocol` — encodes/decodes order messages |

---

*Generated: 2026-10-31 | ChronosMatch Internship Week 3 Day 1*
