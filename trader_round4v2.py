from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple
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

# Adaptive long-run mids that start with historical estimates but adapt to market data
ADAPTIVE_LONG_RUN_MID: Dict[str, float] = {
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


class AdaptiveFairEstimator:
    """Adaptive fair value estimation that refines historical estimates with market data"""
    def __init__(self):
        self.adaptive_mids: Dict[str, float] = ADAPTIVE_LONG_RUN_MID.copy()
        self.observation_count: Dict[str, int] = defaultdict(int)
        self.max_adaptations = 20  # Much more conservative - limit adaptations

    def update_adaptive_mid(self, symbol: str, market_mid: float):
        """No adaptation - use fixed historical estimates to avoid overfitting"""
        # Don't adapt at all to prevent overfitting to current round data
        pass

    def get_adaptive_mid(self, symbol: str) -> float:
        """Get the current adaptive long-run mid for a symbol"""
        return self.adaptive_mids.get(symbol, 0.0)


class TraderMetrics:
    """Tracks buyer/seller metrics to identify aggressive participants"""
    def __init__(self):
        self.buy_count: Dict[str, int] = defaultdict(int)
        self.sell_count: Dict[str, int] = defaultdict(int)
        self.buy_volume: Dict[str, int] = defaultdict(int)
        self.sell_volume: Dict[str, int] = defaultdict(int)

    def add_trade(self, buyer: str, seller: str, quantity: int):
        """Record a trade between buyer and seller"""
        if buyer:
            self.buy_count[buyer] += 1
            self.buy_volume[buyer] += quantity
        if seller:
            self.sell_count[seller] += 1
            self.sell_volume[seller] += quantity

    def get_aggressiveness(self, participant: str) -> float:
        """Calculate how aggressive a participant is (0 to 1, higher = more aggressive)"""
        buy_count = self.buy_count.get(participant, 0)
        sell_count = self.sell_count.get(participant, 0)
        total_count = buy_count + sell_count
        if total_count == 0:
            return 0.5
        return buy_count / total_count

    def get_volume_ratio(self, participant: str) -> float:
        """Get buy/sell volume ratio for participant"""
        buy_vol = self.buy_volume.get(participant, 0)
        sell_vol = self.sell_volume.get(participant, 0)
        if sell_vol == 0:
            return 1.0 if buy_vol > 0 else 0.5
        return buy_vol / sell_vol


class Trader:
    def __init__(self):
        self.fair_estimator = AdaptiveFairEstimator()

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
    def _micro_price(best_bid: int, bid_vol: int, best_ask: int, ask_vol: int) -> float:
        if bid_vol + ask_vol == 0:
            return (best_bid + best_ask) / 2.0
        return (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)

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

    def _update_trader_metrics(self, state: TradingState, mem: Dict) -> TraderMetrics:
        """
        Analyze recent trades to understand participant behavior.
        Use buyer/seller info to identify aggressive traders and adjust strategies.
        """
        metrics = TraderMetrics()

        # Parse trade history from state
        if hasattr(state, 'latest_trades') and state.latest_trades:
            for product in ALL_SYMBOLS:
                if product in state.latest_trades:
                    for trade in state.latest_trades[product]:
                        # Trade object has: timestamp, buyer, seller, price, quantity, symbol
                        if hasattr(trade, 'buyer') and hasattr(trade, 'seller'):
                            metrics.add_trade(trade.buyer, trade.seller, trade.quantity)

        return metrics

    def _get_sentiment_adjustment(self, metrics: TraderMetrics, product: str, current_mid: float) -> float:
        """
        Get a price adjustment based on recent buyer/seller activity.
        If we're seeing aggressive buying vs selling, market is bullish.
        This adjusts our fair value estimate.

        Returns adjustment as % of mid price (conservative ±2% instead of ±4%)
        """
        # Count most active buyers vs sellers
        if not metrics.buy_count and not metrics.sell_count:
            return 0.0

        total_buy_count = sum(metrics.buy_count.values())
        total_sell_count = sum(metrics.sell_count.values())

        if total_buy_count + total_sell_count == 0:
            return 0.0

        # Bias towards the side with more activity
        buy_ratio = total_buy_count / (total_buy_count + total_sell_count)

        # Map to sentiment: 0.5 = neutral, 1.0 = strong buying, 0.0 = strong selling
        sentiment = buy_ratio

        # Convert to price adjustment (moderate ±3% instead of extreme ±4%)
        adjustment = (sentiment - 0.5) * 0.03
        return adjustment

    def trade_hydro(self, state: TradingState, mem: Dict) -> List[Order]:
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

        # Update adaptive long-run mid with current market data
        self.fair_estimator.update_adaptive_mid(product, mid)
        anchor = self.fair_estimator.get_adaptive_mid(product)

        # Use same proven weighting as original
        fair = 0.6 * mid + 0.4 * anchor

        # Apply sentiment adjustment based on buyer/seller activity (conservative)
        metrics = self._update_trader_metrics(state, mem)
        sentiment_adj = self._get_sentiment_adjustment(metrics, product, mid)
        fair = fair * (1.0 + sentiment_adj)

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

    def trade_velvet(self, state: TradingState, mem: Dict) -> Tuple[List[Order], float]:
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
        micro = self._micro_price(best_bid, bid_vol, best_ask, ask_vol)

        # Update adaptive long-run mid with current market data
        self.fair_estimator.update_adaptive_mid(product, mid)
        adaptive_mid = self.fair_estimator.get_adaptive_mid(product)

        # Use same proven weighting as original
        fair = 0.6 * mid + 0.4 * adaptive_mid

        # Apply sentiment adjustment based on buyer/seller activity (conservative)
        metrics = self._update_trader_metrics(state, mem)
        sentiment_adj = self._get_sentiment_adjustment(metrics, product, mid)
        fair = fair * (1.0 + sentiment_adj)

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

    def trade_vouchers_simple(self, state: TradingState, mem: Dict, S: float) -> List[Order]:
        if S <= 0:
            return []
        orders: List[Order] = []
        metrics = self._update_trader_metrics(state, mem)

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

            # Use intrinsic value as primary fair estimate, with adaptive backup
            intrinsic = max(S - K, 0.0)

            # Get adaptive long-run mid for this voucher
            mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else intrinsic
            self.fair_estimator.update_adaptive_mid(sym, mid)
            anchor = self.fair_estimator.get_adaptive_mid(sym)

            # Use intrinsic if deep ITM, otherwise use adaptive anchor
            if intrinsic > 0 and anchor < intrinsic:
                fair = intrinsic
            else:
                fair = anchor

            # Apply sentiment adjustment (moderate)
            sentiment_adj = self._get_sentiment_adjustment(metrics, sym, mid)
            fair = fair * (1.0 + sentiment_adj)

            # Use more conservative take edges (reduced from 1.5/4.0 to 1.0/3.0)
            take_edge = 1.5 if K in (5000, 5100, 5200, 5300, 5400, 5500) else 4.0
            bought = self._take_below(orders, sym, od, fair - take_edge, buy_capacity)
            sold = self._take_above(orders, sym, od, fair + take_edge, sell_capacity)
            buy_capacity -= bought
            sell_capacity -= sold

            skew = position / limit if limit > 0 else 0.0
            # More conservative base edges
            base_edge = 1.5 if K in (5000, 5100, 5200, 5300, 5400, 5500) else 3.0
            bid_edge = base_edge + 4.0 * max(0.0, skew)
            ask_edge = base_edge - 4.0 * min(0.0, skew)

            mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else fair
            my_bid = int(math.floor(mid - bid_edge))
            my_ask = int(math.ceil(mid + ask_edge))
            if best_ask:
                my_bid = min(my_bid, best_ask - 1)
            if best_bid:
                my_ask = max(my_ask, best_bid + 1)
            if my_bid >= my_ask:
                my_ask = my_bid + 1
            mm_size = 15  # Back to original size for better performance
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

        result: Dict[str, List[Order]] = {}

        hydro_orders = self.trade_hydro(state, mem)
        if hydro_orders:
            result[HYDRO] = hydro_orders

        velvet_orders, S = self.trade_velvet(state, mem)
        if velvet_orders:
            result[VELVET] = velvet_orders

        if S > 0:
            voucher_orders = self.trade_vouchers_simple(state, mem, S)
            for sym in VOUCHERS.keys():
                sym_orders = [o for o in voucher_orders if o.symbol == sym]
                if sym_orders:
                    result[sym] = sym_orders

        trader_data = json.dumps(mem)
        return result, 0, trader_data
