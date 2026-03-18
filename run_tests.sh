#!/bin/bash
echo "--- Starte apexbot Tests ---"

if [ ! -f ".venv/bin/activate" ]; then
    echo "Fehler: .venv nicht gefunden. Bitte install.sh ausfuehren."
    exit 1
fi
source .venv/bin/activate

echo "Fuehre Pytest aus..."
if python3 -m pytest -v -s; then
    echo "Alle Tests bestanden."
    EXIT_CODE=0
else
    PYTEST_EXIT_CODE=$?
    if [ $PYTEST_EXIT_CODE -eq 5 ]; then
        echo "Keine Tests gefunden."
        EXIT_CODE=0
    else
        echo "Tests fehlgeschlagen (Exit Code: $PYTEST_EXIT_CODE)."
        EXIT_CODE=$PYTEST_EXIT_CODE
    fi
fi

deactivate
echo "--- Tests abgeschlossen ---"
exit $EXIT_CODE
