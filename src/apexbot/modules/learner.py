"""
LEARNER — Self-Learning Module for apexbot
- Adaptive cycle target (GENOME-style EV optimization)
- Adaptive FUSION signal weights
- RL Gate (Q-table based trade filter)
"""

import json
import math
import logging
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEARNER_PATH = PROJECT_ROOT / "artifacts" / "learner"
CYCLES_PATH  = PROJECT_ROOT / "artifacts" / "cycles"

logger = logging.getLogger(__name__)


# ── Adaptive Cycle Target ─────────────────────────────────────────────────────

def update_adaptive_target(current_target: float, min_cycles: int = 10) -> float:
    """
    Reads all archived cycle files and computes the candidate multiplier
    that maximizes expected value (hit_rate * candidate).
    Returns best candidate, or current_target if not enough data.
    """
    files = list(CYCLES_PATH.glob("cycle_*.json"))
    if len(files) < min_cycles:
        logger.info(f"[LEARNER] Not enough cycles ({len(files)}/{min_cycles}) for adaptive target.")
        return current_target

    multipliers = []
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
            mult = data.get("multiplier")
            if mult is not None:
                multipliers.append(float(mult))
        except Exception as e:
            logger.warning(f"[LEARNER] Could not read {f}: {e}")

    if not multipliers:
        return current_target

    max_mult = max(multipliers)
    min_candidate = 1.5
    if max_mult <= min_candidate:
        return current_target

    # 50 candidates on log scale from 1.5x to max(multipliers)
    candidates = [
        math.exp(math.log(min_candidate) + i * (math.log(max_mult) - math.log(min_candidate)) / 49)
        for i in range(50)
    ]

    best_ev = -1.0
    best_candidate = current_target

    for candidate in candidates:
        hit_rate = sum(1 for m in multipliers if m >= candidate) / len(multipliers)
        ev = hit_rate * candidate
        if ev > best_ev:
            best_ev = ev
            best_candidate = candidate

    logger.info(f"[LEARNER] Adaptive target: {best_candidate:.4f}x (EV={best_ev:.4f}, from {len(multipliers)} cycles)")
    return round(best_candidate, 4)


# ── Adaptive Signal Weights ───────────────────────────────────────────────────

WEIGHTS_PATH = LEARNER_PATH / "signal_weights.json"
STATS_PATH   = LEARNER_PATH / "signal_stats.json"

DEFAULT_SIGNALS = ["bb", "volume", "ema", "body", "rsi"]


def load_signal_weights() -> dict:
    """
    Loads signal weights from artifacts/learner/signal_weights.json.
    Returns dict with all 5 signal keys, defaulting to 1.0.
    """
    default = {sig: 1.0 for sig in DEFAULT_SIGNALS}
    if not WEIGHTS_PATH.exists():
        return default
    try:
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)
        # Ensure all keys present
        for sig in DEFAULT_SIGNALS:
            if sig not in data:
                data[sig] = 1.0
        return data
    except Exception as e:
        logger.warning(f"[LEARNER] Could not load signal weights: {e}")
        return default


def record_trade_signals(signals: dict, won: bool):
    """
    Updates signal_stats.json with win/loss counts for signals that fired (value=1).
    signals: dict like {'bb': 1, 'volume': 0, 'ema': 1, 'body': 1, 'rsi': 0}
    won: True if trade was profitable
    """
    LEARNER_PATH.mkdir(parents=True, exist_ok=True)

    stats = {}
    if STATS_PATH.exists():
        try:
            with open(STATS_PATH) as f:
                stats = json.load(f)
        except Exception:
            stats = {}

    for sig, fired in signals.items():
        if fired != 1:
            continue
        if sig not in stats:
            stats[sig] = {"wins": 0, "losses": 0}
        if won:
            stats[sig]["wins"] += 1
        else:
            stats[sig]["losses"] += 1

    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    # Recompute and save weights
    weights = _recompute_weights(stats)
    LEARNER_PATH.mkdir(parents=True, exist_ok=True)
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(weights, f, indent=2)


def _recompute_weights(stats: dict) -> dict:
    """
    weight = signal_winrate / mean_winrate, clipped to [0.3, 2.5].
    Requires min 20 trades per signal; otherwise weight stays 1.0.
    """
    MIN_TRADES = 20
    winrates = {}

    for sig in DEFAULT_SIGNALS:
        if sig in stats:
            w = stats[sig].get("wins", 0)
            l = stats[sig].get("losses", 0)
            total = w + l
            if total >= MIN_TRADES:
                winrates[sig] = w / total
            else:
                winrates[sig] = None  # Not enough data
        else:
            winrates[sig] = None

    # Compute mean winrate from signals with enough data
    valid_rates = [r for r in winrates.values() if r is not None]
    if not valid_rates:
        return {sig: 1.0 for sig in DEFAULT_SIGNALS}

    mean_wr = sum(valid_rates) / len(valid_rates)
    if mean_wr == 0:
        return {sig: 1.0 for sig in DEFAULT_SIGNALS}

    weights = {}
    for sig in DEFAULT_SIGNALS:
        wr = winrates.get(sig)
        if wr is None:
            weights[sig] = 1.0
        else:
            raw = wr / mean_wr
            weights[sig] = max(0.3, min(2.5, raw))

    return weights


# ── RL Gate ───────────────────────────────────────────────────────────────────

RL_LOG_PATH    = LEARNER_PATH / "rl_trade_log.json"
RL_QTABLE_PATH = LEARNER_PATH / "rl_qtable.json"

RL_LOG_MAX_ENTRIES = 2000
RL_TRAIN_EVERY     = 10


def _discretize_state(state_dict: dict) -> str:
    """
    Discretize state into a bucket string key.
    Buckets: hour//4 (0-5), fusion_score (0-5), volatility_bucket (0/1/2),
             cycle_phase (1-4), direction[0]
    """
    hour         = int(state_dict.get("hour", 0)) // 4
    fusion_score = int(state_dict.get("fusion_score", 0))
    vol_bucket   = int(state_dict.get("volatility_bucket", 1))
    cycle_phase  = int(state_dict.get("cycle_phase", 1))
    direction    = str(state_dict.get("direction", "n"))[0]

    # Clamp values
    hour         = max(0, min(5, hour))
    fusion_score = max(0, min(5, fusion_score))
    vol_bucket   = max(0, min(2, vol_bucket))
    cycle_phase  = max(1, min(4, cycle_phase))

    return f"{hour}_{fusion_score}_{vol_bucket}_{cycle_phase}_{direction}"


def log_rl_decision(state_dict: dict, won: bool):
    """
    Appends trade result to rl_trade_log.json (rolling 2000 entries).
    Triggers Q-table training every 10 trades after 200+ entries.
    """
    LEARNER_PATH.mkdir(parents=True, exist_ok=True)

    log = []
    if RL_LOG_PATH.exists():
        try:
            with open(RL_LOG_PATH) as f:
                log = json.load(f)
        except Exception:
            log = []

    entry = {
        "state": _discretize_state(state_dict),
        "won":   won,
        "ts":    datetime.utcnow().isoformat(),
    }
    log.append(entry)

    # Rolling window
    if len(log) > RL_LOG_MAX_ENTRIES:
        log = log[-RL_LOG_MAX_ENTRIES:]

    with open(RL_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

    # Train every RL_TRAIN_EVERY trades after 200+ entries
    if len(log) >= 200 and len(log) % RL_TRAIN_EVERY == 0:
        _train_qtable(log)


def _train_qtable(log: list):
    """
    For each state bucket, compute win_rate from log entries.
    Save to rl_qtable.json with global_wr and trained_on count.
    """
    LEARNER_PATH.mkdir(parents=True, exist_ok=True)

    state_wins   = {}
    state_counts = {}

    for entry in log:
        s = entry["state"]
        if s not in state_counts:
            state_counts[s] = 0
            state_wins[s]   = 0
        state_counts[s] += 1
        if entry["won"]:
            state_wins[s] += 1

    total_won  = sum(1 for e in log if e["won"])
    global_wr  = total_won / len(log) if log else 0.5

    qtable = {
        "global_wr":  global_wr,
        "trained_on": len(log),
        "states":     {
            s: state_wins[s] / state_counts[s]
            for s in state_counts
        }
    }

    with open(RL_QTABLE_PATH, "w") as f:
        json.dump(qtable, f, indent=2)

    logger.info(f"[LEARNER] Q-table trained on {len(log)} entries. Global WR: {global_wr:.2%}")


def rl_should_trade(state_dict: dict, threshold: float = 0.15) -> tuple[bool, str]:
    """
    Checks Q-table: if state win_rate < global_wr - threshold → block trade.
    Returns (should_trade: bool, reason: str).
    """
    if not RL_QTABLE_PATH.exists():
        return True, "no_model"

    try:
        with open(RL_QTABLE_PATH) as f:
            qtable = json.load(f)
    except Exception:
        return True, "no_model"

    trained_on = qtable.get("trained_on", 0)
    if trained_on < 200:
        return True, "no_model"

    global_wr = qtable.get("global_wr", 0.5)
    state_key = _discretize_state(state_dict)
    states    = qtable.get("states", {})

    if state_key not in states:
        return True, "state_unknown"

    state_wr = states[state_key]
    if state_wr < global_wr - threshold:
        reason = f"rl_block: state_wr={state_wr:.2%} < global_wr={global_wr:.2%} - {threshold}"
        logger.info(f"[RL GATE] Blocked trade. {reason}")
        return False, reason

    return True, f"rl_ok: state_wr={state_wr:.2%}"


# ── Seed from Backtest ────────────────────────────────────────────────────────

HISTORY_PATH = LEARNER_PATH / "backtest_seed.json"


def seed_from_backtest(result: dict):
    """
    Vortraining aller Lern-Systeme aus Backtest-Ergebnissen.

    - RL Gate:        Backtest-Trades → rl_trade_log.json (tagged 'backtest')
    - Signal Weights: Backtest-Signale → signal_stats.json
    - Cycle Target:   Backtest-Cycles  → artifacts/cycles/history/
    - Soforttraining: Q-Table + Weights werden direkt berechnet

    Wird nach jedem run_pipeline.sh automatisch aufgerufen.
    Vorhandene Live-Daten bleiben erhalten — Backtest-Daten werden ersetzt.
    """
    trades = result.get('trades', [])
    cycles = result.get('cycles', [])

    if not trades:
        logger.info("[LEARNER] seed_from_backtest: keine Trades in Backtest-Ergebnis.")
        return

    LEARNER_PATH.mkdir(parents=True, exist_ok=True)

    # ── 1. RL Gate: Backtest-Trades in RL-Log einpflegen ─────────────────────
    # Vorhandene Live-Eintraege behalten, alte Backtest-Eintraege ersetzen
    live_entries = []
    if RL_LOG_PATH.exists():
        try:
            with open(RL_LOG_PATH) as f:
                existing = json.load(f)
            live_entries = [e for e in existing if e.get('source') == 'live']
        except Exception:
            live_entries = []

    backtest_entries = []
    for t in trades:
        entry_time = t.get('entry_time', '')
        try:
            hour = int(entry_time[11:13]) if len(entry_time) >= 13 else 0
        except (ValueError, TypeError):
            hour = 0

        atr_pct = float(t.get('atr_pct', 0.0))
        if atr_pct < 0.001:
            vol_bucket = 0
        elif atr_pct < 0.003:
            vol_bucket = 1
        else:
            vol_bucket = 2

        state = _discretize_state({
            'hour':              hour,
            'fusion_score':      t.get('fusion_score', 0),
            'volatility_bucket': vol_bucket,
            'cycle_phase':       t.get('cycle_phase', 1),
            'direction':         t.get('direction', 'long'),
        })
        backtest_entries.append({
            'state':  state,
            'won':    t.get('won', False),
            'ts':     entry_time,
            'source': 'backtest',
        })

    merged = backtest_entries + live_entries
    if len(merged) > RL_LOG_MAX_ENTRIES:
        # Priorität: Live-Daten behalten, älteste Backtest-Daten kürzen
        keep_live = live_entries[-RL_LOG_MAX_ENTRIES // 2:]
        keep_bt   = backtest_entries[-(RL_LOG_MAX_ENTRIES - len(keep_live)):]
        merged    = keep_bt + keep_live

    with open(RL_LOG_PATH, 'w') as f:
        json.dump(merged, f, indent=2)

    # Sofort trainieren wenn >= 200 Eintraege
    if len(merged) >= 200:
        _train_qtable(merged)
        logger.info(f"[LEARNER] RL-Gate vortrainiert: {len(backtest_entries)} Backtest + {len(live_entries)} Live-Trades")

    # ── 2. Signal Weights: Backtest-Signale als Basis ─────────────────────────
    # Vorhandene Live-Stats mit Backtest-Stats zusammenfuehren
    stats = {}
    if STATS_PATH.exists():
        try:
            with open(STATS_PATH) as f:
                existing_stats = json.load(f)
            # Nur Live-Daten behalten (kein 'source'-Feld = live)
            stats = {
                sig: {k: v for k, v in data.items() if k != 'backtest_wins'}
                for sig, data in existing_stats.items()
            }
        except Exception:
            stats = {}

    # Backtest-Signal-Stats berechnen (in eigene Felder schreiben)
    bt_stats = {sig: {'wins': 0, 'losses': 0} for sig in DEFAULT_SIGNALS}
    for t in trades:
        signals = t.get('signals', {})
        won     = t.get('won', False)
        for sig, fired in signals.items():
            if sig in bt_stats and fired == 1:
                if won:
                    bt_stats[sig]['wins'] += 1
                else:
                    bt_stats[sig]['losses'] += 1

    # Backtest- und Live-Stats zusammenfuehren
    for sig in DEFAULT_SIGNALS:
        if sig not in stats:
            stats[sig] = {'wins': 0, 'losses': 0}
        # Backtest-Werte als separate Felder speichern (werden bei Recompute zusammengezaehlt)
        stats[sig]['bt_wins']   = bt_stats[sig]['wins']
        stats[sig]['bt_losses'] = bt_stats[sig]['losses']

    with open(STATS_PATH, 'w') as f:
        json.dump(stats, f, indent=2)

    # Gewichte berechnen (live + backtest kombiniert)
    combined_stats = {}
    for sig in DEFAULT_SIGNALS:
        s = stats.get(sig, {})
        combined_stats[sig] = {
            'wins':   s.get('wins', 0)   + s.get('bt_wins', 0),
            'losses': s.get('losses', 0) + s.get('bt_losses', 0),
        }
    weights = _recompute_weights(combined_stats)
    with open(WEIGHTS_PATH, 'w') as f:
        json.dump(weights, f, indent=2)
    logger.info(f"[LEARNER] Signal-Gewichte aus {len(trades)} Backtest-Trades: {weights}")

    # ── 3. Cycle Target: Backtest-Cycles als History speichern ───────────────
    history_dir = LEARNER_PATH / "cycle_history"
    history_dir.mkdir(parents=True, exist_ok=True)

    # Alte Backtest-Cycles loeschen (frische Daten)
    for old in history_dir.glob("hist_*.json"):
        old.unlink(missing_ok=True)

    for idx, cycle in enumerate(cycles):
        record = {
            'multiplier':    cycle.get('multiplier', 1.0),
            'trades':        len(cycle.get('trades', [])),
            'reason':        cycle.get('reason', 'UNKNOWN'),
            'source':        'backtest',
        }
        with open(history_dir / f"hist_{idx:04d}.json", 'w') as f:
            json.dump(record, f)

    logger.info(f"[LEARNER] {len(cycles)} Backtest-Cycles als History gespeichert.")

    n_bt  = len(backtest_entries)
    n_sig = sum(bt_stats[s]['wins'] + bt_stats[s]['losses'] for s in DEFAULT_SIGNALS)
    print(f"\n[LEARNER] Vortraining abgeschlossen:")
    print(f"  RL Gate:       {n_bt} Trades (Live: {len(live_entries)})")
    print(f"  Signal-Stats:  {n_sig} Signal-Feuererungen")
    print(f"  Cycle History: {len(cycles)} Cycles")
    print(f"  Weights:       {weights}")


def update_adaptive_target_with_history(current_target: float, min_cycles: int = 10) -> float:
    """
    Wie update_adaptive_target(), aber liest zusaetzlich Backtest-History ein.
    Wird von compounder._close_cycle() aufgerufen (ersetzt die einfache Variante).
    """
    # Live-Cycles
    live_files    = list(CYCLES_PATH.glob("cycle_*.json"))
    # Backtest-History
    history_dir   = LEARNER_PATH / "cycle_history"
    history_files = list(history_dir.glob("hist_*.json")) if history_dir.exists() else []

    all_files = live_files + history_files
    if len(all_files) < min_cycles:
        logger.info(f"[LEARNER] Zu wenig Cycle-Daten ({len(all_files)}/{min_cycles}).")
        return current_target

    multipliers = []
    for f in all_files:
        try:
            with open(f) as fp:
                data = json.load(fp)
            mult = data.get('multiplier')
            if mult is not None:
                multipliers.append(float(mult))
        except Exception:
            continue

    if not multipliers:
        return current_target

    max_mult      = max(multipliers)
    min_candidate = 1.5
    if max_mult <= min_candidate:
        return current_target

    candidates = [
        math.exp(math.log(min_candidate) + i * (math.log(max_mult) - math.log(min_candidate)) / 49)
        for i in range(50)
    ]

    best_ev, best_candidate = -1.0, current_target
    for c in candidates:
        hit_rate = sum(1 for m in multipliers if m >= c) / len(multipliers)
        ev = hit_rate * c
        if ev > best_ev:
            best_ev, best_candidate = ev, c

    n_live = len(live_files)
    n_hist = len(history_files)
    logger.info(
        f"[LEARNER] Adaptives Ziel: {best_candidate:.2f}x (EV={best_ev:.3f} | "
        f"Live: {n_live} | Backtest-History: {n_hist} Cycles)"
    )
    return round(best_candidate, 4)
