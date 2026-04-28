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
        # Update OBSERVED_PNL_SINGLE_DAY after each backtester run.
        OBSERVED_PNL_SINGLE_DAY = 93540  

        DAYS_PER_ROUND     = 2  
        MM_FRACTION        = 0.15  
        EXTRA_QUOTE_GAIN   = 0.25  
        GAME_THEORY_FACTOR = 0.60  

        full_round_pnl = OBSERVED_PNL_SINGLE_DAY * DAYS_PER_ROUND
        mm_pnl         = full_round_pnl * MM_FRACTION
        extra_value    = mm_pnl * EXTRA_QUOTE_GAIN
        bid_amount     = int(extra_value * GAME_THEORY_FACTOR)

        return bid_amount

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

            # ----------------------------------------------------------
            # ASH_COATED_OSMIUM
            # ----------------------------------------------------------
            if product == "ASH_COATED_OSMIUM":
                position = state.position.get(product, 0)
                position_limit = 80

                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

                if best_bid is not None and best_ask is not None:
                    raw_mid = (best_bid + best_ask) / 2
                elif best_bid is not None:
                    raw_mid = best_bid
                elif best_ask is not None:
                    raw_mid = best_ask
                else:
                    raw_mid = 10000

                fair_price = 0.8 * 10000 + 0.2 * raw_mid

                # Dynamic Edge
                take_buy_edge = 2
                take_sell_edge = 2

                if 30 < position <= 50:
                    take_buy_edge = 3; take_sell_edge = 1
                elif 50 < position <= 70:
                    take_buy_edge = 4; take_sell_edge = 1
                elif position > 70:
                    take_buy_edge = 5; take_sell_edge = 1
                elif -50 <= position < -30:
                    take_buy_edge = 1; take_sell_edge = 3
                elif -70 <= position < -50:
                    take_buy_edge = 1; take_sell_edge = 4
                elif position < -70:
                    take_buy_edge = 1; take_sell_edge = 5

                # Taker Logic
                for ask in sorted(order_depth.sell_orders.keys()):
                    if ask <= fair_price - take_buy_edge:
                        trade_volume = min(-order_depth.sell_orders[ask], position_limit - position)
                        if trade_volume > 0:
                            orders.append(Order(product, ask, trade_volume))
                            position += trade_volume

                for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid >= fair_price + take_sell_edge:
                        trade_volume = min(order_depth.buy_orders[bid], position + position_limit)
                        if trade_volume > 0:
                            orders.append(Order(product, bid, -trade_volume))
                            position -= trade_volume

                # Passive Logic
                SPREAD = 2
                BASE_PASSIVE_SIZE = 14
                price_skew = max(-3, min(3, -position / 25))

                quote_buy_price = math.floor(fair_price - SPREAD + price_skew)
                quote_sell_price = math.ceil(fair_price + SPREAD + price_skew)

                if best_bid: quote_buy_price = min(quote_buy_price, best_bid + 1)
                if best_ask: quote_sell_price = max(quote_sell_price, best_ask - 1)

                if quote_buy_price >= quote_sell_price:
                    quote_buy_price = math.floor(fair_price - SPREAD)
                    quote_sell_price = math.ceil(fair_price + SPREAD)

                inventory_bias = position // 15
                buy_size = min(max(0, BASE_PASSIVE_SIZE - inventory_bias), position_limit - position)
                sell_size = min(max(0, BASE_PASSIVE_SIZE + inventory_bias), position_limit + position)

                if position >= 70: buy_size = 0
                if position <= -70: sell_size = 0

                if buy_size > 0: orders.append(Order(product, quote_buy_price, buy_size))
                if sell_size > 0: orders.append(Order(product, quote_sell_price, -sell_size))
                result[product] = orders

            # ----------------------------------------------------------
            # INTARIAN_PEPPER_ROOT
            # ----------------------------------------------------------
            if product == "INTARIAN_PEPPER_ROOT":
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                mid_price = ((best_bid + best_ask) / 2) if (best_bid and best_ask) else (best_bid or best_ask or 10000)

                # 1. Fair Value Calculation
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 1000) * 1000
                fair_value = base_price + (state.timestamp * 0.001)

                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                TARGET_HOLD = 65
                MM_SPREAD = 2
                MM_BASE_SIZE = 12

                # Crash Failsafe check
                CRASH_THRESHOLD = 400
                book_is_live = mid_price > 0
                prev_base = trader_data.get("pepper_base", None)
                
                crash_detected = (
                    book_is_live
                    and prev_base is not None
                    and base_price < prev_base - CRASH_THRESHOLD
                    and current_pos > 0
                )

                if crash_detected:
                    logger.print(f"PEPPER CRASH: {prev_base}->{base_price}, closing {current_pos}")
                    # Hit all bids to dump
                    for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                        if current_pos <= 0: break
                        vol = min(order_depth.buy_orders[bid_price], current_pos)
                        orders.append(Order(product, bid_price, -vol))
                        current_pos -= vol
                    # Emergency limit sell if book is thin
                    if current_pos > 0:
                        orders.append(Order(product, math.floor(fair_value) - 10, -current_pos))
                else:
                    # 2. Statistical Arbitrage 
                    if order_depth.sell_orders:
                        for ask in sorted(order_depth.sell_orders.keys()):
                            if ask < fair_value or (state.timestamp < 1000 and current_pos < TARGET_HOLD):
                                target_buy = (TARGET_HOLD - current_pos) if (state.timestamp < 1000 and ask >= fair_value) else (POSITION_LIMIT - current_pos)
                                buy_vol = min(-order_depth.sell_orders[ask], target_buy)
                                if buy_vol > 0:
                                    orders.append(Order(product, ask, buy_vol))
                                    current_pos += buy_vol

                    if order_depth.buy_orders:
                        for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                            if bid > fair_value:
                                sell_vol = max(-order_depth.buy_orders[bid], TARGET_HOLD - current_pos)
                                if sell_vol < 0:
                                    orders.append(Order(product, bid, sell_vol))
                                    current_pos += sell_vol

                    # 3. Market Making 
                

                    fb_cap = math.floor(fair_value) - MM_SPREAD
                    fa_floor = math.ceil(fair_value) + MM_SPREAD

                    passive_bid = min(fb_cap, best_bid + 1) if best_bid else fb_cap
                    passive_ask = max(fa_floor, best_ask - 1) if best_ask else fa_floor

                    if passive_bid >= passive_ask:
                        passive_bid, passive_ask = fb_cap, fa_floor

                    inventory_gap = TARGET_HOLD - current_pos
                    r_buy = MM_BASE_SIZE + inventory_gap // 4
                    r_sell = MM_BASE_SIZE - inventory_gap // 4

                    b_vol = min(POSITION_LIMIT - current_pos, max(1, r_buy))
                    s_vol = min(POSITION_LIMIT + current_pos, max(1, r_sell))

                    if b_vol > 0: orders.append(Order(product, passive_bid, b_vol))
                    if s_vol > 0: orders.append(Order(product, passive_ask, -s_vol))

                if book_is_live:
                    trader_data["pepper_base"] = base_price
                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData