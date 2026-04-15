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
        # Platzhalter für neue Swingtrading-Strategie
            balance = self.exchange.fetch_balance(params=params)
