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

class Trader:

    def bid(self):
        return 0

    def run(self, state: TradingState):
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

                fair_price = 0.85 * 10000 + 0.15 * raw_mid

                print(f"OSM fair_price={fair_price}, position={position}")

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
                            print(f"TAKE BUY {trade_volume}x {ask}")
                            orders.append(Order(product, ask, trade_volume))
                            position += trade_volume

                for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid >= fair_price + take_sell_edge:
                        trade_volume = min(
                            order_depth.buy_orders[bid],
                            position + position_limit,
                        )
                        if trade_volume > 0:
                            print(f"TAKE SELL {trade_volume}x {bid}")
                            orders.append(Order(product, bid, -trade_volume))
                            position -= trade_volume

                SPREAD = 1
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
                    print(f"PASSIVE BUY {buy_size}x {quote_buy_price}")
                    orders.append(Order(product, quote_buy_price, buy_size))

                if sell_size > 0:
                    print(f"PASSIVE SELL {sell_size}x {quote_sell_price}")
                    orders.append(Order(product, quote_sell_price, -sell_size))

                result[product] = orders
            
            elif product == "INTARIAN_PEPPER_ROOT":
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
                base_price = round(implied_base / 1000) * 1000
                fair_value = base_price + (state.timestamp * 0.001)

                # Position management
                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                TARGET_HOLD = 70
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
