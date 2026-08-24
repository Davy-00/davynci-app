import logging
import asyncio
from typing import Optional

import requests

from schemas import Signal, SignalStatus
from config.settings import TELEGRAM_CONFIG

logger = logging.getLogger(__name__)


def _post_message(text: str) -> bool:
    token = TELEGRAM_CONFIG.bot_token
    chat_id = TELEGRAM_CONFIG.chat_id
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Telegram send failed [{resp.status_code}]: {resp.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


async def send_telegram(text: str) -> Optional[bool]:
    if not TELEGRAM_CONFIG.enabled:
        return False
    try:
        return await asyncio.to_thread(_post_message, text)
    except Exception as e:
        logger.error(f"Telegram task error: {e}")
        return False


def _dir_str(direction) -> str:
    # Signal.direction is a SignalDirection enum; .value gives "BUY"/"SELL".
    # Fall back to str() for plain-string callers.
    return direction.value if hasattr(direction, "value") else str(direction)


def _dir_emoji(direction) -> str:
    return "\U0001F7E2 BUY" if _dir_str(direction) == "BUY" else "\U0001F534 SELL"


def format_new_signal(s: Signal) -> str:
    lines = [
        f"<b>{_dir_emoji(s.direction)} \u2014 XAUUSD {_dir_str(s.direction)}</b>",
        "",
        f"\u2022 Entry: <code>{s.entry_price:.2f}</code>",
        f"\u2022 Stop Loss: <code>{s.stop_loss:.2f}</code>",
        f"\u2022 TP1: <code>{s.tp1:.2f}</code> (move SL to BE)",
        f"\u2022 TP2: <code>{s.tp2:.2f}</code>",
        "",
        f"Risk: ${s.risk_dollars:.2f} | Size: {s.lot_size} lots",
        f"Time: {s.entry_time.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


def format_signal_closed(s: Signal) -> str:
    status_map = {
        SignalStatus.TP2_HIT: ("\U0001F3AF TP2 HIT", True),
        SignalStatus.TP1_HIT: ("\U00002705 TP1 HIT", True),
        SignalStatus.SL_HIT: ("\U0001F6D1 STOPPED OUT", False),
    }
    label, positive = status_map.get(
        s.status, (f"CLOSED ({s.exit_reason})", (s.current_pnl or 0) >= 0)
    )
    emoji = "\U0001F4C8" if not positive else "\U0001F4C7"
    pnl_line = (
        f"{emoji} P&L: <b>${s.current_pnl:+.2f}</b>"
        if s.current_pnl is not None
        else ""
    )
    rr = f" | R:R: {s.rr_achieved:.2f}" if s.rr_achieved else ""
    lines = [
        f"<b>{label} \u2014 XAUUSD {_dir_str(s.direction)}</b>",
        "",
        f"Entry: <code>{s.entry_price:.2f}</code> \u2192 Exit: <code>{(s.exit_price if s.exit_price is not None else 0):.2f}</code>",
        pnl_line + rr,
        f"Time: {(s.exit_time or s.entry_time).strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)
