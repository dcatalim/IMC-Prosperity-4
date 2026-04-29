from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple


POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 40

# Synthetic group-index relative strength.  Long the categories whose average
# group index beat the whole universe; short the lagging group indexes.  Every
# constituent gets the same sign because the synthetic asset is the category,
# not the individual product.
TARGETS: Dict[str, int] = {
    "SLEEP_POD_COTTON": 7,
    "SLEEP_POD_LAMB_WOOL": 7,
    "SLEEP_POD_NYLON": 7,
    "SLEEP_POD_POLYESTER": 7,
    "SLEEP_POD_SUEDE": 7,
    "GALAXY_SOUNDS_BLACK_HOLES": 5,
    "GALAXY_SOUNDS_DARK_MATTER": 5,
    "GALAXY_SOUNDS_PLANETARY_RINGS": 5,
    "GALAXY_SOUNDS_SOLAR_FLAMES": 5,
    "GALAXY_SOUNDS_SOLAR_WINDS": 5,
    "OXYGEN_SHAKE_CHOCOLATE": 5,
    "OXYGEN_SHAKE_EVENING_BREATH": 5,
    "OXYGEN_SHAKE_GARLIC": 5,
    "OXYGEN_SHAKE_MINT": 5,
    "OXYGEN_SHAKE_MORNING_BREATH": 5,
    "MICROCHIP_CIRCLE": -7,
    "MICROCHIP_OVAL": -7,
    "MICROCHIP_RECTANGLE": -7,
    "MICROCHIP_SQUARE": -7,
    "MICROCHIP_TRIANGLE": -7,
    "ROBOT_DISHES": -5,
    "ROBOT_IRONING": -5,
    "ROBOT_LAUNDRY": -5,
    "ROBOT_MOPPING": -5,
    "ROBOT_VACUUMING": -5,
    "TRANSLATOR_ASTRO_BLACK": -5,
    "TRANSLATOR_ECLIPSE_CHARCOAL": -5,
    "TRANSLATOR_GRAPHITE_MIST": -5,
    "TRANSLATOR_SPACE_GRAY": -5,
    "TRANSLATOR_VOID_BLUE": -5,
    "UV_VISOR_AMBER": -3,
    "UV_VISOR_MAGENTA": -3,
    "UV_VISOR_ORANGE": -3,
    "UV_VISOR_RED": -3,
    "UV_VISOR_YELLOW": -3,
    "PANEL_1X2": -3,
    "PANEL_1X4": -3,
    "PANEL_2X2": -3,
    "PANEL_2X4": -3,
    "PANEL_4X4": -3,
}


class Trader:
    @staticmethod
    def _best_bid_ask(order_depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return best_bid, best_ask

    @staticmethod
    def _clamp_target(target: int) -> int:
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, int(target)))

    def _walk_to_target(self, product: str, order_depth: OrderDepth, position: int, target: int) -> List[Order]:
        target = self._clamp_target(target)
        delta = target - int(position)
        if delta == 0:
            return []
        best_bid, best_ask = self._best_bid_ask(order_depth)
        if best_bid is None or best_ask is None or best_ask - best_bid > MAX_CROSS_SPREAD:
            return []
        orders: List[Order] = []
        if delta > 0:
            remaining = min(delta, POSITION_LIMIT - int(position))
            for ask_price in sorted(order_depth.sell_orders):
                if remaining <= 0:
                    break
                qty = min(-int(order_depth.sell_orders[ask_price]), remaining)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    remaining -= qty
        else:
            remaining = min(-delta, POSITION_LIMIT + int(position))
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                qty = min(int(order_depth.buy_orders[bid_price]), remaining)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    remaining -= qty
        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, target in TARGETS.items():
            if product not in state.order_depths:
                continue
            orders = self._walk_to_target(product, state.order_depths[product], state.position.get(product, 0), target)
            if orders:
                result[product] = orders
        return result, 0, state.traderData or ""
