import logging
import os
import json
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = (
    "You are a concise XAUUSD (gold) trading analyst embedded in a charting app. "
    "You receive a live market snapshot: price, session, H1/M15/M5 trends, RSI, "
    "ATR, patterns, support/resistance, and the system's current suggested trade. "
    "Respond in under 180 words. Structure:\n"
    "1) One-line market read\n"
    "2) Key levels and momentum\n"
    "3) Verdict on the suggested trade (agree/disagree + why)\n"
    "4) One risk to watch\n"
    "Be direct and specific with numbers. Never invent data not in the snapshot. "
    "End with a one-line reminder that this is analysis, not financial advice."
)


def ai_configured() -> bool:
    return bool(GEMINI_API_KEY)


def _build_snapshot(chart_data: dict) -> str:
    """Compress /api/chart payload into a compact text snapshot for Gemini."""
    price = chart_data.get("current_price") or {}
    a = chart_data.get("analysis") or {}
    h1, m15, m5 = a.get("h1") or {}, a.get("m15") or {}, a.get("m5") or {}
    st = chart_data.get("suggested_trade") or {}
    sess = chart_data.get("session_info") or {}

    candles = chart_data.get("candles") or []
    recent = candles[-12:]
    recent_str = ", ".join(f"{c['close']:.2f}" for c in recent)

    ind = chart_data.get("indicators") or {}
    rsi_val = ind.get("rsi")
    if isinstance(rsi_val, list):
        rsi_val = rsi_val[-1] if rsi_val else None

    parts = [
        f"Symbol: {chart_data.get('instrument', 'XAUUSD')} | timeframe {chart_data.get('timeframe', '?')}",
        f"Price: bid {price.get('bid')} ask {price.get('ask')} spread {price.get('spread')}",
        f"Session active: {sess.get('is_active')} current: {sess.get('current_session')}",
        f"H1 trend: {h1.get('trend')} strength {h1.get('trend_strength')}",
        f"M15 trend: {m15.get('trend')} RSI {rsi_val} status {m15.get('rsi_status')}",
        f"M5 trend: {m5.get('trend')} pattern {m5.get('pattern')}",
        f"Supports: {[round(x, 1) for x in (ind.get('support_levels') or [])[:4]]}",
        f"Resistances: {[round(x, 1) for x in (ind.get('resistance_levels') or [])[:4]]}",
        f"Trend lines: {[(tl.get('type'), tl.get('end_price'), 'broken' if tl.get('is_broken') else 'intact') for tl in (ind.get('trend_lines') or [])[:3]]}",
        f"Suggested trade: {json.dumps(st) if st else 'none'}",
        f"Last 12 closes: {recent_str}",
    ]
    return "\n".join(p for p in parts if p)


def analyze_chart(chart_data: dict, question: Optional[str] = None) -> dict:
    if not ai_configured():
        return {"error": "GEMINI_API_KEY not configured"}
    snapshot = _build_snapshot(chart_data)
    user_text = snapshot
    if question:
        user_text = f"{snapshot}\n\nUser question: {question}"
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_API_KEY,
                     "Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"parts": [{"text": user_text}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 512},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Gemini error [{resp.status_code}]: {resp.text[:300]}")
            return {"error": f"Gemini API error {resp.status_code}"}
        body = resp.json()
        candidates = body.get("candidates") or []
        if not candidates:
            return {"error": "Gemini returned no candidates"}
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        return {"insight": text, "model": GEMINI_MODEL}
    except Exception as e:
        logger.error(f"Gemini request failed: {e}")
        return {"error": f"AI request failed: {type(e).__name__}"}
