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
from typing import List, Any, Dict
import string
import pandas as pd
import numpy as np
import statistics as stats
import math
import jsonpickle
import json

# This logger allows to visualize the trading process
# https://jmerle.github.io/imc-prosperity-3-visualizer/
# https://prosperity.equirag.com/

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
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
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
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(
        self, order_depths: dict[Symbol, OrderDepth]
    ) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

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

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()


class Trader:
    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""

        logger.print("traderData: " + state.traderData)
        logger.print("Observations: " + str(state.observations))

        result = {}
        conversions = 0
        trader_data = {}

        if state.traderData:
            try:
                decoded_data = jsonpickle.decode(state.traderData)
                if isinstance(decoded_data, dict):
                    trader_data = decoded_data
            except Exception:
                trader_data = {}

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            
            if product == "INTARIAN_PEPPER_ROOT":
                best_bid = max(order_depth.buy_orders.keys()) if len(order_depth.buy_orders) > 0 else None
                best_ask = min(order_depth.sell_orders.keys()) if len(order_depth.sell_orders) > 0 else None
                mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else (best_bid or best_ask or 10000)

                # 1. Calculate Expected Fair Value
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 1000) * 1000
                fair_value = base_price + (state.timestamp * 0.001)
                
                # Position management
                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                TARGET_HOLD = 40

                # Desired Quotes
                my_bid = math.floor(fair_value) - 2
                my_ask = math.ceil(fair_value) + 2
                
                # 2. Statistical Arbitrage: Clear market orders that are mispriced
                if len(order_depth.sell_orders) != 0:
                    for ask in sorted(order_depth.sell_orders.keys()):
                        if ask < fair_value or state.timestamp < 1000 and current_pos < TARGET_HOLD:
                            ask_amount = order_depth.sell_orders[ask]
                            target_buy = TARGET_HOLD - current_pos if state.timestamp < 1000 and ask >= fair_value else POSITION_LIMIT - current_pos
                            buy_vol = min(-ask_amount, target_buy)
                            if buy_vol > 0:
                                orders.append(Order(product, ask, buy_vol))
                                current_pos += buy_vol
                
                if len(order_depth.buy_orders) != 0:
                    for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                        if bid > fair_value:
                            bid_amount = order_depth.buy_orders[bid]
                            sell_vol = max(-bid_amount, TARGET_HOLD - current_pos)
                            if sell_vol < 0:
                                orders.append(Order(product, bid, sell_vol))
                                current_pos += sell_vol

                # 3. Market Making: Post resting limit orders around the fair value
                buy_volume = POSITION_LIMIT - current_pos
                if buy_volume > 0:
                    orders.append(Order(product, my_bid, buy_volume))
                    
                sell_volume = TARGET_HOLD - current_pos
                if sell_volume < 0:
                    orders.append(Order(product, my_ask, sell_volume))

                result[product] = orders


        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        conversions = 0
        return result, conversions, traderData
