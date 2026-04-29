from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple

POSITION_LIMIT = 10

# Round 5 All-Groups Long/Short v2 Wide/Non-Gated
# Static all-groups long/short basket.
# This is intentionally non-gated: the edge in historical replay came from entering
# the selected cross-sectional basket early, not from waiting for rolling signals.
# Every target is clamped to the Round 5 +/-10 product limit.

TARGETS: Dict[str, int] = {'GALAXY_SOUNDS_BLACK_HOLES': 10,
 'GALAXY_SOUNDS_DARK_MATTER': 10,
 'GALAXY_SOUNDS_PLANETARY_RINGS': -10,
 'GALAXY_SOUNDS_SOLAR_FLAMES': 10,
 'GALAXY_SOUNDS_SOLAR_WINDS': 10,
 'MICROCHIP_CIRCLE': 10,
 'MICROCHIP_OVAL': -10,
 'MICROCHIP_RECTANGLE': -10,
 'MICROCHIP_SQUARE': 10,
 'MICROCHIP_TRIANGLE': -10,
 'OXYGEN_SHAKE_CHOCOLATE': 10,
 'OXYGEN_SHAKE_EVENING_BREATH': -10,
 'OXYGEN_SHAKE_GARLIC': 10,
 'OXYGEN_SHAKE_MINT': 10,
 'OXYGEN_SHAKE_MORNING_BREATH': -10,
 'PANEL_1X2': -10,
 'PANEL_1X4': -10,
 'PANEL_2X2': -10,
 'PANEL_2X4': 10,
 'PANEL_4X4': -10,
 'PEBBLES_L': -10,
 'PEBBLES_M': 10,
 'PEBBLES_S': -10,
 'PEBBLES_XL': 10,
 'PEBBLES_XS': -10,
 'ROBOT_DISHES': 10,
 'ROBOT_IRONING': -10,
 'ROBOT_LAUNDRY': -10,
 'ROBOT_MOPPING': 10,
 'ROBOT_VACUUMING': -10,
 'SLEEP_POD_COTTON': 10,
 'SLEEP_POD_LAMB_WOOL': 10,
 'SLEEP_POD_NYLON': 10,
 'SLEEP_POD_POLYESTER': 10,
 'SLEEP_POD_SUEDE': 10,
 'SNACKPACK_CHOCOLATE': -10,
 'SNACKPACK_PISTACHIO': -10,
 'SNACKPACK_RASPBERRY': 10,
 'SNACKPACK_STRAWBERRY': 10,
 'SNACKPACK_VANILLA': 10,
 'TRANSLATOR_ASTRO_BLACK': -10,
 'TRANSLATOR_ECLIPSE_CHARCOAL': -10,
 'TRANSLATOR_GRAPHITE_MIST': -10,
 'TRANSLATOR_SPACE_GRAY': -10,
 'TRANSLATOR_VOID_BLUE': 10,
 'UV_VISOR_AMBER': -10,
 'UV_VISOR_MAGENTA': 10,
 'UV_VISOR_ORANGE': -10,
 'UV_VISOR_RED': 10,
 'UV_VISOR_YELLOW': 10}

PRODUCT_GROUP: Dict[str, str] = {'GALAXY_SOUNDS_BLACK_HOLES': 'Galaxy',
 'GALAXY_SOUNDS_DARK_MATTER': 'Galaxy',
 'GALAXY_SOUNDS_PLANETARY_RINGS': 'Galaxy',
 'GALAXY_SOUNDS_SOLAR_FLAMES': 'Galaxy',
 'GALAXY_SOUNDS_SOLAR_WINDS': 'Galaxy',
 'MICROCHIP_CIRCLE': 'Microchip',
 'MICROCHIP_OVAL': 'Microchip',
 'MICROCHIP_RECTANGLE': 'Microchip',
 'MICROCHIP_SQUARE': 'Microchip',
 'MICROCHIP_TRIANGLE': 'Microchip',
 'OXYGEN_SHAKE_CHOCOLATE': 'Oxygen',
 'OXYGEN_SHAKE_EVENING_BREATH': 'Oxygen',
 'OXYGEN_SHAKE_GARLIC': 'Oxygen',
 'OXYGEN_SHAKE_MINT': 'Oxygen',
 'OXYGEN_SHAKE_MORNING_BREATH': 'Oxygen',
 'PANEL_1X2': 'Panel',
 'PANEL_1X4': 'Panel',
 'PANEL_2X2': 'Panel',
 'PANEL_2X4': 'Panel',
 'PANEL_4X4': 'Panel',
 'PEBBLES_L': 'Pebbles',
 'PEBBLES_M': 'Pebbles',
 'PEBBLES_S': 'Pebbles',
 'PEBBLES_XL': 'Pebbles',
 'PEBBLES_XS': 'Pebbles',
 'ROBOT_DISHES': 'Robot',
 'ROBOT_IRONING': 'Robot',
 'ROBOT_LAUNDRY': 'Robot',
 'ROBOT_MOPPING': 'Robot',
 'ROBOT_VACUUMING': 'Robot',
 'SLEEP_POD_COTTON': 'Sleep',
 'SLEEP_POD_LAMB_WOOL': 'Sleep',
 'SLEEP_POD_NYLON': 'Sleep',
 'SLEEP_POD_POLYESTER': 'Sleep',
 'SLEEP_POD_SUEDE': 'Sleep',
 'SNACKPACK_CHOCOLATE': 'Snack',
 'SNACKPACK_PISTACHIO': 'Snack',
 'SNACKPACK_RASPBERRY': 'Snack',
 'SNACKPACK_STRAWBERRY': 'Snack',
 'SNACKPACK_VANILLA': 'Snack',
 'TRANSLATOR_ASTRO_BLACK': 'Translator',
 'TRANSLATOR_ECLIPSE_CHARCOAL': 'Translator',
 'TRANSLATOR_GRAPHITE_MIST': 'Translator',
 'TRANSLATOR_SPACE_GRAY': 'Translator',
 'TRANSLATOR_VOID_BLUE': 'Translator',
 'UV_VISOR_AMBER': 'UV',
 'UV_VISOR_MAGENTA': 'UV',
 'UV_VISOR_ORANGE': 'UV',
 'UV_VISOR_RED': 'UV',
 'UV_VISOR_YELLOW': 'UV'}

GROUP_MAX_CROSS_SPREAD: Dict[str, int] = {
    "Galaxy": 40,
    "Sleep": 35,
    "Microchip": 35,
    "Pebbles": 40,
    "Robot": 35,
    "UV": 40,
    "Translator": 35,
    "Panel": 35,
    "Oxygen": 40,
    "Snack": 35,
}

DEFAULT_MAX_CROSS_SPREAD = 40


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

    def _max_spread_for(self, product: str) -> int:
        group = PRODUCT_GROUP.get(product, "")
        return int(GROUP_MAX_CROSS_SPREAD.get(group, DEFAULT_MAX_CROSS_SPREAD))

    def _walk_to_target(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
    ) -> List[Order]:
        target = self._clamp_target(target)
        position = int(position)
        delta = target - position
        if delta == 0:
            return []

        best_bid, best_ask = self._best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return []

        if int(best_ask) - int(best_bid) > self._max_spread_for(product):
            return []

        orders: List[Order] = []

        if delta > 0:
            remaining = min(delta, POSITION_LIMIT - position)
            for ask_price in sorted(order_depth.sell_orders):
                if remaining <= 0:
                    break
                available = -int(order_depth.sell_orders[ask_price])
                if available <= 0:
                    continue
                qty = min(available, remaining)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    remaining -= qty
        else:
            remaining = min(-delta, POSITION_LIMIT + position)
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                available = int(order_depth.buy_orders[bid_price])
                if available <= 0:
                    continue
                qty = min(available, remaining)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    remaining -= qty

        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        # Submit orders only for products with target != 0 and a visible order book.
        for product, target in TARGETS.items():
            if target == 0 or product not in state.order_depths:
                continue
            orders = self._walk_to_target(
                product,
                state.order_depths[product],
                state.position.get(product, 0),
                target,
            )
            if orders:
                result[product] = orders

        return result, 0, state.traderData or ""
