from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple
import json
import math

POSITION_LIMIT = 10

# Round 5 Group Strategies v3 Robust
# Base: relative-strength v4 robust basket.
# Different group logic:
# - stable carry/relative groups walk directly to their base target;
# - fragile half-size names can upgrade to full size only when their own momentum confirms;
# - no passive market making.
# This is intentionally simpler than the previous mixed version: less churn, less state, more non-gated structure.

BASE_TARGETS: Dict[str, int] = {'GALAXY_SOUNDS_BLACK_HOLES': 10,
 'GALAXY_SOUNDS_DARK_MATTER': 5,
 'GALAXY_SOUNDS_PLANETARY_RINGS': -5,
 'GALAXY_SOUNDS_SOLAR_FLAMES': 5,
 'GALAXY_SOUNDS_SOLAR_WINDS': 5,
 'MICROCHIP_OVAL': -10,
 'MICROCHIP_RECTANGLE': -10,
 'MICROCHIP_SQUARE': 10,
 'MICROCHIP_TRIANGLE': -10,
 'OXYGEN_SHAKE_CHOCOLATE': 5,
 'OXYGEN_SHAKE_EVENING_BREATH': -5,
 'OXYGEN_SHAKE_GARLIC': 10,
 'OXYGEN_SHAKE_MORNING_BREATH': -5,
 'PANEL_1X2': -10,
 'PANEL_1X4': -5,
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
 'SLEEP_POD_COTTON': 5,
 'SLEEP_POD_LAMB_WOOL': 10,
 'SLEEP_POD_NYLON': 5,
 'SLEEP_POD_POLYESTER': 10,
 'SLEEP_POD_SUEDE': 10,
 'SNACKPACK_CHOCOLATE': -10,
 'SNACKPACK_PISTACHIO': -10,
 'SNACKPACK_RASPBERRY': 10,
 'SNACKPACK_STRAWBERRY': 10,
 'SNACKPACK_VANILLA': 10,
 'TRANSLATOR_ASTRO_BLACK': -10,
 'TRANSLATOR_ECLIPSE_CHARCOAL': -5,
 'TRANSLATOR_SPACE_GRAY': -10,
 'TRANSLATOR_VOID_BLUE': 10,
 'UV_VISOR_AMBER': -10,
 'UV_VISOR_MAGENTA': 10,
 'UV_VISOR_ORANGE': -10,
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

# Overlay only upgrades half-size or fragile products to full target when the tape confirms.
# side = +1 for long momentum confirmation, -1 for short momentum confirmation.
OVERLAY_CFG: Dict[str, Dict[str, float]] = {
    "SLEEP_POD_COTTON": {"side": 1, "L": 120, "entry": 1.00, "exit": -0.15},
    "SLEEP_POD_NYLON": {"side": 1, "L": 160, "entry": 1.05, "exit": -0.15},
    "GALAXY_SOUNDS_SOLAR_FLAMES": {"side": 1, "L": 120, "entry": 1.10, "exit": -0.10},
    "GALAXY_SOUNDS_DARK_MATTER": {"side": 1, "L": 120, "entry": 1.05, "exit": -0.10},
    "GALAXY_SOUNDS_SOLAR_WINDS": {"side": 1, "L": 120, "entry": 1.05, "exit": -0.10},
    "GALAXY_SOUNDS_PLANETARY_RINGS": {"side": -1, "L": 120, "entry": 1.05, "exit": -0.10},
    "PANEL_1X4": {"side": -1, "L": 80, "entry": 1.10, "exit": -0.05},
    "OXYGEN_SHAKE_CHOCOLATE": {"side": 1, "L": 160, "entry": 1.15, "exit": -0.10},
    "OXYGEN_SHAKE_EVENING_BREATH": {"side": -1, "L": 160, "entry": 1.10, "exit": -0.10},
    "OXYGEN_SHAKE_MORNING_BREATH": {"side": -1, "L": 160, "entry": 1.10, "exit": -0.10},
    "TRANSLATOR_ECLIPSE_CHARCOAL": {"side": -1, "L": 120, "entry": 1.10, "exit": -0.10},
}

MAX_L = 170


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

    def _load(self, data: str) -> Dict:
        if data:
            try:
                s = json.loads(data)
                if isinstance(s, dict):
                    s.setdefault("b", {})
                    s.setdefault("l", {})
                    s.setdefault("d", {})
                    s.setdefault("v", {})
                    s.setdefault("t", {})
                    return s
            except Exception:
                pass
        return {"b": {}, "l": {}, "d": {}, "v": {}, "t": {}}

    def _save(self, s: Dict) -> str:
        return json.dumps(s, separators=(",", ":"))

    def _update_mid(self, s: Dict, product: str, mid: float) -> float:
        mid_i = int(round(mid))
        if product not in s["l"]:
            s["b"][product] = mid_i
            s["l"][product] = mid_i
            s["d"][product] = []
            s["v"][product] = 1.0
            return 1.0

        last = int(s["l"][product])
        delta = mid_i - last
        ds = s["d"].setdefault(product, [])
        ds.append(int(delta))
        s["l"][product] = mid_i

        if len(ds) > MAX_L:
            extra = len(ds) - MAX_L
            s["b"][product] = int(s["b"][product]) + sum(int(x) for x in ds[:extra])
            del ds[:extra]

        old_v = float(s["v"].get(product, 1.0))
        v = 0.025 * abs(delta) + 0.975 * max(old_v, 1.0)
        s["v"][product] = round(max(v, 1.0), 4)
        return max(v, 1.0)

    def _past_mid(self, s: Dict, product: str, L: int) -> Optional[int]:
        ds = s["d"].get(product, [])
        if len(ds) < L:
            return None
        # base plus all deltas before the last L deltas
        return int(s["b"][product]) + sum(int(x) for x in ds[:len(ds)-L])

    def _target_for_product(self, s: Dict, product: str, depth: OrderDepth) -> int:
        base = int(BASE_TARGETS.get(product, 0))
        if product not in OVERLAY_CFG:
            return base

        best_bid, best_ask = self._best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return base

        mid = (int(best_bid) + int(best_ask)) / 2.0
        vol = self._update_mid(s, product, mid)
        cfg = OVERLAY_CFG[product]
        side = int(cfg["side"])
        L = int(cfg["L"])
        old = int(s["t"].get(product, base))
        past = self._past_mid(s, product, L)
        if past is None:
            s["t"][product] = base
            return base

        now = int(s["l"][product])
        scale = max(5.0, vol * math.sqrt(float(L)) * 1.5)
        signal = side * (float(now) - float(past)) / scale

        if signal >= float(cfg["entry"]):
            target = side * 10
        elif signal <= float(cfg["exit"]):
            target = base
        else:
            target = old

        target = self._clamp(target)
        s["t"][product] = target
        return target

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
                qty_avail = -int(ask_qty_neg)
                if qty_avail <= 0:
                    continue
                qty = min(qty_avail, remaining)
                orders.append(Order(product, int(ask_price), int(qty)))
                remaining -= qty
        else:
            remaining = min(-delta, POSITION_LIMIT + position)
            for bid_price, bid_qty in sorted(depth.buy_orders.items(), reverse=True):
                if remaining <= 0:
                    break
                qty_avail = int(bid_qty)
                if qty_avail <= 0:
                    continue
                qty = min(qty_avail, remaining)
                orders.append(Order(product, int(bid_price), -int(qty)))
                remaining -= qty
        return orders

    def run(self, state: TradingState):
        s = self._load(state.traderData)
        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            if product not in BASE_TARGETS and product not in OVERLAY_CFG:
                continue
            target = self._target_for_product(s, product, depth)
            if target == 0:
                continue
            orders = self._walk_to_target(product, depth, int(state.position.get(product, 0)), target)
            if orders:
                result[product] = orders

        return result, 0, self._save(s)
