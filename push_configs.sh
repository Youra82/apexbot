#!/bin/bash
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR"

CONFIGS_DIR="artifacts/configs"

echo ""
echo -e "${YELLOW}========== CONFIGS PUSHEN ==========${NC}"
echo ""

# Prüfe ob Config-Dateien existieren
CONFIG_COUNT=$(ls "$CONFIGS_DIR"/config_*.json 2>/dev/null | wc -l)
if [ "$CONFIG_COUNT" -eq 0 ]; then
    echo -e "${RED}❌ Keine Konfigurationsdateien gefunden in: $CONFIGS_DIR${NC}"
    echo -e "${YELLOW}Bitte zuerst run_pipeline.sh ausfuehren.${NC}"
    exit 1
fi

echo "Gefundene Konfigurationen:"
for f in "$CONFIGS_DIR"/config_*.json; do
    echo "  - $(basename "$f")"
done
echo ""

# Änderungen prüfen
git add "$CONFIGS_DIR"/config_*.json
STAGED=$(git diff --cached --name-only)

if [ -z "$STAGED" ]; then
    echo -e "${YELLOW}ℹ  Keine Änderungen — Configs sind bereits aktuell im Repo.${NC}"
    exit 0
fi

echo "Geänderte Dateien:"
echo "$STAGED" | sed 's/^/  /'
echo ""

# Commit-Nachricht generieren
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
git commit -m "Update: Optimierte Configs aktualisiert ($TIMESTAMP)"

# Push (mit automatischem Rebase bei Konflikt)
echo ""
echo -e "${YELLOW}Pushe auf origin/main...${NC}"
git push origin HEAD:main

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Configs erfolgreich gepusht!${NC}"
else
    echo ""
    echo -e "${YELLOW}Remote hat neuere Commits — führe Rebase durch...${NC}"
    git pull origin main --rebase
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Rebase fehlgeschlagen. Bitte manuell lösen.${NC}"
        exit 1
    fi
    git push origin HEAD:main
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✅ Configs erfolgreich gepusht!${NC}"
    else
        echo -e "${RED}❌ Push nach Rebase fehlgeschlagen.${NC}"
        exit 1
    fi
fi
