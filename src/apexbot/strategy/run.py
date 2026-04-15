import pandas as pd

# ── Swingtrading-Strategie Grundstruktur ───────────────────────────────────
class SwingStrategy:
        def backtest(self, df: pd.DataFrame) -> dict:
            """
            Simuliert Trades auf Basis historischer Daten und berechnet Kennzahlen.
            Args:
                df: OHLCV DataFrame mit Spalten ['open', 'high', 'low', 'close', 'volume']
            Returns:
                dict mit Ergebnissen: Gesamtgewinn, Trefferquote, Anzahl Trades, Trade-Liste
            """
            trades = []
            position = None
            wins = 0
            for i in range(len(df)):
                window = df.iloc[:i+1]
                signal_info = self.detect_signal(window)
                if position is None and signal_info['signal']:
                    entry = self.get_entry(window, signal_info['signal'])
                    if entry['entry'] is not None:
                        position = {
                            'side': signal_info['signal'],
                            'entry_price': entry['entry'],
                            'stop_loss': entry['stop_loss'],
                            'take_profit': entry['take_profit'],
                            'entry_index': i
                        }
                elif position is not None:
                    price = df['close'].iloc[i]
                    if position['side'] == 'long':
                        if price <= position['stop_loss']:
                            trades.append({'result': 'loss', 'entry': position['entry_price'], 'exit': price, 'side': 'long'})
                            position = None
                        elif price >= position['take_profit']:
                            trades.append({'result': 'win', 'entry': position['entry_price'], 'exit': price, 'side': 'long'})
                            wins += 1
                            position = None
                    elif position['side'] == 'short':
                        if price >= position['stop_loss']:
                            trades.append({'result': 'loss', 'entry': position['entry_price'], 'exit': price, 'side': 'short'})
                            position = None
                        elif price <= position['take_profit']:
                            trades.append({'result': 'win', 'entry': position['entry_price'], 'exit': price, 'side': 'short'})
                            wins += 1
                            position = None
            total = len(trades)
            winrate = wins / total if total > 0 else 0.0
            return {
                'trades': trades,
                'total_trades': total,
                'winrate': winrate,
            }
    """
    Professionelle Swingtrading-Strategie nach allen Regeln der Kunst.
    Modular, konfigurierbar und für Backtest/Livebetrieb geeignet.
    """
    def __init__(self, config: dict):
        self.config = config


    def detect_signal(self, df: pd.DataFrame) -> dict:
        """
        Profi-Swingtrading-Signalerkennung:
        - EMA-Crossover (Trend)
        - RSI (Momentum)
        - Candlestick-Pattern (Reversal/Continuation)
        - ATR-Filter (Volatilität)
        """
        if len(df) < max(self.config['ema_slow'], self.config['rsi_period'], self.config['atr_period']) + 2:
            return {'signal': None, 'reason': 'zu wenig Daten'}

        close = df['close']
        ema_fast = close.ewm(span=self.config['ema_fast'], adjust=False).mean()
        ema_slow = close.ewm(span=self.config['ema_slow'], adjust=False).mean()
        rsi = self._compute_rsi(close, self.config['rsi_period'])
        atr = self._compute_atr(df, self.config['atr_period'])

        # EMA-Crossover
        if ema_fast.iloc[-2] < ema_slow.iloc[-2] and ema_fast.iloc[-1] > ema_slow.iloc[-1]:
            trend = 'long'
        elif ema_fast.iloc[-2] > ema_slow.iloc[-2] and ema_fast.iloc[-1] < ema_slow.iloc[-1]:
            trend = 'short'
        else:
            trend = None

        # RSI-Filter
        if rsi > self.config['rsi_overbought']:
            momentum = 'short'
        elif rsi < self.config['rsi_oversold']:
            momentum = 'long'
        else:
            momentum = None

        # Candlestick-Pattern (letzte Kerze)
        candle = df.iloc[-2]
        body = abs(candle['close'] - candle['open'])
        rng = candle['high'] - candle['low']
        upper_wick = candle['high'] - max(candle['close'], candle['open'])
        lower_wick = min(candle['close'], candle['open']) - candle['low']
        body_ratio = body / rng if rng > 0 else 0
        upper_wick_ratio = upper_wick / rng if rng > 0 else 0
        lower_wick_ratio = lower_wick / rng if rng > 0 else 0

        candle_signal = None
        # Hammer
        if lower_wick_ratio > 0.5 and body_ratio < 0.3:
            candle_signal = 'long'
        # Shooting Star
        elif upper_wick_ratio > 0.5 and body_ratio < 0.3:
            candle_signal = 'short'
        # Bullish Engulfing
        elif candle['close'] > candle['open'] and body_ratio > 0.6:
            candle_signal = 'long'
        # Bearish Engulfing
        elif candle['close'] < candle['open'] and body_ratio > 0.6:
            candle_signal = 'short'

        # ATR-Filter: Nur handeln bei ausreichender Volatilität
        atr_val = atr.iloc[-1]
        if atr_val < 0.005 * close.iloc[-1]:
            return {'signal': None, 'reason': 'zu wenig Volatilität'}

        # Konsens-Logik: Mindestens 2 von 3 müssen übereinstimmen
        votes = [trend, momentum, candle_signal]
        long_votes = votes.count('long')
        short_votes = votes.count('short')
        if long_votes >= 2:
            return {'signal': 'long', 'reason': f'long ({votes})'}
        elif short_votes >= 2:
            return {'signal': 'short', 'reason': f'short ({votes})'}
        else:
            return {'signal': None, 'reason': f'kein Konsens ({votes})'}

    def get_entry(self, df: pd.DataFrame, signal: str) -> dict:
        """
        Entry, Stop-Loss und Take-Profit nach Profi-Swingtrading-Logik.
        - Entry: Close der letzten Kerze
        - SL: ATR-basiert unter/über Swing-Low/High
        - TP: RR-Multiplikator
        """
        close = df['close']
        atr = self._compute_atr(df, self.config['atr_period'])
        entry = close.iloc[-2]
        atr_val = atr.iloc[-2]

        if signal == 'long':
            # Swing-Low der letzten N Kerzen
            swing_low = df['low'].iloc[-self.config['ema_slow']:].min()
            stop_loss = min(entry - atr_val, swing_low)
            take_profit = entry + (entry - stop_loss) * self.config['reward_risk']
        elif signal == 'short':
            swing_high = df['high'].iloc[-self.config['ema_slow']:].max()
            stop_loss = max(entry + atr_val, swing_high)
            take_profit = entry - (stop_loss - entry) * self.config['reward_risk']
        else:
            return {'entry': None, 'stop_loss': None, 'take_profit': None}

        return {'entry': entry, 'stop_loss': stop_loss, 'take_profit': take_profit}

    def should_exit(self, df: pd.DataFrame, position: dict) -> bool:
        """
        Exit-Regel: Schließe Position, wenn Gegensignal oder TP/SL erreicht.
        """
        signal_info = self.detect_signal(df)
        if position['side'] == 'long' and signal_info['signal'] == 'short':
            return True
        if position['side'] == 'short' and signal_info['signal'] == 'long':
            return True
        return False

    @staticmethod
    def _compute_rsi(series: pd.Series, period: int) -> float:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = -delta.clip(upper=0).rolling(window=period).mean()
        rs = gain / (loss.replace(0, 1e-10))
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def get_entry(self, df: pd.DataFrame, signal: str) -> dict:
        """
        Bestimmt Entry-Preis, Stop-Loss und Take-Profit für das Signal.
        Rückgabe: dict mit 'entry', 'stop_loss', 'take_profit'
        """
        # TODO: Entry/SL/TP-Logik implementieren
        return {'entry': None, 'stop_loss': None, 'take_profit': None}

    def should_exit(self, df: pd.DataFrame, position: dict) -> bool:
        """
        Prüft, ob ein aktiver Trade geschlossen werden soll.
        """
        # TODO: Exit-Logik implementieren
        return False

    @staticmethod
    def default_config() -> dict:
        """Gibt Default-Parameter für die Strategie zurück."""
        return {
            'ema_fast': 21,
            'ema_slow': 50,
            'rsi_period': 14,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'atr_period': 14,
            'risk_per_trade': 0.01,
            'reward_risk': 2.0,
        }

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
    # Neue Swingtrading-Strategie Grundstruktur
    logger.info('Swingtrading-Strategie Grundstruktur aktiv.')
    strategy = SwingStrategy(settings.get('strategy', SwingStrategy.default_config()))
    # Beispiel: Daten laden, Signal prüfen, Entry bestimmen
    # df = ...
    # signal_info = strategy.detect_signal(df)
    # if signal_info['signal']:
    #     entry = strategy.get_entry(df, signal_info['signal'])
    #     ...


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
