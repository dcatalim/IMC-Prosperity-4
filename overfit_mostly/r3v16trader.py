from overfit_mostly.r3lab_core import DEFAULT_OFFSETS, build_trader, make_voucher_maps


voucher_maps = make_voucher_maps(
    default_side="both",
    default_width=6.0,
    default_size=0,
    default_take_edge=None,
    size_overrides={"VEV_4000": 16},
)

CONFIG = {
    "tte_candidates": [5.0, 6.0, 7.0, 8.0],
    "hydro": {
        "anchor": 10000.0,
        "micro_coef": 0.90,
        "mean_coef": 0.18,
        "ema_alpha": 0.08,
        "take_buy_edge": 2.0,
        "take_sell_edge": 2.0,
        "take_buy_edge_wide": 4.0,
        "take_sell_edge_wide": 4.0,
        "wide_position": 60,
        "flatten_trigger": 120,
        "flatten_size": 25,
        "quote_width": 2.0,
        "skew": 0.03,
        "quote_size": 24,
    },
    "velvet": {
        "enabled": True,
        "anchor": 5250.0,
        "micro_coef": 0.00,
        "ema_coef": 0.00,
        "ema_alpha": 0.10,
        "take_enabled": True,
        "take_buy_edge": 7.0,
        "take_sell_edge": 7.0,
        "quote_width": 100.0,
        "skew": 0.00,
        "quote_size": 0,
        "flatten_trigger": 40,
        "flatten_size": 20,
    },
    "vouchers": {
        "sigma": 0.01275,
        "offsets": DEFAULT_OFFSETS,
        "skew": 0.02,
        "flatten_trigger": 160,
        "flatten_size": 15,
        **voucher_maps,
    },
}

Trader = build_trader(CONFIG)
