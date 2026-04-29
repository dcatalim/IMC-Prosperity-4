from typing import Dict, List, Tuple, Optional
import json
import math

try:
    from datamodel import Order, OrderDepth, TradingState
except Exception:
    class Order:
        def __init__(self, symbol: str, price: int, quantity: int):
            self.symbol = symbol
            self.price = price
            self.quantity = quantity
        def __repr__(self):
            return f"({self.symbol}, {self.price}, {self.quantity})"
    class OrderDepth:
        def __init__(self):
            self.buy_orders = {}
            self.sell_orders = {}
    class TradingState:
        pass


class Trader:
    """
    Round 5 alternative idea: group relative-strength trader.

    This is deliberately different from the active-only v2 momentum script:
    - most groups trade product-vs-group relative strength, not standalone price momentum;
    - some groups use relative momentum, others use relative mean reversion;
    - UV was not robust as a relative basket, so it uses small color-specific directional overlays;
    - no passive market making.

    Relative signal for product p in group g:
        rel = (return_p_L - average_return_group_L) / normalized_vol_scale

    mode = +1 -> relative momentum: long winners / short losers.
    mode = -1 -> relative mean reversion: short winners / long losers.
    """

    LIMIT = 10
    VOL_ALPHA = 2.0 / 120.0

    GROUPS: Dict[str, List[str]] = {
        "GALAXY": ['GALAXY_SOUNDS_DARK_MATTER', 'GALAXY_SOUNDS_BLACK_HOLES', 'GALAXY_SOUNDS_PLANETARY_RINGS', 'GALAXY_SOUNDS_SOLAR_WINDS', 'GALAXY_SOUNDS_SOLAR_FLAMES'],
        "SLEEP": ['SLEEP_POD_SUEDE', 'SLEEP_POD_LAMB_WOOL', 'SLEEP_POD_POLYESTER', 'SLEEP_POD_NYLON', 'SLEEP_POD_COTTON'],
        "MICROCHIP": ['MICROCHIP_CIRCLE', 'MICROCHIP_OVAL', 'MICROCHIP_SQUARE', 'MICROCHIP_RECTANGLE', 'MICROCHIP_TRIANGLE'],
        "PEBBLES": ['PEBBLES_XS', 'PEBBLES_S', 'PEBBLES_M', 'PEBBLES_L', 'PEBBLES_XL'],
        "ROBOT": ['ROBOT_VACUUMING', 'ROBOT_MOPPING', 'ROBOT_DISHES', 'ROBOT_LAUNDRY', 'ROBOT_IRONING'],
        "UV": ['UV_VISOR_YELLOW', 'UV_VISOR_AMBER', 'UV_VISOR_ORANGE', 'UV_VISOR_RED', 'UV_VISOR_MAGENTA'],
        "TRANSLATOR": ['TRANSLATOR_SPACE_GRAY', 'TRANSLATOR_ASTRO_BLACK', 'TRANSLATOR_ECLIPSE_CHARCOAL', 'TRANSLATOR_GRAPHITE_MIST', 'TRANSLATOR_VOID_BLUE'],
        "PANEL": ['PANEL_1X2', 'PANEL_2X2', 'PANEL_1X4', 'PANEL_2X4', 'PANEL_4X4'],
        "OXYGEN": ['OXYGEN_SHAKE_MORNING_BREATH', 'OXYGEN_SHAKE_EVENING_BREATH', 'OXYGEN_SHAKE_MINT', 'OXYGEN_SHAKE_CHOCOLATE', 'OXYGEN_SHAKE_GARLIC'],
        "SNACK": ['SNACKPACK_CHOCOLATE', 'SNACKPACK_VANILLA', 'SNACKPACK_PISTACHIO', 'SNACKPACK_STRAWBERRY', 'SNACKPACK_RASPBERRY'],
    }

    GROUP_CFG: Dict[str, Dict[str, float]] = {
        "PEBBLES": {'mode': -1, 'L': 500, 'entry': 0.8, 'exit_abs': 0.6, 'target': 10, 'qty': 5, 'cooldown': 20, 'max_spread': 15, 'sweep_extra': 0},
        "OXYGEN": {'mode': 1, 'L': 500, 'entry': 1.2, 'exit_abs': 0.2, 'target': 10, 'qty': 5, 'cooldown': 20, 'max_spread': 18, 'sweep_extra': 0},
        "SNACK": {'mode': -1, 'L': 500, 'entry': 1.2, 'exit_abs': 0.2, 'target': 10, 'qty': 2, 'cooldown': 100, 'max_spread': 16, 'sweep_extra': 0},
        "SLEEP": {'mode': -1, 'L': 500, 'entry': 1.6, 'exit_abs': 0.6, 'target': 10, 'qty': 5, 'cooldown': 20, 'max_spread': 12, 'sweep_extra': 0},
        "PANEL": {'mode': 1, 'L': 100, 'entry': 1.2, 'exit_abs': 0.2, 'target': 10, 'qty': 5, 'cooldown': 100, 'max_spread': 10, 'sweep_extra': 0},
        "MICROCHIP": {'mode': 1, 'L': 20, 'entry': 0.8, 'exit_abs': 0.2, 'target': 5, 'qty': 2, 'cooldown': 100, 'max_spread': 10, 'sweep_extra': 0},
        "ROBOT": {'mode': 1, 'L': 50, 'entry': 1.2, 'exit_abs': 0.2, 'target': 5, 'qty': 2, 'cooldown': 100, 'max_spread': 8, 'sweep_extra': 0},
        "GALAXY": {'mode': 1, 'L': 200, 'entry': 1.6, 'exit_abs': 0.6, 'target': 5, 'qty': 2, 'cooldown': 100, 'max_spread': 16, 'sweep_extra': 0},
    }

    DIRECTIONAL_CFG: Dict[str, Dict[str, float]] = {
        "UV_VISOR_MAGENTA": {'side': 1, 'L': 500, 'entry': 1.2, 'exit': 0.2, 'target': 5, 'qty': 2, 'cooldown': 20, 'max_spread': 16, 'sweep_extra': 0},
    }

    PRODUCTS = set()
    for g, cfg in GROUP_CFG.items():
        for p in GROUPS[g]:
            PRODUCTS.add(p)
    for p in DIRECTIONAL_CFG:
        PRODUCTS.add(p)

    PRODUCT_MAX_DELTAS: Dict[str, int] = {}
    for g, cfg in GROUP_CFG.items():
        need = int(cfg["L"]) + 1
        for p in GROUPS[g]:
            PRODUCT_MAX_DELTAS[p] = max(PRODUCT_MAX_DELTAS.get(p, 0), need)
    for p, cfg in DIRECTIONAL_CFG.items():
        PRODUCT_MAX_DELTAS[p] = max(PRODUCT_MAX_DELTAS.get(p, 0), int(cfg["L"]) + 1)

    def bid(self):
        return 15

    @staticmethod
    def best_bid_ask(depth: OrderDepth) -> Optional[Tuple[int, int, int, int]]:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        return int(best_bid), int(best_ask), int(depth.buy_orders[best_bid]), int(-depth.sell_orders[best_ask])

    def load_state(self, trader_data: str) -> Dict:
        if trader_data:
            try:
                s = json.loads(trader_data)
                if isinstance(s, dict):
                    s.setdefault("b", {})
                    s.setdefault("d", {})
                    s.setdefault("l", {})
                    s.setdefault("v", {})
                    s.setdefault("t", {})
                    s.setdefault("lt", {})
                    return s
            except Exception:
                pass
        return {"b": {}, "d": {}, "l": {}, "v": {}, "t": {}, "lt": {}}

    def save_state(self, s: Dict) -> str:
        return json.dumps(s, separators=(",", ":"))

    @staticmethod
    def timestamp_to_step(timestamp: int) -> int:
        return int(timestamp // 100) if timestamp >= 100 else int(timestamp)

    def update_mid_state(self, s: Dict, product: str, mid: float) -> float:
        mid_i = int(round(mid))
        if product not in s["b"]:
            s["b"][product] = mid_i
            s["d"][product] = []
            s["l"][product] = mid_i
            s["v"][product] = 1.0
            return 1.0

        last = int(s["l"].get(product, mid_i))
        delta = mid_i - last
        ds = s["d"].setdefault(product, [])
        ds.append(int(delta))
        s["l"][product] = mid_i

        max_deltas = int(self.PRODUCT_MAX_DELTAS.get(product, 501))
        if len(ds) > max_deltas:
            extra = len(ds) - max_deltas
            roll = 0
            for x in ds[:extra]:
                roll += int(x)
            s["b"][product] = int(s["b"][product]) + roll
            del ds[:extra]

        prev_v = float(s["v"].get(product, 1.0))
        v = self.VOL_ALPHA * abs(delta) + (1.0 - self.VOL_ALPHA) * max(prev_v, 1.0)
        if v < 1.0:
            v = 1.0
        s["v"][product] = round(v, 4)
        return v

    def past_mid(self, s: Dict, product: str, L: int) -> Optional[int]:
        ds = s["d"].get(product, [])
        if len(ds) < L:
            return None
        idx = len(ds) - L
        val = int(s["b"][product])
        for x in ds[:idx]:
            val += int(x)
        return val

    def compute_group_relative_targets(self, s: Dict):
        for group, cfg in self.GROUP_CFG.items():
            products = self.GROUPS[group]
            L = int(cfg["L"])

            rets: Dict[str, float] = {}
            valid = True
            for p in products:
                if p not in s["l"]:
                    valid = False
                    break
                past = self.past_mid(s, p, L)
                if past is None:
                    valid = False
                    break
                rets[p] = float(int(s["l"][p]) - int(past))

            if not valid:
                for p in products:
                    s["t"].setdefault(p, 0)
                continue

            group_ret = sum(rets.values()) / float(len(products))
            mode = int(cfg["mode"])
            entry = float(cfg["entry"])
            exit_abs = float(cfg["exit_abs"])
            target_abs = int(cfg["target"])

            for p in products:
                vol = max(1.0, float(s["v"].get(p, 1.0)))
                scale = max(5.0, vol * math.sqrt(float(L)) * 1.5)
                rel = (rets[p] - group_ret) / scale
                sig = rel * float(mode)
                old_target = int(s["t"].get(p, 0))

                if sig >= entry:
                    target = target_abs
                elif sig <= -entry:
                    target = -target_abs
                elif abs(sig) <= exit_abs:
                    target = 0
                else:
                    target = old_target

                if target > self.LIMIT:
                    target = self.LIMIT
                elif target < -self.LIMIT:
                    target = -self.LIMIT
                s["t"][p] = int(target)

    def compute_directional_targets(self, s: Dict):
        for p, cfg in self.DIRECTIONAL_CFG.items():
            if p not in s["l"]:
                continue
            L = int(cfg["L"])
            past = self.past_mid(s, p, L)
            if past is None:
                s["t"].setdefault(p, 0)
                continue

            side = int(cfg["side"])
            vol = max(1.0, float(s["v"].get(p, 1.0)))
            scale = max(5.0, vol * math.sqrt(float(L)) * 1.5)
            sig = side * (float(int(s["l"][p]) - int(past))) / scale
            old_target = int(s["t"].get(p, 0))

            if sig >= float(cfg["entry"]):
                target = side * int(cfg["target"])
            elif sig <= float(cfg["exit"]):
                target = 0
            else:
                target = old_target

            if target > self.LIMIT:
                target = self.LIMIT
            elif target < -self.LIMIT:
                target = -self.LIMIT
            s["t"][p] = int(target)

    def exec_cfg_for_product(self, product: str) -> Optional[Dict[str, float]]:
        if product in self.DIRECTIONAL_CFG:
            return self.DIRECTIONAL_CFG[product]
        for group, products in self.GROUPS.items():
            if product in products and group in self.GROUP_CFG:
                return self.GROUP_CFG[group]
        return None

    def choose_cross_order(self, product: str, depth: OrderDepth, position: int, target: int, cfg: Dict[str, float]) -> Optional[Order]:
        if target == position:
            return None

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return None
        best_bid, best_ask, _, _ = bb_ba

        qty_cap = int(cfg["qty"])
        max_spread = int(cfg["max_spread"])
        sweep_extra = int(cfg.get("sweep_extra", 0))

        if target > position:
            remaining = min(qty_cap, target - position, self.LIMIT - position)
            if remaining <= 0:
                return None
            qty = 0
            limit_price = None
            first_ask = None
            increasing = target > 0 and position >= 0

            for ask_price, ask_qty_neg in sorted(depth.sell_orders.items()):
                ask_price = int(ask_price)
                ask_qty = int(-ask_qty_neg)
                if ask_qty <= 0:
                    continue
                if first_ask is None:
                    first_ask = ask_price
                elif ask_price - first_ask > sweep_extra:
                    break
                if increasing and ask_price - best_bid > max_spread:
                    break
                take = min(remaining - qty, ask_qty)
                if take <= 0:
                    break
                qty += take
                limit_price = ask_price
                if qty >= remaining:
                    break

            if qty > 0 and limit_price is not None:
                return Order(product, int(limit_price), int(qty))

        else:
            remaining = min(qty_cap, position - target, self.LIMIT + position)
            if remaining <= 0:
                return None
            qty = 0
            limit_price = None
            first_bid = None
            increasing = target < 0 and position <= 0

            for bid_price, bid_qty in sorted(depth.buy_orders.items(), reverse=True):
                bid_price = int(bid_price)
                bid_qty = int(bid_qty)
                if bid_qty <= 0:
                    continue
                if first_bid is None:
                    first_bid = bid_price
                elif first_bid - bid_price > sweep_extra:
                    break
                if increasing and best_ask - bid_price > max_spread:
                    break
                take = min(remaining - qty, bid_qty)
                if take <= 0:
                    break
                qty += take
                limit_price = bid_price
                if qty >= remaining:
                    break

            if qty > 0 and limit_price is not None:
                return Order(product, int(limit_price), -int(qty))

        return None

    def run(self, state: TradingState):
        s = self.load_state(state.traderData)
        result: Dict[str, List[Order]] = {}
        step = self.timestamp_to_step(int(getattr(state, "timestamp", 0)))

        # First pass: update all relevant mids, so group signals use the same timestamp.
        for product, depth in state.order_depths.items():
            result[product] = []
            if product not in self.PRODUCTS:
                continue
            bb_ba = self.best_bid_ask(depth)
            if bb_ba is None:
                continue
            best_bid, best_ask, _, _ = bb_ba
            self.update_mid_state(s, product, (best_bid + best_ask) / 2.0)

        self.compute_group_relative_targets(s)
        self.compute_directional_targets(s)

        # Second pass: trade toward targets.
        for product, depth in state.order_depths.items():
            if product not in self.PRODUCTS:
                continue
            cfg = self.exec_cfg_for_product(product)
            if cfg is None:
                continue

            last_trade_step = int(s["lt"].get(product, -10**9))
            cooldown = int(cfg["cooldown"])
            if step - last_trade_step < cooldown:
                continue

            position = int(state.position.get(product, 0))
            target = int(s["t"].get(product, 0))
            order = self.choose_cross_order(product, depth, position, target, cfg)
            if order is not None:
                result[product] = [order]
                s["lt"][product] = step

        return result, 0, self.save_state(s)
