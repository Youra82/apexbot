# src/apexbot/utils/trade_manager.py
"""
Trade Manager fuer apexbot.
Positionsgroesse = aktuelles Cycle-Kapital (FULL_SEND) oder 50% (HALF_SEND).
SL/TP prozentbasiert aus settings.json.
"""

import logging
import time

from apexbot.utils.telegram import send_message

MIN_NOTIONAL_USDT = 5.0

logger = logging.getLogger(__name__)


def execute_apex_trade(exchange, symbol: str, timeframe: str,
                       direction: str, usdt_amount: float,
                       settings: dict, telegram_config: dict) -> bool:
    """
    Platziert Entry + SL + TP fuer apexbot.
    Returns True wenn Trade erfolgreich platziert.
    """
    leverage    = int(settings.get('leverage', 20))
    margin_mode = settings.get('margin_mode', 'isolated')
    sl_pct      = float(settings['risk']['stop_loss_pct'])
    tp_mult     = float(settings['risk']['take_profit_multiplier'])

    if usdt_amount < MIN_NOTIONAL_USDT:
        logger.warning(f"Betrag {usdt_amount:.2f} USDT < {MIN_NOTIONAL_USDT} Minimum. Kein Trade.")
        return False

    exchange.set_margin_mode(symbol, margin_mode)
    exchange.set_leverage(symbol, leverage, margin_mode)

    min_amount   = exchange.fetch_min_amount_tradable(symbol)
    entry_side   = 'buy' if direction == 'long' else 'sell'

    # Aktuellem Preis holen via fetch_recent_ohlcv (letzter Close)
    df = exchange.fetch_recent_ohlcv(symbol, '1m', limit=3)
    if df.empty:
        logger.error("Kein Kurs abrufbar. Kein Trade.")
        return False
    current_price = float(df['close'].iloc[-1])

    # Positionsgroesse: USDT-Betrag / Preis * Hebel
    notional  = usdt_amount * leverage
    contracts = notional / current_price
    contracts = max(contracts, min_amount)
    contracts = float(exchange.amount_to_precision(symbol, contracts))

    if contracts * current_price < MIN_NOTIONAL_USDT:
        logger.warning(f"Notional {contracts * current_price:.2f} USDT zu klein. Kein Trade.")
        return False

    # SL / TP berechnen
    sl_price_dist = current_price * (sl_pct / 100.0)
    tp_price_dist = sl_price_dist * tp_mult

    if direction == 'long':
        sl_price = current_price - sl_price_dist
        tp_price = current_price + tp_price_dist
    else:
        sl_price = current_price + sl_price_dist
        tp_price = current_price - tp_price_dist

    logger.info(
        f"APEX {direction.upper()} | {contracts:.4f} {symbol} | "
        f"Entry: {current_price:.4f} | SL: {sl_price:.4f} | TP: {tp_price:.4f}"
    )

    # Entry platzieren
    try:
        entry_order = exchange.place_market_order(symbol, entry_side, contracts, margin_mode=margin_mode)
    except Exception as e:
        logger.error(f"Entry fehlgeschlagen: {e}")
        return False

    entry_price = float(entry_order.get('average') or entry_order.get('price') or current_price)
    filled      = float(entry_order.get('filled') or entry_order.get('amount') or contracts)
    if entry_price <= 0:
        entry_price = current_price
    if filled <= 0:
        filled = contracts

    time.sleep(1.0)

    # SL platzieren
    sl_side = 'sell' if direction == 'long' else 'buy'
    try:
        exchange.place_trigger_market_order(symbol, sl_side, filled, sl_price, reduce=True)
        logger.info(f"SL platziert @ {sl_price:.4f}")
    except Exception as e:
        logger.error(f"SL fehlgeschlagen: {e}. Schliesse Position!")
        try:
            exchange.close_position(symbol)
        except Exception as ce:
            logger.critical(f"Konnte Position nicht schliessen: {ce}")
        return False

    # TP platzieren
    try:
        exchange.place_trigger_market_order(symbol, sl_side, filled, tp_price, reduce=True)
        logger.info(f"TP platziert @ {tp_price:.4f}")
    except Exception as e:
        logger.error(f"TP fehlgeschlagen: {e}")

    # Telegram
    sl_dist_pct = abs(entry_price - sl_price) / entry_price * 100
    tp_dist_pct = abs(tp_price - entry_price) / entry_price * 100
    rr = tp_dist_pct / sl_dist_pct if sl_dist_pct > 0 else 0
    emoji = "🟢" if direction == 'long' else "🔴"

    send_message(
        telegram_config.get('bot_token'),
        telegram_config.get('chat_id'),
        f"APEX TRADE: {symbol} ({timeframe})\n"
        f"{'─' * 32}\n"
        f"{emoji} {direction.upper()} | Kapital: {usdt_amount:.2f} USDT\n"
        f"Entry:  ${entry_price:.4f}\n"
        f"SL:     ${sl_price:.4f} (-{sl_dist_pct:.2f}%)\n"
        f"TP:     ${tp_price:.4f} (+{tp_dist_pct:.2f}%)\n"
        f"R:R:    1:{rr:.1f} | Hebel: {leverage}x"
    )

    return True


def check_position_closed(exchange, symbol: str, telegram_config: dict,
                           state: dict, logger: logging.Logger) -> tuple[bool, float]:
    """
    Prueft ob Position noch offen.
    Returns (is_closed, estimated_pnl)
    """
    positions = exchange.fetch_open_positions(symbol)

    if positions:
        pos     = positions[0]
        unr_pnl = float(pos.get('unrealizedPnl', 0.0))
        logger.info(f"Position noch offen | UnrPnL: {unr_pnl:.2f} USDT")
        return False, 0.0

    # Position geschlossen
    logger.info("Position geschlossen (TP oder SL getroffen).")

    try:
        exchange.cancel_all_orders_for_symbol(symbol)
    except Exception as e:
        logger.warning(f"Fehler beim Stornieren restlicher Orders: {e}")

    pos_info = state.get('active_position', {}) or {}
    entry_p  = pos_info.get('entry_price', '?')
    sl_p     = pos_info.get('sl_price', '?')
    tp_p     = pos_info.get('tp_price', '?')
    direction = pos_info.get('direction', '?')

    send_message(
        telegram_config.get('bot_token'),
        telegram_config.get('chat_id'),
        f"APEX TRADE GESCHLOSSEN\n"
        f"{'─' * 32}\n"
        f"{'🟢' if direction == 'long' else '🔴'} {direction.upper()} | {symbol}\n"
        f"Entry:  ${entry_p}\n"
        f"SL:     ${sl_p}\n"
        f"TP:     ${tp_p}\n"
        f"Warte auf naechstes Signal..."
    )

    # PnL schaetzen aus TP-Abstand (exakter Wert ueber Exchange-History nicht immer verfuegbar)
    try:
        if entry_p != '?' and tp_p != '?' and sl_p != '?':
            entry_f = float(entry_p)
            tp_f    = float(tp_p)
            sl_f    = float(sl_p)
            tp_dist = abs(tp_f - entry_f)
            sl_dist = abs(sl_f - entry_f)
            usdt_amt = pos_info.get('usdt_amount', 0)
            leverage = int(pos_info.get('leverage', 20))
            # Grobe Schaetzung — wird spaeter durch echten Balance-Check korrigiert
            pnl_win  = usdt_amt * leverage * (tp_dist / entry_f)
            pnl_loss = -(usdt_amt * leverage * (sl_dist / entry_f))
            return True, pnl_win  # Optimistisch; Compounder wird echte Balance nehmen
    except Exception:
        pass

    return True, 0.0
