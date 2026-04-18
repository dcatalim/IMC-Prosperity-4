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
import math
import jsonpickle

class Trader:
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

                # Exact Fair Value calculation (base is a multiple of 100)
                implied_base = mid_price - state.timestamp * 0.001
                base_price = round(implied_base / 100) * 100
                fair_value = base_price + (state.timestamp * 0.001)

                current_pos = state.position.get(product, 0)
                POSITION_LIMIT = 80
                
                # To profit from mispricings, we want a target slightly below max so we CAN buy undervalued asks
                # But mostly we want to stay very long.
                TARGET_HOLD = 75

                # 1. Clear mispriced orders
                if len(order_depth.sell_orders) != 0:
                    for ask in sorted(order_depth.sell_orders.keys()):
                        # If ask is cheap, or we're bootstrapping early on
                        if ask < fair_value or (state.timestamp < 1000 and current_pos < TARGET_HOLD):
                            ask_amount = order_depth.sell_orders[ask]
                            target_buy = TARGET_HOLD - current_pos if state.timestamp < 1000 and ask >= fair_value else POSITION_LIMIT - current_pos
                            buy_vol = min(-ask_amount, target_buy)
                            if buy_vol > 0:
                                orders.append(Order(product, ask, buy_vol))
                                current_pos += buy_vol

                if len(order_depth.buy_orders) != 0:
                    for bid in sorted(order_depth.buy_orders.keys(), reverse=True):
                        # Sell if we can rip them off
                        if bid > fair_value + 1.5:  # Require higher premium to sell because of drift
                            bid_amount = order_depth.buy_orders[bid]
                            sell_vol = max(-bid_amount, 0 - current_pos) # can sell down to 0 if it's insanely mispriced
                            if sell_vol < 0:
                                orders.append(Order(product, bid, sell_vol))
                                current_pos += sell_vol

                # 2. Market Making
                fair_bid_cap = math.floor(fair_value) - 1
                fair_ask_floor = math.ceil(fair_value) + 2 # Keep Asks high, we don't want to sell easily

                passive_bid = fair_bid_cap
                passive_ask = fair_ask_floor

                if best_bid is not None:
                    passive_bid = min(fair_bid_cap, best_bid + 1)
                if best_ask is not None:
                    passive_ask = max(fair_ask_floor, best_ask - 1)

                if passive_bid >= passive_ask:
                    passive_bid = fair_bid_cap
                    passive_ask = fair_ask_floor

                inventory_gap = TARGET_HOLD - current_pos
                buy_volume = min(POSITION_LIMIT - current_pos, max(1, 10 + inventory_gap))
                sell_volume = min(POSITION_LIMIT + current_pos, max(1, 5 - inventory_gap))

                if buy_volume > 0:
                    orders.append(Order(product, passive_bid, buy_volume))
                if sell_volume > 0:
                    orders.append(Order(product, passive_ask, -sell_volume))

                result[product] = orders

        traderData = jsonpickle.encode(trader_data)
        return result, conversions, traderData
