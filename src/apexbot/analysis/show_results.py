# src/apexbot/analysis/show_results.py
"""
APEXBOT Show Results — Python-Backend

Modi (aufgerufen von show_results.sh):
  --mode 1  Einzel-Backtest          (frische Simulation je Pair)
  --mode 2  Manuelle Symbol-Auswahl  (Auswahl aus gespeicherten Backtests)
  --mode 3  Automatische Symbol-Opt. (bestes Pair automatisch ermitteln)
  --mode 4  Config-Bibliothek        (gespeicherte Optimizer-Ergebnisse)
  --mode 5  Interaktive Charts       (Equity-Kurve + Telegram)
"""

import os
import sys
import json
import argparse
import copy
from pathlib import Path
from datetime import datetime, timezone

import numpy as np


class _NumpyEncoder(json.JSONEncoder):
    """Konvertiert numpy-Typen für JSON-Serialisierung."""
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        return super().default(obj)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.analysis.backtest import fetch_historical, run_backtest

G   = '\033[0;32m'
Y   = '\033[1;33m'
R   = '\033[0;31m'
C   = '\033[0;36m'
NC  = '\033[0m'
SEP = '=' * 72
SEP2 = '-' * 72

RESULTS_DIR = Path(PROJECT_ROOT) / 'artifacts' / 'results'
CONFIGS_DIR = Path(PROJECT_ROOT) / 'artifacts' / 'configs'
CYCLES_DIR  = Path(PROJECT_ROOT) / 'artifacts' / 'cycles'
STATE_FILE  = Path(PROJECT_ROOT) / 'artifacts' / 'state' / 'global_state.json'


def load_settings() -> dict:
    with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
        return json.load(f)


def load_settings_for_pair(symbol: str, timeframe: str) -> dict:
    """
    Lädt pair-spezifische Parameter aus artifacts/configs/ falls vorhanden,
    ansonsten Fallback auf settings.json.
    RADAR, FUSION, RISK und cycle_target_multiplier kommen aus der Pair-Config.
    """
    base = load_settings()
    safe = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cfg_path = Path(PROJECT_ROOT) / 'artifacts' / 'configs' / f'config_{safe}.json'
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            params = cfg.get('params', {})
            if params.get('radar'):
                base['radar'] = params['radar']
            if params.get('fusion'):
                base['fusion'] = params['fusion']
            if params.get('risk'):
                base['risk'] = params['risk']
            if params.get('cycle', {}).get('cycle_target_multiplier'):
                base['cycle']['cycle_target_multiplier'] = params['cycle']['cycle_target_multiplier']
        except Exception:
            pass
    return base


def load_secret() -> dict:
    p = os.path.join(PROJECT_ROOT, 'secret.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def load_saved_results() -> list:
    """Laedt alle gespeicherten Backtest-Ergebnisse aus artifacts/results/."""
    if not RESULTS_DIR.exists():
        return []
    rows = []
    for f in sorted(RESULTS_DIR.glob("backtest_*.json")):
        try:
            r = json.load(open(f))
            if r.get('total_trades', 0) > 0:
                rows.append(r)
        except Exception:
            pass
    rows.sort(key=lambda x: x.get('avg_multiplier', 0), reverse=True)
    return rows


def print_results_table(rows: list):
    print(f"\n{SEP}")
    print(f"  {'Nr':<4} {'Markt':<24} {'TF':<6} {'Trades':>7} {'WR':>8} {'AvgX':>7} {'MaxX':>7} {'>1x':>8}")
    print(f"  {SEP2}")
    for i, r in enumerate(rows, 1):
        wr  = f"{r.get('win_rate_pct', 0)}%"
        ag  = r.get('avg_multiplier', 1.0)
        mx  = r.get('max_multiplier', 1.0)
        ab1 = r.get('cycles_above_1x', 0)
        tot = r.get('total_cycles', 0)
        pnl_sign = '+' if ag >= 1.0 else ' '
        print(
            f"  {i:<4} {r.get('symbol','?'):<24} {r.get('timeframe','?'):<6}"
            f" {r.get('total_trades',0):>7} {wr:>8}"
            f" {pnl_sign}{ag-1:.0%}".rjust(8) +
            f" {mx:.2f}x  {ab1}/{tot}"
        )
    print(f"{SEP}")


# ── Mode 1: Einzel-Backtest ──────────────────────────────────────────────────

def mode_einzel_backtest(symbols: list, timeframes: list, days: int, capital: float):
    settings = load_settings()
    results  = []

    print(f"\n{SEP}")
    print(
        f"  apexbot — Einzel-Backtest\n"
        f"  Kapital: {capital} USDT | Pairs: {len(symbols)*len(timeframes)} | {days}d History"
    )
    print(f"{SEP}\n")

    for sym in symbols:
        for tf in timeframes:
            s = load_settings_for_pair(sym, tf)
            s['symbol']    = sym
            s['timeframe'] = tf
            s['cycle']['start_capital_usdt'] = capital

            print(f"  Lade Daten: {sym} ({tf}) | {days}d History")
            df = fetch_historical(sym, tf, days)
            if df.empty:
                print(f"  [FEHLER] Keine Daten für {sym} ({tf}).\n")
                continue

            print(f"  {len(df)} Kerzen geladen.")
            r = run_backtest(df, s)

            print(f"\n{SEP}")
            print(f"  BACKTEST: {sym} ({tf})")
            print(f"{SEP}")
            print(f"  Trades simuliert:    {r['total_trades']}")
            print(f"  Win-Rate:            {r['win_rate_pct']}%")
            print(f"  Cycles:              {r['total_cycles']}")
            print(f"  Avg Cycle-Mult:      {r['avg_multiplier']}x")
            print(f"  Max Cycle-Mult:      {r['max_multiplier']}x")
            print(f"  Cycles > 1x:         {r['cycles_above_1x']} / {r['total_cycles']}")
            print(f"  RADAR gefiltert:     {r['skipped_regime']}")
            print(f"  FUSION gefiltert:    {r['skipped_score']}")
            print(f"{SEP}\n")

            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            safe = f"{sym.replace('/', '').replace(':', '')}_{tf}"
            out  = RESULTS_DIR / f"backtest_{safe}.json"
            save = {k: v for k, v in r.items() if k != 'cycles'}
            save.update({'capital': capital, 'days': days, 'timestamp': datetime.now(timezone.utc).isoformat()})
            json.dump(save, open(out, 'w'), indent=2, cls=_NumpyEncoder)
            print(f"  Backtest-Ergebnisse gespeichert: {out}")
            results.append(r)

    if len(results) > 1:
        print(f"\n{SEP}")
        print(f"  ZUSAMMENFASSUNG — alle Pairs")
        print(f"{SEP}")
        print(f"  {'Markt':<24} {'TF':<6} {'Trades':>7} {'WR':>8} {'AvgX':>7} {'MaxX':>7} {'>1x':>8}")
        print(f"  {SEP2}")
        for r in sorted(results, key=lambda x: x['avg_multiplier'], reverse=True):
            print(
                f"  {r['symbol']:<24} {r['timeframe']:<6}"
                f" {r['total_trades']:>7} {r['win_rate_pct']:>7}%"
                f" {r['avg_multiplier']:>6.2f}x {r['max_multiplier']:>6.2f}x"
                f" {r['cycles_above_1x']:>4}/{r['total_cycles']}"
            )
        print(f"{SEP}")


# ── Mode 2: Manuelle Symbol-Auswahl ─────────────────────────────────────────

def mode_manual_auswahl(selection: str):
    rows = load_saved_results()
    if not rows:
        print(f"\n  {R}Keine gespeicherten Backtest-Ergebnisse gefunden.{NC}")
        print("  Bitte zuerst Mode 1 ausführen.\n")
        return

    print(f"\n{SEP}")
    print(f"  Verfügbare Pairs  (AvgX = durchschnittlicher Cycle-Multiplikator)")
    print_results_table(rows)

    if not selection:
        return

    try:
        indices = [int(x.strip()) - 1 for x in selection.replace(',', ' ').split()]
        selected = [rows[i] for i in indices if 0 <= i < len(rows)]
    except Exception:
        print(f"  {R}Ungültige Eingabe.{NC}")
        return

    if not selected:
        return

    print(f"\n{SEP}")
    print(f"  Ausgewählte Pairs — {len(selected)} Pair(s)")
    print(f"{SEP}")
    print(f"  {'Markt':<24} {'TF':<6} {'Trades':>7} {'WR':>8} {'AvgX':>7} {'MaxX':>7} {'>1x':>8}")
    print(f"  {SEP2}")
    for r in selected:
        print(
            f"  {r.get('symbol','?'):<24} {r.get('timeframe','?'):<6}"
            f" {r.get('total_trades',0):>7} {r.get('win_rate_pct',0):>7}%"
            f" {r.get('avg_multiplier',1):>6.2f}x {r.get('max_multiplier',1):>6.2f}x"
            f" {r.get('cycles_above_1x',0):>4}/{r.get('total_cycles',0)}"
        )

    total_trades = sum(r.get('total_trades', 0) for r in selected)
    avg_wr   = np.mean([r.get('win_rate_pct', 0) for r in selected])
    avg_mult = np.mean([r.get('avg_multiplier', 1) for r in selected])
    best     = max(selected, key=lambda x: x.get('avg_multiplier', 0))

    print(f"  {SEP2}")
    print(f"  Zusammenfassung ({len(selected)} Pairs):")
    print(f"  Trades gesamt:     {total_trades}")
    print(f"  Ø Win-Rate:        {avg_wr:.1f}%")
    print(f"  Ø Cycle-Mult:      {avg_mult:.2f}x")
    print(f"  Bestes Pair:       {best.get('symbol')} ({best.get('timeframe')}) — {best.get('avg_multiplier')}x")
    print(f"{SEP}")


# ── Mode 3: Automatische Symbol-Opt. ────────────────────────────────────────

def mode_auto_opt(max_dd_pct: float = 100.0):
    rows = load_saved_results()
    if not rows:
        print(f"\n  {R}Keine gespeicherten Backtest-Ergebnisse gefunden.{NC}")
        print("  Bitte zuerst Mode 1 ausführen.\n")
        return

    # Score = avg_mult × win_rate_cycles × log(1 + total_cycles)
    def score(r):
        wr   = r.get('cycles_above_1x', 0) / max(r.get('total_cycles', 1), 1)
        mult = r.get('avg_multiplier', 1.0)
        n    = r.get('total_cycles', 0)
        return mult * wr * np.log1p(n)

    ranked = sorted(rows, key=score, reverse=True)

    print(f"\n{SEP}")
    print(f"  apexbot — Automatische Symbol-Optimierung")
    print(f"  Score = Ø-Mult × Cycle-WR × log(1 + Cycles)")
    print(f"{SEP}")
    print(f"  {'Nr':<4} {'Markt':<24} {'TF':<6} {'Score':>7} {'AvgX':>7} {'WR':>8} {'Cycles':>7}")
    print(f"  {SEP2}")
    for i, r in enumerate(ranked[:15], 1):
        s   = score(r)
        wr  = r.get('cycles_above_1x', 0) / max(r.get('total_cycles', 1), 1) * 100
        print(
            f"  {i:<4} {r.get('symbol','?'):<24} {r.get('timeframe','?'):<6}"
            f" {s:>7.3f} {r.get('avg_multiplier',1):>6.2f}x {wr:>7.1f}%"
            f" {r.get('total_cycles',0):>7}"
        )

    best = ranked[0]
    wr   = best.get('cycles_above_1x', 0) / max(best.get('total_cycles', 1), 1) * 100

    print(f"{SEP}")
    print(f"\n  Optimales Pair: {best.get('symbol')} ({best.get('timeframe')})")
    print(f"  Score:          {score(best):.3f}")
    print(f"  Avg Mult:       {best.get('avg_multiplier')}x")
    print(f"  Cycle Win-Rate: {wr:.1f}%")
    print(f"  Cycles >1x:     {best.get('cycles_above_1x')}/{best.get('total_cycles')}")

    # Empfehlung: settings.json updaten?
    print(f"\n  Kapital geändert → settings.json aktualisieren?")
    print(f"  Symbol: {best.get('symbol')} | Timeframe: {best.get('timeframe')}")
    answer = input("  Überschreibe settings.json? (j/n): ").strip().lower()
    if answer in ('j', 'y'):
        s = load_settings()
        s['symbol']    = best.get('symbol')
        s['timeframe'] = best.get('timeframe')
        json.dump(s, open(os.path.join(PROJECT_ROOT, 'settings.json'), 'w'), indent=2)
        print(f"  {G}✔ settings.json aktualisiert.{NC}")
    print(f"{SEP}")


# ── Mode 4: Config-Bibliothek ────────────────────────────────────────────────

def mode_config_bibliothek():
    if not CONFIGS_DIR.exists() or not list(CONFIGS_DIR.glob("config_*.json")):
        print(f"\n  {R}Keine optimierten Configs gefunden.{NC}")
        print("  Bitte zuerst run_pipeline.sh (Optimizer) ausführen.\n")
        return

    files = sorted(CONFIGS_DIR.glob("config_*.json"))
    configs = []
    for f in files:
        try:
            configs.append(json.load(open(f)))
        except Exception:
            pass

    configs.sort(key=lambda x: x.get('score', 0), reverse=True)

    print(f"\n{SEP}")
    print(f"  apexbot — Config-Bibliothek ({len(configs)} optimierte Configs)")
    print(f"{SEP}")

    for c in configs:
        sym    = c.get('symbol', '?')
        tf     = c.get('timeframe', '?')
        score  = c.get('score', 0)
        cycles = c.get('cycles', 0)
        wr     = c.get('win_rate', 0) * 100
        mult   = c.get('avg_mult', 1.0)
        ts     = c.get('timestamp', '?')[:10]
        trials = c.get('trials', '?')

        print(f"\n  {C}{'─' * 55}{NC}")
        print(f"  {sym} ({tf}) | Score: {score:.3f} | Stand: {ts} | Trials: {trials}")
        print(f"  {'─' * 55}")
        tgt      = c.get('target_multiplier', '?')
        hits     = c.get('target_hit_count', '?')
        tgt_str  = f"{tgt:.1f}x" if isinstance(tgt, float) else str(tgt)
        hits_str = f"{hits}/{cycles}" if isinstance(hits, int) and isinstance(cycles, int) else str(hits)
        print(f"  Cycles: {cycles} | Win-Rate: {wr:.0f}% | Avg Mult: {mult:.2f}x")
        print(f"  Ziel:   {tgt_str} | Treffer: {hits_str}")
        print(f"  RADAR:  ADX≥{c['params']['radar']['adx_min']} | "
              f"ATR≥{c['params']['radar']['atr_multiplier_min']} | "
              f"BB≥{c['params']['radar']['bb_width_min']}")
        print(f"  FUSION: Vol≥{c['params']['fusion']['volume_surge_multiplier']}x | "
              f"Body≥{c['params']['fusion']['body_ratio_min']:.0%} | "
              f"RSI {c['params']['fusion']['rsi_momentum_min']}-{c['params']['fusion']['rsi_momentum_max']} | "
              f"Score≥{c['params']['fusion']['min_score_full_send']}/5")
        print(f"  RISK:   SL {c['params']['risk']['stop_loss_pct']}% | "
              f"TP {c['params']['risk']['take_profit_multiplier']}x R:R")

    print(f"\n{SEP}")


# ── Mode 5: Interaktive Charts (Candlestick + Entry/Exit-Marker) ─────────────

def _select_pairs_interactive() -> list:
    """Zeigt alle gespeicherten Backtest-Ergebnisse und lässt Auswahl zu."""
    rows = load_saved_results()
    if not rows:
        print(f"\n  {R}Keine gespeicherten Backtest-Ergebnisse gefunden.{NC}")
        print("  Bitte zuerst Mode 1 ausführen.\n")
        return []

    w = 70
    print("\n" + "=" * w)
    print("  Verfügbare Pairs:  (AvgX = Ø Cycle-Multiplikator, voller Zeitraum)")
    print("=" * w)
    for i, r in enumerate(rows, 1):
        sym  = r.get('symbol', '?')
        tf   = r.get('timeframe', '?')
        ag   = r.get('avg_multiplier', 1.0)
        safe = f"{sym.replace('/', '').replace(':', '')}_{tf}"
        sign = '+' if ag >= 1.0 else ''
        pnl_str = f"  [{sign}{ag-1:.0%}]"
        print(f"  {i:2d}) {safe}{pnl_str}")
    print("=" * w)

    print("\n  Wähle Pair(s):")
    print("  Einzeln: z.B. '1' oder '5'")
    print("  Mehrfach: z.B. '1,3,5' oder '1 3 5'")
    raw = input("\n  Auswahl: ").strip()

    selected = []
    for token in raw.replace(',', ' ').split():
        try:
            idx = int(token) - 1
            if 0 <= idx < len(rows) and rows[idx] not in selected:
                selected.append(rows[idx])
        except ValueError:
            pass
    if not selected:
        print("  Ungültige Auswahl.")
    return selected


def _create_apex_chart(symbol: str, timeframe: str, df, trades: list,
                       result: dict, capital: float):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("  plotly nicht installiert. pip install plotly")
        return None

    close = df['close']
    ma20  = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        specs=[[{'secondary_y': True}],
               [{'secondary_y': False}],
               [{'secondary_y': False}],
               [{'secondary_y': False}]],
        vertical_spacing=0.022,
        row_heights=[0.45, 0.18, 0.18, 0.19],
        subplot_titles=['', 'Volumen', 'RSI  (Momentum-Filter)', 'FUSION Score  (Signalqualität)'],
    )

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['open'], high=df['high'],
        low=df['low'], close=df['close'], name='OHLC',
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350',
    ), row=1, col=1, secondary_y=False)

    # Bollinger Bands
    fig.add_trace(go.Scatter(
        x=df.index, y=bb_upper, mode='lines',
        line=dict(color='rgba(255,167,38,0.4)', width=1, dash='dot'),
        name='BB Upper', showlegend=False,
    ), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=df.index, y=bb_lower, mode='lines',
        line=dict(color='rgba(255,167,38,0.4)', width=1, dash='dot'),
        fill='tonexty', fillcolor='rgba(255,167,38,0.04)',
        name='BB Lower', showlegend=False,
    ), row=1, col=1, secondary_y=False)

    # Entry/Exit Marker + SL/TP Linien
    entry_long_x, entry_long_y, entry_long_txt   = [], [], []
    entry_short_x, entry_short_y, entry_short_txt = [], [], []
    exit_win_x, exit_win_y   = [], []
    exit_loss_x, exit_loss_y = [], []

    sorted_trades = sorted(trades, key=lambda t: str(t.get('entry_time', '')))
    for t in sorted_trades:
        et  = t.get('entry_time')
        xt  = t.get('exit_time')
        tip = (f"Score: {t.get('fusion_score',0)}/5<br>"
               f"SL: {t.get('sl_price',0):.4f} | TP: {t.get('tp_price',0):.4f}")
        if t.get('direction') == 'long':
            entry_long_x.append(et);  entry_long_y.append(t.get('entry_price', 0))
            entry_long_txt.append(tip)
        else:
            entry_short_x.append(et); entry_short_y.append(t.get('entry_price', 0))
            entry_short_txt.append(tip)
        if t.get('outcome') == 'WIN':
            exit_win_x.append(xt);  exit_win_y.append(t.get('exit_price', 0))
        else:
            exit_loss_x.append(xt); exit_loss_y.append(t.get('exit_price', 0))
        if et and xt:
            fig.add_shape(type='line', x0=et, x1=xt, y0=t['sl_price'], y1=t['sl_price'],
                          line=dict(color='rgba(239,68,68,0.45)', width=1, dash='dot'))
            fig.add_shape(type='line', x0=et, x1=xt, y0=t['tp_price'], y1=t['tp_price'],
                          line=dict(color='rgba(34,197,94,0.45)', width=1, dash='dot'))

    if entry_long_x:
        fig.add_trace(go.Scatter(x=entry_long_x, y=entry_long_y, mode='markers',
            marker=dict(color='#26a69a', symbol='triangle-up', size=14,
                        line=dict(width=1, color='#ffffff')),
            name='Entry Long', text=entry_long_txt,
            hovertemplate='%{text}<extra>Entry Long</extra>',
        ), row=1, col=1, secondary_y=False)
    if entry_short_x:
        fig.add_trace(go.Scatter(x=entry_short_x, y=entry_short_y, mode='markers',
            marker=dict(color='#ffa726', symbol='triangle-down', size=14,
                        line=dict(width=1, color='#ffffff')),
            name='Entry Short', text=entry_short_txt,
            hovertemplate='%{text}<extra>Entry Short</extra>',
        ), row=1, col=1, secondary_y=False)
    if exit_win_x:
        fig.add_trace(go.Scatter(x=exit_win_x, y=exit_win_y, mode='markers',
            marker=dict(color='#00bcd4', symbol='circle', size=11,
                        line=dict(width=1, color='#ffffff')),
            name='Exit TP ✓',
        ), row=1, col=1, secondary_y=False)
    if exit_loss_x:
        fig.add_trace(go.Scatter(x=exit_loss_x, y=exit_loss_y, mode='markers',
            marker=dict(color='#ef5350', symbol='x', size=11,
                        line=dict(width=2, color='#ef5350')),
            name='Exit SL ✗',
        ), row=1, col=1, secondary_y=False)

    # Equity-Kurve (rechte Y-Achse)
    eq_cap = capital; eq_times = []; eq_vals = []
    for t in sorted_trades:
        eq_cap = max(0, eq_cap + t.get('pnl', 0))
        eq_times.append(t.get('entry_time'))
        eq_vals.append(round(eq_cap, 4))
    if eq_times:
        fig.add_trace(go.Scatter(x=eq_times, y=eq_vals, name='Equity',
            line=dict(color='#5c9bd6', width=1.5),
            hovertemplate='Equity: %{y:.2f} USDT<extra></extra>',
        ), row=1, col=1, secondary_y=True)

    # Volumen
    vol_colors = ['#26a69a' if c >= o else '#ef5350'
                  for c, o in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(x=df.index, y=df['volume'], marker_color=vol_colors,
        name='Volumen', showlegend=False, opacity=0.65,
        hovertemplate='Vol: %{y:,.0f}<extra></extra>',
    ), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=df.index, y=rsi, mode='lines',
        line=dict(color='#ce93d8', width=1.5),
        fill='tozeroy', fillcolor='rgba(206,147,216,0.08)',
        name='RSI(14)', showlegend=False,
        hovertemplate='RSI: %{y:.1f}<extra></extra>',
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash='dot', line_color='rgba(239,68,68,0.5)',   row=3, col=1)
    fig.add_hline(y=50, line_dash='dot', line_color='rgba(255,255,255,0.2)', row=3, col=1)
    fig.add_hline(y=30, line_dash='dot', line_color='rgba(38,166,154,0.5)',  row=3, col=1)
    if sorted_trades:
        sig_rsi = []
        for t in sorted_trades:
            try:    sig_rsi.append(float(rsi.asof(t['entry_time'])))
            except: sig_rsi.append(50.0)
        fig.add_trace(go.Scatter(x=[t['entry_time'] for t in sorted_trades], y=sig_rsi,
            mode='markers', marker=dict(symbol='circle-open', size=9, color='#ce93d8',
                                        line=dict(width=2)),
            showlegend=False, hovertemplate='Signal RSI: %{y:.1f}<extra></extra>',
        ), row=3, col=1)

    # FUSION Score
    if sorted_trades:
        score_colors = ['#26a69a' if t['direction'] == 'long' else '#ffa726' for t in sorted_trades]
        score_txt    = [f"Score: {t.get('fusion_score',0)}/5<br>Dir: {t['direction'].upper()} | {t['outcome']}"
                        for t in sorted_trades]
        fig.add_trace(go.Bar(
            x=[t['entry_time'] for t in sorted_trades],
            y=[t.get('fusion_score', 0) for t in sorted_trades],
            marker_color=score_colors, opacity=0.8,
            name='FUSION Score', showlegend=False,
            text=score_txt, hovertemplate='%{text}<extra></extra>',
        ), row=4, col=1)
        fig.add_hline(y=4, line_dash='dot', line_color='rgba(255,255,255,0.3)', row=4, col=1)

    n = result['total_trades']; wr = result['win_rate_pct']
    agx = result['avg_multiplier']; mxc = result['total_cycles']
    fig.update_layout(
        title=dict(
            text=f"{symbol} {timeframe} — APEXBOT | Trades: {n} | WR: {wr}% | AvgX: {agx}x | Cycles: {mxc}",
            font=dict(size=13), x=0.5, xanchor='center',
        ),
        height=1100, hovermode='x unified', template='plotly_dark',
        dragmode='zoom', xaxis_rangeslider_visible=False,
        legend=dict(orientation='h', yanchor='bottom', y=1.01,
                    xanchor='center', x=0.5, font=dict(size=11)),
        margin=dict(l=60, r=70, t=80, b=40),
        yaxis2=dict(title='Equity (USDT)', showgrid=False,
                    tickfont=dict(color='#5c9bd6'), title_font=dict(color='#5c9bd6')),
    )
    fig.update_yaxes(title_text='Preis', row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text='Vol',   row=2, col=1)
    fig.update_yaxes(title_text='RSI',   row=3, col=1, tickformat='.0f')
    fig.update_yaxes(title_text='Score', row=4, col=1, range=[0, 5])
    for row in range(1, 5):
        fig.update_xaxes(rangeslider_visible=False, row=row, col=1)
    return fig


def mode_interactive_charts(symbol: str, timeframe: str, days: int,
                             capital: float, send_telegram: bool):
    settings = load_settings()
    s = copy.deepcopy(settings)
    s['symbol']    = symbol
    s['timeframe'] = timeframe
    s['cycle']['start_capital_usdt'] = capital

    print(f"\n--- {symbol} ({timeframe}) ---")
    print(f"  Lade {days} Tage History...")
    df = fetch_historical(symbol, timeframe, days)
    if df.empty:
        print(f"  Keine Daten — übersprungen.")
        return

    print(f"  {len(df)} Kerzen geladen.")
    print("  Führe Backtest durch...")
    result = run_backtest(df, s)
    trades = result.get('trades', [])
    print(f"  {result['total_trades']} Trades | WR: {result['win_rate_pct']}% | AvgX: {result['avg_multiplier']}x")
    print("  Erstelle Chart...")

    fig = _create_apex_chart(symbol, timeframe, df, trades, result, capital)
    if fig is None:
        return

    safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    out_path = Path('/tmp') / f"apexbot_{safe}.html"
    fig.write_html(str(out_path))
    print(f"  ✅ Chart gespeichert: {out_path}")

    if send_telegram:
        secret = load_secret()
        tg     = secret.get('telegram', {})
        token  = tg.get('bot_token')
        chat   = tg.get('chat_id')
        if token and chat:
            from apexbot.utils.telegram import send_message
            msg = (
                f"APEX Chart: {symbol} ({timeframe})\n"
                f"{'─' * 28}\n"
                f"Trades:    {result['total_trades']}\n"
                f"Win-Rate:  {result['win_rate_pct']}%\n"
                f"Cycles:    {result['total_cycles']}\n"
                f"Avg Mult:  {result['avg_multiplier']}x\n"
                f"Cycles>1x: {result['cycles_above_1x']}/{result['total_cycles']}"
            )
            send_message(token, chat, msg)
            print(f"  ✅ Telegram: {symbol} {timeframe} gesendet.")
        else:
            print("  Kein Telegram-Token/Chat-ID in secret.json — übersprungen.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode',       type=int, default=4)
    parser.add_argument('--symbols',    default='')
    parser.add_argument('--timeframes', default='')
    parser.add_argument('--days',       type=int, default=180)
    parser.add_argument('--capital',    type=float, default=50.0)
    parser.add_argument('--selection',  default='')
    parser.add_argument('--telegram',   action='store_true')
    args = parser.parse_args()

    settings   = load_settings()
    symbols    = args.symbols.split()    if args.symbols    else [settings['symbol']]
    timeframes = args.timeframes.split() if args.timeframes else [settings['timeframe']]

    if args.mode == 1:
        mode_einzel_backtest(symbols, timeframes, args.days, args.capital)
    elif args.mode == 2:
        mode_manual_auswahl(args.selection)
    elif args.mode == 3:
        mode_auto_opt()
    elif args.mode == 4:
        mode_config_bibliothek()
    elif args.mode == 5:
        selected = _select_pairs_interactive()
        if not selected:
            return

        raw_days = input("\n  History-Tage [Standard: 180]: ").strip()
        days = int(raw_days) if raw_days.isdigit() else 180

        raw_cap = input("  Startkapital in USDT [Standard: 50]: ").strip()
        try:
            capital = float(raw_cap) if raw_cap else 50.0
        except ValueError:
            capital = 50.0

        raw_tg = input("  Per Telegram senden? (j/n) [Standard: n]: ").strip().lower()
        send_telegram = raw_tg in ('j', 'y')

        for r in selected:
            mode_interactive_charts(
                r['symbol'], r['timeframe'], days, capital, send_telegram
            )


if __name__ == '__main__':
    main()
