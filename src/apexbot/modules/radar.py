"""
RADAR — Regime Detection Module
Determines if the market is in a state worth trading.
Regimes: SLEEP | STALK | HUNT | RETREAT
"""

import pandas as pd
import numpy as np


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    tr = compute_atr(df, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / tr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / tr)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.rolling(period).mean().iloc[-1]


def compute_bb_width(df: pd.DataFrame, period: int = 20) -> float:
    close = df["close"]
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    width = ((upper - lower) / ma).iloc[-1]
    return width


def detect_regime(df: pd.DataFrame, config: dict, funding_rate: float = 0.0) -> str:
    """
    Returns one of: SLEEP, STALK, HUNT, RETREAT
    """
    cfg = config["radar"]

    atr = compute_atr(df)
    atr_normalized = (atr / df["close"]).iloc[-1]
    adx = compute_adx(df)
    bb_width = compute_bb_width(df)
    funding_ok = abs(funding_rate) >= cfg["funding_rate_threshold"]

    scores = {
        "atr": atr_normalized >= cfg["atr_multiplier_min"] * 0.001,
        "adx": adx >= cfg["adx_min"],
        "bb_width": bb_width >= cfg["bb_width_min"],
        "funding": funding_ok,
    }

    score = sum(scores.values())

    if score >= 4:
        return "HUNT"
    elif score >= 2:
        return "STALK"
    elif score == 1:
        return "SLEEP"
    else:
        return "SLEEP"
