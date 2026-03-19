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
from apexbot.modules.radar import detect_attractor, compute_supertrend, get_higher_timeframe
from apexbot.modules.fusion import compute_edge
from apexbot.modules.compounder import (
    load_state, save_state, get_position_size,
    record_trade_result, compute_optimal_exit_trade
)
from apexbot.modules.learner import record_trade_signals, log_rl_decision


# ── Logging ─────────────────────────────────────────────────────────────────

def build_full_config(symbol: str, timeframe: str, minimal: dict) -> dict:
    """
    Baut vollstaendige settings aus minimaler settings.json + Optimizer-Config.
    Fallback: sinnvolle Defaults (Best-Profit / Moon-Mode).
    """
    full = {
        'symbol':    symbol,
        'timeframe': timeframe,
        'leverage':  minimal.get('leverage', 20),
        'margin_mode': minimal.get('margin_mode', 'isolated'),
        'cycle': {
            'start_capital_usdt':     minimal.get('start_capital_usdt', 50.0),
            'max_trades_per_cycle':   minimal.get('max_trades_per_cycle', 4),
            'cycle_target_multiplier': 16.0,
        },
        # v2 defaults (overridden by optimizer config if available)
        'attractor': {
            'hurst_trend_min': 0.55, 'adx_trend_min': 25,
            'hurst_range_max': 0.45, 'adx_range_max': 20,
            'entropy_chaos_min': 0.70,
        },
        'edge': {
            'threshold': 0.30, 'min_rr': 1.50, 'atr_sl_mult': 1.50,
            'base_p_win': 0.47, 'volume_surge_multiplier': 1.50,
            'rsi_momentum_min': 50, 'rsi_momentum_max': 75, 'body_ratio_min': 0.50,
        },
        'risk':  {'max_drawdown_pct': 100.0},
        'kelly': {'enabled': False, 'fraction': 1.0},
        'supertrend': {'enabled': False, 'period': 10, 'multiplier': 3.0},
        'killswitch': {'enabled': False, 'notify_telegram': minimal.get('notify_telegram', True)},
    }

    # Optimizer-Config einlesen falls vorhanden
    safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cfg_path = Path(PROJECT_ROOT) / 'artifacts' / 'configs' / f'config_{safe}.json'
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            params = cfg.get('params', {})
            if params.get('attractor'):
                full['attractor'].update(params['attractor'])
            if params.get('edge'):
                full['edge'].update(params['edge'])
            if params.get('risk'):
                full['risk'].update(params['risk'])
            if params.get('kelly'):
                full['kelly'].update(params['kelly'])
            if params.get('leverage'):
                full['leverage'] = params['leverage']
            if params.get('cycle', {}).get('cycle_target_multiplier'):
                full['cycle']['cycle_target_multiplier'] = params['cycle']['cycle_target_multiplier']
        except Exception:
            pass

    return full


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

    # OHLCV laden
    df = exchange.fetch_recent_ohlcv(symbol, timeframe, limit=200)
    if df.empty:
        logger.warning("Keine OHLCV-Daten. Ueberspringe.")
        return

    # ── ATTRACTOR filter ─────────────────────────────────────────────────
    attractor = detect_attractor(df, settings)
    logger.info(f"ATTRACTOR: {attractor}")
    if attractor == 'CHAOS':
        logger.info("Attractor CHAOS — kein Trade.")
        return

    # ── EDGE check ───────────────────────────────────────────────────────
    edge_result = compute_edge(df, settings)
    logger.info(
        f"EDGE: {edge_result['edge']:.3f} | P(win): {edge_result['p_win']:.2f} | "
        f"RR: {edge_result['rr']:.2f} | Dir: {edge_result['direction']} | Mode: {edge_result['mode']}"
    )
    if edge_result['mode'] == 'SKIP' or edge_result['direction'] == 'none':
        logger.info("Edge zu gering — ueberspringe.")
        return

    direction = edge_result['direction']

    # Supertrend higher-TF confirmation (optional)
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
                if st_dir != direction:
                    logger.info(f"Supertrend {st_dir} != Edge {direction} — kein Trade.")
                    return
        except Exception as e:
            logger.warning(f"Supertrend HTF error: {e}")

    # ── Positionsgroesse ─────────────────────────────────────────────────
    usdt_amount = get_position_size(state, 'FULL_SEND', settings)
    if usdt_amount < 5.0:
        logger.warning(f"Kapital {usdt_amount:.2f} USDT < 5 USDT Minimum. Ueberspringe.")
        return

    kelly_cfg = settings.get('kelly', {})
    if kelly_cfg.get('enabled', False):
        capital    = state.get('current_capital_usdt', settings['cycle']['start_capital_usdt'])
        frac       = kelly_cfg.get('fraction', 1.0)
        p, rr      = edge_result['p_win'], edge_result['rr']
        f_star     = (p * rr - (1 - p)) / rr if rr > 0 else frac
        kelly_scale = min(frac, max(0.05, f_star))
        usdt_amount = max(5.0, capital * kelly_scale)
        logger.info(f"Kelly: {kelly_scale:.1%} × {capital:.2f} = {usdt_amount:.2f} USDT")

    now_hour    = datetime.now(timezone.utc).hour
    cycle_phase = state.get('trade_number', 0) + 1

    # ── TRADE ────────────────────────────────────────────────────────────
    success = execute_apex_trade(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        usdt_amount=usdt_amount,
        settings=settings,
        telegram_config=telegram_config
    )

    if success:
        df_entry    = exchange.fetch_recent_ohlcv(symbol, '1m', limit=3)
        entry_price = float(df_entry['close'].iloc[-1]) if not df_entry.empty else 0

        # ATR-based SL + liquidity zone TP
        atr_sl = edge_result['atr_sl']
        if direction == 'long':
            sl_p = entry_price - atr_sl
            tp_p = edge_result['tp_price']
        else:
            sl_p = entry_price + atr_sl
            tp_p = edge_result['tp_price']

        leverage  = settings['leverage']
        contracts = usdt_amount * leverage / entry_price if entry_price > 0 else 0

        state['active_position'] = {
            'direction':      direction,
            'entry_price':    entry_price,
            'sl_price':       sl_p,
            'tp_price':       tp_p,
            'usdt_amount':    usdt_amount,
            'leverage':       leverage,
            'contracts':      contracts,
            'edge':           edge_result['edge'],
            'p_win':          edge_result['p_win'],
            'rr':             edge_result['rr'],
            'attractor':      attractor,
            'partial_closed': False,
            'hour_of_entry':  now_hour,
            'cycle_phase':    cycle_phase,
            'timestamp':      datetime.now(timezone.utc).isoformat(),
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
    parser.add_argument('--symbol',    default=None, help='Symbol Override (Turnier)')
    parser.add_argument('--timeframe', default=None, help='Timeframe Override (Turnier)')
    args = parser.parse_args()

    logger = setup_logging()

    try:
        with open(os.path.join(PROJECT_ROOT, 'settings.json')) as f:
            minimal = json.load(f)
        with open(os.path.join(PROJECT_ROOT, 'secret.json')) as f:
            secrets = json.load(f)
    except FileNotFoundError as e:
        logger.critical(f"Datei nicht gefunden: {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.critical(f"JSON-Fehler: {e}")
        sys.exit(1)

    symbol    = args.symbol    or minimal.get('symbol', 'SOL/USDT:USDT')
    timeframe = args.timeframe or minimal.get('timeframe', '1h')
    settings  = build_full_config(symbol, timeframe, minimal)

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
