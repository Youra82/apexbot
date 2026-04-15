"""
CANDLE SHAPE — Candlestick pattern analysis.

Estimates P(win) delta from the shape of the last candle:
  Strong body     → trend continuation → P(win) up
  Large opp. wick → reversal risk      → P(win) down
  Hammer / Star   → reversal signal    → P(win) up for the reversal direction
"""

import pandas as pd


# Platzhalter für neue Swingtrading-Strategie
