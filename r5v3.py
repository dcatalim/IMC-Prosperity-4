import json
import math
from typing import Dict, List, Optional, Tuple

try:
    from datamodel import OrderDepth, TradingState, Order
except ImportError:
    class Order:
        def __init__(self, symbol: str, price: int, quantity: int) -> None:
            self.symbol = symbol
            self.price = price
            self.quantity = quantity

    class OrderDepth:
        def __init__(self) -> None:
            self.buy_orders: Dict[int, int] = {}
            self.sell_orders: Dict[int, int] = {}

    class TradingState:
        def __init__(
            self,
            traderData: str = "",
            order_depths: Optional[Dict[str, OrderDepth]] = None,
            position: Optional[Dict[str, int]] = None,
            timestamp: int = 0,
        ) -> None:
            self.traderData = traderData
            self.order_depths = order_depths or {}
            self.position = position or {}
            self.timestamp = timestamp


POSITION_LIMIT = 10
TARGET_SCALE = 300.0
PRODUCT_PRIOR_WEIGHT = 0.80
REALIZED_DECAY = 0.30
SLOPE_REALIZED_DECAY = 0.50
EMA_WEIGHT = 0.35
EMA_ALPHA = 0.08

LEVEL_COEFFS = [0.2, 0.2, 0.2, 0.2, 0.2]
SLOPE_COEFFS = [-0.4, -0.2, 0.0, 0.2, 0.4]
CURVE_COEFFS = [2.0 / 7.0, -1.0 / 7.0, -2.0 / 7.0, -1.0 / 7.0, 2.0 / 7.0]
SLOPE_LOADINGS = [-1.0, -0.5, 0.0, 0.5, 1.0]
CURVE_LOADINGS = [1.0, -0.5, -1.0, -0.5, 1.0]

CATEGORY_PRODUCTS: Dict[str, List[str]] = {
    "GALAXY_SOUNDS": [
        "GALAXY_SOUNDS_DARK_MATTER",
        "GALAXY_SOUNDS_BLACK_HOLES",
        "GALAXY_SOUNDS_PLANETARY_RINGS",
        "GALAXY_SOUNDS_SOLAR_WINDS",
        "GALAXY_SOUNDS_SOLAR_FLAMES",
    ],
    "SLEEP_POD": [
        "SLEEP_POD_SUEDE",
        "SLEEP_POD_LAMB_WOOL",
        "SLEEP_POD_POLYESTER",
        "SLEEP_POD_NYLON",
        "SLEEP_POD_COTTON",
    ],
    "MICROCHIP": [
        "MICROCHIP_CIRCLE",
        "MICROCHIP_OVAL",
        "MICROCHIP_SQUARE",
        "MICROCHIP_RECTANGLE",
        "MICROCHIP_TRIANGLE",
    ],
    "PEBBLES": [
        "PEBBLES_XS",
        "PEBBLES_S",
        "PEBBLES_M",
        "PEBBLES_L",
        "PEBBLES_XL",
    ],
    "ROBOT": [
        "ROBOT_VACUUMING",
        "ROBOT_MOPPING",
        "ROBOT_DISHES",
        "ROBOT_LAUNDRY",
        "ROBOT_IRONING",
    ],
    "UV_VISOR": [
        "UV_VISOR_YELLOW",
        "UV_VISOR_AMBER",
        "UV_VISOR_ORANGE",
        "UV_VISOR_RED",
        "UV_VISOR_MAGENTA",
    ],
    "TRANSLATOR": [
        "TRANSLATOR_SPACE_GRAY",
        "TRANSLATOR_ASTRO_BLACK",
        "TRANSLATOR_ECLIPSE_CHARCOAL",
        "TRANSLATOR_GRAPHITE_MIST",
        "TRANSLATOR_VOID_BLUE",
    ],
    "PANEL": [
        "PANEL_1X2",
        "PANEL_2X2",
        "PANEL_1X4",
        "PANEL_2X4",
        "PANEL_4X4",
    ],
    "OXYGEN_SHAKE": [
        "OXYGEN_SHAKE_MORNING_BREATH",
        "OXYGEN_SHAKE_EVENING_BREATH",
        "OXYGEN_SHAKE_MINT",
        "OXYGEN_SHAKE_CHOCOLATE",
        "OXYGEN_SHAKE_GARLIC",
    ],
    "SNACKPACK": [
        "SNACKPACK_CHOCOLATE",
        "SNACKPACK_VANILLA",
        "SNACKPACK_PISTACHIO",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_RASPBERRY",
    ],
}

PRODUCT_TO_CATEGORY = {
    product: category
    for category, products in CATEGORY_PRODUCTS.items()
    for product in products
}

PRODUCT_PRIOR = {
    "GALAXY_SOUNDS_BLACK_HOLES": 1151.8,
    "GALAXY_SOUNDS_DARK_MATTER": 59.6,
    "GALAXY_SOUNDS_PLANETARY_RINGS": -80.0,
    "GALAXY_SOUNDS_SOLAR_FLAMES": 184.9,
    "GALAXY_SOUNDS_SOLAR_WINDS": 55.7,
    "MICROCHIP_CIRCLE": 84.9,
    "MICROCHIP_OVAL": -1488.5,
    "MICROCHIP_RECTANGLE": -269.0,
    "MICROCHIP_SQUARE": 803.6,
    "MICROCHIP_TRIANGLE": -462.2,
    "OXYGEN_SHAKE_CHOCOLATE": 160.4,
    "OXYGEN_SHAKE_EVENING_BREATH": -128.9,
    "OXYGEN_SHAKE_GARLIC": 1299.3,
    "OXYGEN_SHAKE_MINT": 34.8,
    "OXYGEN_SHAKE_MORNING_BREATH": -99.8,
    "PANEL_1X2": -66.0,
    "PANEL_1X4": -179.9,
    "PANEL_2X2": -128.0,
    "PANEL_2X4": 790.2,
    "PANEL_4X4": -194.4,
    "PEBBLES_L": -198.0,
    "PEBBLES_M": 153.2,
    "PEBBLES_S": -651.3,
    "PEBBLES_XL": 1363.6,
    "PEBBLES_XS": -1326.2,
    "ROBOT_DISHES": 270.3,
    "ROBOT_IRONING": -480.0,
    "ROBOT_LAUNDRY": -159.7,
    "ROBOT_MOPPING": 353.4,
    "ROBOT_VACUUMING": -380.3,
    "SLEEP_POD_COTTON": 314.3,
    "SLEEP_POD_LAMB_WOOL": 272.0,
    "SLEEP_POD_NYLON": 161.3,
    "SLEEP_POD_POLYESTER": 437.1,
    "SLEEP_POD_SUEDE": 402.0,
    "SNACKPACK_CHOCOLATE": -113.7,
    "SNACKPACK_PISTACHIO": -298.2,
    "SNACKPACK_RASPBERRY": 68.8,
    "SNACKPACK_STRAWBERRY": 297.0,
    "SNACKPACK_VANILLA": 72.9,
    "TRANSLATOR_ASTRO_BLACK": -235.1,
    "TRANSLATOR_ECLIPSE_CHARCOAL": -58.8,
    "TRANSLATOR_GRAPHITE_MIST": -46.7,
    "TRANSLATOR_SPACE_GRAY": -346.4,
    "TRANSLATOR_VOID_BLUE": 339.4,
    "UV_VISOR_AMBER": -954.5,
    "UV_VISOR_MAGENTA": 334.3,
    "UV_VISOR_ORANGE": -151.0,
    "UV_VISOR_RED": 574.0,
    "UV_VISOR_YELLOW": 10.7,
}

SLOPE_PRIOR = {
    "GALAXY_SOUNDS": -138.5,
    "PEBBLES": 1419.5,
    "UV_VISOR": 499.9,
    "TRANSLATOR": 468.1,
    "OXYGEN_SHAKE": 666.4,
    "SNACKPACK": 124.3,
}

SLOPE_WEIGHT = {
    "GALAXY_SOUNDS": 0.25,
    "PEBBLES": 0.75,
    "UV_VISOR": 0.60,
    "TRANSLATOR": 0.55,
    "OXYGEN_SHAKE": 0.65,
    "SNACKPACK": 0.30,
}

RESIDUAL_WEIGHT = {
    "SLEEP_POD": 0.25,
    "PEBBLES": 0.60,
    "ROBOT": 0.20,
    "TRANSLATOR": 0.45,
    "PANEL": 0.35,
    "SNACKPACK": 0.25,
}


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def signed_target(alpha: float) -> int:
    raw = POSITION_LIMIT * math.tanh(alpha / TARGET_SCALE)
    return clamp(int(round(raw)), -POSITION_LIMIT, POSITION_LIMIT)


def category_basis(prices: List[float]) -> Tuple[float, float, float, List[float]]:
    level = sum(c * p for c, p in zip(LEVEL_COEFFS, prices))
    slope = sum(c * p for c, p in zip(SLOPE_COEFFS, prices))
    curve = sum(c * p for c, p in zip(CURVE_COEFFS, prices))
    fitted = [
        level + slope * x + curve * q
        for x, q in zip(SLOPE_LOADINGS, CURVE_LOADINGS)
    ]
    residuals = [price - fit for price, fit in zip(prices, fitted)]
    return level, slope, curve, residuals


class Trader:
    def _load_memory(self, trader_data: str, timestamp: int) -> Dict[str, Dict[str, float]]:
        if trader_data:
            try:
                memory = json.loads(trader_data)
            except Exception:
                memory = {}
        else:
            memory = {}
        if not isinstance(memory, dict):
            memory = {}
        if memory.get("prev_ts", -1) > timestamp:
            memory = {}
        memory.setdefault("open", {})
        memory.setdefault("ema", {})
        return memory

    def _best_prices(
        self, order_depth: OrderDepth
    ) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
        if best_bid is not None and best_ask is not None:
            mid = 0.5 * (best_bid + best_ask)
        elif best_bid is not None:
            mid = float(best_bid)
        elif best_ask is not None:
            mid = float(best_ask)
        else:
            mid = None
        return best_bid, best_ask, mid

    def _build_category_state(
        self,
        mids: Dict[str, float],
        open_mids: Dict[str, float],
    ) -> Dict[str, Dict[str, object]]:
        state: Dict[str, Dict[str, object]] = {}
        for category, products in CATEGORY_PRODUCTS.items():
            if any(product not in mids for product in products):
                continue
            prices = [mids[product] for product in products]
            _, slope, _, residuals = category_basis(prices)
            open_slope = 0.0
            if all(product in open_mids for product in products):
                open_prices = [open_mids[product] for product in products]
                _, open_slope, _, _ = category_basis(open_prices)
            state[category] = {
                "slope_change": slope - open_slope,
                "residuals": {product: residual for product, residual in zip(products, residuals)},
            }
        return state

    def _alpha_for_product(
        self,
        product: str,
        mid: float,
        ema: float,
        open_mid: float,
        category_state: Dict[str, Dict[str, object]],
    ) -> float:
        alpha = 0.0
        realized = mid - open_mid
        alpha += PRODUCT_PRIOR_WEIGHT * (
            PRODUCT_PRIOR.get(product, 0.0) - REALIZED_DECAY * realized
        )
        alpha += EMA_WEIGHT * (ema - mid)

        category = PRODUCT_TO_CATEGORY[product]
        cat_info = category_state.get(category)
        if cat_info is not None:
            residual = float(cat_info["residuals"].get(product, 0.0))
            alpha += -RESIDUAL_WEIGHT.get(category, 0.0) * residual
            if category in SLOPE_PRIOR:
                idx = CATEGORY_PRODUCTS[category].index(product)
                load = SLOPE_LOADINGS[idx]
                slope_remaining = (
                    SLOPE_PRIOR[category]
                    - SLOPE_REALIZED_DECAY * float(cat_info["slope_change"])
                )
                alpha += SLOPE_WEIGHT[category] * load * slope_remaining
        return alpha

    def _trade_to_target(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        target: int,
        fair: float,
    ) -> List[Order]:
        orders: List[Order] = []
        best_bid, best_ask, mid = self._best_prices(order_depth)
        if mid is None:
            return orders

        spread = 2.0
        if best_bid is not None and best_ask is not None:
            spread = max(1.0, float(best_ask - best_bid))
        take_edge = max(1.0, 0.12 * spread)
        passive_edge = max(1.0, 0.25 * spread)

        current = position

        if target > current:
            need = target - current
            for ask_price, ask_qty in sorted(order_depth.sell_orders.items()):
                if need <= 0:
                    break
                if ask_price > fair - take_edge:
                    break
                available = -ask_qty
                trade_qty = min(need, available)
                if trade_qty > 0:
                    orders.append(Order(product, ask_price, trade_qty))
                    current += trade_qty
                    need -= trade_qty
            if need > 0 and best_bid is not None and best_ask is not None:
                bid_price = min(best_bid + 1, int(math.floor(fair - passive_edge)))
                if bid_price < best_ask:
                    orders.append(Order(product, bid_price, need))

        elif target < current:
            need = current - target
            for bid_price, bid_qty in sorted(order_depth.buy_orders.items(), reverse=True):
                if need <= 0:
                    break
                if bid_price < fair + take_edge:
                    break
                trade_qty = min(need, bid_qty)
                if trade_qty > 0:
                    orders.append(Order(product, bid_price, -trade_qty))
                    current -= trade_qty
                    need -= trade_qty
            if need > 0 and best_bid is not None and best_ask is not None:
                ask_price = max(best_ask - 1, int(math.ceil(fair + passive_edge)))
                if ask_price > best_bid:
                    orders.append(Order(product, ask_price, -need))

        return orders

    def run(self, state: TradingState):
        memory = self._load_memory(getattr(state, "traderData", ""), state.timestamp)
        open_mids: Dict[str, float] = memory["open"]
        ema_mids: Dict[str, float] = memory["ema"]

        mids: Dict[str, float] = {}
        best_data: Dict[str, Tuple[Optional[int], Optional[int], Optional[float]]] = {}
        for product, order_depth in state.order_depths.items():
            best_data[product] = self._best_prices(order_depth)
            _, _, mid = best_data[product]
            if mid is None:
                if product in ema_mids:
                    mid = ema_mids[product]
                elif product in open_mids:
                    mid = open_mids[product]
            if mid is None:
                continue
            mids[product] = mid
            open_mids.setdefault(product, mid)
            ema_mids[product] = mid if product not in ema_mids else (
                (1.0 - EMA_ALPHA) * ema_mids[product] + EMA_ALPHA * mid
            )

        category_state = self._build_category_state(mids, open_mids)

        result: Dict[str, List[Order]] = {}
        for product, order_depth in state.order_depths.items():
            if product not in mids:
                result[product] = []
                continue
            position = state.position.get(product, 0)
            mid = mids[product]
            ema = ema_mids[product]
            open_mid = open_mids[product]
            alpha = self._alpha_for_product(product, mid, ema, open_mid, category_state)
            target = signed_target(alpha)
            fair = mid + alpha
            result[product] = self._trade_to_target(
                product=product,
                order_depth=order_depth,
                position=position,
                target=target,
                fair=fair,
            )

        memory["prev_ts"] = state.timestamp
        trader_data = json.dumps(memory, separators=(",", ":"))
        return result, 0, trader_data
