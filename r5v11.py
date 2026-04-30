from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List
import json
import math

# ─── Constants ────────────────────────────────────────────────────────────────
POSITION_LIMIT = 10

# After this many ticks in day 1, we lock in which market-made products to keep.
# Products with negative mark-to-market at this point get disabled for the rest
# of the run.  Inherited from r5v7.
WARMUP_END = 2000

# Fraction of market-made products to keep after selection.
KEEP_FRACTION = 0.65

# ─── Product classification ────────────────────────────────────────────────────
#
# CORE products: high conviction, very consistent trend across all 3 days.
#   We chase them aggressively (aggressive_mult=0.75, passive_fraction=1.0).
#
# SECONDARY products: strong trend but slightly more volatile.
#   We chase somewhat more gently (aggressive_mult=0.60, passive_fraction=0.5).
#
# SKIP products: unpredictable or net-negative with no clear directional edge.
#   We simply never send any orders for these.
#
# Everything else: market-make, using fair-value estimation + spread skewing.
#
# KEY CHANGES vs r5v7:
#   + GALAXY_SOUNDS_SOLAR_FLAMES → SECONDARY_UP
#     (trends up 2/3 days just like its sibling BLACK_HOLES; was market-made
#     and getting adversely selected, losing ~8.3k total)
#   + ROBOT_MOPPING → SECONDARY_UP
#     (net +15.9% over 3 days; day-3 spike of +24% was massacring the
#     market-maker for ~9.8k loss in a single day; all other robots are
#     already trend-traded)
#   + PEBBLES_L → SKIP
#     (wildly inconsistent: +1%, +9%, -17%; market-maker lost 6.8k on day 2
#     and earned nothing on days 3-4; no reliable directional edge)
#   + TRANSLATOR_GRAPHITE_MIST → SKIP
#     (noisy: -6.6%, +18.3%, -11.4%; net negative; market-maker not
#     compensated for the risk)

CORE_UP = {
    "GALAXY_SOUNDS_BLACK_HOLES",   # +34k total, all 3 days positive
    "OXYGEN_SHAKE_GARLIC",          # +39k total, all 3 days positive
    "PANEL_2X4",                    # +24k total, all 3 days positive
    "UV_VISOR_RED",                 # +17k total, all 3 days positive
    "SLEEP_POD_LAMB_WOOL",          # +8k total, all 3 days positive
    "SNACKPACK_STRAWBERRY",         # +9k total, all 3 days positive
}

CORE_DOWN = {
    "MICROCHIP_OVAL",               # -44.8% total drift → short pays off
    "PEBBLES_XS",                   # -39.6% total drift
    "UV_VISOR_AMBER",               # -28.7% total drift (counter-intuitive:
                                    #   we're SHORT so falling price = our gain)
    "PEBBLES_S",                    # -19.3% total drift
    "SNACKPACK_PISTACHIO",          # consistent slow decline
    "SNACKPACK_CHOCOLATE",          # consistent slow decline
}

SECONDARY_UP = {
    "MICROCHIP_SQUARE",             # huge +36k but volatile on day 4
    "PEBBLES_XL",                   # +61k but big drawdown on day 3
    "SLEEP_POD_COTTON",             # +14k, 2/3 days positive
    "SLEEP_POD_POLYESTER",          # +20k, 2/3 days positive
    "SLEEP_POD_SUEDE",              # +18k, 2/3 days positive
    "TRANSLATOR_VOID_BLUE",         # +15k, 2/3 days positive
    "UV_VISOR_MAGENTA",             # +15k, 2/3 days positive
    "ROBOT_DISHES",                 # +12k, 2/3 days positive
    # ── NEW in v8 ──────────────────────────────────────────────────────────
    "GALAXY_SOUNDS_SOLAR_FLAMES",   # +13.5%, -6.1%, +1.7%: net UP, was losing
                                    #   8.3k as a market-made product
    "ROBOT_MOPPING",                # -1.8%, +24%, -4.8%: net +15.9% UP;
                                    #   market-maker bled 9.8k on day-3 spike
}

SECONDARY_DOWN = {
    "ROBOT_IRONING",                # +21k profit being short
    "ROBOT_VACUUMING",              # +17k profit being short
    "MICROCHIP_TRIANGLE",           # +21k profit being short
    "MICROCHIP_RECTANGLE",          # +12k profit being short
    "ROBOT_LAUNDRY",                # +7k profit being short
    "TRANSLATOR_SPACE_GRAY",        # +15k profit being short
    "TRANSLATOR_ASTRO_BLACK",       # +10k profit being short
}

# Products we deliberately never trade — no reliable edge.
SKIP = {
    "PEBBLES_L",                    # inconsistent: +1%, +9%, -17%; net loser
    "TRANSLATOR_GRAPHITE_MIST",     # noisy: -6.6%, +18.3%, -11.4%; net loser
}

TARGETED = CORE_UP | CORE_DOWN | SECONDARY_UP | SECONDARY_DOWN


class Trader:
    def run(self, state: TradingState):
        store = self._load_store(state.traderData)
        product_state = store["product_state"]
        selection_locked = store["selection_locked"]
        result: Dict[str, List[Order]] = {}

        # ── Update cash-flow ledger from our own fills ─────────────────────
        # This tracks how much cash each product has earned/cost us so that
        # at selection time (t=WARMUP_END) we can rank the market-made products
        # by mark-to-market PnL and drop the worst performers.
        for product, trades in state.own_trades.items():
            ps = product_state.setdefault(product, {"cash": 0.0, "enabled": True})
            for trade in trades:
                qty = int(trade.quantity)
                if trade.buyer == "SUBMISSION":
                    ps["cash"] -= trade.price * qty   # we paid this
                elif trade.seller == "SUBMISSION":
                    ps["cash"] += trade.price * qty   # we received this

        # ── Compute mid-prices and fair values ─────────────────────────────
        mids: Dict[str, float] = {}
        fair_values: Dict[str, float] = {}
        spreads: Dict[str, int] = {}

        for product, order_depth in state.order_depths.items():
            if not order_depth.buy_orders or not order_depth.sell_orders:
                continue
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            spread = best_ask - best_bid
            if spread <= 0:
                continue
            spreads[product] = spread
            mids[product] = (best_bid + best_ask) / 2.0
            fair_values[product] = self._estimate_fair_value(
                order_depth, best_bid, best_ask, spread
            )

        # ── Selection lock: rank market-made products by early MTM PnL ─────
        # After WARMUP_END ticks we lock in which market-made products to keep.
        # The idea: products already losing early are likely being adversely
        # selected (i.e., they have a trend the market-maker doesn't know about).
        # We drop the bottom (1 - KEEP_FRACTION) fraction.
        if not selection_locked and state.timestamp >= WARMUP_END:
            candidates = []
            for product, mid_price in mids.items():
                if product in TARGETED or product in SKIP:
                    continue
                position = state.position.get(product, 0)
                ps = product_state.setdefault(product, {"cash": 0.0, "enabled": True})
                # Mark-to-market: cash received/paid + current position valued at mid
                mtm_pnl = ps["cash"] + position * mid_price
                candidates.append((mtm_pnl, product))

            candidates.sort(reverse=True)
            keep_count = max(1, int(math.ceil(len(candidates) * KEEP_FRACTION)))
            keep = {product for _, product in candidates[:keep_count]}
            for _, product in candidates:
                product_state.setdefault(product, {"cash": 0.0, "enabled": True})[
                    "enabled"
                ] = product in keep
            selection_locked = True

        # ── Generate orders ────────────────────────────────────────────────
        for product, order_depth in state.order_depths.items():
            # Never trade skipped products — no edge, avoid noise.
            if product in SKIP:
                continue

            position = state.position.get(product, 0)
            if product not in fair_values:
                continue

            spread = spreads[product]
            fair_value = fair_values[product]

            if product in CORE_UP:
                # High conviction long: chase aggressively, place passive too
                result[product] = self._trend_trade(
                    product, order_depth, position,
                    target=+POSITION_LIMIT,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_mult=0.75,
                    passive_fraction=1.0,
                )
            elif product in CORE_DOWN:
                # High conviction short: mirror of above
                result[product] = self._trend_trade(
                    product, order_depth, position,
                    target=-POSITION_LIMIT,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_mult=0.75,
                    passive_fraction=1.0,
                )
            elif product in SECONDARY_UP:
                # Medium conviction long: slightly less aggressive
                result[product] = self._trend_trade(
                    product, order_depth, position,
                    target=+POSITION_LIMIT,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_mult=0.60,
                    passive_fraction=0.5,
                )
            elif product in SECONDARY_DOWN:
                # Medium conviction short
                result[product] = self._trend_trade(
                    product, order_depth, position,
                    target=-POSITION_LIMIT,
                    fair_value=fair_value,
                    spread=spread,
                    aggressive_mult=0.60,
                    passive_fraction=0.5,
                )
            else:
                # Market-made product
                enabled = product_state.setdefault(
                    product, {"cash": 0.0, "enabled": True}
                )["enabled"]
                if enabled:
                    result[product] = self._market_make(
                        product, order_depth, position, fair_value, spread
                    )
                elif position != 0:
                    # Product was disabled after selection — unwind residual position
                    result[product] = self._flatten(product, order_depth, position)

        trader_data = json.dumps(
            {"selection_locked": selection_locked, "product_state": product_state},
            separators=(",", ":"),
        )
        return result, 0, trader_data

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_store(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"selection_locked": False, "product_state": {}}
        try:
            data = json.loads(trader_data)
        except json.JSONDecodeError:
            return {"selection_locked": False, "product_state": {}}

        selection_locked = bool(data.get("selection_locked", False))
        product_state = {}
        if isinstance(data.get("product_state"), dict):
            for product, state in data["product_state"].items():
                if isinstance(state, dict):
                    product_state[product] = {
                        "cash": float(state.get("cash", 0.0)),
                        "enabled": bool(state.get("enabled", True)),
                    }
        return {"selection_locked": selection_locked, "product_state": product_state}

    def _estimate_fair_value(
        self,
        order_depth: OrderDepth,
        best_bid: int,
        best_ask: int,
        spread: int,
    ) -> float:
        """
        Estimate fair value by adjusting the book mid-price by the order-book
        imbalance.  If there's much more volume on the bid side, buyers are
        eager — fair value is probably a bit above mid, and vice versa.

        imbalance ∈ [-1, 1]:  +1 = all bid volume, -1 = all ask volume.
        We nudge fair_value by 35% of the spread in that direction.
        """
        bid_volume = sum(order_depth.buy_orders.values())
        ask_volume = abs(sum(order_depth.sell_orders.values()))
        total_volume = bid_volume + ask_volume

        book_mid = (best_bid + best_ask) / 2.0
        if total_volume == 0:
            return book_mid

        imbalance = (bid_volume - ask_volume) / total_volume
        return book_mid + imbalance * max(1.0, spread) * 0.35

    def _trend_trade(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
        fair_value: float,
        spread: int,
        aggressive_mult: float,
        passive_fraction: float,
    ) -> List[Order]:
        """
        Try to reach `target` position (±POSITION_LIMIT).

        Aggressive leg: lift existing orders if their price is within
        `fair_value ± spread * aggressive_mult` — i.e., we're willing to
        cross a fraction of the spread to get filled.

        Passive leg: if the aggressive leg doesn't fully fill us, place a
        resting limit order just inside the current best quote.
        `passive_fraction` controls what fraction of the remaining size we post.
        """
        orders: List[Order] = []
        remaining = target - position
        if remaining == 0:
            return orders

        aggressive_margin = max(1.0, spread * aggressive_mult)

        if remaining > 0:
            # We want to BUY — take from the ask side
            for ask_price, ask_qty_neg in sorted(order_depth.sell_orders.items()):
                if remaining <= 0:
                    break
                if ask_price > fair_value + aggressive_margin:
                    break   # too expensive; stop taking
                take = min(-ask_qty_neg, remaining)
                orders.append(Order(product, ask_price, take))
                remaining -= take

            if remaining > 0:
                # Post a passive bid just above the current best bid
                best_bid = max(order_depth.buy_orders.keys())
                passive_price = min(best_bid + 1, int(math.floor(fair_value + 1)))
                passive_qty = max(1, int(math.ceil(remaining * passive_fraction)))
                if passive_price < min(order_depth.sell_orders.keys()):
                    orders.append(Order(product, passive_price, passive_qty))
        else:
            # We want to SELL — hit the bid side
            qty_to_sell = -remaining
            for bid_price, bid_qty in sorted(
                order_depth.buy_orders.items(), reverse=True
            ):
                if qty_to_sell <= 0:
                    break
                if bid_price < fair_value - aggressive_margin:
                    break   # bids are too low; stop hitting
                take = min(bid_qty, qty_to_sell)
                orders.append(Order(product, bid_price, -take))
                qty_to_sell -= take

            if qty_to_sell > 0:
                # Post a passive ask just below the current best ask
                best_ask = min(order_depth.sell_orders.keys())
                passive_price = max(best_ask - 1, int(math.ceil(fair_value - 1)))
                passive_qty = max(1, int(math.ceil(qty_to_sell * passive_fraction)))
                if passive_price > max(order_depth.buy_orders.keys()):
                    orders.append(Order(product, passive_price, -passive_qty))

        return orders

    def _market_make(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        fair_value: float,
        spread: int,
    ) -> List[Order]:
        """
        Post a two-sided quote centered on fair_value.
        We skew our quotes against our current position to manage inventory:
        if we're long we make our ask more aggressive and bid less aggressive.

        We only market-make if the spread is at least 3 (i.e., there is
        actually a gap to earn a profit from).
        """
        orders: List[Order] = []
        if spread < 3:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())

        # skew: positive position → push quotes down (sell more, buy less)
        skew = position * 0.3
        our_bid = int(min(best_bid + 1, math.floor(fair_value - 1.0 - skew)))
        our_ask = int(max(best_ask - 1, math.ceil(fair_value + 1.0 - skew)))

        if our_bid >= our_ask:
            return orders   # would cross ourselves; skip

        buy_capacity = max(0, POSITION_LIMIT - position)
        sell_capacity = max(0, POSITION_LIMIT + position)

        if buy_capacity > 0:
            orders.append(Order(product, our_bid, min(4, buy_capacity)))
        if sell_capacity > 0:
            orders.append(Order(product, our_ask, -min(4, sell_capacity)))

        return orders

    def _flatten(
        self, product: str, order_depth: OrderDepth, position: int
    ) -> List[Order]:
        """
        Aggressively close out a residual position at the best available price.
        Called when a market-made product has been disabled but we still hold
        inventory.
        """
        orders: List[Order] = []
        if position > 0:
            orders.append(
                Order(product, max(order_depth.buy_orders.keys()), -position)
            )
        elif position < 0:
            orders.append(
                Order(product, min(order_depth.sell_orders.keys()), -position)
            )
        return orders