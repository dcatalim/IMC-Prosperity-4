import json
import math
from typing import Any
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: Any) -> None:
        print(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, trader_data, self.truncate(self.logs, 1000)]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [state.timestamp, trader_data, [], self.compress_order_depths(state.order_depths), [], [], state.position, []]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {symbol: [order_depth.buy_orders, order_depth.sell_orders] for symbol, order_depth in order_depths.items()}

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr: compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str: return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))
    def truncate(self, value: str, max_length: int) -> str: return value[:max_length] + "..." if len(value) > max_length else value

LOGGER = Logger()

class Trader:
    HYDRO = "HYDROGEL_PACK"
    VELVET = "VELVETFRUIT_EXTRACT"
    VOUCHERS = {"VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500}

    def __init__(self) -> None:
        self.limits = {self.HYDRO: 200, self.VELVET: 200, **{s: 300 for s in self.VOUCHERS}, "VEV_6000": 300, "VEV_6500": 300}

    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / 1.41421356))

    def bs_call(self, S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0: return max(0.0, S - K)
        d1 = (math.log(S / K) + (0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.norm_cdf(d1) - K * self.norm_cdf(d2)

    def get_book_stats(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders: return None
        best_bid, bid_vol = max(depth.buy_orders.items())
        best_ask, ask_vol = min(depth.sell_orders.items())
        mid = (best_bid + best_ask) / 2.0
        # Micro-price uses imbalance to predict the next tick move
        micro = (best_bid * abs(ask_vol) + best_ask * bid_vol) / (bid_vol + abs(ask_vol))
        return {"mid": mid, "micro": micro, "bid": best_bid, "ask": best_ask, "spread": best_ask - best_bid}

    def run(self, state: TradingState):
        result = {}
        # Load Cache
        try:
            cache = json.loads(state.traderData) if state.traderData else {}
        except:
            cache = {}
        
        cache.setdefault("sigma", 0.0132)
        cache.setdefault("v_ema", {})

        # 1. Trade VELVETFRUIT_EXTRACT
        v_depth = state.order_depths.get(self.VELVET)
        v_stats = self.get_book_stats(v_depth)
        velvet_fair = None

        if v_stats:
            pos = state.position.get(self.VELVET, 0)
            # Use Micro-price for faster reaction to dips
            velvet_fair = 0.4 * v_stats["micro"] + 0.6 * v_stats["mid"]
            v_orders = []
            
            # Reduce inventory aggressively if we are leaning too far one way
            bid_price = math.floor(velvet_fair - 2 - (0.05 * pos))
            ask_price = math.ceil(velvet_fair + 2 - (0.05 * pos))
            
            if pos < self.limits[self.VELVET]:
                v_orders.append(Order(self.VELVET, bid_price, min(20, self.limits[self.VELVET] - pos)))
            if pos > -self.limits[self.VELVET]:
                v_orders.append(Order(self.VELVET, ask_price, -min(20, pos + self.limits[self.VELVET])))
            result[self.VELVET] = v_orders

        # 2. Trade VOUCHERS
        if velvet_fair:
            tte = max(0.0001, 5.0 - (state.timestamp / 1_000_000.0))
            sigma = cache["sigma"]
            
            for symbol, strike in self.VOUCHERS.items():
                d = state.order_depths.get(symbol)
                s = self.get_book_stats(d)
                if not s: continue
                
                v_fair = self.bs_call(velvet_fair, strike, tte, sigma)
                v_pos = state.position.get(symbol, 0)
                
                # Dynamic spread: wider spread when position is high
                v_edge = 1.5 + (abs(v_pos) / 100.0)
                
                v_orders = []
                # Market Take if there's significant mispricing (Aggressive entry)
                for price, vol in d.sell_orders.items():
                    if price < v_fair - (v_edge + 1) and v_pos < self.limits[symbol]:
                        buy_qty = min(-vol, self.limits[symbol] - v_pos)
                        v_orders.append(Order(symbol, price, buy_qty))
                        v_pos += buy_qty
                
                # Market Making (Passive entry)
                v_bid = math.floor(v_fair - v_edge)
                v_ask = math.ceil(v_fair + v_edge)
                
                if v_pos < self.limits[symbol]:
                    v_orders.append(Order(symbol, min(v_bid, s["ask"] - 1), 10))
                if v_pos > -self.limits[symbol]:
                    v_orders.append(Order(symbol, max(v_ask, s["bid"] + 1), -10))
                
                if v_orders: result[symbol] = v_orders

        # 3. Trade HYDROGEL_PACK (Mean Reversion)
        h_depth = state.order_depths.get(self.HYDRO)
        h_stats = self.get_book_stats(h_depth)
        if h_stats:
            h_pos = state.position.get(self.HYDRO, 0)
            h_fair = 10000 # Constant fair value for Hydrogel
            h_orders = []
            
            # Very aggressive mean reversion
            h_bid = h_fair - 2 if h_pos < 0 else h_fair - 3
            h_ask = h_fair + 2 if h_pos > 0 else h_fair + 3
            
            if h_pos < self.limits[self.HYDRO]:
                h_orders.append(Order(self.HYDRO, int(h_bid), self.limits[self.HYDRO] - h_pos))
            if h_pos > -self.limits[self.HYDRO]:
                h_orders.append(Order(self.HYDRO, int(h_ask), - (h_pos + self.limits[self.HYDRO])))
            result[self.HYDRO] = h_orders

        trader_data = json.dumps(cache)
        return result, 0, trader_data