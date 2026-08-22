import json
import os
from datetime import datetime, timezone
from typing import List, Optional
from schemas import Signal, TradeHistoryEntry, Statistics, SignalStatus, SignalDirection, StrategyType
from config.settings import TRADING_CONFIG
import logging

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "trade_history.json")


class TradeHistory:
    def __init__(self):
        self.trades: List[TradeHistoryEntry] = []
        self._ensure_data_dir()
        self._load_history()

    def _ensure_data_dir(self):
        os.makedirs(DATA_DIR, exist_ok=True)

    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r') as f:
                    data = json.load(f)
                    self.trades = [TradeHistoryEntry(**item) for item in data]
                logger.info(f"Loaded {len(self.trades)} historical trades")
            except Exception as e:
                logger.error(f"Error loading history: {e}")
                self.trades = []

    def _save_history(self):
        try:
            with open(HISTORY_FILE, 'w') as f:
                data = [trade.model_dump() for trade in self.trades]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving history: {e}")

    def add_trade(self, signal: Signal):
        if signal.exit_time is None:
            return
        
        result = "TP2"
        if signal.status == SignalStatus.SL_HIT:
            result = "SL"
        elif signal.tp1_hit and signal.status == SignalStatus.TP2_HIT:
            result = "TP2"
        elif signal.tp1_hit:
            result = "TP1"
        
        entry = TradeHistoryEntry(
            date=signal.entry_time.strftime("%Y-%m-%d"),
            time=signal.entry_time.strftime("%H:%M:%S"),
            direction=signal.direction,
            strategy_type=signal.strategy_type,
            entry=signal.entry_price,
            stop_loss=signal.stop_loss,
            result=result,
            pnl_pips=signal.current_pnl_pips,
            pnl_dollars=signal.current_pnl,
            rr_achieved=signal.rr_achieved or 0.0,
        )
        
        self.trades.append(entry)
        self._save_history()
        logger.info(f"Trade added to history: {entry}")

    def get_all_trades(self) -> List[TradeHistoryEntry]:
        return self.trades

    def get_today_trades(self) -> List[TradeHistoryEntry]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [t for t in self.trades if t.date == today]

    def get_statistics(self) -> Statistics:
        if not self.trades:
            return Statistics()
        
        total_signals = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl_dollars > 0]
        win_rate = (len(winning_trades) / total_signals * 100) if total_signals > 0 else 0
        
        avg_rr = sum(t.rr_achieved for t in self.trades) / total_signals if total_signals > 0 else 0
        total_pnl = sum(t.pnl_dollars for t in self.trades)
        
        today_trades = self.get_today_trades()
        daily_pnl = sum(t.pnl_dollars for t in today_trades)
        
        return Statistics(
            total_signals=total_signals,
            win_rate=round(win_rate, 1),
            avg_rr=round(avg_rr, 2),
            total_pnl_dollars=round(total_pnl, 2),
            daily_pnl_dollars=round(daily_pnl, 2),
        )

    def clear_history(self):
        self.trades = []
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        logger.info("Trade history cleared")


trade_history = TradeHistory()
