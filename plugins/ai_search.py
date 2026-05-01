# AI Smart Search — by mn-bots
# Uses Anthropic Claude to understand vague / misspelled queries,
# suggest corrected titles, and re-run the regular filter search.

import asyncio
import json
import logging
import re

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from info import ADMINS, ANTHROPIC_API_KEY, AI_SEARCH_ENABLED
from database.ia_filterdb import get_movie_list, get_search_results
from database.search_logs_db import log_search

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─── Anthropic helpers ───────────────────────────────────────────────────────

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_HEADERS = {
    "Content-Type":      "application/json",
    "x-api-key":         "",          # filled at call time
    "anthropic-version": "2023-06-01",
}

_SEARCH_SYSTEM = """You are an intelligent search engine for a Telegram auto filter bot.

Your job is to understand user intent and return the most relevant file results
even if the query is incomplete, misspelled, or vague.

DATABASE:
You have access to a list of files (provided in the user message).
Each entry is a raw filename from the media library.

INSTRUCTIONS:
1. Understand intent — correct spelling, expand abbreviations
   (e.g. "kgf2" → "KGF Chapter 2"), detect language / quality preference.
2. Semantic matching — match meaning, not just keywords
   (e.g. "vijay police movie" → "Theri").
3. Return up to 5 distinct movie/show names ranked by relevance.
4. If nothing clearly matches, suggest the closest alternatives.
5. Avoid duplicates — merge the same title at different qualities.

OUTPUT ONLY valid JSON — no markdown fences, no explanation.

Format when results found:
[
  {"movie_name": "...", "year": "...", "language": "...",
   "available_qualities": ["480p","720p","1080p"]}
]

Format when NOT found:
{"not_found": true, "suggestions": ["Movie 1", "Movie 2", "Movie 3"]}"""


async def _call_anthropic(user_query: str, file_list: list[str]) -> dict | list | None:
    """Call Anthropic API and return parsed JSON or None on failure."""
    if not ANTHROPIC_API_KEY:
        return None

    sample = file_list[:150]          # keep prompt small
    user_content = (
        f'User search query: "{user_query}"\n\n'
        f"Available files in database (sample):\n"
        + "\n".join(f"- {f}" for f in sample)
        + f'\n\nOUTPUT ONLY JSON. User query: "{user_query}"'
    )

    payload = {
        "model":      "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system":     _SEARCH_SYSTEM,
        "messages":   [{"role": "user", "content": user_content}],
    }
    headers = {**ANTHROPIC_HEADERS, "x-api-key": ANTHROPIC_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ANTHROPIC_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.error("Anthropic API error %s", resp.status)
                    return None
                data = await resp.json()
                raw = data["content"][0]["text"].strip()
                # Strip accidental markdown fences
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
                return json.loads(raw)
    except Exception as e:
        logger.exception("_call_anthropic failed: %s", e)
        return None


# ─── Core AI search logic ─────────────────────────────────────────────────────

async def ai_smart_search(client: Client, msg, original_query: str) -> bool:
    """
    Called when the regular search found nothing.
    Tries to understand the query with AI and suggests corrected results.

    Returns True if we sent a reply, False if we gave up silently.
    """
    if not AI_SEARCH_ENABLED or not ANTHROPIC_API_KEY:
        return False

    # Build a sample of filenames from the DB for AI context
    try:
        file_list = await get_movie_list(limit=200)
    except Exception:
        file_list = []

    thinking_msg = await msg.reply_text(
        "🤖 **AI Search** — analysing your query, please wait…"
    )

    ai_result = await _call_anthropic(original_query, file_list)

    if not ai_result:
        await thinking_msg.delete()
        return False

    # ── Case 1: not_found → suggestions ──────────────────────────────────────
    if isinstance(ai_result, dict) and ai_result.get("not_found"):
        suggestions = ai_result.get("suggestions", [])[:5]
        if not suggestions:
            await thinking_msg.delete()
            return False

        btn = [
            [InlineKeyboardButton(
                text=f"🔍 {name}",
                callback_data=f"aisearch#{name[:55]}"
            )]
            for name in suggestions
        ]
        btn.append([InlineKeyboardButton("✘ Close", callback_data="aisearch#close")])

        await thinking_msg.edit_text(
            "🤖 **AI Search** — No exact match found.\n"
            "Did you mean one of these? 👇",
            reply_markup=InlineKeyboardMarkup(btn),
        )
        # Auto-delete after 3 minutes
        await asyncio.sleep(180)
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        return True

    # ── Case 2: list of matched results ──────────────────────────────────────
    if isinstance(ai_result, list) and ai_result:
        lines = []
        recheck_queries = []

        for item in ai_result[:5]:
            movie  = item.get("movie_name", "")
            year   = item.get("year", "")
            lang   = item.get("language", "")
            quals  = ", ".join(item.get("available_qualities", []))
            if not movie:
                continue
            label = f"🎬 {movie}"
            if year:
                label += f" ({year})"
            if lang:
                label += f" • {lang}"
            if quals:
                label += f" • {quals}"
            lines.append(label)
            recheck_queries.append(movie)

        if not lines:
            await thinking_msg.delete()
            return False

        btn = [
            [InlineKeyboardButton(
                text=f"🔍 {name}",
                callback_data=f"aisearch#{name[:55]}"
            )]
            for name in recheck_queries[:5]
        ]
        btn.append([InlineKeyboardButton("✘ Close", callback_data="aisearch#close")])

        caption = (
            "🤖 **AI Search Results**\n\n"
            + "\n".join(lines)
            + "\n\n_Tap a title to search the database_"
        )

        await thinking_msg.edit_text(
            caption,
            reply_markup=InlineKeyboardMarkup(btn),
        )
        await asyncio.sleep(180)
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        return True

    await thinking_msg.delete()
    return False


# ─── Callback handler for AI suggestion buttons ───────────────────────────────

@Client.on_callback_query(filters.regex(r"^aisearch#"))
async def aisearch_callback(bot, query):
    payload = query.data.split("#", 1)[1]

    if payload == "close":
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer()
        return

    movie_name = payload.strip()
    await query.answer(f"🔍 Searching: {movie_name}", show_alert=False)

    files, offset, total = await get_search_results(movie_name.lower(), offset=0, filter=True)

    if not files:
        await query.answer(
            f"😔 Still no results for «{movie_name}» in the database.",
            show_alert=True,
        )
        return

    # Reuse the existing pm_filter auto_filter flow by injecting a fake spoll tuple
    from plugins.pm_filter import auto_filter
    await auto_filter(bot, query, spoll=(movie_name, files, offset, total))


# ─── /aisearch command (manual override) ─────────────────────────────────────

@Client.on_message(filters.command("aisearch"))
async def aisearch_command(client, message):
    """Allow users to explicitly trigger AI search: /aisearch <query>"""
    if len(message.command) < 2:
        return await message.reply_text(
            "Usage: `/aisearch <movie name>`\n"
            "Example: `/aisearch kgf2 hindi`",
            quote=True,
        )
    query_text = " ".join(message.command[1:])

    # First try the normal DB search
    files, offset, total = await get_search_results(query_text.lower(), offset=0, filter=True)
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id

    if files:
        await log_search(user_id, chat_id, query_text, result_found=True)
        from plugins.pm_filter import auto_filter
        await auto_filter(client, message, spoll=(query_text, files, offset, total))
    else:
        await log_search(user_id, chat_id, query_text, result_found=False)
        await ai_smart_search(client, message, query_text)
