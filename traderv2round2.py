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

    def bid(self):
        # -----------------------------------------------------------------------
        # MARKET ACCESS FEE BID (Round 2 only)
        #
        # This is a one-time blind auction. The top 50% of bids across all
        # participants get accepted and pay this amount. If accepted, we gain
        # access to 25% more order book volume, which means more trading
        # opportunities. If rejected, we pay nothing but get no extra access.
        #
        # 2000 XIRECs is a moderate bid — confident enough to likely beat the
        # median without overpaying. Adjust up if you want more certainty of
        # getting access, or down to be more conservative.
        # -----------------------------------------------------------------------
        return 2000

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

            # ==================================================================
            # ASH_COATED_OSMIUM
            # ==================================================================
            # CHANGE FROM ROUND 1:
            # fair_price was hardcoded at 10000 forever. 
            # we bot only traded when the market crossed that exact number,
            # missing huge stretches of the trading day when the market moved
            # away from 10000.
            #
            # Now we calculate a DYNAMIC fair price 
            # every tick using the mid-price 
            # This means the bot always knows where the market actually is and
            # trades relative to that 
            #
            #  also added INVENTORY SKEW to the passive quotes. If we're
            # holding a lot of Osmium, we nudge both our
            # bid and ask downward to encourage selling and discourage buying
            # more. If we're short, we nudge them upward. This keeps our
            # inventory balanced automatically without relying on a hard
            # rebalance order at a stale price.
            # ==================================================================

            if product == "ASH_COATED_OSMIUM":
                order_depth: OrderDepth = state.order_depths[product]
                orders: List[Order] = []
                position = state.position.get(product, 0)
                position_limit = 80
                posted_buy = 0
                posted_sell = 0

                # --- Step 1: Calculate dynamic fair price from the order book ---
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

                # If both sides of the book exist, mid-price is the average.
                # If only one side exists, use that. If the book is totally
                # empty (very rare), fall back to 10000.
                if best_bid is not None and best_ask is not None:
                    fair_price = (best_bid + best_ask) / 2
                elif best_bid is not None:
                    fair_price = best_bid
                elif best_ask is not None:
                    fair_price = best_ask
                else:
                    fair_price = 10000

                logger.print(f"OSM fair_price={fair_price}, position={position}")

                # --- Step 2: Take favorable liquidity ---
                # Buy anything being sold BELOW our fair price (they're cheap).
                # Sell anything being bought ABOVE our fair price (they're
                # overpaying).
                for ask in sorted(order_depth.sell_orders.keys()):
                    if ask < fair_price:
                        # How much can we still buy without hitting the limit?
                        trade_volume = min(
                            -order_depth.sell_orders[ask],
                            position_limit - position
                        )
                        if trade_volume > 0:
                            logger.print(f"TAKE BUY {trade_volume}x {ask}")
                            orders.append(Order(product, ask, trade_volume))
                            position += trade_volume
                            posted_buy += trade_volume

                for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid > fair_price:
                        # How much can we still sell without going below -limit?
                        trade_volume = min(
                            order_depth.buy_orders[bid],
                            position + position_limit
                        )
                        if trade_volume > 0:
                            logger.print(f"TAKE SELL {trade_volume}x {bid}")
                            orders.append(Order(product, bid, -trade_volume))
                            position -= trade_volume
                            posted_sell += trade_volume

                # --- Step 3: Post passive quotes with inventory skew ---
                # SPREAD: how many ticks away from fair price we quote.
                # We use 1 tick on each side to stay competitive.
                SPREAD = 1

                # SKEW: we adjust our quote prices based on how much inventory
                # we're holding. If position = +40 (we own a lot), skew = -0.4,
                # meaning we shift both quotes 0.4 ticks downward. This makes
                # our sell quote more attractive and our buy quote less
                # attractive, nudging us back toward zero automatically.
                # Max skew is capped at ±2 ticks to avoid quoting too far off.
                skew = max(-2, min(2, -position / 40))

                quote_buy_price = math.floor(fair_price - SPREAD + skew)
                quote_sell_price = math.ceil(fair_price + SPREAD + skew)

                # Improve over existing book quotes when possible (standard
                # market making: join or beat the best price), but never let
                # the bid and ask cross each other.
                if best_bid is not None:
                    quote_buy_price = min(quote_buy_price, best_bid + 1)
                if best_ask is not None:
                    quote_sell_price = max(quote_sell_price, best_ask - 1)

                # Safety check: quotes must never cross.
                if quote_buy_price >= quote_sell_price:
                    quote_buy_price = math.floor(fair_price - SPREAD)
                    quote_sell_price = math.ceil(fair_price + SPREAD)

                remaining_buy_capacity = position_limit - position - posted_buy
                remaining_sell_capacity = position_limit + position - posted_sell

                if remaining_buy_capacity > 0:
                    logger.print(f"PASSIVE BUY {remaining_buy_capacity}x {quote_buy_price}")
                    orders.append(Order(product, quote_buy_price, remaining_buy_capacity))

                if remaining_sell_capacity > 0:
                    logger.print(f"PASSIVE SELL {remaining_sell_capacity}x {quote_sell_price}")
                    orders.append(Order(product, quote_sell_price, -remaining_sell_capacity))

                result[product] = orders

            # ==================================================================
            # INTARIAN_PEPPER_ROOT
            # ==================================================================
            # STRATEGY (unchanged from your Round 1):
            # Hold a core position of TARGET_HOLD = 65 units as a base.
            # Use the remaining 15 units of capacity to actively
            # trade around fair value.
            #
            #  CHANGED:
            # - Fixed a bug in the sell logic: the old code used
            #   `max(-bid_amount, TARGET_HOLD - current_pos)` which could produce
            #   a POSITIVE number when current_pos < TARGET_HOLD, meaning it
            #   would accidentally try to BUY instead of SELL. Now we explicitly
            #   cap sell volume correctly so we never sell below TARGET_HOLD.
            # - Cleaned up operator precedence in the buy condition (added
            #   brackets so the `or` and `and` logic is unambiguous).
            # ==================================================================
            
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
                mid_price = (
                    (best_bid + best_ask) / 2
                    if (best_bid and best_ask)
                    else (best_bid or best_ask or 10000)
                )

                # Fair value: Pepper drifts slowly upward with time.
                # We remove the time drift to find the base, round it to the
                # nearest 1000 (to find the "true" base), then add the drift
                # back in. This gives us a smooth expected price at this moment.
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 1000) * 1000
                fair_value = base_price + (state.timestamp * 0.001)

                # Position management constants
                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                TARGET_HOLD = 65   # We always want to hold at least this many
                MM_SPREAD = 2
                MM_BASE_SIZE = 12

                # Desired passive quote prices (used as fallback below)
                my_bid = math.floor(fair_value) - 2
                my_ask = math.ceil(fair_value) + 2

                # --- Step 1: Take mispriced market orders ---
                # Buy anything below fair value, up to our full position limit.
                # Exception: at the very start (timestamp < 1000), also buy up
                # to TARGET_HOLD even at fair value, to build the core position.
                if len(order_depth.sell_orders) != 0:
                    for ask in sorted(order_depth.sell_orders.keys()):
                        # Buy condition: price is below fair value OR
                        # (it's early in the round AND we haven't built our
                        # core position yet)
                        if ask < fair_value or (
                            state.timestamp < 1000 and current_pos < TARGET_HOLD
                        ):
                            ask_amount = order_depth.sell_orders[ask]
                            # If we're buying at fair value early on, only buy
                            # enough to reach TARGET_HOLD. Otherwise, buy up to
                            # the full position limit.
                            if state.timestamp < 1000 and ask >= fair_value:
                                target_buy = TARGET_HOLD - current_pos
                            else:
                                target_buy = POSITION_LIMIT - current_pos
                            buy_vol = min(-ask_amount, target_buy)
                            if buy_vol > 0:
                                orders.append(Order(product, ask, buy_vol))
                                current_pos += buy_vol

                # Sell anything above fair value, but NEVER go below TARGET_HOLD.
                # BUG FIX: old code used max(-bid_amount, TARGET_HOLD - current_pos)
                # which could return a positive number, accidentally placing a BUY.
                # Now we correctly calculate how much we can sell while keeping
                # current_pos >= TARGET_HOLD, then cap it at the available volume.
                if len(order_depth.buy_orders) != 0:
                    for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                        if bid > fair_value:
                            bid_amount = order_depth.buy_orders[bid]
                            # Maximum we can sell: however many units above TARGET_HOLD we have
                            max_sellable = current_pos - TARGET_HOLD
                            if max_sellable <= 0:
                                # We're already at or below our hold target, don't sell
                                break
                            sell_vol = min(bid_amount, max_sellable)
                            if sell_vol > 0:
                                orders.append(Order(product, bid, -sell_vol))
                                current_pos -= sell_vol

                # --- Step 2: Post passive market-making quotes ---
                # These sit in the order book and earn us the spread passively.
                # We improve over the existing best quotes when we can.
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

                # Safety: quotes must not cross
                if passive_bid >= passive_ask:
                    passive_bid = fair_bid_cap
                    passive_ask = fair_ask_floor

                # Size the quotes with an inventory-aware skew toward TARGET_HOLD.
                # If we're below target, buy more aggressively; if above, sell more.
                inventory_gap = TARGET_HOLD - current_pos
                raw_buy_size = MM_BASE_SIZE + inventory_gap // 4
                raw_sell_size = MM_BASE_SIZE - inventory_gap // 4

                buy_volume = min(POSITION_LIMIT - current_pos, max(1, raw_buy_size))
                sell_volume = min(POSITION_LIMIT + current_pos, max(1, raw_sell_size))

                if buy_volume > 0:
                    orders.append(Order(product, passive_bid, buy_volume))

                if sell_volume > 0:
                    orders.append(Order(product, passive_ask, -sell_volume))

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        conversions = 0
        return result, conversions, traderData