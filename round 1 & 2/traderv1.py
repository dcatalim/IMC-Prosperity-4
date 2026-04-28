from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string
import pandas as pd
import numpy as np
import statistics as stats
import math
import jsonpickle


class Trader:
    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""

        print("traderData: " + state.traderData)
        print("Observations: " + str(state.observations))

        result = {}

        trader_data: dict = {}
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
                fair_price = 10000
                position = state.position.get(product, 0)
                position_limit = 80

                print("Acceptable price : " + str(fair_price))
                print(
                    "Buy Order depth : "
                    + str(len(order_depth.buy_orders))
                    + ", Sell order depth : "
                    + str(len(order_depth.sell_orders))
                )

                best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
                best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None

                if best_ask is not None and best_ask <= fair_price:
                    buy_volume = min(-order_depth.sell_orders[best_ask], position_limit - position)
                    if buy_volume > 0:
                        print("BUY", str(buy_volume) + "x", best_ask)
                        orders.append(Order(product, best_ask, buy_volume))

                if best_bid is not None and best_bid >= fair_price:
                    sell_volume = min(order_depth.buy_orders[best_bid], position_limit + position)
                    if sell_volume > 0:
                        print("SELL", str(sell_volume) + "x", best_bid)
                        orders.append(Order(product, best_bid, -sell_volume))

                remaining_buy_capacity = max(0, position_limit - (position + sum(order.quantity for order in orders)))
                remaining_sell_capacity = max(0, position_limit + (position + sum(order.quantity for order in orders)))

                if remaining_buy_capacity > 0:
                    quote_buy = min(fair_price - 1, best_bid + 1 if best_bid is not None else fair_price - 1)
                    print("QUOTE BUY", str(remaining_buy_capacity) + "x", quote_buy)
                    orders.append(Order(product, quote_buy, remaining_buy_capacity))

                if remaining_sell_capacity > 0:
                    quote_sell = max(fair_price + 1, best_ask - 1 if best_ask is not None else fair_price + 1)
                    print("QUOTE SELL", str(remaining_sell_capacity) + "x", quote_sell)
                    orders.append(Order(product, quote_sell, -remaining_sell_capacity))

            elif product == "ASH_COATED_OSMIUM":
                position = state.position.get(product, 0)
                position_limit = 60

                best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
                best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
                if best_bid is not None and best_ask is not None:
                    mid_price = (best_bid + best_ask) / 2
                elif best_bid is not None:
                    mid_price = float(best_bid)
                elif best_ask is not None:
                    mid_price = float(best_ask)
                else:
                    mid_price = 5000.0

                osmium_state = trader_data.get("ASH_COATED_OSMIUM", {})
                ema = osmium_state.get("ema", mid_price)
                alpha = 0.18
                ema = alpha * mid_price + (1 - alpha) * ema

                osmium_state["ema"] = ema
                trader_data["ASH_COATED_OSMIUM"] = osmium_state

                fair_price = int(round(ema))
                spread = max(2, int(round(abs(mid_price - ema) * 0.35)) + 1)
                buy_threshold = fair_price - spread
                sell_threshold = fair_price + spread

                print("Acceptable price : " + str(fair_price))
                print(
                    "Buy Order depth : "
                    + str(len(order_depth.buy_orders))
                    + ", Sell order depth : "
                    + str(len(order_depth.sell_orders))
                )

                if best_ask is not None:
                    ask_volume = -order_depth.sell_orders[best_ask]
                    if best_ask <= buy_threshold:
                        buy_volume = min(ask_volume, position_limit - position)
                        if buy_volume > 0:
                            print("BUY", str(buy_volume) + "x", best_ask)
                            orders.append(Order(product, best_ask, buy_volume))

                if best_bid is not None:
                    bid_volume = order_depth.buy_orders[best_bid]
                    if best_bid >= sell_threshold:
                        sell_volume = min(bid_volume, position_limit + position)
                        if sell_volume > 0:
                            print("SELL", str(sell_volume) + "x", best_bid)
                            orders.append(Order(product, best_bid, -sell_volume))

                remaining_buy_capacity = max(0, position_limit - (position + sum(order.quantity for order in orders)))
                remaining_sell_capacity = max(0, position_limit + (position + sum(order.quantity for order in orders)))

                quote_buy = min(fair_price - 1, best_bid + 1 if best_bid is not None else fair_price - 1)
                quote_sell = max(fair_price + 1, best_ask - 1 if best_ask is not None else fair_price + 1)

                if remaining_buy_capacity > 0 and position <= 20:
                    print("QUOTE BUY", str(remaining_buy_capacity) + "x", quote_buy)
                    orders.append(Order(product, quote_buy, remaining_buy_capacity))

                if remaining_sell_capacity > 0 and position >= -20:
                    print("QUOTE SELL", str(remaining_sell_capacity) + "x", quote_sell)
                    orders.append(Order(product, quote_sell, -remaining_sell_capacity))

            result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        conversions = 0
        return result, conversions, traderData
