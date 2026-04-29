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
    Round 5 active-only v3.

    Main changes vs v2:
    - no passive market making;
    - broader active product set, selected only if the one-sided signal was positive on
      day 2, day 3, and day 4 in the local replay;
    - product-specific history lengths instead of one global 500-tick history;
    - compact traderData: stores recent mid-price deltas under numeric product IDs,
      not full mid histories under long product names;
    - controlled sweeping only when the signal is already strong, otherwise best level only.

    Signal:
        side_signal = side * (mid_now - mid_L_steps_ago) / normalized_vol

    side = +1 -> long-only momentum product
    side = -1 -> short-only momentum product
    """

    LIMIT = 10

    CFG: Dict[str, Dict[str, float]] = {
        "SLEEP_POD_COTTON": {'side': 1, 'L': 200, 'entry': 0.8, 'exit': -0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 12, 'sweep_extra': 2},
        "PANEL_1X4": {'side': -1, 'L': 100, 'entry': 1.2, 'exit': 0.2, 'target': 10, 'qty': 10, 'cooldown': 3, 'max_spread': 10, 'sweep_extra': 1},
        "MICROCHIP_OVAL": {'side': -1, 'L': 500, 'entry': 0.8, 'exit': 0.2, 'target': 10, 'qty': 10, 'cooldown': 3, 'max_spread': 10, 'sweep_extra': 1},
        "ROBOT_IRONING": {'side': -1, 'L': 500, 'entry': 1.2, 'exit': -0.2, 'target': 10, 'qty': 2, 'cooldown': 100, 'max_spread': 8, 'sweep_extra': 0},
        "GALAXY_SOUNDS_BLACK_HOLES": {'side': 1, 'L': 200, 'entry': 1.2, 'exit': -0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 18, 'sweep_extra': 0},
        "MICROCHIP_TRIANGLE": {'side': -1, 'L': 200, 'entry': 1.2, 'exit': 0.2, 'target': 10, 'qty': 5, 'cooldown': 3, 'max_spread': 10, 'sweep_extra': 0},
        "PANEL_2X4": {'side': 1, 'L': 20, 'entry': 0.8, 'exit': -0.2, 'target': 10, 'qty': 2, 'cooldown': 100, 'max_spread': 12, 'sweep_extra': 0},
        "ROBOT_VACUUMING": {'side': -1, 'L': 20, 'entry': 1.6, 'exit': -0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 8, 'sweep_extra': 1},
        "MICROCHIP_SQUARE": {'side': -1, 'L': 100, 'entry': 1.6, 'exit': 0.2, 'target': 10, 'qty': 5, 'cooldown': 100, 'max_spread': 15, 'sweep_extra': 0},
        "OXYGEN_SHAKE_MORNING_BREATH": {'side': -1, 'L': 500, 'entry': 0.8, 'exit': 0.2, 'target': 10, 'qty': 2, 'cooldown': 100, 'max_spread': 15, 'sweep_extra': 0},
        "UV_VISOR_AMBER": {'side': -1, 'L': 20, 'entry': 0.8, 'exit': 0.2, 'target': 10, 'qty': 5, 'cooldown': 100, 'max_spread': 14, 'sweep_extra': 0},
        "PANEL_4X4": {'side': -1, 'L': 100, 'entry': 0.8, 'exit': 0.6, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 10, 'sweep_extra': 1},
        "OXYGEN_SHAKE_GARLIC": {'side': 1, 'L': 200, 'entry': 0.8, 'exit': 0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 18, 'sweep_extra': 0},
        "ROBOT_DISHES": {'side': 1, 'L': 200, 'entry': 0.8, 'exit': -0.2, 'target': 10, 'qty': 2, 'cooldown': 3, 'max_spread': 8, 'sweep_extra': 0},
        "SLEEP_POD_SUEDE": {'side': 1, 'L': 500, 'entry': 0.8, 'exit': 0.2, 'target': 10, 'qty': 5, 'cooldown': 100, 'max_spread': 12, 'sweep_extra': 0},
        "OXYGEN_SHAKE_MINT": {'side': 1, 'L': 200, 'entry': 1.6, 'exit': -0.2, 'target': 10, 'qty': 5, 'cooldown': 30, 'max_spread': 14, 'sweep_extra': 0},
        "MICROCHIP_RECTANGLE": {'side': -1, 'L': 200, 'entry': 1.2, 'exit': -0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 10, 'sweep_extra': 1},
        "PEBBLES_L": {'side': 1, 'L': 100, 'entry': 1.6, 'exit': 0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 15, 'sweep_extra': 2},
        "SLEEP_POD_LAMB_WOOL": {'side': 1, 'L': 500, 'entry': 1.6, 'exit': 0.2, 'target': 10, 'qty': 2, 'cooldown': 3, 'max_spread': 11, 'sweep_extra': 0},
        "PEBBLES_XL": {'side': 1, 'L': 200, 'entry': 1.6, 'exit': 0.2, 'target': 10, 'qty': 5, 'cooldown': 100, 'max_spread': 22, 'sweep_extra': 0},
        "PANEL_1X2": {'side': 1, 'L': 500, 'entry': 1.2, 'exit': -0.2, 'target': 10, 'qty': 5, 'cooldown': 30, 'max_spread': 14, 'sweep_extra': 0},
        "PEBBLES_XS": {'side': 1, 'L': 20, 'entry': 2.2, 'exit': -0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 14, 'sweep_extra': 2},
        "UV_VISOR_MAGENTA": {'side': 1, 'L': 500, 'entry': 1.2, 'exit': 0.2, 'target': 10, 'qty': 2, 'cooldown': 3, 'max_spread': 16, 'sweep_extra': 0},
        "PANEL_2X2": {'side': -1, 'L': 20, 'entry': 2.2, 'exit': 0.6, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 10, 'sweep_extra': 1},
        "SLEEP_POD_NYLON": {'side': 1, 'L': 200, 'entry': 1.6, 'exit': -0.2, 'target': 10, 'qty': 5, 'cooldown': 3, 'max_spread': 10, 'sweep_extra': 0},
        "UV_VISOR_RED": {'side': 1, 'L': 20, 'entry': 0.8, 'exit': -0.2, 'target': 10, 'qty': 2, 'cooldown': 30, 'max_spread': 16, 'sweep_extra': 0},
        "GALAXY_SOUNDS_SOLAR_WINDS": {'side': 1, 'L': 100, 'entry': 0.8, 'exit': -0.2, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 15, 'sweep_extra': 2},
        "MICROCHIP_CIRCLE": {'side': 1, 'L': 500, 'entry': 0.8, 'exit': -0.2, 'target': 10, 'qty': 5, 'cooldown': 30, 'max_spread': 10, 'sweep_extra': 0},
        "ROBOT_MOPPING": {'side': 1, 'L': 100, 'entry': 1.6, 'exit': 0.2, 'target': 10, 'qty': 5, 'cooldown': 100, 'max_spread': 9, 'sweep_extra': 0},
        "TRANSLATOR_VOID_BLUE": {'side': 1, 'L': 200, 'entry': 1.2, 'exit': 0.6, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 11, 'sweep_extra': 2},
        "OXYGEN_SHAKE_EVENING_BREATH": {'side': 1, 'L': 100, 'entry': 2.2, 'exit': 0.6, 'target': 10, 'qty': 10, 'cooldown': 100, 'max_spread': 14, 'sweep_extra': 2}
    }

    PRODUCTS = set(CFG.keys())
    PID = {p: str(i) for i, p in enumerate(CFG.keys())}
    VOL_ALPHA = 2.0 / 120.0

    def bid(self):
        return 15

    @staticmethod
    def best_bid_ask(depth: OrderDepth) -> Optional[Tuple[int, int, int, int]]:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        return int(best_bid), int(best_ask), int(depth.buy_orders[best_bid]), int(-depth.sell_orders[best_ask])

    @staticmethod
    def timestamp_to_step(timestamp: int) -> int:
        if timestamp >= 100:
            return int(timestamp // 100)
        return int(timestamp)

    def load_state(self, trader_data: str) -> Dict:
        if trader_data:
            try:
                saved = json.loads(trader_data)
                if isinstance(saved, dict):
                    saved.setdefault("d", {})   # recent mid deltas by product id
                    saved.setdefault("l", {})   # last mid by product id
                    saved.setdefault("v", {})   # volatility estimate by product id
                    saved.setdefault("t", {})   # target position by product id
                    saved.setdefault("c", {})   # last trade step/cooldown by product id
                    return saved
            except Exception:
                pass
        return {"d": {}, "l": {}, "v": {}, "t": {}, "c": {}}

    @staticmethod
    def save_state(saved: Dict) -> str:
        # Compact JSON. This must stay below the 50k traderData limit.
        return json.dumps(saved, separators=(",", ":"))

    def update_delta_history(self, saved: Dict, product: str, mid: float) -> Tuple[List[int], float]:
        cfg = self.CFG[product]
        pid = self.PID[product]
        L = int(cfg["L"])
        mid_i = int(round(mid))

        deltas = saved["d"].setdefault(pid, [])
        had_last = pid in saved["l"]
        last_mid = int(saved["l"].get(pid, mid_i))

        if had_last:
            delta = mid_i - last_mid
            deltas.append(int(delta))
            if len(deltas) > L:
                del deltas[:len(deltas) - L]
        else:
            delta = 0

        prev_vol = float(saved["v"].get(pid, 1.0))
        vol = self.VOL_ALPHA * abs(delta) + (1.0 - self.VOL_ALPHA) * max(prev_vol, 1.0)
        if vol < 1.0:
            vol = 1.0

        saved["l"][pid] = mid_i
        saved["v"][pid] = vol
        return deltas, vol

    def compute_signal_and_target(self, saved: Dict, product: str, deltas: List[int], vol: float) -> Tuple[Optional[float], int]:
        cfg = self.CFG[product]
        pid = self.PID[product]
        L = int(cfg["L"])
        side = int(cfg["side"])

        if len(deltas) < L:
            saved["t"][pid] = 0
            return None, 0

        move_l = float(sum(deltas[-L:]))
        scale = max(5.0, vol * math.sqrt(float(L)) * 1.5)
        signal = side * move_l / scale

        old_target = int(saved["t"].get(pid, 0))
        entry = float(cfg["entry"])
        exit_thr = float(cfg["exit"])
        target_abs = int(cfg["target"])

        if signal >= entry:
            new_target = side * target_abs
        elif signal <= exit_thr:
            new_target = 0
        else:
            new_target = old_target

        saved["t"][pid] = int(new_target)
        return float(signal), int(new_target)

    def allowed_sweep(self, product: str, signal: Optional[float], target: int, position: int) -> int:
        cfg = self.CFG[product]
        base = int(cfg.get("sweep_extra", 0))
        if base <= 0:
            return 0

        # Exits/reductions can use a small sweep so we do not get trapped in a stale position.
        reducing = (target == 0 and position != 0) or (target > 0 and position > target) or (target < 0 and position < target)
        if reducing:
            return min(base, 1)

        if signal is None:
            return 0

        # Build full size only when the signal is materially stronger than the entry threshold.
        entry = float(cfg["entry"])
        if signal >= entry + 0.9:
            return base
        if signal >= entry + 0.45:
            return min(base, 1)
        return 0

    def choose_cross_order(
        self,
        product: str,
        depth: OrderDepth,
        position: int,
        target: int,
        signal: Optional[float],
    ) -> Optional[Order]:
        if target == position:
            return None

        cfg = self.CFG[product]
        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return None

        best_bid, best_ask, _, _ = bb_ba
        max_spread = int(cfg.get("max_spread", 20))
        sweep_extra = self.allowed_sweep(product, signal, target, position)
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
        signal: Optional[float],
        step: int,
        saved: Dict,
    ) -> List[Order]:
        pid = self.PID[product]
        last_step = int(saved["c"].get(pid, -10**9))
        cooldown = int(self.CFG[product]["cooldown"])
        if step - last_step < cooldown:
            return []

        order = self.choose_cross_order(product, depth, position, target, signal)
        if order is None:
            return []

        saved["c"][pid] = step
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

            deltas, vol = self.update_delta_history(saved, product, mid)
            signal, target = self.compute_signal_and_target(saved, product, deltas, vol)
            position = int(state.position.get(product, 0))

            result[product] = self.active_order_towards_target(
                product=product,
                depth=depth,
                position=position,
                target=target,
                signal=signal,
                step=step,
                saved=saved,
            )

        return result, 0, self.save_state(saved)
