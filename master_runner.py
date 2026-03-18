"""
APEXBOT Master Runner
Wird vom Cronjob aufgerufen. Fuehrt erst 'check' (offene Position pruefen),
dann 'signal' (neues Signal suchen) aus.
"""

import subprocess
import sys
import os
import json
import logging
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [MASTER] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('master')


def run_mode(mode: str) -> int:
    result = subprocess.run(
        [sys.executable, 'src/apexbot/strategy/run.py', '--mode', mode],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True
    )
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='')
    return result.returncode


def main():
    logger.info(f"=== APEX Master Runner | {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC ===")

    # Schritt 1: Position pruefen (TP/SL getroffen?)
    logger.info("Schritt 1: Position-Check...")
    rc = run_mode('check')
    if rc != 0:
        logger.warning(f"check-Modus beendet mit Exit-Code {rc}")

    # Schritt 2: Signal suchen (nur wenn kein Trade aktiv)
    logger.info("Schritt 2: Signal-Check...")
    rc = run_mode('signal')
    if rc != 0:
        logger.warning(f"signal-Modus beendet mit Exit-Code {rc}")

    logger.info("=== Master Runner abgeschlossen ===")


if __name__ == '__main__':
    main()
