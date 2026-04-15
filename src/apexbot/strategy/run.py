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

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from apexbot.utils.exchange import Exchange
from apexbot.utils.telegram import send_message
from apexbot.utils.trade_manager import execute_apex_trade, check_position_closed
from apexbot.modules.radar import detect_attractor, compute_supertrend, get_higher_timeframe
from apexbot.modules.fusion import compute_edge
from apexbot.modules.compounder import (
    load_state, save_state, get_position_size,
    record_trade_result, compute_optimal_exit_trade,
)
from apexbot.modules.learner import record_trade_signals, log_rl_decision


# ── Swingtrading Strategy (signal detection helper) ───────────────────────────

class SwingStrategy:
    """
    Lightweight signal helper used as a secondary confirmation layer.
    Primary trading decisions come from RADAR (attractor) + FUSION (edge engine).
    """

    def __init__(self, config: dict):
        self.config = config

    def detect_signal(self, df: pd.DataFrame) -> dict:
        """
        Consensus signal from EMA crossover, RSI, and candlestick pattern.
        Requires ≥ 2 of 3 votes in the same direction.
        """
        cfg = self.config
        min_bars = max(cfg['ema_slow'], cfg['rsi_period'], cfg['atr_period']) + 2
        if len(df) < min_bars:
            return {'signal': None, 'reason': 'too_few_bars'}

        close = df['close']
        ema_fast = close.ewm(span=cfg['ema_fast'], adjust=False).mean()
        ema_slow = close.ewm(span=cfg['ema_slow'], adjust=False).mean()
        rsi      = self._compute_rsi(close, cfg['rsi_period'])
        atr      = self._compute_atr(df, cfg['atr_period'])

        # Trend vote
        if ema_fast.iloc[-2] < ema_slow.iloc[-2] and ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            trend = 'long'
        elif ema_fast.iloc[-2] > ema_slow.iloc[-2] and ema_fast.iloc[-1] < ema_slow.iloc[-1]:
            trend = 'short'
        else:
            trend = None

        # Momentum vote
        if rsi > cfg['rsi_overbought']:
            momentum = 'short'
        elif rsi < cfg['rsi_oversold']:
            momentum = 'long'
        else:
            momentum = None

        # Candlestick vote (last closed candle)
        candle = df.iloc[-2]
        body   = abs(candle['close'] - candle['open'])
        rng    = candle['high'] - candle['low']
        upper_wick = candle['high'] - max(candle['close'], candle['open'])
        lower_wick = min(candle['close'], candle['open']) - candle['low']
        body_ratio  = body / rng        if rng > 0 else 0
        uw_ratio    = upper_wick / rng  if rng > 0 else 0
        lw_ratio    = lower_wick / rng  if rng > 0 else 0

        candle_signal = None
        if lw_ratio > 0.5 and body_ratio < 0.3:
            candle_signal = 'long'   # Hammer
        elif uw_ratio > 0.5 and body_ratio < 0.3:
            candle_signal = 'short'  # Shooting Star
        elif candle['close'] > candle['open'] and body_ratio > 0.6:
            candle_signal = 'long'   # Bullish Engulfing
        elif candle['close'] < candle['open'] and body_ratio > 0.6:
            candle_signal = 'short'  # Bearish Engulfing

        # ATR volatility gate
        if float(atr.iloc[-1]) < 0.005 * float(close.iloc[-1]):
            return {'signal': None, 'reason': 'low_volatility'}

        votes = [trend, momentum, candle_signal]
        if votes.count('long') >= 2:
            return {'signal': 'long',  'reason': f'consensus {votes}'}
        if votes.count('short') >= 2:
            return {'signal': 'short', 'reason': f'consensus {votes}'}
        return {'signal': None, 'reason': f'no_consensus {votes}'}

    def get_entry(self, df: pd.DataFrame, signal: str) -> dict:
        """
        Entry + ATR-based SL + RR-scaled TP.
        SL anchored to swing low/high for structural validity.
        """
        close = df['close']
        atr   = self._compute_atr(df, self.config['atr_period'])
        entry = float(close.iloc[-2])
        atr_v = float(atr.iloc[-2])

        if signal == 'long':
            swing_low  = float(df['low'].iloc[-self.config['ema_slow']:].min())
            stop_loss  = min(entry - atr_v, swing_low)
            take_profit = entry + (entry - stop_loss) * self.config['reward_risk']
        elif signal == 'short':
            swing_high = float(df['high'].iloc[-self.config['ema_slow']:].max())
            stop_loss  = max(entry + atr_v, swing_high)
            take_profit = entry - (stop_loss - entry) * self.config['reward_risk']
        else:
            return {'entry': None, 'stop_loss': None, 'take_profit': None}

        return {'entry': entry, 'stop_loss': stop_loss, 'take_profit': take_profit}

    def should_exit(self, df: pd.DataFrame, position: dict) -> bool:
        """Exit when an opposite signal appears."""
        info = self.detect_signal(df)
        if position['side'] == 'long'  and info['signal'] == 'short':
            return True
        if position['side'] == 'short' and info['signal'] == 'long':
            return True
        return False

    def backtest(self, df: pd.DataFrame) -> dict:
        """Simple candle-by-candle backtest using detect_signal / get_entry."""
        trades   = []
        position = None
        wins     = 0

        for i in range(len(df)):
            window     = df.iloc[:i + 1]
            signal_info = self.detect_signal(window)

            if position is None and signal_info['signal']:
                entry = self.get_entry(window, signal_info['signal'])
                if entry['entry'] is not None:
                    position = {
                        'side':        signal_info['signal'],
                        'entry_price': entry['entry'],
                        'stop_loss':   entry['stop_loss'],
                        'take_profit': entry['take_profit'],
                        'entry_index': i,
                    }
            elif position is not None:
                price = float(df['close'].iloc[i])
                if position['side'] == 'long':
                    if price <= position['stop_loss']:
                        trades.append({'result': 'loss', 'entry': position['entry_price'], 'exit': price, 'side': 'long'})
                        position = None
                    elif price >= position['take_profit']:
                        trades.append({'result': 'win', 'entry': position['entry_price'], 'exit': price, 'side': 'long'})
                        wins += 1
                        position = None
                else:
                    if price >= position['stop_loss']:
                        trades.append({'result': 'loss', 'entry': position['entry_price'], 'exit': price, 'side': 'short'})
                        position = None
                    elif price <= position['take_profit']:
                        trades.append({'result': 'win', 'entry': position['entry_price'], 'exit': price, 'side': 'short'})
                        wins += 1
                        position = None

        total   = len(trades)
        winrate = wins / total if total > 0 else 0.0
        return {'trades': trades, 'total_trades': total, 'winrate': winrate}

    @staticmethod
    def _compute_rsi(series: pd.Series, period: int) -> float:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(window=period).mean()
        loss  = (-delta.clip(upper=0)).rolling(window=period).mean()
        rs    = gain / loss.replace(0, 1e-10)
        return float((100 - 100 / (1 + rs)).iloc[-1])

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
        high, low, close = df['high'], df['low'], df['close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def default_config() -> dict:
        return {
            'ema_fast':       21,
            'ema_slow':       50,
            'rsi_period':     14,
            'rsi_overbought': 70,
            'rsi_oversold':   30,
            'atr_period':     14,
            'risk_per_trade': 0.01,
            'reward_risk':    2.0,
        }


# ── Config Builder ────────────────────────────────────────────────────────────

def build_full_config(symbol: str, timeframe: str, minimal: dict) -> dict:
    """
    Merges minimal settings.json + optimizer-generated pair config + safe defaults.
    """
    full = {
        'symbol':      symbol,
        'timeframe':   timeframe,
        'leverage':    minimal.get('leverage', 20),
        'margin_mode': minimal.get('margin_mode', 'isolated'),
        'cycle': {
            'start_capital_usdt':      minimal.get('start_capital_usdt', 50.0),
            'max_trades_per_cycle':    minimal.get('max_trades_per_cycle', 4),
            'cycle_target_multiplier': 16.0,
        },
        'attractor': {
            'hurst_trend_min':  0.55,
            'adx_trend_min':    25,
            'hurst_range_max':  0.45,
            'adx_range_max':    20,
            'entropy_chaos_min': 0.70,
        },
        'edge': {
            'threshold':               0.30,
            'min_rr':                  1.50,
            'atr_sl_mult':             1.50,
            'base_p_win':              0.47,
            'volume_surge_multiplier': 1.50,
            'rsi_momentum_min':        50,
            'rsi_momentum_max':        75,
            'body_ratio_min':          0.50,
        },
        'risk':       {'max_drawdown_pct': 100.0},
        'kelly':      {'enabled': False, 'fraction': 1.0},
        'supertrend': {'enabled': False, 'period': 10, 'multiplier': 3.0},
        'killswitch': {
            'enabled':          False,
            'notify_telegram':  minimal.get('notify_telegram', True),
        },
    }

    # Merge optimizer-generated pair config if available
    safe     = f"{symbol.replace('/', '').replace(':', '')}_{timeframe}"
    cfg_path = Path(PROJECT_ROOT) / 'artifacts' / 'configs' / f'config_{safe}.json'
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            params = cfg.get('params', {})
            for key in ('attractor', 'edge', 'risk', 'kelly', 'supertrend'):
                if params.get(key):
                    full[key].update(params[key])
            if params.get('leverage'):
                full['leverage'] = params['leverage']
            if params.get('cycle', {}).get('cycle_target_multiplier'):
                full['cycle']['cycle_target_multiplier'] = params['cycle']['cycle_target_multiplier']
        except Exception:
            pass

    return full


# ── Logging ───────────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_volatility_bucket(df: pd.DataFrame, atr_pct: float) -> int:
    if atr_pct < 0.005:  return 0
    if atr_pct < 0.015:  return 1
    return 2


def _init_state(settings: dict) -> dict:
    return {
        'cycle_number':         1,
        'trade_number':         0,
        'current_capital_usdt': settings['cycle']['start_capital_usdt'],
        'start_capital_usdt':   settings['cycle']['start_capital_usdt'],
        'peak_capital_usdt':    settings['cycle']['start_capital_usdt'],
        'status':               'WAITING',
        'active_position':      None,
        'symbol':               settings['symbol'],
        'timeframe':            settings['timeframe'],
    }


# ── Main Run ──────────────────────────────────────────────────────────────────

def run(mode: str, settings: dict, account: dict, telegram_config: dict,
        logger: logging.Logger):
    """
    Core trading loop.

    signal mode:
      1. Connect exchange
      2. Load / init state
      3. Skip if already in a trade
      4. Fetch OHLCV data
      5. RADAR: classify attractor → skip on CHAOS
      6. FUSION: compute edge → skip on SKIP
      7. Position sizing (Kelly optional)
      8. Place trade with explicit SL/TP from fusion
      9. Persist state

    check mode:
      1. Connect exchange
      2. Load state
      3. If IN_TRADE: check if position closed → update state
    """
    symbol    = settings['symbol']
    timeframe = settings['timeframe']
    leverage  = settings.get('leverage', 20)
    notify    = settings.get('killswitch', {}).get('notify_telegram', True)

    # ── Exchange connection ───────────────────────────────────────────────────
    ex = Exchange(account)

    # ── State management ─────────────────────────────────────────────────────
    try:
        state = load_state()
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        logger.warning("Kein gültiger State gefunden — initialisiere neu.")
        state = _init_state(settings)
        state_dir = Path(PROJECT_ROOT) / 'artifacts' / 'state'
        state_dir.mkdir(parents=True, exist_ok=True)
        save_state(state)

    # ═══════════════════════════════════════════════════════════════════════════
    # CHECK MODE — verify open position
    # ═══════════════════════════════════════════════════════════════════════════
    if mode == 'check':
        if state.get('status') != 'IN_TRADE':
            logger.info("Status: WAITING — kein offener Trade zu prüfen.")
            return

        is_closed, estimated_pnl = check_position_closed(
            ex, symbol, telegram_config, state, logger
        )

        if not is_closed:
            pos = state.get('active_position') or {}
            logger.info(
                f"Trade noch offen | dir={pos.get('direction','?')} "
                f"sl={pos.get('sl_price','?')} tp={pos.get('tp_price','?')}"
            )
            return

        # Position closed — update capital from real balance if possible
        try:
            real_balance = ex.fetch_balance_usdt()
            if real_balance > 1.0:
                state['current_capital_usdt'] = real_balance
                state['peak_capital_usdt'] = max(
                    state.get('peak_capital_usdt', 0), real_balance
                )
                logger.info(f"Echte Balance: {real_balance:.2f} USDT")
        except Exception as e:
            logger.warning(f"Balance-Abruf fehlgeschlagen: {e}")

        won = estimated_pnl > 0
        state = record_trade_result(state, won=won, pnl_usdt=estimated_pnl, config=settings)
        state['status']          = 'WAITING'
        state['active_position'] = None
        save_state(state)
        logger.info(
            f"Trade geschlossen: {'WIN' if won else 'LOSS'} | "
            f"PnL ~{estimated_pnl:+.2f} USDT | "
            f"Capital: {state['current_capital_usdt']:.2f} USDT"
        )
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # SIGNAL MODE — scan for new entry
    # ═══════════════════════════════════════════════════════════════════════════
    if mode != 'signal':
        logger.error(f"Unbekannter Modus: {mode}")
        return

    if state.get('status') == 'IN_TRADE':
        logger.info("Bereits in Trade — kein neues Signal gesucht.")
        return

    # ── Fetch OHLCV ──────────────────────────────────────────────────────────
    limit = 300   # 300 bars: enough for EMA200 + all indicators
    df = ex.fetch_recent_ohlcv(symbol, timeframe, limit=limit)
    if df is None or df.empty or len(df) < 60:
        logger.warning(f"Zu wenig Daten: {len(df) if df is not None else 0} Kerzen.")
        return

    logger.info(f"Analysiere {symbol} {timeframe} | {len(df)} Kerzen | "
                f"letzter Close: {df['close'].iloc[-1]:.4f}")

    # ── RADAR: Attractor Detection ────────────────────────────────────────────
    attractor = detect_attractor(df, settings)
    logger.info(f"Attractor: {attractor}")

    if attractor == 'CHAOS':
        logger.info("CHAOS erkannt → kein Trade.")
        return

    # Optional: Higher Timeframe Supertrend filter
    if settings.get('supertrend', {}).get('enabled', False):
        htf = get_higher_timeframe(timeframe)
        try:
            df_htf = ex.fetch_recent_ohlcv(symbol, htf, limit=150)
            if df_htf is not None and len(df_htf) >= 50:
                st_dir = compute_supertrend(
                    df_htf,
                    settings['supertrend']['period'],
                    settings['supertrend']['multiplier'],
                )
                logger.info(f"Supertrend ({htf}): {st_dir}")
        except Exception as e:
            logger.warning(f"Supertrend-Abruf fehlgeschlagen: {e}")

    # ── FUSION: Edge Engine ───────────────────────────────────────────────────
    edge_result = compute_edge(df, settings)
    logger.info(
        f"FUSION: {edge_result['mode']} | dir={edge_result['direction']} | "
        f"edge={edge_result['edge']} | rr={edge_result['rr']} | "
        f"reason={edge_result.get('reason','')}"
    )

    if edge_result['mode'] == 'SKIP' or edge_result['direction'] == 'none':
        try:
            log_rl_decision(state, edge_result, action='skip')
        except Exception:
            pass
        return

    direction = edge_result['direction']
    sl_price  = float(edge_result['sl_price'])
    tp_price  = float(edge_result['tp_price'])
    atr_sl    = float(edge_result['atr_sl'])
    entry_est = float(df['close'].iloc[-1])

    # ── Position Sizing ───────────────────────────────────────────────────────
    kelly_cfg  = settings.get('kelly', {})
    use_kelly  = kelly_cfg.get('enabled', False)
    kelly_frac = float(kelly_cfg.get('fraction', 1.0))
    capital    = float(state['current_capital_usdt'])

    if use_kelly and edge_result['rr'] > 0:
        p   = edge_result['p_win']
        rr  = edge_result['rr']
        f   = (p * rr - (1 - p)) / rr
        f   = max(0.05, min(kelly_frac, f))
        usdt_amount = capital * f
    else:
        usdt_amount = capital * kelly_frac

    logger.info(
        f"SIGNAL: {direction.upper()} | Kapital: {usdt_amount:.2f} USDT | "
        f"SL: {sl_price:.4f} | TP: {tp_price:.4f} | "
        f"Cycle: {state.get('cycle_number',1)} Trade: {state.get('trade_number',0)+1}"
    )

    # ── Execute ───────────────────────────────────────────────────────────────
    success = execute_apex_trade(
        ex, symbol, timeframe, direction, usdt_amount,
        settings, telegram_config,
        sl_price=sl_price, tp_price=tp_price,
    )

    if success:
        # Learner signal logging (non-critical)
        try:
            atr_pct    = atr_sl / entry_est if entry_est > 0 else 0
            vol_bucket = _compute_volatility_bucket(df, atr_pct)
            record_trade_signals(state, edge_result, vol_bucket, direction)
        except Exception:
            pass

        state['status'] = 'IN_TRADE'
        state['active_position'] = {
            'direction':   direction,
            'entry_price': entry_est,
            'sl_price':    sl_price,
            'tp_price':    tp_price,
            'usdt_amount': usdt_amount,
            'leverage':    leverage,
            'edge':        edge_result['edge'],
            'attractor':   attractor,
            'entry_time':  datetime.now(timezone.utc).isoformat(),
        }
        save_state(state)
        logger.info("Trade platziert | Status → IN_TRADE")
    else:
        logger.error("Trade-Ausführung fehlgeschlagen.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='apexbot Strategy Runner')
    parser.add_argument('--mode',      required=True, choices=['signal', 'check'],
                        help='signal=Signal pruefen | check=Position pruefen')
    parser.add_argument('--symbol',    default=None, help='Symbol Override')
    parser.add_argument('--timeframe', default=None, help='Timeframe Override')
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

    symbol    = args.symbol    or minimal.get('symbol',    'SOL/USDT:USDT')
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
