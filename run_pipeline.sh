#!/bin/bash
# run_pipeline.sh — apexbot Training Pipeline
#
# Schritt 1: Symbol/Timeframe-Auswahl
# Schritt 2: Historische Daten + Parameter-Optimizer (Optuna)
# Schritt 3: Backtest mit optimierten Parametern
# Schritt 4: Ergebnisse

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}FEHLER: .venv nicht gefunden. Erst install.sh ausfuehren!${NC}"
    exit 1
fi
source "$SCRIPT_DIR/.venv/bin/activate"

echo ""
echo "======================================================="
echo "       apexbot — Training Pipeline"
echo "======================================================="
echo ""

# ── Alte Configs loeschen? ───────────────────────────────────────────────────
CFG_DIR="$SCRIPT_DIR/artifacts/configs"
if [ -d "$CFG_DIR" ] && [ "$(ls -A $CFG_DIR 2>/dev/null)" ]; then
    read -p "Alte optimierte Configs loeschen (Neustart)? (j/n) [Standard: n]: " RESET_CFG
    RESET_CFG="${RESET_CFG//[$'\r\n ']/}"
    if [[ "$RESET_CFG" == "j" || "$RESET_CFG" == "J" ]]; then
        rm -f "$CFG_DIR"/*.json
        echo -e "${GREEN}✔ Alte Configs geloescht.${NC}"
    else
        echo -e "${GREEN}✔ Bestehende Configs werden beibehalten.${NC}"
    fi
fi

# ── Coins / Timeframes ───────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Coins und Timeframes:${NC}"
echo "  Leer lassen → Symbol/Timeframe aus settings.json uebernehmen"
echo ""
read -p "Coin(s) eingeben (z.B. BTC ETH SOL) [leer=auto]: " COINS_INPUT
read -p "Timeframe(s) eingeben (z.B. 15m 1h 4h) [leer=auto]: " TF_INPUT

COINS_INPUT="${COINS_INPUT//[$'\r\n']/}"
TF_INPUT="${TF_INPUT//[$'\r\n']/}"

# Paare aufloesen via Python
PAIRS=$($PYTHON - <<'PYEOF'
import os, sys, json

coins_raw = os.environ.get('APEX_OVERRIDE_COINS', '').strip()
tfs_raw   = os.environ.get('APEX_OVERRIDE_TFS', '').strip()

try:
    with open('settings.json') as f:
        s = json.load(f)
    auto_sym = s.get('symbol', 'BTC/USDT:USDT')
    auto_tf  = s.get('timeframe', '15m')
except Exception:
    auto_sym = 'BTC/USDT:USDT'
    auto_tf  = '15m'

def to_symbol(coin):
    coin = coin.strip().upper()
    if '/' not in coin:
        return f"{coin}/USDT:USDT"
    return coin

coins = [to_symbol(c) for c in coins_raw.split()] if coins_raw else [auto_sym]
tfs   = [t.strip() for t in tfs_raw.split()]      if tfs_raw   else [auto_tf]

for sym in coins:
    for tf in tfs:
        print(f"{sym} {tf}")
PYEOF
)

if [ -n "$COINS_INPUT" ]; then
    export APEX_OVERRIDE_COINS="$COINS_INPUT"
fi
if [ -n "$TF_INPUT" ]; then
    export APEX_OVERRIDE_TFS="$TF_INPUT"
fi

# Paare neu generieren mit gesetzten Overrides
PAIRS=$($PYTHON - <<'PYEOF'
import os, sys, json

coins_raw = os.environ.get('APEX_OVERRIDE_COINS', '').strip()
tfs_raw   = os.environ.get('APEX_OVERRIDE_TFS', '').strip()

try:
    with open('settings.json') as f:
        s = json.load(f)
    auto_sym = s.get('symbol', 'BTC/USDT:USDT')
    auto_tf  = s.get('timeframe', '15m')
except Exception:
    auto_sym = 'BTC/USDT:USDT'
    auto_tf  = '15m'

def to_symbol(coin):
    coin = coin.strip().upper()
    if '/' not in coin:
        return f"{coin}/USDT:USDT"
    return coin

coins = [to_symbol(c) for c in coins_raw.split()] if coins_raw else [auto_sym]
tfs   = [t.strip() for t in tfs_raw.split()]      if tfs_raw   else [auto_tf]

for sym in coins:
    for tf in tfs:
        print(f"{sym} {tf}")
PYEOF
)

echo ""
echo -e "${CYAN}Scan-Paare:${NC}"
echo "$PAIRS" | while read -r sym tf; do
    echo "  → $sym ($tf)"
done

# ── History-Tage ─────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}--- Empfehlung: Optimaler Rueckblick-Zeitraum ---${NC}"
printf "  %-12s  %s\n" "Zeitfenster" "Empfohlene Tage"
printf "  %-12s  %s\n" "──────────" "───────────────"
printf "  %-12s  %s\n" "1m, 5m"     "30 - 90 Tage"
printf "  %-12s  %s\n" "15m, 30m"   "60 - 180 Tage"
printf "  %-12s  %s\n" "1h"         "180 - 365 Tage"
printf "  %-12s  %s\n" "4h"         "365 - 730 Tage"
echo ""
read -p "History-Tage (oder 'a' fuer Automatik) [Standard: a]: " HISTORY_INPUT
HISTORY_INPUT="${HISTORY_INPUT//[$'\r\n ']/}"

if [[ "$HISTORY_INPUT" =~ ^[0-9]+$ ]]; then
    DAYS="$HISTORY_INPUT"
    echo -e "${CYAN}ℹ  Fester Rueckblick: ${DAYS} Tage${NC}"
else
    # Automatik: erster Timeframe bestimmt Default
    FIRST_TF=$(echo "$PAIRS" | head -1 | awk '{print $2}')
    case "$FIRST_TF" in
        1m|5m)         DAYS=60  ;;
        15m|30m)       DAYS=120 ;;
        1h)            DAYS=270 ;;
        2h|4h)         DAYS=540 ;;
        6h|1d)         DAYS=900 ;;
        *)             DAYS=180 ;;
    esac
    echo -e "${GREEN}✔ Automatischer Rueckblick: ${DAYS} Tage (nach Timeframe ${FIRST_TF}).${NC}"
fi

# ── Parameter-Optimizer ──────────────────────────────────────────────────────
echo ""
read -p "Parameter-Optimizer ausfuehren? (Optuna) (j/n) [Standard: j]: " RUN_OPT
RUN_OPT="${RUN_OPT//[$'\r\n ']/}"
RUN_OPT="${RUN_OPT:-j}"

TRIALS=100
MIN_TRADES=0
TEST_FRACTION=0.0
APPLY_ARG=""
if [[ "$RUN_OPT" == "j" || "$RUN_OPT" == "J" || "$RUN_OPT" == "y" ]]; then
    read -p "Anzahl Optuna-Trials [Standard: 100]: " TRIALS_INPUT
    TRIALS_INPUT="${TRIALS_INPUT//[$'\r\n ']/}"
    if [[ "$TRIALS_INPUT" =~ ^[0-9]+$ ]]; then TRIALS=$TRIALS_INPUT; fi

    read -p "Min-Trades-Constraint (0=aus, z.B. 20) [Standard: 0]: " MT_INPUT
    MT_INPUT="${MT_INPUT//[$'\r\n ']/}"
    if [[ "$MT_INPUT" =~ ^[0-9]+$ ]]; then MIN_TRADES=$MT_INPUT; fi

    read -p "Walk-Forward OOS-Anteil (0=aus, z.B. 0.3 fuer 30%%) [Standard: 0]: " TF_INPUT2
    TF_INPUT2="${TF_INPUT2//[$'\r\n ']/}"
    if [[ "$TF_INPUT2" =~ ^0\.[0-9]+$ || "$TF_INPUT2" =~ ^[0-9]+$ ]]; then TEST_FRACTION=$TF_INPUT2; fi

    read -p "Beste Parameter direkt auf settings.json anwenden? (j/n) [Standard: n]: " APPLY_INPUT
    APPLY_INPUT="${APPLY_INPUT//[$'\r\n ']/}"
    if [[ "$APPLY_INPUT" == "j" || "$APPLY_INPUT" == "J" ]]; then
        APPLY_ARG="--apply"
    fi
fi

# ── Backtest ─────────────────────────────────────────────────────────────────
echo ""
read -p "Backtest nach Optimierung durchfuehren? (j/n) [Standard: j]: " RUN_BT
RUN_BT="${RUN_BT//[$'\r\n ']/}"
RUN_BT="${RUN_BT:-j}"

CAPITAL=50
if [[ "$RUN_BT" == "j" || "$RUN_BT" == "J" || "$RUN_BT" == "y" ]]; then
    read -p "Startkapital in USDT [Standard: 50]: " CAP_INPUT
    CAP_INPUT="${CAP_INPUT//[$'\r\n ']/}"
    if [[ "$CAP_INPUT" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then CAPITAL=$CAP_INPUT; fi
fi

# ── Pipeline starten ─────────────────────────────────────────────────────────
echo ""
echo "======================================================="
echo "  Pipeline startet..."
echo "======================================================="
echo ""

PAIR_COUNT=$(echo "$PAIRS" | wc -l)
CURRENT=0

echo "$PAIRS" | while IFS=' ' read -r sym tf; do
    CURRENT=$((CURRENT + 1))
    echo ""
    echo -e "${CYAN}[$CURRENT/$PAIR_COUNT] Paar: $sym ($tf)${NC}"

    # Schritt 1: Parameter-Optimizer
    if [[ "$RUN_OPT" == "j" || "$RUN_OPT" == "J" || "$RUN_OPT" == "y" ]]; then
        echo -e "${YELLOW}  [Optimizer] Starte Optuna ($TRIALS Trials)...${NC}"
        $PYTHON "$SCRIPT_DIR/src/apexbot/analysis/optimizer.py" \
            --symbol "$sym" \
            --timeframe "$tf" \
            --days "$DAYS" \
            --trials "$TRIALS" \
            --min-trades "$MIN_TRADES" \
            --test-fraction "$TEST_FRACTION" \
            $APPLY_ARG
    fi

    # Schritt 2: Backtest
    if [[ "$RUN_BT" == "j" || "$RUN_BT" == "J" || "$RUN_BT" == "y" ]]; then
        echo -e "${YELLOW}  [Backtest] Simuliere...${NC}"
        $PYTHON "$SCRIPT_DIR/src/apexbot/analysis/show_results.py" \
            --mode 1 \
            --symbols "$sym" \
            --timeframes "$tf" \
            --days "$DAYS" \
            --capital "$CAPITAL"
    fi
done

echo ""
echo "======================================================="
echo -e "  ${GREEN}Pipeline abgeschlossen!${NC}"
echo ""
echo "  Naechste Schritte:"
echo "    1. Ergebnisse pruefen:    ./show_results.sh"
echo "    2. Status pruefen:        ./show_status.sh"
echo "    3. Cronjob einrichten:    crontab -e"
echo "       */5 * * * * cd $SCRIPT_DIR && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1"
echo "======================================================="

deactivate
