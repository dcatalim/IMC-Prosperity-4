from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple


POSITION_LIMIT = 10

# Round 5 Relative Strength V2
# Base idea: Codex cross-sectional relative strength inside each 5-product category.
# Changes vs Codex base:
# - keep the strongest static group relative targets;
# - remove or flip products whose Codex direction was consistently weak in days 2-4;
# - use group-specific max spread guards;
# - still no market making and no traderData dependency.
#
# This intentionally stays close to the Codex structure because that performed better
# in the real simulator than my earlier relative-strength attempt.
GROUP_MAX_SPREAD: Dict[str, int] = {
    "GALAXY": 40,
    "SLEEP": 30,
    "MICROCHIP": 30,
    "PEBBLES": 40,
    "ROBOT": 30,
    "UV": 35,
    "TRANSLATOR": 25,
    "PANEL": 30,
    "OXYGEN": 40,
    "SNACK": 35,
}

GROUP_TARGETS: Dict[str, Dict[str, int]] = {'GALAXY': {'GALAXY_SOUNDS_BLACK_HOLES': 10,
            'GALAXY_SOUNDS_DARK_MATTER': 0,
            'GALAXY_SOUNDS_PLANETARY_RINGS': 0,
            'GALAXY_SOUNDS_SOLAR_FLAMES': 0,
            'GALAXY_SOUNDS_SOLAR_WINDS': 0},
 'MICROCHIP': {'MICROCHIP_CIRCLE': 0,
               'MICROCHIP_OVAL': -10,
               'MICROCHIP_RECTANGLE': -10,
               'MICROCHIP_SQUARE': 10,
               'MICROCHIP_TRIANGLE': -10},
 'OXYGEN': {'OXYGEN_SHAKE_CHOCOLATE': 0,
            'OXYGEN_SHAKE_EVENING_BREATH': 0,
            'OXYGEN_SHAKE_GARLIC': 10,
            'OXYGEN_SHAKE_MINT': 0,
            'OXYGEN_SHAKE_MORNING_BREATH': 0},
 'PANEL': {'PANEL_1X2': -10, 'PANEL_1X4': 0, 'PANEL_2X2': -10, 'PANEL_2X4': 10, 'PANEL_4X4': -10},
 'PEBBLES': {'PEBBLES_L': -10, 'PEBBLES_M': 10, 'PEBBLES_S': -10, 'PEBBLES_XL': 10, 'PEBBLES_XS': -10},
 'ROBOT': {'ROBOT_DISHES': 10, 'ROBOT_IRONING': -10, 'ROBOT_LAUNDRY': -10, 'ROBOT_MOPPING': 10, 'ROBOT_VACUUMING': -10},
 'SLEEP': {'SLEEP_POD_COTTON': 0,
           'SLEEP_POD_LAMB_WOOL': 10,
           'SLEEP_POD_NYLON': 0,
           'SLEEP_POD_POLYESTER': 10,
           'SLEEP_POD_SUEDE': 10},
 'SNACK': {'SNACKPACK_CHOCOLATE': -10,
           'SNACKPACK_PISTACHIO': -10,
           'SNACKPACK_RASPBERRY': 10,
           'SNACKPACK_STRAWBERRY': 10,
           'SNACKPACK_VANILLA': 10},
 'TRANSLATOR': {'TRANSLATOR_ASTRO_BLACK': -10,
                'TRANSLATOR_ECLIPSE_CHARCOAL': 0,
                'TRANSLATOR_GRAPHITE_MIST': 0,
                'TRANSLATOR_SPACE_GRAY': -10,
                'TRANSLATOR_VOID_BLUE': 10},
 'UV': {'UV_VISOR_AMBER': -10,
        'UV_VISOR_MAGENTA': 10,
        'UV_VISOR_ORANGE': -10,
        'UV_VISOR_RED': 10,
        'UV_VISOR_YELLOW': 0}}

PRODUCT_TO_GROUP: Dict[str, str] = {
    product: group
    for group, targets in GROUP_TARGETS.items()
    for product in targets
}

RELATIVE_TARGETS: Dict[str, int] = {
    product: target
    for group_targets in GROUP_TARGETS.values()
    for product, target in group_targets.items()
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

    def _walk_to_target(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
    ) -> List[Order]:
        target = self._clamp_target(target)
        delta = target - int(position)
        if delta == 0:
            return []

        best_bid, best_ask = self._best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return []

        group = PRODUCT_TO_GROUP.get(product, "")
        max_spread = GROUP_MAX_SPREAD.get(group, 30)
        if best_ask - best_bid > max_spread:
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
                quantity = min(available, remaining)
                orders.append(Order(product, int(ask_price), int(quantity)))
                remaining -= quantity
        else:
            remaining = min(-delta, POSITION_LIMIT + int(position))
            for bid_price in sorted(order_depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                available = int(order_depth.buy_orders[bid_price])
                if available <= 0:
                    continue
                quantity = min(available, remaining)
                orders.append(Order(product, int(bid_price), -int(quantity)))
                remaining -= quantity

        return orders

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product, target in RELATIVE_TARGETS.items():
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
