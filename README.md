# ChronosMatch: Zero-Copy High-Frequency Trading Engine

ChronosMatch is a Python-based trading-engine project exploring low-latency order processing through binary serialization, memory-mapped inter-process communication, a Cython matching engine, and performance benchmarking.

The project is designed to demonstrate how orders can move through a multi-stage processing pipeline while minimizing serialization and communication overhead.

## Project Features

- **Binary order protocol:** Fixed-size, 32-byte order messages.
- **Memory-mapped ring buffer:** Single-producer, single-consumer (SPSC) communication architecture.
- **Market-data firehose:** Synthetic order generation for testing and benchmarking.
- **Order consumer and adapter:** Reads orders from the ring buffer and translates them for the matching engine.
- **Cython matching engine:** Limit Order Book implementation designed around price-time priority.
- **Terminal dashboard:** Curses-based market summary, order-book display, and performance monitoring interface.
- **Pipeline benchmarking:** Configurable benchmarks for individual stages and the complete order-processing pipeline.
- **Automated tests:** Protocol, ring-buffer, matching-engine, dashboard, and integration coverage.

## Architecture

The intended order-processing flow is:

```text
Synthetic Market Feed
        |
        v
   Binary Protocol
        |
        v
 Memory-Mapped Ring Buffer
        |
        v
 Consumer / Order Adapter
        |
        v
 Cython Matching Engine
        |
        v
 Order Processing Results
```

The benchmark runner can measure different portions of this pipeline.

### Main Components

| Component | Responsibility |
|---|---|
| `chronos/firehose.py` | Synthetic order-feed generation |
| `chronos/protocol.py` | Binary order serialization and deserialization |
| `chronos/ring_buffer.py` | Ring-buffer communication |
| `chronos/consumer.py` | Order consumption and processing |
| `chronos/adapter.py` | Translation between incoming orders and the matching engine |
| `chronos/matching_engine.pyx` | Cython-based matching engine |
| `chronos/benchmark.py` | Benchmark configuration, execution, and reporting |
| `chronos/dashboard.py` | Terminal dashboard and display logic |

## Technology Stack

- Python
- Cython
- `struct` and binary data handling
- Memory-mapped inter-process communication
- `curses` terminal interface
- `pytest` and `pytest-asyncio`
- Windows C++ build tools for compiling the Cython extension

## Prerequisites

- Python installed and available through the terminal
- Git
- Cython and the Python dependencies listed in `requirements.txt`
- On Windows, Microsoft C++ Build Tools with the MSVC compiler to build the native extension

## Installation and Setup

### 1. Clone the repository

```powershell
git clone https://github.com/shamstabrez23015-lab/ChronosMatch-Internship.git
cd ChronosMatch-Internship
```

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, follow your environment's PowerShell execution-policy guidance rather than changing system-wide security settings unnecessarily.

### 3. Install the dependencies

```powershell
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

### 4. Build the Cython matching engine

```powershell
python setup.py build_ext --inplace
```

This compiles `chronos/matching_engine.pyx` into a platform-specific extension that Python can import.

If compilation fails on Windows, check that the required Microsoft C++ Build Tools are installed and available.

**Important:** The generated `.pyd` file depends on the Python version and platform. Rebuild it in your own environment when necessary.

## Running the Project

### Run the consumer and market feed

For the producer/consumer demonstration, open two terminals and activate the same project's virtual environment in both.

Terminal 1 — start the consumer:

```powershell
python scripts/run_consumer.py
```

Terminal 2 — start the market feed:

```powershell
python scripts/run_firehose.py
```

Review the terminal output to confirm that orders are being produced and processed.

### Run the terminal dashboard

```powershell
python scripts/run_dashboard.py
```

The dashboard uses a terminal interface and requires a compatible interactive terminal.

To print a dashboard frame without entering interactive curses mode:

```powershell
python scripts/run_dashboard.py --non-interactive
```

To configure the refresh interval:

```powershell
python scripts/run_dashboard.py --refresh-ms 100
```

The refresh interval is specified in milliseconds.

**Dashboard note:** The dashboard includes demonstration order-book data and placeholder/sample fields. Its event-interval latency metrics measure the spacing between dashboard processing-recording events; they should not be interpreted as full end-to-end order-processing latency.

## Pipeline Benchmarking

The pipeline benchmark runner supports configurable order counts, repetitions, warmup runs, batch sizes, and benchmark scopes.

### Run a standard pipeline benchmark

```powershell
python scripts/benchmark_pipeline.py --orders 10000 --repeats 3
```

### Run a larger benchmark with LIMIT orders

```powershell
python scripts/benchmark_pipeline.py --orders 50000 --repeats 5 --limit-only
```

### Benchmark the adapter and matching engine

```powershell
python scripts/benchmark_pipeline.py --scope adapter-engine --orders 20000
```

### Export benchmark results as JSON

```powershell
python scripts/benchmark_pipeline.py --orders 10000 --json
```

Additional options can be inspected with:

```powershell
python scripts/benchmark_pipeline.py --help
```

Benchmark results depend on the machine, Python version, compiler, configuration, order count, and workload. Run the benchmark in the target environment before reporting performance figures. Do not treat older measurements as current results.

## Testing

Run the complete test suite from the repository root:

```powershell
python -m pytest -v
```

For a concise summary:

```powershell
python -m pytest -q
```

### Latest verified test result

The latest recorded run in the development environment reported:

```text
645 passed in 1.68s
```

This is a snapshot of that test run, not a guarantee that every future environment or code revision will produce the same result.

## Repository Structure

```text
ChronosMatch-Internship/
├── chronos/
│   ├── __init__.py
│   ├── adapter.py
│   ├── benchmark.py
│   ├── config.py
│   ├── consumer.py
│   ├── dashboard.py
│   ├── firehose.py
│   ├── matching_engine.pyx
│   ├── protocol.py
│   └── ring_buffer.py
├── scripts/
│   ├── benchmark_ipc.py
│   ├── benchmark_pipeline.py
│   ├── run_consumer.py
│   ├── run_dashboard.py
│   └── run_firehose.py
├── tests/
├── requirements.txt
├── setup.py
└── README.md
```

The compiled matching-engine extension and generated build files may also appear locally after building.

## Team Development Workflow

ChronosMatch uses separate branches for team development.

- `Faizan-branch` — integration, documentation, and related project work
- `Albert-branch` — matching-engine and integration work
- `Taniya-branch` — dashboard and latency-monitoring work
- `main` — reviewed and merged project changes

Recommended workflow:

1. Make changes on your assigned branch.
2. Run the relevant tests.
3. Commit and push your work to that branch.
4. Open a pull request into `main`.
5. Review and merge the pull request after checks are complete.

Example commands for your own branch:

```powershell
git status
git add README.md
git commit -m "Update project documentation"
git push origin Faizan-branch
```

Only stage `README.md` for the documentation commit so unrelated code changes are not included.

## Development Notes

- Rebuild the Cython extension after changing `matching_engine.pyx`.
- Run the tests after integration changes.
- Record benchmark settings alongside measured results so comparisons are meaningful.
- Distinguish demonstration dashboard values from measurements produced by the actual processing pipeline.
- Avoid committing virtual environments, temporary build outputs, or platform-specific generated files unless the project explicitly requires them.

## Project Goal

ChronosMatch aims to provide a practical demonstration of binary order processing, efficient inter-process communication, a Cython-based matching engine, and reproducible performance measurement in a collaborative Python development project.
