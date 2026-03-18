#!/bin/bash
# show_status.sh — Zeigt aktuellen Cycle-Status und Backtest-Ergebnisse
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

STATE_FILE="$SCRIPT_DIR/artifacts/state/global_state.json"
BACKTEST_FILE="$SCRIPT_DIR/artifacts/backtest_result.json"

echo ""
echo "======================================================="
echo "       apexbot — Status"
echo "======================================================="

# Aktueller Cycle-Status
if [ -f "$STATE_FILE" ]; then
    echo ""
    echo -e "${YELLOW}Cycle-Status:${NC}"
    $PYTHON - <<'PYEOF'
import json, sys
try:
    with open("artifacts/state/global_state.json") as f:
        s = json.load(f)
    print(f"  Cycle:         {s.get('cycle_number', '?')}")
    print(f"  Trade:         {s.get('trade_number', '?')}")
    print(f"  Kapital:       {s.get('current_capital_usdt', '?'):.2f} USDT")
    print(f"  Peak:          {s.get('peak_capital_usdt', '?'):.2f} USDT")
    print(f"  Status:        {s.get('status', '?')}")
    pos = s.get('active_position')
    if pos:
        print(f"  Aktive Pos:    {pos.get('direction', '?').upper()} | Entry: {pos.get('entry_price', '?'):.4f}")
    else:
        print(f"  Aktive Pos:    keine")
except Exception as e:
    print(f"  Fehler: {e}")
PYEOF
else
    echo -e "${RED}  Kein State gefunden.${NC}"
fi

# Cycle-History
CYCLE_DIR="$SCRIPT_DIR/artifacts/cycles"
if [ -d "$CYCLE_DIR" ] && [ "$(ls -A $CYCLE_DIR 2>/dev/null)" ]; then
    echo ""
    echo -e "${YELLOW}Letzte Cycles:${NC}"
    $PYTHON - <<'PYEOF'
import json, os
from pathlib import Path
files = sorted(Path("artifacts/cycles").glob("cycle_*.json"))[-10:]
for f in files:
    try:
        with open(f) as fp:
            c = json.load(fp)
        mult = c.get('multiplier', 0)
        emoji = "✅" if mult >= 1.0 else "❌"
        print(f"  {emoji} Cycle {c.get('cycle','?'):3d}: {c.get('start_capital',0):.0f} → {c.get('end_capital',0):.1f} USDT ({mult:.2f}x) | {c.get('reason','?')}")
    except Exception:
        pass
PYEOF
fi

# Letzter Backtest
if [ -f "$BACKTEST_FILE" ]; then
    echo ""
    echo -e "${YELLOW}Letzter Backtest:${NC}"
    $PYTHON - <<'PYEOF'
import json
try:
    with open("artifacts/backtest_result.json") as f:
        r = json.load(f)
    print(f"  Symbol:        {r.get('symbol','?')} {r.get('timeframe','?')}")
    print(f"  Trades:        {r.get('total_trades','?')} | Win-Rate: {r.get('win_rate_pct','?')}%")
    print(f"  Cycles:        {r.get('total_cycles','?')} | Avg: {r.get('avg_multiplier','?')}x | Max: {r.get('max_multiplier','?')}x")
    print(f"  Cycles > 1x:   {r.get('cycles_above_1x','?')}")
    print(f"  Stand:         {r.get('timestamp','?')}")
except Exception as e:
    print(f"  Fehler: {e}")
PYEOF
fi

echo ""
echo "======================================================="
