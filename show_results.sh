#!/bin/bash
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

VENV_PATH=".venv/bin/activate"

if [ ! -f "$VENV_PATH" ]; then
    echo -e "${RED}Fehler: .venv nicht gefunden. Erst install.sh ausführen.${NC}"
    exit 1
fi
source "$VENV_PATH"

echo ""
echo -e "${YELLOW}Wähle einen Analyse-Modus:${NC}"
echo "  1) Einzel-Backtest               (jedes Pair wird simuliert)"
echo "  2) Manuelle Symbol-Auswahl       (du wählst die Pairs aus)"
echo "  3) Automatische Symbol-Opt.      (Bot wählt das beste Pair)"
echo "  4) Config-Bibliothek             (optimierte RADAR/FUSION-Parameter)"
echo "  5) Interaktive Charts            (Candlestick + Entry/Exit-Marker)"
read -p "Auswahl (1-5) [Standard: 4]: " MODE

if [[ ! "$MODE" =~ ^[1-5]?$ ]]; then
    echo -e "${RED}Ungültige Eingabe. Verwende Standard (4).${NC}"
    MODE=4
fi
MODE=${MODE:-4}

# ─────────────────────────────────────────
# Mode 1: Einzel-Backtest
# ─────────────────────────────────────────
if [ "$MODE" == "1" ]; then
    echo ""
    read -p "Coin(s) eingeben (z.B. BTC ETH SOL) [leer=alle Configs]: " COINS_INPUT
    COINS_INPUT="${COINS_INPUT//[$'\r\n']/}"
    read -p "Timeframe(s) eingeben (z.B. 15m 1h 4h) [leer=alle Configs]: " TF_INPUT
    TF_INPUT="${TF_INPUT//[$'\r\n']/}"

    read -p "Startkapital in USDT [Standard: 50]: " CAPITAL
    CAPITAL="${CAPITAL//[$'\r\n ']/}"
    if ! [[ "$CAPITAL" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then CAPITAL=50; fi

    read -p "History-Tage [Standard: 180]: " DAYS
    DAYS="${DAYS//[$'\r\n ']/}"
    if ! [[ "$DAYS" =~ ^[0-9]+$ ]]; then DAYS=180; fi

    echo ""
    if [ -z "$COINS_INPUT" ] && [ -z "$TF_INPUT" ]; then
        # Kein Input → auto-detect alle verfügbaren Configs
        python3 src/apexbot/analysis/show_results.py \
            --mode 1 \
            --days "$DAYS" \
            --capital "$CAPITAL"
    else
        RESULT=$(python3 - <<PYEOF
import json
coins_raw = """$COINS_INPUT""".strip()
tfs_raw   = """$TF_INPUT""".strip()
try:
    with open('settings.json') as f: s = json.load(f)
    auto_sym = s.get('symbol', 'SOL/USDT:USDT')
    auto_tf  = s.get('timeframe', '30m')
except:
    auto_sym = 'SOL/USDT:USDT'; auto_tf = '30m'
def to_sym(c):
    c = c.strip().upper()
    return c if '/' in c else f"{c}/USDT:USDT"
coins = [to_sym(c) for c in coins_raw.split()] if coins_raw else [auto_sym]
tfs   = [t.strip() for t in tfs_raw.split()]   if tfs_raw   else [auto_tf]
print(' '.join(coins) + '|' + ' '.join(tfs))
PYEOF
)
        SYMS=$(echo "$RESULT" | cut -d'|' -f1 | xargs)
        TFS=$(echo  "$RESULT" | cut -d'|' -f2 | xargs)

        python3 src/apexbot/analysis/show_results.py \
            --mode 1 \
            --symbols "$SYMS" \
            --timeframes "$TFS" \
            --days "$DAYS" \
            --capital "$CAPITAL"
    fi

# ─────────────────────────────────────────
# Mode 2: Manuelle Symbol-Auswahl
# ─────────────────────────────────────────
elif [ "$MODE" == "2" ]; then
    echo ""

    # Erst Tabelle anzeigen (ohne Auswahl)
    python3 src/apexbot/analysis/show_results.py --mode 2

    echo ""
    echo "  Eingabe: Nummern kommagetrennt (z.B. 1,3,5) oder leer lassen"
    read -p "  Auswahl: " SELECTION
    SELECTION="${SELECTION//[$'\r\n']/}"

    if [ -n "$SELECTION" ]; then
        echo ""
        python3 src/apexbot/analysis/show_results.py --mode 2 --selection "$SELECTION"
    fi

# ─────────────────────────────────────────
# Mode 3: Automatische Symbol-Opt.
# ─────────────────────────────────────────
elif [ "$MODE" == "3" ]; then
    echo ""
    python3 src/apexbot/analysis/show_results.py --mode 3

# ─────────────────────────────────────────
# Mode 4: Config-Bibliothek
# ─────────────────────────────────────────
elif [ "$MODE" == "4" ]; then
    echo ""
    python3 src/apexbot/analysis/show_results.py --mode 4

# ─────────────────────────────────────────
# Mode 5: Interaktive Charts
# ─────────────────────────────────────────
elif [ "$MODE" == "5" ]; then
    echo ""
    python3 src/apexbot/analysis/show_results.py --mode 5
fi

deactivate
