
# APEXBOT — Modularer Swingtrading-Bot

Vollautomatischer, modularer Swingtrading-Bot für Bitget (Perpetual Swaps) mit Backtesting- und Optimierungs-Engine.

---

## Was macht dieser Bot?

Der neue ApexBot setzt auf eine saubere, professionelle Swingtrading-Strategie nach allen Regeln der Kunst:

- **Modularer Aufbau:** Alle Strategie-Komponenten sind klar getrennt und leicht erweiterbar.
- **Backtesting-Fähigkeit:** Die Strategie kann auf beliebigen historischen Daten getestet und optimiert werden.
- **Signal-Logik:** Entry/Exit, Stop-Loss und Take-Profit werden nach klassischen Swingtrading-Prinzipien berechnet (z.B. EMA, RSI, ATR, Chartmuster).
- **Konfigurierbare Parameter:** Alle wichtigen Schwellenwerte und Indikatoren sind flexibel einstellbar.
- **Optimierungs- und Analyse-Tools:** Integrierte Backtest- und Optimizer-Schnittstellen für systematische Strategieverbesserung.

---


## Strategie — Swingtrading nach Lehrbuch

Die Strategie orientiert sich an klassischen Swingtrading-Prinzipien:

- **Signal-Detection:** Einstiegssignale werden durch Kombination von Trend-, Momentum- und Volumenindikatoren erkannt (z.B. EMA-Cross, RSI, ATR, Chartmuster).
- **Entry/Exit:** Entry, Stop-Loss und Take-Profit werden nach bewährten Methoden berechnet und sind flexibel konfigurierbar.
- **Backtesting:** Die Strategie kann auf beliebigen historischen Daten getestet werden (siehe Methode `backtest()` in `src/apexbot/strategy/run.py`).
- **Modularität:** Alle Komponenten sind als Methoden und Module gekapselt und können leicht erweitert oder angepasst werden.

**Hinweis:** Die konkrete Signal- und Entry/Exit-Logik ist in der Klasse `SwingStrategy` implementiert und kann individuell angepasst werden.

---


## Installation & Nutzung

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


### 5. Backtest oder Optimierung ausführen

```bash
./run_pipeline.sh   # Optimierung & Backtest (empfohlen)
# oder
python -m src.apexbot.strategy.run  # Individueller Backtest/Strategie-Check
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

Führt alle Unittests und Backtest-Checks aus. Empfohlen nach jeder Änderung an der Strategie.

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


Alle Trading-Parameter (Indikator-Perioden, Schwellenwerte, SL/TP-Logik etc.) sind in der Strategie-Klasse konfigurierbar und können durch den Optimizer angepasst werden.

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


## Optimizer — Parameter-Raum (optional)

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


## Hinweise zur Strategie-Anpassung

Die Signal- und Entry/Exit-Logik befindet sich in `src/apexbot/strategy/run.py` in der Klasse `SwingStrategy`. Passe die Methoden `detect_signal`, `get_entry`, `should_exit` und `backtest` nach deinen Anforderungen an.

---

ApexBot kombiniert **RADAR** (Hurst-Exponent + Entropie zur Regime-Erkennung) mit **FUSION** (P(win)-Scoring via EMA, RSI, Volumen, Kerzenform). Benötigt: Coins mit detektierbarer Persistenz (Hurst > 0.55 = trending) und klaren Volumen- sowie Momentum-Mustern.

### Effektive Zeitspannen je Timeframe

| TF | Hurst(20K) | Entropy(20K) | ADX(14) | EMA20/50 | Geeignet |
|---|---|---|---|---|---|
| 15m | 5h | 5h | 3.5h | 5h / 12.5h | ⚠️ |
| 30m | 10h | 10h | 7h | 10h / 25h | ⚠️ |
| **1h** | **20h** | **20h** | **14h** | **20h / 50h** | **✅✅** |
| **2h** | **40h** | **40h** | **28h** | **40h / 100h** | **✅✅** |
| **4h** | **80h** | **80h** | **56h** | **80h / 200h** | **✅✅** |
| 6h | 120h | 120h | 84h | 120h / 300h | ✅ |
| 1d | 20d | 20d | 14d | 20d / 50d | ✅ |

Der Hurst-Exponent braucht mindestens 20h Daten (1h x 20 Kerzen) um zwischen Persistenz und Random Walk zu unterscheiden. Auf 15m misst er nur 5h — zu wenig für statistische Verlässlichkeit. Ab 1h wird die Persistenz-Erkennung aussagekräftig; ab 4h ist sie robust.

### Coin-Eignung

| Coin | Hurst-Persistenz | Entropie-Profil | FUSION-Signale | Bewertung |
|---|---|---|---|---|
| **BTC** | Hoch in Bullphasen (H ~0.6-0.7) | Klare Entropie-Reduktion vor Breakouts | Starke EMA/RSI/Volumen-Kombination | ✅✅ Beste Wahl |
| **ETH** | Hoch — ähnlich BTC | Gutes Entropie-Profil | Klare FUSION-Signale | ✅✅ Sehr gut |
| **SOL** | Gut — explosive Persistenzphasen | Starke Entropie-Reduktion | Hohe Volumen-Surges erkennbar | ✅ Gut |
| **BNB** | Gut — stabile, niedrige Entropie | Klares Profil | Moderate FUSION-Signale | ✅ Gut |
| **AVAX** | Gut — klare Persistenzphasen | Gutes Signal | Gute Volumen-Patterns | ✅ Gut |
| **TON** | Gut — wachsende Trending-Struktur | Moderate Entropie | Aufbauende FUSION-Basis | ✅ Gut |
| **INJ** | Gut — explosive Trending-Phasen | Gutes Signal | Hohe Momentum-Signale | ✅ Gut |
| **LTC** | Mittel — BTC-korreliert, moderater Hurst | Mittel | Moderate Signale | ⚠️ Mittel |
| **XRP** | Mittel — Hurst nahe 0.5 beim Ranging | Mittel | Unregelmäßig | ⚠️ Mittel |
| **ADA** | Schwach — häufig Random Walk (H ~0.5) | Wenig Struktur | Schwache Signale | ⚠️ Schwach |
| **DOGE** | Nicht vorhanden — Sentiment übersteuert | Dauerhaft chaotisch | Unbrauchbare Signale | ❌ Schlecht |
| **SHIB/PEPE** | Null — reine Pumps | Dauerhaft Chaos | Keine FUSION-Basis | ❌❌ Nicht geeignet |

### Empfohlene Kombinationen (Ranking)

| Rang | Kombination | Begründung |
|---|---|---|
| 🥇 1 | **BTC 1h / 2h** | Bester Hurst in Bullphasen, starke FUSION-Signale, viele Trades |
| 🥇 1 | **ETH 1h / 2h** | Ähnlich BTC, sehr gute Persistenz-Erkennung |
| 🥈 2 | **SOL 1h** | Explosive Persistenz-Phasen, hohe Volumen-Surges |
| 🥉 3 | **BTC 4h** | Robustester Hurst-Wert, weniger aber qualitativ höhere Signale |
| 4 | **BNB 2h** | Stabile, vorhersehbare Persistenz |
| 4 | **AVAX 2h** | Gute Bullmarkt-Performance |
| 4 | **INJ 1h** | Explosive Trending-Phasen, hoher Hurst |
| ❌ | **15m** | Hurst- und Entropie-Fenster (je 5h) zu kurz für valide Messung |
| ❌ | **DOGE / SHIB** | Kein detektierbarer Hurst-Wert, dauerhaftes Chaos-Regime |

> **Hinweis:** ApexBot blockiert im CHAOS-Regime (Entropie > 0.70) alle Trades. Bei Meme-Coins ist die Entropie chronisch hoch — der Bot tradet dort de facto nie.


---

## Coin & Timeframe Empfehlungen

ApexBot kombiniert **RADAR** (Hurst-Exponent + Entropie zur Regime-Erkennung) mit **FUSION** (P(win)-Scoring via EMA, RSI, Volumen, Kerzenform). Benötigt: Coins mit detektierbarer Persistenz (Hurst > 0.55 = trending) und klaren Volumen- sowie Momentum-Mustern.

### Effektive Zeitspannen je Timeframe

| TF | Hurst(20K) | Entropy(20K) | ADX(14) | EMA20/50 | Geeignet |
|---|---|---|---|---|---|
| 15m | 5h | 5h | 3.5h | 5h / 12.5h | ⚠️ |
| 30m | 10h | 10h | 7h | 10h / 25h | ⚠️ |
| **1h** | **20h** | **20h** | **14h** | **20h / 50h** | **✅✅** |
| **2h** | **40h** | **40h** | **28h** | **40h / 100h** | **✅✅** |
| **4h** | **80h** | **80h** | **56h** | **80h / 200h** | **✅✅** |
| 6h | 120h | 120h | 84h | 120h / 300h | ✅ |
| 1d | 20d | 20d | 14d | 20d / 50d | ✅ |

Der Hurst-Exponent braucht mindestens 20h Daten (1h x 20 Kerzen) um zwischen Persistenz und Random Walk zu unterscheiden. Auf 15m misst er nur 5h — zu wenig für statistische Verlässlichkeit. Ab 1h wird die Persistenz-Erkennung aussagekräftig; ab 4h ist sie robust.

### Coin-Eignung

| Coin | Hurst-Persistenz | Entropie-Profil | FUSION-Signale | Bewertung |
|---|---|---|---|---|
| **BTC** | Hoch in Bullphasen (H ~0.6-0.7) | Klare Entropie-Reduktion vor Breakouts | Starke EMA/RSI/Volumen-Kombination | ✅✅ Beste Wahl |
| **ETH** | Hoch — ähnlich BTC | Gutes Entropie-Profil | Klare FUSION-Signale | ✅✅ Sehr gut |
| **SOL** | Gut — explosive Persistenzphasen | Starke Entropie-Reduktion | Hohe Volumen-Surges erkennbar | ✅ Gut |
| **BNB** | Gut — stabile, niedrige Entropie | Klares Profil | Moderate FUSION-Signale | ✅ Gut |
| **AVAX** | Gut — klare Persistenzphasen | Gutes Signal | Gute Volumen-Patterns | ✅ Gut |
| **TON** | Gut — wachsende Trending-Struktur | Moderate Entropie | Aufbauende FUSION-Basis | ✅ Gut |
| **INJ** | Gut — explosive Trending-Phasen | Gutes Signal | Hohe Momentum-Signale | ✅ Gut |
| **LTC** | Mittel — BTC-korreliert, moderater Hurst | Mittel | Moderate Signale | ⚠️ Mittel |
| **XRP** | Mittel — Hurst nahe 0.5 beim Ranging | Mittel | Unregelmäßig | ⚠️ Mittel |
| **ADA** | Schwach — häufig Random Walk (H ~0.5) | Wenig Struktur | Schwache Signale | ⚠️ Schwach |
| **DOGE** | Nicht vorhanden — Sentiment übersteuert | Dauerhaft chaotisch | Unbrauchbare Signale | ❌ Schlecht |
| **SHIB/PEPE** | Null — reine Pumps | Dauerhaft Chaos | Keine FUSION-Basis | ❌❌ Nicht geeignet |

### Empfohlene Kombinationen (Ranking)

| Rang | Kombination | Begründung |
|---|---|---|
| 🥇 1 | **BTC 1h / 2h** | Bester Hurst in Bullphasen, starke FUSION-Signale, viele Trades |
| 🥇 1 | **ETH 1h / 2h** | Ähnlich BTC, sehr gute Persistenz-Erkennung |
| 🥈 2 | **SOL 1h** | Explosive Persistenz-Phasen, hohe Volumen-Surges |
| 🥉 3 | **BTC 4h** | Robustester Hurst-Wert, weniger aber qualitativ höhere Signale |
| 4 | **BNB 2h** | Stabile, vorhersehbare Persistenz |
| 4 | **AVAX 2h** | Gute Bullmarkt-Performance |
| 4 | **INJ 1h** | Explosive Trending-Phasen, hoher Hurst |
| ❌ | **15m** | Hurst- und Entropie-Fenster (je 5h) zu kurz für valide Messung |
| ❌ | **DOGE / SHIB** | Kein detektierbarer Hurst-Wert, dauerhaftes Chaos-Regime |

> **Hinweis:** ApexBot blockiert im CHAOS-Regime (Entropie > 0.70) alle Trades. Bei Meme-Coins ist die Entropie chronisch hoch — der Bot tradet dort de facto nie.


---

## Scoring & Validierung

```
Score = GeoMean(Cycle-Multiplier) × log1p(Anzahl Cycles) × (1 + Target-Hit-Rate)
```

- **OOS-Ratio ≥ 0.5** → Config valid (Out-of-Sample hält ≥ 50% der Train-Performance)
- **OOS-Ratio < 0.5** → Overfit — Config verwerfen, mehr Daten oder weniger Trials

