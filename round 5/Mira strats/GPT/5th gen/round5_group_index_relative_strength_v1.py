from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple

POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 40
TARGETS: Dict[str, int] = {'GALAXY_SOUNDS_BLACK_HOLES': 5,
 'GALAXY_SOUNDS_DARK_MATTER': 5,
 'GALAXY_SOUNDS_PLANETARY_RINGS': 5,
 'GALAXY_SOUNDS_SOLAR_FLAMES': 5,
 'GALAXY_SOUNDS_SOLAR_WINDS': 5,
 'MICROCHIP_CIRCLE': -5,
 'MICROCHIP_OVAL': -5,
 'MICROCHIP_RECTANGLE': -5,
 'MICROCHIP_SQUARE': -5,
 'MICROCHIP_TRIANGLE': -5,
 'OXYGEN_SHAKE_CHOCOLATE': 4,
 'OXYGEN_SHAKE_EVENING_BREATH': 4,
 'OXYGEN_SHAKE_GARLIC': 4,
 'OXYGEN_SHAKE_MINT': 4,
 'OXYGEN_SHAKE_MORNING_BREATH': 4,
 'PANEL_1X2': -1,
 'PANEL_1X4': -1,
 'PANEL_2X2': -1,
 'PANEL_2X4': -1,
 'PANEL_4X4': -1,
 'ROBOT_DISHES': -4,
 'ROBOT_IRONING': -4,
 'ROBOT_LAUNDRY': -4,
 'ROBOT_MOPPING': -4,
 'ROBOT_VACUUMING': -4,
 'SLEEP_POD_COTTON': 6,
 'SLEEP_POD_LAMB_WOOL': 6,
 'SLEEP_POD_NYLON': 6,
 'SLEEP_POD_POLYESTER': 6,
 'SLEEP_POD_SUEDE': 6,
 'SNACKPACK_CHOCOLATE': 2,
 'SNACKPACK_PISTACHIO': 2,
 'SNACKPACK_RASPBERRY': 2,
 'SNACKPACK_STRAWBERRY': 2,
 'SNACKPACK_VANILLA': 2,
 'TRANSLATOR_ASTRO_BLACK': -3,
 'TRANSLATOR_ECLIPSE_CHARCOAL': -3,
 'TRANSLATOR_GRAPHITE_MIST': -3,
 'TRANSLATOR_SPACE_GRAY': -3,
 'TRANSLATOR_VOID_BLUE': -3,
 'UV_VISOR_AMBER': -1,
 'UV_VISOR_MAGENTA': -1,
 'UV_VISOR_ORANGE': -1,
 'UV_VISOR_RED': -1,
 'UV_VISOR_YELLOW': -1}

class Trader:
    def bid(self):
        return 15

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
        if best_bid is None or best_ask is None:
            return []
        if best_ask - best_bid > MAX_CROSS_SPREAD:
            return []
        orders: List[Order] = []
        if delta > 0:
            remaining = min(delta, POSITION_LIMIT - int(position))
            for ask_price in sorted(order_depth.sell_orders):
                if remaining <= 0:
                    break
                available = -int(order_depth.sell_orders[ask_price])
                if available <= 0:
                    continue
                qty = min(available, remaining)
                orders.append(Order(product, int(ask_price), int(qty)))
                remaining -= qty
        else:
            remaining = min(-delta, POSITION_LIMIT + int(position))
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                available = int(order_depth.buy_orders[bid_price])
                if available <= 0:
                    continue
                qty = min(available, remaining)
                orders.append(Order(product, int(bid_price), -int(qty)))
                remaining -= qty
        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        for product, target in TARGETS.items():
            if target == 0 or product not in state.order_depths:
                continue
            orders = self._walk_to_target(product, state.order_depths[product], state.position.get(product, 0), target)
            if orders:
                result[product] = orders
        return result, 0, state.traderData or ""
