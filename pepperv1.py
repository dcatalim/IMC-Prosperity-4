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
                mid_price = ((best_bid + best_ask) / 2 if (best_bid and best_ask) else (best_bid or best_ask or 100000))

                # Fair value formula - accurate to within std of 2.28, do not change
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 100) * 100
                fair_value = base_price + (state.timestamp * 0.001)

                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80

                # 70 units held as core drift position → 7,000 XIRECs baseline
                # 10 units above 70 actively market make to earn extra spread profit
                DRIFT_TARGET = 70
                TRADING_BAND_TOP = 80

                # --- REGIME 1: TAKE ORDERS ---

                if len(order_depth.sell_orders) != 0:
                    for ask in sorted(order_depth.sell_orders.keys()):

                        if current_pos < DRIFT_TARGET:
                            # DRIFT REGIME: buy gradually as good offers appear.
                            # We accept anything at or 1 above fair value — good enough
                            # to be worth holding for the drift, but we are not
                            # desperately chasing. Offers above fair+1 we simply ignore
                            # and wait for a better price to come along passively.
                            buy_threshold = fair_value +1
                        else:
                            # TRADING BAND: only buy genuine bargains at or below fair
                            # so we have room to sell again and complete round trips
                            buy_threshold = fair_value

                        if ask <= buy_threshold:
                            buy_vol = min(-order_depth.sell_orders[ask], POSITION_LIMIT - current_pos)
                            if buy_vol > 0:
                                orders.append(Order(product, ask, buy_vol))
                                current_pos += buy_vol

                if len(order_depth.buy_orders) != 0:
                    for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                        # Only take-sell above drift target AND at a serious premium.
                        # Never sell below drift target — those are our core drift units.
                        if current_pos > DRIFT_TARGET and bid > fair_value + 3:
                            sell_vol = max(
                                -order_depth.buy_orders[bid],
                                DRIFT_TARGET - current_pos
                            )
                            if sell_vol < 0:
                                orders.append(Order(product, bid, sell_vol))
                                current_pos += sell_vol

                # --- REGIME 2: PASSIVE QUOTING ---

                fair_bid_cap = math.floor(fair_value) - 1
                passive_bid = fair_bid_cap
                if best_bid is not None:
                    passive_bid = min(fair_bid_cap, best_bid + 1)

                if current_pos <= DRIFT_TARGET:
                    # DRIFT REGIME: passive ask is nearly impossible to fill.
                    # Protect the core 70 units at all costs.
                    passive_ask = math.ceil(fair_value) + 4
                    if best_ask is not None:
                        passive_ask = max(math.ceil(fair_value) + 4, best_ask - 1)
                else:
                    # TRADING BAND: competitive ask to earn the spread on extra units
                    passive_ask = math.ceil(fair_value) + 2
                    if best_ask is not None:
                        passive_ask = max(math.ceil(fair_value) + 2, best_ask - 1)

                if passive_bid >= passive_ask:
                    passive_bid = math.floor(fair_value) - 1
                    passive_ask = math.ceil(fair_value) + 2

                # Passive sizes
                if current_pos < DRIFT_TARGET:
                    # Still building toward drift target — buy normally, barely sell
                    buy_volume = min(POSITION_LIMIT - current_pos, 10)
                    sell_volume = 1
                elif current_pos <= TRADING_BAND_TOP:
                    # In trading band — cycle the extra units above 70
                    units_above_drift = current_pos - DRIFT_TARGET
                    buy_volume = min(POSITION_LIMIT - current_pos, max(1, 10 - units_above_drift))
                    sell_volume = min(current_pos - DRIFT_TARGET, max(1, units_above_drift))
                else:
                    buy_volume = 0
                    sell_volume = min(current_pos - DRIFT_TARGET, 10)

                if buy_volume > 0:
                    orders.append(Order(product, passive_bid, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, passive_ask, -sell_volume))

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        conversions = 0
        return result, conversions, traderData
