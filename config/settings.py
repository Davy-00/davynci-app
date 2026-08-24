import os
from dataclasses import dataclass
from typing import List


def _load_dotenv(path: str = None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not os.environ.get(key):
                os.environ[key] = value


_load_dotenv()


@dataclass
class OandaConfig:
    api_token: str = ""
    env: str = "practice"
    account_id: str = ""
    instrument: str = "XAU_USD"

    def __post_init__(self):
        self.api_token = self.api_token or os.environ.get("OANDA_API_TOKEN", "")
        self.env = os.environ.get("OANDA_ENV", self.env)
        self.account_id = self.account_id or os.environ.get("OANDA_ACCOUNT_ID", "")

    @property
    def hostname(self) -> str:
        return "api-fxpractice.oanda.com" if self.env == "practice" else "api-fxtrade.oanda.com"


@dataclass
class TradingConfig:
    account_balance: float = 5000.0
    risk_per_trade_pct: float = 1.0
    max_daily_signals: int = 3
    max_consecutive_losses: int = 2
    ema_periods: List[int] = None
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    atr_period: int = 14
    swing_lookback: int = 20
    ema_200_slope_lookback: int = 10
    price_ema_threshold_pct: float = 0.3
    sl_atr_multiplier: float = 3.0
    tp1_rr: float = 2.0
    tp2_rr: float = 6.0
    rsi_cross_bars: int = 2
    require_engulfing: bool = False
    session_windows: List[tuple] = None

    def __post_init__(self):
        if self.ema_periods is None:
            self.ema_periods = [21, 50, 200]
        if self.session_windows is None:
            self.session_windows = [
                (12, 16),   # New York 12:00-16:00 GMT
            ]


@dataclass
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8050
    ws_port: int = 8051
    debug: bool = True
    chart_update_interval_ms: int = 5000
    price_update_interval_ms: int = 5000
    candle_history_bars: int = 500


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    def __post_init__(self):
        self.bot_token = self.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = self.chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


OANDA_CONFIG = OandaConfig()
TRADING_CONFIG = TradingConfig()
APP_CONFIG = AppConfig()
TELEGRAM_CONFIG = TelegramConfig()