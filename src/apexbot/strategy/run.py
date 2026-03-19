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
from apexbot.utils.trade_manager import execute_apex_trade, check_position_closed, execute_partial_exit
from apexbot.modules.radar import detect_regime, compute_supertrend, get_higher_timeframe
from apexbot.modules.fusion import compute_fusion_score
from apexbot.modules.compounder import (
    load_state, save_state, get_position_size,
    record_trade_result, compute_optimal_exit_trade
)
from apexbot.modules.learner import (
    load_signal_weights, record_trade_signals,
    log_rl_decision, rl_should_trade
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _compute_volatility_bucket(df, atr_pct: float) -> int:
    """Convert normalized ATR to bucket 0/1/2 (low/mid/high)."""
    if atr_pct < 0.005:
        return 0
    elif atr_pct < 0.015:
        return 1
    return 2


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

    supertrend_cfg = settings.get('supertrend', {})
    partial_exit_cfg = settings.get('partial_exit', {})
    learner_cfg = settings.get('learner', {})

    # ── CHECK MODE ───────────────────────────────────────────────────────────
    if mode == 'check':
        if not state.get('active_position'):
            logger.info("Kein aktiver Trade. Nichts zu pruefen.")
            return

        pos_info  = state['active_position']
        direction = pos_info.get('direction', 'long')

        df_15m = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=200)

        # ── Supertrend Kill-Switch ────────────────────────────────────────
        if (supertrend_cfg.get('enabled', False)
                and supertrend_cfg.get('kill_switch', False)
                and not df_15m.empty
                and not pos_info.get('partial_closed', False)):
            try:
                st_dir = compute_supertrend(
                    df_15m,
                    period=int(supertrend_cfg.get('period', 10)),
                    multiplier=float(supertrend_cfg.get('multiplier', 3.0))
                )
                logger.info(f"{timeframe} Supertrend: {st_dir} | Position: {direction}")
                if st_dir != direction:
                    logger.warning(
                        f"KILL-SWITCH: Supertrend {st_dir} vs Position {direction} — schliesse!"
                    )
                    send_message(
                        telegram_config.get('bot_token'),
                        telegram_config.get('chat_id'),
                        f"APEX KILL-SWITCH: {symbol}\n"
                        f"Supertrend {st_dir.upper()} gegen Position {direction.upper()}\n"
                        f"Schliesse Position!"
                    )
                    exchange.cancel_all_orders_for_symbol(symbol)
                    exchange.close_position(symbol)

                    # Record result
                    real_balance = exchange.fetch_balance_usdt()
                    pnl = real_balance - state['current_capital_usdt']
                    state['current_capital_usdt'] = real_balance
                    state['peak_capital_usdt'] = max(state['peak_capital_usdt'], real_balance)

                    # Record signals and RL decision
                    signals = pos_info.get('signals', {})
                    won = pnl > 0
                    if signals and learner_cfg.get('adaptive_weights', False):
                        try:
                            record_trade_signals(signals, won)
                        except Exception as e:
                            logger.warning(f"record_trade_signals failed: {e}")

                    if learner_cfg.get('rl_gate', False):
                        try:
                            hour = int(pos_info.get('hour_of_entry', datetime.now(timezone.utc).hour))
                            atr_pct = (df_15m['high'] - df_15m['low']).iloc[-1] / df_15m['close'].iloc[-1]
                            vol_bucket = _compute_volatility_bucket(df_15m, atr_pct)
                            rl_state = {
                                'hour': hour,
                                'fusion_score': pos_info.get('fusion_score', 0),
                                'volatility_bucket': vol_bucket,
                                'cycle_phase': pos_info.get('cycle_phase', 1),
                                'direction': direction,
                            }
                            log_rl_decision(rl_state, won)
                        except Exception as e:
                            logger.warning(f"log_rl_decision failed: {e}")

                    state['active_position'] = None
                    state = record_trade_result(state, won, pnl, settings)
                    save_state(state)
                    return
            except Exception as e:
                logger.error(f"Supertrend kill-switch error: {e}", exc_info=True)

        # ── Partial Exit Check ────────────────────────────────────────────
        if (partial_exit_cfg.get('enabled', False)
                and not pos_info.get('partial_closed', False)
                and not df_15m.empty):
            try:
                positions = exchange.fetch_open_positions(symbol)
                if positions:
                    unr_pnl = float(positions[0].get('unrealizedPnl', 0.0))
                    usdt_amount = float(pos_info.get('usdt_amount', 0))
                    leverage    = int(pos_info.get('leverage', settings.get('leverage', 20)))
                    sl_pct      = float(settings['risk']['stop_loss_pct'])
                    threshold_11 = usdt_amount * leverage * (sl_pct / 100.0)

                    logger.info(
                        f"UnrPnL: {unr_pnl:.2f} USDT | 1:1 Threshold: {threshold_11:.2f} USDT"
                    )

                    if unr_pnl >= threshold_11:
                        logger.info("1:1 Threshold erreicht — starte Partial Exit!")
                        ok = execute_partial_exit(
                            exchange, symbol, pos_info, settings, telegram_config
                        )
                        if ok:
                            state['active_position']['partial_closed'] = True
                            save_state(state)
                            logger.info("Partial Exit abgeschlossen.")
            except Exception as e:
                logger.error(f"Partial exit check error: {e}", exc_info=True)

        # ── Standard position check ───────────────────────────────────────
        closed, _ = check_position_closed(exchange, symbol, telegram_config, state, logger)

        if closed:
            real_balance = exchange.fetch_balance_usdt()
            pnl = real_balance - state['current_capital_usdt']
            logger.info(f"Trade geschlossen. Balance: {real_balance:.2f} | PnL: {pnl:.2f} USDT")

            state['current_capital_usdt'] = real_balance
            state['peak_capital_usdt'] = max(state['peak_capital_usdt'], real_balance)

            # Record signals and RL decision
            signals = pos_info.get('signals', {})
            won = pnl > 0
            if signals and learner_cfg.get('adaptive_weights', False):
                try:
                    record_trade_signals(signals, won)
                except Exception as e:
                    logger.warning(f"record_trade_signals failed: {e}")

            if learner_cfg.get('rl_gate', False):
                try:
                    hour = int(pos_info.get('hour_of_entry', datetime.now(timezone.utc).hour))
                    if not df_15m.empty:
                        atr_pct = (df_15m['high'] - df_15m['low']).iloc[-1] / df_15m['close'].iloc[-1]
                    else:
                        atr_pct = 0.01
                    vol_bucket = _compute_volatility_bucket(df_15m, atr_pct)
                    rl_state = {
                        'hour': hour,
                        'fusion_score': pos_info.get('fusion_score', 0),
                        'volatility_bucket': vol_bucket,
                        'cycle_phase': pos_info.get('cycle_phase', 1),
                        'direction': direction,
                    }
                    log_rl_decision(rl_state, won)
                except Exception as e:
                    logger.warning(f"log_rl_decision failed: {e}")

            state['active_position'] = None
            state = record_trade_result(state, pnl > 0, pnl, settings)
            save_state(state)

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

    # Supertrend higher-TF filter
    if supertrend_cfg.get('enabled', False):
        try:
            higher_tf = get_higher_timeframe(timeframe)
            df_htf = exchange.fetch_recent_ohlcv(symbol, higher_tf, limit=200)
            if not df_htf.empty:
                st_dir = compute_supertrend(
                    df_htf,
                    period=int(supertrend_cfg.get('period', 10)),
                    multiplier=float(supertrend_cfg.get('multiplier', 3.0))
                )
                logger.info(f"{higher_tf} Supertrend: {st_dir}")
            else:
                st_dir = None
                logger.warning(f"Keine {higher_tf} Daten fuer Supertrend.")
        except Exception as e:
            logger.error(f"Supertrend HTF error: {e}", exc_info=True)
            st_dir = None
    else:
        st_dir = None

    # FUSION
    weights = None
    if learner_cfg.get('adaptive_weights', False):
        try:
            weights = load_signal_weights()
        except Exception as e:
            logger.warning(f"load_signal_weights failed: {e}")

    fusion = compute_fusion_score(df, settings, weights=weights)
    logger.info(
        f"FUSION Score: {fusion['score']}/5 | "
        f"Direction: {fusion['direction']} | Mode: {fusion['mode']} | "
        f"Weighted: {fusion.get('weighted_score', fusion['score']):.2f}"
    )

    if fusion['mode'] == 'SKIP':
        logger.info("Score zu niedrig — ueberspringe.")
        return

    # Apply supertrend filter
    if st_dir is not None and fusion['direction'] != 'none':
        if st_dir != fusion['direction']:
            logger.info(
                f"Supertrend {st_dir} != Fusion {fusion['direction']} — kein Trade."
            )
            return

    # COMPOUNDER: Positionsgroesse
    usdt_amount = get_position_size(state, fusion['mode'], settings)
    if usdt_amount < 5.0:
        logger.warning(f"Kapital {usdt_amount:.2f} USDT < 5 USDT Minimum. Ueberspringe.")
        return

    # RL Gate
    now_hour = datetime.now(timezone.utc).hour
    atr_series = (df['high'] - df['low']) / df['close']
    atr_pct = float(atr_series.iloc[-1])
    vol_bucket = _compute_volatility_bucket(df, atr_pct)
    cycle_phase = state.get('trade_number', 0) + 1

    rl_state_dict = {
        'hour':             now_hour,
        'fusion_score':     fusion['score'],
        'volatility_bucket': vol_bucket,
        'cycle_phase':      cycle_phase,
        'direction':        fusion['direction'],
    }

    if learner_cfg.get('rl_gate', False):
        try:
            threshold = float(learner_cfg.get('rl_block_threshold', 0.15))
            ok, reason = rl_should_trade(rl_state_dict, threshold=threshold)
            logger.info(f"RL Gate: {ok} | {reason}")
            if not ok:
                logger.info(f"RL Gate blockiert Trade: {reason}")
                return
        except Exception as e:
            logger.warning(f"rl_should_trade failed: {e}")

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

        leverage = settings['leverage']
        contracts = usdt_amount * leverage / entry_price if entry_price > 0 else 0

        state['active_position'] = {
            'direction':    fusion['direction'],
            'entry_price':  entry_price,
            'sl_price':     sl_p,
            'tp_price':     tp_p,
            'usdt_amount':  usdt_amount,
            'leverage':     leverage,
            'fusion_score': fusion['score'],
            'signals':      fusion['signals'],
            'contracts':    contracts,
            'partial_closed': False,
            'hour_of_entry':  now_hour,
            'cycle_phase':    cycle_phase,
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
