#!/bin/bash
# install.sh — Erstinstallation von apexbot auf dem VPS
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  apexbot — Installation"
echo "============================================================"

if [ ! -d ".venv" ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv .venv
fi

echo "Installiere Abhaengigkeiten..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

mkdir -p artifacts/logs artifacts/cycles artifacts/state logs

chmod +x *.sh

if [ ! -f "secret.json" ]; then
    cp secret.json.example secret.json
    echo ""
    echo "WICHTIG: secret.json wurde erstellt."
    echo "         Bitte mit echten API-Keys befuellen!"
fi

echo ""
echo "Installation abgeschlossen!"
echo ""
echo "Naechste Schritte:"
echo "  1. secret.json mit Bitget API-Keys befuellen"
echo "  2. settings.json pruefen (Symbol, Timeframe, Kapital)"
echo "  3. ./run_pipeline.sh ausfuehren (Backtest)"
echo "  4. Cronjob einrichten:"
echo "     */5 * * * * cd $SCRIPT_DIR && .venv/bin/python3 master_runner.py >> logs/cron.log 2>&1"
