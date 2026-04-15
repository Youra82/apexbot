"""
FUSION — APEXBOT v2 Professional Swing Trading Edge Engine

Strategy Philosophy:
  Trade WITH the trend, enter on PULLBACKS, confirm with VOLUME.

Entry Requirements — LONG:
  1. EMA21 > EMA50, price > EMA21      (trend aligned)
  2. EMA21 > EMA50 > EMA200 (bonus)   (full trend stack)
  3. RSI in 45–rsi_max range           (momentum healthy, not over-extended)
  4. Volume > vol_surge_mult × 20-bar avg  (smart money participation)
  5. Last closed candle: bullish body ≥ body_ratio_min
  6. Market structure: Higher High + Higher Low

SHORT = exact mirror of LONG.

Stop Loss  : ATR × atr_sl_mult below/above nearest swing low/high.
Take Profit: Nearest liquidity zone with R:R ≥ min_rr (fallback: ATR × min_rr).
"""

import numpy as np
import pandas as pd

from apexbot.modules.radar import compute_atr
from apexbot.modules.liquidity import find_liquidity_zones, nearest_tp_zone


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(window=period).mean()
    loss  = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs    = gain / loss.replace(0, 1e-10)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def _swing_points(df: pd.DataFrame, lookback: int = 5) -> tuple:
    """
    Pivot-based swing high/low detection.
    Returns (swing_highs, swing_lows) as lists of (bar_index, price) tuples.
    """
    highs = df['high'].values
    lows  = df['low'].values
    n     = len(df)
    swing_highs: list = []
    swing_lows:  list = []

    for i in range(lookback, n - lookback):
        window_h = highs[max(0, i - lookback): i + lookback + 1]
        window_l = lows[max(0, i - lookback): i + lookback + 1]
        if highs[i] >= max(window_h):
            swing_highs.append((i, float(highs[i])))
        if lows[i] <= min(window_l):
            swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


def _market_structure(swing_highs: list, swing_lows: list) -> str:
    """
    Classify market structure from recent pivot sequence.
    'bullish' = HH + HL  |  'bearish' = LH + LL  |  'neutral'
    """
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1][1] > swing_highs[-2][1]
        hl = swing_lows[-1][1]  > swing_lows[-2][1]
        lh = swing_highs[-1][1] < swing_highs[-2][1]
        ll = swing_lows[-1][1]  < swing_lows[-2][1]

        if hh and hl:
            return 'bullish'
        if lh and ll:
            return 'bearish'
    return 'neutral'


def _skip(reason: str = 'no_edge') -> dict:
    return {
        'mode':      'SKIP',
        'direction': 'none',
        'edge':      0.0,
        'p_win':     0.0,
        'rr':        0.0,
        'atr_sl':    0.0,
        'tp_price':  0.0,
        'sl_price':  0.0,
        'reason':    reason,
    }


# ── Full Edge Engine (live trading + backtesting) ─────────────────────────────

def compute_edge(df: pd.DataFrame, settings: dict) -> dict:
    """
    Full professional swing trading edge calculation.

    Scoring (max 10 pts):
      EMA stack bonus    : 1 pt
      RSI momentum zone  : 2 pt
      Volume surge       : 2 pt
      Candle quality     : 2 pt
      Market structure   : 2 pt
      Pullback quality   : 1 pt  (price near EMA21, not racing away)

    Direction gate: EMA21/EMA50 alignment required.
    Threshold gate: edge_score >= threshold (default 0.30).
    RR gate:        actual_rr >= min_rr after SL/TP placement.

    Returns full trade setup dict including sl_price and tp_price.
    """
    ecfg           = settings.get('edge', {})
    threshold      = ecfg.get('threshold',               0.30)
    min_rr         = ecfg.get('min_rr',                  1.50)
    atr_sl_mult    = ecfg.get('atr_sl_mult',             1.50)
    base_p_win     = ecfg.get('base_p_win',              0.47)
    vol_surge_mult = ecfg.get('volume_surge_multiplier', 1.50)
    rsi_min        = int(ecfg.get('rsi_momentum_min',    50))
    rsi_max        = int(ecfg.get('rsi_momentum_max',    75))
    body_min       = ecfg.get('body_ratio_min',          0.50)

    if len(df) < 60:
        return _skip('insufficient_data')

    close = df['close']
    vol   = df['volume']
    price = float(close.iloc[-1])

    # ── 1. EMA Alignment (required gate — no score, just direction) ──────────
    ef  = float(_ema(close, 21).iloc[-1])
    es  = float(_ema(close, 50).iloc[-1])
    span200 = min(200, len(df) // 2)
    et  = float(_ema(close, span200).iloc[-1])

    long_ok  = ef > es and price > ef
    short_ok = ef < es and price < ef

    if not long_ok and not short_ok:
        return _skip('ema_not_aligned')

    direction = 'long' if long_ok else 'short'
    score = 0.0
    max_s = 10.0

    # ── 2. Full EMA Stack Bonus (1 pt) ───────────────────────────────────────
    if (direction == 'long'  and ef > es > et) or \
       (direction == 'short' and ef < es < et):
        score += 1.0

    # ── 3. RSI Momentum Zone (2 pts) ─────────────────────────────────────────
    rsi = _rsi(close, 14)
    if direction == 'long':
        rsi_ok = rsi_min <= rsi <= rsi_max
    else:
        inv_min = 100 - rsi_max
        inv_max = 100 - rsi_min
        rsi_ok  = inv_min <= rsi <= inv_max
    if rsi_ok:
        score += 2.0

    # ── 4. Volume Surge (2 pts) ───────────────────────────────────────────────
    avg_vol  = float(vol.rolling(20).mean().iloc[-1])
    curr_vol = float(vol.iloc[-1])
    if avg_vol > 0 and curr_vol / avg_vol >= vol_surge_mult:
        score += 2.0

    # ── 5. Candlestick Quality on Last Closed Candle (2 pts) ─────────────────
    candle  = df.iloc[-2]
    c_body  = abs(float(candle['close']) - float(candle['open']))
    c_range = float(candle['high']) - float(candle['low'])
    br      = c_body / c_range if c_range > 0 else 0.0
    is_bull = candle['close'] > candle['open']
    candle_ok = br >= body_min and (
        (direction == 'long'  and is_bull) or
        (direction == 'short' and not is_bull)
    )
    if candle_ok:
        score += 2.0

    # ── 6. Market Structure (2 pts) ───────────────────────────────────────────
    swing_h, swing_l = _swing_points(df.tail(60), lookback=3)
    structure = _market_structure(swing_h, swing_l)
    if (direction == 'long'  and structure == 'bullish') or \
       (direction == 'short' and structure == 'bearish'):
        score += 2.0

    # ── 7. Pullback Quality Bonus (1 pt) ──────────────────────────────────────
    # Price should be close to EMA21 (pullback entry), not chasing a breakout
    dist_pct = abs(price - ef) / ef if ef > 0 else 1.0
    if dist_pct < 0.015:          # within 1.5% of EMA21
        score += 1.0

    edge_score = score / max_s

    if edge_score < threshold:
        return _skip(f'edge_low({edge_score:.2f}<{threshold:.2f})')

    # ── 8. Stop Loss at Swing Structure + ATR Buffer ──────────────────────────
    atr_val = float(compute_atr(df, 14).iloc[-1])
    atr_sl  = atr_val * atr_sl_mult

    if direction == 'long':
        sl_price = price - atr_sl
        # Tighten SL if swing low is closer than ATR distance
        if swing_l:
            ref = float(swing_l[-1][1]) - atr_val * 0.2
            sl_price = min(sl_price, ref)
        sl_price = max(sl_price, price * 0.80)   # hard cap: max 20% loss
        atr_sl   = price - sl_price
    else:
        sl_price = price + atr_sl
        if swing_h:
            ref = float(swing_h[-1][1]) + atr_val * 0.2
            sl_price = max(sl_price, ref)
        sl_price = min(sl_price, price * 1.20)
        atr_sl   = sl_price - price

    if atr_sl <= 0:
        return _skip('zero_sl')

    # ── 9. Take Profit: Nearest Liquidity Zone ────────────────────────────────
    try:
        zones    = find_liquidity_zones(df)
        tp_price = nearest_tp_zone(direction, price, zones, min_rr, atr_sl)
    except Exception:
        tp_price = (price + atr_sl * min_rr) if direction == 'long' \
                   else (price - atr_sl * min_rr)

    actual_rr = abs(tp_price - price) / atr_sl if atr_sl > 0 else 0.0

    if actual_rr < min_rr:
        return _skip(f'rr_low({actual_rr:.2f}<{min_rr:.2f})')

    # ── 10. Win Probability Estimate ─────────────────────────────────────────
    # Scales linearly: base ± 0.20 across full edge range
    p_win = float(np.clip(base_p_win + (edge_score - 0.5) * 0.20, 0.30, 0.75))

    return {
        'mode':      'TRADE',
        'direction': direction,
        'edge':      round(edge_score, 3),
        'p_win':     round(p_win, 3),
        'rr':        round(actual_rr, 2),
        'atr_sl':    round(float(atr_sl), 8),
        'tp_price':  round(float(tp_price), 6),
        'sl_price':  round(float(sl_price), 6),
        'reason':    f'{direction}_e={edge_score:.2f}_rr={actual_rr:.2f}',
    }


# ── Fast Edge Engine (Optuna optimizer) ───────────────────────────────────────

def compute_edge_fast(df: pd.DataFrame, settings: dict) -> dict:
    """
    Stripped-down edge calculation for the optimizer (no liquidity zones,
    no EMA200 stack, no swing structure).  Focuses on the three high-signal
    components so Optuna can sweep thousands of trials quickly.
    """
    ecfg           = settings.get('edge', {})
    threshold      = ecfg.get('threshold',               0.30)
    min_rr         = ecfg.get('min_rr',                  1.50)
    atr_sl_mult    = ecfg.get('atr_sl_mult',             1.50)
    base_p_win     = ecfg.get('base_p_win',              0.47)
    vol_surge_mult = ecfg.get('volume_surge_multiplier', 1.50)
    rsi_min        = int(ecfg.get('rsi_momentum_min',    50))
    rsi_max        = int(ecfg.get('rsi_momentum_max',    75))
    body_min       = ecfg.get('body_ratio_min',          0.50)

    SKIP = {
        'mode': 'SKIP', 'direction': 'none', 'edge': 0.0,
        'p_win': 0.0, 'rr': min_rr, 'atr_sl': 0.0,
        'tp_price': 0.0, 'sl_price': 0.0,
    }

    if len(df) < 60:
        return SKIP

    close = df['close']
    vol   = df['volume']
    price = float(close.iloc[-1])

    ef = float(_ema(close, 21).iloc[-1])
    es = float(_ema(close, 50).iloc[-1])

    long_ok  = ef > es and price > ef
    short_ok = ef < es and price < ef

    if not long_ok and not short_ok:
        return SKIP

    direction = 'long' if long_ok else 'short'

    # RSI
    rsi = _rsi(close, 14)
    if direction == 'long':
        rsi_ok = rsi_min <= rsi <= rsi_max
    else:
        inv_min, inv_max = 100 - rsi_max, 100 - rsi_min
        rsi_ok = inv_min <= rsi <= inv_max

    # Volume
    avg_vol  = float(vol.rolling(20).mean().iloc[-1])
    curr_vol = float(vol.iloc[-1])
    vol_ok   = avg_vol > 0 and curr_vol / avg_vol >= vol_surge_mult

    # Candle
    candle  = df.iloc[-2]
    c_body  = abs(float(candle['close']) - float(candle['open']))
    c_range = float(candle['high']) - float(candle['low'])
    br      = c_body / c_range if c_range > 0 else 0.0
    is_bull = candle['close'] > candle['open']
    candle_ok = br >= body_min and (
        (direction == 'long' and is_bull) or (direction == 'short' and not is_bull)
    )

    score      = 2.0 * rsi_ok + 2.0 * vol_ok + 2.0 * candle_ok
    edge_score = score / 6.0

    if edge_score < threshold:
        return SKIP

    atr_val  = float(compute_atr(df, 14).iloc[-1])
    atr_sl   = atr_val * atr_sl_mult
    sl_price = (price - atr_sl) if direction == 'long' else (price + atr_sl)
    tp_price = (price + atr_sl * min_rr) if direction == 'long' \
               else (price - atr_sl * min_rr)

    p_win = float(np.clip(base_p_win + (edge_score - 0.5) * 0.20, 0.30, 0.75))

    return {
        'mode':      'TRADE',
        'direction': direction,
        'edge':      round(edge_score, 3),
        'p_win':     round(p_win, 3),
        'rr':        round(min_rr, 2),
        'atr_sl':    round(float(atr_sl), 8),
        'tp_price':  round(float(tp_price), 6),
        'sl_price':  round(float(sl_price), 6),
    }
