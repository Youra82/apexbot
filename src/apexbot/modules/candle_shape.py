"""
CANDLE SHAPE — Candlestick pattern analysis.

Estimates P(win) delta from the shape of the last candle:
  Strong body     → trend continuation → P(win) up
  Large opp. wick → reversal risk      → P(win) down
  Hammer / Star   → reversal signal    → P(win) up for the reversal direction
"""

import pandas as pd


def analyze_candle_shape(df: pd.DataFrame) -> dict:
    """
    Analyzes the last candle for directional bias and P(win) contribution.

    Returns:
      direction        : 'long' | 'short' | 'none'
      p_win_delta      : float  (add to base P(win))
      body_ratio       : float  [0, 1]
      upper_wick_ratio : float  [0, 1]
      lower_wick_ratio : float  [0, 1]
      signal           : str    (description tag)
    """
    last = df.iloc[-1]
    o = float(last['open'])
    h = float(last['high'])
    l = float(last['low'])
    c = float(last['close'])

    total_range = h - l
    if total_range < 1e-10:
        return {
            'direction': 'none', 'p_win_delta': 0.0, 'body_ratio': 0.0,
            'upper_wick_ratio': 0.0, 'lower_wick_ratio': 0.0, 'signal': 'doji',
        }

    body             = abs(c - o)
    body_ratio       = body / total_range
    upper_wick       = h - max(o, c)
    lower_wick       = min(o, c) - l
    upper_wick_ratio = upper_wick / total_range
    lower_wick_ratio = lower_wick / total_range
    is_bullish       = c >= o

    # ── Hammer (bullish reversal) ─────────────────────────────────────────
    if lower_wick_ratio > 0.55 and body_ratio < 0.25:
        return {
            'direction': 'long', 'p_win_delta': 0.04,
            'body_ratio': round(body_ratio, 4),
            'upper_wick_ratio': round(upper_wick_ratio, 4),
            'lower_wick_ratio': round(lower_wick_ratio, 4),
            'signal': 'hammer',
        }

    # ── Shooting star (bearish reversal) ─────────────────────────────────
    if upper_wick_ratio > 0.55 and body_ratio < 0.25:
        return {
            'direction': 'short', 'p_win_delta': 0.04,
            'body_ratio': round(body_ratio, 4),
            'upper_wick_ratio': round(upper_wick_ratio, 4),
            'lower_wick_ratio': round(lower_wick_ratio, 4),
            'signal': 'shooting_star',
        }

    direction   = 'long' if is_bullish else 'short'
    p_win_delta = 0.0

    if body_ratio >= 0.60:
        p_win_delta += 0.06
        signal = 'strong_body'
    elif body_ratio >= 0.40:
        p_win_delta += 0.02
        signal = 'moderate_body'
    else:
        p_win_delta -= 0.03
        signal    = 'weak_body'
        direction = 'none'

    # Opposing wick — reversal risk
    if is_bullish and upper_wick_ratio > 0.35:
        p_win_delta -= 0.05
        signal += '+upper_wick'
    elif not is_bullish and lower_wick_ratio > 0.35:
        p_win_delta -= 0.05
        signal += '+lower_wick'

    return {
        'direction':       direction,
        'p_win_delta':     round(p_win_delta, 4),
        'body_ratio':      round(body_ratio, 4),
        'upper_wick_ratio': round(upper_wick_ratio, 4),
        'lower_wick_ratio': round(lower_wick_ratio, 4),
        'signal':          signal,
    }
