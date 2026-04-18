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

    def bid(self):
        return 0

    def run(self, state: TradingState):
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

            if product == "ASH_COATED_OSMIUM":
                order_depth = state.order_depths[product]
                position = state.position.get(product, 0)
                position_limit = 80

                best_bid = (
                    max(order_depth.buy_orders.keys())
                    if order_depth.buy_orders
                    else None
                )
                best_ask = (
                    min(order_depth.sell_orders.keys())
                    if order_depth.sell_orders
                    else None
                )

                if best_bid is not None and best_ask is not None:
                    raw_mid = (best_bid + best_ask) / 2
                elif best_bid is not None:
                    raw_mid = best_bid
                elif best_ask is not None:
                    raw_mid = best_ask
                else:
                    raw_mid = 10001

                fair_price = 0.85 * 10001 + 0.15 * raw_mid

                logger.print(f"OSM fair_price={fair_price}, position={position}")

                take_buy_edge = 2
                take_sell_edge = 2

                #added dynamic edge adjustment based on position to encourage more aggressive trading when further from center
                #before it was only when position was abocve 40 or below -40, now it scales up more gradually and starts at 30 and -30 to encourage more trading even when not extremely far from center

                if position > 30 and position <= 50:
                    take_buy_edge = 3
                    take_sell_edge = 1
                elif position > 50 and position <= 70:
                    take_buy_edge = 4
                    take_sell_edge = 1
                elif position > 70:
                    take_buy_edge = 5
                    take_sell_edge = 1
                elif position < -30 and position >= -50:
                    take_buy_edge = 1
                    take_sell_edge = 3
                elif position < -50 and position >= -70:
                    take_buy_edge = 1
                    take_sell_edge = 4
                elif position < -70:
                    take_buy_edge = 1
                    take_sell_edge = 5

                for ask in sorted(order_depth.sell_orders.keys()):
                    if ask <= fair_price - take_buy_edge:
                        trade_volume = min(
                            -order_depth.sell_orders[ask],
                            position_limit - position,
                        )
                        if trade_volume > 0:
                            logger.print(f"TAKE BUY {trade_volume}x {ask}")
                            orders.append(Order(product, ask, trade_volume))
                            position += trade_volume

                for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid >= fair_price + take_sell_edge:
                        trade_volume = min(
                            order_depth.buy_orders[bid],
                            position + position_limit,
                        )
                        if trade_volume > 0:
                            logger.print(f"TAKE SELL {trade_volume}x {bid}")
                            orders.append(Order(product, bid, -trade_volume))
                            position -= trade_volume

                SPREAD = 2
                BASE_PASSIVE_SIZE = 14
                price_skew = max(-3, min(3, -position / 25))

                quote_buy_price = math.floor(fair_price - SPREAD + price_skew)
                quote_sell_price = math.ceil(fair_price + SPREAD + price_skew)

                if best_bid is not None:
                    quote_buy_price = min(quote_buy_price, best_bid + 1)
                if best_ask is not None:
                    quote_sell_price = max(quote_sell_price, best_ask - 1)

                if quote_buy_price >= quote_sell_price:
                    quote_buy_price = math.floor(fair_price - SPREAD)
                    quote_sell_price = math.ceil(fair_price + SPREAD)

                inventory_bias = position // 15
                buy_size = max(0, BASE_PASSIVE_SIZE - inventory_bias)
                sell_size = max(0, BASE_PASSIVE_SIZE + inventory_bias)

                if position >= 55:
                    buy_size = 0
                elif position <= -55:
                    sell_size = 0

                buy_size = min(buy_size, position_limit - position)
                sell_size = min(sell_size, position_limit + position)

                if buy_size > 0:
                    logger.print(f"PASSIVE BUY {buy_size}x {quote_buy_price}")
                    orders.append(Order(product, quote_buy_price, buy_size))

                if sell_size > 0:
                    logger.print(f"PASSIVE SELL {sell_size}x {quote_sell_price}")
                    orders.append(Order(product, quote_sell_price, -sell_size))

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        conversions = 0
        return result, conversions, traderData
