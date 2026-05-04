"""
Validly Autonomous Digest Agent
=================================
Runs continuously and fires once per day at DIGEST_HOUR (UTC).

On each trigger it:
1. Reads all unsent ideas with score >= threshold from Postgres
2. Asks Ollama to reason deeply and pick the single best idea
3. Formats a rich Discord embed with all metadata
4. POSTs the embed to DISCORD_WEBHOOK_URL
5. Marks the idea as sent (sent_at = now())
6. Logs the run to agent_runs

The process never exits — it sleeps until the next trigger time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POSTGRES_URL: str = os.environ.get(
    "POSTGRES_URL", "postgresql://agent:agent@postgres:5432/validly"
)
OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
DISCORD_WEBHOOK_URL: str = os.environ.get("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
DIGEST_HOUR: int = int(os.environ.get("DIGEST_HOUR", "8"))
SCORE_THRESHOLD: float = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DIGEST] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("digest")


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

async def ollama_generate(
    client: httpx.AsyncClient,
    prompt: str,
    system: str = "",
    json_mode: bool = False,
    timeout: float = 300.0,
) -> str:
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"

    while True:
        try:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("Ollama unavailable (%s), retrying in 15 s…", exc)
            await asyncio.sleep(15)
        except Exception as exc:  # noqa: BLE001
            log.error("Ollama error: %s — retrying in 30 s", exc)
            await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def get_pool() -> asyncpg.Pool:
    while True:
        try:
            pool = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=5)
            log.info("Connected to Postgres")
            return pool
        except Exception as exc:  # noqa: BLE001
            log.warning("Postgres not ready (%s), retrying in 5 s…", exc)
            await asyncio.sleep(5)


async def load_candidates(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT id, name, problem, opportunity, target_customers, competitors,
               score, urgency, verdict, sources, times_seen, created_at
        FROM   ideas
        WHERE  sent_at IS NULL
          AND  score >= $1
        ORDER  BY score DESC, urgency DESC, times_seen DESC
        LIMIT  20
        """,
        SCORE_THRESHOLD,
    )
    return [dict(r) for r in rows]


async def mark_sent(pool: asyncpg.Pool, idea_id: int) -> None:
    await pool.execute(
        "UPDATE ideas SET sent_at = now() WHERE id = $1",
        idea_id,
    )


async def log_digest_run(
    pool: asyncpg.Pool,
    actions: list[dict],
) -> None:
    await pool.execute(
        """
        INSERT INTO agent_runs (agent_type, ended_at, actions_taken)
        VALUES ('digest', now(), $1)
        """,
        json.dumps(actions),
    )


# ---------------------------------------------------------------------------
# Digest logic
# ---------------------------------------------------------------------------

async def pick_best_idea(
    client: httpx.AsyncClient, candidates: list[dict]
) -> dict[str, Any] | None:
    """Ask Ollama to reason deeply and pick the single strongest idea."""
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    candidates_text = json.dumps(
        [
            {
                "id": c["id"],
                "name": c["name"],
                "problem": c["problem"],
                "opportunity": c["opportunity"],
                "score": c["score"],
                "urgency": c["urgency"],
                "times_seen": c["times_seen"],
                "verdict": c["verdict"],
            }
            for c in candidates
        ],
        indent=2,
    )

    system = (
        "You are a senior startup analyst picking the single most promising SaaS idea "
        "to highlight today. Consider: score, urgency, novelty, market size, and how many "
        "times it has been seen across different sources (higher = stronger signal). "
        "Return a JSON object with a single key 'chosen_id' set to the integer id of the "
        "best idea. Return ONLY valid JSON."
    )
    response = await ollama_generate(
        client, candidates_text, system=system, json_mode=True, timeout=180.0
    )

    try:
        data = json.loads(response)
        chosen_id = int(data.get("chosen_id", candidates[0]["id"]))
        for c in candidates:
            if c["id"] == chosen_id:
                return c
    except (json.JSONDecodeError, TypeError, ValueError):
        log.warning("Could not parse chosen_id, falling back to top candidate")

    return candidates[0]


async def generate_why_now(
    client: httpx.AsyncClient, idea: dict[str, Any]
) -> str:
    """Generate a 3-sentence 'why now' reasoning for the digest message."""
    prompt = (
        f"SaaS idea: {idea['name']}\n"
        f"Problem: {idea['problem']}\n"
        f"Opportunity: {idea['opportunity']}\n"
        f"Score: {idea['score']:.1f}, Urgency: {idea['urgency']:.1f}, "
        f"Times seen: {idea['times_seen']}\n\n"
        "Write exactly 3 sentences explaining why this is the right opportunity to pursue "
        "RIGHT NOW. Be specific about market timing, current trends, and urgency. "
        "No preamble, just the 3 sentences."
    )
    return await ollama_generate(client, prompt, timeout=120.0)


def build_discord_payload(idea: dict[str, Any], why_now: str) -> dict[str, Any]:
    """Build a Discord webhook payload with a rich embed."""
    sources: list[dict] = []
    try:
        sources = json.loads(idea["sources"]) if isinstance(idea["sources"], str) else idea["sources"]
    except (json.JSONDecodeError, TypeError):
        pass

    competitors: list[str] = []
    try:
        competitors = json.loads(idea["competitors"]) if isinstance(idea["competitors"], str) else idea["competitors"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Score bar
    score_bar = "█" * int(idea["score"]) + "░" * (10 - int(idea["score"]))
    urgency_bar = "█" * int(idea["urgency"]) + "░" * (10 - int(idea["urgency"]))

    fields = [
        {"name": "📋 Problem", "value": idea["problem"][:1024], "inline": False},
        {"name": "💡 Opportunity", "value": idea["opportunity"][:1024], "inline": False},
        {
            "name": "📊 Scores",
            "value": f"**Market:** `{score_bar}` {idea['score']:.1f}/10\n**Urgency:** `{urgency_bar}` {idea['urgency']:.1f}/10",
            "inline": False,
        },
        {"name": "⏰ Why Now", "value": why_now[:1024], "inline": False},
    ]

    if competitors:
        fields.append(
            {
                "name": "🏆 Known Competitors",
                "value": ", ".join(competitors[:8]),
                "inline": False,
            }
        )

    if sources:
        source_lines = [
            f"[{s.get('title', 'Source')}]({s.get('url', '')})"
            for s in sources[:5]
            if s.get("url")
        ]
        if source_lines:
            fields.append(
                {
                    "name": "🔗 Sources",
                    "value": "\n".join(source_lines)[:1024],
                    "inline": False,
                }
            )

    fields.append(
        {
            "name": "📈 Signal Strength",
            "value": f"Seen across **{idea['times_seen']}** source(s) · Verdict: **{idea['verdict']}**",
            "inline": False,
        }
    )

    color = 0x2ECC71 if idea["verdict"] == "Strong" else (0xF39C12 if idea["verdict"] == "Decent" else 0xE74C3C)

    return {
        "username": "Validly Digest 🤖",
        "avatar_url": "https://raw.githubusercontent.com/SilentSword123456/validly/main/public/favicon.ico",
        "embeds": [
            {
                "title": f"🚀 Today's Top SaaS Opportunity: {idea['name']}",
                "color": color,
                "fields": fields,
                "footer": {
                    "text": f"Validly Autonomous Agent • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                },
            }
        ],
    }


async def send_discord(client: httpx.AsyncClient, payload: dict) -> bool:
    """POST the payload to the Discord webhook. Returns True on success."""
    if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/your"):
        log.warning("DISCORD_WEBHOOK_URL not configured, skipping Discord send")
        return False

    try:
        resp = await client.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=30.0,
        )
        if resp.status_code in (200, 204):
            log.info("Discord message sent successfully")
            return True
        log.error("Discord webhook returned %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("Discord send failed: %s", exc)
        return False


def build_telegram_text(idea: dict[str, Any], why_now: str) -> str:
    """Build a Telegram HTML-formatted message for the daily digest."""
    sources: list[dict] = []
    try:
        sources = json.loads(idea["sources"]) if isinstance(idea["sources"], str) else (idea["sources"] or [])
    except (json.JSONDecodeError, TypeError):
        pass

    competitors: list[str] = []
    try:
        competitors = json.loads(idea["competitors"]) if isinstance(idea["competitors"], str) else (idea["competitors"] or [])
    except (json.JSONDecodeError, TypeError):
        pass

    score_bar = "█" * int(idea["score"]) + "░" * (10 - int(idea["score"]))
    urgency_bar = "█" * int(idea["urgency"]) + "░" * (10 - int(idea["urgency"]))

    lines: list[str] = [
        f"🚀 <b>Today's Top SaaS Opportunity</b>",
        f"",
        f"<b>{idea['name']}</b>",
        f"",
        f"📋 <b>Problem</b>",
        f"{idea['problem'][:800]}",
        f"",
        f"💡 <b>Opportunity</b>",
        f"{idea['opportunity'][:800]}",
        f"",
        f"📊 <b>Scores</b>",
        f"Market:  <code>{score_bar}</code> {idea['score']:.1f}/10",
        f"Urgency: <code>{urgency_bar}</code> {idea['urgency']:.1f}/10",
        f"",
        f"⏰ <b>Why Now</b>",
        f"{why_now[:800]}",
    ]

    if competitors:
        lines += ["", f"🏆 <b>Competitors</b>", ", ".join(competitors[:8])]

    if sources:
        source_lines = [
            f'• <a href="{s["url"]}">{s.get("title", "Source")[:60]}</a>'
            for s in sources[:5]
            if s.get("url")
        ]
        if source_lines:
            lines += ["", "🔗 <b>Sources</b>"] + source_lines

    lines += [
        "",
        f"📈 Seen <b>{idea['times_seen']}</b> time(s) · Verdict: <b>{idea['verdict']}</b>",
        f"<i>Validly Autonomous Agent · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>",
    ]

    return "\n".join(lines)


async def send_telegram(client: httpx.AsyncClient, text: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured, skipping Telegram send")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = await client.post(url, json=payload, timeout=30.0)
        if resp.status_code == 200:
            log.info("Telegram message sent successfully")
            return True
        log.error("Telegram API returned %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("Telegram send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------

def seconds_until_next_trigger(hour: int) -> float:
    """Return the number of seconds until the next occurrence of `hour:00 UTC`."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_digest(pool: asyncpg.Pool, client: httpx.AsyncClient) -> None:
    """Execute one digest cycle."""
    log.info("Digest cycle starting…")
    actions: list[dict] = []

    candidates = await load_candidates(pool)
    log.info("Found %d unsent candidates with score >= %.1f", len(candidates), SCORE_THRESHOLD)
    actions.append({"action": "loaded_candidates", "count": len(candidates)})

    if not candidates:
        log.info("No candidates to digest today")
        await log_digest_run(pool, actions)
        return

    best = await pick_best_idea(client, candidates)
    if not best:
        log.warning("No best idea selected")
        await log_digest_run(pool, actions)
        return

    log.info("Selected idea: '%s' (score=%.1f)", best["name"], best["score"])
    actions.append({"action": "selected_idea", "id": best["id"], "name": best["name"]})

    why_now = await generate_why_now(client, best)
    log.info("Generated why-now reasoning")

    discord_payload = build_discord_payload(best, why_now)
    telegram_text = build_telegram_text(best, why_now)

    discord_sent = await send_discord(client, discord_payload)
    telegram_sent = await send_telegram(client, telegram_text)
    sent = discord_sent or telegram_sent

    if sent:
        await mark_sent(pool, best["id"])
        log.info("Marked idea id=%d as sent", best["id"])
    if discord_sent:
        actions.append({"action": "sent_discord", "idea_id": best["id"]})
    if telegram_sent:
        actions.append({"action": "sent_telegram", "idea_id": best["id"]})
    if not sent:
        actions.append({"action": "all_notifications_skipped_or_failed", "idea_id": best["id"]})

    await log_digest_run(pool, actions)
    log.info("Digest cycle complete")


async def main() -> None:
    log.info("Digest agent starting… (fires at %02d:00 UTC daily)", DIGEST_HOUR)
    pool = await get_pool()

    async with httpx.AsyncClient() as client:
        while True:
            wait_secs = seconds_until_next_trigger(DIGEST_HOUR)
            log.info(
                "Next digest in %.0f s (at %02d:00 UTC)",
                wait_secs,
                DIGEST_HOUR,
            )
            await asyncio.sleep(wait_secs)

            try:
                await run_digest(pool, client)
            except Exception as exc:  # noqa: BLE001
                log.error("Digest cycle error: %s", exc, exc_info=True)

            # Sleep 61 seconds to avoid double-firing within the same minute
            await asyncio.sleep(61)


if __name__ == "__main__":
    asyncio.run(main())
