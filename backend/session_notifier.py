import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Set, Tuple

import requests

from config.settings import TELEGRAM_CONFIG

logger = logging.getLogger(__name__)

SESSION_NAMES = {
    (7, 10): ("LONDON", "\U0001F1EC\U0001F1E7"),
    (12, 16): ("NEW YORK", "\U0001F1FA\U0001F1F8"),
}

_fired: Set[Tuple[str, int]] = set()


def _post_message(text: str) -> bool:
    token = TELEGRAM_CONFIG.bot_token
    chat_id = TELEGRAM_CONFIG.chat_id
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"Telegram send failed [{resp.status_code}]: {resp.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def check_session_opens(session_windows, now: datetime = None) -> list:
    """Return alert texts for sessions whose open hour was just crossed.
    Pure function (injectable clock) so it can be tested deterministically."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # FX market closed Sat/Sun
        return []
    today = now.strftime("%Y-%m-%d")
    alerts = []
    for window in session_windows:
        name, flag = SESSION_NAMES.get(window, (f"SESSION {window}", ""))
        start, end = window
        key = (today, start)
        if key in _fired:
            continue
        if now.hour == start:
            _fired.add(key)
            alerts.append(
                f"\U0001F4F1 @davynci00\n"
                f"{flag} <b>{name} SESSION JUST OPENED</b> \u2014 XAUUSD\n\n"
                f"\u2022 Signal window: <code>{start:02d}:00\u2013{end:02d}:00 GMT</code>\n"
                f"\u2022 Scanning for EMA pullback entries until {end:02d}:00 GMT"
            )
    # prune old day keys
    cutoff = now.strftime("%Y-%m-%d")
    _fired.difference_update(k for k in _fired if k[0] < cutoff)
    return alerts


def announce_if_session_active(session_windows, now: datetime = None) -> Optional[str]:
    """On backend startup/wake: if inside an active session window, announce it."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return None
    today = now.strftime("%Y-%m-%d")
    for window in session_windows:
        name, flag = SESSION_NAMES.get(window, (f"SESSION {window}", ""))
        start, end = window
        key = (today, start)
        if key in _fired:
            continue
        if start <= now.hour < end:
            _fired.add(key)
            return (
                f"\U0001F4F1 @davynci00\n"
                f"{flag} <b>{name} SESSION IS OPEN</b> \u2014 XAUUSD\n\n"
                f"\u2022 Opened at {start:02d}:00 GMT \u2014 ends {end:02d}:00 GMT\n"
                f"\u2022 Scanning for EMA pullback entries"
            )
    return None


async def session_watch_loop(session_windows):
    logger.info("Session watch loop started")
    while True:
        try:
            for text in check_session_opens(session_windows):
                await send_alert(text)
        except Exception as e:
            logger.error(f"Session watch error: {e}")
        await asyncio.sleep(60)


async def send_alert(text: str) -> bool:
    if not TELEGRAM_CONFIG.enabled:
        return False
    result = await asyncio.to_thread(_post_message, text)
    return result
