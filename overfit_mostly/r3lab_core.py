import json
import math
from typing import Any

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


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(
        self,
        state: TradingState,
        orders: dict[Symbol, list[Order]],
        conversions: int,
        trader_data: Any,
    ) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )
        max_item_length = (self.max_log_length - base_length) // 3
        print(
            self.to_json(
                [
                    self.compress_state(
                        state, self.truncate(state.traderData, max_item_length)
                    ),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[listing.symbol, listing.product, listing.denomination] for listing in listings.values()]

    def compress_order_depths(
        self, order_depths: dict[Symbol, OrderDepth]
    ) -> dict[Symbol, list[Any]]:
        return {
            symbol: [order_depth.buy_orders, order_depth.sell_orders]
            for symbol, order_depth in order_depths.items()
        }

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


LOGGER = Logger()

VOUCHERS = {
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

DEFAULT_OFFSETS = {
    "VEV_4000": 0.00,
    "VEV_4500": 0.00,
    "VEV_5000": 0.25,
    "VEV_5100": 0.20,
    "VEV_5200": 0.90,
    "VEV_5300": 1.60,
    "VEV_5400": -1.70,
    "VEV_5500": 1.00,
    "VEV_6000": 0.50,
    "VEV_6500": 0.50,
}


def build_trader(config: dict[str, Any]):
    class Trader:
        HYDRO = "HYDROGEL_PACK"
        VELVET = "VELVETFRUIT_EXTRACT"

        def __init__(self) -> None:
            self.config = config
            self.limits = {
                self.HYDRO: 200,
                self.VELVET: 200,
                **{symbol: 300 for symbol in VOUCHERS},
            }

        def clamp(self, value: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, value))

        def load_state(self, raw: str) -> dict[str, Any]:
            if not raw:
                return {"ema": {}, "tte_start": None}
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    parsed.setdefault("ema", {})
                    parsed.setdefault("tte_start", None)
                    return parsed
            except json.JSONDecodeError:
                pass
            return {"ema": {}, "tte_start": None}

        def save_state(self, state: dict[str, Any]) -> str:
            return json.dumps(state, separators=(",", ":"))

        def norm_cdf(self, x: float) -> float:
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

        def bs_call(self, spot: float, strike: float, tte: float, sigma: float) -> float:
            if spot <= 0:
                return 0.0
            if tte <= 0:
                return max(0.0, spot - strike)
            sigma = max(sigma, 1e-9)
            tte = max(tte, 1e-9)
            d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * tte) / (
                sigma * math.sqrt(tte)
            )
            d2 = d1 - sigma * math.sqrt(tte)
            return spot * self.norm_cdf(d1) - strike * self.norm_cdf(d2)

        def get_book(self, depth: OrderDepth) -> dict[str, float] | None:
            if not depth.buy_orders or not depth.sell_orders:
                return None
            best_bid = max(depth.buy_orders)
            best_ask = min(depth.sell_orders)
            bid_volume = depth.buy_orders[best_bid]
            ask_volume = -depth.sell_orders[best_ask]
            mid = (best_bid + best_ask) / 2
            total = bid_volume + ask_volume
            micro = mid if total <= 0 else (best_bid * ask_volume + best_ask * bid_volume) / total
            return {
                "best_bid": float(best_bid),
                "best_ask": float(best_ask),
                "mid": float(mid),
                "micro": float(micro),
                "spread": float(best_ask - best_bid),
            }

        def update_ema(
            self, cache: dict[str, Any], symbol: str, price: float, alpha: float
        ) -> float:
            prev = cache["ema"].get(symbol)
            ema = price if prev is None else alpha * price + (1.0 - alpha) * float(prev)
            cache["ema"][symbol] = ema
            return ema

        def take_liquidity(
            self,
            symbol: str,
            depth: OrderDepth,
            fair: float,
            buy_edge: float,
            sell_edge: float,
            position: int,
            side: str = "both",
        ) -> tuple[list[Order], int]:
            orders: list[Order] = []
            limit = self.limits[symbol]
            working_position = position

            if side in ("both", "buy"):
                buy_threshold = math.floor(fair - buy_edge)
                for ask in sorted(depth.sell_orders):
                    volume = -depth.sell_orders[ask]
                    if ask > buy_threshold or working_position >= limit:
                        break
                    quantity = min(volume, limit - working_position)
                    if quantity > 0:
                        orders.append(Order(symbol, int(ask), quantity))
                        working_position += quantity

            if side in ("both", "sell"):
                sell_threshold = math.ceil(fair + sell_edge)
                for bid in sorted(depth.buy_orders, reverse=True):
                    volume = depth.buy_orders[bid]
                    if bid < sell_threshold or working_position <= -limit:
                        break
                    quantity = min(volume, working_position + limit)
                    if quantity > 0:
                        orders.append(Order(symbol, int(bid), -quantity))
                        working_position -= quantity

            return orders, working_position

        def make_liquidity(
            self,
            symbol: str,
            book: dict[str, float],
            fair: float,
            position: int,
            width: float,
            skew: float,
            size: int,
            side: str = "both",
        ) -> list[Order]:
            orders: list[Order] = []
            limit = self.limits[symbol]
            reservation = fair - skew * position

            bid_price = max(int(book["best_bid"]) + 1, math.floor(reservation - width))
            ask_price = min(int(book["best_ask"]) - 1, math.ceil(reservation + width))

            if side in ("both", "buy") and position < limit and bid_price < int(book["best_ask"]):
                quantity = min(size, limit - position)
                if quantity > 0:
                    orders.append(Order(symbol, bid_price, quantity))

            if side in ("both", "sell") and position > -limit and ask_price > int(book["best_bid"]):
                quantity = min(size, position + limit)
                if quantity > 0:
                    orders.append(Order(symbol, ask_price, -quantity))

            return orders

        def infer_tte_start(self, state: TradingState, velvet_fair: float) -> float:
            candidates = self.config.get("tte_candidates", [5.0, 6.0, 7.0, 8.0])
            sigma = self.config["vouchers"]["sigma"]
            symbols = self.config["vouchers"].get(
                "tte_fit_symbols",
                ["VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"],
            )
            best_tte = candidates[0]
            best_score = float("inf")
            for tte in candidates:
                score = 0.0
                count = 0
                for symbol in symbols:
                    depth = state.order_depths.get(symbol)
                    if depth is None:
                        continue
                    book = self.get_book(depth)
                    if book is None:
                        continue
                    fair = self.bs_call(velvet_fair, VOUCHERS[symbol], tte, sigma)
                    score += (book["mid"] - fair) ** 2
                    count += 1
                if count > 0 and score < best_score:
                    best_score = score
                    best_tte = tte
            return best_tte

        def hydro_fair(self, book: dict[str, float], ema: float) -> float:
            cfg = self.config["hydro"]
            return (
                cfg.get("anchor", 10000.0)
                + cfg.get("micro_coef", 0.9) * (book["micro"] - book["mid"])
                + cfg.get("mean_coef", 0.18) * (cfg.get("anchor", 10000.0) - ema)
            )

        def velvet_fair(self, book: dict[str, float], ema: float) -> float:
            cfg = self.config["velvet"]
            anchor = cfg.get("anchor")
            base = book["mid"] if anchor is None else anchor
            return (
                base
                + cfg.get("micro_coef", 0.0) * (book["micro"] - book["mid"])
                - cfg.get("ema_coef", 0.0) * (book["mid"] - ema)
            )

        def trade_hydro(self, state: TradingState, cache: dict[str, Any]) -> list[Order]:
            cfg = self.config["hydro"]
            depth = state.order_depths.get(self.HYDRO)
            if depth is None:
                return []
            book = self.get_book(depth)
            if book is None:
                return []

            position = state.position.get(self.HYDRO, 0)
            ema = self.update_ema(cache, self.HYDRO, book["mid"], cfg.get("ema_alpha", 0.08))
            fair = self.hydro_fair(book, ema)

            orders, position = self.take_liquidity(
                self.HYDRO,
                depth,
                fair,
                cfg.get("take_buy_edge_wide", 4.0) if position > cfg.get("wide_position", 60) else cfg.get("take_buy_edge", 2.0),
                cfg.get("take_sell_edge_wide", 4.0) if position < -cfg.get("wide_position", 60) else cfg.get("take_sell_edge", 2.0),
                position,
            )

            flatten_trigger = cfg.get("flatten_trigger", 120)
            flatten_size = cfg.get("flatten_size", 25)
            if position > flatten_trigger:
                orders.append(
                    Order(self.HYDRO, max(int(book["best_bid"]), math.floor(fair)), -min(flatten_size, position))
                )
            elif position < -flatten_trigger:
                orders.append(
                    Order(self.HYDRO, min(int(book["best_ask"]), math.ceil(fair)), min(flatten_size, -position))
                )

            orders.extend(
                self.make_liquidity(
                    self.HYDRO,
                    book,
                    fair,
                    position,
                    cfg.get("quote_width", 2.0),
                    cfg.get("skew", 0.03),
                    cfg.get("quote_size", 24),
                )
            )
            return orders

        def trade_velvet(
            self, state: TradingState, cache: dict[str, Any]
        ) -> tuple[list[Order], float | None]:
            cfg = self.config["velvet"]
            if not cfg.get("enabled", False):
                return [], None
            depth = state.order_depths.get(self.VELVET)
            if depth is None:
                return [], None
            book = self.get_book(depth)
            if book is None:
                return [], None

            position = state.position.get(self.VELVET, 0)
            ema = self.update_ema(cache, self.VELVET, book["mid"], cfg.get("ema_alpha", 0.10))
            fair = self.velvet_fair(book, ema)
            orders: list[Order] = []

            if cfg.get("take_enabled", False):
                take_orders, position = self.take_liquidity(
                    self.VELVET,
                    depth,
                    fair,
                    cfg.get("take_buy_edge", 3.0),
                    cfg.get("take_sell_edge", 3.0),
                    position,
                )
                orders.extend(take_orders)

            flatten_trigger = cfg.get("flatten_trigger", 60)
            flatten_size = cfg.get("flatten_size", 8)
            if position > flatten_trigger:
                orders.append(Order(self.VELVET, max(int(book["best_bid"]), math.floor(fair)), -min(flatten_size, position)))
            elif position < -flatten_trigger:
                orders.append(Order(self.VELVET, min(int(book["best_ask"]), math.ceil(fair)), min(flatten_size, -position)))

            orders.extend(
                self.make_liquidity(
                    self.VELVET,
                    book,
                    fair,
                    position,
                    cfg.get("quote_width", 2.0),
                    cfg.get("skew", 0.04),
                    cfg.get("quote_size", 8),
                )
            )

            return orders, fair

        def trade_voucher(
            self,
            symbol: str,
            state: TradingState,
            velvet_reference: float,
            tte_start: float,
        ) -> list[Order]:
            cfg = self.config["vouchers"]
            depth = state.order_depths.get(symbol)
            if depth is None:
                return []
            book = self.get_book(depth)
            if book is None:
                return []

            strike = VOUCHERS[symbol]
            tte = max(0.0001, tte_start - state.timestamp / 1_000_000.0)
            fair = self.bs_call(velvet_reference, strike, tte, cfg["sigma"]) + cfg["offsets"].get(symbol, 0.0)
            position = state.position.get(symbol, 0)
            side = cfg["sides"].get(symbol, "both")
            orders: list[Order] = []

            take_edge = cfg["take_edges"].get(symbol)
            if take_edge is not None:
                take_orders, position = self.take_liquidity(
                    symbol,
                    depth,
                    fair,
                    take_edge,
                    take_edge,
                    position,
                    side,
                )
                orders.extend(take_orders)

            flatten_trigger = cfg.get("flatten_trigger", 180)
            flatten_size = cfg.get("flatten_size", 20)
            if position > flatten_trigger:
                orders.append(Order(symbol, int(book["best_bid"]), -min(flatten_size, position)))
            elif position < -flatten_trigger:
                orders.append(Order(symbol, int(book["best_ask"]), min(flatten_size, -position)))

            orders.extend(
                self.make_liquidity(
                    symbol,
                    book,
                    fair,
                    position,
                    cfg["quote_widths"].get(symbol, 3.0),
                    cfg.get("skew", 0.03),
                    cfg["quote_sizes"].get(symbol, 6),
                    side,
                )
            )
            return orders

        def run(self, state: TradingState):
            cache = self.load_state(state.traderData)
            result: dict[Symbol, list[Order]] = {}

            hydro_orders = self.trade_hydro(state, cache)
            if hydro_orders:
                result[self.HYDRO] = hydro_orders

            velvet_orders, velvet_reference = self.trade_velvet(state, cache)
            if velvet_orders:
                result[self.VELVET] = velvet_orders

            if velvet_reference is None:
                velvet_depth = state.order_depths.get(self.VELVET)
                velvet_book = self.get_book(velvet_depth) if velvet_depth else None
                if velvet_book is not None:
                    velvet_ema = self.update_ema(cache, self.VELVET, velvet_book["mid"], self.config["velvet"].get("ema_alpha", 0.10))
                    velvet_reference = self.velvet_fair(velvet_book, velvet_ema)

            if velvet_reference is not None:
                if state.timestamp == 0 or cache.get("tte_start") is None:
                    cache["tte_start"] = self.infer_tte_start(state, velvet_reference)
                for symbol in VOUCHERS:
                    voucher_orders = self.trade_voucher(symbol, state, velvet_reference, float(cache["tte_start"]))
                    if voucher_orders:
                        result[symbol] = voucher_orders

            trader_data = self.save_state(cache)
            conversions = 0
            LOGGER.flush(state, result, conversions, trader_data)
            return result, conversions, trader_data

    return Trader


def make_voucher_maps(
    *,
    default_side: str = "both",
    default_width: float = 3.0,
    default_size: int = 6,
    default_take_edge: float | None = None,
    side_overrides: dict[str, str] | None = None,
    width_overrides: dict[str, float] | None = None,
    size_overrides: dict[str, int] | None = None,
    take_overrides: dict[str, float | None] | None = None,
) -> dict[str, dict[str, Any]]:
    sides = {symbol: default_side for symbol in VOUCHERS}
    widths = {symbol: default_width for symbol in VOUCHERS}
    sizes = {symbol: default_size for symbol in VOUCHERS}
    take_edges = {symbol: default_take_edge for symbol in VOUCHERS}

    if side_overrides:
        sides.update(side_overrides)
    if width_overrides:
        widths.update(width_overrides)
    if size_overrides:
        sizes.update(size_overrides)
    if take_overrides:
        take_edges.update(take_overrides)

    return {
        "sides": sides,
        "quote_widths": widths,
        "quote_sizes": sizes,
        "take_edges": take_edges,
    }
