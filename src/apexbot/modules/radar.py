"""
RADAR — Regime Detection Module
Determines if the market is in a state worth trading.
Regimes: SLEEP | STALK | HUNT | RETREAT
"""

import pandas as pd
import numpy as np


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> str:
    """
    Computes Supertrend indicator (Pine Script equivalent).
    Returns 'long' if price is above supertrend, 'short' if below.
    """
    high = df["high"]
    low  = df["low"]
    close = df["close"]

    # Wilder ATR
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    direction   = pd.Series(index=df.index, dtype=int)

    for i in range(1, len(df)):
        # Final upper band: only moves down (bearish side)
        if basic_upper.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]

        # Final lower band: only moves up (bullish side)
        if basic_lower.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        # Direction: -1 = bullish (long), 1 = bearish (short)
        prev_dir = direction.iloc[i - 1] if i > 1 else 1
        if close.iloc[i] > final_upper.iloc[i - 1]:
            direction.iloc[i] = -1
        elif close.iloc[i] < final_lower.iloc[i - 1]:
            direction.iloc[i] = 1
        else:
            direction.iloc[i] = prev_dir

    last_dir = direction.iloc[-1]
    return 'long' if last_dir == -1 else 'short'


_HIGHER_TF_MAP = {
    '1m':  '5m',
    '3m':  '15m',
    '5m':  '15m',
    '15m': '1h',
    '30m': '2h',
    '1h':  '4h',
    '2h':  '8h',
    '4h':  '1d',
    '6h':  '1d',
    '12h': '3d',
    '1d':  '1w',
    '1w':  '1M',
}


def get_higher_timeframe(timeframe: str) -> str:
    """Returns the next higher timeframe for Supertrend filtering."""
    return _HIGHER_TF_MAP.get(timeframe, '4h')


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
