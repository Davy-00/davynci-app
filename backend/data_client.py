import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import logging
import time

from schemas import CandleData, Timeframe, LivePrice
from config.settings import APP_CONFIG

logger = logging.getLogger(__name__)

TF_YF_INTERVAL = {
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.H1: "60m",
}

TF_PERIOD = {
    Timeframe.M5: "5d",
    Timeframe.M15: "10d",
    Timeframe.H1: "60d",
}

TICKER = "GC=F"

class DataClient:
    def __init__(self):
        self.symbol = "XAUUSD"
        self.connected = False
        self._cache: Dict[str, pd.DataFrame] = {}
        self._last_fetch: Dict[str, float] = {}
        self._last_prices: Dict[str, LivePrice] = {}
        self._basis_spread: Optional[float] = None
        self._basis_updated: float = 0
        self._last_xauusd_price: Optional[float] = None
        self._data_source_label: str = "yfinance (GC=F)"

    def connect(self) -> bool:
        try:
            ticker = yf.Ticker(TICKER)
            data = ticker.history(period="1d", interval="1m")
            if data is not None and not data.empty:
                self.connected = True
                logger.info("DataClient connected (GC=F with XAUUSD basis adjustment)")
                return True
        except Exception as e:
            logger.error(f"DataClient connect error: {e}")
        self.connected = True  # optimistic
        return True

    def _get_basis_spread(self) -> float:
        now = time.time()
        if self._basis_spread is not None and (now - self._basis_updated) < 120:
            return self._basis_spread
        try:
            xau = self._fetch_xauusd_price()
            gc = self._fetch_gcf_price()
            if xau and gc:
                self._basis_spread = xau - gc
                self._basis_updated = now
                logger.info(f"Basis XAUUSD-GC=F: ${self._basis_spread:.2f}")
            elif self._basis_spread is None:
                self._basis_spread = -18.0
        except Exception as e:
            logger.error(f"Basis spread error: {e}")
            if self._basis_spread is None:
                self._basis_spread = -18.0
        return self._basis_spread

    def _fetch_gcf_price(self) -> Optional[float]:
        try:
            t = yf.Ticker(TICKER)
            data = t.history(period="1d", interval="1m")
            if data is not None and not data.empty:
                return float(data.iloc[-1]['Close'])
        except Exception as e:
            logger.error(f"GC=F price error: {e}")
        return None

    def _fetch_xauusd_price(self) -> Optional[float]:
        try:
            from tradingview_ta import TA_Handler, Interval
            handler = TA_Handler(
                symbol="XAUUSD",
                exchange="OANDA",
                screener="cfd",
                interval=Interval.INTERVAL_15_MINUTES,
            )
            analysis = handler.get_analysis()
            price = analysis.indicators.get('close')
            if price:
                self._last_xauusd_price = float(price)
                return self._last_xauusd_price
        except Exception as e:
            logger.error(f"XAUUSD price error: {e}")
        return self._last_xauusd_price

    def get_live_price(self) -> Optional[LivePrice]:
        now = time.time()
        if "live" in self._last_fetch and (now - self._last_fetch.get("_price", 0)) < 10:
            return self._last_prices.get("live")

        xauusd = self._fetch_xauusd_price()
        gc = self._fetch_gcf_price()

        if xauusd:
            bid = xauusd - 0.3
            ask = xauusd + 0.3
            spread = round(ask - bid, 2)
            self._data_source_label = "XAUUSD (TradingView)"
        elif gc:
            bid = gc - 0.5
            ask = gc + 0.5
            spread = 1.0
            self._data_source_label = "GC=F (yfinance)"
        else:
            self._data_source_label = "offline"
            if self._last_prices.get("live"):
                return self._last_prices["live"]
            return None

        lp = LivePrice(
            symbol=f"XAUUSD",
            bid=bid,
            ask=ask,
            spread=spread,
            time=datetime.now(timezone.utc),
        )
        self._last_prices["live"] = lp
        self._last_fetch["_price"] = now
        return lp

    def get_data_source_label(self) -> str:
        return self._data_source_label

    def _tf_cache_key(self, tf: Timeframe) -> str:
        return f"df_{tf.value}"

    def _cache_valid(self, cache_key: str, ttl: float) -> bool:
        if cache_key not in self._last_fetch:
            return False
        return (time.time() - self._last_fetch[cache_key]) < ttl

    def _get_candle_cache_ttl(self, tf: Timeframe) -> float:
        if tf == Timeframe.M5:
            return 30
        elif tf == Timeframe.M15:
            return 60
        elif tf == Timeframe.H1:
            return 240
        return 60

    def get_candles_df(self, timeframe: Timeframe, count: int = None) -> Optional[pd.DataFrame]:
        cache_key = self._tf_cache_key(timeframe)
        ttl = self._get_candle_cache_ttl(timeframe)
        if self._cache_valid(cache_key, ttl) and cache_key in self._cache:
            df = self._cache[cache_key]
            if count and len(df) > count:
                return df.tail(count)
            return df

        try:
            interval = TF_YF_INTERVAL[timeframe]
            period = TF_PERIOD[timeframe]
            ticker = yf.Ticker(TICKER)
            df = ticker.history(period=period, interval=interval)

            if df is None or df.empty:
                if cache_key in self._cache:
                    cached = self._cache[cache_key]
                    if count and len(cached) > count:
                        return cached.tail(count)
                    return cached
                return None

            df = df.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low',
                'Close': 'close', 'Volume': 'volume'
            })
            df.index = pd.DatetimeIndex(df.index).tz_convert('UTC')

            base_spread = self._get_basis_spread()
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col] + base_spread

            self._cache[cache_key] = df
            self._last_fetch[cache_key] = time.time()

            if count and len(df) > count:
                return df.tail(count)
            return df

        except Exception as e:
            logger.error(f"get_candles_df error: {e}")
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                if count and len(cached) > count:
                    return cached.tail(count)
                return cached
            return None

    def check_new_candle(self, timeframe: Timeframe) -> bool:
        return True


_data_client_instance: Optional['DataClient'] = None


def get_data_client() -> DataClient:
    global _data_client_instance
    if _data_client_instance is None:
        _data_client_instance = DataClient()
        _data_client_instance.connect()
    return _data_client_instance
