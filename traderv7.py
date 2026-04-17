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

# =============================================================================
# STRATEGY OVERVIEW
# =============================================================================
#
# ASH_COATED_OSMIUM — Market Making
# ----------------------------------
# Posts simultaneous bid and ask orders on both sides of the order book,
# profiting from the spread between the two prices without taking any
# directional view on price movement.
#
# Quotes are placed one tick inside the market's best bid and ask to gain
# queue priority and maximise fill rate. Quoting is gated behind a minimum
# spread threshold of 2 ticks to ensure profitability after tightening.
# A safety check prevents posting a crossed spread in edge cases.
#
# INTARIAN_PEPPER_ROOT — Buy & Hold
# -----------------------------------
# Exploits a persistent upward drift in the pepper price by immediately
# acquiring the maximum allowed long position and holding it for the
# duration of the session.
#
# =============================================================================

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
                # STRATEGY: SPREAD-GATED MARKET MAKING WITH INVENTORY SKEW

                # Step 1: Find the best prices currently in the market.
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

                # Step 2: Only proceed if there are orders on BOTH sides of the book.
                if best_bid is not None and best_ask is not None:

                    spread = best_ask - best_bid

                    # Step 3: Only quote if the spread is wide enough to be profitable.
                    MIN_SPREAD = 2

                    if spread >= MIN_SPREAD:

                        # Step 4: Inventory skew — how "full" is our position, from -1 to +1.
                        skew = pos / LIMIT

                        # Step 5: Adjust quotes based on skew.
                        # Being very long shifts both prices down: sell more eagerly, buy less eagerly.
                        bid_adjustment = -round(skew)
                        ask_adjustment = -round(skew)

                        my_bid = best_bid + bid_adjustment
                        my_ask = best_ask + ask_adjustment

                        # Step 6: Safety check — never let bid >= ask.
                        if my_bid >= my_ask:
                            my_bid = best_bid
                            my_ask = best_ask

                        # Step 7: Post orders for remaining capacity on each side.
                        buy_capacity = LIMIT - pos
                        sell_capacity = LIMIT + pos

                        if buy_capacity > 0:
                            orders.append(Order(product, int(my_bid), buy_capacity))
                        if sell_capacity > 0:
                            orders.append(Order(product, int(my_ask), -sell_capacity))

            elif product == "INTARIAN_PEPPER_ROOT":
                # --- STRATEGY: SIMPLE BUY & HOLD ---
                if pos < LIMIT:
                    best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                    if best_ask:
                        orders.append(Order(product, best_ask, LIMIT - pos))
                    else:
                        orders.append(Order(product, 20000, LIMIT - pos))

            result[product] = orders

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data