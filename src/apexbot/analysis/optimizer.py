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
from datetime import datetime, timezone

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.modules.radar import detect_attractor
from apexbot.modules.fusion import compute_edge_fast

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


# ── APEXBOT v2 — Attractor + Edge Backtest ───────────────────────────────────

def quick_backtest_v2(df: pd.DataFrame, settings: dict) -> dict:
    """
    Fast backtest for APEXBOT v2 optimizer.
    Uses detect_attractor + compute_edge_fast (no liquidity zone lookup).
    SL = ATR × atr_sl_mult, TP = entry ± SL × min_rr.
    """
    start       = settings['cycle']['start_capital_usdt']
    max_tr      = settings['cycle']['max_trades_per_cycle']
    target_mult = settings['cycle'].get('cycle_target_multiplier', 16.0)
    leverage    = settings['leverage']
    max_dd_lim  = settings['risk']['max_drawdown_pct'] / 100
    min_rr      = settings['edge'].get('min_rr', 1.5)

    kelly_cfg  = settings.get('kelly', {})
    use_kelly  = kelly_cfg.get('enabled', False)
    kelly_frac = kelly_cfg.get('fraction', 1.0)

    WARMUP      = 60
    cycles      = []
    capital     = start
    peak        = start
    cur         = {'trades': []}
    in_trade    = False
    entry       = None
    max_dd_seen = 0.0

    for i in range(WARMUP, len(df)):
        window = df.iloc[max(0, i - 200):i + 1]
        row    = df.iloc[i]

        if in_trade:
            hit_sl = row['low']  <= entry['sl'] if entry['dir'] == 'long' else row['high'] >= entry['sl']
            hit_tp = row['high'] >= entry['tp'] if entry['dir'] == 'long' else row['low']  <= entry['tp']

            if hit_tp or hit_sl:
                ep     = entry['price']
                sl_pct = entry['sl_dist'] / ep if ep > 0 else 0.0
                tp_pct = entry['tp_dist'] / ep if ep > 0 else 0.0
                pnl    = entry['margin'] * leverage * (tp_pct if hit_tp else -sl_pct)

                capital = max(start * 0.01, capital + pnl)
                peak    = max(peak, capital)
                cur['trades'].append({'won': hit_tp, 'pnl': pnl})
                in_trade    = False
                dd          = 1 - capital / peak if peak > 0 else 0
                max_dd_seen = max(max_dd_seen, dd)

                hit_target = capital >= start * target_mult
                if hit_target or len(cur['trades']) >= max_tr or dd >= max_dd_lim:
                    cur['mult']   = capital / start
                    cur['reason'] = ('TARGET_HIT' if hit_target else
                                     ('MAX' if len(cur['trades']) >= max_tr else 'DD'))
                    cycles.append(cur)
                    capital  = start
                    peak     = start
                    cur      = {'trades': []}
            continue

        attractor = detect_attractor(window, settings)
        if attractor == 'CHAOS':
            continue

        edge = compute_edge_fast(window, settings)
        if edge['mode'] == 'SKIP' or edge['direction'] == 'none' or edge['atr_sl'] <= 0:
            continue

        ep        = float(row['close'])
        atr_sl    = edge['atr_sl']
        direction = edge['direction']
        tp_dist   = atr_sl * min_rr

        if direction == 'long':
            sl_price = ep - atr_sl
            tp_price = ep + tp_dist
        else:
            sl_price = ep + atr_sl
            tp_price = ep - tp_dist

        if use_kelly:
            p   = edge['p_win']
            rr  = min_rr
            f   = (p * rr - (1 - p)) / rr
            margin = capital * min(kelly_frac, max(0.05, f))
        else:
            margin = capital * kelly_frac

        entry    = {'dir': direction, 'sl': sl_price, 'tp': tp_price,
                    'price': ep, 'margin': margin,
                    'sl_dist': atr_sl, 'tp_dist': tp_dist}
        in_trade = True

    total_trades = sum(len(c['trades']) for c in cycles)

    if not cycles:
        return {'score': 0.0, 'total_cycles': 0, 'total_trades': 0,
                'win_rate': 0.0, 'avg_mult': 1.0, 'geo_mean': 1.0,
                'target_hit_count': 0, 'target_multiplier': target_mult,
                'max_dd_seen': max_dd_seen}

    mults            = [c['mult'] for c in cycles]
    target_hit_count = sum(1 for c in cycles if c.get('reason') == 'TARGET_HIT')
    hit_rate         = target_hit_count / len(cycles)
    win_rate         = sum(1 for m in mults if m > 1) / len(mults)
    avg_mult         = float(np.mean(mults))
    geo_mean         = float(np.exp(np.mean(np.log(np.maximum(mults, 1e-6)))))
    score            = geo_mean * np.log1p(len(cycles)) * (1.0 + hit_rate)

    return {
        'score':            round(score, 4),
        'total_cycles':     len(cycles),
        'total_trades':     total_trades,
        'win_rate':         round(win_rate, 3),
        'avg_mult':         round(avg_mult, 3),
        'geo_mean':         round(geo_mean, 3),
        'target_hit_count': target_hit_count,
        'target_multiplier': target_mult,
        'max_dd_seen':      round(max_dd_seen, 4),
        'cycles':           cycles,
    }


def build_settings_from_trial_v2(trial, base_settings: dict,
                                  mode: str = 'best_profit') -> dict:
    import copy
    s = copy.deepcopy(base_settings)

    # ATTRACTOR thresholds
    s['attractor']['hurst_trend_min']   = trial.suggest_float('hurst_trend',    0.50, 0.65, step=0.05)
    s['attractor']['adx_trend_min']     = trial.suggest_int(  'adx_trend',      20,   35,   step=5)
    s['attractor']['entropy_chaos_min'] = trial.suggest_float('entropy_chaos',  0.55, 0.90, step=0.05)

    # EDGE parameters
    s['edge']['threshold']               = trial.suggest_float('edge_thresh',    0.00, 0.80, step=0.05)
    s['edge']['min_rr']                  = trial.suggest_float('min_rr',         1.00, 3.00, step=0.25)
    s['edge']['atr_sl_mult']             = trial.suggest_float('atr_sl_mult',    0.50, 3.00, step=0.25)
    s['edge']['volume_surge_multiplier'] = trial.suggest_float('vol_surge',      1.20, 3.00, step=0.20)
    s['edge']['rsi_momentum_min']        = trial.suggest_int(  'rsi_min',        45,   60)
    s['edge']['rsi_momentum_max']        = trial.suggest_int(  'rsi_max',        65,   82)
    s['edge']['body_ratio_min']          = trial.suggest_float('body_ratio',     0.35, 0.75, step=0.05)

    if mode == 'strict':
        s['cycle']['cycle_target_multiplier'] = trial.suggest_float('target_mult', 1.1, 8.0, step=0.1)
        kelly_frac = trial.suggest_float('kelly_frac', 0.10, 1.00, step=0.05)
        s['kelly'] = {'enabled': True, 'fraction': kelly_frac}
    else:
        s['cycle']['cycle_target_multiplier'] = trial.suggest_float('target_mult', 1.5, 20.0, step=0.5)
        s['kelly'] = {'enabled': False, 'fraction': 1.0}

    return s


def make_objective_v2(df: pd.DataFrame, base_settings: dict, min_trades: int = 0,
                      max_dd_pct: float = 100.0, min_wr: float = 0.0,
                      mode: str = 'best_profit'):
    def objective(trial):
        try:
            s      = build_settings_from_trial_v2(trial, base_settings, mode)
            result = quick_backtest_v2(df, s)
            if min_trades > 0 and result['total_trades'] < min_trades:
                return 0.0
            if result['max_dd_seen'] > max_dd_pct / 100:
                return 0.0
            if mode == 'strict' and result['win_rate'] < min_wr / 100:
                return 0.0
            return result['score']
        except Exception:
            return 0.0
    return objective


# ── Haupt-Optimizer ──────────────────────────────────────────────────────────

def _make_progress_callback(n_trials: int, update_every: int = 25):
    """
    Callback der sich alle `update_every` Trials in-place aktualisiert.
    Keine neue Zeile — kein Spam.
    """
    import sys
    import time
    start = time.time()

    def callback(study, trial):
        n = trial.number + 1
        if n % update_every != 0 and n != n_trials:
            return
        best = study.best_value if study.best_value is not None else 0.0
        elapsed = time.time() - start
        eta = (elapsed / n) * (n_trials - n) if n > 0 else 0
        eta_str = f"{int(eta//60)}m{int(eta%60):02d}s" if eta > 0 else "--:--"
        bar_len  = 25
        filled   = int(bar_len * n / n_trials)
        bar      = "#" * filled + "-" * (bar_len - filled)
        line = f"  [{bar}] {n}/{n_trials}  Score: {best:.4f}  ETA: {eta_str}   "
        sys.stdout.write(f"\r{line}")
        sys.stdout.flush()
        if n == n_trials:
            sys.stdout.write("\n")
            sys.stdout.flush()

    return callback


def run_optimizer(symbol: str, timeframe: str, days: int,
                  n_trials: int, base_settings: dict,
                  test_fraction: float = 0.0,
                  min_trades: int = 0,
                  max_dd_pct: float = 100.0,
                  min_wr: float = 0.0,
                  mode: str = 'best_profit',
                  n_jobs: int = 1) -> dict:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    df = load_data(symbol, timeframe, days)
    if df.empty:
        print(f"  [FEHLER] Keine Daten fuer {symbol} {timeframe}")
        return {}

    # Walk-Forward Split
    if test_fraction > 0:
        split_idx = int(len(df) * (1 - test_fraction))
        df_train  = df.iloc[:split_idx]
        df_test   = df.iloc[split_idx:]
        print(f"  {len(df)} Kerzen | Train: {len(df_train)} | OOS-Test: {len(df_test)} | Starte Optimierung ({n_trials} Trials)...")
    else:
        df_train = df
        df_test  = None
        print(f"  {len(df)} Kerzen geladen. Starte Optimierung ({n_trials} Trials)...")

    if min_trades > 0:
        print(f"  Min-Trades-Constraint: {min_trades} Trades")

    update_every = max(1, n_trials // 20)
    callbacks    = [_make_progress_callback(n_trials, update_every)]

    # Use v2 engine (Attractor + Edge)
    study = optuna.create_study(direction='maximize')
    study.optimize(
        make_objective_v2(df_train, base_settings, min_trades, max_dd_pct, min_wr, mode),
        n_trials=n_trials,
        n_jobs=n_jobs,
        show_progress_bar=False,
        callbacks=callbacks,
    )

    best          = study.best_trial
    best_settings = build_settings_from_trial_v2(best, base_settings, mode)
    train_result  = quick_backtest_v2(df_train, best_settings)
    oos_result    = quick_backtest_v2(df_test, best_settings) if df_test is not None else None
    oos_score     = oos_result['score'] if oos_result else None
    oos_ratio     = round(oos_score / best.value, 3) if (oos_result and best.value > 0) else None
    oos_geo_mean  = oos_result['geo_mean'] if oos_result else None

    output = {
        'symbol':            symbol,
        'timeframe':         timeframe,
        'days':              days,
        'trials':            n_trials,
        'min_trades':        min_trades,
        'test_fraction':     test_fraction,
        'train_score':       best.value,
        'oos_score':         oos_score,
        'oos_ratio':         oos_ratio,
        'oos_geo_mean':      oos_geo_mean,
        'cycles':            train_result['total_cycles'],
        'total_trades':      train_result['total_trades'],
        'win_rate':          train_result['win_rate'],
        'avg_mult':          train_result['avg_mult'],
        'geo_mean':          train_result['geo_mean'],
        'target_multiplier': train_result['target_multiplier'],
        'target_hit_count':  train_result['target_hit_count'],
        'params': {
            'attractor': best_settings['attractor'],
            'edge':      best_settings['edge'],
            'risk':      best_settings['risk'],
            'cycle':     {'cycle_target_multiplier': best_settings['cycle']['cycle_target_multiplier']},
            'kelly':     best_settings['kelly'],
            'mode':      mode,
        },
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    # Speichern
    cfg_dir = Path(PROJECT_ROOT) / 'artifacts' / 'configs'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cfg_path = cfg_dir / f"config_{safe}.json"
    with open(cfg_path, 'w') as f:
        json.dump(output, f, indent=2)

    tgt  = train_result['target_multiplier']
    hits = train_result['target_hit_count']
    cyc  = train_result['total_cycles']
    trd  = train_result['total_trades']

    geo = train_result['geo_mean']
    if oos_result:
        valid     = "OK" if (oos_ratio is not None and oos_ratio >= 0.5) else "SCHWACH"
        oos_pct   = f"{oos_ratio*100:.0f}%" if oos_ratio is not None else "N/A"
        oos_sc    = f"{oos_score:.4f}" if oos_score is not None else "N/A"
        print(f"  Train: {best.value:.4f} | OOS: {oos_sc} ({oos_pct}) [{valid}] | Trades: {trd} | Cycles: {cyc} | WR: {train_result['win_rate']*100:.0f}% | GeoMean: {geo:.3f}x")
        print(f"  OOS  : Cycles: {oos_result['total_cycles']} | Trades: {oos_result['total_trades']} | WR: {oos_result['win_rate']*100:.0f}% | GeoMean: {oos_result['geo_mean']:.3f}x | Target: {oos_result['target_hit_count']}/{oos_result['total_cycles']}")
    else:
        print(f"  Score: {best.value:.4f} | Trades: {trd} | Cycles: {cyc} | WR: {train_result['win_rate']*100:.0f}% | GeoMean: {geo:.3f}x")

    if cyc:
        print(f"  Ziel: {tgt:.1f}x | Treffer: {hits}/{cyc} ({hits/cyc*100:.0f}%)")
    print(f"  Config gespeichert: {cfg_path.name}")

    return output


def _build_base_settings(minimal: dict, mode: str, capital: float, max_dd: float) -> dict:
    """
    Konstruiert vollstaendige base_settings (APEXBOT v2) aus minimaler settings.json.
    Parameter-Raum: Attractor-Thresholds + Edge-Engine.
    """
    return {
        'symbol':     minimal.get('symbol', 'SOL/USDT:USDT'),
        'timeframe':  minimal.get('timeframe', '1h'),
        'leverage':   minimal.get('leverage', 20),
        'margin_mode': minimal.get('margin_mode', 'isolated'),
        'cycle': {
            'start_capital_usdt':    capital,
            'max_trades_per_cycle':  minimal.get('max_trades_per_cycle', 4),
            'cycle_target_multiplier': 16.0,
        },
        'attractor': {
            'hurst_trend_min':   0.55,
            'adx_trend_min':     25,
            'hurst_range_max':   0.45,
            'adx_range_max':     20,
            'entropy_chaos_min': 0.70,
        },
        'edge': {
            'threshold':               0.30,
            'min_rr':                  1.50,
            'atr_sl_mult':             1.50,
            'base_p_win':              0.47,
            'volume_surge_multiplier': 1.50,
            'rsi_momentum_min':        50,
            'rsi_momentum_max':        75,
            'body_ratio_min':          0.50,
        },
        'risk': {'max_drawdown_pct': max_dd},
        'kelly': {
            'enabled':  mode == 'strict',
            'fraction': 0.25 if mode == 'strict' else 1.0,
        },
        'killswitch': {
            'enabled': False,
            'notify_telegram': minimal.get('notify_telegram', True),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol',        required=True)
    parser.add_argument('--timeframe',     required=True)
    parser.add_argument('--days',          type=int,   default=365)
    parser.add_argument('--trials',        type=int,   default=200)
    parser.add_argument('--capital',       type=float, default=50.0,  help='Startkapital in USDT')
    parser.add_argument('--mode',          default='best_profit',     help='strict | best_profit')
    parser.add_argument('--max-drawdown',  type=float, default=100.0, help='Max Drawdown %% (Constraint)')
    parser.add_argument('--min-win-rate',  type=float, default=0.0,   help='Min Win-Rate %% (nur strict)')
    parser.add_argument('--n-jobs',        type=int,   default=1,     help='CPU-Kerne (-1=alle)')
    parser.add_argument('--min-trades',    type=int,   default=0)
    parser.add_argument('--test-fraction', type=float, default=0.30)
    args = parser.parse_args()

    with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
        minimal = json.load(f)

    base = _build_base_settings(minimal, args.mode, args.capital, args.max_drawdown)

    mode_label = 'STRICT' if args.mode == 'strict' else 'BEST PROFIT'
    print(f"\n  Modus: {mode_label} | Max DD: {args.max_drawdown}% | Kapital: {args.capital} USDT | Trials: {args.trials}")

    # Min-Trades automatisch nach Timeframe wenn nicht gesetzt
    min_trades = args.min_trades
    if min_trades == 0:
        min_trades = {'1m': 50, '3m': 40, '5m': 35, '15m': 25, '30m': 20,
                      '1h': 15, '2h': 12, '4h': 10, '6h': 8, '1d': 5}.get(args.timeframe, 15)

    run_optimizer(
        args.symbol, args.timeframe, args.days, args.trials, base,
        test_fraction=args.test_fraction,
        min_trades=min_trades,
        max_dd_pct=args.max_drawdown,
        min_wr=args.min_win_rate,
        mode=args.mode,
        n_jobs=args.n_jobs,
    )


if __name__ == '__main__':
    main()
