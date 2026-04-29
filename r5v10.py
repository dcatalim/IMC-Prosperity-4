from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import math

POSITION_LIMIT = 10
MIN_SPREAD = 3

CORE_LONG = {
    "GALAXY_SOUNDS_BLACK_HOLES",
    "OXYGEN_SHAKE_GARLIC",
    "PANEL_2X4",
    "UV_VISOR_RED",
    "SLEEP_POD_LAMB_WOOL",
    "SNACKPACK_STRAWBERRY",
}
CORE_SHORT = {
    "MICROCHIP_OVAL",
    "PEBBLES_XS",
    "UV_VISOR_AMBER",
    "PEBBLES_S",
    "SNACKPACK_PISTACHIO",
    "SNACKPACK_CHOCOLATE",
}
SECONDARY_LONG = {
    "MICROCHIP_SQUARE",
    "PEBBLES_XL",
    "SLEEP_POD_COTTON",
    "SLEEP_POD_POLYESTER",
    "SLEEP_POD_SUEDE",
    "TRANSLATOR_VOID_BLUE",
    "UV_VISOR_MAGENTA",
    "ROBOT_DISHES",
}
SECONDARY_SHORT = {
    "ROBOT_IRONING",
    "ROBOT_VACUUMING",
    "MICROCHIP_TRIANGLE",
    "MICROCHIP_RECTANGLE",
    "ROBOT_LAUNDRY",
    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_ASTRO_BLACK",
}
NO_TRADE = {
    "GALAXY_SOUNDS_SOLAR_FLAMES",
    "OXYGEN_SHAKE_MINT",
    "PANEL_1X2",
    "PANEL_4X4",
    "PEBBLES_L",
    "PEBBLES_M",
    "ROBOT_MOPPING",
    "TRANSLATOR_GRAPHITE_MIST",
}


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            spread = best_ask - best_bid
            if spread <= 0:
                continue

            fair_value = self._estimate_fair_value(order_depth, best_bid, best_ask, spread)
            position = state.position.get(product, 0)

            if product in CORE_LONG:
                result[product] = self._directional_trade(
                    product,
                    order_depth,
                    position,
                    target=POSITION_LIMIT,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_multiplier=0.75,
                    passive_fraction=0.5,
                )
            elif product in CORE_SHORT:
                result[product] = self._directional_trade(
                    product,
                    order_depth,
                    position,
                    target=-POSITION_LIMIT,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_multiplier=0.75,
                    passive_fraction=0.5,
                )
            elif product in SECONDARY_LONG:
                result[product] = self._directional_trade(
                    product,
                    order_depth,
                    position,
                    target=6,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_multiplier=0.60,
                    passive_fraction=0.35,
                )
            elif product in SECONDARY_SHORT:
                result[product] = self._directional_trade(
                    product,
                    order_depth,
                    position,
                    target=-6,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_multiplier=0.60,
                    passive_fraction=0.35,
                )
            elif product not in NO_TRADE:
                result[product] = self._market_make(product, order_depth, position, fair_value, spread)

        return result, 0, ""

    def _estimate_fair_value(
        self,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        spread: int,
    ) -> float:
        book_mid = (best_bid + best_ask) / 2.0
        bid_volume = sum(order_depth.buy_orders.values())
        ask_volume = abs(sum(order_depth.sell_orders.values()))
        total_volume = bid_volume + ask_volume

        if total_volume == 0:
            return book_mid

        imbalance = (bid_volume - ask_volume) / total_volume
        return book_mid + imbalance * max(1.0, spread) * 0.35

    def _directional_trade(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
        fair_value: float,
        spread: int,
        aggressive_multiplier: float,
        passive_fraction: float,
    ) -> List[Order]:
        orders: List[Order] = []
        remaining = target - position
        if remaining == 0:
            return orders

        aggressive_margin = max(1.0, spread * aggressive_multiplier)

        if remaining > 0:
            for ask_price, ask_qty_neg in sorted(order_depth.sell_orders.items()):
                if remaining <= 0:
                    break
                if ask_price > fair_value + aggressive_margin:
                    break
                qty = min(-ask_qty_neg, remaining)
                orders.append(Order(product, ask_price, qty))
                remaining -= qty

            if remaining > 0 and order_depth.buy_orders:
                passive_price = min(max(order_depth.buy_orders.keys()) + 1, int(math.floor(fair_value + 0.5)))
                if passive_price < min(order_depth.sell_orders.keys()):
                    passive_qty = max(1, min(remaining, int(math.ceil(abs(remaining) * passive_fraction))))
                    orders.append(Order(product, passive_price, passive_qty))
        else:
            remaining_sell = -remaining
            for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
                if remaining_sell <= 0:
                    break
                if bid_price < fair_value - aggressive_margin:
                    break
                qty = min(bid_qty, remaining_sell)
                orders.append(Order(product, bid_price, -qty))
                remaining_sell -= qty

            if remaining_sell > 0 and order_depth.sell_orders:
                passive_price = max(min(order_depth.sell_orders.keys()) - 1, int(math.ceil(fair_value - 0.5)))
                if passive_price > max(order_depth.buy_orders.keys()):
                    passive_qty = max(1, min(remaining_sell, int(math.ceil(remaining_sell * passive_fraction))))
                    orders.append(Order(product, passive_price, -passive_qty))

        return orders

    def _market_make(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        fair_value: float,
        spread: int,
    ) -> List[Order]:
        orders: List[Order] = []
        if spread < MIN_SPREAD:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        skew = position * 0.2

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
