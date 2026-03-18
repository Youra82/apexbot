# APEXBOT — Adaptive Compounding Trading Bot

APEXBOT ist ein vollautomatischer Futures-Trading-Bot für Bitget (Perpetual Swaps), der auf einem **Cycle-Compounding-Prinzip** basiert: Das Kapital startet pro Cycle bei einem definierten Betrag (Standard: 50 USDT), wird durch aufeinanderfolgende Trades multipliziert und bei Erreichen eines optimierten Ziel-Multiplikators automatisch zurückgesetzt. Jeder Cycle wird archiviert und das Muster statistisch ausgewertet.

---

## Architektur

```
RADAR → FUSION → COMPOUNDER → Trade
```

### RADAR — Regime Detection
Bewertet den Markt anhand von 4 Indikatoren und gibt ein Regime zurück:

| Regime   | Bedeutung                              |
|----------|----------------------------------------|
| `HUNT`   | Markt aktiv, alle Filter grün → trade  |
| `STALK`  | Markt in Bewegung, aber nicht eindeutig|
| `SLEEP`  | Kein Trend, kein Volumen               |
| `RETREAT`| Extremes Momentum / Überhitzung        |

**Indikatoren:**
- **ATR** (Average True Range) — normalisiert als % des Preises
- **ADX** (Average Directional Index) — Trendstärke
- **BB-Width** (Bollinger Band Breite) — Volatilitätsmessung
- **Funding Rate** — Ausrichtung des Marktes (Long/Short Bias)

Nur bei `HUNT` (Score ≥ 4/4) wird ein Trade in Betracht gezogen.

---

### FUSION — Multi-Signal Score Engine
5 unabhängige Signale müssen sich ausrichten. Das Score-System bestimmt die Trade-Größe:

| Score | Mode        | Kapital-Einsatz   |
|-------|-------------|-------------------|
| 5/5   | `FULL_SEND` | 100% des Capitals |
| 4/5   | `HALF_SEND` | 50% des Capitals  |
| ≤3/5  | `SKIP`      | kein Trade        |

**Die 5 Signale:**

| Signal | Beschreibung |
|--------|--------------|
| **A — BB-Breakout** | Kurs bricht über/unter das Bollinger Band (±2σ) |
| **B — Volume Surge** | Volumen > N × 20-Perioden-MA |
| **C — EMA Trend** | EMA20 > EMA50, Kurs über EMA20 (Long) oder umgekehrt (Short) |
| **D — Candle Body** | Kerzenkörper ≥ X% der Gesamtrange (saubere Bewegung) |
| **E — RSI Momentum** | RSI in der Beschleunigungszone (nicht überkauft/überverkauft) |

Die Richtung (Long/Short) wird per Mehrheitsvotum der Signale A, C, D, E bestimmt.

---

### COMPOUNDER — Cycle & Position Sizing Manager
Verwaltet das Kapital innerhalb eines Cycles:

- Startet jeden Cycle mit definiertem Startkapital (z.B. 50 USDT)
- Trackt Trade-Nummer, aktuelles Kapital und Peak-Kapital
- Beendet Cycle automatisch bei:
  - **`TARGET_HIT`** — Kapital ≥ Startkapital × `cycle_target_multiplier`
  - **`MAX_TRADES`** — maximale Trades pro Cycle erreicht
  - **`DRAWDOWN`** — Drawdown ≥ `max_drawdown_pct`
  - **`BUST`** — Kapital auf 0 gefallen
- Archiviert jeden Cycle unter `artifacts/cycles/cycle_XXXX.json`
- Setzt State nach jedem Cycle auf Startkapital zurück

---

## Compounding-Mathematik

Bei Standard-Einstellungen (20x Hebel, 2.5% SL, 5% TP = 2:1 R:R):

```
Trade 1:  50 USDT → 100 USDT  (+100%)
Trade 2: 100 USDT → 200 USDT  (+100%)
Trade 3: 200 USDT → 400 USDT  (+100%)
Trade 4: 400 USDT → 800 USDT  (+100%)
```

Der optimale Ziel-Multiplikator (`cycle_target_multiplier`) wird durch Optuna **statistisch ermittelt** — nicht manuell gesetzt.

---

## Ziel-Multiplikator-Optimierung

Der Pipeline-Optimizer sucht automatisch den statistisch besten Ziel-Multiplikator:

- **Suchraum:** 2x bis 200x (logarithmische Skala)
- **Scoring:** `avg_mult × log(1+cycles) × (1 + hit_rate)`
  - `hit_rate` = Anteil der Cycles die das Ziel erreichen (0–100% → Bonus-Faktor 1.0–2.0)
- **Resultat:** Kein manuelles Raten — Optuna findet z.B. `12.4x` als optimales Ziel, wenn 30% aller Cycles es realistisch erreichen

```
  Score: 2.8431 | Cycles: 47 | WR: 68% | Avg: 3.21x
  Ziel: 12.4x | Treffer: 14/47 (30%)
```

---

## Projektstruktur

```
apexbot/
├── src/apexbot/
│   ├── modules/
│   │   ├── radar.py          # Regime Detection (ATR, ADX, BB, Funding)
│   │   ├── fusion.py         # 5-Signal Score Engine
│   │   └── compounder.py     # Cycle Tracking & Position Sizing
│   ├── strategy/
│   │   └── run.py            # Live-Trading Entry Point (--mode signal/check)
│   ├── utils/
│   │   ├── exchange.py       # ccxt Bitget Wrapper
│   │   ├── trade_manager.py  # Order Execution, TP/SL Platzierung
│   │   └── telegram.py       # Telegram Notifications
│   └── analysis/
│       ├── backtest.py       # Historische Simulation
│       ├── optimizer.py      # Optuna Parameter-Optimierung
│       └── show_results.py   # Analyse-Backend (5 Modi)
├── tests/
│   └── test_modules.py       # Unit Tests (RADAR, FUSION, COMPOUNDER)
├── artifacts/
│   ├── configs/              # Optimierte Parameter-Configs
│   ├── cycles/               # Archivierte Cycle-Ergebnisse
│   ├── results/              # Backtest-Ergebnisse
│   └── state/                # Globaler Bot-State (live)
├── settings.json             # Haupt-Konfiguration
├── secret.json               # API-Keys (NICHT in git)
├── master_runner.py          # Haupt-Loop (Cron-Einstieg)
├── run_pipeline.sh           # Training Pipeline (Optimizer + Backtest)
├── show_results.sh           # Analyse & Charts (5 Modi)
├── show_status.sh            # Live Bot Status
├── install.sh                # Installation
├── update.sh                 # Update vom Repo
└── run_tests.sh              # Test-Runner
```

---

## Installation

```bash
git clone https://github.com/Youra82/apexbot.git
cd apexbot
chmod +x *.sh
./install.sh
```

### API-Keys konfigurieren

```bash
cp secret.json.example secret.json
nano secret.json
```

```json
{
  "apexbot": [{
    "apiKey":   "DEIN_BITGET_API_KEY",
    "secret":   "DEIN_BITGET_SECRET",
    "password": "DEIN_BITGET_PASSPHRASE"
  }],
  "telegram": {
    "bot_token": "DEIN_BOT_TOKEN",
    "chat_id":   "DEINE_CHAT_ID"
  }
}
```

---

## Konfiguration (`settings.json`)

```json
{
  "symbol": "BTC/USDT:USDT",
  "timeframe": "15m",
  "leverage": 20,
  "margin_mode": "isolated",

  "cycle": {
    "start_capital_usdt": 50.0,
    "max_trades_per_cycle": 4,
    "cycle_target_multiplier": 50.0
  },

  "radar": {
    "atr_multiplier_min": 1.2,
    "adx_min": 20,
    "bb_width_min": 0.015,
    "funding_rate_threshold": 0.001
  },

  "fusion": {
    "min_score_full_send": 5,
    "min_score_half_send": 4,
    "volume_surge_multiplier": 2.0,
    "body_ratio_min": 0.60,
    "rsi_momentum_min": 50,
    "rsi_momentum_max": 75
  },

  "risk": {
    "stop_loss_pct": 2.5,
    "take_profit_multiplier": 2.0,
    "max_drawdown_pct": 50.0
  }
}
```

> **Hinweis:** Alle Parameter außer `symbol`, `timeframe`, `leverage`, `margin_mode` und `start_capital_usdt` werden durch den Optimizer automatisch optimiert. Manuelle Anpassungen werden beim nächsten `run_pipeline.sh --apply` überschrieben.

---

## Training Pipeline

```bash
./run_pipeline.sh
```

**Schritte:**
1. Symbol und Timeframe auswählen (oder aus `settings.json` übernehmen)
2. History-Tage eingeben (Empfehlung wird nach Timeframe angezeigt)
3. Optuna-Optimizer starten (z.B. 100 Trials)
4. Optimale Parameter inkl. `cycle_target_multiplier` suchen
5. Optional: beste Parameter direkt auf `settings.json` anwenden
6. Backtest mit optimierten Parametern

**Empfohlene History-Zeiträume:**

| Timeframe | Empfohlene Tage |
|-----------|-----------------|
| 1m, 5m    | 30–90           |
| 15m, 30m  | 60–180          |
| 1h        | 180–365         |
| 4h        | 365–730         |

---

## Analyse & Ergebnisse

```bash
./show_results.sh
```

```
Wähle einen Analyse-Modus:
  1) Einzel-Backtest               (jedes Pair wird simuliert)
  2) Manuelle Symbol-Auswahl       (du wählst die Pairs aus)
  3) Automatische Symbol-Opt.      (Bot wählt das beste Pair)
  4) Config-Bibliothek             (optimierte RADAR/FUSION-Parameter)
  5) Interaktive Charts            (Candlestick + Entry/Exit-Marker)
Auswahl (1-5) [Standard: 4]:
```

### Mode 5 — Interaktive Charts
Erzeugt ein vollständiges Plotly-Chart mit 4 Panels:

- **Panel 1:** Candlestick + Bollinger Bands + Entry-/Exit-Marker + Equity-Kurve (rechte Y-Achse)
  - ▲ Grün = Long Entry
  - ▼ Orange = Short Entry
  - ● Cyan = Exit TP (Win)
  - ✗ Rot = Exit SL (Loss)
  - Gepunktete Linien = SL/TP Level je Trade
- **Panel 2:** Volumen
- **Panel 3:** RSI mit Signal-Markierungen
- **Panel 4:** FUSION Score je Trade (grün = Long, orange = Short)

---

## Live-Betrieb

### Bot starten (manuell)
```bash
# Signal prüfen und ggf. traden
.venv/bin/python3 src/apexbot/strategy/run.py --mode signal

# Offene Position prüfen
.venv/bin/python3 src/apexbot/strategy/run.py --mode check
```

### Cron-Job einrichten (empfohlen)
```bash
crontab -e
```
```cron
*/5 * * * * cd /pfad/zu/apexbot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

`master_runner.py` ruft dabei in jedem Zyklus zuerst `--mode check` (offene Position?), dann `--mode signal` (neues Signal?) auf.

### Status prüfen
```bash
./show_status.sh
```

---

## Tests

```bash
./run_tests.sh
```

```
tests/test_modules.py::test_radar_returns_valid_regime     PASSED
tests/test_modules.py::test_radar_flat_market_not_hunt     PASSED
tests/test_modules.py::test_fusion_returns_valid_output    PASSED
tests/test_modules.py::test_fusion_score_range             PASSED
tests/test_modules.py::test_compounder_full_send_returns_full_capital  PASSED
tests/test_modules.py::test_compounder_half_send_returns_half          PASSED
tests/test_modules.py::test_compounder_skip_returns_zero               PASSED
```

---

## Update

```bash
./update.sh
```

Führt `git reset --hard origin/main` aus und stellt `secret.json` automatisch wieder her.

---

## Abhängigkeiten

```
ccxt==4.3.5        # Exchange-Interface (Bitget)
pandas==2.1.3      # Datenverarbeitung
numpy              # Mathematik / Indikatoren
ta==0.11.0         # Technische Indikatoren
optuna==4.5.0      # Bayesianischer Parameter-Optimizer
requests==2.31.0   # Telegram API
plotly             # Interaktive Charts
pytest             # Tests
```

---

## Risikohinweis

> **ACHTUNG:** Dieser Bot handelt mit Hebelwirkung (Standard: 20x) auf Krypto-Futures. Hebelhandel birgt ein erhebliches Verlustrisiko bis hin zum Totalverlust des eingesetzten Kapitals. Dieser Bot ist ausschließlich für Bildungs- und Forschungszwecke konzipiert. Der Einsatz erfolgt auf eigenes Risiko.

---

## Lizenz

MIT License
