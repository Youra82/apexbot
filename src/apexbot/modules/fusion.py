"""
FUSION — Multi-Signal Score Engine
5 independent signals must align. Score 5/5 = FULL SEND, 4/5 = HALF SEND.
"""

import pandas as pd
import numpy as np


def signal_bb_breakout(df: pd.DataFrame) -> tuple[int, str]:
    """Signal A: Price breaks above/below Bollinger Band"""
    close = df["close"]
    ma = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = ma + 2 * std
    lower = ma - 2 * std

    last_close = close.iloc[-1]
    if last_close > upper.iloc[-1]:
        return 1, "long"
    elif last_close < lower.iloc[-1]:
        return 1, "short"
    return 0, "none"


def signal_volume_surge(df: pd.DataFrame, multiplier: float = 2.0) -> int:
    """Signal B: Volume > N x moving average"""
    vol = df["volume"]
    vol_ma = vol.rolling(20).mean()
    if vol.iloc[-1] > multiplier * vol_ma.iloc[-1]:
        return 1
    return 0


def signal_candle_body(df: pd.DataFrame, min_ratio: float = 0.60) -> tuple[int, str]:
    """Signal D: Clean candle body (no big wicks)"""
    last = df.iloc[-1]
    total_range = last["high"] - last["low"]
    if total_range == 0:
        return 0, "none"
    body = abs(last["close"] - last["open"])
    ratio = body / total_range
    if ratio >= min_ratio:
        direction = "long" if last["close"] > last["open"] else "short"
        return 1, direction
    return 0, "none"


def signal_rsi_momentum(df: pd.DataFrame, period: int = 14, min_val: float = 50, max_val: float = 75) -> tuple[int, str]:
    """Signal E: RSI in acceleration zone (not overbought/oversold, but moving)"""
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]

    if min_val <= val <= max_val:
        return 1, "long"
    elif (100 - max_val) <= val <= (100 - min_val):
        return 1, "short"
    return 0, "none"


def signal_ema_trend(df: pd.DataFrame) -> tuple[int, str]:
    """Signal C: Price above EMA20 and EMA50 aligned"""
    close = df["close"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()

    if ema20.iloc[-1] > ema50.iloc[-1] and close.iloc[-1] > ema20.iloc[-1]:
        return 1, "long"
    elif ema20.iloc[-1] < ema50.iloc[-1] and close.iloc[-1] < ema20.iloc[-1]:
        return 1, "short"
    return 0, "none"


def compute_fusion_score(df: pd.DataFrame, config: dict, weights: dict = None) -> dict:
    """
    Returns score (0-5), direction, send_mode (FULL/HALF/SKIP), and weighted_score.
    weights: optional dict mapping signal names to float weights.
             If None, all weights default to 1.0.
    """
    cfg = config["fusion"]

    sa, dir_a = signal_bb_breakout(df)
    sb = signal_volume_surge(df, cfg["volume_surge_multiplier"])
    sc, dir_c = signal_ema_trend(df)
    sd, dir_d = signal_candle_body(df, cfg["body_ratio_min"])
    se, dir_e = signal_rsi_momentum(df, min_val=cfg["rsi_momentum_min"], max_val=cfg["rsi_momentum_max"])

    directions = [d for d in [dir_a, dir_c, dir_d, dir_e] if d != "none"]
    if not directions:
        return {"score": 0, "direction": "none", "mode": "SKIP", "signals": {}, "weighted_score": 0.0}

    from collections import Counter
    direction = Counter(directions).most_common(1)[0][0]

    score = sa + sb + sc + sd + se

    # Default weights = 1.0 for each signal
    if weights is None:
        weights = {"bb": 1.0, "volume": 1.0, "ema": 1.0, "body": 1.0, "rsi": 1.0}

    signal_values = {"bb": sa, "volume": sb, "ema": sc, "body": sd, "rsi": se}
    weighted_score = sum(weights.get(sig, 1.0) * val for sig, val in signal_values.items())

    if score >= cfg["min_score_full_send"]:
        mode = "FULL_SEND"
    elif score >= cfg["min_score_half_send"]:
        mode = "HALF_SEND"
    else:
        mode = "SKIP"

    return {
        "score": score,
        "direction": direction,
        "mode": mode,
        "signals": signal_values,
        "weighted_score": weighted_score,
    }
