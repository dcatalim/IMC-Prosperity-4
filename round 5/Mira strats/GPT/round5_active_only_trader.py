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
    Round 5 active-only strategy.

    Main change vs the previous file:
    - no passive market making at all;
    - only crosses the spread when a product-specific one-sided momentum signal is active;
    - each product has its own side, lookback, entry/exit thresholds, target, size, cooldown;
    - targets persist while the signal is still alive, so it does not churn in/out every tick.

    Signal form:
        side_signal = side * (mid_now - mid_L_steps_ago) / normalized_vol

    side = +1 -> long-only momentum product
    side = -1 -> short-only momentum product
    """

    LIMIT = 10

    # Product-specific configs selected from days 2/3/4 active-only tests.
    # L/cooldown are in observations, not timestamp units.
    # entry/exit use the normalized momentum signal.
    # qty is the maximum active adjustment per cooldown.
    CFG: Dict[str, Dict[str, float]] = {
        # Strong long-only momentum candidates
        "SLEEP_POD_COTTON":              {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 12},
        "GALAXY_SOUNDS_BLACK_HOLES":    {"side":  1, "L": 200, "entry": 1.2, "exit": -0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 18},
        "PANEL_2X4":                    {"side":  1, "L":  20, "entry": 0.8, "exit": -0.2, "target":  6, "qty":  2, "cooldown": 100, "max_spread": 12},
        "SLEEP_POD_SUEDE":              {"side":  1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 12},
        "SLEEP_POD_LAMB_WOOL":          {"side":  1, "L": 500, "entry": 1.6, "exit":  0.2, "target": 10, "qty":  5, "cooldown":   3, "max_spread": 11},
        "UV_VISOR_RED":                 {"side":  1, "L":  50, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 16},
        "ROBOT_DISHES":                 {"side":  1, "L": 200, "entry": 0.8, "exit": -0.2, "target": 10, "qty":  2, "cooldown":  10, "max_spread":  8},

        # Strong short-only momentum candidates
        "PANEL_1X4":                    {"side": -1, "L": 100, "entry": 1.2, "exit":  0.2, "target": 10, "qty": 10, "cooldown":   3, "max_spread": 10},
        "MICROCHIP_OVAL":               {"side": -1, "L": 500, "entry": 0.8, "exit":  0.2, "target": 10, "qty": 10, "cooldown":   3, "max_spread": 10},
        "ROBOT_IRONING":                {"side": -1, "L": 500, "entry": 0.8, "exit": -0.2, "target": 10, "qty":  1, "cooldown": 100, "max_spread":  8},
        "TRANSLATOR_SPACE_GRAY":        {"side": -1, "L":  20, "entry": 0.8, "exit":  0.2, "target": 10, "qty": 10, "cooldown": 100, "max_spread": 10},
        "UV_VISOR_AMBER":               {"side": -1, "L":  20, "entry": 0.8, "exit":  0.2, "target": 10, "qty":  5, "cooldown": 100, "max_spread": 14},
    }

    PRODUCTS = set(CFG.keys())
    MAX_HISTORY = max(int(c["L"]) for c in CFG.values()) + 2
    VOL_ALPHA = 2.0 / 120.0

    def bid(self):
        # Ignored in Round 5, harmless to keep.
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
                    saved.setdefault("h", {})      # product -> compact mid history
                    saved.setdefault("vol", {})    # product -> EWMA abs move
                    saved.setdefault("last", {})   # product -> last mid
                    saved.setdefault("target", {}) # product -> target position
                    saved.setdefault("lt", {})     # product -> last active step
                    return saved
            except Exception:
                pass
        return {"h": {}, "vol": {}, "last": {}, "target": {}, "lt": {}}

    def save_state(self, saved: Dict) -> str:
        # Compact JSON keeps traderData safely below the 50k character cap.
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
        # Official timestamps usually move in 100-unit increments.
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
            # Keep existing target while the signal is between entry and exit.
            # This avoids paying the spread repeatedly just because momentum pauses.
            new_target = old_target

        saved["target"][product] = int(new_target)
        return int(new_target)

    def active_order_towards_target(
        self,
        product: str,
        depth: OrderDepth,
        position: int,
        target: int,
        step: int,
        saved: Dict,
    ) -> List[Order]:
        orders: List[Order] = []
        cfg = self.CFG[product]

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return orders

        best_bid, best_ask, best_bid_vol, best_ask_vol = bb_ba
        spread = best_ask - best_bid
        max_spread = int(cfg.get("max_spread", 20))

        last_step = int(saved["lt"].get(product, -10**9))
        cooldown = int(cfg["cooldown"])
        if step - last_step < cooldown:
            return orders

        if target == position:
            return orders

        qty_cap = int(cfg["qty"])

        if target > position:
            # Buy. Opening/increasing active exposure requires reasonable spread.
            # If this is a close of a short, allow it even when spread is wide.
            increasing_exposure = target > 0 and position >= 0
            if increasing_exposure and spread > max_spread:
                return orders
            buy_capacity = self.LIMIT - position
            qty = min(qty_cap, target - position, buy_capacity, best_ask_vol)
            if qty > 0:
                orders.append(Order(product, int(best_ask), int(qty)))
                saved["lt"][product] = step

        elif target < position:
            # Sell. Opening/increasing active exposure requires reasonable spread.
            # If this is a close of a long, allow it even when spread is wide.
            increasing_exposure = target < 0 and position <= 0
            if increasing_exposure and spread > max_spread:
                return orders
            sell_capacity = self.LIMIT + position
            qty = min(qty_cap, position - target, sell_capacity, best_bid_vol)
            if qty > 0:
                orders.append(Order(product, int(best_bid), -int(qty)))
                saved["lt"][product] = step

        return orders

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
