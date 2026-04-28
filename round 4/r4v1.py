import json
import math
from typing import Dict, List, Tuple
from datamodel import OrderDepth, TradingState, Order

# Symbols
HYDRO = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
VOUCHERS = {f"VEV_{s}": s for s in [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]}
LIMITS = {HYDRO: 200, VELVET: 200, **{sym: 300 for sym in VOUCHERS}}

class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}
        
        # 1. Get underlying Velvetfruit Mid
        velvet_mid = 0
        if VELVET in state.order_depths:
            v_depth = state.order_depths[VELVET]
            if v_depth.buy_orders and v_depth.sell_orders:
                velvet_mid = (max(v_depth.buy_orders.keys()) + min(v_depth.sell_orders.keys())) / 2.0

        # 2. Process Vouchers (Arbitrage + Market Taking)
        total_delta = 0
        if velvet_mid > 0:
            for sym, strike in VOUCHERS.items():
                if sym not in state.order_depths: continue
                depth = state.order_depths[sym]
                pos = state.position.get(sym, 0)
                
                # Fair Value = Intrinsic + Estimated Time Value (Bell curve)
                intrinsic = max(0, velvet_mid - strike)
                time_val = 41.0 * math.exp(-(abs(velvet_mid - strike)**2) / 45000)
                fair = intrinsic + time_val
                
                v_orders = []
                best_ask = min(depth.sell_orders.keys())
                best_bid = max(depth.buy_orders.keys())

                # MARKET TAKE: If someone sells below fair, BUY. If they buy above, SELL.
                if best_ask < fair - 0.5:
                    vol = min(LIMITS[sym] - pos, depth.sell_orders[best_ask])
                    if vol > 0: v_orders.append(Order(sym, int(best_ask), int(vol)))
                
                if best_bid > fair + 0.5:
                    vol = min(LIMITS[sym] + pos, depth.buy_orders[best_bid])
                    if vol > 0: v_orders.append(Order(sym, int(best_bid), int(-vol)))

                if v_orders:
                    result[sym] = v_orders
                
                # Delta Calculation (Standard Option Delta)
                delta = 1.0 / (1.0 + math.exp(-(velvet_mid - strike) / 60.0))
                total_delta += pos * delta

        # 3. Delta Hedge with Velvetfruit
        if VELVET in state.order_depths:
            v_depth = state.order_depths[VELVET]
            v_pos = state.position.get(VELVET, 0)
            target_v_pos = -int(total_delta) # Hedge the voucher delta
            target_v_pos = max(-LIMITS[VELVET], min(LIMITS[VELVET], target_v_pos))
            
            diff = target_v_pos - v_pos
            if abs(diff) > 0:
                best_ask = min(v_depth.sell_orders.keys())
                best_bid = max(v_depth.buy_orders.keys())
                # Take the spread to ensure the hedge is locked in
                price = int(best_ask if diff > 0 else best_bid)
                result[VELVET] = [Order(VELVET, price, int(diff))]

        # 4. Hydrogel Pack (Mean Reversion against Mark 38)
        if HYDRO in state.order_depths:
            h_depth = state.order_depths[HYDRO]
            h_pos = state.position.get(HYDRO, 0)
            
            # Use fixed mean but allow Mark 14 to "push" it
            h_fair = 9991.0
            for t in state.market_trades.get(HYDRO, []):
                if t.buyer == "Mark 14": h_fair += 5
                if t.seller == "Mark 14": h_fair -= 5
            
            h_orders = []
            best_ask = min(h_depth.sell_orders.keys())
            best_bid = max(h_depth.buy_orders.keys())
            
            # Simple MM with inventory skew
            bid_p = int(h_fair - 1 - (h_pos / 40))
            ask_p = int(h_fair + 1 - (h_pos / 40))
            
            h_orders.append(Order(HYDRO, int(min(bid_p, best_ask - 1)), int(LIMITS[HYDRO] - h_pos)))
            h_orders.append(Order(HYDRO, int(max(ask_p, best_bid + 1)), int(-(LIMITS[HYDRO] + h_pos))))
            result[HYDRO] = h_orders

        return result, 0, ""