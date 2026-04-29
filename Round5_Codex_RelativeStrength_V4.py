from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple
import json


POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 40

CORE_TARGETS: Dict[str, int] = {
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

EXTENDED_TARGETS: Dict[str, int] = {
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

ALL_TARGETS = {**CORE_TARGETS, **EXTENDED_TARGETS}


class Trader:
    EMA_ALPHA = 0.08

    @staticmethod
    def _best_bid_ask(depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None
        return best_bid, best_ask

    @staticmethod
    def _mid(depth: OrderDepth) -> Optional[float]:
        best_bid, best_ask = Trader._best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return None
        return (best_bid + best_ask) / 2.0

    @staticmethod
    def _load(trader_data: str) -> Dict:
        if trader_data:
            try:
                data = json.loads(trader_data)
                if isinstance(data, dict):
                    data.setdefault("a", {})
                    data.setdefault("g", {"min": 0.0, "ema": 0.0, "active": 0})
                    return data
            except Exception:
                pass
        return {"a": {}, "g": {"min": 0.0, "ema": 0.0, "active": 0}}

    @staticmethod
    def _save(data: Dict) -> str:
        return json.dumps(data, separators=(",", ":"))

    @staticmethod
    def _clamp(target: int) -> int:
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, int(target)))

    def _extended_gate(self, data: Dict, mids: Dict[str, float]) -> bool:
        gate = data["g"]
        if int(gate.get("active", 0)) == 1:
            return True
        paper = 0.0
        gross = 0
        for product, target in EXTENDED_TARGETS.items():
            if product not in mids:
                continue
            anchor = float(data["a"].get(product, mids[product]))
            paper += target * (mids[product] - anchor)
            gross += abs(target)
        gate["min"] = min(float(gate.get("min", paper)), paper)
        gate["ema"] = self.EMA_ALPHA * paper + (1.0 - self.EMA_ALPHA) * float(gate.get("ema", paper))
        turnup = paper - float(gate["min"])
        momentum = paper - float(gate["ema"])
        threshold = max(1200.0, 38.0 * gross)
        active = (paper >= threshold and momentum >= 0.0) or (turnup >= threshold and momentum >= max(140.0, 4.0 * gross))
        gate["active"] = 1 if active else 0
        return active

    def _walk_to_target(self, product: str, depth: OrderDepth, position: int, target: int) -> List[Order]:
        target = self._clamp(target)
        delta = target - int(position)
        if delta == 0:
            return []
        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None or best_ask is None or best_ask - best_bid > MAX_CROSS_SPREAD:
            return []
        orders: List[Order] = []
        if delta > 0:
            remaining = min(delta, POSITION_LIMIT - int(position))
            for ask_price in sorted(depth.sell_orders):
                if remaining <= 0:
                    break
                qty = min(-int(depth.sell_orders[ask_price]), remaining)
                if qty > 0:
                    orders.append(Order(product, int(ask_price), int(qty)))
                    remaining -= qty
        else:
            remaining = min(-delta, POSITION_LIMIT + int(position))
            for bid_price in sorted(depth.buy_orders, reverse=True):
                if remaining <= 0:
                    break
                qty = min(int(depth.buy_orders[bid_price]), remaining)
                if qty > 0:
                    orders.append(Order(product, int(bid_price), -int(qty)))
                    remaining -= qty
        return orders

    def run(self, state: TradingState):
        data = self._load(state.traderData)
        mids: Dict[str, float] = {}
        for product, depth in state.order_depths.items():
            mid = self._mid(depth)
            if mid is not None:
                mids[product] = mid
                data["a"].setdefault(product, mid)

        targets = dict(CORE_TARGETS)
        if self._extended_gate(data, mids):
            targets.update(EXTENDED_TARGETS)

        result: Dict[str, List[Order]] = {}
        for product, depth in state.order_depths.items():
            position = int(state.position.get(product, 0))
            target = targets.get(product)
            if target is None:
                target = position if product in ALL_TARGETS and position != 0 else 0
            orders = self._walk_to_target(product, depth, position, target)
            if orders:
                result[product] = orders
        return result, 0, self._save(data)
