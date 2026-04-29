# ═══════════════════════════════════════════════════════════════════════════════
# Round 5 — IMC Prosperity 4
# Strategy: Directional trend-following on 27 identified products,
#            passive market-making on the remaining 23.
#
# All products have position limit = 10.
#
# TREND CLASSIFICATION (from 3-day historical analysis):
#
#   ALL_UP  (consistent all 3 days):
#     GALAXY_SOUNDS_BLACK_HOLES   +1446, +688, +1320  avg=+11,518 PnL/day at limit
#     OXYGEN_SHAKE_GARLIC          +1828, +111, +1958  avg=+12,993
#     PANEL_2X4                    +738, +738, +894    avg=+7,902 (most stable uptrend)
#     UV_VISOR_RED                 +842, +182, +698    avg=+5,740
#     SLEEP_POD_LAMB_WOOL          +404, +396, +16     avg=+2,720
#     SNACKPACK_STRAWBERRY         +436, +358, +98     avg=+2,970
#
#   ALL_DOWN (consistent all 3 days):
#     MICROCHIP_OVAL              -744, -1824, -1898   avg=+14,885 short PnL/day
#     PEBBLES_XS                  -1952, -1204, -824   avg=+13,262
#     UV_VISOR_AMBER              -1500, -1109, -255   avg=+9,545
#     PEBBLES_S                   -840, -177, -937     avg=+6,513
#     SNACKPACK_PISTACHIO         -489, -124, -282     avg=+2,982
#     SNACKPACK_CHOCOLATE         -84, -75, -182       avg=+1,137
#
#   2/3_UP (strong positive expected value):
#     MICROCHIP_SQUARE            +2456, +3438, -2278  avg=+12,053
#     PEBBLES_XL                  +3674, -1552, +4014  avg=+20,453
#     SLEEP_POD_COTTON            +1123, +1076, -784   avg=+4,715
#     SLEEP_POD_POLYESTER         +1766, +1118, -917   avg=+6,557
#     SLEEP_POD_SUEDE             +1099, +1048, -338   avg=+6,030
#     TRANSLATOR_VOID_BLUE        +1082, -426, +871    avg=+5,092
#     UV_VISOR_MAGENTA            +1300, +254, -49     avg=+5,015
#     ROBOT_DISHES                -79, +218, +1077     avg=+4,055
#
#   2/3_DOWN (strong positive expected value from shorting):
#     ROBOT_IRONING               -490, -2000, +330    avg=+7,200
#     ROBOT_VACUUMING             +64, -1466, -309     avg=+5,705
#     MICROCHIP_TRIANGLE          +704, -1706, -1078   avg=+6,933
#     MICROCHIP_RECTANGLE         -580, -1572, +942    avg=+4,035
#     ROBOT_LAUNDRY               +252, -752, -219     avg=+2,395
#     TRANSLATOR_SPACE_GRAY       -507, +638, -1690    avg=+5,197
#     TRANSLATOR_ASTRO_BLACK      +155, -1016, -196    avg=+3,527
#
#   Total expected PnL per day from trend positions: ~191,000
#
# ═══════════════════════════════════════════════════════════════════════════════

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict

# ─── Universal position limit for all products in Round 5 ────────────────────
POSITION_LIMIT = 10

# ─── Products to hold at maximum LONG (+10) throughout ───────────────────────
# We immediately buy to the limit and maintain that position.
TREND_UP = {
    # All 3 historical days rose:
    'GALAXY_SOUNDS_BLACK_HOLES',
    'OXYGEN_SHAKE_GARLIC',
    'PANEL_2X4',
    'UV_VISOR_RED',
    'SLEEP_POD_LAMB_WOOL',
    'SNACKPACK_STRAWBERRY',
    # Rose 2 out of 3 days with positive expected value:
    'MICROCHIP_SQUARE',
    'PEBBLES_XL',
    'SLEEP_POD_COTTON',
    'SLEEP_POD_POLYESTER',
    'SLEEP_POD_SUEDE',
    'TRANSLATOR_VOID_BLUE',
    'UV_VISOR_MAGENTA',
    'ROBOT_DISHES',
}

# ─── Products to hold at maximum SHORT (-10) throughout ──────────────────────
TREND_DOWN = {
    # All 3 historical days fell:
    'MICROCHIP_OVAL',
    'PEBBLES_XS',
    'UV_VISOR_AMBER',
    'PEBBLES_S',
    'SNACKPACK_PISTACHIO',
    'SNACKPACK_CHOCOLATE',
    # Fell 2 out of 3 days with positive expected value from shorting:
    'ROBOT_IRONING',
    'ROBOT_VACUUMING',
    'MICROCHIP_TRIANGLE',
    'MICROCHIP_RECTANGLE',
    'ROBOT_LAUNDRY',
    'TRANSLATOR_SPACE_GRAY',
    'TRANSLATOR_ASTRO_BLACK',
}

# Remaining 23 products → passive market-making (see below)


class Trader:

    def run(self, state: TradingState):
        """
        Called once per timestamp (iteration). Returns:
          result     — dict of product → list of orders to submit
          conversions — 0 (no conversions in Round 5)
          traderData  — empty string (we don't need cross-tick state here)
        """
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            position: int = state.position.get(product, 0)

            if product in TREND_UP:
                # Hold maximum long position; fill aggressively to +LIMIT
                orders = self._go_to_target(
                    product, order_depth, position, target=+POSITION_LIMIT
                )
            elif product in TREND_DOWN:
                # Hold maximum short position; fill aggressively to -LIMIT
                orders = self._go_to_target(
                    product, order_depth, position, target=-POSITION_LIMIT
                )
            else:
                # Oscillating / unclear direction: earn the bid-ask spread passively
                orders = self._market_make(product, order_depth, position)

            result[product] = orders

        return result, 0, ""

    # ──────────────────────────────────────────────────────────────────────────
    # TREND FOLLOWING
    # ──────────────────────────────────────────────────────────────────────────

    def _go_to_target(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
    ) -> List[Order]:
        """
        Fill toward 'target' position as aggressively as possible this tick.

        For target > position (need to BUY):
          1. Take from all available ask levels (cheapest first) up to remaining capacity.
          2. If asks are exhausted before we reach target, post a passive bid
             2 ticks above the current best bid to attract crossing sellers.

        For target < position (need to SELL short):
          1. Hit all available bid levels (highest first) up to remaining capacity.
          2. If bids are exhausted, post a passive ask 2 ticks below best ask.

        "Aggressive taking" means we pay the spread on entry, but for products
        trending by hundreds to thousands per day, the half-spread cost (~4-9 per
        unit) is negligible compared to the expected directional gain.
        """
        orders: List[Order] = []

        # How many units away are we from the target?
        # Positive = need to buy, negative = need to sell.
        remaining = target - position

        if remaining == 0:
            return orders  # Already at target; nothing to do.

        if remaining > 0:
            # ── Need to BUY ────────────────────────────────────────────────
            # sell_orders is a dict {price: negative_quantity}.
            # Sorted ascending = cheapest ask first.
            for ask_price, ask_qty_neg in sorted(order_depth.sell_orders.items()):
                if remaining <= 0:
                    break
                available = -ask_qty_neg  # Convert to positive available quantity
                take = min(available, remaining)
                orders.append(Order(product, ask_price, take))  # positive qty = BUY
                remaining -= take

            # If we couldn't fully fill from existing asks (order book was thin),
            # post a passive buy order to catch any selling bots this tick.
            if remaining > 0 and order_depth.buy_orders:
                best_bid = max(order_depth.buy_orders.keys())
                # Post 2 ticks above best bid — attractive to sellers without
                # overpaying significantly.
                orders.append(Order(product, best_bid + 2, remaining))

        else:
            # ── Need to SELL (go short) ────────────────────────────────────
            qty_to_sell = -remaining  # Make positive for clarity

            # buy_orders is {price: positive_quantity}.
            # Sorted descending = highest bid first (best price for us as seller).
            for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
                if qty_to_sell <= 0:
                    break
                take = min(bid_qty, qty_to_sell)
                orders.append(Order(product, bid_price, -take))  # negative qty = SELL
                qty_to_sell -= take

            # Passive cleanup: post a sell order if bids were exhausted
            if qty_to_sell > 0 and order_depth.sell_orders:
                best_ask = min(order_depth.sell_orders.keys())
                # Post 2 ticks below best ask — attractive to buyers
                orders.append(Order(product, best_ask - 2, -qty_to_sell))

        return orders

    # ──────────────────────────────────────────────────────────────────────────
    # MARKET MAKING
    # ──────────────────────────────────────────────────────────────────────────

    def _market_make(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
    ) -> List[Order]:
        """
        Post passive limit orders just inside the existing bid-ask spread.

        We post:
          - A BUY at (best_bid + 1)  — 1 tick better than the existing best bid
          - A SELL at (best_ask - 1) — 1 tick better than the existing best ask

        Posting 1 tick inside ensures we are at the front of the price queue,
        so any market participant that crosses our price fills us first.

        Quantity: we post up to our full remaining buy/sell capacity.
        The buy capacity and sell capacity are naturally skewed by our current
        position — e.g., if we're long +7, buy_capacity=3 and sell_capacity=17,
        so we will lean toward selling, naturally mean-reverting our inventory.

        We skip this tick if the spread is less than 4 ticks (posting inside
        would mean our bid >= our ask, which makes no sense, or our profit per
        trade would be negative after crossing).
        """
        orders: List[Order] = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        market_spread = best_ask - best_bid

        # Need spread of at least 4 to earn at least 1 tick on each side
        if market_spread < 4:
            return orders

        our_bid = best_bid + 1
        our_ask = best_ask - 1

        # Safety check: our quotes shouldn't cross each other
        if our_bid >= our_ask:
            return orders

        # Capacity calculation:
        # buy_capacity = how many more we can BUY before hitting the +10 limit
        # sell_capacity = how many more we can SELL before hitting the -10 limit
        buy_capacity = POSITION_LIMIT - position   # e.g., pos=+3 → cap=7
        sell_capacity = POSITION_LIMIT + position  # e.g., pos=+3 → cap=13 (sell to -10)

        # Cap each side at POSITION_LIMIT to avoid extreme one-sided exposure
        # on volatile products. This limits downside if price trends hard against us.
        buy_capacity = min(buy_capacity, POSITION_LIMIT)
        sell_capacity = min(sell_capacity, POSITION_LIMIT)

        if buy_capacity > 0:
            orders.append(Order(product, our_bid, buy_capacity))

        if sell_capacity > 0:
            orders.append(Order(product, our_ask, -sell_capacity))

        return orders