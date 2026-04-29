from typing import Dict, List, Tuple, Optional
import math
import json

try:
    import jsonpickle
except Exception:
    class _JsonPickleFallback:
        @staticmethod
        def encode(value):
            return json.dumps(value)

        @staticmethod
        def decode(value):
            return json.loads(value)

    jsonpickle = _JsonPickleFallback()

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
    Round 5 selected-product strategy with passive MM + controlled active taker layer.

    Core idea:
    1) Keep the original selected passive market-making engine on products that looked clean.
    2) Add a SMALL active layer only for historically robust, side-specific momentum signals.
       This is deliberately asymmetric: some products are active-buy candidates, others are
       active-sell candidates. Do not use the same signal both ways on every product.
    3) Respect the universal Round 5 position limit of 10 by keeping active targets below
       the hard limit and using passive quotes for most inventory management.

    Why active is restricted:
    - Crossing the spread is expensive.
    - Position limit is only 10.
    - Many Round 5 products look similar but do not have equally reliable timing.
    """

    LIMIT = 10

    # Products kept from the passive baseline.
    PASSIVE_PRODUCTS = {
        "TRANSLATOR_VOID_BLUE",
        "SLEEP_POD_SUEDE",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "OXYGEN_SHAKE_MORNING_BREATH",
        "SNACKPACK_PISTACHIO",
        "GALAXY_SOUNDS_BLACK_HOLES",
        "SNACKPACK_VANILLA",
        "SLEEP_POD_NYLON",
    }

    # Side-specific active momentum candidates from days 2/3/4.
    #
    # side = +1 means only actively BUY when momentum is strongly positive.
    # side = -1 means only actively SELL when momentum is strongly negative.
    #
    # target is intentionally below the hard position limit. The active layer should build
    # conviction, not slam straight into +/-10 every time.
    ACTIVE_TAKER = {
        # Strongest and most robust active-buy signal in the sample.
        "GALAXY_SOUNDS_BLACK_HOLES": {
            "side": 1, "entry": 2.0, "exit": 0.40, "target": 8, "qty": 2,
            "warmup": 450, "cooldown": 300, "max_spread": 18
        },

        # Strong robust active-buy signal, but smaller size because it was not in passive baseline.
        "UV_VISOR_MAGENTA": {
            "side": 1, "entry": 2.5, "exit": 0.40, "target": 5, "qty": 1,
            "warmup": 450, "cooldown": 400, "max_spread": 18
        },

        # Strongest active-sell signal among the oxygen products.
        "OXYGEN_SHAKE_MORNING_BREATH": {
            "side": -1, "entry": 1.5, "exit": 0.40, "target": 7, "qty": 2,
            "warmup": 450, "cooldown": 350, "max_spread": 18
        },

        # Galaxy solar flames had a clean negative-momentum continuation signal.
        "GALAXY_SOUNDS_SOLAR_FLAMES": {
            "side": -1, "entry": 2.5, "exit": 0.40, "target": 5, "qty": 1,
            "warmup": 450, "cooldown": 400, "max_spread": 18
        },

        # Smaller satellite signals. Keep these mild; they diversify but are lower conviction.
        "PANEL_1X2": {
            "side": -1, "entry": 2.5, "exit": 0.40, "target": 4, "qty": 1,
            "warmup": 450, "cooldown": 500, "max_spread": 18
        },
        "MICROCHIP_OVAL": {
            "side": -1, "entry": 1.5, "exit": 0.35, "target": 4, "qty": 1,
            "warmup": 450, "cooldown": 500, "max_spread": 18
        },
        "SLEEP_POD_COTTON": {
            "side": 1, "entry": 1.5, "exit": 0.35, "target": 4, "qty": 1,
            "warmup": 450, "cooldown": 500, "max_spread": 18
        },
        "ROBOT_VACUUMING": {
            "side": -1, "entry": 2.0, "exit": 0.35, "target": 4, "qty": 1,
            "warmup": 450, "cooldown": 500, "max_spread": 18
        },
    }

    TRADED_PRODUCTS = PASSIVE_PRODUCTS | set(ACTIVE_TAKER.keys())

    # Passive quote sizes from the original baseline.
    QUOTE_SIZE = {
        "TRANSLATOR_VOID_BLUE": 2,
        "SLEEP_POD_SUEDE": 2,
        "TRANSLATOR_ECLIPSE_CHARCOAL": 2,
        "OXYGEN_SHAKE_MORNING_BREATH": 2,
        "SNACKPACK_PISTACHIO": 2,
        "GALAXY_SOUNDS_BLACK_HOLES": 1,
        "SNACKPACK_VANILLA": 1,
        "SLEEP_POD_NYLON": 1,
    }

    CAUTIOUS_PRODUCTS = {
        "GALAXY_SOUNDS_BLACK_HOLES",
        "SNACKPACK_VANILLA",
        "SLEEP_POD_NYLON",
    }

    # Indicators:
    # - fast/slow are for momentum state.
    # - vol is EWMA absolute mid move, used to normalize signal strength.
    FAST_ALPHA = 2.0 / 35.0
    SLOW_ALPHA = 2.0 / 350.0
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
        best_bid_volume = depth.buy_orders[best_bid]              # positive
        best_ask_volume = -depth.sell_orders[best_ask]            # convert to positive
        return best_bid, best_ask, best_bid_volume, best_ask_volume

    @staticmethod
    def clamp_int(x: int, lo: int, hi: int) -> int:
        if x < lo:
            return lo
        if x > hi:
            return hi
        return x

    def load_state(self, trader_data: str) -> Dict:
        if trader_data:
            try:
                saved = jsonpickle.decode(trader_data)
                if isinstance(saved, dict):
                    saved.setdefault("p", {})
                    saved.setdefault("last_active", {})
                    return saved
            except Exception:
                pass
        return {"p": {}, "last_active": {}}

    def update_indicators(self, saved: Dict, product: str, mid: float) -> Dict:
        pdata = saved["p"].setdefault(product, {})

        if "fast" not in pdata:
            pdata["fast"] = mid
            pdata["slow"] = mid
            pdata["vol"] = 1.0
            pdata["last"] = mid
            pdata["n"] = 1
            pdata["mom"] = 0.0
            return pdata

        last = pdata.get("last", mid)
        move = abs(mid - last)

        pdata["fast"] = self.FAST_ALPHA * mid + (1.0 - self.FAST_ALPHA) * pdata["fast"]
        pdata["slow"] = self.SLOW_ALPHA * mid + (1.0 - self.SLOW_ALPHA) * pdata["slow"]
        pdata["vol"] = self.VOL_ALPHA * move + (1.0 - self.VOL_ALPHA) * max(pdata.get("vol", 1.0), 1.0)
        pdata["last"] = mid
        pdata["n"] = int(pdata.get("n", 0)) + 1

        vol_scale = max(5.0, pdata["vol"] * 6.0)
        pdata["mom"] = (pdata["fast"] - pdata["slow"]) / vol_scale
        return pdata

    def active_taker_orders(
        self,
        product: str,
        depth: OrderDepth,
        position: int,
        pdata: Dict,
        saved: Dict,
        timestamp: int,
        buy_capacity: int,
        sell_capacity: int,
    ) -> Tuple[List[Order], int, int, int]:
        """
        Returns: (orders, expected_position, remaining_buy_capacity, remaining_sell_capacity)
        Active orders are designed to cross only the best visible bid/ask.
        """
        orders: List[Order] = []
        cfg = self.ACTIVE_TAKER.get(product)
        if cfg is None:
            return orders, position, buy_capacity, sell_capacity

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return orders, position, buy_capacity, sell_capacity

        best_bid, best_ask, best_bid_vol, best_ask_vol = bb_ba
        spread = best_ask - best_bid
        if spread <= 0 or spread > int(cfg.get("max_spread", 18)):
            return orders, position, buy_capacity, sell_capacity

        if int(pdata.get("n", 0)) < int(cfg.get("warmup", 450)):
            return orders, position, buy_capacity, sell_capacity

        last_active = int(saved.get("last_active", {}).get(product, -10**9))
        cooldown = int(cfg.get("cooldown", 400))
        if timestamp - last_active < cooldown:
            return orders, position, buy_capacity, sell_capacity

        mom = float(pdata.get("mom", 0.0))
        side = int(cfg["side"])
        entry = float(cfg["entry"])
        exit_thr = float(cfg.get("exit", 0.4))
        target_abs = int(cfg["target"])
        qty_base = int(cfg.get("qty", 1))

        expected_position = position

        # Build in the configured direction only when signal is very strong.
        directional_signal = side * mom

        if directional_signal >= entry:
            target = side * target_abs

            if side > 0 and expected_position < target and buy_capacity > 0:
                qty = min(qty_base, buy_capacity, best_ask_vol, target - expected_position)
                if qty > 0:
                    orders.append(Order(product, int(best_ask), int(qty)))
                    expected_position += qty
                    buy_capacity -= qty
                    saved["last_active"][product] = timestamp

            elif side < 0 and expected_position > target and sell_capacity > 0:
                qty = min(qty_base, sell_capacity, best_bid_vol, expected_position - target)
                if qty > 0:
                    orders.append(Order(product, int(best_bid), -int(qty)))
                    expected_position -= qty
                    sell_capacity -= qty
                    saved["last_active"][product] = timestamp

        # Emergency active exit only when the signal actually turns against the active side.
        # This prevents holding stale active inventory through a clear reversal.
        elif directional_signal <= -exit_thr:
            if side > 0 and expected_position > 0 and sell_capacity > 0:
                qty = min(qty_base, sell_capacity, best_bid_vol, expected_position)
                if qty > 0:
                    orders.append(Order(product, int(best_bid), -int(qty)))
                    expected_position -= qty
                    sell_capacity -= qty
                    saved["last_active"][product] = timestamp

            elif side < 0 and expected_position < 0 and buy_capacity > 0:
                qty = min(qty_base, buy_capacity, best_ask_vol, -expected_position)
                if qty > 0:
                    orders.append(Order(product, int(best_ask), int(qty)))
                    expected_position += qty
                    buy_capacity -= qty
                    saved["last_active"][product] = timestamp

        return orders, expected_position, buy_capacity, sell_capacity

    def passive_quote_orders(
        self,
        product: str,
        depth: OrderDepth,
        expected_position: int,
        pdata: Dict,
        buy_capacity: int,
        sell_capacity: int,
    ) -> List[Order]:
        orders: List[Order] = []

        if product not in self.PASSIVE_PRODUCTS:
            return orders

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return orders

        best_bid, best_ask, _, _ = bb_ba
        spread = best_ask - best_bid

        # Do not fight for tiny spreads. We need compensation for adverse selection.
        if spread < 4:
            return orders

        mid = (best_bid + best_ask) / 2.0
        mom = float(pdata.get("mom", 0.0))

        base_size = self.QUOTE_SIZE.get(product, 1)
        if product in self.CAUTIOUS_PRODUCTS:
            mom_threshold = 0.55
            soft_inventory = 6
        else:
            mom_threshold = 0.75
            soft_inventory = 7

        bid_qty = min(base_size, buy_capacity)
        ask_qty = min(base_size, sell_capacity)

        # Inventory guard: do not keep worsening inventory near the edges.
        if expected_position >= soft_inventory:
            bid_qty = 0
        if expected_position <= -soft_inventory:
            ask_qty = 0

        # Trend/adverse-selection guard.
        if mom > mom_threshold and expected_position <= 0:
            ask_qty = 0
        elif mom < -mom_threshold and expected_position >= 0:
            bid_qty = 0

        # Basic inside-spread prices.
        bid_price = best_bid + 1
        ask_price = best_ask - 1

        # Inventory skew.
        skew = 0
        if abs(expected_position) >= 4:
            skew = 1
        if abs(expected_position) >= 8:
            skew = 2

        if expected_position > 0:
            bid_price -= skew
            ask_price -= min(skew, 1)
        elif expected_position < 0:
            bid_price += min(skew, 1)
            ask_price += skew

        # Momentum quote skew.
        if mom > mom_threshold:
            bid_price += 1
            ask_price += 1
        elif mom < -mom_threshold:
            bid_price -= 1
            ask_price -= 1

        # Never cross.
        bid_price = int(min(bid_price, best_ask - 1))
        ask_price = int(max(ask_price, best_bid + 1))

        if bid_price >= ask_price:
            return orders

        # Extra guard for very wide, volatile moments: quote smaller.
        if spread >= 18:
            bid_qty = min(bid_qty, 1)
            ask_qty = min(ask_qty, 1)

        if bid_qty > 0:
            orders.append(Order(product, bid_price, int(bid_qty)))

        if ask_qty > 0:
            orders.append(Order(product, ask_price, -int(ask_qty)))

        return orders

    def run(self, state: TradingState):
        saved = self.load_state(state.traderData)
        result: Dict[str, List[Order]] = {}

        timestamp = int(getattr(state, "timestamp", 0))

        for product, depth in state.order_depths.items():
            result[product] = []

            if product not in self.TRADED_PRODUCTS:
                continue

            bb_ba = self.best_bid_ask(depth)
            if bb_ba is None:
                continue

            best_bid, best_ask, _, _ = bb_ba
            mid = (best_bid + best_ask) / 2.0
            pdata = self.update_indicators(saved, product, mid)

            position = int(state.position.get(product, 0))
            buy_capacity = max(0, self.LIMIT - position)
            sell_capacity = max(0, self.LIMIT + position)

            # 1) Active taker layer first. It consumes capacity if it crosses.
            active_orders, expected_position, buy_capacity, sell_capacity = self.active_taker_orders(
                product=product,
                depth=depth,
                position=position,
                pdata=pdata,
                saved=saved,
                timestamp=timestamp,
                buy_capacity=buy_capacity,
                sell_capacity=sell_capacity,
            )

            # 2) Passive MM layer with whatever capacity remains.
            passive_orders = self.passive_quote_orders(
                product=product,
                depth=depth,
                expected_position=expected_position,
                pdata=pdata,
                buy_capacity=buy_capacity,
                sell_capacity=sell_capacity,
            )

            result[product] = active_orders + passive_orders

        traderData = jsonpickle.encode(saved)
        conversions = 0
        return result, conversions, traderData
