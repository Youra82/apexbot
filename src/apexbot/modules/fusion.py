"""
FUSION — APEXBOT v2 Edge Engine
E = P(win) × RR − P(loss) × 1.0

P(win) estimated from: volume surge, EMA alignment, RSI momentum, candle shape.
TP targeting via liquidity zones (compute_edge) or ATR×RR (compute_edge_fast).
"""

import pandas as pd
import numpy as np
from collections import Counter


def _compute_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return float((100 - (100 / (1 + rs))).iloc[-1])


def _p_win_from_signals(df: pd.DataFrame, cfg: dict) -> tuple[float, str]:
    """
    Shared P(win) estimation used by both edge functions.
    Returns (p_win, direction).
    """
    from apexbot.modules.candle_shape import analyze_candle_shape

    base_p       = cfg.get('base_p_win',              0.47)
    vol_mult_thr = cfg.get('volume_surge_multiplier', 1.5)
    rsi_min      = cfg.get('rsi_momentum_min',        50)
    rsi_max      = cfg.get('rsi_momentum_max',        75)

    p_win = base_p
    close = df['close']

    # Volume surge
    vol    = df['volume']
    vol_ma = vol.rolling(20).mean().iloc[-1]
    if vol_ma > 0 and vol.iloc[-1] >= vol_mult_thr * vol_ma:
        p_win += 0.05

    # EMA alignment
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema_long  = ema20.iloc[-1] > ema50.iloc[-1] and close.iloc[-1] > ema20.iloc[-1]
    ema_short = ema20.iloc[-1] < ema50.iloc[-1] and close.iloc[-1] < ema20.iloc[-1]
    ema_dir   = 'long' if ema_long else ('short' if ema_short else 'none')
    if ema_dir != 'none':
        p_win += 0.03

    # RSI momentum
    rsi     = _compute_rsi(close)
    rsi_dir = ('long'  if rsi_min <= rsi <= rsi_max
               else ('short' if (100 - rsi_max) <= rsi <= (100 - rsi_min)
               else 'none'))
    if rsi_dir != 'none':
        p_win += 0.04

    # Candle shape
    shape  = analyze_candle_shape(df)
    p_win += shape['p_win_delta']

    # Direction consensus
    dirs = [d for d in [ema_dir, rsi_dir, shape['direction']] if d != 'none']
    direction = Counter(dirs).most_common(1)[0][0] if dirs else 'none'

    return round(p_win, 4), direction


def compute_edge_fast(df: pd.DataFrame, config: dict) -> dict:
    """
    Fast edge estimation for the optimizer (no liquidity zone lookup).
    TP = entry ± ATR × atr_sl_mult × min_rr  (deterministic, O(1) per candle).

    Returns: {edge, direction, p_win, rr, atr_sl, mode}
    """
    from apexbot.modules.radar import compute_atr

    cfg            = config.get('edge', {})
    edge_threshold = cfg.get('threshold',     0.3)
    min_rr         = cfg.get('min_rr',        1.5)
    atr_sl_mult    = cfg.get('atr_sl_mult',   1.5)

    p_win, direction = _p_win_from_signals(df, cfg)

    if direction == 'none':
        return {'edge': 0.0, 'direction': 'none', 'p_win': p_win,
                'rr': min_rr, 'atr_sl': 0.0, 'mode': 'SKIP'}

    atr_val = float(compute_atr(df).iloc[-1])
    atr_sl  = atr_val * atr_sl_mult
    rr      = min_rr

    edge = p_win * rr - (1.0 - p_win) * 1.0
    mode = 'TRADE' if edge >= edge_threshold else 'SKIP'

    return {
        'edge':      round(edge, 4),
        'direction': direction,
        'p_win':     p_win,
        'rr':        round(rr, 3),
        'atr_sl':    atr_sl,
        'mode':      mode,
    }


def compute_edge(df: pd.DataFrame, config: dict) -> dict:
    """
    Full APEXBOT v2 Edge Engine with liquidity zone TP targeting.
    E = P(win) × RR − P(loss) × 1.0

    P(win) is built from independent signals:
      base 0.47 + volume surge + EMA alignment + RSI momentum + candle shape
    TP = nearest liquidity zone with RR >= min_rr.

    Returns: {edge, direction, p_win, rr, atr_sl, atr_sl_pct, tp_price, mode, components}
    """
    from apexbot.modules.radar import compute_atr
    from apexbot.modules.candle_shape import analyze_candle_shape
    from apexbot.modules.liquidity import find_liquidity_zones, nearest_tp_zone

    cfg            = config.get('edge', {})
    edge_threshold = cfg.get('threshold',     0.3)
    min_rr         = cfg.get('min_rr',        1.5)
    atr_sl_mult    = cfg.get('atr_sl_mult',   1.5)
    vol_mult_thr   = cfg.get('volume_surge_multiplier', 1.5)
    rsi_min        = cfg.get('rsi_momentum_min', 50)
    rsi_max        = cfg.get('rsi_momentum_max', 75)
    base_p         = cfg.get('base_p_win',    0.47)

    p_win      = base_p
    components = {}
    close      = df['close']

    # Volume surge
    vol    = df['volume']
    vol_ma = vol.rolling(20).mean().iloc[-1]
    vol_ratio = vol.iloc[-1] / vol_ma if vol_ma > 0 else 1.0
    if vol_ratio >= vol_mult_thr:
        p_win += 0.05
    components['volume_ratio'] = round(float(vol_ratio), 3)

    # EMA alignment
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema_long  = ema20.iloc[-1] > ema50.iloc[-1] and close.iloc[-1] > ema20.iloc[-1]
    ema_short = ema20.iloc[-1] < ema50.iloc[-1] and close.iloc[-1] < ema20.iloc[-1]
    ema_dir   = 'long' if ema_long else ('short' if ema_short else 'none')
    if ema_dir != 'none':
        p_win += 0.03
    components['ema_dir'] = ema_dir

    # RSI momentum
    rsi     = _compute_rsi(close)
    rsi_dir = ('long'  if rsi_min <= rsi <= rsi_max
               else ('short' if (100 - rsi_max) <= rsi <= (100 - rsi_min)
               else 'none'))
    if rsi_dir != 'none':
        p_win += 0.04
    components['rsi'] = round(rsi, 1)

    # Candle shape
    from apexbot.modules.candle_shape import analyze_candle_shape
    shape = analyze_candle_shape(df)
    p_win += shape['p_win_delta']
    components['shape'] = shape

    # Direction consensus
    dirs = [d for d in [ema_dir, rsi_dir, shape['direction']] if d != 'none']
    if not dirs:
        return {'edge': 0.0, 'direction': 'none', 'p_win': round(p_win, 4),
                'rr': 0.0, 'atr_sl': 0.0, 'atr_sl_pct': 0.0, 'tp_price': 0.0,
                'mode': 'SKIP', 'components': components}

    direction = Counter(dirs).most_common(1)[0][0]

    # ATR-based SL
    atr_val    = float(compute_atr(df).iloc[-1])
    ep         = float(close.iloc[-1])
    atr_sl     = atr_val * atr_sl_mult
    atr_sl_pct = atr_sl / ep * 100 if ep > 0 else 0.0

    # Liquidity zone TP
    zones    = find_liquidity_zones(df)
    tp_price = nearest_tp_zone(direction, ep, zones, min_rr, atr_sl)
    tp_dist  = abs(tp_price - ep)
    rr       = max(min_rr, tp_dist / atr_sl if atr_sl > 0 else min_rr)

    edge = p_win * rr - (1.0 - p_win) * 1.0
    mode = 'TRADE' if edge >= edge_threshold else 'SKIP'

    return {
        'edge':       round(edge, 4),
        'direction':  direction,
        'p_win':      round(p_win, 4),
        'rr':         round(rr, 3),
        'atr_sl':     round(atr_sl, 6),
        'atr_sl_pct': round(atr_sl_pct, 4),
        'tp_price':   round(tp_price, 6),
        'mode':       mode,
        'components': components,
    }


