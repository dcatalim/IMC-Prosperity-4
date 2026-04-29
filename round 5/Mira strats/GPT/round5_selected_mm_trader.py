from typing import Dict, List
import jsonpickle
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
    Round 5 selected-product passive market maker.

    Research summary behind this version:
    - All products have position limit 10, so inventory mistakes are expensive.
    - The strongest historical passive candidates in the attached days were a small
      subset, not the full 50-product universe.
    - This bot avoids active crossing. It posts inside-spread liquidity only.
    - A slow EMA momentum guard stops the bot from repeatedly buying into clear
      downtrends or selling into clear uptrends.
    """

    LIMIT = 10

    # Conservative whitelist from the attached day 2/3/4 prices + trades.
    # These were the cleanest under a simple passive fill approximation.
    ACTIVE_PRODUCTS = {
        "TRANSLATOR_VOID_BLUE",
        "SLEEP_POD_SUEDE",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "OXYGEN_SHAKE_MORNING_BREATH",
        "SNACKPACK_PISTACHIO",
        "GALAXY_SOUNDS_BLACK_HOLES",
        "SNACKPACK_VANILLA",
        "SLEEP_POD_NYLON",
    }

    # Slightly different quote sizes by product. Keep sizes small because limit = 10.
    QUOTE_SIZE = {
        "TRANSLATOR_VOID_BLUE": 2,
        "SLEEP_POD_SUEDE": 2,
        "TRANSLATOR_ECLIPSE_CHARCOAL": 2,
        "OXYGEN_SHAKE_MORNING_BREATH": 2,
        "SNACKPACK_PISTACHIO": 2,
        "GALAXY_SOUNDS_BLACK_HOLES": 1,  # more volatile; do not over-size
        "SNACKPACK_VANILLA": 1,
        "SLEEP_POD_NYLON": 1,
    }

    # Products with somewhat higher historical inventory/drawdown risk.
    CAUTIOUS_PRODUCTS = {
        "GALAXY_SOUNDS_BLACK_HOLES",
        "SNACKPACK_VANILLA",
        "SLEEP_POD_NYLON",
    }

    FAST_ALPHA = 2.0 / 35.0
    SLOW_ALPHA = 2.0 / 350.0
    VOL_ALPHA = 2.0 / 120.0

    def bid(self):
        # Ignored in Round 5, harmless to keep.
        return 15

    @staticmethod
    def best_bid_ask(depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders:
            return None
        best_bid = max(depth.buy_orders.keys())
        best_ask = min(depth.sell_orders.keys())
        return best_bid, best_ask

    @staticmethod
    def clamp(x: int, lo: int, hi: int) -> int:
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
                    return saved
            except Exception:
                pass
        return {"p": {}}

    def update_indicators(self, saved: Dict, product: str, mid: float):
        pdata = saved["p"].setdefault(product, {})

        if "fast" not in pdata:
            pdata["fast"] = mid
            pdata["slow"] = mid
            pdata["vol"] = 1.0
            pdata["last"] = mid
            return pdata

        last = pdata.get("last", mid)
        move = abs(mid - last)

        pdata["fast"] = self.FAST_ALPHA * mid + (1.0 - self.FAST_ALPHA) * pdata["fast"]
        pdata["slow"] = self.SLOW_ALPHA * mid + (1.0 - self.SLOW_ALPHA) * pdata["slow"]
        pdata["vol"] = self.VOL_ALPHA * move + (1.0 - self.VOL_ALPHA) * max(pdata.get("vol", 1.0), 1.0)
        pdata["last"] = mid
        return pdata

    def quote_product(self, product: str, depth: OrderDepth, position: int, pdata: Dict) -> List[Order]:
        orders: List[Order] = []

        bb_ba = self.best_bid_ask(depth)
        if bb_ba is None:
            return orders

        best_bid, best_ask = bb_ba
        spread = best_ask - best_bid

        # Do not fight for tiny spreads. We need compensation for adverse selection.
        if spread < 4:
            return orders

        mid = (best_bid + best_ask) / 2.0
        fast = pdata.get("fast", mid)
        slow = pdata.get("slow", mid)
        vol = max(pdata.get("vol", 1.0), 1.0)

        # Normalized slow momentum. Positive means avoid getting short;
        # negative means avoid getting long.
        # Use a deliberately slow scale so it does not flip on tiny bounces.
        mom = (fast - slow) / max(5.0, vol * 6.0)

        base_size = self.QUOTE_SIZE.get(product, 1)
        if product in self.CAUTIOUS_PRODUCTS:
            mom_threshold = 0.55
            soft_inventory = 6
        else:
            mom_threshold = 0.75
            soft_inventory = 7

        buy_capacity = self.LIMIT - position
        sell_capacity = self.LIMIT + position

        bid_qty = min(base_size, buy_capacity)
        ask_qty = min(base_size, sell_capacity)

        # Inventory guard: do not keep worsening inventory near the edges.
        if position >= soft_inventory:
            bid_qty = 0
        if position <= -soft_inventory:
            ask_qty = 0

        # Trend/adverse-selection guard.
        # If the product is trending up, do not post asks that build/increase a short.
        # If trending down, do not post bids that build/increase a long.
        if mom > mom_threshold and position <= 0:
            ask_qty = 0
        elif mom < -mom_threshold and position >= 0:
            bid_qty = 0

        # Basic inside-spread prices.
        bid_price = best_bid + 1
        ask_price = best_ask - 1

        # Inventory skew:
        # - Long inventory: less aggressive bids, slightly easier asks.
        # - Short inventory: slightly easier bids, less aggressive asks.
        skew = 0
        if abs(position) >= 4:
            skew = 1
        if abs(position) >= 8:
            skew = 2

        if position > 0:
            bid_price -= skew
            ask_price -= min(skew, 1)
        elif position < 0:
            bid_price += min(skew, 1)
            ask_price += skew

        # Momentum quote skew:
        # - Uptrend: improve bid by 1, make ask less attractive.
        # - Downtrend: improve ask by 1, make bid less attractive.
        if mom > mom_threshold:
            bid_price += 1
            ask_price += 1
        elif mom < -mom_threshold:
            bid_price -= 1
            ask_price -= 1

        # Never cross. If quotes collapse, skip the bad side.
        bid_price = int(min(bid_price, best_ask - 1))
        ask_price = int(max(ask_price, best_bid + 1))

        if bid_price >= ask_price:
            return orders

        # Extra guard for very wide, volatile moments: quote smaller.
        if spread >= 18:
            bid_qty = min(bid_qty, 1)
            ask_qty = min(ask_qty, 1)

        if bid_qty > 0:
            orders.append(Order(product, bid_price, bid_qty))

        if ask_qty > 0:
            orders.append(Order(product, ask_price, -ask_qty))

        return orders

    def run(self, state: TradingState):
        saved = self.load_state(state.traderData)
        result: Dict[str, List[Order]] = {}

        # First update indicators for active products that are visible.
        for product, depth in state.order_depths.items():
            result[product] = []

            if product not in self.ACTIVE_PRODUCTS:
                continue

            bb_ba = self.best_bid_ask(depth)
            if bb_ba is None:
                continue

            best_bid, best_ask = bb_ba
            mid = (best_bid + best_ask) / 2.0
            pdata = self.update_indicators(saved, product, mid)

            position = state.position.get(product, 0)
            result[product] = self.quote_product(product, depth, position, pdata)

        traderData = jsonpickle.encode(saved)
        conversions = 0
        return result, conversions, traderData
