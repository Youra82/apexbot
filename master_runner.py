"""
APEXBOT Master Runner
Wird vom Cronjob aufgerufen.
Schritt 1: Turnier — bestes Pair nach Hurst × Entropie-Score waehlen.
Schritt 2: check (offene Position pruefen).
Schritt 3: signal (neues Signal suchen).
"""

import subprocess
import sys
import os
import json
import logging
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [MASTER] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('master')


def score_pair(symbol: str, timeframe: str, account: dict) -> float:
    """Hurst × (1 - Entropie): hoher Score = trendend + geordnet."""
    try:
        import ccxt
        exchange = ccxt.bitget({
            'apiKey':    account.get('api_key', ''),
            'secret':    account.get('api_secret', ''),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'},
        })
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=60)
        if not ohlcv:
            return 0.0
        import pandas as pd
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        from apexbot.modules.radar import compute_pair_score
        return compute_pair_score(df)
    except Exception as e:
        logger.warning(f"score_pair {symbol} {timeframe}: {e}")
        return 0.0


def tournament_winner(settings: dict, account: dict) -> tuple[str, str]:
    """Gibt Symbol + Timeframe mit hoechstem Vorhersagbarkeits-Score zurueck."""
    t_cfg = settings.get('tournament', {})
    if not t_cfg.get('enabled', False):
        return settings['symbol'], settings['timeframe']

    candidate_pairs = t_cfg.get('candidate_pairs', [settings['symbol']])
    candidate_tfs   = t_cfg.get('candidate_timeframes', [settings['timeframe']])

    scored = []
    for sym in candidate_pairs:
        for tf in candidate_tfs:
            s = score_pair(sym, tf, account)
            scored.append((s, sym, tf))
            logger.info(f"  Turnier: {sym} {tf} → Score {s:.4f}")

    if not scored:
        return settings['symbol'], settings['timeframe']

    scored.sort(reverse=True)
    best_score, best_sym, best_tf = scored[0]
    logger.info(f"  Turnier-Gewinner: {best_sym} {best_tf} (Score {best_score:.4f})")
    return best_sym, best_tf


def run_mode(mode: str, symbol: str, timeframe: str) -> int:
    result = subprocess.run(
        [sys.executable, 'src/apexbot/strategy/run.py',
         '--mode', mode, '--symbol', symbol, '--timeframe', timeframe],
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

    try:
        with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
            settings = json.load(f)
        with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
            secrets = json.load(f)
    except Exception as e:
        logger.critical(f"Config-Fehler: {e}")
        sys.exit(1)

    accounts = secrets.get('apexbot', [])
    if not accounts:
        logger.critical("Keine 'apexbot'-Accounts in secret.json.")
        sys.exit(1)
    account = accounts[0]

    # Turnier: bestes Pair auswaehlen
    symbol, timeframe = tournament_winner(settings, account)

    # Schritt 1: Position pruefen
    logger.info(f"Schritt 1: Check | {symbol} {timeframe}")
    rc = run_mode('check', symbol, timeframe)
    if rc != 0:
        logger.warning(f"check beendet mit Exit-Code {rc}")

    # Schritt 2: Signal suchen
    logger.info(f"Schritt 2: Signal | {symbol} {timeframe}")
    rc = run_mode('signal', symbol, timeframe)
    if rc != 0:
        logger.warning(f"signal beendet mit Exit-Code {rc}")

    logger.info("=== Master Runner abgeschlossen ===")


if __name__ == '__main__':
    main()
