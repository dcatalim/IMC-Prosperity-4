from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple


POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 40

# V2: diversified historical drift book.
#
# V1 only traded products whose direction was positive on every historical day.
# That was safe but left a lot of edge unused.  The Round 5 limit is per product,
# with no cross-product capital constraint, so the better simple strategy is a
# diversified target book: trade each product in its historical average drift
# direction, then remove/trim names that worsen the worst historical day.
#
# Historical opening-spread-to-close-mid PnL for these targets:
#   day 2: 222,774
#   day 3: 223,374
#   day 4: 222,948.5
#
# Deliberately skipped despite weak average alpha because they hurt the worst
# historical day too much: UV_VISOR_YELLOW, ROBOT_MOPPING,
# TRANSLATOR_ECLIPSE_CHARCOAL.
STRUCTURAL_TARGETS: Dict[str, int] = {
    "GALAXY_SOUNDS_BLACK_HOLES": 10,
    "GALAXY_SOUNDS_DARK_MATTER": 9,
    "GALAXY_SOUNDS_PLANETARY_RINGS": -10,
    "GALAXY_SOUNDS_SOLAR_FLAMES": 10,
    "GALAXY_SOUNDS_SOLAR_WINDS": 10,
    "MICROCHIP_CIRCLE": 10,
    "MICROCHIP_OVAL": -10,
    "MICROCHIP_RECTANGLE": -10,
    "MICROCHIP_SQUARE": 10,
    "MICROCHIP_TRIANGLE": -10,
    "OXYGEN_SHAKE_CHOCOLATE": 10,
    "OXYGEN_SHAKE_EVENING_BREATH": -10,
    "OXYGEN_SHAKE_GARLIC": 10,
    "OXYGEN_SHAKE_MINT": 10,
    "OXYGEN_SHAKE_MORNING_BREATH": -10,
    "PANEL_1X2": -10,
    "PANEL_1X4": -10,
    "PANEL_2X2": -10,
    "PANEL_2X4": 10,
    "PANEL_4X4": -10,
    "PEBBLES_L": -10,
    "PEBBLES_M": 10,
    "PEBBLES_S": -10,
    "PEBBLES_XL": 10,
    "PEBBLES_XS": -10,
    "ROBOT_DISHES": 10,
    "ROBOT_IRONING": -10,
    "ROBOT_LAUNDRY": -10,
    "ROBOT_VACUUMING": -10,
    "SLEEP_POD_COTTON": 10,
    "SLEEP_POD_LAMB_WOOL": 10,
    "SLEEP_POD_NYLON": 10,
    "SLEEP_POD_POLYESTER": 10,
    "SLEEP_POD_SUEDE": 10,
    "SNACKPACK_CHOCOLATE": -10,
    "SNACKPACK_PISTACHIO": -10,
    "SNACKPACK_RASPBERRY": 10,
    "SNACKPACK_STRAWBERRY": 10,
    "SNACKPACK_VANILLA": 10,
    "TRANSLATOR_ASTRO_BLACK": -10,
    "TRANSLATOR_GRAPHITE_MIST": -10,
    "TRANSLATOR_SPACE_GRAY": -10,
    "TRANSLATOR_VOID_BLUE": 10,
    "UV_VISOR_AMBER": -10,
    "UV_VISOR_MAGENTA": 10,
    "UV_VISOR_ORANGE": -10,
    "UV_VISOR_RED": 10,
}


class Trader:
    @staticmethod
    def _best_bid_ask(order_depth: OrderDepth) -> Tuple[Optional[int], int, Optional[int], int]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        bid_volume = order_depth.buy_orders.get(best_bid, 0) if best_bid is not None else 0
        ask_volume = -order_depth.sell_orders.get(best_ask, 0) if best_ask is not None else 0
        return best_bid, bid_volume, best_ask, ask_volume

    @staticmethod
    def _clamp_target(target: int) -> int:
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, target))

    def _walk_book_to_target(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
    ) -> List[Order]:
        target = self._clamp_target(target)
        delta = target - position
        if delta == 0:
            return []

        best_bid, _, best_ask, _ = self._best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return []

        spread = best_ask - best_bid
        if spread > MAX_CROSS_SPREAD:
            return []

        orders: List[Order] = []

        if delta > 0:
            remaining = min(delta, POSITION_LIMIT - position)
            for ask_price in sorted(order_depth.sell_orders):
                if remaining <= 0:
                    break
                available = -order_depth.sell_orders[ask_price]
                if available <= 0:
                    continue
                quantity = min(available, remaining)
                orders.append(Order(product, ask_price, quantity))
                remaining -= quantity
        else:
            remaining = min(-delta, POSITION_LIMIT + position)
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                available = order_depth.buy_orders[bid_price]
                if available <= 0:
                    continue
                quantity = min(available, remaining)
                orders.append(Order(product, bid_price, -quantity))
                remaining -= quantity

        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product, order_depth in state.order_depths.items():
            target = STRUCTURAL_TARGETS.get(product, 0)
            if target == 0:
                continue

            position = state.position.get(product, 0)
            orders = self._walk_book_to_target(product, order_depth, position, target)
            if orders:
                result[product] = orders

        return result, 0, state.traderData or ""
