#!/bin/bash
# update.sh — Update von apexbot vom Git (titanbot-Stil)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starte apexbot Update..."

if [ -f "secret.json" ]; then
    cp secret.json secret.json.bak
    echo "secret.json gesichert."
fi

git fetch origin
git reset --hard origin/main
# Configs entfernen die NICHT im Repo sind (alte ungetrackte Dateien)
git clean -f artifacts/configs/ 2>/dev/null || true

if [ -f "secret.json.bak" ]; then
    cp secret.json.bak secret.json
    rm secret.json.bak
    echo "secret.json wiederhergestellt."
fi

find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

chmod +x *.sh

echo "Update abgeschlossen!"
