# src/apexbot/analysis/backtest.py
"""
APEXBOT Backtest — simuliert Cycle-Logik auf historischen Daten.
Zeigt wie oft FUSION feuert, Win-Rate, und Cycle-Outcome-Verteilung.

Usage:
  python src/apexbot/analysis/backtest.py --symbol BTC/USDT:USDT --timeframe 15m --days 180
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import numpy as np
import ccxt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.modules.radar import detect_attractor, compute_atr
from apexbot.modules.fusion import compute_edge

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('backtest')


# ── Daten laden ──────────────────────────────────────────────────────────────

def fetch_historical(symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    exchange.load_markets()

    tf_ms   = exchange.parse_timeframe(timeframe) * 1000
    since   = exchange.milliseconds() - days * 24 * 3600 * 1000
    all_rows = []

    logger.info(f"Lade {days} Tage {symbol} {timeframe}...")
    while since < exchange.milliseconds() - tf_ms:
        try:
            rows = exchange.fetch_ohlcv(symbol, timeframe, since, 1000)
            if not rows:
                break
            all_rows.extend(rows)
            since = rows[-1][0] + tf_ms
            import time; time.sleep(exchange.rateLimit / 1000)
        except Exception as e:
            logger.warning(f"Fehler beim Laden: {e}")
            break

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='last')]
    logger.info(f"{len(df)} Kerzen geladen ({df.index[0]} → {df.index[-1]})")
    return df


# ── Backtest-Engine ──────────────────────────────────────────────────────────

def run_backtest_v2(df: pd.DataFrame, settings: dict) -> dict:
    """
    APEXBOT v2 backtest: Attractor + Edge Engine with liquidity zone TP.
    """
    leverage    = settings['leverage']
    start_cap   = settings['cycle']['start_capital_usdt']
    max_trades  = settings['cycle']['max_trades_per_cycle']
    max_dd      = settings['risk']['max_drawdown_pct'] / 100
    target_mult = settings['cycle'].get('cycle_target_multiplier', 16.0)

    kelly_cfg  = settings.get('kelly', {})
    use_kelly  = kelly_cfg.get('enabled', False)
    kelly_frac = kelly_cfg.get('fraction', 1.0)

    WARMUP = 60

    cycles         = []
    current_cycle  = {'trades': [], 'capital': start_cap}
    capital        = start_cap
    peak_capital   = start_cap
    in_trade       = False
    trade_entry    = None
    total_signals  = 0
    skipped_chaos  = 0
    skipped_edge   = 0

    for i in range(WARMUP, len(df)):
        window = df.iloc[max(0, i - 200):i + 1]
        row    = df.iloc[i]

        if in_trade:
            high  = row['high']
            low   = row['low']
            entry = trade_entry

            hit_sl = low  <= entry['sl'] if entry['dir'] == 'long' else high >= entry['sl']
            hit_tp = high >= entry['tp'] if entry['dir'] == 'long' else low  <= entry['tp']

            if hit_tp or hit_sl:
                won       = hit_tp
                ep        = entry['price']
                sl_pct    = entry['sl_dist'] / ep if ep > 0 else 0.0
                tp_pct    = entry['tp_dist'] / ep if ep > 0 else 0.0
                pnl_pct   = tp_pct if won else -sl_pct
                pnl_usdt  = entry['margin'] * leverage * pnl_pct
                capital   = max(start_cap * 0.01, capital + pnl_usdt)
                peak_capital = max(peak_capital, capital)

                current_cycle['trades'].append({
                    'won':          won,
                    'pnl':          pnl_usdt,
                    'capital_after': capital,
                    'direction':    entry['dir'],
                    'entry_time':   entry['entry_time'].isoformat(),
                    'exit_time':    df.index[i].isoformat(),
                    'entry_price':  entry['price'],
                    'exit_price':   entry['tp'] if won else entry['sl'],
                    'sl_price':     entry['sl'],
                    'tp_price':     entry['tp'],
                    'outcome':      'WIN' if won else 'LOSS',
                    'edge':         entry.get('edge', 0.0),
                    'p_win':        entry.get('p_win', 0.0),
                    'rr':           entry.get('rr', 0.0),
                    'attractor':    entry.get('attractor', 'TREND'),
                    'cycle_phase':  len(current_cycle['trades']) + 1,
                })
                in_trade = False

                n_trades   = len(current_cycle['trades'])
                drawdown   = 1 - capital / peak_capital if peak_capital > 0 else 0
                hit_target = capital >= start_cap * target_mult

                if hit_target or n_trades >= max_trades or drawdown >= max_dd:
                    current_cycle['end_capital']  = capital
                    current_cycle['start_capital'] = start_cap
                    current_cycle['multiplier']    = capital / start_cap
                    current_cycle['reason'] = (
                        'TARGET_HIT' if hit_target else
                        ('MAX_TRADES' if n_trades >= max_trades else 'DRAWDOWN')
                    )
                    cycles.append(current_cycle)
                    capital        = start_cap
                    peak_capital   = start_cap
                    current_cycle  = {'trades': [], 'capital': start_cap}
            continue

        # Attractor filter
        attractor = detect_attractor(window, settings)
        if attractor == 'CHAOS':
            skipped_chaos += 1
            continue

        # Edge check (full version with liquidity zones)
        edge_result = compute_edge(window, settings)
        total_signals += 1

        if edge_result['mode'] == 'SKIP' or edge_result['direction'] == 'none':
            skipped_edge += 1
            continue

        ep        = float(row['close'])
        atr_sl    = edge_result['atr_sl']
        direction = edge_result['direction']
        min_rr    = settings['edge'].get('min_rr', 1.5)
        tp_price  = edge_result['tp_price']
        tp_dist   = abs(tp_price - ep)

        if direction == 'long':
            sl_price = ep - atr_sl
        else:
            sl_price = ep + atr_sl

        if use_kelly:
            p   = edge_result['p_win']
            rr  = edge_result['rr']
            f   = (p * rr - (1 - p)) / rr
            margin = capital * min(kelly_frac, max(0.05, f))
        else:
            margin = capital * kelly_frac

        trade_entry = {
            'dir':        direction,
            'sl':         sl_price,
            'tp':         tp_price,
            'price':      ep,
            'margin':     margin,
            'sl_dist':    atr_sl,
            'tp_dist':    tp_dist,
            'entry_time': df.index[i],
            'edge':       edge_result['edge'],
            'p_win':      edge_result['p_win'],
            'rr':         edge_result['rr'],
            'attractor':  attractor,
        }
        in_trade = True

    # Auswertung
    all_trades    = [t for c in cycles for t in c['trades']]
    total_trades  = len(all_trades)
    wins          = sum(1 for t in all_trades if t['won'])
    win_rate      = wins / total_trades * 100 if total_trades > 0 else 0

    cycle_results    = [c['multiplier'] for c in cycles]
    avg_mult         = np.mean(cycle_results) if cycle_results else 1.0
    max_mult         = max(cycle_results)      if cycle_results else 1.0
    cycles_above1    = sum(1 for m in cycle_results if m > 1)
    target_hit_count = sum(1 for c in cycles if c.get('reason') == 'TARGET_HIT')

    return {
        'symbol':            settings['symbol'],
        'timeframe':         settings['timeframe'],
        'candles':           len(df),
        'total_signals':     total_signals,
        'skipped_chaos':     skipped_chaos,
        'skipped_edge':      skipped_edge,
        'total_trades':      total_trades,
        'win_rate_pct':      round(win_rate, 1),
        'total_cycles':      len(cycles),
        'avg_multiplier':    round(avg_mult, 2),
        'max_multiplier':    round(max_mult, 2),
        'cycles_above_1x':   cycles_above1,
        'target_multiplier': target_mult,
        'target_hit_count':  target_hit_count,
        'cycles':            cycles,
        'trades':            all_trades,
        'engine':            'v2',
    }


def run_backtest(df: pd.DataFrame, settings: dict) -> dict:
    return run_backtest_v2(df, settings)


def print_results(r: dict):
    print("\n" + "=" * 55)
    print(f"  APEXBOT BACKTEST [v2] — {r['symbol']} {r['timeframe']}")
    print("=" * 55)
    print(f"  Kerzen gesamt:       {r['candles']}")
    print(f"  CHAOS gefiltert:     {r.get('skipped_chaos', 0)}")
    print(f"  Edge gefiltert:      {r.get('skipped_edge', 0)}")
    print(f"  Trades simuliert:    {r['total_trades']}")
    print(f"  Win-Rate:            {r['win_rate_pct']}%")
    print(f"  Cycles:              {r['total_cycles']}")
    print(f"  Avg Cycle-Mult:      {r['avg_multiplier']}x")
    print(f"  Max Cycle-Mult:      {r['max_multiplier']}x")
    print(f"  Cycles > 1x (Gewinn): {r['cycles_above_1x']}")
    print(f"  Ziel ({r['target_multiplier']:.0f}x) erreicht: {r['target_hit_count']} / {r['total_cycles']}")
    print("")
    if r['cycles']:
        print("  Letzte 10 Cycles:")
        for c in r['cycles'][-10:]:
            trades_str = f"{len(c['trades'])} Trades"
            mult_str   = f"{c['multiplier']:.2f}x"
            reason     = c.get('reason', '?')
            print(f"    {mult_str:8s}  {trades_str:10s}  [{reason}]")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol',    default=None, help='Symbol z.B. BTC/USDT:USDT')
    parser.add_argument('--timeframe', default=None, help='Timeframe z.B. 15m')
    parser.add_argument('--days',      default=180,  type=int, help='Historische Tage')
    args = parser.parse_args()

    settings_path = os.path.join(PROJECT_ROOT, 'settings.json')
    with open(settings_path) as f:
        settings = json.load(f)

    if args.symbol:
        settings['symbol'] = args.symbol
    if args.timeframe:
        settings['timeframe'] = args.timeframe

    # Pair-spezifische Config laden (aus artifacts/configs/) falls vorhanden
    sym  = settings['symbol']
    tf   = settings['timeframe']
    safe = f"{sym.replace('/', '').replace(':', '')}_{tf}"
    cfg_path = Path(PROJECT_ROOT) / 'artifacts' / 'configs' / f'config_{safe}.json'
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            params = cfg.get('params', {})
            # v2 config
            if params.get('attractor'): settings['attractor'] = params['attractor']
            if params.get('edge'):      settings['edge']      = params['edge']
            if params.get('risk'):      settings['risk']      = params['risk']
            if params.get('kelly'):     settings['kelly']     = params['kelly']
            if params.get('leverage'):  settings['leverage']  = params['leverage']
            if params.get('cycle', {}).get('cycle_target_multiplier'):
                settings.setdefault('cycle', {})['cycle_target_multiplier'] = \
                    params['cycle']['cycle_target_multiplier']
            logger.info(f"Pair-Config geladen: {cfg_path.name}")
        except Exception as e:
            logger.warning(f"Pair-Config Ladefehler: {e}")

    df = fetch_historical(settings['symbol'], settings['timeframe'], args.days)
    if df.empty:
        logger.error("Keine Daten geladen.")
        sys.exit(1)

    results = run_backtest(df, settings)
    print_results(results)

    # Ergebnis speichern
    out_path = Path(PROJECT_ROOT) / 'artifacts' / 'backtest_result.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results_save = {k: v for k, v in results.items() if k not in ('cycles', 'trades')}
    results_save['timestamp'] = datetime.now(timezone.utc).isoformat()
    with open(out_path, 'w') as f:
        json.dump(results_save, f, indent=2)
    logger.info(f"Ergebnis gespeichert: {out_path}")

    # Learner aus historischen Daten vortrainieren
    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
        from apexbot.modules.learner import seed_from_backtest
        seed_from_backtest(results)
    except Exception as e:
        logger.warning(f"Learner-Seeding fehlgeschlagen (nicht kritisch): {e}")


if __name__ == '__main__':
    main()
