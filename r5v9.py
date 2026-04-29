from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math

POSITION_LIMIT = 10
MIN_SPREAD = 3
HISTORY_LENGTH = 50
TREND_SELECT_COUNT = 8
TREND_MIN_SCORE = 0.14


class Trader:
    def run(self, state: TradingState):
        store = self._load_store(state.traderData)
        history = store["history"]
        result: Dict[str, List[Order]] = {}

        fair_values: Dict[str, float] = {}
        spreads: Dict[str, int] = {}
        mids: Dict[str, float] = {}

        for product, order_depth in state.order_depths.items():
            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            spread = best_ask - best_bid
            if spread <= 0:
                continue
            mid_price = (best_bid + best_ask) / 2.0
            fair_values[product] = self._estimate_fair_value(order_depth, best_bid, best_ask, spread)
            spreads[product] = spread
            mids[product] = mid_price
            self._append_history(history, product, mid_price)

        trend_scores = {
            product: self._trend_score(history.get(product, []))
            for product in mids
        }

        top_trend_products = {
            product
            for product, score in sorted(trend_scores.items(), key=lambda kv: abs(kv[1]), reverse=True)[:TREND_SELECT_COUNT]
            if abs(score) >= TREND_MIN_SCORE
        }

        for product, order_depth in state.order_depths.items():
            if product not in fair_values:
                continue
            position = state.position.get(product, 0)
            fair_value = fair_values[product]
            spread = spreads[product]
            trend_score = trend_scores.get(product, 0.0)

            if product in top_trend_products and spread >= MIN_SPREAD:
                result[product] = self._trend_trade(
                    product,
                    order_depth,
                    position,
                    fair_value,
                    spread,
                    trend_score,
                )
            elif spread >= MIN_SPREAD:
                result[product] = self._market_make(product, order_depth, position, fair_value, spread)
            elif position != 0:
                result[product] = self._flatten(product, order_depth, position)

        trader_data = json.dumps({"history": history}, separators=(",", ":"))
        return result, 0, trader_data

    def _load_store(self, trader_data: str) -> Dict[str, object]:
        if not trader_data:
            return {"history": {}}
        try:
            data = json.loads(trader_data)
        except json.JSONDecodeError:
            return {"history": {}}
        history = {}
        if isinstance(data.get("history"), dict):
            for product, mids in data["history"].items():
                if isinstance(mids, list):
                    history[product] = [float(value) for value in mids[-HISTORY_LENGTH:]]
        return {"history": history}

    def _append_history(self, history: Dict[str, List[float]], product: str, mid_price: float) -> None:
        values = history.setdefault(product, [])
        values.append(mid_price)
        if len(values) > HISTORY_LENGTH:
            del values[0]

    def _estimate_fair_value(self, order_depth: OrderDepth, best_bid: int, best_ask: int, spread: int) -> float:
        bid_volume = sum(order_depth.buy_orders.values())
        ask_volume = abs(sum(order_depth.sell_orders.values()))
        book_mid = (best_bid + best_ask) / 2.0
        total = bid_volume + ask_volume
        if total == 0:
            return book_mid
        imbalance = (bid_volume - ask_volume) / total
        return book_mid + imbalance * max(1.0, spread) * 0.30

    def _trend_score(self, history: List[float]) -> float:
        if len(history) < HISTORY_LENGTH:
            return 0.0
        prices = history[-HISTORY_LENGTH:]
        x = list(range(len(prices)))
        n = len(prices)
        x_mean = sum(x) / n
        y_mean = sum(prices) / n
        num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, prices))
        den = sum((xi - x_mean) ** 2 for xi in x)
        if den == 0:
            return 0.0
        slope = num / den
        return slope

    def _trend_trade(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        fair_value: float,
        spread: int,
        score: float,
    ) -> List[Order]:
        target = int(math.copysign(min(POSITION_LIMIT, max(4, int(abs(score) * 30))), score))
        if position == target:
            return []

        remaining = target - position
        orders: List[Order] = []
        aggressive_margin = max(1.0, spread * 0.65)

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
                passive_price = min(best_bid + 1, int(math.floor(fair_value + 0.5)))
                if passive_price < min(order_depth.sell_orders.keys()):
                    orders.append(Order(product, passive_price, max(1, remaining)))
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
                passive_price = max(best_ask - 1, int(math.ceil(fair_value - 0.5)))
                if passive_price > max(order_depth.buy_orders.keys()):
                    orders.append(Order(product, passive_price, -max(1, qty_to_sell)))

        return orders

    def _market_make(self, product: str, order_depth: OrderDepth, position: int, fair_value: float, spread: int) -> List[Order]:
        orders: List[Order] = []
        if spread < MIN_SPREAD:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        skew = position * 0.15
        our_bid = int(min(best_bid + 1, math.floor(fair_value - 0.5 - skew)))
        our_ask = int(max(best_ask - 1, math.ceil(fair_value + 0.5 - skew)))

        if our_bid >= our_ask:
            return orders

        buy_qty = max(0, min(POSITION_LIMIT - position, 3))
        sell_qty = max(0, min(POSITION_LIMIT + position, 3))
        if buy_qty > 0:
            orders.append(Order(product, our_bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order(product, our_ask, -sell_qty))

        return orders

    def _flatten(self, product: str, order_depth: OrderDepth, position: int) -> List[Order]:
        if position == 0:
            return []
        if position > 0 and order_depth.buy_orders:
            return [Order(product, max(order_depth.buy_orders.keys()), -position)]
        if position < 0 and order_depth.sell_orders:
            return [Order(product, min(order_depth.sell_orders.keys()), -position)]
        return []
