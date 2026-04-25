import json
import math
from typing import Any, Dict, List, Tuple

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
                    conversions if hasattr(conversions, 'versions') else conversions, # Safety fallback
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


HYDRO = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
VOUCHERS: Dict[str, int] = {
    "VEV_4000": 4000,
    "VEV_4500": 4500,
    "VEV_5000": 5000,
    "VEV_5100": 5100,
    "VEV_5200": 5200,
    "VEV_5300": 5300,
    "VEV_5400": 5400,
    "VEV_5500": 5500,
    "VEV_6000": 6000,
    "VEV_6500": 6500,
}

POSITION_LIMITS: Dict[str, int] = {
    HYDRO: 200,
    VELVET: 200,
    **{sym: 300 for sym in VOUCHERS},
}

# Global long-run mids from historical data
LONG_RUN_MID: Dict[str, float] = {
    HYDRO: 9990.8069,
    VELVET: 5250.0981,
    "VEV_4000": 1250.1098,
    "VEV_4500": 750.1098,
    "VEV_5000": 252.0195,
    "VEV_5100": 166.4258,
    "VEV_5200": 102.7788,
    "VEV_5300": 53.3082,
    "VEV_5400": 20.3015,
    "VEV_5500": 7.7656,
    "VEV_6000": 0.5000,
    "VEV_6500": 0.5000,
}


class Trader:
    def norm_cdf(self, d: float) -> float:
        return 0.5 * (1.0 + math.erf(d / math.sqrt(2.0)))

    def bs_price(self, S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0:
            return max(0.0, S - K)
        if S <= 0 or K <= 0 or sigma <= 0:
            return 0.0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * self.norm_cdf(d1) - K * self.norm_cdf(d2)

    def get_smile_sigma(self, S: float, K: float) -> float:
        if S <= 0:
            return 0.2306
        m = math.log(K / S)
        return 0.0307 * m**2 + 0.0021 * m + 0.2306

    def trade_hydro(self, state: TradingState) -> List[Order]:
        orders: List[Order] = []
        if HYDRO not in state.order_depths:
            return orders
        od = state.order_depths[HYDRO]
        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        mid = (best_bid + best_ask) / 2.0
        pos = state.position.get(HYDRO, 0)
        
        # Taking logic
        take_edge = 2.0
        fair = mid
        for ask, vol in od.sell_orders.items():
            if ask <= fair - take_edge:
                qty = min(-vol, POSITION_LIMITS[HYDRO] - pos)
                if qty > 0:
                    orders.append(Order(HYDRO, ask, qty))
                    pos += qty
        for bid, vol in sorted(od.buy_orders.items(), reverse=True):
            if bid >= fair + take_edge:
                qty = min(vol, pos + POSITION_LIMITS[HYDRO])
                if qty > 0:
                    orders.append(Order(HYDRO, bid, -qty))
                    pos -= qty

        # Passive MM
        skew = -0.05 * pos
        mm_bid = int(math.floor(fair - 1.5 + skew))
        mm_ask = int(math.ceil(fair + 1.5 + skew))
        mm_bid = min(mm_bid, best_ask - 1)
        mm_ask = max(mm_ask, best_bid + 1)
        if mm_bid >= mm_ask:
            mm_ask = mm_bid + 1
            
        buy_cap = POSITION_LIMITS[HYDRO] - pos
        sell_cap = pos + POSITION_LIMITS[HYDRO]
        if buy_cap > 0:
            orders.append(Order(HYDRO, mm_bid, min(buy_cap, 15)))
        if sell_cap > 0:
            orders.append(Order(HYDRO, mm_ask, -min(sell_cap, 15)))

        return orders

    def trade_velvet(self, state: TradingState) -> Tuple[List[Order], float]:
        """
        Velvetfruit trading substituted with logic from r3vsixtrader.
        Returns the orders and the calculated 'fair' spot price to be passed to vouchers.
        """
        orders: List[Order] = []
        od = state.order_depths.get(VELVET)
        
        if not od or not od.buy_orders or not od.sell_orders:
            return orders, LONG_RUN_MID[VELVET]

        best_bid = max(od.buy_orders.keys())
        bid_vol = od.buy_orders[best_bid]
        best_ask = min(od.sell_orders.keys())
        ask_vol = od.sell_orders[best_ask]
        
        mid = (best_bid + best_ask) / 2.0
        
        # Micro-price handles toxic flow/adverse selection faster than mid-price
        micro = (best_bid * abs(ask_vol) + best_ask * bid_vol) / (bid_vol + abs(ask_vol))
        
        # Use Micro-price weighted for faster reaction to dips
        velvet_fair = 0.4 * micro + 0.6 * mid
        pos = state.position.get(VELVET, 0)
        
        # Reduce inventory aggressively if we are leaning too far one way
        bid_price = int(math.floor(velvet_fair - 2 - (0.05 * pos)))
        ask_price = int(math.ceil(velvet_fair + 2 - (0.05 * pos)))
        
        limit = POSITION_LIMITS[VELVET]
        
        if pos < limit:
            # We enforce a max clip size (e.g., 20) per tick to mimic r3vsixtrader pacing
            orders.append(Order(VELVET, bid_price, min(20, limit - pos)))
        if pos > -limit:
            orders.append(Order(VELVET, ask_price, -min(20, pos + limit)))
            
        return orders, velvet_fair

    def trade_vouchers_simple(self, state: TradingState, S: float) -> Dict[str, List[Order]]:
        ans: Dict[str, List[Order]] = {}
        day = state.day if hasattr(state, "day") else 0
        T_days = max(0.0, 5.0 - day - state.timestamp / 1_000_000.0)
        
        biases = {
            "VEV_5000": 0.0,
            "VEV_5100": 0.0,
            "VEV_5200": 0.77,
            "VEV_5300": 1.36,
            "VEV_5400": -2.16,
            "VEV_5500": 0.56,
        }

        for sym, K in VOUCHERS.items():
            if sym not in state.order_depths:
                continue
            od = state.order_depths[sym]
            if not od.buy_orders or not od.sell_orders:
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())
            pos = state.position.get(sym, 0)
            orders: List[Order] = []

            # Free MT hack for extreme OTM
            if K in [6000, 6500]:
                if pos < POSITION_LIMITS[sym]:
                    orders.append(Order(sym, 0, POSITION_LIMITS[sym] - pos))
                if pos > 0:
                    orders.append(Order(sym, 1, -pos))
                if orders:
                    ans[sym] = orders
                continue

            # Deep ITM Delta-1 tracking
            if K in [4000, 4500]:
                intrinsic = S - K
                fair = intrinsic
                take_edge = 3.0
                for ask, vol in od.sell_orders.items():
                    if ask <= fair - take_edge:
                        qty = min(-vol, POSITION_LIMITS[sym] - pos)
                        if qty > 0:
                            orders.append(Order(sym, ask, qty))
                            pos += qty
                for bid, vol in sorted(od.buy_orders.items(), reverse=True):
                    if bid >= fair + take_edge:
                        qty = min(vol, pos + POSITION_LIMITS[sym])
                        if qty > 0:
                            orders.append(Order(sym, bid, -qty))
                            pos -= qty
                if orders:
                    ans[sym] = orders
                continue

            # Calibrated Smile Math
            sigma = self.get_smile_sigma(S, K)
            base_fair = self.bs_price(S, K, T_days, sigma)
            fair = base_fair + biases.get(sym, 0.0)

            take_edge = 2.0
            for ask, vol in od.sell_orders.items():
                if ask <= fair - take_edge:
                    qty = min(-vol, POSITION_LIMITS[sym] - pos)
                    if qty > 0:
                        orders.append(Order(sym, ask, qty))
                        pos += qty
            for bid, vol in sorted(od.buy_orders.items(), reverse=True):
                if bid >= fair + take_edge:
                    qty = min(vol, pos + POSITION_LIMITS[sym])
                    if qty > 0:
                        orders.append(Order(sym, bid, -qty))
                        pos -= qty

            buy_capacity = POSITION_LIMITS[sym] - pos
            sell_capacity = pos + POSITION_LIMITS[sym]
            skew = -0.05 * pos
            bid_edge = max(1.0, 1.5 - skew)
            ask_edge = max(1.0, 1.5 + skew)

            mid = (best_bid + best_ask) / 2.0
            my_bid = int(math.floor(mid - bid_edge))
            my_ask = int(math.ceil(mid + ask_edge))
            my_bid = min(my_bid, best_ask - 1)
            my_ask = max(my_ask, best_bid + 1)
            if my_bid >= my_ask:
                my_ask = my_bid + 1
                
            mm_size = 15
            if buy_capacity > 0:
                orders.append(Order(sym, my_bid, min(buy_capacity, mm_size)))
            if sell_capacity > 0:
                orders.append(Order(sym, my_ask, -min(sell_capacity, mm_size)))

            if orders:
                ans[sym] = orders

        return ans

    def run(self, state: TradingState):
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            mem = {}

        result: Dict[str, List[Order]] = {}

        hydro_orders = self.trade_hydro(state)
        if hydro_orders:
            result[HYDRO] = hydro_orders

        # Run Velvet trading to get orders and the dynamic spot price (S)
        velvet_orders, S = self.trade_velvet(state)
        if velvet_orders:
            result[VELVET] = velvet_orders

        if S > 0:
            voucher_orders = self.trade_vouchers_simple(state, S)
            for sym, ords in voucher_orders.items():
                result[sym] = ords

        # Wrap it up, push the string to the traderData log, and flush the visualizer logger
        trader_data = json.dumps(mem)
        LOGGER.flush(state, result, 0, trader_data)
        
        return result, 0, trader_data