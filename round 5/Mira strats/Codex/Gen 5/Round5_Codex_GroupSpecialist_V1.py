from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple


POSITION_LIMIT = 10

# One deliberate rule per group, encoded as robust target exposures:
# Galaxy = structural leader carry; Sleep = broad pod strength; Microchip =
# shape spread; Pebbles = size curve; Robot = chore-quality spread; UV = color
# strength; Translator = compact pair; Panel = format spread; Oxygen = garlic
# leader; Snack = flavor spread.
TARGETS: Dict[str, int] = {
    "GALAXY_SOUNDS_BLACK_HOLES": 10,
    "GALAXY_SOUNDS_SOLAR_FLAMES": 4,
    "GALAXY_SOUNDS_PLANETARY_RINGS": -4,
    "SLEEP_POD_COTTON": 5,
    "SLEEP_POD_LAMB_WOOL": 10,
    "SLEEP_POD_NYLON": 3,
    "SLEEP_POD_POLYESTER": 7,
    "SLEEP_POD_SUEDE": 5,
    "MICROCHIP_OVAL": -10,
    "MICROCHIP_RECTANGLE": -6,
    "MICROCHIP_SQUARE": 7,
    "MICROCHIP_TRIANGLE": -7,
    "PEBBLES_XS": -10,
    "PEBBLES_S": -10,
    "PEBBLES_M": 8,
    "PEBBLES_L": -6,
    "PEBBLES_XL": 8,
    "ROBOT_DISHES": 6,
    "ROBOT_IRONING": -7,
    "ROBOT_LAUNDRY": -4,
    "ROBOT_VACUUMING": -6,
    "UV_VISOR_AMBER": -10,
    "UV_VISOR_MAGENTA": 7,
    "UV_VISOR_ORANGE": -4,
    "UV_VISOR_RED": 10,
    "TRANSLATOR_ASTRO_BLACK": -5,
    "TRANSLATOR_SPACE_GRAY": -6,
    "TRANSLATOR_VOID_BLUE": 6,
    "PANEL_1X2": -4,
    "PANEL_2X2": -8,
    "PANEL_2X4": 10,
    "PANEL_4X4": -6,
    "OXYGEN_SHAKE_EVENING_BREATH": -5,
    "OXYGEN_SHAKE_GARLIC": 10,
    "OXYGEN_SHAKE_MINT": -3,
    "OXYGEN_SHAKE_MORNING_BREATH": -6,
    "SNACKPACK_CHOCOLATE": -10,
    "SNACKPACK_PISTACHIO": -10,
    "SNACKPACK_RASPBERRY": 5,
    "SNACKPACK_STRAWBERRY": 10,
    "SNACKPACK_VANILLA": 5,
}

GROUP_SPREAD: Dict[str, int] = {
    "ROBOT_": 12,
    "SLEEP_POD_": 18,
    "MICROCHIP_": 24,
    "TRANSLATOR_": 24,
    "PANEL_": 24,
    "UV_VISOR_": 32,
    "SNACKPACK_": 36,
    "PEBBLES_": 40,
    "OXYGEN_SHAKE_": 40,
    "GALAXY_SOUNDS_": 40,
}


class Trader:
    @staticmethod
    def _max_spread(product: str) -> int:
        for prefix, spread in GROUP_SPREAD.items():
            if product.startswith(prefix):
                return spread
        return 30

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
        if best_bid is None or best_ask is None or best_ask - best_bid > self._max_spread(product):
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
