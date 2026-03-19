# APEXBOT v2 — Adaptive Probabilistic Cycle Engine

Vollautomatischer Futures-Trading-Bot für Bitget (Perpetual Swaps).

**Prinzip:** Kapital startet pro Cycle bei 50 USDT → wird durch aufeinanderfolgende Trades multipliziert → Reset nach Ziel oder Max-Trades.

**Mathematische Basis:** Phase-Space Attractors · Probabilistisches Edge-Trading · Fractional Kelly · Liquidity Gravitation · Walk-Forward Validation

---

## Architektur

```
MARKT → ATTRACTOR → EDGE → KELLY-SIZING → TRADE → CYCLE
```

### ATTRACTOR — Phase-Space Erkennung

Klassifiziert den Marktzustand in drei Phasen:

| Zustand | Bedingung | Aktion |
|---------|-----------|--------|
| `TREND` | Hurst ≥ threshold · ADX ≥ threshold · Entropie niedrig | Edge berechnen |
| `RANGE` | Hurst niedrig · ADX niedrig | Edge berechnen |
| `CHAOS` | Entropie > threshold | Kein Trade |

### EDGE — Probabilistische Handelsentscheidung

```
E = P(win) × RR − P(loss) × 1.0
Trade nur wenn E ≥ edge_threshold
```

**P(win) wird geschätzt aus:**

| Signal | Beitrag |
|--------|---------|
| Basis-Wahrscheinlichkeit | 0.47 |
| Volume Surge (> N × MA) | +0.05 |
| EMA-Ausrichtung (20/50) | +0.03 |
| RSI Momentum-Zone | +0.04 |
| Kerzenkörper stark (≥ 60%) | +0.06 |
| Hammer / Shooting Star | +0.04 |
| Gegenläufiger Wick | −0.05 |

**TP via Liquidity Zones:** Volumen-Profil der letzten 100 Kerzen → High-Volume Preiscluster → nächste Zone mit RR ≥ min_rr als TP-Target.

**SL via ATR:** `SL = ATR × atr_sl_mult` (marktadaptiv, kein fester Prozentsatz).

### KELLY — Positionsgröße

- `kelly.enabled = false` → All-In (voller Kapitaleinsatz)
- `kelly.enabled = true` → `f* = (P(win)×RR − P(loss)) / RR`, begrenzt durch `fraction`

### CYCLE — Compounding

- Start: `start_capital_usdt` (Standard: 50 USDT)
- Max Trades pro Cycle: 4
- Cycle endet bei: `TARGET_HIT` | `MAX_TRADES` | `DRAWDOWN`
- Nach Cycle-Ende: Kapital-Reset auf Startwert

---

## Quickstart

```bash
# 1. Installieren
./install.sh

# 2. API-Key in secret.json eintragen
# {"apexbot": [{"apiKey": "...", "secret": "...", "password": "..."}],
#  "telegram": {"bot_token": "...", "chat_id": "..."}}

# 3. Pipeline: Daten laden, optimieren, Config speichern
./run_pipeline.sh

# 4. Ergebnisse ansehen
./show_results.sh

# 5. Bot live starten (Cron alle 5 Minuten)
crontab -e
# */5 * * * * cd /pfad/apexbot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

---

## Konfiguration

### settings.json — Nur Benutzervorgaben

```json
{
  "symbol":               "SOL/USDT:USDT",
  "timeframe":            "1h",
  "leverage":             20,
  "margin_mode":          "isolated",
  "start_capital_usdt":   50.0,
  "max_trades_per_cycle": 4,
  "notify_telegram":      true
}
```

Alle Trading-Parameter (Attractor-Thresholds, Edge-Threshold, ATR-Mult, Min-RR, Kelly-Fraction) werden **automatisch durch den Optimizer** bestimmt und in `artifacts/configs/` gespeichert.

### run_pipeline.sh — Optimierungs-Pipeline

Interaktive Prompts:

| Parameter | Beschreibung |
|-----------|-------------|
| Handelspaar(e) | z.B. `SOL ETH BTC` |
| Zeitfenster | z.B. `1h 4h` |
| Startdatum | `JJJJ-MM-TT` oder `a` für Auto |
| Startkapital | USDT (Standard: 50) |
| CPU-Kerne | `-1` für alle |
| Trials | Anzahl Optuna-Trials (Standard: 200) |
| Modus | `1` Streng (Kelly + DD-Kontrolle) · `2` Best Profit (All-In) |
| Max Drawdown % | Constraint für Optimizer |

---

## Dateistruktur

```
apexbot/
├── settings.json                    # Minimale Benutzerkonfiguration
├── secret.json                      # API-Keys (nicht im Repo)
├── master_runner.py                 # Autopilot-Runner
├── run_pipeline.sh                  # Optimierungs-Pipeline
├── show_results.sh                  # Ergebnisse & Backtests
├── install.sh                       # Einmalige Installation
│
├── src/apexbot/
│   ├── modules/
│   │   ├── radar.py                 # Attractor-Erkennung (TREND/RANGE/CHAOS)
│   │   ├── fusion.py                # Edge-Engine (E = P×RR − P_loss)
│   │   ├── liquidity.py             # Volumen-Profil & TP-Zonen
│   │   ├── candle_shape.py          # Kerzenmuster-Analyse (P(win)-Beitrag)
│   │   ├── compounder.py            # Cycle-State & Positionsgröße
│   │   └── learner.py               # Trade-Logging
│   ├── analysis/
│   │   ├── optimizer.py             # Optuna Walk-Forward Optimizer
│   │   ├── backtest.py              # Vollständiger Backtest (mit Liquidity-TP)
│   │   └── show_results.py          # Ergebnisdarstellung
│   ├── strategy/
│   │   └── run.py                   # Live-Trading Entry Point
│   └── utils/
│       ├── exchange.py              # Bitget CCXT Wrapper
│       ├── trade_manager.py         # Order-Ausführung & SL/TP
│       └── telegram.py              # Benachrichtigungen
│
└── artifacts/
    ├── configs/                     # Optimierte Configs (pro Pair/TF)
    └── results/                     # Backtest- & Optimizer-Ergebnisse
```

---

## Optimizer — Parameter-Raum

Der Optimizer (Optuna, Walk-Forward 70/30) sucht:

| Parameter | Bereich | Beschreibung |
|-----------|---------|-------------|
| `attractor.hurst_trend_min` | 0.50–0.65 | Hurst-Schwelle für TREND |
| `attractor.adx_trend_min` | 20–35 | ADX-Schwelle für TREND |
| `attractor.entropy_chaos_min` | 0.55–0.90 | Entropie-Schwelle für CHAOS |
| `edge.threshold` | 0.0–0.8 | Mindest-Edge E für Trade |
| `edge.min_rr` | 1.0–3.0 | Mindest Risk/Reward |
| `edge.atr_sl_mult` | 0.5–3.0 | SL = ATR × Multiplikator |
| `edge.volume_surge_multiplier` | 1.2–3.0 | Volumen-Surge-Schwelle |
| `edge.rsi_momentum_min/max` | 45–82 | RSI Momentum-Zone |
| `edge.body_ratio_min` | 0.35–0.75 | Mindest-Kerzenkörper |
| `cycle.target_multiplier` | 1.5–20x | Cycle-Ziel |
| `kelly.fraction` | 0.1–1.0 | Max Kelly-Anteil (nur Strict) |

**Scoring:** `GeoMean × log(1 + Cycles) × (1 + Hit-Rate)` — bevorzugt konsistente Gewinne statt Ausreißer.

---

## Scoring & Validierung

```
Score = GeoMean(Cycle-Multiplier) × log1p(Anzahl Cycles) × (1 + Target-Hit-Rate)
```

- **OOS-Ratio ≥ 0.5** → Config valid (Out-of-Sample hält ≥ 50% der Train-Performance)
- **OOS-Ratio < 0.5** → Overfit — Config verwerfen, mehr Daten oder weniger Trials

---

## Edge-Mathematik

Beispiel mit P(win) = 0.55, RR = 2.0:
```
E = 0.55 × 2.0 − 0.45 × 1.0 = 1.10 − 0.45 = 0.65  → TRADE
```

Beispiel mit P(win) = 0.45, RR = 1.2:
```
E = 0.45 × 1.2 − 0.55 × 1.0 = 0.54 − 0.55 = −0.01  → SKIP
```

Auch bei 50/50-Chance ist der Bot profitabel wenn RR > 1.0 — Edge kommt aus Signalfilterung + Liquidity-TP.
