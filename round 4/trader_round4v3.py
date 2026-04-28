from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple, Set
import math
import json
from collections import defaultdict

HYDRO = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"
VOUCHERS: Dict[str, int] = {
    "VEV_4000": 4000,
    "VEV_4500": 4500,
    "VEV_5000": 5000,
    "VEV_5100": 5100,
    "VEV_5200": 5200,
    "VEV_5300": 5300,
    "VEV_5400": 5400,
    "VEV_5500": 5500,
    "VEV_6000": 6000,
    "VEV_6500": 6500,
}

POSITION_LIMITS: Dict[str, int] = {
    HYDRO: 200,
    VELVET: 200,
    **{sym: 300 for sym in VOUCHERS},
}

ALL_SYMBOLS = list(VOUCHERS.keys()) + [HYDRO, VELVET]

# Fixed long-run mids from historical data (no adaptation to avoid overfitting)
LONG_RUN_MID: Dict[str, float] = {
    HYDRO: 9990.8069,
    VELVET: 5250.0981,
    "VEV_4000": 1250.1098,
    "VEV_4500": 750.1096,
    "VEV_5000": 255.0224,
    "VEV_5100": 166.8055,
    "VEV_5200": 95.5488,
    "VEV_5300": 46.7599,
    "VEV_5400": 15.9519,
    "VEV_5500": 6.6414,
    "VEV_6000": 0.50,
    "VEV_6500": 0.50,
}

# Time-aware pricing for options with significant time decay
# Round 4: TTE starts at 4 days, decreases by 1 each day
INITIAL_TTE = 4
# Daily decay rates based on historical data (drop per day) - MODERATE VERSION
DAILY_DECAY_RATES: Dict[str, float] = {
    "VEV_5000": 3.0,    # Moderate decay - half the observed rate
    "VEV_5100": 3.5,    # Moderate decay - half the observed rate
    "VEV_5200": 4.0,    # Moderate decay - half the observed rate
    "VEV_5300": 3.5,    # Moderate decay - half the observed rate
    "VEV_5400": 2.0,    # Moderate decay - half the observed rate
    "VEV_5500": 1.0,    # Moderate decay - half the observed rate
}


class TraderIntelligence:
    """Track "Mark" traders to understand their behavior patterns and adjust spreads"""
    
    def __init__(self):
        # By product and trader: how they trade
        self.trader_product_stats: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(lambda: {
            'buy_count': 0,
            'sell_count': 0,
            'buy_volume': 0,
            'sell_volume': 0,
        }))
        self.active_traders: Set[str] = set()
        self.aggressive_buyers: Set[str] = set()
        self.aggressive_sellers: Set[str] = set()
        self.current_tte = INITIAL_TTE  # Track time to expiry
    
    def update_from_trades(self, state: TradingState):
        """Parse all trades to identify trader patterns"""
        if not hasattr(state, 'latest_trades') or not state.latest_trades:
            return
        
        for product in ALL_SYMBOLS:
            if product not in state.latest_trades:
                continue
            
            for trade in state.latest_trades[product]:
                if not hasattr(trade, 'buyer') or not hasattr(trade, 'seller'):
                    continue
                
                buyer = trade.buyer
                seller = trade.seller
                quantity = trade.quantity if hasattr(trade, 'quantity') else 0
                
                if buyer:
                    self.active_traders.add(buyer)
                    stats = self.trader_product_stats[buyer][product]
                    stats['buy_count'] += 1
                    stats['buy_volume'] += quantity
                
                if seller:
                    self.active_traders.add(seller)
                    stats = self.trader_product_stats[seller][product]
                    stats['sell_count'] += 1
                    stats['sell_volume'] += quantity
        
        self._classify_traders()
    
    def _classify_traders(self):
        """Classify which traders are aggressive buyers vs sellers"""
        self.aggressive_buyers.clear()
        self.aggressive_sellers.clear()
        
        for trader, products in self.trader_product_stats.items():
            total_buy = sum(p.get('buy_count', 0) for p in products.values())
            total_sell = sum(p.get('sell_count', 0) for p in products.values())
            total = total_buy + total_sell
            
            if total >= 10:  # High threshold - only very clear patterns
                buy_ratio = total_buy / total
                if buy_ratio > 0.75:  # Very aggressive threshold for consistency
                    self.aggressive_buyers.add(trader)
                elif buy_ratio < 0.25:
                    self.aggressive_sellers.add(trader)
    
    def get_trader_activity_for_product(self, product: str) -> Tuple[int, int]:
        """Get count of aggressive buyers/sellers for a product"""
        buyer_count = len([t for t in self.aggressive_buyers 
                          if product in self.trader_product_stats[t]])
        seller_count = len([t for t in self.aggressive_sellers 
                           if product in self.trader_product_stats[t]])
        return buyer_count, seller_count
    
    def get_time_aware_fair_value(self, symbol: str, intrinsic_value: float) -> float:
        """
        For options with significant time decay (VEV_5000-VEV_5500), adjust the historical
        anchor downward based on observed daily decay rates.
        For other symbols, use the fixed historical anchor.
        """
        if symbol not in DAILY_DECAY_RATES:
            return LONG_RUN_MID.get(symbol, intrinsic_value)
        
        # For time-decaying options: max(intrinsic, anchor - accumulated_decay)
        # This prevents using stale high anchors while still allowing intrinsic value dominance
        base_anchor = LONG_RUN_MID[symbol]
        days_elapsed = INITIAL_TTE - self.current_tte
        accumulated_decay = days_elapsed * DAILY_DECAY_RATES[symbol]
        decayed_anchor = max(intrinsic_value, base_anchor - accumulated_decay)
        
        return decayed_anchor


class Trader:
    def __init__(self):
        self.trader_intel = TraderIntelligence()
    
    def bid(self) -> int:
        return 15
    
    @staticmethod
    def _bbo(od: OrderDepth) -> Tuple[int, int, int, int]:
        if od.buy_orders:
            best_bid = max(od.buy_orders.keys())
            best_bid_qty = od.buy_orders[best_bid]
        else:
            best_bid, best_bid_qty = 0, 0
        if od.sell_orders:
            best_ask = min(od.sell_orders.keys())
            best_ask_qty = -od.sell_orders[best_ask]
        else:
            best_ask, best_ask_qty = 0, 0
        return best_bid, best_bid_qty, best_ask, best_ask_qty
    
    @staticmethod
    def _take_below(orders: List[Order], product: str, od: OrderDepth, threshold: float, capacity: int) -> int:
        if capacity <= 0:
            return 0
        filled = 0
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price <= threshold and capacity > 0:
                qty_avail = -od.sell_orders[ask_price]
                qty = min(qty_avail, capacity)
                if qty <= 0:
                    continue
                orders.append(Order(product, ask_price, qty))
                capacity -= qty
                filled += qty
            else:
                break
        return filled
    
    @staticmethod
    def _take_above(orders: List[Order], product: str, od: OrderDepth, threshold: float, capacity: int) -> int:
        if capacity <= 0:
            return 0
        filled = 0
        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price >= threshold and capacity > 0:
                qty_avail = od.buy_orders[bid_price]
                qty = min(qty_avail, capacity)
                if qty <= 0:
                    continue
                orders.append(Order(product, bid_price, -qty))
                capacity -= qty
                filled += qty
            else:
                break
        return filled
    
    def _get_spread_adjustment_from_traders(self, product: str) -> float:
        """Trader intelligence disabled - always return 0 for now"""
        return 0.0
    
    def trade_hydro(self, state: TradingState) -> List[Order]:
        product = HYDRO
        if product not in state.order_depths:
            return []
        od = state.order_depths[product]
        best_bid, bid_vol, best_ask, ask_vol = self._bbo(od)
        if best_bid == 0 or best_ask == 0:
            return []
        
        position = state.position.get(product, 0)
        limit = POSITION_LIMITS[product]
        mid = (best_bid + best_ask) / 2.0
        anchor = LONG_RUN_MID[product]
        fair = 0.6 * mid + 0.4 * anchor
        
        orders: List[Order] = []
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        
        bought = self._take_below(orders, product, od, fair - 2.0, buy_capacity)
        sold = self._take_above(orders, product, od, fair + 2.0, sell_capacity)
        buy_capacity -= bought
        sell_capacity -= sold
        
        skew = position / limit if limit > 0 else 0.0
        bid_edge = 2.0 + 4.0 * max(0.0, skew)
        ask_edge = 2.0 - 4.0 * min(0.0, skew)
        
        # Adjust spreads based on trader activity
        trader_adj = self._get_spread_adjustment_from_traders(product)
        bid_edge = max(0.5, bid_edge + trader_adj)
        ask_edge = max(0.5, ask_edge - trader_adj)
        
        my_bid = int(round(mid - bid_edge))
        my_ask = int(round(mid + ask_edge))
        my_bid = min(my_bid, best_ask - 1)
        my_ask = max(my_ask, best_bid + 1)
        if my_bid >= my_ask:
            my_ask = my_bid + 1
        
        max_quote = 40
        if buy_capacity > 0:
            orders.append(Order(product, my_bid, min(buy_capacity, max_quote)))
        if sell_capacity > 0:
            orders.append(Order(product, my_ask, -min(sell_capacity, max_quote)))
        return orders
    
    def trade_velvet(self, state: TradingState) -> Tuple[List[Order], float]:
        product = VELVET
        if product not in state.order_depths:
            return [], 0.0
        od = state.order_depths[product]
        best_bid, bid_vol, best_ask, ask_vol = self._bbo(od)
        if best_bid == 0 or best_ask == 0:
            return [], 0.0
        
        position = state.position.get(product, 0)
        limit = POSITION_LIMITS[product]
        mid = (best_bid + best_ask) / 2.0
        anchor = LONG_RUN_MID[product]
        fair = 0.6 * mid + 0.4 * anchor
        
        orders: List[Order] = []
        buy_capacity = max(0, limit - position)
        sell_capacity = max(0, limit + position)
        
        bought = self._take_below(orders, product, od, fair - 2.0, buy_capacity)
        sold = self._take_above(orders, product, od, fair + 2.0, sell_capacity)
        buy_capacity -= bought
        sell_capacity -= sold
        
        skew = position / limit if limit > 0 else 0.0
        bid_edge = 1.0 + 3.0 * max(0.0, skew)
        ask_edge = 1.0 - 3.0 * min(0.0, skew)
        
        # Adjust spreads based on trader activity
        trader_adj = self._get_spread_adjustment_from_traders(product)
        bid_edge = max(0.5, bid_edge + trader_adj)
        ask_edge = max(0.5, ask_edge - trader_adj)
        
        my_bid = int(round(fair - bid_edge))
        my_ask = int(round(fair + ask_edge))
        my_bid = min(my_bid, best_ask - 1)
        my_ask = max(my_ask, best_bid + 1)
        if my_bid >= my_ask:
            my_ask = my_bid + 1
        
        max_quote = 20
        if buy_capacity > 0:
            orders.append(Order(product, my_bid, min(buy_capacity, max_quote)))
        if sell_capacity > 0:
            orders.append(Order(product, my_ask, -min(sell_capacity, max_quote)))
        return orders, fair
    
    def trade_vouchers_simple(self, state: TradingState, S: float) -> List[Order]:
        if S <= 0:
            return []
        orders: List[Order] = []
        
        for sym, K in VOUCHERS.items():
            if sym not in state.order_depths:
                continue
            od = state.order_depths[sym]
            best_bid, bid_vol, best_ask, ask_vol = self._bbo(od)
            if best_bid == 0 and best_ask == 0:
                continue
            
            position = state.position.get(sym, 0)
            limit = POSITION_LIMITS[sym]
            buy_capacity = max(0, limit - position)
            sell_capacity = max(0, limit + position)
            
            intrinsic = max(S - K, 0.0)
            mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else intrinsic
            
            # Use time-aware fair value for options with significant time decay
            fair = self.trader_intel.get_time_aware_fair_value(sym, intrinsic)
            
            take_edge = 1.5 if K in (5000, 5100, 5200, 5300, 5400, 5500) else 4.0
            bought = self._take_below(orders, sym, od, fair - take_edge, buy_capacity)
            sold = self._take_above(orders, sym, od, fair + take_edge, sell_capacity)
            buy_capacity -= bought
            sell_capacity -= sold
            
            skew = position / limit if limit > 0 else 0.0
            base_edge = 1.5 if K in (5000, 5100, 5200, 5300, 5400, 5500) else 3.0
            bid_edge = base_edge + 4.0 * max(0.0, skew)
            ask_edge = base_edge - 4.0 * min(0.0, skew)
            
            # Adjust spreads based on trader activity
            trader_adj = self._get_spread_adjustment_from_traders(sym)
            bid_edge = max(0.5, bid_edge + trader_adj)
            ask_edge = max(0.5, ask_edge - trader_adj)
            
            mid_for_quoting = (best_bid + best_ask) / 2.0 if best_bid and best_ask else fair
            my_bid = int(math.floor(mid_for_quoting - bid_edge))
            my_ask = int(math.ceil(mid_for_quoting + ask_edge))
            if best_ask:
                my_bid = min(my_bid, best_ask - 1)
            if best_bid:
                my_ask = max(my_ask, best_bid + 1)
            if my_bid >= my_ask:
                my_ask = my_bid + 1
            
            mm_size = 15
            if buy_capacity > 0:
                orders.append(Order(sym, my_bid, min(buy_capacity, mm_size)))
            if sell_capacity > 0:
                orders.append(Order(sym, my_ask, -min(sell_capacity, mm_size)))
        return orders
    
    def run(self, state: TradingState):
        try:
            mem = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            mem = {}
        
        # Track actual day transitions, not ticks
        # Timestamp resets/goes backward when a new day starts
        prev_timestamp = mem.get('prev_timestamp', -1)
        current_timestamp = state.timestamp
        
        if current_timestamp < prev_timestamp:
            # Timestamp reset = new day has started
            mem['days_elapsed'] = mem.get('days_elapsed', 0) + 1
        
        mem['prev_timestamp'] = current_timestamp
        self.trader_intel.current_tte = max(0, INITIAL_TTE - mem.get('days_elapsed', 0))
        
        self.trader_intel.update_from_trades(state)
        
        result: Dict[str, List[Order]] = {}
        
        hydro_orders = self.trade_hydro(state)
        if hydro_orders:
            result[HYDRO] = hydro_orders
        
        velvet_orders, S = self.trade_velvet(state)
        if velvet_orders:
            result[VELVET] = velvet_orders
        
        if S > 0:
            voucher_orders = self.trade_vouchers_simple(state, S)
            for sym in VOUCHERS.keys():
                sym_orders = [o for o in voucher_orders if o.symbol == sym]
                if sym_orders:
                    result[sym] = sym_orders
        
        trader_data = json.dumps(mem)
        return result, 0, trader_data
