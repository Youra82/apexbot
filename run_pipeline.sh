#!/bin/bash
# run_pipeline.sh — apexbot Optimierungs-Pipeline

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"
OPTIMIZER="src/apexbot/analysis/optimizer.py"

echo -e "${BLUE}======================================================="
echo "       apexbot — Optimierungs-Pipeline"
echo -e "=======================================================${NC}"

if [ ! -f "$PYTHON" ]; then
    echo -e "${RED}Fehler: .venv nicht gefunden. install.sh ausführen.${NC}"
    exit 1
fi
source "$SCRIPT_DIR/.venv/bin/activate"
echo -e "${GREEN}✔ Virtuelle Umgebung aktiviert.${NC}"

# --- Aufräumen ---
echo ""
echo -e "${YELLOW}Möchtest du alle alten Configs vor dem Start löschen?${NC}"
read -p "Empfohlen für Neustart. (j/n) [Standard: n]: " CLEANUP; CLEANUP=${CLEANUP:-n}
CLEANUP="${CLEANUP//[$'\r\n ']/}"
if [[ "$CLEANUP" == "j" || "$CLEANUP" == "J" ]]; then
    rm -f "$SCRIPT_DIR/artifacts/configs/config_"*.json
    rm -f "$SCRIPT_DIR/artifacts/results/backtest_"*.json
    echo -e "${GREEN}✔ Alte Configs und Ergebnisse gelöscht.${NC}"
else
    echo -e "${GREEN}✔ Alte Ergebnisse beibehalten.${NC}"
fi

# --- Eingaben ---
echo ""
read -p "Handelspaar(e) eingeben (z.B. SOL ETH BTC): " COINS_RAW
read -p "Zeitfenster eingeben (z.B. 1h 4h): " TF_RAW
COINS_RAW="${COINS_RAW//[$'\r\n']/}"
TF_RAW="${TF_RAW//[$'\r\n']/}"

echo -e "\n${BLUE}--- Empfehlung: Optimaler Rückblick-Zeitraum ---${NC}"
printf "+-------------+--------------------------------+\n"
printf "| Zeitfenster | Empfohlener Rückblick (Tage)   |\n"
printf "+-------------+--------------------------------+\n"
printf "| 5m, 15m     | 30 - 90 Tage                   |\n"
printf "| 30m, 1h     | 180 - 365 Tage                 |\n"
printf "| 2h, 4h      | 365 - 730 Tage                 |\n"
printf "| 6h, 1d      | 1095 - 1825 Tage               |\n"
printf "+-------------+--------------------------------+\n"

read -p "Startdatum (JJJJ-MM-TT) oder 'a' für Automatik [Standard: a]: " START_DATE
START_DATE="${START_DATE//[$'\r\n ']/}"
START_DATE=${START_DATE:-a}

read -p "Startkapital in USDT [Standard: 50]: " CAPITAL
CAPITAL="${CAPITAL//[$'\r\n ']/}"
CAPITAL=${CAPITAL:-50}

read -p "CPU-Kerne [Standard: -1 für alle]: " N_JOBS
N_JOBS="${N_JOBS//[$'\r\n ']/}"
N_JOBS=${N_JOBS:--1}

read -p "Anzahl Trials [Standard: 200]: " N_TRIALS
N_TRIALS="${N_TRIALS//[$'\r\n ']/}"
N_TRIALS=${N_TRIALS:-200}

echo ""
echo -e "${YELLOW}Wähle einen Optimierungs-Modus:${NC}"
echo "  1) Strenger Modus   (Profitabel & Sicher — Kelly-Sizing, DD-Kontrolle)"
echo "  2) 'Finde das Beste' (Max Profit — All-In, voller Einsatz)"
read -p "Auswahl (1-2) [Standard: 2]: " OPT_MODE
OPT_MODE="${OPT_MODE//[$'\r\n ']/}"
OPT_MODE=${OPT_MODE:-2}

read -p "Max Drawdown % [Standard: 50]: " MAX_DD
MAX_DD="${MAX_DD//[$'\r\n ']/}"
MAX_DD=${MAX_DD:-50}

if [ "$OPT_MODE" == "1" ]; then
    MODE_ARG="strict"
    read -p "Min Win-Rate % [Standard: 40]: " MIN_WR
    MIN_WR="${MIN_WR//[$'\r\n ']/}"
    MIN_WR=${MIN_WR:-40}
    MIN_WR_ARG="--min-win-rate $MIN_WR"
    echo -e "${CYAN}Modus: STRICT | Max DD: ${MAX_DD}% | Min WR: ${MIN_WR}%${NC}"
else
    MODE_ARG="best_profit"
    MIN_WR_ARG=""
    echo -e "${CYAN}Modus: BEST PROFIT (All-In) | Max DD: ${MAX_DD}%${NC}"
fi

# --- Paare aufbauen ---
PAIRS=$("$PYTHON" - <<PYEOF
import json, os
coins_raw = """$COINS_RAW""".strip()
tfs_raw   = """$TF_RAW""".strip()
try:
    with open('settings.json') as f: s = json.load(f)
    auto_sym = s.get('symbol', 'SOL/USDT:USDT')
    auto_tf  = s.get('timeframe', '1h')
except Exception:
    auto_sym = 'SOL/USDT:USDT'; auto_tf = '1h'
def to_sym(c):
    c = c.strip().upper()
    return c if '/' in c else f"{c}/USDT:USDT"
coins = [to_sym(c) for c in coins_raw.split()] if coins_raw else [auto_sym]
tfs   = [t.strip() for t in tfs_raw.split()]   if tfs_raw   else [auto_tf]
for sym in coins:
    for tf in tfs:
        print(f"{sym} {tf}")
PYEOF
)

echo ""
echo -e "${CYAN}Scan-Paare:${NC}"
echo "$PAIRS" | while read -r sym tf; do
    [ -n "$sym" ] && echo "  → $sym ($tf)"
done

# --- Pipeline starten ---
echo ""
echo -e "${BLUE}======================================================="
echo "  Pipeline startet..."
echo -e "=======================================================${NC}"

PAIR_COUNT=$(echo "$PAIRS" | grep -c .)
CURRENT=0

echo "$PAIRS" | while IFS=' ' read -r sym tf; do
    [ -z "$sym" ] && continue
    CURRENT=$((CURRENT + 1))

    # Tage berechnen
    if [ "$START_DATE" == "a" ]; then
        case "$tf" in
            1m|3m|5m)  DAYS=60   ;;
            15m|30m)   DAYS=180  ;;
            1h)        DAYS=365  ;;
            2h|4h)     DAYS=730  ;;
            6h|1d)     DAYS=1095 ;;
            *)         DAYS=365  ;;
        esac
    else
        DAYS=$("$PYTHON" -c "from datetime import date; print((date.today() - date.fromisoformat('$START_DATE')).days)" 2>/dev/null || echo 365)
    fi

    echo ""
    echo -e "${CYAN}[$CURRENT/$PAIR_COUNT] $sym ($tf) | ${DAYS}d | Kapital: ${CAPITAL} USDT | ${N_TRIALS} Trials${NC}"

    "$PYTHON" "$OPTIMIZER" \
        --symbol      "$sym" \
        --timeframe   "$tf" \
        --days        "$DAYS" \
        --trials      "$N_TRIALS" \
        --capital     "$CAPITAL" \
        --mode        "$MODE_ARG" \
        --max-drawdown "$MAX_DD" \
        --n-jobs      "$N_JOBS" \
        --test-fraction 0.30 \
        $MIN_WR_ARG

    if [ $? -ne 0 ]; then
        echo -e "${RED}Fehler bei $sym ($tf). Überspringe.${NC}"
    fi
done

echo ""
echo -e "${BLUE}======================================================="
echo -e "  ${GREEN}✔ Pipeline abgeschlossen!${NC}"
echo ""
echo "  Nächste Schritte:"
echo "    Ergebnisse ansehen:  ./show_results.sh  (Option 1 oder 4)"
echo "    Bot starten:         crontab -e"
echo "       */5 * * * * cd $SCRIPT_DIR && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1"
echo -e "=======================================================${NC}"

deactivate
