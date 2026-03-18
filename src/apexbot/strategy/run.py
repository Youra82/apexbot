# src/apexbot/strategy/run.py
"""
APEXBOT — Strategy Runner

Modi:
  --mode signal : RADAR + FUSION pruefen, Trade platzieren wenn Signal
  --mode check  : Offene Position pruefen, Cycle-State aktualisieren
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.utils.exchange import Exchange
from apexbot.utils.telegram import send_message
from apexbot.utils.trade_manager import execute_apex_trade, check_position_closed
from apexbot.modules.radar import detect_regime
from apexbot.modules.fusion import compute_fusion_score
from apexbot.modules.compounder import (
    load_state, save_state, get_position_size,
    record_trade_result, compute_optimal_exit_trade
)


# ── Logging ─────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    log_dir  = os.path.join(PROJECT_ROOT, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'apexbot.log')

    logger = logging.getLogger('apexbot')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter('%(asctime)s [APEX] %(levelname)s: %(message)s', datefmt='%H:%M:%S'))
        logger.addHandler(ch)
        logger.propagate = False
    return logger


# ── Main run ─────────────────────────────────────────────────────────────────

def run(mode: str, settings: dict, account: dict, telegram_config: dict, logger: logging.Logger):
    symbol    = settings['symbol']
    timeframe = settings['timeframe']

    state = load_state()
    logger.info(
        f"=== APEX {mode.upper()} | Cycle {state['cycle_number']} | "
        f"Trade {state['trade_number']} | Kapital: {state['current_capital_usdt']:.2f} USDT ==="
    )

    # Auto-optimize exit trade count
    if settings['cycle'].get('auto_optimize_exit'):
        optimal = compute_optimal_exit_trade(Path(PROJECT_ROOT) / 'artifacts' / 'cycles')
        if optimal:
            settings['cycle']['max_trades_per_cycle'] = optimal
            logger.info(f"Auto-Optimal Exit: Trade {optimal}")

    exchange = Exchange(account)

    # ── CHECK MODE ───────────────────────────────────────────────────────────
    if mode == 'check':
        if not state.get('active_position'):
            logger.info("Kein aktiver Trade. Nichts zu pruefen.")
            return

        closed, _ = check_position_closed(exchange, symbol, telegram_config, state, logger)

        if closed:
            # Echte Balance von Exchange holen fuer genaues Compounding
            real_balance = exchange.fetch_balance_usdt()
            pnl = real_balance - state['current_capital_usdt']
            logger.info(f"Trade geschlossen. Balance: {real_balance:.2f} | PnL: {pnl:.2f} USDT")

            # Neues Kapital setzen (direkt aus Exchange-Balance)
            state['current_capital_usdt'] = real_balance
            state['peak_capital_usdt'] = max(state['peak_capital_usdt'], real_balance)
            state['active_position'] = None

            # Cycle-Ende pruefen
            state = record_trade_result(state, pnl > 0, pnl, settings)
            save_state(state)

            # Telegram: Cycle-Status
            start = settings['cycle']['start_capital_usdt']
            mult  = real_balance / start if start > 0 else 1.0
            send_message(
                telegram_config.get('bot_token'),
                telegram_config.get('chat_id'),
                f"APEX Cycle {state['cycle_number'] - 1} Update\n"
                f"Trade {state['trade_number']} / {settings['cycle']['max_trades_per_cycle']}\n"
                f"Balance: {real_balance:.2f} USDT ({mult:.1f}x)"
            )
        return

    # ── SIGNAL MODE ──────────────────────────────────────────────────────────
    if state.get('active_position'):
        logger.info("Position bereits offen. Ueberspringe Signal-Check.")
        return

    # RADAR
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=200)
    if df.empty:
        logger.warning("Keine OHLCV-Daten. Ueberspringe.")
        return

    regime = detect_regime(df, settings)
    logger.info(f"RADAR Regime: {regime}")

    if regime != 'HUNT':
        logger.info(f"Regime {regime} — kein Trade.")
        return

    # FUSION
    fusion = compute_fusion_score(df, settings)
    logger.info(
        f"FUSION Score: {fusion['score']}/5 | "
        f"Direction: {fusion['direction']} | Mode: {fusion['mode']}"
    )

    if fusion['mode'] == 'SKIP':
        logger.info("Score zu niedrig — ueberspringe.")
        return

    # COMPOUNDER: Positionsgroesse
    usdt_amount = get_position_size(state, fusion['mode'], settings)
    if usdt_amount < 5.0:
        logger.warning(f"Kapital {usdt_amount:.2f} USDT < 5 USDT Minimum. Ueberspringe.")
        return

    # TRADE
    success = execute_apex_trade(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        direction=fusion['direction'],
        usdt_amount=usdt_amount,
        settings=settings,
        telegram_config=telegram_config
    )

    if success:
        # Position im State speichern
        df_entry = exchange.fetch_recent_ohlcv(symbol, '1m', limit=3)
        entry_price = float(df_entry['close'].iloc[-1]) if not df_entry.empty else 0
        sl_pct  = settings['risk']['stop_loss_pct']
        tp_mult = settings['risk']['take_profit_multiplier']
        sl_dist = entry_price * (sl_pct / 100.0)

        if fusion['direction'] == 'long':
            sl_p = entry_price - sl_dist
            tp_p = entry_price + sl_dist * tp_mult
        else:
            sl_p = entry_price + sl_dist
            tp_p = entry_price - sl_dist * tp_mult

        state['active_position'] = {
            'direction':    fusion['direction'],
            'entry_price':  entry_price,
            'sl_price':     sl_p,
            'tp_price':     tp_p,
            'usdt_amount':  usdt_amount,
            'leverage':     settings['leverage'],
            'fusion_score': fusion['score'],
            'timestamp':    datetime.now(timezone.utc).isoformat(),
        }
        state['status'] = 'IN_TRADE'
        save_state(state)
        logger.info("Trade platziert und State gespeichert.")
    else:
        logger.info("Trade nicht platziert.")

    logger.info("=== APEX Ende ===")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='apexbot Strategy Runner')
    parser.add_argument('--mode', required=True, choices=['signal', 'check'],
                        help='signal=Signal pruefen | check=Position pruefen')
    args = parser.parse_args()

    logger = setup_logging()

    try:
        with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
            settings = json.load(f)
        with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
            secrets = json.load(f)
    except FileNotFoundError as e:
        logger.critical(f"Datei nicht gefunden: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.critical(f"JSON-Fehler: {e}")
        sys.exit(1)

    accounts = secrets.get('apexbot', [])
    if not accounts:
        logger.critical("Keine 'apexbot'-Accounts in secret.json gefunden.")
        sys.exit(1)

    account         = accounts[0]
    telegram_config = secrets.get('telegram', {})

    try:
        run(args.mode, settings, account, telegram_config, logger)
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
