# src/apexbot/utils/exchange.py
import ccxt
import pandas as pd
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class Exchange:
    def __init__(self, account_config):
        self.account = account_config
        self.exchange = ccxt.bitget({
            'apiKey':   self.account.get('apiKey'),
            'secret':   self.account.get('secret'),
            'password': self.account.get('password'),
            'options':  {'defaultType': 'swap'},
            'enableRateLimit': True,
        })
        try:
            self.markets = self.exchange.load_markets()
            logger.info("Maerkte erfolgreich geladen.")
        except Exception as e:
            logger.critical(f"Maerkte konnten nicht geladen werden: {e}")
            self.markets = {}

    def fetch_recent_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        if not self.markets:
            return pd.DataFrame()
        timeframe_ms = self.exchange.parse_timeframe(timeframe) * 1000
        since = self.exchange.milliseconds() - timeframe_ms * limit
        all_ohlcv = []

        while since < self.exchange.milliseconds():
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since, 200)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + timeframe_ms
                time.sleep(self.exchange.rateLimit / 1000)
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limit - warte 5s...")
                time.sleep(5)
            except Exception as e:
                logger.error(f"Fehler beim OHLCV-Abruf: {e}")
                break

        if not all_ohlcv:
            return pd.DataFrame()

        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        df = df[~df.index.duplicated(keep='last')]
        if len(df) > limit:
            df = df.iloc[-limit:]
        return df

    def fetch_balance_usdt(self) -> float:
        if not self.markets:
            return 0.0
        try:
            balance = self.exchange.fetch_balance(params={'type': 'swap'})
            usdt = balance.get('USDT', {})
            return float(usdt.get('free', usdt.get('total', 0.0)) or 0.0)
        except Exception as e:
            logger.error(f"fetch_balance_usdt Fehler: {e}")
            return 0.0

    def set_margin_mode(self, symbol: str, margin_mode: str):
        try:
            self.exchange.set_margin_mode(margin_mode, symbol)
        except Exception as e:
            logger.warning(f"set_margin_mode: {e}")

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'isolated'):
        try:
            self.exchange.set_leverage(leverage, symbol, params={'marginMode': margin_mode})
        except Exception as e:
            logger.warning(f"set_leverage: {e}")

    def fetch_min_amount_tradable(self, symbol: str) -> float:
        try:
            market = self.exchange.market(symbol)
            return float(market.get('limits', {}).get('amount', {}).get('min', 0.0) or 0.0)
        except Exception:
            return 0.0

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        try:
            return self.exchange.amount_to_precision(symbol, amount)
        except Exception:
            return str(round(amount, 4))

    def place_market_order(self, symbol: str, side: str, amount: float,
                           margin_mode: str = 'isolated') -> dict:
        return self.exchange.create_order(
            symbol, 'market', side, amount,
            params={'marginMode': margin_mode, 'reduceOnly': False},
        )

    def place_trigger_market_order(self, symbol: str, side: str, amount: float,
                                   trigger_price: float, reduce: bool = True):
        params = {
            'triggerPrice': trigger_price,
            'reduceOnly':   reduce,
            'marginMode':   'isolated',
        }
        self.exchange.create_order(symbol, 'market', side, amount, params=params)

    def place_trailing_stop(self, symbol: str, side: str, amount: float,
                            activation_price: float, callback_rate: float,
                            margin_mode: str = 'isolated'):
        params = {
            'activationPrice': activation_price,
            'callbackRate':    callback_rate,
            'reduceOnly':      True,
            'marginMode':      margin_mode,
        }
        self.exchange.create_order(symbol, 'market', side, amount, params=params)

    def close_position(self, symbol: str):
        positions = self.fetch_open_positions(symbol)
        for pos in positions:
            side   = 'sell' if pos.get('side') == 'long' else 'buy'
            amount = float(pos.get('contracts', 0))
            if amount > 0:
                self.exchange.create_order(
                    symbol, 'market', side, amount,
                    params={'reduceOnly': True},
                )

    def partial_close_position(self, symbol: str, fraction: float,
                                margin_mode: str = 'isolated') -> float:
        positions = self.fetch_open_positions(symbol)
        if not positions:
            return 0.0
        pos     = positions[0]
        side    = 'sell' if pos.get('side') == 'long' else 'buy'
        total   = float(pos.get('contracts', 0))
        to_close = total * fraction
        if to_close <= 0:
            return 0.0
        self.exchange.create_order(
            symbol, 'market', side, to_close,
            params={'reduceOnly': True, 'marginMode': margin_mode},
        )
        return to_close

    def fetch_open_positions(self, symbol: str) -> list:
        try:
            positions = self.exchange.fetch_positions([symbol])
            return [p for p in positions if abs(float(p.get('contracts') or 0)) > 0]
        except Exception as e:
            logger.error(f"fetch_open_positions Fehler: {e}")
            return []

    def cancel_all_orders_for_symbol(self, symbol: str):
        try:
            self.exchange.cancel_all_orders(symbol)
        except Exception as e:
            logger.warning(f"cancel_all_orders: {e}")
