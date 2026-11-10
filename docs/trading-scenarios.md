# ChronosMatch — Reusable Deterministic Trading Scenarios & Verification Framework

## 1. Executive Summary

In high-frequency trading (HFT) matching engines, deterministic execution and sub-microsecond latency tracking are foundational. A single rounding discrepancy, priority inversion, or unhandled partial fill can result in order book corruption, regulatory violation, or severe financial loss.

This document details the **Reusable Deterministic Trading Scenarios and Verification Framework** implemented for **Week 3, Day 5** of the **ChronosMatch** project. Building upon the static fixtures created in Week 2, this framework provides executable, parameterized trading scenarios that validate the live Cython `MatchingEngine`, `OrderAdapter`, binary order protocol, and nanosecond latency telemetry pipeline.

---

## 2. Core Scenario Categories

The framework formalizes five mandatory trading categories to test every operational regime of the matching engine:

```
+---------------------------------------------------------------------------------------------------------+
| Category Identifier           | Focus Area                                 | Canonical Scenarios        |
+---------------------------------------------------------------------------------------------------------+
| successful_matching           | Exact matches, crossed markets, full fills | 1, 2, 4, 5, 6, 7, 8, 9     |
| partial_fills                 | Buy-larger, sell-larger, multi-order fills | 4, 5, 7, 8, 9              |
| multiple_price_levels         | Multi-level book sweeps (depth traversal)  | 8, 9                       |
| non_crossing                  | Positive spreads, empty book states        | 3, 10                      |
| unmatched_orders              | Passive resting orders with zero matches   | 3, 10                      |
+---------------------------------------------------------------------------------------------------------+
```

### 2.1 Category Breakdown

1. **Successful Matching (`CATEGORY_SUCCESSFUL_MATCHING`)**:
   - Focuses on orders that meet crossing conditions ($\text{Bid} \ge \text{Ask}$) and successfully execute trades.
   - Asserts positive executed volume ($\text{volume} > 0$), valid trade counts, and accurate maker prices.
2. **Partial Fills (`CATEGORY_PARTIAL_FILLS`)**:
   - Focuses on unbalanced order sizes where one counterparty's quantity exceeds the other.
   - Asserts exact trade size, complete exhaustion of the smaller order, and correct resting residual quantity on the book for the larger order.
3. **Multiple Price Levels (`CATEGORY_MULTIPLE_PRICE_LEVELS`)**:
   - Focuses on aggressive orders large enough to consume multiple price tiers in the book.
   - Asserts depth traversal in strict price priority (highest bid first for sell sweeps, lowest ask first for buy sweeps), executing distinct trades at the resting maker prices of each tier.
4. **Non-Crossing Orders (`CATEGORY_NON_CROSSING`)**:
   - Focuses on market conditions where $\text{Best Bid} < \text{Best Ask}$ (wide bid-ask spread) or when orders enter an empty book.
   - Asserts zero trade execution ($\text{trades} = 0$, $\text{volume} = 0$), non-crossing metric updates, and resting book placement.
5. **Unmatched Orders (`CATEGORY_UNMATCHED_ORDERS`)**:
   - Focuses on passive liquidity provision where orders rest on the book without encountering matching counterparties.
   - Asserts quantity conservation ($\text{Remaining Quantity} = \text{Initial Quantity}$) and correct book priority indexing.

---

## 3. Order Protocol & Matching Engine Principles

### 3.1 Binary Protocol & Side Conventions
The framework interfaces directly with the binary protocol definitions (`chronos.protocol`):
* `Side.BUY = 1` (Bid side)
* `Side.SELL = 2` (Ask side)
* 32-byte zero-copy struct serialization (`pack()` / `unpack_order_raw()`).

### 3.2 Integer Cent Price Representation
To eliminate floating-point rounding errors and non-associative floating-point addition in Cython, all internal book calculations use **integer cents**:
$$\text{price\_cents} = \text{round}(\text{price} \times 100.0)$$
* Example: `$100.00` $\rightarrow$ `10000` cents
* Example: `$205.50` $\rightarrow$ `20550` cents

### 3.3 Strict Price-Time Priority (FIFO)
1. **Price Priority**:
   - **Bids (BUY)**: Sorted descending (highest price executes first).
   - **Asks (SELL)**: Sorted ascending (lowest price executes first).
2. **Time Priority**:
   - At identical price levels, orders are queued in chronological arrival sequence determined by `timestamp_ns` and engine arrival sequence.

### 3.4 Maker Price Rule
When an aggressive incoming order crosses with resting liquidity, the **execution price is determined by the resting (maker) order**:
* If a BUY order is already resting at `$105.00` and an incoming SELL arrives at `$100.00`, the trade executes at the maker price of **`$105.00`**.
* If a SELL order is resting at `$200.00` and an incoming BUY arrives at `$205.00`, the trade executes at the maker price of **`$200.00`**.

### 3.5 Quantity Conservation Invariant
For every order $i$ throughout matching:
$$\text{Initial Quantity}_i = \sum \text{Executed Quantity}_{i, k} + \text{Remaining Quantity}_i$$

---

## 4. Complete Catalog of Reusable Trading Scenarios

The suite contains exactly ten canonical scenarios, maintaining strict backward compatibility with existing integration tests:

---

### Scenario 1: Exact-Price BUY and SELL Match
* **Identifier**: `scenario_1_exact_match`
* **Categories**: `successful_matching`
* **Purpose**: Verifies that identical prices and quantities match completely with zero book residue.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **101** | BUY | $100.00 | 10000 | 50 | 1,000,000,000 | 1001 |
| **102** | SELL | $100.00 | 10000 | 50 | 1,000,001,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 101 rests on the bid book at $100.00 (qty 50).
  2. Order 102 arrives on the ask side at $100.00 (qty 50).
  3. Crossing condition satisfied ($100.00 \ge 100.00$). Both orders match fully.
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `101`, `best_sell_id`: `102`
  - `total_matched_quantity`: `50`
  - `remaining_quantities`: `{101: 0, 102: 0}`
  - `trades`:
    1. Buy 101 vs Sell 102 @ $100.00, qty 50

---

### Scenario 2: Crossed Market (BUY Price > SELL Price)
* **Identifier**: `scenario_2_crossed_market`
* **Categories**: `successful_matching`
* **Purpose**: Verifies crossed market resolution and maker price execution when bid exceeds ask.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **201** | BUY | $105.00 | 10500 | 100 | 1,000,000,000 | 1001 |
| **202** | SELL | $100.00 | 10000 | 100 | 1,000,001,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 201 rests on bid book at $105.00 (qty 100).
  2. Order 202 arrives on ask side at $100.00 (qty 100).
  3. Crossing condition met ($105.00 \ge 100.00$).
  4. Execution occurs at resting maker price of $105.00.
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `201`, `best_sell_id`: `202`
  - `total_matched_quantity`: `100`
  - `remaining_quantities`: `{201: 0, 202: 0}`
  - `trades`:
    1. Buy 201 vs Sell 202 @ $105.00, qty 100

---

### Scenario 3: Non-Crossing Wide Spread (No Trade)
* **Identifier**: `scenario_3_no_trade_wide_spread`
* **Categories**: `non_crossing`, `unmatched_orders`
* **Purpose**: Verifies that non-crossing orders ($\text{Bid} < \text{Ask}$) produce zero trades and rest passively on the book.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **301** | BUY | $95.00 | 9500 | 100 | 1,000,000,000 | 1001 |
| **302** | SELL | $105.00 | 10500 | 100 | 1,000,001,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 301 rests on bid book at $95.00.
  2. Order 302 arrives on ask side at $105.00.
  3. No crossing ($95.00 < 105.00$, spread = $10.00). Both orders rest with full initial quantity.
* **Expected Output**:
  - `has_crossing`: `False`
  - `best_buy_id`: `301`, `best_sell_id`: `302`
  - `total_matched_quantity`: `0`
  - `remaining_quantities`: `{301: 100, 302: 100}`
  - `trades`: `()`

---

### Scenario 4: Partial Fill with BUY Quantity Larger
* **Identifier**: `scenario_4_partial_fill_buy_larger`
* **Categories**: `successful_matching`, `partial_fills`
* **Purpose**: Verifies partial fill when bid quantity exceeds ask quantity, leaving resting bid residue.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **401** | BUY | $500.00 | 50000 | 100 | 1,000,000,000 | 1001 |
| **402** | SELL | $500.00 | 50000 | 40 | 1,000,001,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 401 rests on bid book (qty 100).
  2. Order 402 arrives on ask side (qty 40).
  3. Matched quantity is $\min(100, 40) = 40$.
  4. Order 402 is fully filled (0 remaining). Order 401 remains resting with $100 - 40 = 60$ shares.
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `401`, `best_sell_id`: `402`
  - `total_matched_quantity`: `40`
  - `remaining_quantities`: `{401: 60, 402: 0}`
  - `trades`:
    1. Buy 401 vs Sell 402 @ $500.00, qty 40

---

### Scenario 5: Partial Fill with SELL Quantity Larger
* **Identifier**: `scenario_5_partial_fill_sell_larger`
* **Categories**: `successful_matching`, `partial_fills`
* **Purpose**: Verifies partial fill when ask quantity exceeds bid quantity, leaving resting ask residue.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **501** | BUY | $250.00 | 25000 | 30 | 1,000,000,000 | 1001 |
| **502** | SELL | $250.00 | 25000 | 80 | 1,000,001,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 501 rests on bid book (qty 30).
  2. Order 502 arrives on ask side (qty 80).
  3. Matched quantity is $\min(30, 80) = 30$.
  4. Order 501 is fully filled (0 remaining). Order 502 remains resting with $80 - 30 = 50$ shares.
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `501`, `best_sell_id`: `502`
  - `total_matched_quantity`: `30`
  - `remaining_quantities`: `{501: 0, 502: 50}`
  - `trades`:
    1. Buy 501 vs Sell 502 @ $250.00, qty 30

---

### Scenario 6: Exact Full Fill with Equal Quantities
* **Identifier**: `scenario_6_exact_full_fill`
* **Categories**: `successful_matching`
* **Purpose**: Verifies full fill with clean zero residue at intermediate price levels.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **601** | BUY | $300.00 | 30000 | 75 | 1,000,000,000 | 1001 |
| **602** | SELL | $300.00 | 30000 | 75 | 1,000,001,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 601 rests on bid book (qty 75).
  2. Order 602 arrives on ask side (qty 75).
  3. Exact match: 75 shares execute at $300.00, fully clearing both orders.
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `601`, `best_sell_id`: `602`
  - `total_matched_quantity`: `75`
  - `remaining_quantities`: `{601: 0, 602: 0}`
  - `trades`:
    1. Buy 601 vs Sell 602 @ $300.00, qty 75

---

### Scenario 7: FIFO Priority at Identical Price Level
* **Identifier**: `scenario_7_fifo_same_price`
* **Categories**: `successful_matching`, `partial_fills`
* **Purpose**: Verifies time priority (FIFO) when multiple orders share the same limit price.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **701** | BUY | $150.00 | 15000 | 40 | 1,000,000,000 | 1001 |
| **702** | BUY | $150.00 | 15000 | 60 | 1,000,001,000 | 1001 |
| **703** | SELL | $150.00 | 15000 | 50 | 1,000,002,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 701 rests at $150.00 (qty 40, $t = 1.0\text{s}$).
  2. Order 702 queues behind 701 at $150.00 (qty 60, $t = 1.000001\text{s}$).
  3. Order 703 arrives to sell 50 shares.
  4. FIFO allocates the first 40 shares to Order 701 (fully filling it).
  5. The remaining 10 shares are allocated to Order 702 (partially filling it, leaving 50 resting shares).
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `701`, `best_sell_id`: `703`
  - `prioritized_buy_ids`: `(701, 702)`
  - `total_matched_quantity`: `50`
  - `remaining_quantities`: `{701: 0, 702: 50, 703: 0}`
  - `trades`:
    1. Buy 701 vs Sell 703 @ $150.00, qty 40
    2. Buy 702 vs Sell 703 @ $150.00, qty 10

---

### Scenario 8: Multiple BUY Price Levels (Highest Price Priority)
* **Identifier**: `scenario_8_price_priority_buy`
* **Categories**: `successful_matching`, `partial_fills`, `multiple_price_levels`
* **Purpose**: Verifies price priority over arrival time on the bid side, sweeping across multiple price levels.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **801** | BUY | $100.00 | 10000 | 50 | 1,000,000,000 | 1001 |
| **802** | BUY | $102.00 | 10200 | 30 | 1,000,001,000 | 1001 |
| **803** | SELL | $100.00 | 10000 | 40 | 1,000,002,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 801 rests at $100.00.
  2. Order 802 arrives later at higher price $102.00, jumping ahead in priority.
  3. Order 803 arrives to sell 40 shares at $100.00.
  4. First level swept: Order 802 ($102.00) fully filled for 30 shares at maker price $102.00.
  5. Second level swept: Order 801 ($100.00) partially filled for 10 shares at maker price $100.00 (leaving 40 shares resting).
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `802`, `best_sell_id`: `803`
  - `prioritized_buy_ids`: `(802, 801)`
  - `total_matched_quantity`: `40`
  - `remaining_quantities`: `{801: 40, 802: 0, 803: 0}`
  - `trades`:
    1. Buy 802 vs Sell 803 @ $102.00, qty 30
    2. Buy 801 vs Sell 803 @ $100.00, qty 10

---

### Scenario 9: Multiple SELL Price Levels (Lowest Price Priority)
* **Identifier**: `scenario_9_price_priority_sell`
* **Categories**: `successful_matching`, `partial_fills`, `multiple_price_levels`
* **Purpose**: Verifies price priority over arrival time on the ask side, sweeping across multiple price levels.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) | Symbol ID |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **901** | SELL | $205.00 | 20500 | 40 | 1,000,000,000 | 1001 |
| **902** | SELL | $200.00 | 20000 | 25 | 1,000,001,000 | 1001 |
| **903** | BUY | $205.00 | 20500 | 50 | 1,000,002,000 | 1001 |

* **Execution Walkthrough**:
  1. Order 901 rests at $205.00.
  2. Order 902 arrives later at lower price $200.00, jumping ahead in priority.
  3. Order 903 arrives to buy 50 shares at $205.00.
  4. First level swept: Order 902 ($200.00) fully filled for 25 shares at maker price $200.00.
  5. Second level swept: Order 901 ($205.00) partially filled for 25 shares at maker price $205.00 (leaving 15 shares resting).
* **Expected Output**:
  - `has_crossing`: `True`
  - `best_buy_id`: `903`, `best_sell_id`: `902`
  - `prioritized_sell_ids`: `(902, 901)`
  - `total_matched_quantity`: `50`
  - `remaining_quantities`: `{901: 15, 902: 0, 903: 0}`
  - `trades`:
    1. Buy 903 vs Sell 902 @ $200.00, qty 25
    2. Buy 903 vs Sell 901 @ $205.00, qty 25

---

### Scenario 10: Empty Order Book (Zero Orders)
* **Identifier**: `scenario_10_empty_order_book`
* **Categories**: `non_crossing`, `unmatched_orders`
* **Purpose**: Verifies engine boundary condition on uninitialized or cleared book.
* **Input Orders**: `()` (Empty)
* **Execution Walkthrough**:
  1. Engine contains zero bids and zero asks.
  2. No crossing can occur; zero trades executed.
* **Expected Output**:
  - `has_crossing`: `False`
  - `best_buy_id`: `None`, `best_sell_id`: `None`
  - `prioritized_buy_ids`: `()`
  - `prioritized_sell_ids`: `()`
  - `total_matched_quantity`: `0`
  - `remaining_quantities`: `{}`
  - `trades`: `()`

---

## 5. Programmatic Fixture Architecture (`tests/trading_scenarios.py`)

### 5.1 Immutable Data Structures

```python
@dataclass(frozen=True)
class ScenarioOrder:
    order_id: int
    side: int                          # 1 = BUY, 2 = SELL
    price: float                       # e.g. 500.00
    quantity: int
    timestamp_ns: int = 0
    symbol_id: int = 1001
    order_type: int = 1                # 1 = LIMIT

    @property
    def price_cents(self) -> int:
        return int(round(self.price * 100.0))

    def to_protocol_order(self) -> Order: ...
    def pack(self) -> bytes: ...
```

```python
@dataclass(frozen=True)
class ExpectedTrade:
    buy_order_id: int
    sell_order_id: int
    execution_price: float
    trade_quantity: int

    @property
    def execution_price_cents(self) -> int:
        return int(round(self.execution_price * 100.0))

    def matches_trade_result(self, trade: Any) -> bool:
        """Compares buy_order_id, sell_order_id, executed_quantity, and execution_price."""
```

```python
@dataclass(frozen=True)
class ExpectedOutcome:
    has_crossing: bool
    best_buy_id: Optional[int]
    best_sell_id: Optional[int]
    prioritized_buy_ids: Tuple[int, ...]
    prioritized_sell_ids: Tuple[int, ...]
    total_matched_quantity: int
    remaining_quantities: Dict[int, int]
    trades: Tuple[ExpectedTrade, ...] = ()
```

```python
@dataclass(frozen=True)
class TradingScenario:
    name: str
    description: str
    orders: Tuple[ScenarioOrder, ...]
    expected: ExpectedOutcome
    categories: Tuple[str, ...] = ()

    def execute_in_engine(self, engine: MatchingEngine) -> List[TradeResult]: ...
    def execute_in_adapter(self, adapter: OrderAdapter) -> List[TradeResult]: ...
    def verify_execution(self, trades: List[TradeResult], engine: Optional[MatchingEngine] = None) -> bool: ...
```

### 5.2 Scenario Execution & Verification Helpers

The Week 3 additions turn scenarios into active test harnesses:

1. **`scenario.execute_in_engine(engine)`**:
   Sequentially submits each order via `engine.match_order(...)` and aggregates all generated `TradeResult` instances.
2. **`scenario.execute_in_adapter(adapter)`**:
   Dispatches each scenario order through `adapter.dispatch_raw_order(ord.to_protocol_order())`, exercising binary protocol conversion, dispatching, and latency tracking.
3. **`scenario.verify_execution(trades, engine=None)`**:
   Performs a 4-point verification against `scenario.expected`:
   - Checks total executed volume ($\sum \text{qty} == \text{total\_matched\_quantity}$).
   - Checks exact trade count ($\text{len}(trades) == \text{len}(expected.trades)$).
   - Validates individual trade attributes (`buy_order_id`, `sell_order_id`, `trade_quantity`, `execution_price`).
   - Validates resting order book residue if `engine` is passed.

### 5.3 Category Query Helpers

```python
get_all_scenarios() -> List[TradingScenario]
get_scenario(name: str) -> TradingScenario
get_scenarios_by_category(category: str) -> List[TradingScenario]
get_successful_matching_scenarios() -> List[TradingScenario]
get_partial_fill_scenarios() -> List[TradingScenario]
get_multiple_price_levels_scenarios() -> List[TradingScenario]
get_non_crossing_scenarios() -> List[TradingScenario]
get_unmatched_scenarios() -> List[TradingScenario]
```

---

## 6. Week 3 Latency & Telemetry Integration

When scenarios are executed through the `OrderAdapter`, the Week 3 trade execution timestamp and latency tracker capture telemetry for every trade:

1. **Trade Timestamps**:
   - `trade.entry_timestamp_ns`: High-resolution start of dispatch.
   - `trade.exit_timestamp_ns`: Timestamp recorded when fill finishes.
   - `trade.latency_ns`: $\text{exit\_timestamp\_ns} - \text{entry\_timestamp\_ns} \ge 0$.
   - `trade.latency_us`: Latency in microseconds ($\text{latency\_ns} / 1000.0$).
2. **Trade Latency Metrics**:
   - Verified via `adapter.get_trade_latency_snapshot()`:
     * `avg_latency_ns`, `min_latency_ns`, `max_latency_ns`, `trade_count`.
3. **Non-Crossing Order Telemetry**:
   - Non-crossing orders emit a `TradeExecutionEvent` with `matched = False`, `volume_matched = 0`, and `trades = []`, incrementing `adapter.stats.non_crossing_orders`.

---

## 7. Automated Test Suite (`tests/test_trading_scenarios.py`)

The test suite contains **238 automated tests** structured across 12 test classes:

```
+------------------------------------------------------+-------------------------------------------------+
| Test Class                                           | Responsibility                                  |
+------------------------------------------------------+-------------------------------------------------+
| TestScenarioRegistry                                 | Registry lookup, unique names, copy semantics   |
| TestScenarioOrderProtocolValidation                  | Side values, cent conversion, positive price    |
| TestOrderQuantities                                  | Strictly positive quantities, non-zero values   |
| TestCrossingLogic                                    | Crossing conditions, best bid/ask IDs           |
| TestFillArithmeticAndQuantities                      | Quantity conservation, fill math invariants     |
| TestNonCrossingScenarios                             | Zero matched quantity on spread / empty books   |
| TestPrioritySequence                                 | Price priority and FIFO queueing order          |
| TestBinaryProtocolRoundtrip                          | 32-byte struct pack/unpack roundtrip fidelity   |
| TestScenarioCategorization                           | Category tags, filtering APIs, index coverage   |
| TestScenarioExecutionHelpers                         | execute_in_engine, execute_in_adapter, verify    |
| TestCategoryBehaviorRequirements                     | Specific requirements for all 5 categories      |
| TestTradingScenariosLatencyIntegration               | Nanosecond timestamps, latency tracker metrics  |
+------------------------------------------------------+-------------------------------------------------+
```

### Running the Tests

```bash
# Run trading scenario validation tests
python -m pytest tests/test_trading_scenarios.py -v

# Run the complete test suite (excluding network firehose)
python -m pytest --ignore=tests/test_firehose.py
```
