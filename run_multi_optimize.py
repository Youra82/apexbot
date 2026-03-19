"""
run_multi_optimize.py — sequentielle Multi-Pair Optimierung ohne Rate-Limit-Probleme.

Laeuft alle Paare/Timeframes nacheinander, sammelt Ergebnisse und zeigt Ranking.

Usage:
  python run_multi_optimize.py [--trials 200] [--deep-trials 500]
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.analysis.optimizer import load_data, run_optimizer

# ── Konfiguration ─────────────────────────────────────────────────────────────

PAIRS = [
    ('BTC/USDT:USDT',  '30m', 120),
    ('BTC/USDT:USDT',  '1h',  270),
    ('ETH/USDT:USDT',  '30m', 120),
    ('ETH/USDT:USDT',  '1h',  270),
    ('SOL/USDT:USDT',  '30m', 120),
    ('SOL/USDT:USDT',  '1h',  270),
    ('XRP/USDT:USDT',  '30m', 120),
    ('XRP/USDT:USDT',  '1h',  270),
    ('DOGE/USDT:USDT', '30m', 120),
    ('DOGE/USDT:USDT', '1h',  270),
]

TEST_FRACTION = 0.30  # Walk-Forward OOS

# Min-Trades nach Timeframe
MIN_TRADES_MAP = {
    '15m': 20, '30m': 20, '1h': 15, '2h': 12, '4h': 10,
}

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials',       type=int, default=200, help='Optuna Trials pro Pair')
    parser.add_argument('--deep-trials',  type=int, default=500, help='Deep-Dive Trials (Top-3)')
    parser.add_argument('--skip-deep',    action='store_true',   help='Deep-Dive ueberspringen')
    args = parser.parse_args()

    settings_path = os.path.join(PROJECT_ROOT, 'settings.json')
    with open(settings_path) as f:
        base = json.load(f)

    print("")
    print("=" * 65)
    print(f"  APEXBOT Multi-Pair Optimizer  |  {len(PAIRS)} Paare  |  {args.trials} Trials")
    print("=" * 65)

    results = []

    for idx, (symbol, tf, days) in enumerate(PAIRS, 1):
        label = f"{symbol.split('/')[0]} {tf}"
        print(f"\n[{idx}/{len(PAIRS)}] {label}  ({days} Tage, {args.trials} Trials)")
        print("-" * 55)

        min_trades = MIN_TRADES_MAP.get(tf, 15)
        base['symbol']    = symbol
        base['timeframe'] = tf

        try:
            r = run_optimizer(
                symbol       = symbol,
                timeframe    = tf,
                days         = days,
                n_trials     = args.trials,
                base_settings= base,
                test_fraction= TEST_FRACTION,
                min_trades   = min_trades,
            )
            if r:
                r['label'] = label
                results.append(r)
        except Exception as e:
            print(f"  [FEHLER] {e}")

        # Kurze Pause um Rate-Limits zu vermeiden
        if idx < len(PAIRS):
            time.sleep(2)

    # ── Ranking ──────────────────────────────────────────────────────────────
    if not results:
        print("\n[FEHLER] Keine Ergebnisse.")
        return

    results.sort(key=lambda r: r.get('geo_mean', 0.0), reverse=True)

    print("\n")
    print("=" * 65)
    print("  RANKING (nach Geo-Mean, Train)")
    print("=" * 65)
    print(f"  {'#':>2}  {'Pair':18}  {'GeoMean':>8}  {'OOS GM':>7}  {'WR':>5}  {'Trades':>6}  {'OOS':>5}")
    print(f"  {'--'}  {'-'*18}  {'-'*8}  {'-'*7}  {'-----'}  {'------'}  {'-----'}")

    top3 = []
    for rank, r in enumerate(results, 1):
        oos_geo  = r.get('oos_geo_mean')
        oos_str  = f"{oos_geo:.3f}x" if oos_geo is not None else "  N/A "
        oos_ratio= r.get('oos_ratio')
        oos_ok   = "[OK]" if (oos_ratio is not None and oos_ratio >= 0.5) else "[??]"
        geo      = r.get('geo_mean', 0.0)
        print(f"  {rank:>2}  {r['label']:18}  {geo:.3f}x  {oos_str:>7}  "
              f"{r.get('win_rate',0)*100:>4.0f}%  {r.get('total_trades',0):>6}  {oos_ok}")
        if rank <= 3:
            top3.append(r)

    print("=" * 65)

    # OOS GeoMean aus gespeicherten Config-Files nachladen
    _reload_oos_geo(results)

    # ── Deep-Dive Top-3 ──────────────────────────────────────────────────────
    if args.skip_deep or not top3:
        return

    print(f"\n\n  Deep-Dive: Top-3 mit {args.deep_trials} Trials")

    print("=" * 65)

    deep_results = []
    for r in top3:
        sym = r['symbol']
        tf  = r['timeframe']
        days = next((d for s, t, d in PAIRS if s == sym and t == tf), 270)
        label= r['label']
        print(f"\n  Deep: {label}")
        print("-" * 55)
        min_trades = MIN_TRADES_MAP.get(tf, 15)
        base['symbol']    = sym
        base['timeframe'] = tf
        try:
            dr = run_optimizer(
                symbol       = sym,
                timeframe    = tf,
                days         = days,
                n_trials     = args.deep_trials,  # noqa: this is correct attribute name
                base_settings= base,
                test_fraction= TEST_FRACTION,
                min_trades   = min_trades,
            )
            if dr:
                dr['label'] = label
                deep_results.append(dr)
        except Exception as e:
            print(f"  [FEHLER] {e}")
        time.sleep(2)

    if deep_results:
        deep_results.sort(key=lambda r: r.get('geo_mean', 0.0), reverse=True)
        print("\n")
        print("=" * 65)
        print("  DEEP-DIVE RANKING")
        print("=" * 65)
        for rank, r in enumerate(deep_results, 1):
            oos_ratio = r.get('oos_ratio', None)
            oos_ok    = "[OK]" if (oos_ratio and oos_ratio >= 0.5) else "[??]"
            geo       = r.get('geo_mean', 0.0)
            print(f"  {rank}.  {r['label']:18}  GeoMean: {geo:.3f}x  "
                  f"Trades: {r.get('total_trades',0)}  OOS: {oos_ok}")
        print("=" * 65)
        best = deep_results[0]
        print(f"\n  EMPFEHLUNG: {best['label']}")
        print(f"  Config: artifacts/configs/config_{best['symbol'].replace('/','').replace(':','')}_{best['timeframe']}.json")


def _reload_oos_geo(results: list):
    """Liest OOS GeoMean aus gespeicherten Config-Files nach."""
    cfg_dir = Path(PROJECT_ROOT) / 'artifacts' / 'configs'
    for r in results:
        sym  = r.get('symbol', '')
        tf   = r.get('timeframe', '')
        safe = f"{sym.replace('/', '').replace(':', '')}_{tf}"
        cfg  = cfg_dir / f"config_{safe}.json"
        if cfg.exists():
            try:
                with open(cfg) as f:
                    data = json.load(f)
                r['oos_geo_mean'] = data.get('oos_geo_mean')
            except Exception:
                pass


if __name__ == '__main__':
    main()
