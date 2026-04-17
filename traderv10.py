from tkinter import Place

from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string
import jsonpickle
import json


class Trader:

    def bid(self):
        return 15

    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""

        print("traderData: " + state.traderData)
        print("Observations: " + str(state.observations))

        result = {}
        trader_data = {}

        if state.traderData:
            try:
                decoded_data = jsonpickle.decode(state.traderData)
                if isinstance(decoded_data, dict):
                    trader_data = decoded_data
            except Exception:
                trader_data = {}

        for product in state.order_depths:
            if product == "ASH_COATED_OSMIUM":
                order_depth: OrderDepth = state.order_depths[product]
                orders: List[Order] = []
                position = state.position.get(product, 0)

                fair_value = 10000
                position_limit = 80

                # Simple midpoint is vulnerable to pennying attacks
                # Wall Mid uses the price where the most volume sits
                # best_bid_price = (
                #     max(
                #         order_depth.buy_orders.keys(),
                #         key=lambda price: order_depth.buy_orders[price],
                #     )
                #     if order_depth.buy_orders
                #     else None
                # )
                # best_ask_price = (
                #     max(
                #         order_depth.sell_orders.keys(),
                #         key=lambda price: abs(order_depth.sell_orders[price]),
                #     )
                #     if order_depth.sell_orders
                #     else None
                # )
                # wall_mid = (
                #     (best_bid_price + best_ask_price) / 2
                #     if best_bid_price is not None and best_ask_price is not None
                #     else fair_value
                # )

                # print("Best bid price: " + str(best_bid_price))
                # print("Best ask price: " + str(best_ask_price))
                # print("Wall mid price: " + str(wall_mid))

                print("Fair value : " + str(fair_value))
                print(
                    "Buy Order depth : "
                    + str(len(order_depth.buy_orders))
                    + ", Sell order depth : "
                    + str(len(order_depth.sell_orders))
                )

                # TAKE (Aggress on Mispriced Orders)
                # Walk the book and lift/hit any orders that are better than your fair value.
                for ask in sorted(order_depth.sell_orders.keys()):
                    ask_amount = order_depth.sell_orders[ask]
                    if int(ask) < fair_value:
                        trade_volume = min(-ask_amount, position_limit - position)

                        if trade_volume > 0:
                            print("BUY", str(-ask_amount) + "x", ask)
                            orders.append(Order(product, ask, trade_volume))
                            position += trade_volume

                for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                    bid_amount = order_depth.buy_orders[bid]
                    if int(bid) > fair_value :
                        trade_volume = min(bid_amount, position_limit - position)

                        if trade_volume > 0:
                            print("SELL", str(bid_amount) + "x", bid)
                            orders.append(Order(product, bid, -trade_volume))
                            position -= trade_volume
                
                # CLEAR (Flatten Inventory at Fair Value)
                # Place orders at fair value to reduce position toward zero. These are zero-EV trades that free up capacity for the next tick.
                if position > 0:
                    orders.append(Order(product, int(fair_value), -position))
                elif position < 0:
                    orders.append(Order(product, int(fair_value) + 1, -position))

                # MAKE (Post Passive Quotes)
                # Place resting limit orders around fair value to earn the spread.
                spread = 2
                limit = 20

                half = spread // 2

                bid_price = int(fair_value) - half
                ask_price = int(fair_value) + half

                bid_qty = limit - position
                ask_qty = limit + position

                if bid_qty > 0:
                    orders.append(Order(product, bid_price, bid_qty))
                if ask_qty > 0:
                    orders.append(Order(product, ask_price, -ask_qty))

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        conversions = 0
        return result, conversions, traderData
