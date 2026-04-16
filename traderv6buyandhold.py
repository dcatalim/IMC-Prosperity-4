from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
from typing import List, Any, Dict
import math
import jsonpickle
import json

class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: Any) -> None:
        base_length = len(self.to_json([self.compress_state(state, ""), self.compress_orders(orders), conversions, "", ""]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [state.timestamp, trader_data, self.compress_listings(state.listings), self.compress_order_depths(state.order_depths),
                self.compress_trades(state.own_trades), self.compress_trades(state.market_trades), state.position, self.compress_observations(state.observations)]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        return {s: [o.buy_orders, o.sell_orders] for s, o in order_depths.items()}

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for t in arr:
                compressed.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_obs = {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff, o.importTariff, o.sugarPrice, o.sunlightIndex] 
                          for p, o in observations.conversionObservations.items()}
        return [observations.plainValueObservations, conversion_obs]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for o in arr:
                compressed.append([o.symbol, o.price, o.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(json.dumps(value)) <= max_length: return value
        return value[:max_length-3] + "..."

logger = Logger()

class Trader:
    def run(self, state: TradingState):
        result = {}
        conversions = 0
        trader_data = "" 

        for product in state.order_depths.keys():
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            LIMIT = 80

            if product == "ASH_COATED_OSMIUM":
                # Focus exclusively on capturing the massive 16-point spread.
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else 9999
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else 10001
                
                # Competitive pricing: Be the best price in the book
                my_bid = best_bid + 1
                my_ask = best_ask - 1
                
                # Ensure we don't accidentally cross our own spread
                if my_bid >= my_ask:
                    my_bid = best_bid
                    my_ask = best_ask

                # Always maintain max possible volume on both sides of the book
                if LIMIT - pos > 0:
                    orders.append(Order(product, int(my_bid), LIMIT - pos))
                if LIMIT + pos > 0:
                    orders.append(Order(product, int(my_ask), -(LIMIT + pos)))

            elif product == "INTARIAN_PEPPER_ROOT":
                # --- STRATEGY: SIMPLE BUY & HOLD ---
                # Immediate max long to ride the 0.001 drift.
                if pos < LIMIT:
                    # Buy at whatever the best ask is to fill the position instantly
                    best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                    if best_ask:
                        orders.append(Order(product, best_ask, LIMIT - pos))
                    else:
                        # Backup: just place a very high bid to ensure we get filled
                        orders.append(Order(product, 20000, LIMIT - pos))

            result[product] = orders

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data