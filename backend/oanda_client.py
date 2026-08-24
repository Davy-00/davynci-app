import pandas as pd
import requests
from datetime import datetime, timezone
from typing import Optional
import logging
import time

from schemas import Timeframe, LivePrice
from config.settings import OANDA_CONFIG

logger = logging.getLogger(__name__)

TF_MAP = {
    Timeframe.M5: "M5",
    Timeframe.M15: "M15",
    Timeframe.H1: "H1",
}

CACHE_TTL = {
    "M5": 20,
    "M15": 40,
    "H1": 120,
}

MAX_COUNT = 5000


class OandaClient:
    def __init__(self):
        self.connected = False
        self.instrument = OANDA_CONFIG.instrument
        self._base_url = f"https://{OANDA_CONFIG.hostname}/v3"
        self._headers = {
            "Authorization": f"Bearer {OANDA_CONFIG.api_token}",
            "Content-Type": "application/json",
        }
        self.account_id = OANDA_CONFIG.account_id
        self._candle_cache: dict = {}
        self._cache_times: dict = {}
        self._last_price: Optional[LivePrice] = None
        self._last_price_time: float = 0

    def connect(self) -> bool:
        if not OANDA_CONFIG.api_token or not self.account_id:
            logger.error("OANDA_API_TOKEN or OANDA_ACCOUNT_ID missing from environment")
            return False
        try:
            resp = requests.get(
                f"{self._base_url}/accounts/{self.account_id}/summary",
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                acct = data.get("account", {})
                logger.info(
                    f"Connected to OANDA ({OANDA_CONFIG.env}): "
                    f"Account {acct.get('id')}, Balance {acct.get('balance')} {acct.get('currency')}"
                )
                self.connected = True
                return True
            logger.error(f"OANDA connect failed [{resp.status_code}]: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"OANDA connect error: {e}")
            return False

    def disconnect(self):
        self.connected = False

    def get_account_summary(self) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{self._base_url}/accounts/{self.account_id}/summary",
                headers=self._headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("account")
            logger.error(f"OANDA account summary failed [{resp.status_code}]: {resp.text}")
        except Exception as e:
            logger.error(f"OANDA account summary error: {e}")
        return None

    def get_live_price(self) -> Optional[LivePrice]:
        now = time.time()
        if self._last_price and (now - self._last_price_time) < 3:
            return self._last_price

        # Prefer the tick stream when it's alive and current
        from oanda_stream import get_price_stream
        stream = get_price_stream()
        if stream.is_fresh(max_age_seconds=5.0):
            lp = stream.get_live_price()
            if lp:
                self._last_price = lp
                self._last_price_time = now
                return lp

        try:
            resp = requests.get(
                f"{self._base_url}/accounts/{self.account_id}/pricing",
                headers=self._headers,
                params={"instruments": self.instrument},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"OANDA pricing failed [{resp.status_code}]: {resp.text}")
                return self._last_price

            prices = resp.json().get("prices", [])
            if not prices:
                return self._last_price

            p = prices[0]
            bid = float(p["bids"][0]["price"]) if p.get("bids") else float(p["closeoutBid"])
            ask = float(p["asks"][0]["price"]) if p.get("asks") else float(p["closeoutAsk"])
            ts = p.get("time")
            if ts:
                t = pd.to_datetime(ts, utc=True).floor("us").to_pydatetime()
            else:
                t = datetime.now(timezone.utc)

            self._last_price = LivePrice(
                symbol=self.instrument,
                bid=bid,
                ask=ask,
                spread=round(max(ask - bid, 0), 2),
                time=t,
            )
            self._last_price_time = now
            return self._last_price
        except Exception as e:
            logger.error(f"OANDA pricing error: {e}")
            return self._last_price

    def _fetch_candles(self, timeframe: Timeframe, count: int) -> Optional[pd.DataFrame]:
        granularity = TF_MAP[timeframe]
        count = min(count, MAX_COUNT)

        cache_key = f"{timeframe.value}_{count}"
        ttl = CACHE_TTL.get(timeframe.value, 60)
        now = time.time()
        if cache_key in self._candle_cache and (now - self._cache_times.get(cache_key, 0)) < ttl:
            return self._candle_cache[cache_key].tail(count)

        try:
            resp = requests.get(
                f"{self._base_url}/instruments/{self.instrument}/candles",
                headers=self._headers,
                params={
                    "granularity": granularity,
                    "count": count,
                    "price": "M",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(f"OANDA candles failed [{resp.status_code}]: {resp.text}")
                if cache_key in self._candle_cache:
                    return self._candle_cache[cache_key].tail(count)
                return None

            candles = resp.json().get("candles", [])
            if not candles:
                logger.warning(f"OANDA returned no candles for {timeframe.value}")
                if cache_key in self._candle_cache:
                    return self._candle_cache[cache_key].tail(count)
                return None

            records = []
            for c in candles:
                mid = c.get("mid", {})
                records.append({
                    "time": c["time"],
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": int(c.get("volume", 0)),
                })

            df = pd.DataFrame(records)
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df.set_index("time", inplace=True)

            self._candle_cache[cache_key] = df.copy()
            self._cache_times[cache_key] = now
            return df.tail(count)
        except Exception as e:
            logger.error(f"OANDA candles error: {e}")
            if cache_key in self._candle_cache:
                return self._candle_cache[cache_key].tail(count)
            return None

    def get_candles_df(self, timeframe: Timeframe, count: int = 500) -> Optional[pd.DataFrame]:
        df = self._fetch_candles(timeframe, count)
        if df is None or df.empty:
            return df
        if timeframe != Timeframe.M5:
            return df

        # Patch the last (forming) M5 candle with tick-stream data when fresher
        from oanda_stream import get_price_stream
        forming = get_price_stream().get_forming_m5()
        if forming is None:
            return df

        bucket = pd.Timestamp(forming["time"])
        if df.index[-1] == bucket:
            df.iloc[-1, df.columns.get_indexer(["high"])] = max(df["high"].iloc[-1], forming["high"])
            df.iloc[-1, df.columns.get_indexer(["low"])] = min(df["low"].iloc[-1], forming["low"])
            df.iloc[-1, df.columns.get_indexer(["close"])] = forming["close"]
        elif bucket > df.index[-1]:
            patch = pd.DataFrame(
                [{
                    "open": forming["open"], "high": forming["high"],
                    "low": forming["low"], "close": forming["close"],
                    "volume": 0,
                }],
                index=[bucket],
            )
            patch.index.name = "time"
            df = pd.concat([df, patch])
        return df

    def get_candles_range(
        self,
        timeframe: Timeframe,
        start_utc: datetime,
        end_utc: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch candles covering [start_utc, end_utc], paginating past the
        5000-bar per-request limit."""
        granularity = TF_MAP[timeframe]
        tf_seconds = {"M5": 300, "M15": 900, "H1": 3600}[timeframe.value]
        frames = []
        cursor = start_utc.astimezone(timezone.utc)

        while True:
            params = {
                "granularity": granularity,
                "count": MAX_COUNT,
                "price": "M",
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

            try:
                resp = requests.get(
                    f"{self._base_url}/instruments/{self.instrument}/candles",
                    headers=self._headers,
                    params=params,
                    timeout=20,
                )
            except Exception as e:
                logger.error(f"OANDA range fetch error: {e}")
                break

            if resp.status_code != 200:
                logger.error(f"OANDA range fetch failed [{resp.status_code}]: {resp.text}")
                break

            candles = resp.json().get("candles", [])
            if not candles:
                break

            records = []
            for c in candles:
                mid = c.get("mid", {})
                records.append({
                    "time": c["time"],
                    "open": float(mid["o"]),
                    "high": float(mid["h"]),
                    "low": float(mid["l"]),
                    "close": float(mid["c"]),
                    "volume": int(c.get("volume", 0)),
                })
            frames.append(pd.DataFrame(records))

            if len(candles) < MAX_COUNT:
                break

            last_time = pd.to_datetime(candles[-1]["time"], utc=True)
            cursor = (last_time + pd.Timedelta(seconds=tf_seconds)).to_pydatetime()
            if end_utc and cursor >= end_utc:
                break

        if not frames:
            return None

        df = pd.concat(frames)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df.set_index("time", inplace=True)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        logger.info(f"OANDA range {timeframe.value}: {len(df)} bars "
                    f"[{df.index[0]} .. {df.index[-1]}]")
        return df

    def check_new_candle(self, timeframe: Timeframe) -> bool:
        return True

    def get_data_source_label(self) -> str:
        from oanda_stream import get_price_stream
        suffix = " + tick stream" if get_price_stream().is_connected() else ""
        return f"OANDA {OANDA_CONFIG.env} ({self.instrument}){suffix}"


_oanda_client: Optional[OandaClient] = None


def get_oanda_client() -> OandaClient:
    global _oanda_client
    if _oanda_client is None:
        _oanda_client = OandaClient()
    return _oanda_client
