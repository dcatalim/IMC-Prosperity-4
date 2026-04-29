from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple


POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 40

# Different idea from Round5_Codex_V1:
# Cross-sectional relative strength inside each 5-product category.
#
# For every group, products are compared to their own category average, not to
# the whole market.  Longs are the relative leaders; shorts are the laggards.
# Products close to the group average are left flat.  This trades the group
# structure directly and is less dependent on the whole market drifting up/down.
GROUP_TARGETS: Dict[str, Dict[str, int]] = {
    # Galaxy recordings: one clear relative leader, several laggards.
    "GALAXY": {
        "GALAXY_SOUNDS_BLACK_HOLES": 10,
        "GALAXY_SOUNDS_DARK_MATTER": -10,
        "GALAXY_SOUNDS_PLANETARY_RINGS": -10,
        "GALAXY_SOUNDS_SOLAR_FLAMES": 0,
        "GALAXY_SOUNDS_SOLAR_WINDS": -10,
    },

    # Sleep pods: material spread.  Polyester/suede lead; lamb wool/nylon lag.
    "SLEEP": {
        "SLEEP_POD_COTTON": 0,
        "SLEEP_POD_LAMB_WOOL": -10,
        "SLEEP_POD_NYLON": -10,
        "SLEEP_POD_POLYESTER": 10,
        "SLEEP_POD_SUEDE": 10,
    },

    # Organic microchips: circle/square lead the shape complex.
    "MICROCHIP": {
        "MICROCHIP_CIRCLE": 10,
        "MICROCHIP_OVAL": -10,
        "MICROCHIP_RECTANGLE": -10,
        "MICROCHIP_SQUARE": 10,
        "MICROCHIP_TRIANGLE": -10,
    },

    # Pebbles: size curve.  M/XL outperform; XS/S/L lag.
    "PEBBLES": {
        "PEBBLES_XS": -10,
        "PEBBLES_S": -10,
        "PEBBLES_M": 10,
        "PEBBLES_L": -10,
        "PEBBLES_XL": 10,
    },

    # Domestic robots: dishes/mopping lead; vacuuming/laundry/ironing lag.
    "ROBOT": {
        "ROBOT_DISHES": 10,
        "ROBOT_IRONING": -10,
        "ROBOT_LAUNDRY": -10,
        "ROBOT_MOPPING": 10,
        "ROBOT_VACUUMING": -10,
    },

    # UV-visors: red/magenta relative strength, amber/orange weakness.
    "UV": {
        "UV_VISOR_AMBER": -10,
        "UV_VISOR_MAGENTA": 10,
        "UV_VISOR_ORANGE": -10,
        "UV_VISOR_RED": 10,
        "UV_VISOR_YELLOW": 0,
    },

    # Translators: void blue leads, astro black and space gray lag.
    "TRANSLATOR": {
        "TRANSLATOR_ASTRO_BLACK": -10,
        "TRANSLATOR_ECLIPSE_CHARCOAL": 0,
        "TRANSLATOR_GRAPHITE_MIST": 0,
        "TRANSLATOR_SPACE_GRAY": -10,
        "TRANSLATOR_VOID_BLUE": 10,
    },

    # Construction panels: 2x4 is the relative winner; rest are laggards.
    "PANEL": {
        "PANEL_1X2": -10,
        "PANEL_1X4": -10,
        "PANEL_2X2": -10,
        "PANEL_2X4": 10,
        "PANEL_4X4": -10,
    },

    # Oxygen shakes: garlic leads; morning/evening/mint lag the category.
    "OXYGEN": {
        "OXYGEN_SHAKE_CHOCOLATE": 0,
        "OXYGEN_SHAKE_EVENING_BREATH": -10,
        "OXYGEN_SHAKE_GARLIC": 10,
        "OXYGEN_SHAKE_MINT": -10,
        "OXYGEN_SHAKE_MORNING_BREATH": -10,
    },

    # Snack packs: fruit/vanilla strength, chocolate/pistachio weakness.
    "SNACK": {
        "SNACKPACK_CHOCOLATE": -10,
        "SNACKPACK_PISTACHIO": -10,
        "SNACKPACK_RASPBERRY": 10,
        "SNACKPACK_STRAWBERRY": 10,
        "SNACKPACK_VANILLA": 10,
    },
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
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, target))

    def _walk_to_target(
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

        best_bid, best_ask = self._best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return []

        if best_ask - best_bid > MAX_CROSS_SPREAD:
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
