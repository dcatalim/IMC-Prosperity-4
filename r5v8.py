from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math

MIN_SPREAD_TRADE = 3

# Product-class strategy choices for round 5.
# Grouping by the first token keeps the logic broad and avoids per-product overfitting.
CLASS_PARAMS = {
    "GALAXY": {"mode": "trend", "target": 10, "aggression": 1.0, "passive": 0.8, "min_spread": 2},
    "OXYGEN": {"mode": "trend", "target": 10, "aggression": 1.0, "passive": 0.8, "min_spread": 2},
    "PANEL": {"mode": "trend", "target": 10, "aggression": 1.0, "passive": 0.8, "min_spread": 2},
    "SLEEP": {"mode": "trend", "target": 10, "aggression": 1.0, "passive": 0.8, "min_spread": 2},
    "UV": {"mode": "trend", "target": 10, "aggression": 1.0, "passive": 0.8, "min_spread": 2},
    "SNACKPACK": {"mode": "trend", "target": 6, "aggression": 0.8, "passive": 0.6, "min_spread": 3},
    "TRANSLATOR": {"mode": "market_make", "max_pos": 8, "quote_size": 3, "min_spread": 3},
    "ROBOT": {"mode": "market_make", "max_pos": 8, "quote_size": 3, "min_spread": 3},
    "PEBBLES": {"mode": "cautious", "max_pos": 6, "quote_size": 2, "min_spread": 4},
    "MICROCHIP": {"mode": "cautious", "max_pos": 6, "quote_size": 2, "min_spread": 4},
}


class Trader:
    def run(self, state: TradingState):
        store = self._load_store(state.traderData)
        category_state = store["category_state"]
        result: Dict[str, List[Order]] = {}

        for product, trades in state.own_trades.items():
            category = self._product_class(product)
            cs = category_state.setdefault(category, {"cash": 0.0, "enabled": True})
            for trade in trades:
                qty = int(trade.quantity)
                if trade.buyer == "SUBMISSION":
                    cs["cash"] -= trade.price * qty
                elif trade.seller == "SUBMISSION":
                    cs["cash"] += trade.price * qty

        fair_values: Dict[str, float] = {}
        spreads: Dict[str, int] = {}

        for product, order_depth in state.order_depths.items():
            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            spread = best_ask - best_bid
            if spread <= 0:
                continue
            spreads[product] = spread
            fair_values[product] = self._estimate_fair_value(order_depth, best_bid, best_ask, spread)

        for product, order_depth in state.order_depths.items():
            if product not in fair_values:
                continue
            category = self._product_class(product)
            params = self._class_params(category)
            if not category_state.setdefault(category, {"cash": 0.0, "enabled": True})["enabled"]:
                position = state.position.get(product, 0)
                if position != 0:
                    result[product] = self._flatten(product, order_depth, position)
                continue
            position = state.position.get(product, 0)
            fair_value = fair_values[product]
            spread = spreads[product]

            if params["mode"] == "trend":
                if spread >= params["min_spread"]:
                    result[product] = self._trend_trade(product, order_depth, position, fair_value, spread, params["target"], params["aggression"], params["passive"])
            elif params["mode"] == "market_make":
                result[product] = self._market_make(product, order_depth, position, fair_value, spread, params["max_pos"], params["quote_size"])
            elif params["mode"] == "cautious":
                if spread >= params["min_spread"]:
                    result[product] = self._cautious_trade(product, order_depth, position, fair_value, spread, params["max_pos"], params["quote_size"])

        trader_data = json.dumps({"category_state": category_state}, separators=(",", ":"))
        return result, 0, trader_data

    def _load_store(self, trader_data: str) -> Dict[str, object]:
        if not trader_data:
            return {"category_state": {}}
        try:
            data = json.loads(trader_data)
        except json.JSONDecodeError:
            return {"category_state": {}}
        category_state = {}
        if isinstance(data.get("category_state"), dict):
            for category, state in data["category_state"].items():
                if isinstance(state, dict):
                    category_state[category] = {
                        "cash": float(state.get("cash", 0.0)),
                        "enabled": bool(state.get("enabled", True)),
                    }
        return {"category_state": category_state}

    def _product_class(self, product: str) -> str:
        return product.split("_")[0] if "_" in product else product

    def _class_params(self, category: str) -> Dict[str, object]:
        return CLASS_PARAMS.get(category, {"mode": "market_make", "max_pos": 6, "quote_size": 2, "min_spread": 3})

    def _estimate_fair_value(self, order_depth: OrderDepth, best_bid: int, best_ask: int, spread: int) -> float:
        bid_volume = sum(order_depth.buy_orders.values())
        ask_volume = abs(sum(order_depth.sell_orders.values()))
        book_mid = (best_bid + best_ask) / 2.0
        total = bid_volume + ask_volume
        if total == 0:
            return book_mid
        imbalance = (bid_volume - ask_volume) / total
        return book_mid + imbalance * max(1.0, spread) * 0.25

    def _trend_trade(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        fair_value: float,
        spread: int,
        target: int,
        aggressive_mult: float,
        passive_fraction: float,
    ) -> List[Order]:
        orders: List[Order] = []
        remaining = target - position
        if remaining == 0:
            return orders

        aggressive_margin = max(1.0, spread * aggressive_mult)
        if remaining > 0:
            for ask_price, ask_qty_neg in sorted(order_depth.sell_orders.items()):
                if remaining <= 0:
                    break
                if ask_price > fair_value + aggressive_margin:
                    break
                take = min(-ask_qty_neg, remaining)
                orders.append(Order(product, ask_price, take))
                remaining -= take
            if remaining > 0 and order_depth.buy_orders:
                best_bid = max(order_depth.buy_orders.keys())
                passive_price = min(best_bid + 1, int(math.floor(fair_value + 1)))
                passive_qty = max(1, int(math.ceil(remaining * passive_fraction)))
                if passive_price < min(order_depth.sell_orders.keys()):
                    orders.append(Order(product, passive_price, passive_qty))
        else:
            qty_to_sell = -remaining
            for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
                if qty_to_sell <= 0:
                    break
                if bid_price < fair_value - aggressive_margin:
                    break
                take = min(bid_qty, qty_to_sell)
                orders.append(Order(product, bid_price, -take))
                qty_to_sell -= take
            if qty_to_sell > 0 and order_depth.sell_orders:
                best_ask = min(order_depth.sell_orders.keys())
                passive_price = max(best_ask - 1, int(math.ceil(fair_value - 1)))
                passive_qty = max(1, int(math.ceil(qty_to_sell * passive_fraction)))
                if passive_price > max(order_depth.buy_orders.keys()):
                    orders.append(Order(product, passive_price, -passive_qty))
        return orders

    def _market_make(self, product: str, order_depth: OrderDepth, position: int, fair_value: float, spread: int, max_pos: int, quote_size: int) -> List[Order]:
        orders: List[Order] = []
        if spread < MIN_SPREAD_TRADE:
            return orders
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        skew = position * 0.2
        our_bid = int(min(best_bid + 1, math.floor(fair_value - 1.0 - skew)))
        our_ask = int(max(best_ask - 1, math.ceil(fair_value + 1.0 - skew)))
        if our_bid >= our_ask:
            return orders
        buy_capacity = max(0, min(max_pos - position, quote_size))
        sell_capacity = max(0, min(max_pos + position, quote_size))
        if buy_capacity > 0:
            orders.append(Order(product, our_bid, buy_capacity))
        if sell_capacity > 0:
            orders.append(Order(product, our_ask, -sell_capacity))
        return orders

    def _cautious_trade(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        fair_value: float,
        spread: int,
        max_pos: int,
        quote_size: int,
    ) -> List[Order]:
        if spread < MIN_SPREAD_TRADE:
            return self._flatten(product, order_depth, position)
        return self._market_make(product, order_depth, position, fair_value, spread, max_pos, quote_size)

    def _flatten(self, product: str, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        if position > 0:
            orders.append(Order(product, max(order_depth.buy_orders.keys()), -position))
        elif position < 0:
            orders.append(Order(product, min(order_depth.sell_orders.keys()), -position))
        return orders
