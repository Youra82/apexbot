# tests/test_modules.py
"""
Unit-Tests fuer RADAR, FUSION und COMPOUNDER.
Kein echter API-Aufruf benoetigt.
"""

import sys
import os
import json
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.modules.radar import detect_regime
from apexbot.modules.fusion import compute_fusion_score
from apexbot.modules.compounder import get_position_size


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_trending_df(n: int = 100, direction: str = 'up') -> pd.DataFrame:
    """Erzeugt einen trendigen DataFrame fuer RADAR/FUSION Tests."""
    np.random.seed(42)
    prices = 50000 + np.cumsum(np.random.randn(n) * 100)
    if direction == 'up':
        prices = prices + np.linspace(0, 3000, n)
    elif direction == 'down':
        prices = prices - np.linspace(0, 3000, n)

    df = pd.DataFrame({
        'open':   prices * 0.999,
        'high':   prices * 1.003,
        'low':    prices * 0.997,
        'close':  prices,
        'volume': np.random.uniform(500, 2000, n),
    })
    return df


def load_settings() -> dict:
    with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
        return json.load(f)


# ── RADAR Tests ───────────────────────────────────────────────────────────────

def test_radar_returns_valid_regime():
    df       = make_trending_df(100, 'up')
    settings = load_settings()
    regime   = detect_regime(df, settings)
    assert regime in ['SLEEP', 'STALK', 'HUNT', 'RETREAT']


def test_radar_flat_market_not_hunt():
    """Ein flacher Markt sollte kein HUNT-Regime haben."""
    np.random.seed(0)
    prices = 50000 + np.random.randn(100) * 5  # sehr flach
    df = pd.DataFrame({
        'open':  prices * 0.9999,
        'high':  prices * 1.0001,
        'low':   prices * 0.9999,
        'close': prices,
        'volume': np.ones(100) * 100,
    })
    settings = load_settings()
    regime   = detect_regime(df, settings)
    assert regime != 'HUNT', f"Flacher Markt sollte kein HUNT sein, war: {regime}"


# ── FUSION Tests ──────────────────────────────────────────────────────────────

def test_fusion_returns_valid_output():
    df       = make_trending_df(100, 'up')
    settings = load_settings()
    result   = compute_fusion_score(df, settings)

    assert 'score'     in result
    assert 'direction' in result
    assert 'mode'      in result
    assert result['mode']      in ['FULL_SEND', 'HALF_SEND', 'SKIP']
    assert result['direction'] in ['LONG', 'SHORT', 'NONE']
    assert 0 <= result['score'] <= 5


def test_fusion_score_range():
    df       = make_trending_df(100, 'up')
    settings = load_settings()
    result   = compute_fusion_score(df, settings)
    assert isinstance(result['score'], int)
    assert result['score'] >= 0


# ── COMPOUNDER Tests ──────────────────────────────────────────────────────────

def test_compounder_full_send_returns_full_capital():
    settings = load_settings()
    state    = {'current_capital_usdt': 100.0}
    size     = get_position_size(state, 'FULL_SEND', settings)
    assert size == 100.0


def test_compounder_half_send_returns_half():
    settings = load_settings()
    state    = {'current_capital_usdt': 200.0}
    size     = get_position_size(state, 'HALF_SEND', settings)
    assert size == 100.0


def test_compounder_skip_returns_zero():
    settings = load_settings()
    state    = {'current_capital_usdt': 100.0}
    size     = get_position_size(state, 'SKIP', settings)
    assert size == 0.0
