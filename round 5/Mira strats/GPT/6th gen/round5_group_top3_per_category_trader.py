from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple

POSITION_LIMIT = 10

# Round 5 Group Top-3 Per Category: one different group-level variation selecting the strongest 2-3 names per category.
# Active idea: cross to the selected target only; no passive market making.
# This intentionally keeps state empty. It is robust to traderData size limits
# and avoids churn from rolling gates.

TARGETS: Dict[str, int] = {'GALAXY_SOUNDS_BLACK_HOLES': 10,
 'GALAXY_SOUNDS_PLANETARY_RINGS': -3,
 'GALAXY_SOUNDS_SOLAR_FLAMES': 10,
 'MICROCHIP_OVAL': -10,
 'MICROCHIP_SQUARE': 10,
 'MICROCHIP_TRIANGLE': -5,
 'OXYGEN_SHAKE_CHOCOLATE': 3,
 'OXYGEN_SHAKE_EVENING_BREATH': -5,
 'OXYGEN_SHAKE_GARLIC': 10,
 'PANEL_1X4': -3,
 'PANEL_2X4': 10,
 'PANEL_4X4': -10,
 'PEBBLES_S': -5,
 'PEBBLES_XL': 10,
 'PEBBLES_XS': -10,
 'ROBOT_IRONING': -10,
 'ROBOT_MOPPING': 5,
 'ROBOT_VACUUMING': -10,
 'SLEEP_POD_COTTON': 5,
 'SLEEP_POD_POLYESTER': 10,
 'SLEEP_POD_SUEDE': 10,
 'SNACKPACK_CHOCOLATE': -5,
 'SNACKPACK_PISTACHIO': -10,
 'SNACKPACK_STRAWBERRY': 10,
 'TRANSLATOR_ASTRO_BLACK': -5,
 'TRANSLATOR_SPACE_GRAY': -10,
 'TRANSLATOR_VOID_BLUE': 10,
 'UV_VISOR_AMBER': -10,
 'UV_VISOR_MAGENTA': 5,
 'UV_VISOR_RED': 10}

PRODUCT_GROUP: Dict[str, str] = {'GALAXY_SOUNDS_BLACK_HOLES': 'GALAXY',
 'GALAXY_SOUNDS_DARK_MATTER': 'GALAXY',
 'GALAXY_SOUNDS_PLANETARY_RINGS': 'GALAXY',
 'GALAXY_SOUNDS_SOLAR_FLAMES': 'GALAXY',
 'GALAXY_SOUNDS_SOLAR_WINDS': 'GALAXY',
 'MICROCHIP_CIRCLE': 'MICROCHIP',
 'MICROCHIP_OVAL': 'MICROCHIP',
 'MICROCHIP_RECTANGLE': 'MICROCHIP',
 'MICROCHIP_SQUARE': 'MICROCHIP',
 'MICROCHIP_TRIANGLE': 'MICROCHIP',
 'OXYGEN_SHAKE_CHOCOLATE': 'OXYGEN',
 'OXYGEN_SHAKE_EVENING_BREATH': 'OXYGEN',
 'OXYGEN_SHAKE_GARLIC': 'OXYGEN',
 'OXYGEN_SHAKE_MINT': 'OXYGEN',
 'OXYGEN_SHAKE_MORNING_BREATH': 'OXYGEN',
 'PANEL_1X2': 'PANEL',
 'PANEL_1X4': 'PANEL',
 'PANEL_2X2': 'PANEL',
 'PANEL_2X4': 'PANEL',
 'PANEL_4X4': 'PANEL',
 'PEBBLES_L': 'PEBBLES',
 'PEBBLES_M': 'PEBBLES',
 'PEBBLES_S': 'PEBBLES',
 'PEBBLES_XL': 'PEBBLES',
 'PEBBLES_XS': 'PEBBLES',
 'ROBOT_DISHES': 'ROBOT',
 'ROBOT_IRONING': 'ROBOT',
 'ROBOT_LAUNDRY': 'ROBOT',
 'ROBOT_MOPPING': 'ROBOT',
 'ROBOT_VACUUMING': 'ROBOT',
 'SLEEP_POD_COTTON': 'SLEEP',
 'SLEEP_POD_LAMB_WOOL': 'SLEEP',
 'SLEEP_POD_NYLON': 'SLEEP',
 'SLEEP_POD_POLYESTER': 'SLEEP',
 'SLEEP_POD_SUEDE': 'SLEEP',
 'SNACKPACK_CHOCOLATE': 'SNACK',
 'SNACKPACK_PISTACHIO': 'SNACK',
 'SNACKPACK_RASPBERRY': 'SNACK',
 'SNACKPACK_STRAWBERRY': 'SNACK',
 'SNACKPACK_VANILLA': 'SNACK',
 'TRANSLATOR_ASTRO_BLACK': 'TRANSLATOR',
 'TRANSLATOR_ECLIPSE_CHARCOAL': 'TRANSLATOR',
 'TRANSLATOR_GRAPHITE_MIST': 'TRANSLATOR',
 'TRANSLATOR_SPACE_GRAY': 'TRANSLATOR',
 'TRANSLATOR_VOID_BLUE': 'TRANSLATOR',
 'UV_VISOR_AMBER': 'UV',
 'UV_VISOR_MAGENTA': 'UV',
 'UV_VISOR_ORANGE': 'UV',
 'UV_VISOR_RED': 'UV',
 'UV_VISOR_YELLOW': 'UV'}

GROUP_MAX_SPREAD: Dict[str, int] = {'GALAXY': 40,
 'MICROCHIP': 30,
 'OXYGEN': 40,
 'PANEL': 30,
 'PEBBLES': 40,
 'ROBOT': 30,
 'SLEEP': 30,
 'SNACK': 35,
 'TRANSLATOR': 25,
 'UV': 35}


class Trader:
    def bid(self):
        return 15

    @staticmethod
    def _best_bid_ask(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None
        return best_bid, best_ask

    @staticmethod
    def _clamp(x: int) -> int:
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, int(x)))

    def _walk_to_target(self, product: str, depth: OrderDepth, position: int, target: int) -> List[Order]:
        target = self._clamp(target)
        position = int(position)
        delta = target - position
        if delta == 0:
            return []

        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return []

        group = PRODUCT_GROUP.get(product, "")
        max_spread = GROUP_MAX_SPREAD.get(group, 35)
        if int(best_ask) - int(best_bid) > max_spread:
            return []

        orders: List[Order] = []

        if delta > 0:
            remaining = min(delta, POSITION_LIMIT - position)
            for ask_price, ask_qty_neg in sorted(depth.sell_orders.items()):
                if remaining <= 0:
                    break
                available = -int(ask_qty_neg)
                if available <= 0:
                    continue
                qty = min(available, remaining)
                orders.append(Order(product, int(ask_price), int(qty)))
                remaining -= qty
        else:
            remaining = min(-delta, POSITION_LIMIT + position)
            for bid_price, bid_qty in sorted(depth.buy_orders.items(), reverse=True):
                if remaining <= 0:
                    break
                available = int(bid_qty)
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
            orders = self._walk_to_target(
                product,
                state.order_depths[product],
                int(state.position.get(product, 0)),
                int(target),
            )
            if orders:
                result[product] = orders

        return result, 0, state.traderData or ""
