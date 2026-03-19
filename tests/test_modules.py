# tests/test_modules.py
"""
Unit-Tests fuer RADAR, FUSION, COMPOUNDER, LEARNER und SUPERTREND.
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

from apexbot.modules.radar import detect_regime, compute_supertrend
from apexbot.modules.fusion import compute_fusion_score
from apexbot.modules.compounder import get_position_size
from apexbot.modules.learner import load_signal_weights, rl_should_trade


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

    assert 'score'          in result
    assert 'direction'      in result
    assert 'mode'           in result
    assert 'weighted_score' in result
    assert result['mode']      in ['FULL_SEND', 'HALF_SEND', 'SKIP']
    assert result['direction'] in ['long', 'short', 'none']
    assert 0 <= result['score'] <= 5


def test_fusion_score_range():
    df       = make_trending_df(100, 'up')
    settings = load_settings()
    result   = compute_fusion_score(df, settings)
    assert isinstance(result['score'], int)
    assert result['score'] >= 0


def test_fusion_direction_lowercase():
    """Direction must be lowercase: 'long', 'short', or 'none'."""
    df       = make_trending_df(100, 'up')
    settings = load_settings()
    result   = compute_fusion_score(df, settings)
    assert result['direction'] in ['long', 'short', 'none']


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


# ── SUPERTREND Tests ──────────────────────────────────────────────────────────

def test_supertrend_returns_valid_direction():
    """Supertrend must return 'long' or 'short' on a trending df."""
    df     = make_trending_df(100, 'up')
    result = compute_supertrend(df, period=10, multiplier=3.0)
    assert result in ['long', 'short'], f"Expected 'long' or 'short', got: {result}"


# ── LEARNER Tests ─────────────────────────────────────────────────────────────

def test_learner_signal_weights_default():
    """load_signal_weights returns dict with 5 keys all == 1.0 when no file exists."""
    import tempfile
    from unittest.mock import patch
    from pathlib import Path

    # Point WEIGHTS_PATH to a non-existent temp path
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "signal_weights.json"
        import apexbot.modules.learner as learner_mod
        original = learner_mod.WEIGHTS_PATH
        learner_mod.WEIGHTS_PATH = fake_path
        try:
            weights = load_signal_weights()
        finally:
            learner_mod.WEIGHTS_PATH = original

    assert isinstance(weights, dict)
    assert len(weights) == 5
    for sig, val in weights.items():
        assert val == 1.0, f"Expected weight 1.0 for {sig}, got {val}"


def test_rl_no_model_allows_trade():
    """rl_should_trade returns (True, ...) when no model exists."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        fake_path = Path(tmpdir) / "rl_qtable.json"
        import apexbot.modules.learner as learner_mod
        original = learner_mod.RL_QTABLE_PATH
        learner_mod.RL_QTABLE_PATH = fake_path
        try:
            result = rl_should_trade({})
        finally:
            learner_mod.RL_QTABLE_PATH = original

    should_trade, reason = result
    assert should_trade is True
    assert reason  # reason should be non-empty string
