# src/apexbot/analysis/optimizer.py
"""
APEXBOT Parameter-Optimizer (Optuna)
Optimiert FUSION- und RADAR-Schwellenwerte auf historischen Daten.
Speichert beste Parameter in artifacts/configs/config_SYMBOL_TF.json
und ueberschreibt optionell settings.json.

Usage:
  python src/apexbot/analysis/optimizer.py --symbol BTC/USDT:USDT --timeframe 15m --days 180 --trials 100
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.modules.radar import detect_regime
from apexbot.modules.fusion import compute_fusion_score

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('optimizer')


# ── Daten laden (gecacht) ────────────────────────────────────────────────────

_DATA_CACHE: dict = {}


def load_data(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    key = f"{symbol}_{timeframe}_{days}"
    if key in _DATA_CACHE:
        return _DATA_CACHE[key]

    import ccxt, time
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    exchange.load_markets()

    tf_ms    = exchange.parse_timeframe(timeframe) * 1000
    since    = exchange.milliseconds() - days * 24 * 3600 * 1000
    all_rows = []

    while since < exchange.milliseconds() - tf_ms:
        try:
            rows = exchange.fetch_ohlcv(symbol, timeframe, since, 1000)
            if not rows:
                break
            all_rows.extend(rows)
            since = rows[-1][0] + tf_ms
            time.sleep(exchange.rateLimit / 1000)
        except Exception as e:
            logger.warning(f"Fehler: {e}")
            break

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    _DATA_CACHE[key] = df
    return df


# ── Backtest-Kern (schnell, kein Exchange) ───────────────────────────────────

def quick_backtest(df: pd.DataFrame, settings: dict) -> dict:
    sl_pct      = settings['risk']['stop_loss_pct'] / 100
    tp_pct      = sl_pct * settings['risk']['take_profit_multiplier']
    leverage    = settings['leverage']
    start       = settings['cycle']['start_capital_usdt']
    max_tr      = settings['cycle']['max_trades_per_cycle']
    max_dd      = settings['risk']['max_drawdown_pct'] / 100
    target_mult = settings['cycle'].get('cycle_target_multiplier', 50.0)
    WARMUP      = 60

    cycles   = []
    capital  = start
    peak     = start
    cur      = {'trades': []}
    in_trade = False
    entry    = None

    for i in range(WARMUP, len(df)):
        window = df.iloc[max(0, i - 200):i + 1]
        row    = df.iloc[i]

        if in_trade:
            hit_sl = row['low']  <= entry['sl'] if entry['dir'] == 'long' else row['high'] >= entry['sl']
            hit_tp = row['high'] >= entry['tp'] if entry['dir'] == 'long' else row['low']  <= entry['tp']
            if hit_tp or hit_sl:
                pnl     = capital * leverage * (tp_pct if hit_tp else -sl_pct)
                capital = max(0, capital + pnl)
                peak    = max(peak, capital)
                cur['trades'].append({'won': hit_tp, 'pnl': pnl})
                in_trade   = False
                dd         = 1 - capital / peak if peak > 0 else 0
                hit_target = capital >= start * target_mult
                if hit_target or len(cur['trades']) >= max_tr or dd >= max_dd or capital <= 0:
                    cur['mult'] = capital / start
                    if hit_target:
                        cur['reason'] = 'TARGET_HIT'
                    elif len(cur['trades']) >= max_tr:
                        cur['reason'] = 'MAX'
                    elif dd >= max_dd:
                        cur['reason'] = 'DD'
                    else:
                        cur['reason'] = 'BUST'
                    cycles.append(cur)
                    capital = start
                    peak    = start
                    cur     = {'trades': []}
            continue

        regime = detect_regime(window, settings)
        if regime != 'HUNT':
            continue

        fusion = compute_fusion_score(window, settings)
        if fusion['mode'] == 'SKIP':
            continue

        ep  = row['close']
        sd  = ep * sl_pct
        td  = sd * settings['risk']['take_profit_multiplier']
        sl  = ep - sd if fusion['direction'] == 'long' else ep + sd
        tp  = ep + td if fusion['direction'] == 'long' else ep - td
        entry    = {'dir': fusion['direction'], 'sl': sl, 'tp': tp}
        in_trade = True

    if not cycles:
        return {'score': 0.0, 'total_cycles': 0, 'win_rate': 0.0, 'avg_mult': 1.0,
                'target_hit_count': 0, 'target_multiplier': target_mult}

    mults            = [c['mult'] for c in cycles]
    target_hit_count = sum(1 for c in cycles if c.get('reason') == 'TARGET_HIT')
    hit_rate         = target_hit_count / len(cycles)
    win_rate         = sum(1 for m in mults if m > 1) / len(mults)
    avg_mult         = np.mean(mults)
    # Score belohnt: hoher Durchschnitts-Mult × viele Cycles × Bonus fuer Ziel-Treffer
    score = avg_mult * np.log1p(len(cycles)) * (1.0 + hit_rate)
    return {
        'score':             round(score, 4),
        'total_cycles':      len(cycles),
        'win_rate':          round(win_rate, 3),
        'avg_mult':          round(avg_mult, 3),
        'target_hit_count':  target_hit_count,
        'target_multiplier': target_mult,
        'cycles':            cycles,
    }


# ── Optuna Objective ─────────────────────────────────────────────────────────

def build_settings_from_trial(trial, base_settings: dict) -> dict:
    import copy
    s = copy.deepcopy(base_settings)

    # RADAR
    s['radar']['atr_multiplier_min'] = trial.suggest_float('atr_min', 0.5, 3.0, step=0.25)
    s['radar']['adx_min']            = trial.suggest_int('adx_min', 15, 40, step=5)
    s['radar']['bb_width_min']       = trial.suggest_float('bb_width_min', 0.005, 0.04, step=0.005)

    # FUSION
    s['fusion']['min_score_full_send']    = trial.suggest_int('min_score_full', 3, 5)
    s['fusion']['min_score_half_send']    = trial.suggest_int('min_score_half', 2, 4)
    s['fusion']['volume_surge_multiplier'] = trial.suggest_float('vol_surge', 1.2, 3.0, step=0.2)
    s['fusion']['body_ratio_min']          = trial.suggest_float('body_ratio', 0.40, 0.75, step=0.05)
    s['fusion']['rsi_momentum_min']        = trial.suggest_int('rsi_min', 45, 58, step=1)
    s['fusion']['rsi_momentum_max']        = trial.suggest_int('rsi_max', 65, 80, step=1)

    # RISK
    s['risk']['stop_loss_pct']          = trial.suggest_float('sl_pct', 1.0, 4.0, step=0.5)
    s['risk']['take_profit_multiplier'] = trial.suggest_float('tp_mult', 1.5, 3.0, step=0.5)

    # CYCLE TARGET (log-Skala: 2x bis 200x gleichmäßig verteilt)
    s['cycle']['cycle_target_multiplier'] = trial.suggest_float('target_mult', 2.0, 200.0, log=True)

    # Constraint: min_score_half < min_score_full
    if s['fusion']['min_score_half_send'] >= s['fusion']['min_score_full_send']:
        raise Exception("Constraint verletzt")

    return s


def make_objective(df: pd.DataFrame, base_settings: dict):
    def objective(trial):
        import optuna
        try:
            s      = build_settings_from_trial(trial, base_settings)
            result = quick_backtest(df, s)
            return result['score']
        except Exception:
            return 0.0
    return objective


# ── Haupt-Optimizer ──────────────────────────────────────────────────────────

def run_optimizer(symbol: str, timeframe: str, days: int,
                  n_trials: int, base_settings: dict) -> dict:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    df = load_data(symbol, timeframe, days)
    if df.empty:
        print(f"  [FEHLER] Keine Daten fuer {symbol} {timeframe}")
        return {}

    print(f"  {len(df)} Kerzen geladen. Starte Optimierung ({n_trials} Trials)...")

    study = optuna.create_study(direction='maximize')
    study.optimize(make_objective(df, base_settings), n_trials=n_trials, show_progress_bar=False)

    best = study.best_trial
    best_settings = build_settings_from_trial(best, base_settings)
    result        = quick_backtest(df, best_settings)

    output = {
        'symbol':            symbol,
        'timeframe':         timeframe,
        'days':              days,
        'trials':            n_trials,
        'score':             best.value,
        'cycles':            result['total_cycles'],
        'win_rate':          result['win_rate'],
        'avg_mult':          result['avg_mult'],
        'target_multiplier': result['target_multiplier'],
        'target_hit_count':  result['target_hit_count'],
        'params': {
            'radar':   best_settings['radar'],
            'fusion':  best_settings['fusion'],
            'risk':    best_settings['risk'],
            'cycle':   {'cycle_target_multiplier': best_settings['cycle']['cycle_target_multiplier']},
        },
        'timestamp':   datetime.utcnow().isoformat(),
    }

    # Speichern
    cfg_dir = Path(PROJECT_ROOT) / 'artifacts' / 'configs'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cfg_path = cfg_dir / f"config_{safe}.json"
    with open(cfg_path, 'w') as f:
        json.dump(output, f, indent=2)

    tgt = result['target_multiplier']; hits = result['target_hit_count']; cyc = result['total_cycles']
    print(f"  Score: {best.value:.4f} | Cycles: {cyc} | WR: {result['win_rate']*100:.0f}% | Avg: {result['avg_mult']:.2f}x")
    print(f"  Ziel: {tgt:.1f}x | Treffer: {hits}/{cyc} ({hits/cyc*100:.0f}%)" if cyc else "")
    print(f"  Config gespeichert: {cfg_path.name}")

    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol',    required=True)
    parser.add_argument('--timeframe', required=True)
    parser.add_argument('--days',      type=int, default=180)
    parser.add_argument('--trials',    type=int, default=100)
    parser.add_argument('--apply',     action='store_true', help='Best-Config auf settings.json anwenden')
    args = parser.parse_args()

    with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
        base = json.load(f)

    result = run_optimizer(args.symbol, args.timeframe, args.days, args.trials, base)

    if args.apply and result:
        base['radar']  = result['params']['radar']
        base['fusion'] = result['params']['fusion']
        base['risk']   = result['params']['risk']
        base['cycle']['cycle_target_multiplier'] = result['params']['cycle']['cycle_target_multiplier']
        with open(os.path.join(PROJECT_ROOT, 'settings.json'), 'w') as f:
            json.dump(base, f, indent=2)
        tgt = result['params']['cycle']['cycle_target_multiplier']
        print(f"  settings.json aktualisiert. Cycle-Ziel: {tgt:.1f}x")


if __name__ == '__main__':
    main()
