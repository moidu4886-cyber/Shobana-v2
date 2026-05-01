# AI Analytics — by mn-bots
# Admin dashboard powered by Anthropic Claude.
# Commands: /aistats  /aiinsights

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

import aiohttp
from pyrogram import Client, filters

from info import ADMINS, ANTHROPIC_API_KEY, AI_SEARCH_ENABLED
from database.search_logs_db import get_logs

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─── Anthropic helpers ───────────────────────────────────────────────────────

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_ANALYTICS_SYSTEM = """You are an analytics engine for a Telegram bot admin dashboard.

You receive user activity logs.
Your task:
1. Compute: total_users, active_users_24h, total_searches, success_rate (%).
2. Top 10 searched movies.
3. Top failed searches (high volume, no result).
4. Detect trending movies (rapid search spike) and peak_time (hour range, 24-h format).

OUTPUT ONLY valid JSON — no markdown fences, no explanation.
{
  "total_users": 0,
  "active_users_24h": 0,
  "total_searches": 0,
  "success_rate": 0.0,
  "top_searches": [],
  "failed_searches": [],
  "trending": [],
  "peak_time": "00:00-06:00"
}"""

_INSIGHTS_SYSTEM = """You are a growth consultant for a Telegram movie-file bot.
Based on the analytics JSON provided, generate actionable admin insights.

Consider:
- Which movies should be uploaded urgently (high fail rate).
- Which language has highest demand.
- Which users are most active / valuable.
- Suggestions to increase engagement.

OUTPUT ONLY valid JSON — no markdown fences, no explanation.
{
  "insights": [],
  "recommendations": []
}"""


async def _call_anthropic(system_prompt: str, user_content: str) -> dict | None:
    if not ANTHROPIC_API_KEY:
        return None
    payload = {
        "model":      "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_content}],
    }
    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANTHROPIC_URL, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    logger.error("Anthropic API %s", resp.status)
                    return None
                data = await resp.json()
                raw = data["content"][0]["text"].strip()
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                return json.loads(raw)
    except Exception as e:
        logger.exception("_call_anthropic analytics: %s", e)
        return None


# ─── Local fast-path stats (no API needed) ───────────────────────────────────

def _compute_local_stats(logs: list[dict]) -> dict:
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    total_users       = len({r["user_id"] for r in logs})
    active_users_24h  = len({
        r["user_id"] for r in logs
        if _parse_ts(r.get("timestamp")) >= cutoff
    })
    total_searches    = len(logs)
    found             = sum(1 for r in logs if r.get("result_found"))
    success_rate      = round(found / total_searches * 100, 1) if total_searches else 0.0

    query_counter     = Counter(r["query"] for r in logs)
    fail_counter      = Counter(r["query"] for r in logs if not r.get("result_found"))
    top_searches      = [q for q, _ in query_counter.most_common(10)]
    failed_searches   = [q for q, _ in fail_counter.most_common(10)]

    # Peak hour
    hours = [_parse_ts(r.get("timestamp")).hour for r in logs if _parse_ts(r.get("timestamp"))]
    peak_time = "N/A"
    if hours:
        peak_hour = Counter(hours).most_common(1)[0][0]
        peak_time = f"{peak_hour:02d}:00-{(peak_hour+2)%24:02d}:00"

    return {
        "total_users":      total_users,
        "active_users_24h": active_users_24h,
        "total_searches":   total_searches,
        "success_rate":     success_rate,
        "top_searches":     top_searches,
        "failed_searches":  failed_searches,
        "trending":         [],        # filled by AI if available
        "peak_time":        peak_time,
    }


def _parse_ts(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _format_stats(s: dict) -> str:
    lines = [
        "📊 **AI Analytics Report**\n",
        f"👥 Total users:       `{s['total_users']}`",
        f"🟢 Active (24 h):     `{s['active_users_24h']}`",
        f"🔍 Total searches:    `{s['total_searches']}`",
        f"✅ Success rate:      `{s['success_rate']}%`",
        f"⏰ Peak time:         `{s['peak_time']}`\n",
    ]
    if s.get("top_searches"):
        lines.append("🏆 **Top searches:**")
        lines += [f"  {i+1}. {q}" for i, q in enumerate(s["top_searches"][:10])]
    if s.get("failed_searches"):
        lines.append("\n🚫 **Top failed searches** (upload urgently):")
        lines += [f"  • {q}" for q in s["failed_searches"][:5]]
    if s.get("trending"):
        lines.append("\n🔥 **Trending:**")
        lines += [f"  • {t}" for t in s["trending"][:5]]
    return "\n".join(lines)


def _format_insights(d: dict) -> str:
    lines = ["💡 **AI Insights & Recommendations**\n"]
    for item in d.get("insights", []):
        lines.append(f"📌 {item}")
    if d.get("recommendations"):
        lines.append("\n🚀 **Recommendations:**")
        for item in d["recommendations"]:
            lines.append(f"  ➤ {item}")
    return "\n".join(lines) if len(lines) > 1 else "No insights generated."


# ─── Commands ────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("aistats") & filters.user(ADMINS))
async def aistats_command(client, message):
    """
    /aistats — generate analytics report from search logs.
    Uses local fast-path stats + optional AI enrichment for trending.
    """
    wait = await message.reply_text("⏳ Fetching logs and computing stats…")

    logs = await get_logs(limit=1000)
    if not logs:
        return await wait.edit_text(
            "📭 No search logs found yet.\n"
            "Logs are recorded automatically as users search."
        )

    # Always compute fast local stats first
    stats = _compute_local_stats(logs)

    # Optionally enrich with AI (trending detection)
    if AI_SEARCH_ENABLED and ANTHROPIC_API_KEY:
        ai_stats = await _call_anthropic(
            _ANALYTICS_SYSTEM,
            f"Here are {len(logs)} recent search log entries:\n{json.dumps(logs[:500], default=str)}"
        )
        if isinstance(ai_stats, dict):
            # Merge only the AI-enriched fields
            stats["trending"]       = ai_stats.get("trending", stats["trending"])
            stats["peak_time"]      = ai_stats.get("peak_time", stats["peak_time"])
            stats["top_searches"]   = ai_stats.get("top_searches", stats["top_searches"])
            stats["failed_searches"]= ai_stats.get("failed_searches", stats["failed_searches"])

    await wait.edit_text(_format_stats(stats))


@Client.on_message(filters.command("aiinsights") & filters.user(ADMINS))
async def aiinsights_command(client, message):
    """
    /aiinsights — get actionable AI recommendations from search data.
    """
    if not AI_SEARCH_ENABLED or not ANTHROPIC_API_KEY:
        return await message.reply_text(
            "⚠️ AI features are disabled.\n"
            "Set `ANTHROPIC_API_KEY` and `AI_SEARCH_ENABLED=true` in your env vars."
        )

    wait = await message.reply_text("🤖 Generating AI insights…")

    logs = await get_logs(limit=1000)
    if not logs:
        return await wait.edit_text("📭 No search logs found yet.")

    stats = _compute_local_stats(logs)

    result = await _call_anthropic(
        _INSIGHTS_SYSTEM,
        f"Analytics summary:\n{json.dumps(stats, default=str)}\n\n"
        f"Recent log sample (50 entries):\n{json.dumps(logs[:50], default=str)}"
    )

    if not result:
        return await wait.edit_text("❌ AI insights failed. Check your API key or try later.")

    await wait.edit_text(_format_insights(result))


@Client.on_message(filters.command("aihelp") & filters.user(ADMINS))
async def aihelp_command(client, message):
    await message.reply_text(
        "🤖 **AI Commands** (Admin only)\n\n"
        "`/aisearch <query>` — AI-powered smart search (any user)\n"
        "`/aistats`         — Analytics report from search logs\n"
        "`/aiinsights`      — AI growth recommendations\n\n"
        "**Config vars needed:**\n"
        "`ANTHROPIC_API_KEY` — your Anthropic API key\n"
        "`AI_SEARCH_ENABLED` — set `true` to enable (default: false)\n"
    )
