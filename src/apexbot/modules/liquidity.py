"""
LIQUIDITY — Volume Profile based TP Zone Detection

Computes a rolling volume profile from recent candles to identify
high-volume price clusters (liquidity nodes) that act as natural TP targets.
"""

import numpy as np
import pandas as pd


def compute_volume_profile(df: pd.DataFrame, n_candles: int = 100,
                           n_bins: int = 40) -> tuple:
    """
    Distributes each candle's volume proportionally across its price range.
    Returns (bin_centers, bin_volumes) as numpy arrays.
    """
    window = df.tail(n_candles)
    lo_all = float(window['low'].min())
    hi_all = float(window['high'].max())

    if hi_all <= lo_all:
        mid = (lo_all + hi_all) / 2
        return np.array([mid]), np.array([float(window['volume'].sum())])

    edges       = np.linspace(lo_all, hi_all, n_bins + 1)
    bin_volumes = np.zeros(n_bins)

    for _, row in window.iterrows():
        lo, hi, vol = float(row['low']), float(row['high']), float(row['volume'])
        if hi <= lo:
            hi = lo * 1.0001
        i_lo = max(0,      int(np.searchsorted(edges, lo, side='left'))  - 1)
        i_hi = min(n_bins, int(np.searchsorted(edges, hi, side='right')))
        span = i_hi - i_lo
        if span > 0:
            bin_volumes[i_lo:i_hi] += vol / span

    bin_centers = (edges[:-1] + edges[1:]) / 2
    return bin_centers, bin_volumes


def find_liquidity_zones(df: pd.DataFrame, n_candles: int = 100,
                         n_bins: int = 40, top_n: int = 5) -> list:
    """
    Returns up to top_n highest-volume price zones sorted ascending.
    Nearby zones within 0.5% are merged into one.
    """
    centers, volumes = compute_volume_profile(df, n_candles, n_bins)
    if len(centers) == 0:
        return []

    # Local-max peak detection
    peaks: list[tuple[float, float]] = []
    for i in range(1, len(volumes) - 1):
        if volumes[i] >= volumes[i - 1] and volumes[i] >= volumes[i + 1]:
            peaks.append((float(volumes[i]), float(centers[i])))

    if not peaks:
        top_idx = np.argsort(volumes)[::-1][:top_n]
        peaks = [(float(volumes[i]), float(centers[i])) for i in top_idx]

    # Sort by volume desc, take top candidates, then sort by price
    peaks.sort(key=lambda x: -x[0])
    top_prices = sorted(p for _, p in peaks[: top_n * 2])

    # Merge zones within 0.5% of each other
    merged: list[float] = []
    for p in top_prices:
        if not merged or abs(p - merged[-1]) / merged[-1] > 0.005:
            merged.append(p)

    return merged[:top_n]


def nearest_tp_zone(direction: str, entry_price: float, zones: list,
                    min_rr: float, atr_sl: float) -> float:
    """
    Returns the nearest liquidity zone that gives at least min_rr R:R.
    Falls back to entry ± atr_sl * min_rr if no suitable zone found.
    """
    min_tp_dist = atr_sl * min_rr
    if direction == 'long':
        candidates = [z for z in zones if z > entry_price + min_tp_dist]
        return min(candidates) if candidates else entry_price + min_tp_dist
    else:
        candidates = [z for z in zones if z < entry_price - min_tp_dist]
        return max(candidates) if candidates else entry_price - min_tp_dist
