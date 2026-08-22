from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum


class Timeframe(str, Enum):
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    SL_HIT = "SL_HIT"
    CLOSED = "CLOSED"


class StrategyType(str, Enum):
    BOUNCE = "BOUNCE"
    REVERSAL = "REVERSAL"
    CONTINUATION = "CONTINUATION"
    BREAKOUT = "BREAKOUT"


class CandleData(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    timeframe: Timeframe


class IndicatorData(BaseModel):
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    rsi: Optional[float] = None
    atr: Optional[float] = None
    support_levels: List[float] = Field(default_factory=list)
    resistance_levels: List[float] = Field(default_factory=list)
    trend_line_points: List[tuple] = Field(default_factory=list)


class Signal(BaseModel):
    id: str
    direction: SignalDirection
    strategy_type: StrategyType = StrategyType.CONTINUATION
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    risk_pips: float
    risk_dollars: float
    lot_size: float
    entry_time: datetime
    status: SignalStatus = SignalStatus.ACTIVE
    tp1_hit: bool = False
    sl_moved_to_be: bool = False
    current_pnl: float = 0.0
    current_pnl_pips: float = 0.0
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None
    rr_achieved: Optional[float] = None
    strategy_details: Optional[dict] = None


class TradeHistoryEntry(BaseModel):
    date: str
    time: str
    direction: SignalDirection
    strategy_type: StrategyType
    entry: float
    stop_loss: float
    result: Literal["TP1", "TP2", "SL"]
    pnl_pips: float
    pnl_dollars: float
    rr_achieved: float


class Statistics(BaseModel):
    total_signals: int = 0
    win_rate: float = 0.0
    avg_rr: float = 0.0
    total_pnl_dollars: float = 0.0
    daily_pnl_dollars: float = 0.0


class LivePrice(BaseModel):
    symbol: str
    bid: float
    ask: float
    spread: float
    time: datetime


class ChartData(BaseModel):
    candles: List[CandleData]
    indicators: IndicatorData
    signals: List[Signal]
    current_price: LivePrice
    timeframe: Timeframe


class SessionInfo(BaseModel):
    is_london_session: bool
    is_ny_session: bool
    is_active_session: bool
    current_session: str
    next_session: str
    time_to_next_session: str


class BacktestTrade(BaseModel):
    entry_time: datetime
    exit_time: Optional[datetime]
    direction: SignalDirection
    strategy_type: StrategyType
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    tp1: float
    tp2: float
    result: Optional[Literal["TP1", "TP2", "SL"]]
    pnl_pips: float
    pnl_dollars: float
    rr_achieved: float


class BacktestResult(BaseModel):
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl: float
    avg_rr: float
    max_drawdown: float
    profit_factor: float
    avg_bars_held: float
    trades: List[BacktestTrade]
    by_strategy: dict


class BacktestConfig(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_balance: float = 5000.0
    risk_per_trade: float = 1.0
    max_spread: float = 2.0
    session_filter: bool = True
