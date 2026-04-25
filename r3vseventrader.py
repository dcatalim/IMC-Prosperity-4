import json
import math
from typing import Any

from datamodel import (
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Symbol,
    Trade,
    TradingState,
)

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: dict[Symbol, list[Order]],
        conversions: int,
        trader_data: Any,
    ) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                    "",
                ]
            )
        )
        max_item_length = (self.max_log_length - base_length) // 3
        print(
            self.to_json(
                [
                    self.compress_state(
                        state, self.truncate(state.traderData, max_item_length)
                    ),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [
            [listing.symbol, listing.product, listing.denomination]
            for listing in listings.values()
        ]

    def compress_order_depths(
        self, order_depths: dict[Symbol, OrderDepth]
    ) -> dict[Symbol, list[Any]]:
        return {
            symbol: [order_depth.buy_orders, order_depth.sell_orders]
            for symbol, order_depth in order_depths.items()
        }

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out

LOGGER = Logger()

class Trader:
    HYDRO = "HYDROGEL_PACK"
    VELVET = "VELVETFRUIT_EXTRACT"
    
    # Categorized Vouchers for specific logic
    ITM_VOUCHERS = {"VEV_4000": 4000, "VEV_4500": 4500}
    ATM_VOUCHERS = {"VEV_5000": 5000, "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300, "VEV_5400": 5400, "VEV_5500": 5500}
    OTM_VOUCHERS = {"VEV_6000": 6000, "VEV_6500": 6500}

    def __init__(self) -> None:
        self.limits = {
            self.HYDRO: 200, self.VELVET: 200,
            **{symbol: 300 for symbol in self.ITM_VOUCHERS},
            **{symbol: 300 for symbol in self.ATM_VOUCHERS},
            **{symbol: 300 for symbol in self.OTM_VOUCHERS}
        }

    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / 1.41421356))

    def bs_call_with_delta(self, spot: float, strike: float, tte: float, sigma: float):
        if spot <= 0: return 0.0, 0.0
        if tte <= 0: return max(0.0, spot - strike), 1.0 if spot > strike else 0.0
        sigma = max(1e-6, sigma)
        tte = max(1e-6, tte)
        d1 = (math.log(spot / strike) + 0.5 * sigma**2 * tte) / (sigma * math.sqrt(tte))
        d2 = d1 - sigma * math.sqrt(tte)
        delta = self.norm_cdf(d1)
        price = spot * delta - strike * self.norm_cdf(d2)
        return price, delta
        
    def get_smile_sigma(self, spot: float, strike: float) -> float:
        # Generalized Volatility Smile from Dinis (avoiding the hardcoded overfit biases)
        # sigma(m) = 0.0307 m^2 + 0.0021 m + 0.2306  where m = ln(K/S)
        if spot <= 0: return 0.23
        m = math.log(strike / spot)
        return (0.0307 * (m ** 2)) + (0.0021 * m) + 0.2306

    def get_book_stats(self, depth: OrderDepth):
        if not depth.buy_orders or not depth.sell_orders: return None
        best_bid, b_vol = max(depth.buy_orders.items())
        best_ask, a_vol = min(depth.sell_orders.items())
        mid = (best_bid + best_ask) / 2.0
        # Microprice handles toxic flow/adverse selection
        micro = (best_bid * abs(a_vol) + best_ask * b_vol) / (b_vol + abs(a_vol))
        return {"mid": mid, "micro": micro, "bid": best_bid, "ask": best_ask, "spread": best_ask - best_bid}

    def run(self, state: TradingState):
        result: dict[Symbol, list[Order]] = {}
        
        # 1. UNDERLYING STATS (Extract)
        e_depth = state.order_depths.get(self.VELVET)
        e_stats = self.get_book_stats(e_depth) if e_depth else None
        
        total_delta = 0.0
        tte = max(0.0001, 5.0 - state.timestamp / 1_000_000.0) # Assume starting TTE is 5 for R3
        
        if e_stats:
            spot_price = e_stats['micro']
            
            # --- 2. DEEP ITM VOUCHERS (Delta = 1) ---
            for symbol, strike in self.ITM_VOUCHERS.items():
                v_pos = state.position.get(symbol, 0)
                total_delta += v_pos * 1.0 # Delta is effectively 1
                
                v_depth = state.order_depths.get(symbol)
                v_stats = self.get_book_stats(v_depth) if v_depth else None
                if not v_stats: continue
                
                # Fair price is just intrinsic value
                v_fair = spot_price - strike
                width = 1.0 + (abs(v_pos) / 100.0)
                v_bid = math.floor(v_fair - width)
                v_ask = math.ceil(v_fair + width)
                
                v_orders = []
                if v_pos < 300: v_orders.append(Order(symbol, int(min(v_bid, v_stats['ask']-1)), 15))
                if v_pos > -300: v_orders.append(Order(symbol, int(max(v_ask, v_stats['bid']+1)), -15))
                if v_orders: result[symbol] = v_orders

            # --- 3. ATM VOUCHERS (Smile + Dynamic Width) ---
            for symbol, strike in self.ATM_VOUCHERS.items():
                v_pos = state.position.get(symbol, 0)
                v_depth = state.order_depths.get(symbol)
                v_stats = self.get_book_stats(v_depth) if v_depth else None
                if not v_stats: continue
                
                sigma = self.get_smile_sigma(spot_price, strike)
                v_fair, delta = self.bs_call_with_delta(spot_price, strike, tte, sigma)
                total_delta += v_pos * delta
                
                # Dynamic width from V6 to prevent maxing out inventory
                width = 1.5 + (abs(v_pos) / 60.0)
                v_bid = math.floor(v_fair - width)
                v_ask = math.ceil(v_fair + width)
                
                v_orders = []
                if v_pos < 300: v_orders.append(Order(symbol, int(min(v_bid, v_stats['ask']-1)), 15))
                if v_pos > -300: v_orders.append(Order(symbol, int(max(v_ask, v_stats['bid']+1)), -15))
                if v_orders: result[symbol] = v_orders

            # --- 4. DEEP OTM VOUCHERS (The Dinis Free Money Hack) ---
            for symbol, strike in self.OTM_VOUCHERS.items():
                v_pos = state.position.get(symbol, 0)
                v_orders = []
                # Always try to buy for 0 (no downside)
                if v_pos < 300:
                    v_orders.append(Order(symbol, 0, 300 - v_pos))
                # If we somehow get them, sell them for 1 immediately
                if v_pos > 0:
                    v_orders.append(Order(symbol, 1, -v_pos))
                if v_orders: result[symbol] = v_orders

            # --- 5. TRADE EXTRACT (Delta Hedging with Microprice) ---
            e_pos = state.position.get(self.VELVET, 0)
            hedge_offset = -(total_delta + e_pos) 
            
            e_fair = 0.5 * e_stats['micro'] + 0.5 * e_stats['mid']
            e_res = e_fair + (0.1 * hedge_offset)
            
            e_orders = []
            e_bid = math.floor(e_res - 2)
            e_ask = math.ceil(e_res + 2)
            
            if e_pos < 200: e_orders.append(Order(self.VELVET, int(min(e_bid, e_stats['ask']-1)), 20))
            if e_pos > -200: e_orders.append(Order(self.VELVET, int(max(e_ask, e_stats['bid']+1)), -20))
            result[self.VELVET] = e_orders

        # --- 6. HYDROGEL_PACK (Mid-Price Reversion) ---
        h_depth = state.order_depths.get(self.HYDRO)
        if h_depth:
            h_stats = self.get_book_stats(h_depth)
            if h_stats:
                h_pos = state.position.get(self.HYDRO, 0)
                # Dinis style: Center around the current mid instead of a flat 10,000
                h_fair = h_stats['mid'] 
                h_orders = []
                
                # V6 style: Inventory shifting
                h_bid = h_fair - 2 if h_pos < 0 else h_fair - 3
                h_ask = h_fair + 2 if h_pos > 0 else h_fair + 3
                
                if h_pos < 200: h_orders.append(Order(self.HYDRO, int(h_bid), 200 - h_pos))
                if h_pos > -200: h_orders.append(Order(self.HYDRO, int(h_ask), - (h_pos + 200)))
                result[self.HYDRO] = h_orders

        LOGGER.flush(state, result, 0, "")
        return result, 0, ""