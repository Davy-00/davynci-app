import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional
import logging
import time
import os
import csv

from schemas import Timeframe, LivePrice
from config.settings import MT5_CONFIG

logger = logging.getLogger(__name__)

TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600}

CSV_PATH = os.path.join(
    os.environ.get('APPDATA', ''),
    r'MetaQuotes\Terminal\Common\Files\GOLD_data.csv',
)

class MT5BridgeClient:
    def __init__(self):
        self.connected = False
        self.symbol = MT5_CONFIG.symbol
        self._m1_df: Optional[pd.DataFrame] = None
        self._last_price: Optional[LivePrice] = None
        self._last_mtime: float = 0
        self._cache: dict = {}
        self._cache_times: dict = {}

    def connect(self) -> bool:
        if not os.path.exists(CSV_PATH):
            logger.warning(f"GOLD_data.csv not found at {CSV_PATH}")
            return False
        self.connected = True
        logger.info(f"MT5 Bridge connected: {CSV_PATH}")
        return True

    def disconnect(self):
        self.connected = False

    def _read_csv(self) -> Optional[pd.DataFrame]:
        try:
            if not os.path.exists(CSV_PATH):
                return None
            mtime = os.path.getmtime(CSV_PATH)
            if mtime == self._last_mtime and self._m1_df is not None:
                return self._m1_df

            with open(CSV_PATH, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)

            if len(rows) < 4:
                return None

            # Row 1: bid, ask, timestamp
            if len(rows[0]) >= 3:
                bid = float(rows[0][1])
                ask = float(rows[0][2])
                self._last_price = LivePrice(
                    symbol=self.symbol, bid=bid, ask=ask,
                    spread=round(ask - bid, 2),
                    time=datetime.now(timezone.utc),
                )

            # Rows 3+: candles
            records = []
            for row in rows[2:]:
                if len(row) >= 6:
                    try:
                        records.append({
                            'time': pd.to_datetime(row[0], format='%Y.%m.%d %H:%M', utc=True),
                            'open': float(row[1]),
                            'high': float(row[2]),
                            'low': float(row[3]),
                            'close': float(row[4]),
                            'volume': float(row[5]),
                        })
                    except (ValueError, IndexError):
                        continue

            if not records:
                return self._m1_df

            df = pd.DataFrame(records).set_index('time').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            self._m1_df = df
            self._last_mtime = mtime
            return df

        except Exception as e:
            logger.error(f"CSV read error: {e}")
            return self._m1_df

    def get_candles_df(self, timeframe: Timeframe, count: int = 500) -> Optional[pd.DataFrame]:
        cache_key = timeframe.value
        now = time.time()

        if cache_key in self._cache and (now - self._cache_times.get(cache_key, 0)) < 5:
            df = self._cache[cache_key]
            return df.tail(count) if count else df

        m1 = self._read_csv()
        if m1 is None or m1.empty:
            return self._cache.get(cache_key, pd.DataFrame()).tail(count) if count else self._cache.get(cache_key)

        if timeframe.value == 'M1':
            df = m1
        else:
            rule = f"{TF_SECONDS[timeframe.value]}S"
            df = m1.resample(rule).agg({
                'open': 'first', 'high': 'max',
                'low': 'min', 'close': 'last', 'volume': 'sum',
            }).dropna()

        self._cache[cache_key] = df
        self._cache_times[cache_key] = now
        return df.tail(count) if count else df

    def get_live_price(self) -> Optional[LivePrice]:
        self._read_csv()
        return self._last_price

    def check_new_candle(self, timeframe: Timeframe) -> bool:
        return True

    def get_data_source_label(self) -> str:
        return f"MT5 Bridge ({self.symbol})"
