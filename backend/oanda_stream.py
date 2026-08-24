import json
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from schemas import LivePrice
from config.settings import OANDA_CONFIG

logger = logging.getLogger(__name__)

M5_SECONDS = 300


class OandaPriceStream:
    """Background thread consuming OANDA's pricing stream (tick-by-tick).

    Keeps the latest bid/ask in memory and builds the forming M5 candle
    from ticks, so consumers never poll REST for prices.
    """

    def __init__(self):
        self._base_url = f"https://stream-{('fxpractice' if OANDA_CONFIG.env == 'practice' else 'fxtrade')}.oanda.com/v3"
        self._headers = {
            "Authorization": f"Bearer {OANDA_CONFIG.api_token}",
        }
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._latest: Optional[dict] = None  # {bid, ask, time(datetime), instrument}
        self._last_tick_monotonic: float = 0
        self._forming_m5: Optional[dict] = None  # {bucket_ts, open, high, low, close}
        self._connected = False

    # ------------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="oanda-price-stream", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    def _run(self):
        backoff = 1
        url = f"{self._base_url}/accounts/{OANDA_CONFIG.account_id}/pricing/stream"
        params = {"instruments": OANDA_CONFIG.instrument}
        while not self._stop.is_set():
            try:
                with requests.get(
                    url, headers=self._headers, params=params,
                    stream=True, timeout=(10, 30),
                ) as resp:
                    if resp.status_code != 200:
                        logger.error(f"Stream connect failed [{resp.status_code}]: {resp.text[:200]}")
                        self._connected = False
                        self._stop.wait(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                    logger.info(f"Pricing stream connected ({OANDA_CONFIG.instrument})")
                    self._connected = True
                    backoff = 1

                    for raw_line in resp.iter_lines(chunk_size=1):
                        if self._stop.is_set():
                            break
                        if not raw_line:
                            continue
                        try:
                            msg = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue
                        self._handle(msg)

            except requests.exceptions.ReadTimeout:
                logger.warning("Pricing stream read timeout - reconnecting")
            except Exception as e:
                if not self._stop.is_set():
                    logger.error(f"Pricing stream error: {e}")
            finally:
                self._connected = False

            if not self._stop.is_set():
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)

    def _handle(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "HEARTBEAT":
            self._last_tick_monotonic = time.monotonic()
            return
        if mtype != "PRICE":
            return

        bids = msg.get("bids") or []
        asks = msg.get("asks") or []
        if not bids or not asks:
            return

        bid = float(bids[0]["price"])
        ask = float(asks[0]["price"])
        ts = pd_safe_utc(msg.get("time"))

        with self._lock:
            self._latest = {
                "bid": bid,
                "ask": ask,
                "time": ts,
                "status": msg.get("status", "tradeable"),
            }
            self._update_forming(ts, (bid + ask) / 2.0)
        self._last_tick_monotonic = time.monotonic()

    def _update_forming(self, ts: datetime, mid: float):
        bucket = int(ts.timestamp() // M5_SECONDS) * M5_SECONDS
        f = self._forming_m5
        if f is None or bucket > f["bucket_ts"]:
            self._forming_m5 = {
                "bucket_ts": bucket,
                "open": mid,
                "high": mid,
                "low": mid,
                "close": mid,
            }
        else:
            f["high"] = max(f["high"], mid)
            f["low"] = min(f["low"], mid)
            f["close"] = mid

    # ------------------------------------------------------------------
    def is_fresh(self, max_age_seconds: float = 5.0) -> bool:
        if not self._latest:
            return False
        age = time.monotonic() - self._last_tick_monotonic
        return age <= max_age_seconds

    def get_live_price(self) -> Optional[LivePrice]:
        with self._lock:
            snap = dict(self._latest) if self._latest else None
        if not snap:
            return None
        bid, ask = snap["bid"], snap["ask"]
        return LivePrice(
            symbol=OANDA_CONFIG.instrument,
            bid=bid,
            ask=ask,
            spread=round(max(ask - bid, 0), 2),
            time=snap["time"],
        )

    def get_forming_m5(self) -> Optional[dict]:
        with self._lock:
            f = dict(self._forming_m5) if self._forming_m5 else None
        if not f:
            return None
        return {
            "time": datetime.fromtimestamp(f["bucket_ts"], tz=timezone.utc),
            "open": f["open"],
            "high": f["high"],
            "low": f["low"],
            "close": f["close"],
        }

    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "fresh": self.is_fresh(),
            "has_price": self._latest is not None,
        }


def pd_safe_utc(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    t = raw
    if t.endswith("Z"):
        t = t[:-1]
    if "." in t:
        head, frac = t.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        t = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(t).replace(tzinfo=timezone.utc)


_price_stream: Optional[OandaPriceStream] = None


def get_price_stream() -> OandaPriceStream:
    global _price_stream
    if _price_stream is None:
        _price_stream = OandaPriceStream()
    return _price_stream
