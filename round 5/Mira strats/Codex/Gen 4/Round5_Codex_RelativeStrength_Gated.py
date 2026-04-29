from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple
import json


POSITION_LIMIT = 10
MAX_CROSS_SPREAD = 40

GROUP_TARGETS: Dict[str, Dict[str, int]] = {
    "GALAXY": {
        "GALAXY_SOUNDS_BLACK_HOLES": 10,
        "GALAXY_SOUNDS_DARK_MATTER": -10,
        "GALAXY_SOUNDS_PLANETARY_RINGS": -10,
        "GALAXY_SOUNDS_SOLAR_FLAMES": 0,
        "GALAXY_SOUNDS_SOLAR_WINDS": -10,
    },
    "SLEEP": {
        "SLEEP_POD_COTTON": 0,
        "SLEEP_POD_LAMB_WOOL": -10,
        "SLEEP_POD_NYLON": -10,
        "SLEEP_POD_POLYESTER": 10,
        "SLEEP_POD_SUEDE": 10,
    },
    "MICROCHIP": {
        "MICROCHIP_CIRCLE": 10,
        "MICROCHIP_OVAL": -10,
        "MICROCHIP_RECTANGLE": -10,
        "MICROCHIP_SQUARE": 10,
        "MICROCHIP_TRIANGLE": -10,
    },
    "PEBBLES": {
        "PEBBLES_XS": -10,
        "PEBBLES_S": -10,
        "PEBBLES_M": 10,
        "PEBBLES_L": -10,
        "PEBBLES_XL": 10,
    },
    "ROBOT": {
        "ROBOT_DISHES": 10,
        "ROBOT_IRONING": -10,
        "ROBOT_LAUNDRY": -10,
        "ROBOT_MOPPING": 10,
        "ROBOT_VACUUMING": -10,
    },
    "UV": {
        "UV_VISOR_AMBER": -10,
        "UV_VISOR_MAGENTA": 10,
        "UV_VISOR_ORANGE": -10,
        "UV_VISOR_RED": 10,
        "UV_VISOR_YELLOW": 0,
    },
    "TRANSLATOR": {
        "TRANSLATOR_ASTRO_BLACK": -10,
        "TRANSLATOR_ECLIPSE_CHARCOAL": 0,
        "TRANSLATOR_GRAPHITE_MIST": 0,
        "TRANSLATOR_SPACE_GRAY": -10,
        "TRANSLATOR_VOID_BLUE": 10,
    },
    "PANEL": {
        "PANEL_1X2": -10,
        "PANEL_1X4": -10,
        "PANEL_2X2": -10,
        "PANEL_2X4": 10,
        "PANEL_4X4": -10,
    },
    "OXYGEN": {
        "OXYGEN_SHAKE_CHOCOLATE": 0,
        "OXYGEN_SHAKE_EVENING_BREATH": -10,
        "OXYGEN_SHAKE_GARLIC": 10,
        "OXYGEN_SHAKE_MINT": -10,
        "OXYGEN_SHAKE_MORNING_BREATH": -10,
    },
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
    for targets in GROUP_TARGETS.values()
    for product, target in targets.items()
}


class Trader:
    EMA_ALPHA = 0.08

    @staticmethod
    def _best_bid_ask(order_depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        return best_bid, best_ask

    @staticmethod
    def _mid(order_depth: OrderDepth) -> Optional[float]:
        best_bid, best_ask = Trader._best_bid_ask(order_depth)
        if best_bid is None or best_ask is None:
            return None
        return (best_bid + best_ask) / 2.0

    @staticmethod
    def _clamp_target(target: int) -> int:
        return max(-POSITION_LIMIT, min(POSITION_LIMIT, target))

    @staticmethod
    def _load(trader_data: str) -> Dict:
        if trader_data:
            try:
                data = json.loads(trader_data)
                if isinstance(data, dict):
                    data.setdefault("anchor", {})
                    data.setdefault("group", {})
                    return data
            except Exception:
                pass
        return {"anchor": {}, "group": {}}

    @staticmethod
    def _save(data: Dict) -> str:
        return json.dumps(data, separators=(",", ":"))

    def _update_group_gate(self, data: Dict, group: str, paper_pnl: float, gross: int) -> bool:
        state = data["group"].setdefault(
            group,
            {"min": paper_pnl, "ema": paper_pnl, "active": 0},
        )

        if int(state.get("active", 0)) == 1:
            return True

        state["min"] = min(float(state["min"]), paper_pnl)
        state["ema"] = self.EMA_ALPHA * paper_pnl + (1.0 - self.EMA_ALPHA) * float(state["ema"])

        turnup_threshold = max(1400.0, 42.0 * gross)
        momentum_threshold = max(170.0, 5.0 * gross)

        turnup = paper_pnl - float(state["min"])
        momentum = paper_pnl - float(state["ema"])

        active = (
            turnup >= turnup_threshold and momentum >= momentum_threshold
        ) or (
            paper_pnl >= turnup_threshold and momentum >= 0.0
        )

        state["active"] = 1 if active else 0
        return active

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
        data = self._load(state.traderData)
        result: Dict[str, List[Order]] = {}

        mids: Dict[str, float] = {}
        for product, order_depth in state.order_depths.items():
            mid = self._mid(order_depth)
            if mid is not None:
                mids[product] = mid
                data["anchor"].setdefault(product, mid)

        portfolio_pnl = 0.0
        portfolio_gross = 0
        for targets in GROUP_TARGETS.values():
            for product, target in targets.items():
                if target == 0 or product not in mids:
                    continue
                anchor = float(data["anchor"].get(product, mids[product]))
                portfolio_pnl += target * (mids[product] - anchor)
                portfolio_gross += abs(target)

        portfolio_active = (
            portfolio_gross > 0
            and self._update_group_gate(data, "PORTFOLIO", portfolio_pnl, portfolio_gross)
        )

        active_targets: Dict[str, int] = {}
        for group, targets in GROUP_TARGETS.items():
            paper_pnl = 0.0
            gross = 0
            for product, target in targets.items():
                if target == 0 or product not in mids:
                    continue
                anchor = float(data["anchor"].get(product, mids[product]))
                paper_pnl += target * (mids[product] - anchor)
                gross += abs(target)

            if gross == 0:
                continue
            if portfolio_active and self._update_group_gate(data, group, paper_pnl, gross):
                active_targets.update(targets)

        for product, order_depth in state.order_depths.items():
            position = state.position.get(product, 0)
            target = active_targets.get(product)
            if target is None:
                target = position if product in RELATIVE_TARGETS and position != 0 else 0
            orders = self._walk_to_target(product, order_depth, position, target)
            if orders:
                result[product] = orders

        return result, 0, self._save(data)
