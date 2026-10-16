# ChronosMatch — Deterministic Trading Scenarios & Reusable Test Fixtures

## 1. Executive Summary

In high-frequency trading (HFT) matching engines, deterministic execution and microsecond-level accuracy are non-negotiable requirements. A single rounding defect, race condition, or priority inversion can result in erroneous trades, financial loss, or exchange non-compliance.

This document details the **Deterministic Trading Scenarios and Reusable Test Fixtures** introduced during **Week 2, Day 5** of the **ChronosMatch** project. These fixtures provide a standardized, verified specification of order-book states, price-time priority rules, crossing conditions, and trade execution outcomes without implementing or altering the engine's core execution loop.

---

## 2. Why Deterministic Scenarios Matter in HFT

1. **Decoupled Verification**:
   - Engine developers (Albert) and dashboard developers (Taniya) need a shared, authoritative reference for expected matching behavior before trade execution logic is finalized.
2. **Precision & Quantity Conservation**:
   - Every order's lifecycle must strictly satisfy the conservation invariant:
     $$\text{Initial Quantity} = \text{Executed Quantity} + \text{Remaining Quantity}$$
3. **Reproducible Edge Cases**:
   - Scenarios simulate edge cases (e.g. crossed markets, sub-penny spread boundaries, equal timestamps broken by arrival sequence, partial fills, and empty book states) deterministically.
4. **Zero Shared-State Mutation**:
   - Reusable fixtures must be immutable so that concurrent or sequential test runs cannot pollute test inputs.

---

## 3. Core Principles & Conventions

### 3.1 Side Representation
Conforms directly to the Week 1 binary protocol (`chronos.protocol.Side`):
* `1` → **BUY** (Bid side)
* `2` → **SELL** (Ask side)

### 3.2 Price Representation: Integer Cents
The binary protocol transmits prices as 64-bit IEEE 754 floats (`double`). To eliminate floating-point rounding inaccuracies during matching, the engine represents all prices as **integer cents** (ticks of $0.01):
$$\text{price\_cents} = \text{round}(\text{price} \times 100.0)$$
* Example: `$500.00` → `50000` cents
* Example: `$102.50` → `10250` cents

### 3.3 Price-Time Priority (FIFO)
The matching engine evaluates execution priority using a strict two-tier rule:
1. **Primary Priority (Price)**:
   - For **BUY orders (bids)**: Highest price has highest priority.
   - For **SELL orders (asks)**: Lowest price has highest priority.
2. **Secondary Priority (Time / FIFO)**:
   - At identical price levels, the order that arrived earlier (smaller `timestamp_ns` or earlier engine `sequence_num`) has execution priority.

### 3.4 Crossing Condition
A crossing condition exists if and only if:
$$\text{Best BUY Price} \ge \text{Best SELL Price}$$
If either side of the order book is empty, or if $\text{Best BUY Price} < \text{Best SELL Price}$, no crossing exists and no trade can be executed.

### 3.5 Trade Execution & Fills
When an aggressive order crosses the resting order book:
* **Trade Quantity**:
  $$\text{Trade Quantity} = \min(\text{BUY Quantity}, \text{SELL Quantity})$$
* **Full Fill**: The order's entire quantity is matched; remaining quantity becomes `0`.
* **Partial Fill**: The larger order is partially executed; remaining quantity is $\text{Initial Quantity} - \text{Trade Quantity}$.
* **Execution Price**: Determined by the resting (passive) order's limit price.

---

## 4. The Ten Trading Scenarios

The suite defines ten canonical scenarios in `tests/trading_scenarios.py`:

```
+----------------------------------------------------------------------------------------------------+
| ID  | Scenario Name                        | Core Concept Verified                                 |
+----------------------------------------------------------------------------------------------------+
| 1   | scenario_1_exact_match               | Exact price match with equal quantities               |
| 2   | scenario_2_crossed_market            | BUY price higher than SELL price                      |
| 3   | scenario_3_no_trade_wide_spread      | BUY price below SELL price (no crossing, wide spread) |
| 4   | scenario_4_partial_fill_buy_larger   | Partial fill with BUY quantity > SELL quantity        |
| 5   | scenario_5_partial_fill_sell_larger  | Partial fill with SELL quantity > BUY quantity        |
| 6   | scenario_6_exact_full_fill           | Exact full fill with equal quantities                 |
| 7   | scenario_7_fifo_same_price           | Time priority (FIFO) at identical prices              |
| 8   | scenario_8_price_priority_buy        | Price priority on BUY side (highest price first)      |
| 9   | scenario_9_price_priority_sell       | Price priority on SELL side (lowest price first)      |
| 10  | scenario_10_empty_order_book         | Empty order book (zero orders, no matching)           |
+----------------------------------------------------------------------------------------------------+
```

---

### Scenario 1: Exact-Price BUY and SELL Match
* **Identifier**: `scenario_1_exact_match`
* **Description**: A resting BUY order and an incoming SELL order share the exact same limit price and equal quantities.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **101** | BUY | $100.00 | 10000 | 50 | 1,000,000,000 |
| **102** | SELL | $100.00 | 10000 | 50 | 1,000,001,000 |

* **Expected Outcome**:
  - `has_crossing`: `True` ($100.00 \ge 100.00$)
  - `best_buy_id`: `101`, `best_sell_id`: `102`
  - `total_matched_quantity`: `50`
  - `remaining_quantities`: `{101: 0, 102: 0}`
  - `trades`: 1 trade (Buy 101 vs Sell 102 @ $100.00, qty 50)

---

### Scenario 2: BUY Price Higher Than SELL Price
* **Identifier**: `scenario_2_crossed_market`
* **Description**: A crossed market where the incoming SELL order offers shares below the resting BUY limit price.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **201** | BUY | $105.00 | 10500 | 100 | 1,000,000,000 |
| **202** | SELL | $100.00 | 10000 | 100 | 1,000,001,000 |

* **Expected Outcome**:
  - `has_crossing`: `True` ($105.00 \ge 100.00$)
  - `best_buy_id`: `201`, `best_sell_id`: `202`
  - `total_matched_quantity`: `100`
  - `remaining_quantities`: `{201: 0, 202: 0}`
  - `trades`: 1 trade (Buy 201 vs Sell 202 @ $105.00 resting price, qty 100)

---

### Scenario 3: BUY Price Below SELL Price — No Trade
* **Identifier**: `scenario_3_no_trade_wide_spread`
* **Description**: The bid is lower than the ask ($95.00 vs $105.00), creating a positive $10.00 bid-ask spread. No crossing occurs and no trades execute.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **301** | BUY | $95.00 | 9500 | 100 | 1,000,000,000 |
| **302** | SELL | $105.00 | 10500 | 100 | 1,000,001,000 |

* **Expected Outcome**:
  - `has_crossing`: `False` ($95.00 < 105.00$)
  - `best_buy_id`: `301`, `best_sell_id`: `302`
  - `total_matched_quantity`: `0`
  - `remaining_quantities`: `{301: 100, 302: 100}`
  - `trades`: None

---

### Scenario 4: Partial Fill Where BUY Quantity Is Larger
* **Identifier**: `scenario_4_partial_fill_buy_larger`
* **Description**: A large BUY order (100 shares) meets a smaller SELL order (40 shares) at the same price. SELL fills completely; BUY leaves 60 resting shares.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **401** | BUY | $500.00 | 50000 | 100 | 1,000,000,000 |
| **402** | SELL | $500.00 | 50000 | 40 | 1,000,001,000 |

* **Expected Outcome**:
  - `has_crossing`: `True`
  - `best_buy_id`: `401`, `best_sell_id`: `402`
  - `total_matched_quantity`: `40`
  - `remaining_quantities`: `{401: 60, 402: 0}`
  - `trades`: 1 trade (Buy 401 vs Sell 402 @ $500.00, qty 40)

---

### Scenario 5: Partial Fill Where SELL Quantity Is Larger
* **Identifier**: `scenario_5_partial_fill_sell_larger`
* **Description**: A smaller BUY order (30 shares) meets a larger SELL order (80 shares). BUY fills completely; SELL leaves 50 resting shares.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **501** | BUY | $250.00 | 25000 | 30 | 1,000,000,000 |
| **502** | SELL | $250.00 | 25000 | 80 | 1,000,001,000 |

* **Expected Outcome**:
  - `has_crossing`: `True`
  - `best_buy_id`: `501`, `best_sell_id`: `502`
  - `total_matched_quantity`: `30`
  - `remaining_quantities`: `{501: 0, 502: 50}`
  - `trades`: 1 trade (Buy 501 vs Sell 502 @ $250.00, qty 30)

---

### Scenario 6: Exact Full Fill Where Both Quantities Are Equal
* **Identifier**: `scenario_6_exact_full_fill`
* **Description**: Both sides submit identical quantities (75 shares) at $300.00, resulting in clean execution with zero residue on either side.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **601** | BUY | $300.00 | 30000 | 75 | 1,000,000,000 |
| **602** | SELL | $300.00 | 30000 | 75 | 1,000,001,000 |

* **Expected Outcome**:
  - `has_crossing`: `True`
  - `best_buy_id`: `601`, `best_sell_id`: `602`
  - `total_matched_quantity`: `75`
  - `remaining_quantities`: `{601: 0, 602: 0}`
  - `trades`: 1 trade (Buy 601 vs Sell 602 @ $300.00, qty 75)

---

### Scenario 7: Multiple BUY Orders at the Same Price (FIFO)
* **Identifier**: `scenario_7_fifo_same_price`
* **Description**: Two BUY orders arrive at $150.00 at different timestamps. Order 701 arrived at timestamp 1s; Order 702 arrived at timestamp 2s. An incoming SELL order of 50 shares must fill Order 701 first (40 shares), then fill the remaining 10 shares from Order 702.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **701** | BUY | $150.00 | 15000 | 40 | 1,000,000,000 |
| **702** | BUY | $150.00 | 15000 | 60 | 1,000,001,000 |
| **703** | SELL | $150.00 | 15000 | 50 | 1,000,002,000 |

* **Expected Outcome**:
  - `has_crossing`: `True`
  - `best_buy_id`: `701` (earlier arrival), `best_sell_id`: `703`
  - `prioritized_buy_ids`: `(701, 702)`
  - `total_matched_quantity`: `50`
  - `remaining_quantities`: `{701: 0, 702: 50, 703: 0}`
  - `trades`:
    1. Buy 701 vs Sell 703 @ $150.00, qty 40 (Order 701 fully filled)
    2. Buy 702 vs Sell 703 @ $150.00, qty 10 (Order 702 partially filled, 50 remaining)

---

### Scenario 8: Multiple BUY Prices — Highest Price Has Priority
* **Identifier**: `scenario_8_price_priority_buy`
* **Description**: Order 801 arrives first at $100.00. Order 802 arrives later but offers a higher price of $102.00. Price priority dictates Order 802 must be matched before Order 801, overriding arrival order.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **801** | BUY | $100.00 | 10000 | 50 | 1,000,000,000 |
| **802** | BUY | $102.00 | 10200 | 30 | 1,000,001,000 |
| **803** | SELL | $100.00 | 10000 | 40 | 1,000,002,000 |

* **Expected Outcome**:
  - `has_crossing`: `True`
  - `best_buy_id`: `802` (highest price $102.00), `best_sell_id`: `803`
  - `prioritized_buy_ids`: `(802, 801)`
  - `total_matched_quantity`: `40`
  - `remaining_quantities`: `{801: 40, 802: 0, 803: 0}`
  - `trades`:
    1. Buy 802 vs Sell 803 @ $102.00, qty 30 (Order 802 fully filled)
    2. Buy 801 vs Sell 803 @ $100.00, qty 10 (Order 801 partially filled, 40 remaining)

---

### Scenario 9: Multiple SELL Prices — Lowest Price Has Priority
* **Identifier**: `scenario_9_price_priority_sell`
* **Description**: Order 901 arrives first at $205.00. Order 902 arrives later but offers a cheaper price of $200.00. Lowest sell price has top priority and must be matched before Order 901.
* **Input Orders**:

| Order ID | Side | Price ($) | Price (Cents) | Quantity | Timestamp (ns) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **901** | SELL | $205.00 | 20500 | 40 | 1,000,000,000 |
| **902** | SELL | $200.00 | 20000 | 25 | 1,000,001,000 |
| **903** | BUY | $205.00 | 20500 | 50 | 1,000,002,000 |

* **Expected Outcome**:
  - `has_crossing`: `True`
  - `best_buy_id`: `903`, `best_sell_id`: `902` (cheapest price $200.00)
  - `prioritized_sell_ids`: `(902, 901)`
  - `total_matched_quantity`: `50`
  - `remaining_quantities`: `{901: 15, 902: 0, 903: 0}`
  - `trades`:
    1. Buy 903 vs Sell 902 @ $200.00, qty 25 (Order 902 fully filled)
    2. Buy 903 vs Sell 901 @ $205.00, qty 25 (Order 901 partially filled, 15 remaining)

---

### Scenario 10: Empty Order Book — No Matching Opportunity
* **Identifier**: `scenario_10_empty_order_book`
* **Description**: A freshly initialized or cleared order book containing zero bids and zero asks.
* **Input Orders**: None (`()`)
* **Expected Outcome**:
  - `has_crossing`: `False`
  - `best_buy_id`: `None`, `best_sell_id`: `None`
  - `prioritized_buy_ids`: `()`
  - `prioritized_sell_ids`: `()`
  - `total_matched_quantity`: `0`
  - `remaining_quantities`: `{}`
  - `trades`: None

---

## 5. Python Fixture Architecture (`tests/trading_scenarios.py`)

### 5.1 Immutable Data Structures

```python
@dataclass(frozen=True)
class ScenarioOrder:
    order_id: int
    side: int  # 1 = BUY, 2 = SELL
    price: float  # e.g. 500.00
    quantity: int
    timestamp_ns: int = 0
    symbol_id: int = 1001
    order_type: int = 1

    @property
    def price_cents(self) -> int:
        return int(round(self.price * 100.0))

    def to_protocol_order(self) -> Order: ...
    def pack(self) -> bytes: ...  # 32-byte zero-copy struct
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
    trades: Tuple[ExpectedTrade, ...]
```

```python
@dataclass(frozen=True)
class TradingScenario:
    name: str
    description: str
    orders: Tuple[ScenarioOrder, ...]
    expected: ExpectedOutcome

    def load_into_engine(self, engine: MatchingEngine) -> MatchingEngine: ...
    def copy(self) -> TradingScenario: ...
```

### 5.2 Fixture Access Helpers

* `get_all_scenarios() -> List[TradingScenario]`: Returns a fresh list of isolated scenario copies.
* `get_scenario(name: str) -> TradingScenario`: Retrieves an isolated copy of a scenario by name.
* `ALL_SCENARIOS`: Immutable tuple of all 10 scenario definitions.
* `SCENARIOS_BY_NAME`: Canonical lookup dictionary mapping scenario names to definitions.

---

## 6. How Fixtures Will Be Used in Future Integration Tests

When Albert completes trade execution and order book mutations (Day 6+):

1. **Unit Verification**:
   ```python
   engine = MatchingEngine()
   scenario = get_scenario("scenario_4_partial_fill_buy_larger")
   scenario.load_into_engine(engine)
   trades = engine.match_orders()  # Planned Day 6 method

   assert len(trades) == len(scenario.expected.trades)
   assert sum(t.quantity for t in trades) == scenario.expected.total_matched_quantity
   ```

2. **Ring Buffer & IPC Replay**:
   ```python
   # Pack scenario orders into mmap ring buffer
   for order in scenario.orders:
       ring_buffer.write_order(order.pack())
   # Consume and match directly from zero-copy memoryview
   ```

3. **Dashboard Real-Time Telemetry**:
   - Taniya's curses dashboard can ingest scenario events to verify that Depth of Market (L2), Best Bid, Best Ask, and Spread dynamically update as expected.
