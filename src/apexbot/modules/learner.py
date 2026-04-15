"""
LEARNER — APEXBOT Adaptive Trade Logger & RL Stub

Logs trade signals for future reinforcement-learning analysis.
All heavy RL functions are stubs that return safe defaults so the rest
of the system can run without errors.
"""

import json
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RL_LOG_PATH  = PROJECT_ROOT / 'artifacts' / 'rl_log.jsonl'
CYCLE_DIR    = PROJECT_ROOT / 'artifacts' / 'cycles'


# ── Signal Logging ────────────────────────────────────────────────────────────

def record_trade_signals(state: dict, edge_result: dict,
                         vol_bucket: int, direction: str):
    """Append a trade signal record to the RL log for future training."""
    try:
        RL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            'ts':           datetime.utcnow().isoformat(),
            'cycle':        state.get('cycle_number', 1),
            'trade':        state.get('trade_number', 0),
            'direction':    direction,
            'edge':         edge_result.get('edge', 0.0),
            'p_win':        edge_result.get('p_win', 0.0),
            'rr':           edge_result.get('rr', 0.0),
            'vol_bucket':   vol_bucket,
            'capital':      state.get('current_capital_usdt', 0.0),
        }
        with open(RL_LOG_PATH, 'a') as f:
            f.write(json.dumps(record) + '\n')
    except Exception:
        pass


def log_rl_decision(state: dict, edge_result: dict, action: str = 'skip'):
    """Log a skip/trade RL decision for analysis. No-op stub."""
    pass


# ── Backtest Seeding ──────────────────────────────────────────────────────────

def seed_from_backtest(result: dict):
    """
    Pre-populate RL log from backtest trade history.
    Allows the learner to start with historical context.
    """
    trades = result.get('trades', [])
    if not trades:
        return
    try:
        RL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(RL_LOG_PATH, 'a') as f:
            for t in trades:
                record = {
                    'ts':        t.get('entry_time', ''),
                    'source':    'backtest',
                    'direction': t.get('direction', '?'),
                    'edge':      t.get('edge', 0.0),
                    'p_win':     t.get('p_win', 0.0),
                    'rr':        t.get('rr', 0.0),
                    'won':       t.get('won', False),
                    'outcome':   t.get('outcome', '?'),
                }
                f.write(json.dumps(record) + '\n')
    except Exception:
        pass


# ── Adaptive Target Update ────────────────────────────────────────────────────

def update_adaptive_target_with_history(current_target: float,
                                         min_cycles: int = 10) -> float:
    """
    Reads past cycle results and returns an EV-optimal target multiplier.
    Returns current_target unchanged if not enough data yet.
    """
    if not CYCLE_DIR.exists():
        return current_target

    files = sorted(CYCLE_DIR.glob('cycle_*.json'))
    if len(files) < min_cycles:
        return current_target

    results_by_target: dict = {}
    for fp in files:
        try:
            with open(fp) as f:
                c = json.load(f)
            mult   = float(c.get('multiplier', 1.0))
            trades = int(c.get('trades', 0))
            key    = trades
            results_by_target.setdefault(key, []).append(mult)
        except Exception:
            continue

    if not results_by_target:
        return current_target

    # Expected value per trade count
    ev = {k: sum(v) / len(v) for k, v in results_by_target.items()}
    best_trades = max(ev, key=ev.get)
    best_ev     = ev[best_trades]

    # Convert optimal trade count to a target multiplier heuristic
    # (assume ~1.5x per winning trade on average)
    new_target = round(1.5 ** best_trades, 2)
    new_target = max(1.5, min(new_target, 50.0))   # clamp to sane range

    if abs(new_target - current_target) > 0.1:
        print(f"[LEARNER] Adaptive target: {current_target:.2f}x → {new_target:.2f}x "
              f"(EV={best_ev:.3f} @ {best_trades} trades)")
        return new_target

    return current_target


# ── RL Stubs (future implementation) ─────────────────────────────────────────

def _recompute_weights(stats: dict) -> dict:
    """Placeholder. Returns uniform weights."""
    return {k: 1.0 for k in stats}


def _discretize_state(state_dict: dict) -> str:
    """Placeholder. Returns simple state string."""
    cap = state_dict.get('current_capital_usdt', 0)
    trades = state_dict.get('trade_number', 0)
    return f"cap_{int(cap)}_t{trades}"


def _train_qtable(log: list):
    """Placeholder. No-op until RL is fully implemented."""
    pass


def rl_should_trade(state_dict: dict, threshold: float = 0.15) -> tuple:
    """
    Placeholder RL gate. Always allows trading until Q-table is trained.
    Returns (should_trade: bool, reason: str).
    """
    return True, 'rl_stub_always_trade'
