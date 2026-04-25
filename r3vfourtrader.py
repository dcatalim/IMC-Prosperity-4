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
        return [
            [listing.symbol, listing.product, listing.denomination]
            for listing in listings.values()
        ]

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


class Trader:
    HYDRO = "HYDROGEL_PACK"
    VELVET = "VELVETFRUIT_EXTRACT"
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

    def __init__(self) -> None:
        self.limits = {
            self.HYDRO: 200,
            self.VELVET: 200,
            **{symbol: 300 for symbol in self.VOUCHERS},
        }

    def load_cache(self, raw: str) -> dict[str, Any]:
        default = {
            "ema_short": {},
            "ema_long": {},
            "mad": {},
            "sigma": 0.0130,
        }
        if not raw:
            return default
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key, value in default.items():
                    parsed.setdefault(key, value)
                return parsed
        except json.JSONDecodeError:
            pass
        return default

    def save_cache(self, cache: dict[str, Any]) -> str:
        return json.dumps(cache, separators=(",", ":"))

    def clamp(self, value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, spot: float, strike: float, tte: float, sigma: float) -> float:
        if spot <= 0:
            return 0.0
        if tte <= 0:
            return max(0.0, spot - strike)
        sigma = max(1e-6, sigma)
        tte = max(1e-6, tte)
        sqrt_t = math.sqrt(tte)
        d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * tte) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        return spot * self.norm_cdf(d1) - strike * self.norm_cdf(d2)

    def get_book(self, depth: OrderDepth) -> dict[str, float] | None:
        if not depth.buy_orders or not depth.sell_orders:
            return None
        best_bid = max(depth.buy_orders)
        best_ask = min(depth.sell_orders)
        bid_volume = depth.buy_orders[best_bid]
        ask_volume = -depth.sell_orders[best_ask]
        total = bid_volume + ask_volume
        mid = (best_bid + best_ask) / 2.0
        micro = (
            mid
            if total <= 0
            else (best_bid * ask_volume + best_ask * bid_volume) / total
        )
        imbalance = 0.0 if total <= 0 else (bid_volume - ask_volume) / total
        return {
            "best_bid": float(best_bid),
            "best_ask": float(best_ask),
            "bid_volume": float(bid_volume),
            "ask_volume": float(ask_volume),
            "mid": float(mid),
            "micro": float(micro),
            "spread": float(best_ask - best_bid),
            "imbalance": float(imbalance),
        }

    def update_ema(
        self, cache: dict[str, Any], bucket: str, symbol: str, value: float, alpha: float
    ) -> float:
        prev = cache[bucket].get(symbol)
        ema = value if prev is None else alpha * value + (1.0 - alpha) * float(prev)
        cache[bucket][symbol] = ema
        return ema

    def update_mad(
        self, cache: dict[str, Any], symbol: str, value: float, center: float, alpha: float
    ) -> float:
        deviation = abs(value - center)
        prev = cache["mad"].get(symbol)
        mad = deviation if prev is None else alpha * deviation + (1.0 - alpha) * float(prev)
        cache["mad"][symbol] = mad
        return mad

    def take_orders(
        self,
        symbol: str,
        depth: OrderDepth,
        position: int,
        buy_threshold: float | None,
        sell_threshold: float | None,
        max_clip: int,
    ) -> tuple[list[Order], int]:
        orders: list[Order] = []
        working_position = position
        limit = self.limits[symbol]

        if buy_threshold is not None:
            for ask in sorted(depth.sell_orders):
                if ask > buy_threshold or working_position >= limit:
                    break
                volume = -depth.sell_orders[ask]
                quantity = min(volume, max_clip, limit - working_position)
                if quantity > 0:
                    orders.append(Order(symbol, int(ask), quantity))
                    working_position += quantity

        if sell_threshold is not None:
            for bid in sorted(depth.buy_orders, reverse=True):
                if bid < sell_threshold or working_position <= -limit:
                    break
                volume = depth.buy_orders[bid]
                quantity = min(volume, max_clip, working_position + limit)
                if quantity > 0:
                    orders.append(Order(symbol, int(bid), -quantity))
                    working_position -= quantity

        return orders, working_position

    def make_quotes(
        self,
        symbol: str,
        book: dict[str, float],
        reservation: float,
        width: float,
        position: int,
        size: int,
    ) -> list[Order]:
        orders: list[Order] = []
        if size <= 0:
            return orders

        best_bid = int(book["best_bid"])
        best_ask = int(book["best_ask"])
        if best_ask - best_bid <= 1:
            return orders

        limit = self.limits[symbol]
        bid_price = max(best_bid + 1, math.floor(reservation - width))
        ask_price = min(best_ask - 1, math.ceil(reservation + width))

        if bid_price < best_ask and position < limit:
            quantity = min(size, limit - position)
            if quantity > 0:
                orders.append(Order(symbol, int(bid_price), quantity))

        if ask_price > best_bid and position > -limit:
            quantity = min(size, position + limit)
            if quantity > 0:
                orders.append(Order(symbol, int(ask_price), -quantity))

        return orders

    def fit_sigma(
        self, state: TradingState, spot: float, tte: float, previous_sigma: float
    ) -> tuple[float, float]:
        if spot <= 0 or tte <= 0:
            return previous_sigma, 999.0

        start = self.clamp(previous_sigma - 0.0025, 0.010, 0.0165)
        end = self.clamp(previous_sigma + 0.0025, 0.010, 0.0165)
        candidates = []
        sigma = start
        while sigma <= end + 1e-9:
            candidates.append(round(sigma, 6))
            sigma += 0.0004
        if previous_sigma < 0.010 or previous_sigma > 0.0165:
            candidates = [0.010 + 0.0005 * i for i in range(14)]

        best_sigma = previous_sigma
        best_score = float("inf")
        total_weight = 0.0

        books = {}
        for symbol in self.VOUCHERS:
            depth = state.order_depths.get(symbol)
            if depth is None:
                continue
            book = self.get_book(depth)
            if book is None:
                continue
            books[symbol] = book

        if len(books) < 4:
            return previous_sigma, 999.0

        for candidate in candidates:
            score = 0.0
            weight_sum = 0.0
            for symbol, book in books.items():
                mid = book["mid"]
                spread = max(1.0, book["spread"])
                if mid <= 0.5 and self.VOUCHERS[symbol] >= 6000:
                    continue
                theoretical = self.bs_call(spot, self.VOUCHERS[symbol], tte, candidate)
                weight = 1.0 / spread
                score += weight * (theoretical - mid) ** 2
                weight_sum += weight
            if weight_sum > 0 and score < best_score:
                best_score = score
                total_weight = weight_sum
                best_sigma = candidate

        rmse = 999.0 if total_weight <= 0 else math.sqrt(best_score / total_weight)
        return best_sigma, rmse

    def hydro_orders(
        self, state: TradingState, cache: dict[str, Any]
    ) -> tuple[list[Order], float | None]:
        depth = state.order_depths.get(self.HYDRO)
        if depth is None:
            return [], None
        book = self.get_book(depth)
        if book is None:
            return [], None

        position = state.position.get(self.HYDRO, 0)
        short = self.update_ema(cache, "ema_short", self.HYDRO, book["mid"], 0.14)
        long = self.update_ema(cache, "ema_long", self.HYDRO, book["mid"], 0.03)
        mad = self.update_mad(cache, self.HYDRO, book["mid"], long, 0.08)

        fair = (
            10000.0
            + 0.90 * (book["micro"] - book["mid"])
            + 0.18 * (10000.0 - long)
            + 0.15 * (short - long)
        )
        late = self.is_closeout(state)
        edge = 1.5 if abs(position) < 60 else 3.5
        if late:
            edge += 0.75
        take, position = self.take_orders(
            self.HYDRO,
            depth,
            position,
            fair - edge,
            fair + edge,
            max_clip=30,
        )

        orders = take
        if position > (100 if late else 120):
            orders.append(
                Order(
                    self.HYDRO,
                    int(max(book["best_bid"], math.floor(fair))),
                    -min(24, position),
                )
            )
            position -= min(24, position)
        elif position < (-100 if late else -120):
            orders.append(
                Order(
                    self.HYDRO,
                    int(min(book["best_ask"], math.ceil(fair))),
                    min(24, -position),
                )
            )
            position += min(24, -position)

        width = self.clamp(
            1.6 + 0.50 * book["spread"] + 0.35 * mad + (1.0 if late else 0.0),
            2.0,
            4.5,
        )
        reservation = fair - (0.040 if late else 0.030) * position
        orders.extend(
            self.make_quotes(
                self.HYDRO,
                book,
                reservation,
                width,
                position,
                size=14 if late else 24,
            )
        )
        return orders, fair

    def velvet_orders(
        self, state: TradingState, cache: dict[str, Any]
    ) -> tuple[list[Order], float | None]:
        depth = state.order_depths.get(self.VELVET)
        if depth is None:
            return [], None
        book = self.get_book(depth)
        if book is None:
            return [], None

        position = state.position.get(self.VELVET, 0)
        short = self.update_ema(cache, "ema_short", self.VELVET, book["mid"], 0.12)
        long = self.update_ema(cache, "ema_long", self.VELVET, book["mid"], 0.04)
        fair = 0.20 * book["micro"] + 0.55 * short + 0.25 * long
        mad = self.update_mad(cache, self.VELVET, book["mid"], fair, 0.08)
        late = self.is_closeout(state)

        take_edge = self.clamp(
            3.5 + 0.75 * book["spread"] + 1.20 * mad + (1.0 if late else 0.0),
            5.0,
            11.0,
        )
        buy_threshold = fair - take_edge
        sell_threshold = fair + take_edge

        if book["micro"] < book["mid"] - 1.0:
            buy_threshold = None
        if book["micro"] > book["mid"] + 1.0:
            sell_threshold = None

        take, position = self.take_orders(
            self.VELVET,
            depth,
            position,
            buy_threshold,
            sell_threshold,
            max_clip=18,
        )

        orders = take
        if position > 60:
            quantity = min(12, position)
            orders.append(Order(self.VELVET, int(book["best_bid"]), -quantity))
            position -= quantity
        elif position < -60:
            quantity = min(12, -position)
            orders.append(Order(self.VELVET, int(book["best_ask"]), quantity))
            position += quantity

        if late and abs(position) > 20:
            quantity = min(16, abs(position))
            if position > 0:
                orders.append(Order(self.VELVET, int(book["best_bid"]), -quantity))
                position -= quantity
            else:
                orders.append(Order(self.VELVET, int(book["best_ask"]), quantity))
                position += quantity

        width = self.clamp(
            2.0 + 0.65 * book["spread"] + 0.80 * mad + (1.0 if late else 0.0),
            3.0,
            8.0,
        )
        reservation = fair - (0.100 if late else 0.060) * position
        orders.extend(
            self.make_quotes(
                self.VELVET,
                book,
                reservation,
                width,
                position,
                size=4 if late else 8,
            )
        )
        return orders, fair

    def voucher_size(self, fair: float) -> int:
        if fair > 900:
            return 8
        if fair > 250:
            return 6
        if fair > 60:
            return 4
        if fair > 12:
            return 2
        if fair > 4:
            return 1
        return 0

    def should_trade_voucher(self, symbol: str, fair: float) -> bool:
        if fair <= 0:
            return False
        if symbol in ("VEV_6000", "VEV_6500"):
            return False
        if symbol in ("VEV_5400", "VEV_5500") and fair < 40.0:
            return False
        if symbol in ("VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500") and fair < 12.0:
            return False
        return True

    def is_closeout(self, state: TradingState) -> bool:
        return state.timestamp >= 900000

    def voucher_orders(
        self,
        symbol: str,
        state: TradingState,
        spot: float,
        sigma: float,
    ) -> list[Order]:
        depth = state.order_depths.get(symbol)
        if depth is None:
            return []
        book = self.get_book(depth)
        if book is None:
            return []

        tte = max(0.0001, 5.0 - state.timestamp / 1_000_000.0)
        fair = self.bs_call(spot, self.VOUCHERS[symbol], tte, sigma)
        if not self.should_trade_voucher(symbol, fair):
            return []
        late = self.is_closeout(state)
        position = state.position.get(symbol, 0)
        spread = max(1.0, book["spread"])
        width = self.clamp(
            0.55 * spread + 0.75 + (0.25 if late else 0.0),
            1.0,
            8.0,
        )
        take_edge = width + 2.0 + (0.5 if late else 0.0)
        size = self.voucher_size(fair)
        if size <= 0:
            return []

        orders, position = self.take_orders(
            symbol,
            depth,
            position,
            fair - take_edge,
            fair + take_edge,
            max_clip=min(size, 2),
        )

        if position > (120 if not late else 80):
            quantity = min(10, position)
            orders.append(Order(symbol, int(book["best_bid"]), -quantity))
            position -= quantity
        elif position < (-120 if not late else -80):
            quantity = min(10, -position)
            orders.append(Order(symbol, int(book["best_ask"]), quantity))
            position += quantity

        reservation = fair - (0.045 if late else 0.035) * position
        orders.extend(
            self.make_quotes(
                symbol,
                book,
                reservation,
                width,
                position,
                size=size,
            )
        )
        return orders

    def run(self, state: TradingState):
        cache = self.load_cache(state.traderData)
        result: dict[Symbol, list[Order]] = {}

        hydro, _ = self.hydro_orders(state, cache)
        if hydro:
            result[self.HYDRO] = hydro

        velvet, velvet_fair = self.velvet_orders(state, cache)
        if velvet:
            result[self.VELVET] = velvet

        if velvet_fair is None:
            depth = state.order_depths.get(self.VELVET)
            book = self.get_book(depth) if depth is not None else None
            velvet_fair = book["mid"] if book is not None else None

        if velvet_fair is not None:
            tte = max(0.0001, 5.0 - state.timestamp / 1_000_000.0)
            raw_sigma, sigma_rmse = self.fit_sigma(
                state,
                velvet_fair,
                tte,
                float(cache.get("sigma", 0.0130)),
            )
            late = self.is_closeout(state)
            sigma = 0.25 * raw_sigma + 0.75 * float(cache.get("sigma", raw_sigma))
            cache["sigma"] = sigma

            if sigma_rmse <= (7.0 if late else 8.0):
                for symbol in self.VOUCHERS:
                    orders = self.voucher_orders(symbol, state, velvet_fair, sigma)
                    if orders:
                        result[symbol] = orders
            else:
                LOGGER.print(
                    "Skipping vouchers, surface fit too noisy or late:",
                    round(sigma_rmse, 3),
                    "late=",
                    late,
                )

        trader_data = self.save_cache(cache)
        conversions = 0
        LOGGER.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data