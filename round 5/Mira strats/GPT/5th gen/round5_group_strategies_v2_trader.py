from typing import Dict, List, Tuple, Optional
import json
import math

try:
    from datamodel import Order, OrderDepth, TradingState
except Exception:
    class Order:
        def __init__(self, symbol: str, price: int, quantity: int):
            self.symbol = symbol
            self.price = int(price)
            self.quantity = int(quantity)
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
    Round 5 mixed group-strategy trader.

    It deliberately does not use one universal rule for all 50 products.

    Group logic:
    - Galaxy: one-name structural leader carry.
    - Sleep Pods: active trend-following because the within-group static ranks flip.
    - Microchips: cross-sectional shape spread.
    - Pebbles: size-curve relative-strength spread.
    - Robots: bursty active momentum.
    - UV: Amber-short / Red-Magenta-long carry.
    - Translators: cautious half-size relative pair.
    - Panels: 2x4 relative winner plus active 1x4 short.
    - Oxygen: Garlic structural long plus Morning active short.
    - Snackpacks: small relative basket.
    """

    LIMIT = 10
    VOL_ALPHA = 2.0 / 120.0

    STATIC_TARGETS: Dict[str, int] = {'GALAXY_SOUNDS_BLACK_HOLES': 10,
 'MICROCHIP_OVAL': -10,
 'MICROCHIP_RECTANGLE': -10,
 'MICROCHIP_SQUARE': 10,
 'MICROCHIP_TRIANGLE': -10,
 'OXYGEN_SHAKE_GARLIC': 10,
 'PANEL_1X2': -5,
 'PANEL_2X2': -10,
 'PANEL_2X4': 10,
 'PANEL_4X4': -10,
 'PEBBLES_L': -10,
 'PEBBLES_M': 10,
 'PEBBLES_S': -10,
 'PEBBLES_XL': 10,
 'PEBBLES_XS': -10,
 'SNACKPACK_CHOCOLATE': -5,
 'SNACKPACK_PISTACHIO': -10,
 'SNACKPACK_RASPBERRY': 5,
 'SNACKPACK_STRAWBERRY': 5,
 'SNACKPACK_VANILLA': 5,
 'TRANSLATOR_ASTRO_BLACK': -5,
 'TRANSLATOR_SPACE_GRAY': -5,
 'TRANSLATOR_VOID_BLUE': 5,
 'UV_VISOR_AMBER': -10,
 'UV_VISOR_MAGENTA': 10,
 'UV_VISOR_ORANGE': -5,
 'UV_VISOR_RED': 10}

    MOMENTUM_CFG: Dict[str, Dict[str, float]] = {'OXYGEN_SHAKE_MINT': {'L': 200,
                       'cooldown': 10,
                       'entry': 1.7,
                       'exit': -0.2,
                       'max_spread': 15,
                       'qty': 2,
                       'side': 1,
                       'sweep_extra': 0,
                       'target': 8},
 'OXYGEN_SHAKE_MORNING_BREATH': {'L': 500,
                                 'cooldown': 80,
                                 'entry': 0.9,
                                 'exit': 0.2,
                                 'max_spread': 15,
                                 'qty': 5,
                                 'side': -1,
                                 'sweep_extra': 5,
                                 'target': 10},
 'PANEL_1X2': {'L': 500,
               'cooldown': 50,
               'entry': 1.4,
               'exit': -0.2,
               'max_spread': 10,
               'qty': 3,
               'side': 1,
               'sweep_extra': 0,
               'target': 6},
 'PANEL_1X4': {'L': 100,
               'cooldown': 5,
               'entry': 1.2,
               'exit': 0.2,
               'max_spread': 10,
               'qty': 8,
               'side': -1,
               'sweep_extra': 1,
               'target': 10},
 'ROBOT_DISHES': {'L': 200,
                  'cooldown': 10,
                  'entry': 0.9,
                  'exit': -0.2,
                  'max_spread': 8,
                  'qty': 2,
                  'side': 1,
                  'sweep_extra': 0,
                  'target': 10},
 'ROBOT_IRONING': {'L': 500,
                   'cooldown': 80,
                   'entry': 0.9,
                   'exit': -0.2,
                   'max_spread': 8,
                   'qty': 1,
                   'side': -1,
                   'sweep_extra': 0,
                   'target': 10},
 'ROBOT_VACUUMING': {'L': 20,
                     'cooldown': 80,
                     'entry': 1.6,
                     'exit': -0.2,
                     'max_spread': 8,
                     'qty': 8,
                     'side': -1,
                     'sweep_extra': 0,
                     'target': 10},
 'SLEEP_POD_COTTON': {'L': 200,
                      'cooldown': 80,
                      'entry': 0.9,
                      'exit': -0.2,
                      'max_spread': 12,
                      'qty': 6,
                      'side': 1,
                      'sweep_extra': 1,
                      'target': 10},
 'SLEEP_POD_LAMB_WOOL': {'L': 500,
                         'cooldown': 5,
                         'entry': 1.6,
                         'exit': 0.2,
                         'max_spread': 11,
                         'qty': 5,
                         'side': 1,
                         'sweep_extra': 4,
                         'target': 10},
 'SLEEP_POD_POLYESTER': {'L': 200,
                         'cooldown': 100,
                         'entry': 1.8,
                         'exit': 0.3,
                         'max_spread': 12,
                         'qty': 2,
                         'side': 1,
                         'sweep_extra': 0,
                         'target': 5},
 'SLEEP_POD_SUEDE': {'L': 500,
                     'cooldown': 80,
                     'entry': 0.9,
                     'exit': 0.2,
                     'max_spread': 12,
                     'qty': 5,
                     'side': 1,
                     'sweep_extra': 0,
                     'target': 10}}

    GROUP_MAX_SPREAD: Dict[str, int] = {
        "GALAXY": 40, "SLEEP": 14, "MICROCHIP": 30, "PEBBLES": 40, "ROBOT": 10,
        "UV": 35, "TRANSLATOR": 25, "PANEL": 30, "OXYGEN": 40, "SNACK": 35
    }

    PRODUCT_GROUP: Dict[str, str] = {
        "GALAXY_SOUNDS_BLACK_HOLES": "GALAXY",
        "GALAXY_SOUNDS_DARK_MATTER": "GALAXY",
        "GALAXY_SOUNDS_PLANETARY_RINGS": "GALAXY",
        "GALAXY_SOUNDS_SOLAR_FLAMES": "GALAXY",
        "GALAXY_SOUNDS_SOLAR_WINDS": "GALAXY",
        "SLEEP_POD_COTTON": "SLEEP", "SLEEP_POD_LAMB_WOOL": "SLEEP", "SLEEP_POD_NYLON": "SLEEP",
        "SLEEP_POD_POLYESTER": "SLEEP", "SLEEP_POD_SUEDE": "SLEEP",
        "MICROCHIP_CIRCLE": "MICROCHIP", "MICROCHIP_OVAL": "MICROCHIP", "MICROCHIP_RECTANGLE": "MICROCHIP",
        "MICROCHIP_SQUARE": "MICROCHIP", "MICROCHIP_TRIANGLE": "MICROCHIP",
        "PEBBLES_XS": "PEBBLES", "PEBBLES_S": "PEBBLES", "PEBBLES_M": "PEBBLES", "PEBBLES_L": "PEBBLES", "PEBBLES_XL": "PEBBLES",
        "ROBOT_DISHES": "ROBOT", "ROBOT_IRONING": "ROBOT", "ROBOT_LAUNDRY": "ROBOT", "ROBOT_MOPPING": "ROBOT", "ROBOT_VACUUMING": "ROBOT",
        "UV_VISOR_AMBER": "UV", "UV_VISOR_MAGENTA": "UV", "UV_VISOR_ORANGE": "UV", "UV_VISOR_RED": "UV", "UV_VISOR_YELLOW": "UV",
        "TRANSLATOR_ASTRO_BLACK": "TRANSLATOR", "TRANSLATOR_ECLIPSE_CHARCOAL": "TRANSLATOR",
        "TRANSLATOR_GRAPHITE_MIST": "TRANSLATOR", "TRANSLATOR_SPACE_GRAY": "TRANSLATOR", "TRANSLATOR_VOID_BLUE": "TRANSLATOR",
        "PANEL_1X2": "PANEL", "PANEL_1X4": "PANEL", "PANEL_2X2": "PANEL", "PANEL_2X4": "PANEL", "PANEL_4X4": "PANEL",
        "OXYGEN_SHAKE_CHOCOLATE": "OXYGEN", "OXYGEN_SHAKE_EVENING_BREATH": "OXYGEN", "OXYGEN_SHAKE_GARLIC": "OXYGEN",
        "OXYGEN_SHAKE_MINT": "OXYGEN", "OXYGEN_SHAKE_MORNING_BREATH": "OXYGEN",
        "SNACKPACK_CHOCOLATE": "SNACK", "SNACKPACK_PISTACHIO": "SNACK", "SNACKPACK_RASPBERRY": "SNACK",
        "SNACKPACK_STRAWBERRY": "SNACK", "SNACKPACK_VANILLA": "SNACK",
    }

    PRODUCTS = set(STATIC_TARGETS.keys()) | set(MOMENTUM_CFG.keys())
    PRODUCT_MAX_DELTAS = {p: int(c["L"]) + 1 for p, c in MOMENTUM_CFG.items()}

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

    @staticmethod
    def timestamp_to_step(timestamp: int) -> int:
        return int(timestamp // 100) if timestamp >= 100 else int(timestamp)

    def save_state(self, s: Dict) -> str:
        return json.dumps(s, separators=(",", ":"))

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

    def compute_momentum_target(self, s: Dict, product: str, vol: float) -> int:
        cfg = self.MOMENTUM_CFG[product]
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

        target = max(-self.LIMIT, min(self.LIMIT, int(target)))
        s["t"][product] = target
        return target

    def walk_to_target(self, product: str, depth: OrderDepth, position: int, target: int, qty_cap: int, max_spread: int, sweep_extra: int = 0) -> List[Order]:
        target = max(-self.LIMIT, min(self.LIMIT, int(target)))
        position = int(position)
        delta = target - position
        if delta == 0:
            return []

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return []
        best_bid, best_ask, _, _ = bb_ba
        if best_ask - best_bid > max_spread:
            return []

        orders: List[Order] = []
        if delta > 0:
            remaining = min(int(qty_cap), delta, self.LIMIT - position)
            first_ask = None
            taken = 0
            limit_price = None
            for ask_price, ask_qty_neg in sorted(depth.sell_orders.items()):
                ask_qty = -int(ask_qty_neg)
                if ask_qty <= 0 or remaining <= 0:
                    break
                if first_ask is None:
                    first_ask = int(ask_price)
                elif int(ask_price) - first_ask > sweep_extra:
                    break
                qty = min(ask_qty, remaining)
                taken += qty
                remaining -= qty
                limit_price = int(ask_price)
            if taken > 0 and limit_price is not None:
                orders.append(Order(product, limit_price, taken))
        else:
            remaining = min(int(qty_cap), -delta, self.LIMIT + position)
            first_bid = None
            taken = 0
            limit_price = None
            for bid_price, bid_qty in sorted(depth.buy_orders.items(), reverse=True):
                bid_qty = int(bid_qty)
                if bid_qty <= 0 or remaining <= 0:
                    break
                if first_bid is None:
                    first_bid = int(bid_price)
                elif first_bid - int(bid_price) > sweep_extra:
                    break
                qty = min(bid_qty, remaining)
                taken += qty
                remaining -= qty
                limit_price = int(bid_price)
            if taken > 0 and limit_price is not None:
                orders.append(Order(product, limit_price, -taken))

        return orders

    def run(self, state: TradingState):
        s = self.load_state(state.traderData)
        result: Dict[str, List[Order]] = {}
        step = self.timestamp_to_step(int(getattr(state, "timestamp", 0)))

        for product, depth in state.order_depths.items():
            if product not in self.PRODUCTS:
                continue

            # Static group-relative targets have priority because they express the group-level view.
            if product in self.STATIC_TARGETS and int(self.STATIC_TARGETS[product]) != 0:
                group = self.PRODUCT_GROUP.get(product, "")
                max_spread = self.GROUP_MAX_SPREAD.get(group, 30)
                orders = self.walk_to_target(
                    product, depth, int(state.position.get(product, 0)),
                    int(self.STATIC_TARGETS[product]), qty_cap=10, max_spread=max_spread, sweep_extra=40
                )
                if orders:
                    result[product] = orders
                continue

            if product not in self.MOMENTUM_CFG:
                continue

            bb_ba = self.best_bid_ask(depth)
            if bb_ba is None:
                continue
            best_bid, best_ask, _, _ = bb_ba
            mid = (best_bid + best_ask) / 2.0
            vol = self.update_mid_state(s, product, mid)
            target = self.compute_momentum_target(s, product, vol)

            last_trade_step = int(s["lt"].get(product, -10**9))
            cooldown = int(self.MOMENTUM_CFG[product]["cooldown"])
            if step - last_trade_step < cooldown:
                continue

            cfg = self.MOMENTUM_CFG[product]
            orders = self.walk_to_target(
                product, depth, int(state.position.get(product, 0)), target,
                qty_cap=int(cfg["qty"]), max_spread=int(cfg["max_spread"]), sweep_extra=int(cfg.get("sweep_extra", 0))
            )
            if orders:
                result[product] = orders
                s["lt"][product] = step

        return result, 0, self.save_state(s)
