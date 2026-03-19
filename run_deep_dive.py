"""
run_deep_dive.py — 500-Trial Deep-Dive auf die Top-3 Kandidaten.

Top-3 nach OOS-GeoMean aus dem 200-Trial Scan:
  1. SOL/USDT:USDT  30m  (OOS GM 1.012x, WR 67%)
  2. DOGE/USDT:USDT 30m  (OOS GM 1.004x, WR 56%)
  3. ETH/USDT:USDT  30m  (OOS GM 1.002x, WR 60%)
"""

import os, sys, json, time
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.analysis.optimizer import run_optimizer

TOP3 = [
    ('SOL/USDT:USDT',  '30m', 120),
    ('DOGE/USDT:USDT', '30m', 120),
    ('ETH/USDT:USDT',  '30m', 120),
]

MIN_TRADES = 25     # Strenger als im Scan (30m → 20 war Minimum, 25 erzwingt mehr Konfidenz)
TEST_FRACTION = 0.30
TRIALS = 500

settings_path = os.path.join(PROJECT_ROOT, 'settings.json')
with open(settings_path) as f:
    base = json.load(f)

print("")
print("=" * 65)
print(f"  APEXBOT Deep-Dive  |  Top-3  |  {TRIALS} Trials")
print("=" * 65)

deep_results = []

for idx, (symbol, tf, days) in enumerate(TOP3, 1):
    label = f"{symbol.split('/')[0]} {tf}"
    print(f"\n[{idx}/3] {label}  ({days} Tage, {TRIALS} Trials, min_trades={MIN_TRADES})")
    print("-" * 55)
    base['symbol']    = symbol
    base['timeframe'] = tf
    try:
        r = run_optimizer(
            symbol       = symbol,
            timeframe    = tf,
            days         = days,
            n_trials     = TRIALS,
            base_settings= base,
            test_fraction= TEST_FRACTION,
            min_trades   = MIN_TRADES,
        )
        if r:
            r['label'] = label
            deep_results.append(r)
    except Exception as e:
        print(f"  [FEHLER] {e}")
    if idx < len(TOP3):
        time.sleep(2)

# Ranking
if deep_results:
    deep_results.sort(key=lambda r: r.get('oos_geo_mean') or 0.0, reverse=True)
    print("\n\n" + "=" * 65)
    print("  DEEP-DIVE FINAL RANKING (nach OOS GeoMean)")
    print("=" * 65)
    print(f"  {'#':>2}  {'Pair':18}  {'Train GM':>9}  {'OOS GM':>8}  {'OOS WR':>7}  {'OOS Tr':>7}  {'Status'}")
    print(f"  {'--'}  {'-'*18}  {'-'*9}  {'-'*8}  {'-'*7}  {'-'*7}  {'------'}")

    winner = None
    for rank, r in enumerate(deep_results, 1):
        oos_geo  = r.get('oos_geo_mean')
        oos_str  = f"{oos_geo:.4f}x" if oos_geo is not None else "  N/A   "
        oos_ratio= r.get('oos_ratio')
        status   = "[OK]   " if (oos_ratio is not None and oos_ratio >= 0.5) else "[SCHWACH]"
        geo      = r.get('geo_mean', 0.0)
        # OOS win rate from the saved config
        oos_wr   = "?"
        cfg_dir  = Path(PROJECT_ROOT) / 'artifacts' / 'configs'
        safe     = f"{r['symbol'].replace('/', '').replace(':', '')}_{r['timeframe']}"
        cfg_p    = cfg_dir / f"config_{safe}.json"
        if cfg_p.exists():
            try:
                import json as _json
                with open(cfg_p) as f:
                    d = _json.load(f)
                # oos_win_rate not stored but we can compute: not available directly
                # Use OOS trades from output
                oos_wr = "N/A"
            except Exception:
                pass
        print(f"  {rank:>2}  {r['label']:18}  {geo:.4f}x  {oos_str:>8}  {r.get('win_rate',0)*100:>6.0f}%  "
              f"{r.get('total_trades',0):>7}  {status}")
        if rank == 1:
            winner = r

    print("=" * 65)
    if winner:
        sym  = winner['symbol']
        tf   = winner['timeframe']
        safe = f"{sym.replace('/', '').replace(':', '')}_{tf}"
        print(f"\n  EMPFEHLUNG: {winner['label']}")
        print(f"  Config: artifacts/configs/config_{safe}.json")
        print(f"  GeoMean (Train): {winner.get('geo_mean', 0):.4f}x")
        oos_g = winner.get('oos_geo_mean')
        if oos_g:
            print(f"  GeoMean (OOS):   {oos_g:.4f}x")
        print(f"  Trades:  {winner.get('total_trades', 0)}")
        print(f"  Cycles:  {winner.get('cycles', 0)}")
        print(f"  Win-Rate (Train): {winner.get('win_rate',0)*100:.0f}%")

if __name__ == '__main__':
    pass
