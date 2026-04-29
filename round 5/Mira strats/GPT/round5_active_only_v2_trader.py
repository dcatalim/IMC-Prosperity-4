from typing import Dict, List, Tuple, Optional
import json
import math

try:
    from datamodel import Order, OrderDepth, TradingState
except Exception:
    # Local-test fallback only. The official simulator provides datamodel.py.
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
    Round 5 active-only v2.

    Changes vs the previous active-only version:
    - still no passive market making;
    - expands the active product set with only robust one-sided products from days 2/3/4;
    - keeps persistent target positions to avoid churn;
    - adds controlled L2/L3 sweeping so strong signals reach target faster instead of waiting
      several cooldown cycles when top-of-book volume is small;
    - one order per product per tick, with price/volume capped by the visible book and by ±10 limits.

    Signal:
        side_signal = side * (mid_now - mid_L_steps_ago) / normalized_vol

    side = +1 -> long-only momentum product
    side = -1 -> short-only momentum product
    """

    LIMIT = 10

    # Product-specific active momentum configs.
    # L/cooldown are in observations, not timestamp units.
    # sweep_extra controls how far beyond best level we may sweep visible L2/L3.
    CFG: Dict[str, Dict[str, float]] = {
        # Existing core winners
        "SLEEP_POD_COTTON":              {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 12, "sweep_extra": 2},
        "GALAXY_SOUNDS_BLACK_HOLES":    {"side":  1, "L": 200, "entry": 1.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 18, "sweep_extra": 0},
        "PANEL_2X4":                    {"side":  1, "L":  20, "entry": 0.8, "exit": -0.2, "target":  6, "qty":  2, "cooldown": 100, "max_spread": 12, "sweep_extra": 0},
        "SLEEP_POD_SUEDE":              {"side":  1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 12, "sweep_extra": 0},
        "SLEEP_POD_LAMB_WOOL":          {"side":  1, "L": 500, "entry": 1.6, "exit":  0.2, "target": 10, "qty":  5, "cooldown":   3, "max_spread": 11, "sweep_extra": 6},
        "UV_VISOR_RED":                 {"side":  1, "L":  50, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 16, "sweep_extra": 0},
        "ROBOT_DISHES":                 {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty":  2, "cooldown":  10, "max_spread":  8, "sweep_extra": 0},

        "PANEL_1X4":                    {"side": -1, "L": 100, "entry": 1.2, "exit":  0.2, "target": 10, "qty": 10, "cooldown":   3, "max_spread": 10, "sweep_extra": 1},
        "MICROCHIP_OVAL":               {"side": -1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty": 10, "cooldown":   3, "max_spread": 10, "sweep_extra": 1},
        "ROBOT_IRONING":                {"side": -1, "L": 500, "entry": 0.8, "exit": -0.2, "target": 10, "qty":  1, "cooldown": 100, "max_spread":  8, "sweep_extra": 0},
        "TRANSLATOR_SPACE_GRAY":        {"side": -1, "L":  20, "entry": 0.8, "exit":  0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 4},
        "UV_VISOR_AMBER":               {"side": -1, "L":  20, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 14, "sweep_extra": 4},

        # New v2 additions: kept one-sided and filtered for positive day 2/3/4 tests.
        "MICROCHIP_RECTANGLE":          {"side": -1, "L": 200, "entry": 1.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 1},
        "PANEL_4X4":                    {"side": -1, "L": 100, "entry": 0.8, "exit":  0.6, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 6},
        "PEBBLES_L":                    {"side":  1, "L": 100, "entry": 1.6, "exit":  0.6, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 15, "sweep_extra": 0},
        "PEBBLES_XS":                   {"side":  1, "L":  20, "entry": 2.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 14, "sweep_extra": 0},
        "OXYGEN_SHAKE_MORNING_BREATH":  {"side": -1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 15, "sweep_extra": 8},
        "OXYGEN_SHAKE_GARLIC":          {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 18, "sweep_extra": 0},
        "GALAXY_SOUNDS_SOLAR_WINDS":    {"side":  1, "L": 100, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 15, "sweep_extra": 0},
        "PANEL_2X2":                    {"side": -1, "L":  20, "entry": 2.2, "exit":  0.6, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10, "sweep_extra": 0},
    }

    PRODUCTS = set(CFG.keys())
    MAX_HISTORY = max(int(c["L"]) for c in CFG.values()) + 2
    VOL_ALPHA = 2.0 / 120.0

    def bid(self):
        return 15

    @staticmethod
    def best_bid_ask(depth: OrderDepth) -> Optional[Tuple[int, int, int, int]]:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        best_bid_vol = int(depth.buy_orders[best_bid])
        best_ask_vol = int(-depth.sell_orders[best_ask])
        return int(best_bid), int(best_ask), best_bid_vol, best_ask_vol

    def load_state(self, trader_data: str) -> Dict:
        if trader_data:
            try:
                saved = json.loads(trader_data)
                if isinstance(saved, dict):
                    saved.setdefault("h", {})
                    saved.setdefault("vol", {})
                    saved.setdefault("last", {})
                    saved.setdefault("target", {})
                    saved.setdefault("lt", {})
                    return saved
            except Exception:
                pass
        return {"h": {}, "vol": {}, "last": {}, "target": {}, "lt": {}}

    def save_state(self, saved: Dict) -> str:
        return json.dumps(saved, separators=(",", ":"))

    def update_history_and_vol(self, saved: Dict, product: str, mid: float) -> Tuple[List[int], float]:
        mid_i = int(round(mid))

        h = saved["h"].setdefault(product, [])
        h.append(mid_i)
        if len(h) > self.MAX_HISTORY:
            del h[:len(h) - self.MAX_HISTORY]

        last = float(saved["last"].get(product, mid_i))
        prev_vol = float(saved["vol"].get(product, 1.0))
        move = abs(mid_i - last)
        vol = self.VOL_ALPHA * move + (1.0 - self.VOL_ALPHA) * max(prev_vol, 1.0)
        if vol < 1.0:
            vol = 1.0

        saved["last"][product] = mid_i
        saved["vol"][product] = vol
        return h, vol

    @staticmethod
    def timestamp_to_step(timestamp: int) -> int:
        if timestamp >= 100:
            return int(timestamp // 100)
        return int(timestamp)

    def compute_target(self, saved: Dict, product: str, h: List[int], vol: float) -> int:
        cfg = self.CFG[product]
        L = int(cfg["L"])
        side = int(cfg["side"])
        old_target = int(saved["target"].get(product, 0))

        if len(h) <= L:
            saved["target"][product] = 0
            return 0

        past_mid = float(h[-1 - L])
        now_mid = float(h[-1])
        scale = max(5.0, vol * math.sqrt(float(L)) * 1.5)
        signal = side * (now_mid - past_mid) / scale

        entry = float(cfg["entry"])
        exit_thr = float(cfg["exit"])
        target_abs = int(cfg["target"])

        if signal >= entry:
            new_target = side * target_abs
        elif signal <= exit_thr:
            new_target = 0
        else:
            new_target = old_target

        saved["target"][product] = int(new_target)
        return int(new_target)

    def choose_cross_order(
        self,
        product: str,
        depth: OrderDepth,
        position: int,
        target: int,
    ) -> Optional[Order]:
        cfg = self.CFG[product]
        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None or target == position:
            return None

        best_bid, best_ask, _, _ = bb_ba
        max_spread = int(cfg.get("max_spread", 20))
        sweep_extra = int(cfg.get("sweep_extra", 0))
        qty_cap = int(cfg["qty"])

        if target > position:
            # Buy towards target.
            remaining = min(qty_cap, target - position, self.LIMIT - position)
            if remaining <= 0:
                return None

            increasing_exposure = target > 0 and position >= 0
            qty = 0
            limit_price = None
            first_ask = None

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

        elif target < position:
            # Sell towards target.
            remaining = min(qty_cap, position - target, self.LIMIT + position)
            if remaining <= 0:
                return None

            increasing_exposure = target < 0 and position <= 0
            qty = 0
            limit_price = None
            first_bid = None

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

    def active_order_towards_target(
        self,
        product: str,
        depth: OrderDepth,
        position: int,
        target: int,
        step: int,
        saved: Dict,
    ) -> List[Order]:
        last_step = int(saved["lt"].get(product, -10**9))
        cooldown = int(self.CFG[product]["cooldown"])
        if step - last_step < cooldown:
            return []

        order = self.choose_cross_order(product, depth, position, target)
        if order is None:
            return []

        saved["lt"][product] = step
        return [order]

    def run(self, state: TradingState):
        saved = self.load_state(state.traderData)
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

            h, vol = self.update_history_and_vol(saved, product, mid)
            target = self.compute_target(saved, product, h, vol)
            position = int(state.position.get(product, 0))

            result[product] = self.active_order_towards_target(
                product=product,
                depth=depth,
                position=position,
                target=target,
                step=step,
                saved=saved,
            )

        return result, 0, self.save_state(saved)
