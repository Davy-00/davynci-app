import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List
from schemas import Signal, SignalStatus, SignalDirection
from config.settings import TRADING_CONFIG

logger = logging.getLogger(__name__)


class SignalManager:
    def __init__(self):
        self.active_signal: Optional[Signal] = None
        self.signals_today: List[Signal] = []
        self.consecutive_losses: int = 0
        self.daily_limit_reached: bool = False
        self.daily_loss_limit_reached: bool = False
        self._current_date: Optional[date] = None
        self._on_signal_closed_callbacks: List = []

    def _check_new_day(self):
        today = datetime.now(timezone.utc).date()
        if self._current_date is None or today != self._current_date:
            logger.info(f"New day detected: {today}. Resetting daily counters.")
            self._current_date = today
            self.signals_today = []
            self.consecutive_losses = 0
            self.daily_limit_reached = False
            self.daily_loss_limit_reached = False

    def can_generate_signal(self) -> bool:
        self._check_new_day()
        
        if self.active_signal is not None:
            return False
        
        if self.daily_limit_reached:
            return False
        
        if self.daily_loss_limit_reached:
            return False
        
        if len(self.signals_today) >= TRADING_CONFIG.max_daily_signals:
            self.daily_limit_reached = True
            logger.info(f"Daily signal limit ({TRADING_CONFIG.max_daily_signals}) reached.")
            return False
        
        return True

    def add_signal(self, signal: Signal):
        self._check_new_day()
        self.active_signal = signal
        self.signals_today.append(signal)
        logger.info(f"Signal {signal.id} added: {signal.direction} @ {signal.entry_price:.2f}")

    def update_signal_pnl(self, current_price: float):
        if self.active_signal is None:
            return
        
        signal = self.active_signal
        
        if signal.direction == SignalDirection.BUY:
            pnl_pips = current_price - signal.entry_price
            if not signal.sl_moved_to_be:
                sl_distance = signal.entry_price - signal.stop_loss
            else:
                sl_distance = signal.entry_price - signal.stop_loss
        else:
            pnl_pips = signal.entry_price - current_price
            if not signal.sl_moved_to_be:
                sl_distance = signal.stop_loss - signal.entry_price
            else:
                sl_distance = signal.stop_loss - signal.entry_price
        
        point_value = 1.0
        pnl_pips_raw = pnl_pips / point_value
        risk_per_pip = signal.risk_dollars / signal.risk_pips if signal.risk_pips > 0 else 1
        
        signal.current_pnl_pips = round(pnl_pips_raw, 1)
        signal.current_pnl = round(pnl_pips_raw * risk_per_pip, 2)

    def check_tp_sl(self, current_price: float) -> bool:
        if self.active_signal is None:
            return False
        
        signal = self.active_signal
        
        if signal.direction == SignalDirection.BUY:
            if current_price >= signal.tp2:
                self._close_signal(signal.tp2, "TP2_HIT", current_price)
                return True
            elif not signal.tp1_hit and current_price >= signal.tp1:
                signal.tp1_hit = True
                signal.status = SignalStatus.TP1_HIT
                signal.stop_loss = signal.entry_price
                signal.sl_moved_to_be = True
                logger.info(f"Signal {signal.id} TP1 hit. SL moved to breakeven.")
                return False
            elif current_price <= signal.stop_loss:
                self._close_signal(signal.stop_loss, "SL_HIT", current_price)
                return True
        else:
            if current_price <= signal.tp2:
                self._close_signal(signal.tp2, "TP2_HIT", current_price)
                return True
            elif not signal.tp1_hit and current_price <= signal.tp1:
                signal.tp1_hit = True
                signal.status = SignalStatus.TP1_HIT
                signal.stop_loss = signal.entry_price
                signal.sl_moved_to_be = True
                logger.info(f"Signal {signal.id} TP1 hit. SL moved to breakeven.")
                return False
            elif current_price >= signal.stop_loss:
                self._close_signal(signal.stop_loss, "SL_HIT", current_price)
                return True
        
        return False

    def _close_signal(self, exit_price: float, reason: str, current_price: float):
        if self.active_signal is None:
            return
        
        signal = self.active_signal
        signal.exit_price = exit_price
        signal.exit_time = datetime.now(timezone.utc)
        signal.exit_reason = reason
        
        if signal.direction == SignalDirection.BUY:
            total_pips = exit_price - signal.entry_price
        else:
            total_pips = signal.entry_price - exit_price
        
        point_value = 1.0
        total_pips_raw = total_pips / point_value
        risk_per_pip = signal.risk_dollars / signal.risk_pips if signal.risk_pips > 0 else 1
        total_pnl = total_pips_raw * risk_per_pip
        
        signal.current_pnl_pips = round(total_pips_raw, 1)
        signal.current_pnl = round(total_pnl, 2)
        
        if reason == "SL_HIT":
            signal.status = SignalStatus.SL_HIT
            self.consecutive_losses += 1
            if self.consecutive_losses >= TRADING_CONFIG.max_consecutive_losses:
                self.daily_loss_limit_reached = True
                logger.warning("Daily loss limit reached (2 consecutive SL hits).")
        else:
            signal.status = SignalStatus.TP2_HIT
            self.consecutive_losses = 0
        
        signal.rr_achieved = abs(total_pips_raw / signal.risk_pips) if signal.risk_pips > 0 else 0
        
        logger.info(f"Signal {signal.id} closed: {reason} @ {exit_price:.2f}, PnL: ${signal.current_pnl:.2f}")
        
        closed_signal = signal
        self.active_signal = None
        
        for callback in self._on_signal_closed_callbacks:
            try:
                callback(closed_signal)
            except Exception as e:
                logger.error(f"Error in signal close callback: {e}")

    def get_active_signal(self) -> Optional[Signal]:
        return self.active_signal

    def get_signals_today(self) -> List[Signal]:
        self._check_new_day()
        return self.signals_today

    def on_signal_closed(self, callback):
        self._on_signal_closed_callbacks.append(callback)

    def reset(self):
        self.active_signal = None
        self.signals_today = []
        self.consecutive_losses = 0
        self.daily_limit_reached = False
        self.daily_loss_limit_reached = False
        self._current_date = datetime.now(timezone.utc).date()

    def get_status(self) -> dict:
        self._check_new_day()
        return {
            "has_active_signal": self.active_signal is not None,
            "signals_today_count": len(self.signals_today),
            "max_daily_signals": TRADING_CONFIG.max_daily_signals,
            "daily_limit_reached": self.daily_limit_reached,
            "consecutive_losses": self.consecutive_losses,
            "daily_loss_limit_reached": self.daily_loss_limit_reached,
            "can_generate": self.can_generate_signal(),
        }
