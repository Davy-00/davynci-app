import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
import logging
import time
import os
from config.settings import MT5_CONFIG, TRADING_CONFIG, APP_CONFIG
from schemas import CandleData, Timeframe, LivePrice

logger = logging.getLogger(__name__)

TF_MAP = {
    Timeframe.M5: mt5.TIMEFRAME_M5,
    Timeframe.M15: mt5.TIMEFRAME_M15,
    Timeframe.H1: mt5.TIMEFRAME_H1,
}

TF_SECONDS = {
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
}

MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


class MT5Client:
    def __init__(self):
        self.connected = False
        self.symbol = MT5_CONFIG.symbol
        self._last_candle_times: Dict[Timeframe, datetime] = {}
        self._candle_cache: Dict[Timeframe, pd.DataFrame] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._last_price: Optional[LivePrice] = None
        self._last_price_time: float = 0

    def connect(self, timeout: int = 15) -> bool:
        """Initialize MT5 connection in the current process."""
        if not os.path.exists(MT5_PATH):
            logger.error(f"MT5 terminal not found at {MT5_PATH}")
            return False

        logger.info(f"Connecting to MT5: {MT5_CONFIG.server}, login: {MT5_CONFIG.account_login}")
        
        # Try without login/password first (uses currently logged-in terminal)
        r = mt5.initialize(path=MT5_PATH, timeout=timeout * 1000)
        acct = mt5.account_info() if r else None
        
        if not acct:
            # Try with credentials
            mt5.shutdown()
            logger.info("No active account, trying login credentials...")
            r = mt5.initialize(
                path=MT5_PATH,
                login=MT5_CONFIG.account_login,
                password=MT5_CONFIG.password,
                server=MT5_CONFIG.server,
                timeout=timeout * 1000,
            )
            acct = mt5.account_info() if r else None

        if acct:
            logger.info(f"Connected to MT5: {acct.server}, Account: {acct.login}, Balance: {acct.balance}")
            self.connected = True
            return True
        else:
            err = mt5.last_error()
            logger.error(f"MT5 initialize failed: {err}")
            mt5.shutdown()
            return False

    def disconnect(self):
        if self.connected:
            mt5.shutdown()
            self.connected = False

    def get_symbol_info(self) -> Optional[Dict[str, Any]]:
        info = mt5.symbol_info(self.symbol)
        if info is None:
            logger.error(f"Symbol {self.symbol} not found")
            return None
        return {
            "bid": info.bid,
            "ask": info.ask,
            "spread": info.spread,
            "point": info.point,
            "digits": info.digits,
            "trade_tick_size": info.trade_tick_size,
            "trade_tick_value": info.trade_tick_value,
        }

    def get_live_price(self) -> Optional[LivePrice]:
        now = time.time()
        if self._last_price and (now - self._last_price_time) < 3:
            return self._last_price

        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return self._last_price

        self._last_price = LivePrice(
            symbol=self.symbol,
            bid=tick.bid,
            ask=tick.ask,
            spread=max(tick.ask - tick.bid, 0),
            time=datetime.fromtimestamp(tick.time, tz=timezone.utc),
        )
        self._last_price_time = now
        return self._last_price

    def _fetch_candles(self, timeframe: Timeframe, count: int) -> Optional[pd.DataFrame]:
        now = time.time()
        cache_key = f"{timeframe.value}_{count}"
        cache_ttl = {"M5": 20, "M15": 40, "H1": 120}
        ttl = cache_ttl.get(timeframe.value, 60)

        if cache_key in self._candle_cache and (now - self._cache_timestamps.get(cache_key, 0)) < ttl:
            return self._candle_cache[cache_key].tail(count)

        mt5_tf = TF_MAP[timeframe]
        rates = mt5.copy_rates_from_pos(self.symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning(f"No rates for {timeframe}: {mt5.last_error()}")
            if cache_key in self._candle_cache:
                return self._candle_cache[cache_key].tail(count)
            return None

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df.set_index('time', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'tick_volume']]
        df.columns = ['open', 'high', 'low', 'close', 'volume']

        self._candle_cache[cache_key] = df.copy()
        self._cache_timestamps[cache_key] = now
        return df.tail(count)

    def get_candles(self, timeframe: Timeframe, count: int = None) -> List[CandleData]:
        if count is None:
            count = APP_CONFIG.candle_history_bars

        df = self._fetch_candles(timeframe, count)
        if df is None:
            return []

        candles = []
        for idx, row in df.iterrows():
            candles.append(CandleData(
                time=idx.to_pydatetime(),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=int(row['volume']),
                timeframe=timeframe,
            ))
        return candles

    def get_candles_df(self, timeframe: Timeframe, count: int = None) -> Optional[pd.DataFrame]:
        if count is None:
            count = APP_CONFIG.candle_history_bars
        return self._fetch_candles(timeframe, count)

    def check_new_candle(self, timeframe: Timeframe) -> bool:
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return False

        current_time = datetime.fromtimestamp(tick.time, tz=timezone.utc)
        tf_seconds = TF_SECONDS[timeframe]
        current_candle_start = current_time.replace(
            second=0, microsecond=0
        )
        current_candle_start = current_candle_start - timedelta(
            seconds=current_candle_start.timestamp() % tf_seconds
        )

        last_time = self._last_candle_times.get(timeframe)
        if last_time is None:
            self._last_candle_times[timeframe] = current_candle_start
            return True

        if current_candle_start > last_time:
            self._last_candle_times[timeframe] = current_candle_start
            return True
        return False

    def get_all_timeframes_data(self, count: int = None) -> Dict[Timeframe, List[CandleData]]:
        result = {}
        for tf in MT5_CONFIG.timeframes:
            result[tf] = self.get_candles(tf, count)
        return result

    def get_all_timeframes_df(self, count: int = None) -> Dict[Timeframe, pd.DataFrame]:
        result = {}
        for tf in MT5_CONFIG.timeframes:
            result[tf] = self.get_candles_df(tf, count)
        return result


_mt5_client: Optional[MT5Client] = None


def get_mt5_client() -> MT5Client:
    global _mt5_client
    if _mt5_client is None:
        _mt5_client = MT5Client()
    return _mt5_client
