from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import math

POSITION_LIMIT = 10

CORE_UP = {
    'GALAXY_SOUNDS_BLACK_HOLES', 'OXYGEN_SHAKE_GARLIC', 'PANEL_2X4',
    'UV_VISOR_RED', 'SLEEP_POD_LAMB_WOOL', 'SNACKPACK_STRAWBERRY',
}
CORE_DOWN = {
    'MICROCHIP_OVAL', 'PEBBLES_XS', 'UV_VISOR_AMBER', 'PEBBLES_S',
    'SNACKPACK_PISTACHIO', 'SNACKPACK_CHOCOLATE',
}
SECONDARY_UP = {
    'MICROCHIP_SQUARE', 'PEBBLES_XL', 'SLEEP_POD_COTTON',
    'SLEEP_POD_POLYESTER', 'SLEEP_POD_SUEDE', 'TRANSLATOR_VOID_BLUE',
    'UV_VISOR_MAGENTA', 'ROBOT_DISHES',
}
SECONDARY_DOWN = {
    'ROBOT_IRONING', 'ROBOT_VACUUMING', 'MICROCHIP_TRIANGLE',
    'MICROCHIP_RECTANGLE', 'ROBOT_LAUNDRY', 'TRANSLATOR_SPACE_GRAY',
    'TRANSLATOR_ASTRO_BLACK',
}


class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)

            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue

            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            spread = best_ask - best_bid
            if spread <= 0:
                continue

            fair_value = self._estimate_fair_value(order_depth, best_bid, best_ask, spread)

            if product in CORE_UP:
                result[product] = self._trend_trade(
                    product, order_depth, position, +POSITION_LIMIT, fair_value, spread, 0.75, 1.0
                )
            elif product in CORE_DOWN:
                result[product] = self._trend_trade(
                    product, order_depth, position, -POSITION_LIMIT, fair_value, spread, 0.75, 1.0
                )
            elif product in SECONDARY_UP:
                result[product] = self._trend_trade(
                    product, order_depth, position, +POSITION_LIMIT, fair_value, spread, 0.60, 0.5
                )
            elif product in SECONDARY_DOWN:
                result[product] = self._trend_trade(
                    product, order_depth, position, -POSITION_LIMIT, fair_value, spread, 0.60, 0.5
                )
            else:
                result[product] = self._market_make(
                    product, order_depth, position, fair_value, spread
                )

        return result, 0, ""

    def _estimate_fair_value(
        self,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        spread: int,
    ) -> float:
        bid_volume = sum(order_depth.buy_orders.values())
        ask_volume = abs(sum(order_depth.sell_orders.values()))
        total_volume = bid_volume + ask_volume

        book_mid = (best_bid + best_ask) / 2.0
        if total_volume == 0:
            return book_mid

        imbalance = (bid_volume - ask_volume) / total_volume
        return book_mid + imbalance * max(1.0, spread) * 0.35

    def _trend_trade(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
        fair_value: float,
        spread: int,
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

            if remaining > 0:
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

            if qty_to_sell > 0:
                best_ask = min(order_depth.sell_orders.keys())
                passive_price = max(best_ask - 1, int(math.ceil(fair_value - 1)))
                passive_qty = max(1, int(math.ceil(qty_to_sell * passive_fraction)))
                if passive_price > max(order_depth.buy_orders.keys()):
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
        if spread < 3:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        skew = position * 0.3
        our_bid = int(min(best_bid + 1, math.floor(fair_value - 1.0 - skew)))
        our_ask = int(max(best_ask - 1, math.ceil(fair_value + 1.0 - skew)))

        if our_bid >= our_ask:
            return orders

        buy_capacity = max(0, POSITION_LIMIT - position)
        sell_capacity = max(0, POSITION_LIMIT + position)

        if buy_capacity > 0:
            orders.append(Order(product, our_bid, min(4, buy_capacity)))
        if sell_capacity > 0:
            orders.append(Order(product, our_ask, -min(4, sell_capacity)))

        return orders
