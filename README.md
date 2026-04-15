
# APEXBOT — Professioneller Swingtrading-Bot

Vollautomatischer Swingtrading-Bot für Bitget (Perpetual Swaps) mit professioneller Multi-Faktor-Edge-Engine, Backtesting und Optuna-Optimierung.

---

## Strategie — Wie ein echter Profi

ApexBot handelt nicht blind nach einem Indikator, sondern kombiniert mehrere unabhängige Faktoren zu einem **Edge Score** — genau wie ein erfahrener Swing-Trader:

### Einstiegslogik (LONG — SHORT ist spiegelverkehrt)

| Bedingung | Punkte | Warum |
|-----------|--------|-------|
| EMA21 > EMA50, Preis über EMA21 | Pflicht-Gate | Trend muss aligned sein |
| EMA21 > EMA50 > EMA200 | +1 Pt | Volle Trend-Stack-Bestätigung (Macro-Bias) |
| RSI 45–75 (nicht überkauft) | +2 Pt | Momentum gesund, kein Extrempunkt |
| Volumen > 1.5× 20-Bar-Durchschnitt | +2 Pt | Smart Money Participation |
| Letzte Kerze bullish, Body ≥ 50% Range | +2 Pt | Preis-Aktion bestätigt Richtung |
| Marktstruktur: Higher High + Higher Low | +2 Pt | Trenstruktur intakt |
| Preis nahe EMA21 (Pullback < 1.5%) | +1 Pt | Entry an Value, nicht am Top |

**Max 10 Punkte** — gehandelt wird ab Score ≥ threshold (Standard: 0.30 = 30%).

### Stop Loss & Take Profit

- **SL**: ATR × Multiplikator, verankert am letzten Swing-Low/High mit 0.2× ATR Puffer
- **TP**: Nächste Volume-Cluster-Zone (Liquidity Zone) mit mindestens R:R 1.5:1

### Markt-Regime-Filter (RADAR)

Bevor die Edge-Engine überhaupt rechnet, klassifiziert RADAR den Markt:

| Regime | Bedingung | Aktion |
|--------|-----------|--------|
| **TREND** | Hurst ≥ 0.55 + ADX ≥ 25 | Handeln |
| **RANGE** | Hurst ≤ 0.45 + ADX ≤ 20 | Handeln (Reversal-Modus) |
| **CHAOS** | Entropie > 0.70 | **Kein Trade** |

---

## Pipeline

```
RADAR (Attractor)  →  FUSION (Edge Score)  →  COMPOUNDER (Sizing)  →  ORDER
Hurst/Entropy/ADX      EMA+RSI+Vol+Candle      Kelly / Full-Send       Bitget
                        + Marktstruktur
                        + Liquidity-TP
```

---

## Installation & Nutzung

### 1. Klonen

```bash
git clone https://github.com/Youra82/apexbot.git
cd apexbot
```

### 2. Installieren

```bash
./install.sh
```

Legt die virtuelle Python-Umgebung an, installiert alle Abhängigkeiten und erstellt `secret.json` aus dem Beispiel.

### 3. API-Keys eintragen

```bash
nano secret.json
```

```json
{
  "apexbot": [
    {
      "apiKey": "DEIN_BITGET_API_KEY",
      "secret": "DEIN_BITGET_SECRET",
      "password": "DEIN_BITGET_PASSPHRASE"
    }
  ],
  "telegram": {
    "bot_token": "DEIN_TELEGRAM_BOT_TOKEN",
    "chat_id": "DEINE_CHAT_ID"
  }
}
```

> Telegram ist optional. Wenn nicht gewünscht: `"notify_telegram": false` in `settings.json`.

### 4. Einstellungen prüfen

```bash
nano settings.json
```

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

### 5. Optimierung & Backtest

```bash
./run_pipeline.sh
```

Oder direkt:

```bash
# Optimizer (empfohlen vor Live-Trading)
python src/apexbot/analysis/optimizer.py \
  --symbol SOL/USDT:USDT --timeframe 1h \
  --days 365 --trials 200 --mode best_profit

# Backtest
python src/apexbot/analysis/backtest.py \
  --symbol SOL/USDT:USDT --timeframe 1h --days 180
```

### 6. Live-Trading (Cronjob)

```bash
crontab -e
# Folgendes eintragen:
*/5 * * * * cd /pfad/apexbot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

---

## Skripte

| Skript | Beschreibung |
|--------|-------------|
| `./run_pipeline.sh` | Interaktive Optimierungs-Pipeline (Optuna Walk-Forward) |
| `./show_results.sh` | Backtests, Configs, Charts anzeigen |
| `./show_status.sh` | Live Cycle-Status und Kapital |
| `./run_tests.sh` | Alle Tests ausführen |
| `./push_configs.sh` | Optimierte Configs ins Repo pushen |
| `./update.sh` | Bot auf neuesten Stand bringen |
| `./install.sh` | Einmalige Installation |

### `./run_pipeline.sh` — Optimierungs-Pipeline

**Interaktive Eingaben:**

| Prompt | Beschreibung | Beispiel |
|--------|-------------|---------|
| Alte Configs löschen? | Empfohlen bei Neustart | `j` / `n` |
| Handelspaar(e) | Coins, Leerzeichen-getrennt | `SOL ETH BTC` |
| Zeitfenster | Timeframes, Leerzeichen-getrennt | `1h 4h` |
| Startdatum | Datum oder `a` für Automatik | `2024-01-01` / `a` |
| Startkapital | USDT | `50` |
| CPU-Kerne | `-1` = alle Kerne | `-1` |
| Trials | Anzahl Optuna-Trials | `200` |
| Modus | `1` Streng (Kelly + DD-Kontrolle) · `2` Best Profit | `2` |
| Max Drawdown % | Constraint für Optimizer | `50` |

**Empfohlene Rückblickzeiträume:**

| Timeframe | Empfehlung |
|-----------|-----------|
| 5m, 15m | 30 – 90 Tage |
| 30m, 1h | 180 – 365 Tage |
| 2h, 4h | 365 – 730 Tage |
| 6h, 1d | 1095 – 1825 Tage |

---

## Dateistruktur

```
apexbot/
├── settings.json                    # Minimale Benutzerkonfiguration
├── secret.json                      # API-Keys (nicht im Repo)
├── master_runner.py                 # Autopilot-Runner (Cron)
├── run_pipeline.sh                  # Optimierungs-Pipeline
├── show_results.sh                  # Ergebnisse & Backtests
├── show_status.sh                   # Live Cycle-Status
├── run_tests.sh                     # Pytest
├── push_configs.sh                  # Optimierte Configs pushen
├── install.sh                       # Einmalige Installation
└── update.sh                        # Git-Update
│
├── src/apexbot/
│   ├── modules/
│   │   ├── radar.py                 # RADAR: Attractor-Erkennung (TREND/RANGE/CHAOS)
│   │   ├── fusion.py                # FUSION: Profi-Edge-Engine (10-Punkte-Score)
│   │   ├── liquidity.py             # Volume-Profil & Liquidity-TP-Zonen
│   │   ├── candle_shape.py          # Kerzenmuster-Analyse
│   │   ├── compounder.py            # Cycle-State & Kelly-Positionsgröße
│   │   └── learner.py               # Trade-Logging & adaptive Ziele
│   ├── analysis/
│   │   ├── optimizer.py             # Optuna Walk-Forward Optimizer
│   │   ├── backtest.py              # Vollständiger Cycle-Backtest
│   │   └── show_results.py          # Ergebnisdarstellung & Charts
│   ├── strategy/
│   │   └── run.py                   # Live-Trading Entry Point (signal/check Modi)
│   └── utils/
│       ├── exchange.py              # Bitget CCXT Wrapper
│       ├── trade_manager.py         # Order-Ausführung (Entry + SL + TP)
│       └── telegram.py              # Push-Benachrichtigungen
│
└── artifacts/
    ├── configs/                     # Optimierte Configs (pro Pair/TF)
    ├── cycles/                      # Abgeschlossene Cycle-Historien
    ├── state/                       # Aktueller Bot-State (global_state.json)
    └── results/                     # Backtest- & Optimizer-Ergebnisse
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

Alle Trading-Parameter (Indikator-Schwellenwerte, SL/TP-Logik etc.) werden vom Optimizer automatisch optimiert und in `artifacts/configs/` gespeichert.

---

## Optimizer — Parameter-Raum

Der Optimizer (Optuna, Walk-Forward 70/30) sucht die optimale Kombination aus:

| Parameter | Bereich | Beschreibung |
|-----------|---------|-------------|
| `attractor.hurst_trend_min` | 0.50–0.65 | Hurst-Schwelle für TREND-Regime |
| `attractor.adx_trend_min` | 20–35 | ADX-Schwelle für TREND-Regime |
| `attractor.entropy_chaos_min` | 0.55–0.90 | Entropie-Schwelle für CHAOS-Regime |
| `edge.threshold` | 0.0–0.8 | Mindest-Edge-Score für Trade |
| `edge.min_rr` | 1.0–3.0 | Mindest Risk/Reward |
| `edge.atr_sl_mult` | 0.5–3.0 | SL = ATR × Multiplikator |
| `edge.volume_surge_multiplier` | 1.2–3.0 | Volumen-Surge-Schwelle |
| `edge.rsi_momentum_min/max` | 42–82 | RSI Momentum-Zone |
| `edge.body_ratio_min` | 0.25–0.75 | Mindest-Kerzenkörper |
| `cycle.target_multiplier` | 1.5–20x | Cycle-Ziel-Multiplikator |
| `leverage` | 3–50x | Hebel |
| `kelly.fraction` | 0.1–1.0 | Max Kelly-Anteil (nur Strict-Modus) |

**Scoring:** `GeoMean(Cycle-Mults) × log1p(Cycles) × (1 + Hit-Rate)` — bevorzugt Konsistenz statt Ausreißer.

**Validierung:** OOS-Ratio = Out-of-Sample Score / Train Score  
- ≥ 0.5 → Config valid  
- < 0.5 → Overfit — mehr Daten, weniger Trials, oder Threshold erhöhen

---

## Coin & Timeframe Empfehlungen

### Geeignete Timeframes

| TF | Hurst-Fenster | Entropie-Fenster | ADX(14) | EMA50 | Geeignet |
|---|---|---|---|---|---|
| 15m | 5h | 5h | 3.5h | 12.5h | ⚠️ |
| 30m | 10h | 10h | 7h | 25h | ⚠️ |
| **1h** | **20h** | **20h** | **14h** | **50h** | **✅✅** |
| **2h** | **40h** | **40h** | **28h** | **100h** | **✅✅** |
| **4h** | **80h** | **80h** | **56h** | **200h** | **✅✅** |
| 6h | 120h | 120h | 84h | 300h | ✅ |
| 1d | 20d | 20d | 14d | 50d | ✅ |

> Ab 1h hat der Hurst-Exponent genug Datenpunkte für statistische Verlässlichkeit.

### Coin-Eignung

| Coin | Hurst-Profil | Entropie | FUSION-Signale | Bewertung |
|---|---|---|---|---|
| **BTC** | Hoch (H ~0.6–0.7 in Bullphasen) | Klare Reduktion vor Breakouts | Starke EMA/RSI/Vol-Signale | ✅✅ Beste Wahl |
| **ETH** | Hoch — ähnlich BTC | Gutes Entropie-Profil | Klare FUSION-Signale | ✅✅ Sehr gut |
| **SOL** | Gut — explosive Phasen | Starke Reduktion | Hohe Vol-Surges | ✅ Gut |
| **BNB** | Gut — stabile Persistenz | Klares Profil | Moderate Signale | ✅ Gut |
| **AVAX** | Gut — klare Trends | Gutes Signal | Gute Vol-Patterns | ✅ Gut |
| **INJ** | Gut — explosive Phasen | Gutes Signal | Hohe Momentum-Signale | ✅ Gut |
| **XRP** | Mittel — nahe 0.5 beim Ranging | Mittel | Unregelmäßig | ⚠️ Mittel |
| **ADA** | Schwach — häufig Random Walk | Wenig Struktur | Schwache Signale | ⚠️ Schwach |
| **DOGE** | Nicht vorhanden — Sentiment | Dauerhaft chaotisch | Unbrauchbar | ❌ |
| **SHIB/PEPE** | Null — reine Pumps | Dauerhaft CHAOS | Keine Basis | ❌❌ |

### Empfohlene Kombinationen

| Rang | Kombination | Begründung |
|---|---|---|
| 🥇 | BTC / ETH — 1h oder 2h | Bester Hurst, stärkste FUSION-Signale, viele Trades |
| 🥈 | SOL 1h | Explosive Persistenz, hohe Volumen-Surges |
| 🥉 | BTC 4h | Robustester Hurst, weniger aber qualitativ hohe Signale |
| 4 | BNB / AVAX / INJ — 2h | Stabile bis explosive Persistenz-Phasen |
| ❌ | 15m / 30m | Hurst-Fenster (5–10h) zu kurz für verlässliche Messung |
| ❌ | DOGE / SHIB / PEPE | Chronisch CHAOS-Regime — Bot tradet dort nie |

---

## Hinweis zur Anpassung

Die Scoring-Logik liegt in [src/apexbot/modules/fusion.py](src/apexbot/modules/fusion.py).  
Die Regime-Erkennung in [src/apexbot/modules/radar.py](src/apexbot/modules/radar.py).  
Den Live-Trading-Loop in [src/apexbot/strategy/run.py](src/apexbot/strategy/run.py).

Alle Parameter sind über den Optimizer (`./run_pipeline.sh`) automatisch optimierbar — manuelle Anpassung nur für experimentelle Zwecke empfohlen.
