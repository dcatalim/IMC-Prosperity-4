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
        # Everything else calculates automatically from that one number.
        OBSERVED_PNL_SINGLE_DAY = 93540  # your ~9354 over 100k ts x 10

        DAYS_PER_ROUND     = 2     # round 2 has 2 trading days
        MM_FRACTION        = 0.15  # ~15% of PnL comes from market making
                                   # (the part that scales with extra quotes)
        EXTRA_QUOTE_GAIN   = 0.25  # 25% more quotes -> 25% more MM profit
        GAME_THEORY_FACTOR = 0.60  # bid 60% of true value to win top-50% cheaply

        full_round_pnl = OBSERVED_PNL_SINGLE_DAY * DAYS_PER_ROUND
        mm_pnl         = full_round_pnl * MM_FRACTION
        extra_value    = mm_pnl * EXTRA_QUOTE_GAIN
        bid_amount     = int(extra_value * GAME_THEORY_FACTOR)

        return bid_amount

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
                    raw_mid = 10000

                fair_price = 0.8 * 10000 + 0.2 * raw_mid

                logger.print(f"OSM fair_price={fair_price}, position={position}")

                take_buy_edge = 2
                take_sell_edge = 2

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

                if position >= 70:
                    buy_size = 0
                elif position <= -70:
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

            if product == "INTARIAN_PEPPER_ROOT":
                best_bid = (
                    max(order_depth.buy_orders.keys())
                    if len(order_depth.buy_orders) > 0
                    else None
                )
                best_ask = (
                    min(order_depth.sell_orders.keys())
                    if len(order_depth.sell_orders) > 0
                    else None
                )

                # Use 0 as sentinel for "book is empty this tick".
                # We detect this below and skip crash checks + base updates
                # so an empty book is never mistaken for a price crash.
                mid_price = (
                    (best_bid + best_ask) / 2
                    if (best_bid and best_ask)
                    else (best_bid or best_ask or 0)
                )

                # --- Fair value ---
                # Price follows: fair_value = base_price + timestamp * 0.001
                # base_price is the day's starting level (~11000, ~12000, etc.)
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 1000) * 1000
                fair_value = base_price + (state.timestamp * 0.001)

                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                TARGET_HOLD = 65
                MM_SPREAD = 2
                MM_BASE_SIZE = 12

                # -------------------------------------------------------
                # CRASH / DAY-TRANSITION FAILSAFE
                #
                # Logic:
                #   Each tick we save base_price to trader_data["pepper_base"].
                #   Next tick we load it as prev_base and compare.
                #
                #   Normal tick-to-tick noise: the price jiggles by ±7 at most,
                #   which after the round(x/1000)*1000 step stays on the same
                #   1000-multiple — so prev_base and base_price are equal.
                #
                #   Crash or day flip: base_price drops by 500-2000 suddenly.
                #   We catch this with CRASH_THRESHOLD = 400.
                #
                #   When triggered AND we are long, we:
                #     1. Hit every available bid in the book right now.
                #     2. Post an aggressive limit sell 10 below the new (lower)
                #        fair_value as a backup, to catch any remaining units
                #        on the very next tick if the book was thin.
                #
                #   We skip the check entirely when book_is_live is False
                #   (mid_price == 0), because a momentarily empty book is not
                #   the same as a price crash and would give a false base_price.
                # -------------------------------------------------------
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
                    logger.print(
                        f"PEPPER CRASH DETECTED: base dropped "
                        f"{prev_base} -> {base_price}. "
                        f"Closing position of {current_pos}."
                    )

                    # Step 1: take every available bid immediately
                    for bid_price in sorted(
                        order_depth.buy_orders.keys(), reverse=True
                    ):
                        if current_pos <= 0:
                            break
                        vol = min(order_depth.buy_orders[bid_price], current_pos)
                        if vol > 0:
                            orders.append(Order(product, bid_price, -vol))
                            current_pos -= vol

                    # Step 2: post emergency limit sell for any units the book
                    # couldn't absorb (will fill on next tick if price is right)
                    if current_pos > 0:
                        emergency_price = math.floor(fair_value) - 10
                        logger.print(
                            f"PEPPER EMERGENCY SELL {current_pos}x {emergency_price}"
                        )
                        orders.append(Order(product, emergency_price, -current_pos))

                else:
                  
                    my_bid = math.floor(fair_value) - 1
                    my_ask = math.ceil(fair_value) + 1

                    if len(order_depth.sell_orders) != 0:
                        for ask in sorted(order_depth.sell_orders.keys()):
                            if (
                                ask < fair_value
                                or state.timestamp < 1000
                                and current_pos < TARGET_HOLD
                            ):
                                ask_amount = order_depth.sell_orders[ask]
                                target_buy = (
                                    TARGET_HOLD - current_pos
                                    if state.timestamp < 1000 and ask >= fair_value
                                    else POSITION_LIMIT - current_pos
                                )
                                buy_vol = min(-ask_amount, target_buy)
                                if buy_vol > 0:
                                    orders.append(Order(product, ask, buy_vol))
                                    current_pos += buy_vol

                    if len(order_depth.buy_orders) != 0:
                        for bid in sorted(
                            order_depth.buy_orders.keys(), reverse=True
                        ):
                            if bid > fair_value:
                                bid_amount = order_depth.buy_orders[bid]
                                sell_vol = max(-bid_amount, TARGET_HOLD - current_pos)
                                if sell_vol < 0:
                                    orders.append(Order(product, bid, sell_vol))
                                    current_pos += sell_vol

                    passive_bid = my_bid
                    passive_ask = my_ask

                    fair_bid_cap = math.floor(fair_value) - MM_SPREAD
                    fair_ask_floor = math.ceil(fair_value) + MM_SPREAD

                    if best_bid is not None:
                        passive_bid = min(fair_bid_cap, best_bid + 1)
                    else:
                        passive_bid = fair_bid_cap

                    if best_ask is not None:
                        passive_ask = max(fair_ask_floor, best_ask - 1)
                    else:
                        passive_ask = fair_ask_floor

                    if passive_bid >= passive_ask:
                        passive_bid = fair_bid_cap
                        passive_ask = fair_ask_floor

                    inventory_gap = TARGET_HOLD - current_pos
                    raw_buy_size = MM_BASE_SIZE + inventory_gap // 4
                    raw_sell_size = MM_BASE_SIZE - inventory_gap // 4

                    buy_volume = min(POSITION_LIMIT - current_pos, max(1, raw_buy_size))
                    sell_volume = min(POSITION_LIMIT + current_pos, max(1, raw_sell_size))

                    if buy_volume > 0:
                        orders.append(Order(product, passive_bid, buy_volume))

                    if sell_volume > 0:
                        orders.append(Order(product, passive_ask, -sell_volume))

                # Only update the saved base when the book was actually live.
                # If the book was empty we skip this, so the old base stays
                # saved and correctly represents the last known good price.
                if book_is_live:
                    trader_data["pepper_base"] = base_price

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        conversions = 0
        return result, conversions, traderData