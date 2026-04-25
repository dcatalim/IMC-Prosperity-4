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


logger = Logger()


class Trader:
    HYDRO = "HYDROGEL_PACK"
    VELVET = "VELVETFRUIT_EXTRACT"
    VOUCHER = "VEV_4000"

    def __init__(self) -> None:
        self.limits = {
            self.HYDRO: 200,
            self.VELVET: 200,
            self.VOUCHER: 300,
        }
        self.sigma = 0.01275

    def load_state(self, raw: str) -> dict[str, Any]:
        if not raw:
            return {"ema": {}}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                parsed.setdefault("ema", {})
                return parsed
        except json.JSONDecodeError:
            pass
        return {"ema": {}}

    def save_state(self, state: dict[str, Any]) -> str:
        return json.dumps(state, separators=(",", ":"))

    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, spot: float, strike: float, tte: float) -> float:
        if tte <= 0:
            return max(0.0, spot - strike)
        sigma = max(self.sigma, 1e-9)
        tte = max(tte, 1e-9)
        d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * tte) / (sigma * math.sqrt(tte))
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
        }

    def update_ema(self, cache: dict[str, Any], symbol: str, price: float, alpha: float) -> float:
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
        limit: int,
    ) -> tuple[list[Order], int]:
        orders: list[Order] = []
        working_position = position
        buy_threshold = math.floor(fair - buy_edge)
        for ask in sorted(depth.sell_orders):
            volume = -depth.sell_orders[ask]
            if ask > buy_threshold or working_position >= limit:
                break
            quantity = min(volume, limit - working_position)
            if quantity > 0:
                orders.append(Order(symbol, int(ask), quantity))
                working_position += quantity
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
        limit: int,
        width: float,
        skew: float,
        size: int,
    ) -> list[Order]:
        orders: list[Order] = []
        reservation = fair - skew * position
        bid_price = max(int(book["best_bid"]) + 1, math.floor(reservation - width))
        ask_price = min(int(book["best_ask"]) - 1, math.ceil(reservation + width))
        if position < limit and bid_price < int(book["best_ask"]):
            quantity = min(size, limit - position)
            if quantity > 0:
                orders.append(Order(symbol, bid_price, quantity))
        if position > -limit and ask_price > int(book["best_bid"]):
            quantity = min(size, position + limit)
            if quantity > 0:
                orders.append(Order(symbol, ask_price, -quantity))
        return orders

    def hydro_fair(self, book: dict[str, float], ema: float) -> float:
        return 10000.0 + 0.90 * (book["micro"] - book["mid"]) + 0.18 * (10000.0 - ema)

    def velvet_reference(self, book: dict[str, float], ema: float) -> float:
        return book["mid"] + 0.20 * (book["micro"] - book["mid"]) - 0.04 * (book["mid"] - ema)

    def trade_hydro(self, state: TradingState, cache: dict[str, Any]) -> list[Order]:
        depth = state.order_depths.get(self.HYDRO)
        if depth is None:
            return []
        book = self.get_book(depth)
        if book is None:
            return []
        position = state.position.get(self.HYDRO, 0)
        limit = self.limits[self.HYDRO]
        ema = self.update_ema(cache, self.HYDRO, book["mid"], 0.08)
        fair = self.hydro_fair(book, ema)

        orders, position = self.take_liquidity(
            self.HYDRO,
            depth,
            fair,
            4.0 if position > 60 else 2.0,
            4.0 if position < -60 else 2.0,
            position,
            limit,
        )

        if position > 120:
            orders.append(Order(self.HYDRO, max(int(book["best_bid"]), math.floor(fair)), -min(30, position)))
        elif position < -120:
            orders.append(Order(self.HYDRO, min(int(book["best_ask"]), math.ceil(fair)), min(30, -position)))

        orders.extend(self.make_liquidity(self.HYDRO, book, fair, position, limit, 2.0, 0.03, 30))
        return orders

    def trade_vev4000(self, state: TradingState, cache: dict[str, Any]) -> list[Order]:
        velvet_depth = state.order_depths.get(self.VELVET)
        voucher_depth = state.order_depths.get(self.VOUCHER)
        if velvet_depth is None or voucher_depth is None:
            return []
        velvet_book = self.get_book(velvet_depth)
        voucher_book = self.get_book(voucher_depth)
        if velvet_book is None or voucher_book is None:
            return []
        ema = self.update_ema(cache, self.VELVET, velvet_book["mid"], 0.10)
        velvet_fair = self.velvet_reference(velvet_book, ema)
        fair = self.bs_call(velvet_fair, 4000, max(0.0001, 5.0 - state.timestamp / 1_000_000.0))
        position = state.position.get(self.VOUCHER, 0)
        limit = self.limits[self.VOUCHER]

        orders, position = self.take_liquidity(self.VOUCHER, voucher_depth, fair, 10.0, 10.0, position, limit)

        if position > 180:
            orders.append(Order(self.VOUCHER, int(voucher_book["best_bid"]), -min(20, position)))
        elif position < -180:
            orders.append(Order(self.VOUCHER, int(voucher_book["best_ask"]), min(20, -position)))

        orders.extend(self.make_liquidity(self.VOUCHER, voucher_book, fair, position, limit, 6.0, 0.03, 16))
        return orders

    def run(self, state: TradingState):
        cache = self.load_state(state.traderData)
        result: dict[Symbol, list[Order]] = {}
        hydro_orders = self.trade_hydro(state, cache)
        if hydro_orders:
            result[self.HYDRO] = hydro_orders
        voucher_orders = self.trade_vev4000(state, cache)
        if voucher_orders:
            result[self.VOUCHER] = voucher_orders
        trader_data = self.save_state(cache)
        conversions = 0
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
