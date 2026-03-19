# APEXBOT — Adaptive Compounding Trading Bot

APEXBOT ist ein vollautomatischer Futures-Trading-Bot für Bitget (Perpetual Swaps), der auf einem **Cycle-Compounding-Prinzip** basiert: Das Kapital startet pro Cycle bei einem definierten Betrag (Standard: 50 USDT), wird durch aufeinanderfolgende Trades multipliziert und bei Erreichen eines optimierten Ziel-Multiplikators automatisch zurückgesetzt.

**Mathematische Grundlage:** Kelly Criterion · Geometrischer Mittelwert · Hurst-Exponent · Shannon-Entropie · Walk-Forward Validation

---

## Ergebnis: Optimales Pair/Timeframe

Nach vollständiger Multi-Pair Optimierung (500 Trials, Walk-Forward OOS):

| Pair | OOS GeoMean | OOS Win-Rate | OOS Ratio | Status |
|------|-------------|--------------|-----------|--------|
| **SOL/USDT:USDT 30m** | **1.017x** | 53% | 76% | **EMPFOHLEN** |
| ETH/USDT:USDT 30m | 1.007x | 53% | 78% | Gut |
| DOGE/USDT:USDT 30m | 0.996x | 38% | 70% | Schwach |

**Optimale Parameter (SOL 30m):**
```json
"radar":  { "atr_multiplier_min": 2.5, "adx_min": 20, "bb_width_min": 0.01, "hurst_min": 0.15 },
"fusion": { "min_score_full_send": 5, "min_score_half_send": 2,
            "volume_surge_multiplier": 1.8, "body_ratio_min": 0.5,
            "rsi_momentum_min": 54, "rsi_momentum_max": 78 },
"risk":   { "stop_loss_pct": 1.0, "take_profit_multiplier": 1.5 },
"cycle":  { "cycle_target_multiplier": 2.4 }
```

> Config gespeichert in `artifacts/configs/config_SOLUSDTUSDT_30m.json` und wird automatisch vom Bot geladen.

---

## Architektur

```
MARKT → RADAR → FUSION → KELLY → TRADE → CYCLE
```

### RADAR — Regime Detection

Bewertet den Markt anhand von bis zu 5 Indikatoren:

| Regime | Bedeutung |
|--------|-----------|
| `HUNT` | Alle Filter grün → Trade erlaubt |
| `STALK` | Markt in Bewegung, aber nicht eindeutig |
| `SLEEP` | Kein Trend, kein Volumen |

**Indikatoren:**

| Indikator | Beschreibung | Wann aktiv |
|-----------|--------------|------------|
| **ATR** | Normalisierte Volatilität (% des Preises) | Immer |
| **ADX** | Trendstärke (> `adx_min`) | Immer |
| **BB-Width** | Bollinger-Band-Breite | Immer |
| **Hurst-Exponent** | R/S-Analyse: H > 0.5 = trendend, H < 0.5 = mean-reversion | Wenn `hurst_min > 0` |
| **Shannon-Entropie** | Niedrig = geordneter Markt (Ruhe vor dem Sturm) | Wenn `entropy_max > 0` |
| **Funding Rate** | Long/Short-Bias des Marktes | Nur live (nicht im Backtest) |

**Hurst-Exponent:** Filtert Random-Walk-Phasen heraus. H > 0.5 bedeutet, dass vergangene Bewegungen sich fortsetzen (persistent/trending). H ≈ 0.5 ist ein Random Walk — kein Edge. H < 0.5 ist mean-reverting. Für SOL/USDT 30m ist `hurst_min = 0.15` optimal.

**Shannon-Entropie:** Misst die Ordnung der letzten N Log-Returns. Niedrige Entropie = regelmäßige, vorhersagbare Bewegungen. Hohe Entropie = Chaos. Für SOL wurde kein Vorteil gefunden (off).

---

### FUSION — Multi-Signal Score Engine

5 unabhängige Signale müssen sich ausrichten. Kelly-Sizing bestimmt die Trade-Größe:

| Score | Mode | Kelly-Fraktion |
|-------|------|----------------|
| ≥ `min_score_full_send` | `FULL_SEND` | max_fraction (z.B. 25%) |
| ≥ `min_score_half_send` | `HALF_SEND` | Interpoliert (5%–25%) |
| darunter | `SKIP` | kein Trade |

**Die 5 Signale:**

| Signal | Beschreibung |
|--------|--------------|
| **A — BB-Breakout** | Kurs bricht über/unter das Bollinger Band (±2σ) |
| **B — Volume Surge** | Volumen > N × 20-Perioden-MA |
| **C — EMA Trend** | EMA20 > EMA50, Kurs über EMA20 (Long) oder umgekehrt |
| **D — Candle Body** | Kerzenkörper ≥ X% der Gesamtrange (saubere Bewegung) |
| **E — RSI Momentum** | RSI in der Beschleunigungszone (nicht überkauft/überverkauft) |

---

### KELLY CRITERION — Optimales Position Sizing

Verhindert Ruin durch zu große Positionen und maximiert geometrisches Kapitalwachstum:

```
f* = (p × R − (1−p)) / R / 2   (Half-Kelly für Sicherheitspuffer)
```

Wobei:
- `p` = empirische Win-Rate (aus bisherigen Trades)
- `R` = TP/SL-Verhältnis (Risk-Reward Ratio)
- Division durch 2 = Half-Kelly (reduziert Ruin-Risiko erheblich)

**Signal-stratifiziertes Kelly:**
```
Score 3 (niedrig) → min_fraction (z.B. 5%)
Score 5 (hoch)    → max_fraction (z.B. 25%)
```
Mehr Kapital bei High-Confidence-Signalen, weniger bei schwachen.

**Mathematischer Hintergrund (Ergodicity Economics):** Bei multiplikativen Prozessen (Compounding) ist der arithmetische Erwartungswert trügerisch. Ein Trade mit 100% Gewinn gefolgt von 50% Verlust ergibt nicht +50%, sondern 0%. Nur der geometrische Mittelwert beschreibt den realen Langzeit-Outcome. Kelly maximiert genau diesen.

---

### COMPOUNDER — Cycle Manager

| Cycle-Ende | Bedingung |
|-----------|-----------|
| `TARGET_HIT` | Kapital ≥ Startkapital × `cycle_target_multiplier` |
| `MAX_TRADES` | Maximale Trades pro Cycle erreicht |
| `DRAWDOWN` | Drawdown ≥ `max_drawdown_pct` |

Der Ziel-Multiplikator wird durch den Optimizer **statistisch ermittelt** (Kelly-aware Suchraum 1.1x–8x).

---

## Optimizer — Walk-Forward Validation

Der Optimizer verhindert Overfitting durch mathematisch rigorose Validierung:

### Geometrischer Score (statt arithmetischem Mittelwert)
```python
geo_mean = exp(mean(log(cycle_multipliers)))
score    = geo_mean × log1p(n_cycles) × (1 + hit_rate)
```
**Warum geometrisch?** [2x, 0.5x, 2x, 0.5x] → arithmetisch 1.25x (positiv!), geometrisch 1.0x (die Wahrheit: kein Gewinn). Geometrisches Scoring lügt nicht.

### Walk-Forward OOS
- **70% Train** — Optuna optimiert auf diesem Zeitraum
- **30% Test (OOS)** — unsehen Daten, validiert Generalisierung
- **OOS-Ratio ≥ 50%** → `[OK]` — Strategie generalisiert
- **OOS-Ratio < 50%** → `[SCHWACH]` — Overfitting-Verdacht

### Min-Trades Constraint
Configs mit zu wenigen Trades werden automatisch abgelehnt (zu wenige Datenpunkte für statistische Aussagekraft).

| Timeframe | Min-Trades |
|-----------|-----------|
| 15m, 30m | 20–25 |
| 1h | 15 |
| 4h | 10 |

---

## Multi-Pair Tournament

Der Bot kann automatisch das beste Pair/Timeframe auswählen:

```python
pair_score = hurst_exponent × (1 − entropy)
```

Hohes Score = persistent (trendend) + geordnet (vorhersagbar) = bester Edge.

Konfiguration in `settings.json`:
```json
"tournament": {
  "enabled": true,
  "candidate_pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
  "candidate_timeframes": ["30m", "1h"]
}
```

---

## Learner — Adaptive Parameter

| Komponente | Funktion |
|-----------|----------|
| `adaptive_target` | Passt `cycle_target_multiplier` an bisherige Cycle-Performance an |
| `adaptive_weights` | Gewichtet FUSION-Signale nach historischer Trefferquote |
| `rl_gate` | Blockiert Signale wenn RL-Score unter Schwellenwert |

Wird nach jedem abgeschlossenen Cycle aktualisiert.

---

## Projektstruktur

```
apexbot/
├── src/apexbot/
│   ├── modules/
│   │   ├── radar.py          # Regime Detection (ATR, ADX, BB, Hurst, Entropy, Funding)
│   │   ├── fusion.py         # 5-Signal Score Engine
│   │   ├── compounder.py     # Cycle Tracking & Position Sizing
│   │   └── learner.py        # Adaptive Weights & RL Gate
│   ├── strategy/
│   │   └── run.py            # Live-Trading Entry Point (--mode signal/check)
│   ├── utils/
│   │   ├── exchange.py       # ccxt Bitget Wrapper
│   │   ├── trade_manager.py  # Order Execution, TP/SL Platzierung
│   │   └── telegram.py       # Telegram Notifications
│   └── analysis/
│       ├── backtest.py       # Historische Simulation (Kelly-konsistent)
│       ├── optimizer.py      # Optuna + Walk-Forward OOS
│       └── show_results.py   # Analyse-Backend (5 Modi)
├── tests/
│   └── test_modules.py       # Unit Tests
├── artifacts/
│   ├── configs/              # Optimierte Parameter-Configs pro Pair/TF
│   ├── cycles/               # Archivierte Cycle-Ergebnisse
│   ├── results/              # Backtest-Ergebnisse
│   └── state/                # Globaler Bot-State (live)
├── settings.json             # Haupt-Konfiguration
├── secret.json               # API-Keys (NICHT in git)
├── master_runner.py          # Haupt-Loop (Cron-Einstieg) + Tournament
├── run_pipeline.sh           # Training Pipeline (Optimizer + Backtest)
├── run_multi_optimize.py     # Multi-Pair Scan (alle Pairs sequentiell)
├── run_deep_dive.py          # 500-Trial Deep-Dive auf Top-Kandidaten
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
  "symbol": "SOL/USDT:USDT",
  "timeframe": "30m",
  "leverage": 20,
  "margin_mode": "isolated",

  "cycle": {
    "start_capital_usdt": 50.0,
    "max_trades_per_cycle": 4,
    "cycle_target_multiplier": 2.4
  },

  "radar": {
    "atr_multiplier_min": 2.5,
    "adx_min": 20,
    "bb_width_min": 0.01,
    "funding_rate_threshold": 0.001,
    "hurst_min": 0.15,
    "entropy_max": 0.0
  },

  "fusion": {
    "min_score_full_send": 5,
    "min_score_half_send": 2,
    "volume_surge_multiplier": 1.8,
    "body_ratio_min": 0.5,
    "rsi_momentum_min": 54,
    "rsi_momentum_max": 78
  },

  "risk": {
    "stop_loss_pct": 1.0,
    "take_profit_multiplier": 1.5,
    "max_drawdown_pct": 50.0
  },

  "kelly": {
    "enabled": true,
    "signal_stratified": true,
    "max_fraction": 0.25,
    "min_fraction": 0.05,
    "rolling_window": 20
  },

  "tournament": {
    "enabled": false,
    "candidate_pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
    "candidate_timeframes": ["30m", "1h"]
  },

  "learner": {
    "adaptive_target": true,
    "adaptive_weights": true,
    "rl_gate": true,
    "rl_block_threshold": 0.15,
    "min_cycles_for_target": 10,
    "min_trades_for_rl": 200
  }
}
```

> **Hinweis:** Der Optimizer überschreibt `radar`, `fusion`, `risk` und `cycle_target_multiplier` beim nächsten `run_pipeline.sh`. Pair-spezifische Configs werden automatisch aus `artifacts/configs/` geladen.

---

## Training Pipeline

```bash
./run_pipeline.sh
```

**Ablauf:**
1. Symbol und Timeframe auswählen (oder aus `settings.json`)
2. History-Tage (Automatik empfohlen — je nach Timeframe)
3. Optuna-Optimizer mit Walk-Forward OOS (30%)
4. Min-Trades Constraint wird automatisch gesetzt
5. Backtest mit optimierten Parametern

**Automatischer History-Zeitraum:**

| Timeframe | Tage |
|-----------|------|
| 1m, 5m    | 60   |
| 15m, 30m  | 120  |
| 1h        | 270  |
| 2h, 4h    | 540  |

### Multi-Pair Optimizer

```bash
# Alle 10 Pairs sequentiell optimieren (kein Rate-Limit-Problem)
python run_multi_optimize.py --trials 200

# Mit anschliessender Deep-Dive Phase (Top-3, 500 Trials)
python run_multi_optimize.py --trials 200 --deep-trials 500

# Nur Deep-Dive (Top-3 manuell festgelegt)
python run_deep_dive.py
```

**Output-Beispiel:**
```
=================================================================
  RANKING (nach Geo-Mean, Train)
=================================================================
   #  Pair                 GeoMean   OOS GM     WR  Trades    OOS
  --  ------------------  --------  -------  -----  ------  -----
   1  SOL 30m             1.001x   1.012x     46%     182  [OK]
   2  ETH 30m             0.995x   1.002x     60%     156  [OK]
   3  DOGE 30m            1.003x   1.004x     56%     156  [OK]
```

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
```

### Mode 5 — Interaktive Charts

- **Panel 1:** Candlestick + Bollinger Bands + Entry-/Exit-Marker + Equity-Kurve
  - ▲ Grün = Long Entry | ▼ Orange = Short Entry
  - ● Cyan = Exit TP (Win) | ✗ Rot = Exit SL (Loss)
- **Panel 2:** Volumen
- **Panel 3:** RSI mit Signal-Markierungen
- **Panel 4:** FUSION Score je Trade

---

## Live-Betrieb

### Bot starten (manuell)
```bash
# Signal prüfen und ggf. traden
.venv/bin/python3 src/apexbot/strategy/run.py --mode signal

# Offene Position prüfen
.venv/bin/python3 src/apexbot/strategy/run.py --mode check

# Anderes Pair/Timeframe (ohne settings.json zu ändern)
.venv/bin/python3 src/apexbot/strategy/run.py --mode signal --symbol SOL/USDT:USDT --timeframe 30m
```

### Cron-Job (empfohlen: alle 5 Minuten)
```bash
crontab -e
```
```cron
*/5 * * * * cd /pfad/zu/apexbot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

`master_runner.py` ruft dabei in jedem Zyklus:
1. Tournament-Scoring aller Kandidaten (Hurst × (1−Entropy))
2. Bestes Pair auswählen
3. `--mode check` → offene Position prüfen
4. `--mode signal` → neues Signal suchen

### Status prüfen
```bash
./show_status.sh
```

---

## Backtest (standalone)

```bash
python src/apexbot/analysis/backtest.py --symbol SOL/USDT:USDT --timeframe 30m --days 120
```

Verwendet automatisch `artifacts/configs/config_SOLUSDTUSDT_30m.json` falls vorhanden, sonst `settings.json`.

```
=======================================================
  APEXBOT BACKTEST — SOL/USDT:USDT 30m
=======================================================
  Kerzen gesamt:       2288
  Trades simuliert:    182
  Win-Rate:            46.0%
  Cycles:              46
  Avg Cycle-Mult:      1.003x
  Max Cycle-Mult:      1.021x
  Cycles > 1x (Gewinn): 28
=======================================================
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
ccxt>=4.3.5        # Exchange-Interface (Bitget)
pandas>=2.1.3      # Datenverarbeitung
numpy              # Mathematik / Indikatoren
ta>=0.11.0         # Technische Indikatoren
optuna>=4.5.0      # Bayesianischer Parameter-Optimizer
requests>=2.31.0   # Telegram API
plotly             # Interaktive Charts
pytest             # Tests
```

---

## Risikohinweis

> **ACHTUNG:** Dieser Bot handelt mit Hebelwirkung (Standard: 20x) auf Krypto-Futures. Hebelhandel birgt ein erhebliches Verlustrisiko bis hin zum Totalverlust des eingesetzten Kapitals. Backtests und Optimierungsergebnisse sind keine Garantie für zukünftige Performance. Dieser Bot ist ausschließlich für Bildungs- und Forschungszwecke konzipiert. Der Einsatz erfolgt auf eigenes Risiko.

---

## Lizenz

MIT License
