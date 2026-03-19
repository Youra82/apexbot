# APEXBOT v2 — Adaptive Probabilistic Cycle Engine

Vollautomatischer Futures-Trading-Bot für Bitget (Perpetual Swaps).

---

## Was macht dieser Bot?

Der APEXBOT arbeitet in **Cycles** — kurzen, kontrollierten Gewinnläufen mit automatischem Reset.

**Idee:** Statt dauerhaft mit festem Kapital zu handeln, startet der Bot jeden Cycle mit einem definierten Betrag (z.B. 50 USDT) und versucht, diesen durch aufeinanderfolgende Trades zu multiplizieren. Erreicht er sein Ziel oder trifft er die Trade-Grenze, wird das Kapital zurückgesetzt — und der nächste Cycle beginnt.

**Konkret:** Startet ein Cycle mit 50 USDT und einem Ziel von 16x:
```
Trade 1: 50 USDT → 100 USDT   (Win, +100%)
Trade 2: 100 USDT → 200 USDT  (Win, +100%)
Trade 3: 200 USDT → 400 USDT  (Win, +100%)
Trade 4: 400 USDT → 800 USDT  ✓ Ziel erreicht → Cycle-Ende, Reset auf 50 USDT
```
Verliert der Bot, bleibt der Verlust auf den aktuellen Cycle begrenzt. Das Ursprungskapital ist immer der nächste Startpunkt.

**Mathematische Basis:** Phase-Space Attractors · Probabilistisches Edge-Trading · Fractional Kelly · Liquidity Gravitation · Walk-Forward Validation

---

## Strategie — Wie der Bot handelt

Jede Kerze durchläuft denselben Entscheidungsbaum. Nur wenn alle Filter bestanden sind, wird ein Trade eröffnet.

```
MARKT → ATTRACTOR → EDGE → KELLY-SIZING → TRADE → CYCLE
```

---

### Schritt 1 — Marktphase erkennen (ATTRACTOR)

Bevor der Bot irgendwelche Signale auswertet, prüft er: *Ist der Markt gerade handelbar?*

Dazu berechnet er drei Kennzahlen der letzten Kerzen:

**Hurst-Exponent** misst, ob sich Preisbewegungen selbst verstärken (Trend) oder umkehren (Range):
- `H > 0.55` → Markt folgt seiner Richtung → Momentum-Trades sinnvoll
- `H < 0.50` → Markt dreht sich im Kreis → Mean-Reversion sinnvoll
- `H ≈ 0.50` → Zufallsmarsch → nicht handeln

**ADX (Average Directional Index)** misst die Trendstärke unabhängig von der Richtung:
- `ADX > 25` → klarer Trend vorhanden
- `ADX < 20` → trendlos / seitwärts

**Shannon-Entropie** misst, wie chaotisch die Preisveränderungen verteilt sind:
- Niedrige Entropie → geordnete, vorhersagbare Bewegung
- Hohe Entropie → zufällige, unstrukturierte Bewegung → **kein Trade**

Aus diesen drei Werten wird der Marktzustand klassifiziert:

| Zustand | Bedingung | Bedeutung |
|---------|-----------|-----------|
| `TREND` | Hurst hoch · ADX hoch · Entropie niedrig | Gerichtete Bewegung — Momentum-Trade |
| `RANGE` | Hurst niedrig · ADX niedrig | Seitwärtsmarkt — Mean-Reversion-Trade |
| `CHAOS` | Entropie > Schwelle | Unstrukturiert — **kein Trade** |

Bei `CHAOS` stoppt der Bot sofort. Kein Signal, kein Trade.

---

### Schritt 2 — Signale auswerten und Richtung bestimmen (EDGE ENGINE)

Bei `TREND` oder `RANGE` wertet der Bot fünf unabhängige Signale aus, die jeweils eine Richtung (`long` / `short`) und einen Wahrscheinlichkeitsbeitrag liefern:

**Signal 1 — EMA-Ausrichtung (20/50)**
- Preis über EMA20, EMA20 über EMA50 → `long` (+0.03)
- Preis unter EMA20, EMA20 unter EMA50 → `short` (+0.03)
- Unentschieden → kein Beitrag

**Signal 2 — RSI Momentum-Zone**
- RSI im Bereich 50–75 → Aufwärtsmomentum → `long` (+0.04)
- RSI im Bereich 25–50 → Abwärtsmomentum → `short` (+0.04)
- Außerhalb beider Zonen (überkauft/überverkauft) → kein Beitrag

**Signal 3 — Volumen-Surge**
- Aktuelles Volumen ≥ N × gleitender Durchschnitt (20 Kerzen) → erhöhte Aktivität → +0.05
- (Richtungsneutral — verstärkt die Gesamtwahrscheinlichkeit)

**Signal 4 — Kerzenmuster (Candle Shape)**

Die letzte abgeschlossene Kerze wird analysiert:

| Muster | Erkennung | Richtung | Beitrag |
|--------|-----------|---------|---------|
| Hammer | Langer unterer Docht (>55%), kleiner Körper (<25%) | `long` | +0.04 |
| Shooting Star | Langer oberer Docht (>55%), kleiner Körper (<25%) | `short` | +0.04 |
| Starker Körper | Körper ≥ 60% der Gesamtrange | Kerzenrichtung | +0.06 |
| Moderater Körper | Körper ≥ 40% | Kerzenrichtung | +0.02 |
| Schwacher Körper | Körper < 40% | keine Richtung | −0.03 |
| Gegenläufiger Docht | Docht zur Handelsrichtung > 35% | — | −0.05 |

**Richtungsentscheid:** Die Mehrheit der drei Richtungs-Signale (EMA, RSI, Kerzenmuster) bestimmt die Handelsrichtung per Mehrheitsvotum. Sind alle drei unentschieden → kein Trade.

---

### Schritt 3 — Stop-Loss berechnen (ATR)

Der Stop-Loss ist marktadaptiv — kein fester Prozentwert:

```
SL-Distanz = ATR(14) × atr_sl_mult
```

Der ATR (Average True Range) misst die durchschnittliche Kerzenspanne der letzten 14 Perioden. Bei volatilen Märkten ist der SL weiter, bei ruhigen Märkten enger. Das verhindert unnötige Stopouts durch normales Marktrauschen.

---

### Schritt 4 — Take-Profit via Liquiditätszonen

Statt einem festen TP-Prozentsatz sucht der Bot die nächste natürliche Preiszone, bei der viel Volumen gehandelt wurde:

1. Volumen-Profil der letzten 100 Kerzen: Jede Kerze verteilt ihr Volumen proportional auf ihre Preisspanne (40 Bins)
2. Lokale Hochpunkte im Profil = **Liquiditätszonen** (Preisbereiche mit überdurchschnittlichem Handelsvolumen)
3. Nahe Zonen (< 0.5% Abstand) werden zusammengeführt → Top 5 Zonen
4. Der Bot nimmt die nächste Zone, die ein Mindest-RR (Risk/Reward ≥ min_rr) erreicht
5. Gibt es keine passende Zone → Fallback: `TP = Einstieg ± ATR × atr_sl_mult × min_rr`

Die Logik dahinter: Hohe Handelsvolumina entstehen dort, wo viele Marktteilnehmer Positionen haben. Diese Zonen wirken als natürliche Anziehungspunkte für den Preis.

---

### Schritt 5 — Edge-Berechnung und Trade-Entscheidung

Mit allen Werten berechnet der Bot den erwarteten Gewinn pro riskiertem Dollar:

```
E = P(win) × RR − P(loss) × 1.0
```

Nur wenn `E ≥ edge_threshold` → Trade wird eröffnet. Andernfalls: kein Trade.

**Beispiele:**

```
P(win) = 0.55, RR = 2.0:
E = 0.55 × 2.0 − 0.45 × 1.0 = 1.10 − 0.45 = 0.65  → TRADE

P(win) = 0.45, RR = 1.2:
E = 0.45 × 1.2 − 0.55 × 1.0 = 0.54 − 0.55 = −0.01  → SKIP
```

Auch bei 50/50-Chance ist der Bot profitabel wenn RR > 1.0 — der Edge kommt aus der Kombination von Signalfilterung und Liquidity-TP.

---

### Schritt 6 — Positionsgröße (Kelly)

Die Positionsgröße hängt vom gewählten Modus ab:

- **All-In** (`kelly.enabled = false`): Gesamtes Cycle-Kapital wird eingesetzt
- **Fractional Kelly** (`kelly.enabled = true`): `f* = (P(win)×RR − P(loss)) / RR`, begrenzt durch `kelly.fraction`

Bei Kelly handelt der Bot bei unsicheren Setups kleiner und bei starken Setups größer — automatisch, basierend auf dem berechneten P(win) und RR.

---

### Cycle — Compounding

Nach jedem Trade kumuliert das Kapital innerhalb des Cycles:

- Start: `start_capital_usdt` (Standard: 50 USDT)
- Max Trades pro Cycle: 4
- Cycle endet bei: `TARGET_HIT` | `MAX_TRADES` | `DRAWDOWN`
- Nach Cycle-Ende: Kapital-Reset auf Startwert

---

## Installation

### 1. Klonen

```bash
git clone https://github.com/your-user/apexbot.git
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

### 5. Pipeline ausführen (Optimierung + Backtest)

```bash
./run_pipeline.sh
```

### 6. Cronjob einrichten (Live-Trading)

```bash
crontab -e
# Folgendes eintragen:
*/5 * * * * cd /pfad/apexbot && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1
```

---

## Skripte

### `./run_pipeline.sh` — Optimierungs-Pipeline

Interaktive Pipeline: lädt historische Daten, optimiert alle Parameter per Optuna (Walk-Forward 70/30) und speichert die beste Config pro Pair/Timeframe.

```bash
./run_pipeline.sh
```

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
| Modus | `1` Streng (Kelly + DD-Kontrolle) · `2` Best Profit (All-In) | `2` |
| Max Drawdown % | Constraint für Optimizer | `50` |

**Empfohlene Rückblickzeiträume:**

| Timeframe | Empfehlung |
|-----------|-----------|
| 5m, 15m | 30 – 90 Tage |
| 30m, 1h | 180 – 365 Tage |
| 2h, 4h | 365 – 730 Tage |
| 6h, 1d | 1095 – 1825 Tage |

Optimierte Configs werden in `artifacts/configs/` gespeichert und automatisch vom Bot geladen.

---

### `./show_results.sh` — Ergebnisse ansehen

```bash
./show_results.sh
```

| Modus | Beschreibung |
|-------|-------------|
| `1` | Einzel-Backtest — jedes Pair einzeln simulieren |
| `2` | Manuelle Auswahl — Pairs per Nummer auswählen |
| `3` | Automatische Optimierung — Bot wählt das beste Pair |
| `4` | Config-Bibliothek — alle gespeicherten Configs anzeigen |
| `5` | Interaktive Charts — Candlestick + Entry/Exit-Marker |

---

### `./show_status.sh` — Live-Status

```bash
./show_status.sh
```

Zeigt den aktuellen Cycle-Status (laufender Trade, Kapital, Peak), die letzten abgeschlossenen Cycles und den letzten Backtest-Überblick.

---

### `./update.sh` — Bot aktualisieren

```bash
./update.sh
```

Sichert `secret.json`, zieht den neuesten Stand vom Git, stellt den Secret wieder her und bereinigt `.pyc`-Dateien. Das lokale Kapital und die Cycle-History bleiben erhalten.

---

### `./push_configs.sh` — Optimierte Configs pushen

```bash
./push_configs.sh
```

Pusht alle optimierten Configs aus `artifacts/configs/` ins Git-Repository — z.B. nach einer Pipeline-Optimierung auf dem lokalen Rechner, um die Configs auf den VPS zu übertragen. Bei Konflikten wird automatisch ein Rebase durchgeführt.

**Workflow:** `./run_pipeline.sh` → `./push_configs.sh` → auf VPS: `./update.sh`

---

### `./run_tests.sh` — Tests ausführen

```bash
./run_tests.sh
```

Führt alle Pytest-Tests aus. Nutzbar vor einem Update oder nach Codeänderungen zur Funktionsprüfung.

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

---

## Dateistruktur

```
apexbot/
├── settings.json                    # Minimale Benutzerkonfiguration
├── secret.json                      # API-Keys (nicht im Repo)
├── master_runner.py                 # Autopilot-Runner
├── run_pipeline.sh                  # Optimierungs-Pipeline
├── show_results.sh                  # Ergebnisse & Backtests
├── show_status.sh                   # Live Cycle-Status
├── run_tests.sh                     # Pytest
├── push_configs.sh                  # Optimierte Configs ins Repo pushen
├── install.sh                       # Einmalige Installation
├── update.sh                        # Git-Update
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
    ├── cycles/                      # Abgeschlossene Cycle-Historien
    ├── state/                       # Aktueller Bot-State
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

