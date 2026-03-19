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


def compute_hurst(close: pd.Series, lags: int = 20) -> float:
    """
    Hurst-Exponent via R/S-Analyse.
    H > 0.5 : persistent / trending  → Momentum-Strategien profitieren
    H < 0.5 : anti-persistent / mean-reverting
    H ≈ 0.5 : random walk → nicht handeln
    Benötigt mindestens 2*lags Datenpunkte.
    """
    if len(close) < lags * 2:
        return 0.5

    prices = close.values[-lags * 2:]
    tau    = []
    for lag in range(2, lags):
        n_chunks = len(prices) // lag
        if n_chunks < 2:
            continue
        chunks = prices[:n_chunks * lag].reshape(n_chunks, lag)
        ranges    = np.ptp(chunks, axis=1)
        stds      = np.std(chunks, axis=1)
        stds_safe = np.where(stds > 1e-10, stds, 1.0)   # Division durch 0 vermeiden
        rs        = np.where(stds > 1e-10, ranges / stds_safe, 0.0)
        valid  = rs[rs > 0]
        if len(valid):
            tau.append(float(valid.mean()))

    if len(tau) < 2:
        return 0.5

    lags_used = list(range(2, 2 + len(tau)))
    try:
        poly = np.polyfit(np.log(lags_used), np.log(np.maximum(tau, 1e-10)), 1)
        return float(np.clip(poly[0], 0.0, 1.0))
    except Exception:
        return 0.5


def compute_entropy(close: pd.Series, n: int = 20, bins: int = 10) -> float:
    """
    Shannon-Entropie der letzten n Log-Returns, normalisiert auf [0, 1].
    0 = maximale Ordnung (Ausbruch wahrscheinlich) → handeln
    1 = maximales Chaos → meiden
    """
    if len(close) < n + 1:
        return 1.0
    prices = close.values[-(n + 1):]
    returns = np.diff(np.log(np.maximum(prices, 1e-10)))
    counts, _ = np.histogram(returns, bins=bins)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    entropy = -np.sum(probs * np.log(probs))
    max_entropy = np.log(bins)
    return float(entropy / max_entropy) if max_entropy > 0 else 1.0


def compute_pair_score(df: pd.DataFrame) -> float:
    """
    Vorhersagbarkeits-Score fuer Pair-Turnier.
    Hoch = persistent (Hurst) + geordnet (niedrige Entropie).
    """
    h = compute_hurst(df['close'])
    e = compute_entropy(df['close'])
    return round(h * (1.0 - e), 4)


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

    scores = {
        "atr":      atr_normalized >= cfg["atr_multiplier_min"] * 0.001,
        "adx":      adx >= cfg["adx_min"],
        "bb_width": bb_width >= cfg["bb_width_min"],
    }

    # Funding Rate nur mitzählen wenn tatsächlich verfügbar (live).
    if funding_rate != 0.0:
        scores["funding"] = abs(funding_rate) >= cfg["funding_rate_threshold"]

    # Hurst Exponent — optional, aktiv wenn hurst_min > 0 in radar-Config.
    # Filtert Random-Walk-Phasen heraus: nur handeln wenn Markt persistent ist.
    hurst_min = cfg.get("hurst_min", 0.0)
    if hurst_min > 0:
        h = compute_hurst(df["close"])
        scores["hurst"] = h >= hurst_min

    # Entropie-Filter — aktiv wenn entropy_max > 0.
    # Nur handeln wenn Markt geordnet ist (niedrige Entropie = Ruhe vor dem Sturm).
    entropy_max = cfg.get("entropy_max", 0.0)
    if entropy_max > 0:
        ent = compute_entropy(df["close"])
        scores["entropy"] = ent <= entropy_max

    score     = sum(scores.values())
    available = len(scores)  # 3 im Backtest, 4 im Live-Betrieb

    if score >= available:
        return "HUNT"
    elif score >= available - 1:
        return "STALK"
    elif score == 1:
        return "SLEEP"
    else:
        return "SLEEP"
