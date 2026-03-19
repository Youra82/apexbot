"""
COMPOUNDER — Cycle & Position Sizing Manager
Handles compounding logic, cycle tracking, and auto-exit optimization.
"""

import json
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATE_PATH   = PROJECT_ROOT / "artifacts" / "state" / "global_state.json"


def load_state() -> dict:
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state: dict):
    state["last_updated"] = datetime.utcnow().isoformat()
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def get_position_size(state: dict, mode: str, config: dict) -> float:
    """
    Returns USDT amount to use for this trade.
    FULL_SEND = 100% of current capital
    HALF_SEND = 50% of current capital
    """
    capital = state["current_capital_usdt"]
    if mode == "FULL_SEND":
        return capital
    elif mode == "HALF_SEND":
        return capital * 0.5
    return 0.0


def record_trade_result(state: dict, won: bool, pnl_usdt: float, config: dict) -> dict:
    """
    Updates state after a trade closes.
    Checks if cycle is complete (max trades reached or drawdown).
    """
    state["trade_number"] += 1
    state["current_capital_usdt"] += pnl_usdt
    state["peak_capital_usdt"] = max(state["peak_capital_usdt"], state["current_capital_usdt"])

    max_trades  = config["cycle"]["max_trades_per_cycle"]
    max_dd      = config["risk"]["max_drawdown_pct"] / 100
    target_mult = config["cycle"].get("cycle_target_multiplier", 50.0)
    start_cap   = config["cycle"]["start_capital_usdt"]

    cycle_done = False
    reason = ""

    if state["current_capital_usdt"] >= start_cap * target_mult:
        cycle_done = True
        reason = "TARGET_HIT"

    if state["trade_number"] >= max_trades:
        cycle_done = True
        reason = reason or "MAX_TRADES_REACHED"

    drawdown = 1 - (state["current_capital_usdt"] / state["peak_capital_usdt"])
    if drawdown >= max_dd:
        cycle_done = True
        reason = reason or "DRAWDOWN_LIMIT"

    if cycle_done:
        _close_cycle(state, reason, config)

    return state


def _close_cycle(state: dict, reason: str, config: dict):
    """Archive current cycle and reset for next one."""
    cycle_record = {
        "cycle": state["cycle_number"],
        "start_capital": state["start_capital_usdt"],
        "end_capital": state["current_capital_usdt"],
        "trades": state["trade_number"],
        "multiplier": round(state["current_capital_usdt"] / state["start_capital_usdt"], 2),
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    }

    cycles_dir = PROJECT_ROOT / "artifacts" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    cycle_log = cycles_dir / f"cycle_{state['cycle_number']:04d}.json"
    with open(cycle_log, "w") as f:
        json.dump(cycle_record, f, indent=2)

    print(f"[COMPOUNDER] Cycle {state['cycle_number']} done: {reason}")
    print(f"             {state['start_capital_usdt']}€ → {state['current_capital_usdt']:.2f}€ ({cycle_record['multiplier']}x)")

    # Adaptive target update (GENOME-style EV optimization)
    learner_cfg = config.get("learner", {})
    if learner_cfg.get("adaptive_target", False):
        try:
            from apexbot.modules.learner import update_adaptive_target
            min_cycles = learner_cfg.get("min_cycles_for_target", 10)
            current_target = config["cycle"].get("cycle_target_multiplier", 50.0)
            new_target = update_adaptive_target(current_target, min_cycles=min_cycles)
            if new_target != current_target:
                config["cycle"]["cycle_target_multiplier"] = new_target
                # Persist to settings.json
                settings_path = PROJECT_ROOT / "settings.json"
                try:
                    with open(settings_path) as sf:
                        settings_data = json.load(sf)
                    settings_data["cycle"]["cycle_target_multiplier"] = new_target
                    with open(settings_path, "w") as sf:
                        json.dump(settings_data, sf, indent=2)
                    print(f"[COMPOUNDER] Adaptive target updated: {new_target:.4f}x → settings.json")
                except Exception as e:
                    print(f"[COMPOUNDER] Could not save adaptive target to settings.json: {e}")
        except Exception as e:
            print(f"[COMPOUNDER] Adaptive target error: {e}")

    # Reset for next cycle
    start = config["cycle"]["start_capital_usdt"]
    state["cycle_number"] += 1
    state["trade_number"] = 0
    state["current_capital_usdt"] = start
    state["start_capital_usdt"] = start
    state["peak_capital_usdt"] = start
    state["status"] = "WAITING"
    state["active_position"] = None


def compute_optimal_exit_trade(cycle_history_path: Path = Path("artifacts/cycles")) -> int:
    """
    Auto-Statistical: Analyzes past cycles to find the optimal trade number
    to exit (where expected value is maximized).
    Falls back to config default if not enough data.
    """
    files = list(cycle_history_path.glob("cycle_*.json"))
    if len(files) < 10:
        return None  # Not enough data yet

    results_by_trade = {}
    for f in files:
        with open(f) as fp:
            c = json.load(fp)
        t = c["trades"]
        mult = c["multiplier"]
        if t not in results_by_trade:
            results_by_trade[t] = []
        results_by_trade[t].append(mult)

    # Expected value per trade count
    ev = {}
    for t, mults in results_by_trade.items():
        ev[t] = sum(mults) / len(mults)

    best_trade = max(ev, key=ev.get)
    print(f"[COMPOUNDER] Auto-optimal exit: Trade {best_trade} (EV={ev[best_trade]:.2f}x)")
    return best_trade
