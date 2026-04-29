from datamodel import Order, OrderDepth, TradingState
import json
from typing import Dict, List, Optional, Tuple


POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 35
CORE_SCALE = 0.80
EXTENDED_SCALE = 0.60


RAW_CORE_TARGETS = {
    "GALAXY_SOUNDS_BLACK_HOLES": 10,
    "MICROCHIP_OVAL": -10,
    "OXYGEN_SHAKE_GARLIC": 10,
    "PANEL_2X4": 10,
    "PEBBLES_S": -10,
    "PEBBLES_XS": -10,
    "ROBOT_DISHES": 10,
    "SNACKPACK_CHOCOLATE": -10,
    "SNACKPACK_PISTACHIO": -10,
    "SNACKPACK_STRAWBERRY": 10,
    "UV_VISOR_MAGENTA": 10,
    "UV_VISOR_RED": 10,
}

RAW_EXTENDED_TARGETS = {
    "GALAXY_SOUNDS_DARK_MATTER": -10,
    "GALAXY_SOUNDS_PLANETARY_RINGS": -10,
    "GALAXY_SOUNDS_SOLAR_WINDS": -10,
    "SLEEP_POD_LAMB_WOOL": -10,
    "SLEEP_POD_NYLON": -10,
    "SLEEP_POD_POLYESTER": 10,
    "SLEEP_POD_SUEDE": 10,
    "MICROCHIP_CIRCLE": 10,
    "MICROCHIP_RECTANGLE": -10,
    "MICROCHIP_SQUARE": 10,
    "MICROCHIP_TRIANGLE": -10,
    "PEBBLES_M": 10,
    "PEBBLES_L": -10,
    "PEBBLES_XL": 10,
    "ROBOT_IRONING": -10,
    "ROBOT_LAUNDRY": -10,
    "ROBOT_MOPPING": 10,
    "ROBOT_VACUUMING": -10,
    "UV_VISOR_AMBER": -10,
    "UV_VISOR_ORANGE": -10,
    "TRANSLATOR_ASTRO_BLACK": -10,
    "TRANSLATOR_SPACE_GRAY": -10,
    "TRANSLATOR_VOID_BLUE": 10,
    "PANEL_1X2": -10,
    "PANEL_1X4": -10,
    "PANEL_2X2": -10,
    "PANEL_4X4": -10,
    "OXYGEN_SHAKE_EVENING_BREATH": -10,
    "OXYGEN_SHAKE_MINT": -10,
    "OXYGEN_SHAKE_MORNING_BREATH": -10,
    "SNACKPACK_RASPBERRY": 10,
    "SNACKPACK_VANILLA": 10,
}


def scale_targets(targets: Dict[str, int], scale: float) -> Dict[str, int]:
    scaled = {}
    for product, target in targets.items():
        if target == 0:
            continue
        magnitude = max(1, int(round(abs(target) * scale)))
        scaled[product] = magnitude if target > 0 else -magnitude
    return scaled


CORE_TARGETS = scale_targets(RAW_CORE_TARGETS, CORE_SCALE)
EXTENDED_TARGETS = scale_targets(RAW_EXTENDED_TARGETS, EXTENDED_SCALE)


class Trader:
    def _restore(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"anchor": {}, "gate": False}
        try:
            data = json.loads(trader_data)
        except Exception:
            return {"anchor": {}, "gate": False}
        if not isinstance(data, dict):
            return {"anchor": {}, "gate": False}
        data.setdefault("anchor", {})
        data.setdefault("gate", False)
        return data

    def _mid(self, depth: OrderDepth) -> Optional[float]:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        return (max(depth.buy_orders) + min(depth.sell_orders)) / 2.0

    def _paper_pnl(self, anchor: Dict[str, float], mids: Dict[str, float]) -> Tuple[float, int]:
        pnl = 0.0
        gross = 0
        for product, target in EXTENDED_TARGETS.items():
            start = anchor.get(product)
            mid = mids.get(product)
            if start is None or mid is None:
                continue
            pnl += target * (mid - start)
            gross += abs(target)
        return pnl, gross

    def _target_position(self, product: str, gate_open: bool) -> int:
        target = CORE_TARGETS.get(product, 0)
        if gate_open:
            target += EXTENDED_TARGETS.get(product, 0)
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, target))

    def _liquidity_to_target(self, product: str, depth: OrderDepth, position: int, target: int) -> List[Order]:
        orders: List[Order] = []
        delta = target - position
        if delta == 0 or not depth.buy_orders or not depth.sell_orders:
            return orders

        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        if best_ask - best_bid > MAX_CROSS_SPREAD:
            return orders

        if delta > 0:
            remaining = delta
            for price in sorted(depth.sell_orders):
                if remaining <= 0:
                    break
                available = -depth.sell_orders[price]
                quantity = min(remaining, available)
                if quantity > 0:
                    orders.append(Order(product, price, quantity))
                    remaining -= quantity
        else:
            remaining = -delta
            for price in sorted(depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                available = depth.buy_orders[price]
                quantity = min(remaining, available)
                if quantity > 0:
                    orders.append(Order(product, price, -quantity))
                    remaining -= quantity

        return orders

    def run(self, state: TradingState):
        memory = self._restore(state.traderData)
        anchor = memory["anchor"]

        mids: Dict[str, float] = {}
        for product, depth in state.order_depths.items():
            mid = self._mid(depth)
            if mid is None:
                continue
            mids[product] = mid
            anchor.setdefault(product, mid)

        paper_pnl, gross = self._paper_pnl(anchor, mids)
        if gross:
            # Relative strength signals are noisy early, so this variant waits longer.
            open_threshold = max(1400.0, 58.0 * gross)
            if paper_pnl > open_threshold:
                memory["gate"] = True

        gate_open = bool(memory.get("gate", False))
        result: Dict[str, List[Order]] = {}
        products = set(CORE_TARGETS) | set(EXTENDED_TARGETS)
        for product in products:
            depth = state.order_depths.get(product)
            if depth is None:
                continue
            position = state.position.get(product, 0)
            target = self._target_position(product, gate_open)
            orders = self._liquidity_to_target(product, depth, position, target)
            if orders:
                result[product] = orders

        memory["anchor"] = anchor
        return result, 0, json.dumps(memory, separators=(",", ":"))
