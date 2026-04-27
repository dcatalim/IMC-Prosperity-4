from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
from typing import List, Any, Dict
import math
import jsonpickle
import json

# Standard Logger provided by user
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data) -> None:
        base_log = [state.timestamp, trader_data, self.logs]
        print(json.dumps(base_log))
        self.logs = ""

logger = Logger()

class Trader:
    def run(self, state: TradingState):
        result = {}
        conversions = 0
        
        if state.traderData:
            try: trader_data = jsonpickle.decode(state.traderData)
            except: trader_data = {"history": {}}
        else:
            trader_data = {"history": {}}

        for product, order_depth in state.order_depths.items():
            orders: List[Order] = []
            position = state.position.get(product, 0)
            POSITION_LIMIT = 80

            # 1. PRICE CALCULATION
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            if best_ask is None or best_bid is None: continue
            mid_price = (best_ask + best_bid) / 2

            if product not in trader_data["history"]: trader_data["history"][product] = []
            history = trader_data["history"][product]
            history.append(mid_price)
            if len(history) > 20: history.pop(0)
            dynamic_mean = sum(history) / len(history)

            # ---------------------------------------------------------------
            # ASH_COATED_OSMIUM (The Depth Sweeper)
            # ---------------------------------------------------------------
            if product == "ASH_COATED_OSMIUM":
                acceptable_price = dynamic_mean
                
                # Step 1: DEPTH SWEEPING (Take all liquidity below/above mean)
                # Instead of just the best price, we loop through the WHOLE book.
                for ask in sorted(order_depth.sell_orders.keys()):
                    if ask < acceptable_price:
                        # We take the ENTIRE volume at this price level
                        vol_at_price = order_depth.sell_orders[ask]
                        buy_vol = min(-vol_at_price, POSITION_LIMIT - position)
                        if buy_vol > 0:
                            orders.append(Order(product, ask, buy_vol))
                            position += buy_vol
                
                for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid > acceptable_price:
                        vol_at_price = order_depth.buy_orders[bid]
                        sell_vol = min(vol_at_price, POSITION_LIMIT + position)
                        if sell_vol > 0:
                            orders.append(Order(product, bid, -sell_vol))
                            position -= sell_vol

                # Step 2: MAX-VOLUME QUOTING
                # We place ONE massive order at the most competitive price possible
                # to ensure we are the first to get filled for the largest amount.
                if position < POSITION_LIMIT:
                    # Join the best bid if it's safe, otherwise stay 1 tick below mean
                    bid_price = min(best_bid + 1, math.floor(acceptable_price - 1))
                    orders.append(Order(product, int(bid_price), POSITION_LIMIT - position))

                if position > -POSITION_LIMIT:
                    # Join the best ask if it's safe, otherwise stay 1 tick above mean
                    ask_price = max(best_ask - 1, math.ceil(acceptable_price + 1))
                    orders.append(Order(product, int(ask_price), -(POSITION_LIMIT + position)))

            # ---------------------------------------------------------------
            # INTARIAN_PEPPER_ROOT (The Trend Rider)
            # ---------------------------------------------------------------
            elif product == "INTARIAN_PEPPER_ROOT":
                slope = 0
                if len(history) >= 5:
                    slope = (history[-1] - history[0]) / len(history)
                
                fair_value = mid_price + slope
                
                # Buy cheap
                for ask, vol in sorted(order_depth.sell_orders.items()):
                    if ask <= fair_value:
                        buy_vol = min(-vol, POSITION_LIMIT - position)
                        if buy_vol > 0:
                            orders.append(Order(product, ask, buy_vol))
                            position += buy_vol
                
                # Keep Long Bias
                if position < POSITION_LIMIT:
                    orders.append(Order(product, math.floor(fair_value) - 1, POSITION_LIMIT - position))

            result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData