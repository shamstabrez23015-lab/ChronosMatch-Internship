"""ChronosMatch Reusable Trading Scenarios and Fixtures.

Provides deterministic, realistic trading scenarios and expected matching
outcomes for verifying the ChronosMatch Limit Order Book and Matching Engine.

Designed for Day 5 test fixture creation and future end-to-end integration tests.

Price Representation:
    - Floating-point dollar prices (protocol representation)
    - Integer cent ticks (engine representation: price_to_cents(price))

Side Representation:
    - Side.BUY = 1
    - Side.SELL = 2
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from chronos.protocol import (
    ORDER_SIZE,
    Order,
    OrderType,
    Side,
    SYMBOLS,
)


# ==============================================================================
# Data Structures
# ==============================================================================

@dataclass(frozen=True)
class ScenarioOrder:
    """Immutable order definition for trading scenarios.

    Attributes:
        order_id: Unique 64-bit integer identifier.
        side: 1 for BUY, 2 for SELL (mirrors chronos.protocol.Side).
        price: Floating-point dollar price (e.g. 500.00).
        quantity: Positive integer order quantity.
        timestamp_ns: Arrival timestamp in nanoseconds (strictly ordered).
        symbol_id: 16-bit symbol registry ID (default 1001 for AAPL).
        order_type: 1 for LIMIT, 2 for MARKET, 3 for CANCEL.
    """

    order_id: int
    side: int
    price: float
    quantity: int
    timestamp_ns: int = 0
    symbol_id: int = 1001
    order_type: int = int(OrderType.LIMIT)

    @property
    def price_cents(self) -> int:
        """Return the price in integer cent ticks (1 cent = $0.01)."""
        return int(round(self.price * 100.0))

    @property
    def side_str(self) -> str:
        """Return human-readable side string ('BUY' or 'SELL')."""
        return "BUY" if self.side == int(Side.BUY) else "SELL"

    @property
    def order_type_str(self) -> str:
        """Return human-readable order type string."""
        if self.order_type == int(OrderType.LIMIT):
            return "LIMIT"
        elif self.order_type == int(OrderType.MARKET):
            return "MARKET"
        elif self.order_type == int(OrderType.CANCEL):
            return "CANCEL"
        return f"TYPE_{self.order_type}"

    def to_protocol_order(self) -> Order:
        """Convert to chronos.protocol.Order NamedTuple."""
        return Order(
            order_id=self.order_id,
            timestamp_ns=self.timestamp_ns,
            price=self.price,
            quantity=self.quantity,
            symbol_id=self.symbol_id,
            side=self.side,
            order_type=self.order_type,
        )

    def pack(self) -> bytes:
        """Serialize into raw 32-byte binary protocol format."""
        return self.to_protocol_order().pack()

    def as_dict(self) -> Dict[str, Any]:
        """Return a plain dictionary representation."""
        return {
            "order_id": self.order_id,
            "side": self.side,
            "side_str": self.side_str,
            "price": self.price,
            "price_cents": self.price_cents,
            "quantity": self.quantity,
            "timestamp_ns": self.timestamp_ns,
            "symbol_id": self.symbol_id,
            "order_type": self.order_type,
        }


@dataclass(frozen=True)
class ExpectedTrade:
    """Expected trade execution record for future matching verification."""

    buy_order_id: int
    sell_order_id: int
    execution_price: float
    trade_quantity: int

    @property
    def execution_price_cents(self) -> int:
        """Return trade execution price in integer cents."""
        return int(round(self.execution_price * 100.0))

    def as_dict(self) -> Dict[str, Any]:
        """Return dictionary representation."""
        return {
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "execution_price": self.execution_price,
            "execution_price_cents": self.execution_price_cents,
            "trade_quantity": self.trade_quantity,
        }


@dataclass(frozen=True)
class ExpectedOutcome:
    """Expected outcome of order book priority and future trade matching.

    Attributes:
        has_crossing: True if highest BUY price >= lowest SELL price.
        best_buy_id: Order ID of highest priority BUY order, or None if empty.
        best_sell_id: Order ID of highest priority SELL order, or None if empty.
        prioritized_buy_ids: Tuple of BUY order IDs in Price-Time priority sequence.
        prioritized_sell_ids: Tuple of SELL order IDs in Price-Time priority sequence.
        total_matched_quantity: Expected total executed shares/contracts.
        remaining_quantities: Mapping of order_id -> expected unfilled quantity.
        trades: Tuple of expected individual trade executions.
    """

    has_crossing: bool
    best_buy_id: Optional[int]
    best_sell_id: Optional[int]
    prioritized_buy_ids: Tuple[int, ...]
    prioritized_sell_ids: Tuple[int, ...]
    total_matched_quantity: int
    remaining_quantities: Dict[int, int]
    trades: Tuple[ExpectedTrade, ...] = ()

    def copy(self) -> ExpectedOutcome:
        """Return an independent copy."""
        return ExpectedOutcome(
            has_crossing=self.has_crossing,
            best_buy_id=self.best_buy_id,
            best_sell_id=self.best_sell_id,
            prioritized_buy_ids=self.prioritized_buy_ids,
            prioritized_sell_ids=self.prioritized_sell_ids,
            total_matched_quantity=self.total_matched_quantity,
            remaining_quantities=dict(self.remaining_quantities),
            trades=self.trades,
        )


@dataclass(frozen=True)
class TradingScenario:
    """Self-contained, deterministic trading scenario with inputs and expectations."""

    name: str
    description: str
    orders: Tuple[ScenarioOrder, ...]
    expected: ExpectedOutcome

    def get_orders(self) -> List[ScenarioOrder]:
        """Return a mutable list copy of the input orders."""
        return list(self.orders)

    def get_buy_orders(self) -> List[ScenarioOrder]:
        """Return all BUY orders in arrival sequence."""
        return [o for o in self.orders if o.side == int(Side.BUY)]

    def get_sell_orders(self) -> List[ScenarioOrder]:
        """Return all SELL orders in arrival sequence."""
        return [o for o in self.orders if o.side == int(Side.SELL)]

    def load_into_engine(self, engine: Any) -> Any:
        """Populate a MatchingEngine instance with this scenario's orders.

        Submits orders sequentially in their deterministic arrival order.

        Args:
            engine: chronos.matching_engine.MatchingEngine instance.

        Returns:
            The populated MatchingEngine instance.
        """
        for ord_info in self.orders:
            engine.submit_order(
                order_id=ord_info.order_id,
                side=ord_info.side,
                price=ord_info.price,
                quantity=ord_info.quantity,
                timestamp_ns=ord_info.timestamp_ns,
            )
        return engine

    def copy(self) -> TradingScenario:
        """Return an independent deep copy of the scenario."""
        return TradingScenario(
            name=self.name,
            description=self.description,
            orders=self.orders,
            expected=self.expected.copy(),
        )


# ==============================================================================
# Ten Deterministic Trading Scenarios
# ==============================================================================

# ------------------------------------------------------------------------------
# Scenario 1: Exact-price BUY and SELL match
# ------------------------------------------------------------------------------
SCENARIO_1_EXACT_MATCH = TradingScenario(
    name="scenario_1_exact_match",
    description="Exact-price BUY and SELL match where bid and ask prices are equal with matching quantities.",
    orders=(
        ScenarioOrder(
            order_id=101,
            side=int(Side.BUY),
            price=100.00,
            quantity=50,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=102,
            side=int(Side.SELL),
            price=100.00,
            quantity=50,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=101,
        best_sell_id=102,
        prioritized_buy_ids=(101,),
        prioritized_sell_ids=(102,),
        total_matched_quantity=50,
        remaining_quantities={101: 0, 102: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=101,
                sell_order_id=102,
                execution_price=100.00,
                trade_quantity=50,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 2: BUY price higher than SELL price
# ------------------------------------------------------------------------------
SCENARIO_2_CROSSED_MARKET = TradingScenario(
    name="scenario_2_crossed_market",
    description="BUY price higher than SELL price (crossed market). Aggressive order crosses resting limit book.",
    orders=(
        ScenarioOrder(
            order_id=201,
            side=int(Side.BUY),
            price=105.00,
            quantity=100,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=202,
            side=int(Side.SELL),
            price=100.00,
            quantity=100,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=201,
        best_sell_id=202,
        prioritized_buy_ids=(201,),
        prioritized_sell_ids=(202,),
        total_matched_quantity=100,
        remaining_quantities={201: 0, 202: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=201,
                sell_order_id=202,
                execution_price=105.00,
                trade_quantity=100,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 3: BUY price below SELL price — no trade
# ------------------------------------------------------------------------------
SCENARIO_3_NO_TRADE = TradingScenario(
    name="scenario_3_no_trade_wide_spread",
    description="BUY price below SELL price — positive spread prevents crossing; no trade execution.",
    orders=(
        ScenarioOrder(
            order_id=301,
            side=int(Side.BUY),
            price=95.00,
            quantity=100,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=302,
            side=int(Side.SELL),
            price=105.00,
            quantity=100,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=False,
        best_buy_id=301,
        best_sell_id=302,
        prioritized_buy_ids=(301,),
        prioritized_sell_ids=(302,),
        total_matched_quantity=0,
        remaining_quantities={301: 100, 302: 100},
        trades=(),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 4: Partial fill where BUY quantity is larger
# ------------------------------------------------------------------------------
SCENARIO_4_PARTIAL_FILL_BUY_LARGER = TradingScenario(
    name="scenario_4_partial_fill_buy_larger",
    description="Partial fill where BUY quantity (100) is larger than SELL quantity (40). BUY has 60 remaining.",
    orders=(
        ScenarioOrder(
            order_id=401,
            side=int(Side.BUY),
            price=500.00,
            quantity=100,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=402,
            side=int(Side.SELL),
            price=500.00,
            quantity=40,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=401,
        best_sell_id=402,
        prioritized_buy_ids=(401,),
        prioritized_sell_ids=(402,),
        total_matched_quantity=40,
        remaining_quantities={401: 60, 402: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=401,
                sell_order_id=402,
                execution_price=500.00,
                trade_quantity=40,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 5: Partial fill where SELL quantity is larger
# ------------------------------------------------------------------------------
SCENARIO_5_PARTIAL_FILL_SELL_LARGER = TradingScenario(
    name="scenario_5_partial_fill_sell_larger",
    description="Partial fill where SELL quantity (80) is larger than BUY quantity (30). SELL has 50 remaining.",
    orders=(
        ScenarioOrder(
            order_id=501,
            side=int(Side.BUY),
            price=250.00,
            quantity=30,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=502,
            side=int(Side.SELL),
            price=250.00,
            quantity=80,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=501,
        best_sell_id=502,
        prioritized_buy_ids=(501,),
        prioritized_sell_ids=(502,),
        total_matched_quantity=30,
        remaining_quantities={501: 0, 502: 50},
        trades=(
            ExpectedTrade(
                buy_order_id=501,
                sell_order_id=502,
                execution_price=250.00,
                trade_quantity=30,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 6: Exact full fill where both quantities are equal
# ------------------------------------------------------------------------------
SCENARIO_6_EXACT_FULL_FILL = TradingScenario(
    name="scenario_6_exact_full_fill",
    description="Exact full fill where both BUY and SELL quantities are identical (75), resulting in complete execution.",
    orders=(
        ScenarioOrder(
            order_id=601,
            side=int(Side.BUY),
            price=300.00,
            quantity=75,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=602,
            side=int(Side.SELL),
            price=300.00,
            quantity=75,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=601,
        best_sell_id=602,
        prioritized_buy_ids=(601,),
        prioritized_sell_ids=(602,),
        total_matched_quantity=75,
        remaining_quantities={601: 0, 602: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=601,
                sell_order_id=602,
                execution_price=300.00,
                trade_quantity=75,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 7: Multiple BUY orders at the same price (FIFO)
# ------------------------------------------------------------------------------
SCENARIO_7_FIFO_SAME_PRICE = TradingScenario(
    name="scenario_7_fifo_same_price",
    description="Multiple BUY orders at the same price (150.00). Earliest arrival (701) matched before later arrival (702).",
    orders=(
        ScenarioOrder(
            order_id=701,
            side=int(Side.BUY),
            price=150.00,
            quantity=40,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=702,
            side=int(Side.BUY),
            price=150.00,
            quantity=60,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=703,
            side=int(Side.SELL),
            price=150.00,
            quantity=50,
            timestamp_ns=1_000_002_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=701,
        best_sell_id=703,
        prioritized_buy_ids=(701, 702),
        prioritized_sell_ids=(703,),
        total_matched_quantity=50,
        remaining_quantities={701: 0, 702: 50, 703: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=701,
                sell_order_id=703,
                execution_price=150.00,
                trade_quantity=40,
            ),
            ExpectedTrade(
                buy_order_id=702,
                sell_order_id=703,
                execution_price=150.00,
                trade_quantity=10,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 8: Multiple BUY prices — highest price should have priority
# ------------------------------------------------------------------------------
SCENARIO_8_PRICE_PRIORITY_BUY = TradingScenario(
    name="scenario_8_price_priority_buy",
    description="Multiple BUY prices: highest price (802 @ 102.00) takes precedence over earlier lower price (801 @ 100.00).",
    orders=(
        ScenarioOrder(
            order_id=801,
            side=int(Side.BUY),
            price=100.00,
            quantity=50,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=802,
            side=int(Side.BUY),
            price=102.00,
            quantity=30,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=803,
            side=int(Side.SELL),
            price=100.00,
            quantity=40,
            timestamp_ns=1_000_002_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=802,
        best_sell_id=803,
        prioritized_buy_ids=(802, 801),
        prioritized_sell_ids=(803,),
        total_matched_quantity=40,
        remaining_quantities={801: 40, 802: 0, 803: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=802,
                sell_order_id=803,
                execution_price=102.00,
                trade_quantity=30,
            ),
            ExpectedTrade(
                buy_order_id=801,
                sell_order_id=803,
                execution_price=100.00,
                trade_quantity=10,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 9: Multiple SELL prices — lowest price should have priority
# ------------------------------------------------------------------------------
SCENARIO_9_PRICE_PRIORITY_SELL = TradingScenario(
    name="scenario_9_price_priority_sell",
    description="Multiple SELL prices: lowest price (902 @ 200.00) takes precedence over earlier higher price (901 @ 205.00).",
    orders=(
        ScenarioOrder(
            order_id=901,
            side=int(Side.SELL),
            price=205.00,
            quantity=40,
            timestamp_ns=1_000_000_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=902,
            side=int(Side.SELL),
            price=200.00,
            quantity=25,
            timestamp_ns=1_000_001_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
        ScenarioOrder(
            order_id=903,
            side=int(Side.BUY),
            price=205.00,
            quantity=50,
            timestamp_ns=1_000_002_000,
            symbol_id=SYMBOLS["AAPL"],
        ),
    ),
    expected=ExpectedOutcome(
        has_crossing=True,
        best_buy_id=903,
        best_sell_id=902,
        prioritized_buy_ids=(903,),
        prioritized_sell_ids=(902, 901),
        total_matched_quantity=50,
        remaining_quantities={901: 15, 902: 0, 903: 0},
        trades=(
            ExpectedTrade(
                buy_order_id=903,
                sell_order_id=902,
                execution_price=200.00,
                trade_quantity=25,
            ),
            ExpectedTrade(
                buy_order_id=903,
                sell_order_id=901,
                execution_price=205.00,
                trade_quantity=25,
            ),
        ),
    ),
)


# ------------------------------------------------------------------------------
# Scenario 10: Empty order book — no matching opportunity
# ------------------------------------------------------------------------------
SCENARIO_10_EMPTY_ORDER_BOOK = TradingScenario(
    name="scenario_10_empty_order_book",
    description="Empty order book containing no orders; no crossing, zero matches, no priority.",
    orders=(),
    expected=ExpectedOutcome(
        has_crossing=False,
        best_buy_id=None,
        best_sell_id=None,
        prioritized_buy_ids=(),
        prioritized_sell_ids=(),
        total_matched_quantity=0,
        remaining_quantities={},
        trades=(),
    ),
)


# ==============================================================================
# Scenario Collections and Access Helpers
# ==============================================================================

ALL_SCENARIOS: Tuple[TradingScenario, ...] = (
    SCENARIO_1_EXACT_MATCH,
    SCENARIO_2_CROSSED_MARKET,
    SCENARIO_3_NO_TRADE,
    SCENARIO_4_PARTIAL_FILL_BUY_LARGER,
    SCENARIO_5_PARTIAL_FILL_SELL_LARGER,
    SCENARIO_6_EXACT_FULL_FILL,
    SCENARIO_7_FIFO_SAME_PRICE,
    SCENARIO_8_PRICE_PRIORITY_BUY,
    SCENARIO_9_PRICE_PRIORITY_SELL,
    SCENARIO_10_EMPTY_ORDER_BOOK,
)

SCENARIOS_BY_NAME: Dict[str, TradingScenario] = {
    s.name: s for s in ALL_SCENARIOS
}


def get_all_scenarios() -> List[TradingScenario]:
    """Return an independent list copy of all ten trading scenarios."""
    return [s.copy() for s in ALL_SCENARIOS]


def get_scenario(name: str) -> TradingScenario:
    """Retrieve an independent copy of a scenario by its name.

    Args:
        name: The unique scenario name (e.g. 'scenario_1_exact_match').

    Returns:
        A copy of the requested TradingScenario.

    Raises:
        KeyError: If the scenario name is not found.
    """
    if name not in SCENARIOS_BY_NAME:
        raise KeyError(
            f"Unknown scenario '{name}'. Available scenarios: {list(SCENARIOS_BY_NAME.keys())}"
        )
    return SCENARIOS_BY_NAME[name].copy()
