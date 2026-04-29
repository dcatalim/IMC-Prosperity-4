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
    Round 5 active-only robust v2.5.

    Design:
    - keeps the active-only v2 idea that worked better in the website simulator;
    - no passive market-making at all;
    - trades one-sided product momentum only;
    - adds a small set of robust extra signals that were positive across days 2, 3, and 4;
    - uses compact delta histories so traderData stays below the 50k character limit.

    Signal:
        signal = side * (mid_now - mid_L_steps_ago) / normalized_vol_scale

    side = +1 means long-only momentum.
    side = -1 means short-only momentum.
    """

    LIMIT = 10
    VOL_ALPHA = 2.0 / 120.0

    CFG: Dict[str, Dict[str, float]] = {
        "SLEEP_POD_COTTON": {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 12, "sweep_extra": 2},
        "GALAXY_SOUNDS_BLACK_HOLES": {"side":  1, "L": 200, "entry": 1.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 18, "sweep_extra": 0},
        "PANEL_2X4": {"side":  1, "L":  20, "entry": 0.8, "exit": -0.2, "target":  6, "qty":  2, "cooldown": 100, "max_spread": 12, "sweep_extra": 0},
        "SLEEP_POD_SUEDE": {"side":  1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 12, "sweep_extra": 0},
        "SLEEP_POD_LAMB_WOOL": {"side":  1, "L": 500, "entry": 1.6, "exit":  0.2, "target": 10, "qty":  5, "cooldown":   3, "max_spread": 11, "sweep_extra": 6},
        "UV_VISOR_RED": {"side":  1, "L":  50, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 16, "sweep_extra": 0},
        "ROBOT_DISHES": {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty":  2, "cooldown":  10, "max_spread":  8, "sweep_extra": 0},
        "PANEL_1X4": {"side": -1, "L": 100, "entry": 1.2, "exit":  0.2, "target": 10, "qty": 10, "cooldown":   3, "max_spread": 10, "sweep_extra": 1},
        "MICROCHIP_OVAL": {"side": -1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty": 10, "cooldown":   3, "max_spread": 10, "sweep_extra": 1},
        "ROBOT_IRONING": {"side": -1, "L": 500, "entry": 0.8, "exit": -0.2, "target": 10, "qty":  1, "cooldown": 100, "max_spread":  8, "sweep_extra": 0},
        "TRANSLATOR_SPACE_GRAY": {"side": -1, "L":  20, "entry": 0.8, "exit":  0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 4},
        "UV_VISOR_AMBER": {"side": -1, "L":  20, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 14, "sweep_extra": 4},
        "MICROCHIP_RECTANGLE": {"side": -1, "L": 200, "entry": 1.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 1},
        "PANEL_4X4": {"side": -1, "L": 100, "entry": 0.8, "exit":  0.6, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 6},
        "PEBBLES_L": {"side":  1, "L": 100, "entry": 1.6, "exit":  0.6, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 15, "sweep_extra": 0},
        "PEBBLES_XS": {"side":  1, "L":  20, "entry": 2.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 14, "sweep_extra": 0},
        "OXYGEN_SHAKE_MORNING_BREATH": {"side": -1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 15, "sweep_extra": 8},
        "OXYGEN_SHAKE_GARLIC": {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 18, "sweep_extra": 0},
        "GALAXY_SOUNDS_SOLAR_WINDS": {"side":  1, "L": 100, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 15, "sweep_extra": 0},
        "PANEL_2X2": {"side": -1, "L":  20, "entry": 2.2, "exit":  0.6, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 0},
        "MICROCHIP_TRIANGLE": {"side": -1, "L": 100, "entry": 1.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 0},
        "ROBOT_VACUUMING": {"side": -1, "L":  20, "entry": 1.6, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread":  8, "sweep_extra": 0},
        "PEBBLES_XL": {"side":  1, "L": 200, "entry": 1.6, "exit":  0.2, "target": 10, "qty":  2, "cooldown":  20, "max_spread": 15, "sweep_extra": 0},
        "OXYGEN_SHAKE_MINT": {"side":  1, "L": 200, "entry": 1.6, "exit": -0.2, "target": 10, "qty":  2, "cooldown":   3, "max_spread": 15, "sweep_extra": 0},
        "PANEL_1X2": {"side":  1, "L": 500, "entry": 1.2, "exit": -0.2, "target": 10, "qty":  5, "cooldown":  20, "max_spread": 10, "sweep_extra": 0},
        "UV_VISOR_MAGENTA": {"side":  1, "L": 500, "entry": 1.2, "exit":  0.2, "target": 10, "qty":  5, "cooldown":  20, "max_spread": 16, "sweep_extra": 0},
    }

    PRODUCTS = set(CFG.keys())
    PRODUCT_MAX_DELTAS = {p: int(c["L"]) + 1 for p, c in CFG.items()}

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
                    s.setdefault("b", {})   # base mid
                    s.setdefault("d", {})   # mid deltas from base
                    s.setdefault("l", {})   # last mid
                    s.setdefault("v", {})   # EWMA abs move
                    s.setdefault("t", {})   # target position
                    s.setdefault("lt", {})  # last trade step
                    return s
            except Exception:
                pass
        return {"b": {}, "d": {}, "l": {}, "v": {}, "t": {}, "lt": {}}

    def save_state(self, s: Dict) -> str:
        # Compact JSON. Avoid jsonpickle; product histories are stored as small deltas.
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

        # Keep only the last MAX_HISTORY values, represented as base + deltas.
        # If a delta is dropped, roll it into the base.
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
        # Current history length = len(ds)+1. h[-1-L] is at index len(ds)-L.
        idx = len(ds) - L
        val = int(s["b"][product])
        for x in ds[:idx]:
            val += int(x)
        return val

    def compute_target(self, s: Dict, product: str, vol: float) -> int:
        cfg = self.CFG[product]
        L = int(cfg["L"])
        side = int(cfg["side"])
        old_target = int(s["t"].get(product, 0))

        past = self.past_mid(s, product, L)
        if past is None:
            s["t"][product] = 0
            return 0

        now = int(s["l"][product])
        scale = max(5.0, vol * math.sqrt(float(L)) * 1.5)
        signal = side * (float(now) - float(past)) / scale

        if signal >= float(cfg["entry"]):
            target = side * int(cfg["target"])
        elif signal <= float(cfg["exit"]):
            target = 0
        else:
            target = old_target

        # Never ask for a target outside hard limits.
        if target > self.LIMIT:
            target = self.LIMIT
        elif target < -self.LIMIT:
            target = -self.LIMIT

        s["t"][product] = int(target)
        return int(target)

    def choose_cross_order(self, product: str, depth: OrderDepth, position: int, target: int) -> Optional[Order]:
        if target == position:
            return None

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return None
        best_bid, best_ask, _, _ = bb_ba

        cfg = self.CFG[product]
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
            increasing_exposure = target > 0 and position >= 0

            for ask_price, ask_qty_neg in sorted(depth.sell_orders.items()):
                ask_price = int(ask_price)
                ask_qty = int(-ask_qty_neg)
                if ask_qty <= 0:
                    continue
                if first_ask is None:
                    first_ask = ask_price
                elif ask_price - first_ask > sweep_extra:
                    break
                if increasing_exposure and ask_price - best_bid > max_spread:
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
            increasing_exposure = target < 0 and position <= 0

            for bid_price, bid_qty in sorted(depth.buy_orders.items(), reverse=True):
                bid_price = int(bid_price)
                bid_qty = int(bid_qty)
                if bid_qty <= 0:
                    continue
                if first_bid is None:
                    first_bid = bid_price
                elif first_bid - bid_price > sweep_extra:
                    break
                if increasing_exposure and best_ask - bid_price > max_spread:
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

        for product, depth in state.order_depths.items():
            result[product] = []
            if product not in self.PRODUCTS:
                continue

            bb_ba = self.best_bid_ask(depth)
            if bb_ba is None:
                continue
            best_bid, best_ask, _, _ = bb_ba
            mid = (best_bid + best_ask) / 2.0

            vol = self.update_mid_state(s, product, mid)
            target = self.compute_target(s, product, vol)
            position = int(state.position.get(product, 0))

            last_trade_step = int(s["lt"].get(product, -10**9))
            cooldown = int(self.CFG[product]["cooldown"])
            if step - last_trade_step < cooldown:
                continue

            order = self.choose_cross_order(product, depth, position, target)
            if order is not None:
                result[product] = [order]
                s["lt"][product] = step

        return result, 0, self.save_state(s)
