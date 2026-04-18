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

# https://prosperity.equirag.com/

class Trader:
    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""

        print("traderData: " + state.traderData)
        print("Observations: " + str(state.observations))

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

                # 1. Calculate Expected Fair Value
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 100) * 100
                fair_value = base_price + (state.timestamp * 0.001)

                # Position management
                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                TARGET_HOLD = 65
                MM_SPREAD = 2
                MM_BASE_SIZE = 12

                # Desired Quotes
                my_bid = math.floor(fair_value) - 2
                my_ask = math.ceil(fair_value) + 2

                # 2. Statistical Arbitrage: Clear market orders that are mispriced
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
                    for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                        if bid > fair_value:
                            bid_amount = order_depth.buy_orders[bid]
                            sell_vol = max(-bid_amount, TARGET_HOLD - current_pos)
                            if sell_vol < 0:
                                orders.append(Order(product, bid, sell_vol))
                                current_pos += sell_vol

                # 3. Market Making: always post passive two-sided quotes with edge.
                # Improve over existing book when possible, but never cross fair value.
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

                # Keep a valid non-crossing quote pair in very tight books.
                if passive_bid >= passive_ask:
                    passive_bid = fair_bid_cap
                    passive_ask = fair_ask_floor

                inventory_gap = TARGET_HOLD - current_pos
                raw_buy_size = MM_BASE_SIZE + inventory_gap // 4
                raw_sell_size = MM_BASE_SIZE - inventory_gap // 4

                # Keep two-sided quotes when possible, with inventory-aware skew.
                buy_volume = min(POSITION_LIMIT - current_pos, max(1, raw_buy_size))
                sell_volume = min(POSITION_LIMIT + current_pos, max(1, raw_sell_size))

                if buy_volume > 0:
                    orders.append(Order(product, passive_bid, buy_volume))

                if sell_volume > 0:
                    orders.append(Order(product, passive_ask, -sell_volume))

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        conversions = 0
        return result, conversions, traderData
