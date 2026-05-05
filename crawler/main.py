"""
Validly Autonomous Crawler Agent
=================================
Continuous loop that:
1. Reads its mission & memory from Postgres (agent_runs context_summary)
2. Asks Ollama which subreddit to visit next
3. Scrapes Reddit via Decodo residential proxy + Reddit JSON API (falls back to direct)
4. Finds pain points → searches SearXNG for competitors
5. Asks Ollama to reason about each pain point → store/merge idea in DB
6. Generates Ollama embeddings → uses pgvector cosine similarity to deduplicate
7. Logs every action to agent_runs
8. Waits CRAWL_DELAY_SECONDS then loops forever
9. When context grows too long, summarises, writes to agent_runs, restarts fresh
10. One hour before DIGEST_HOUR, pre-reasons and caches top-5 candidates

The agent NEVER exits permanently. All errors are caught, logged, and retried.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import asyncpg
import httpx
from bs4 import BeautifulSoup
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
SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://searxng:8080")
CRAWL_DELAY: int = int(os.environ.get("CRAWL_DELAY_SECONDS", "120"))
STALENESS_DAYS: int = int(os.environ.get("SUBREDDIT_STALENESS_DAYS", "3"))
MAX_IDEAS: int = int(os.environ.get("MAX_IDEAS_IN_DB", "500"))
DIGEST_HOUR: int = int(os.environ.get("DIGEST_HOUR", "8"))

# Decodo residential proxy credentials (optional — falls back to direct requests)
_decodo_api_key = os.environ.get("DECODO_API_KEY", "")
if _decodo_api_key and ":" in _decodo_api_key:
    _decodo_user, _decodo_pass = _decodo_api_key.split(":", 1)
else:
    _decodo_user = os.environ.get("DECODO_USER", _decodo_api_key)
    _decodo_pass = os.environ.get("DECODO_PASS", "")
DECODO_PROXY: str | None = (
    f"http://{_decodo_user}:{_decodo_pass}@gate.decodo.com:10001"
    if _decodo_user and _decodo_pass
    else None
)

# Context window budget (rough token estimate before summarising)
CONTEXT_TOKEN_BUDGET = 6000
# Cosine similarity threshold below which two ideas are considered duplicates
SIMILARITY_THRESHOLD = 0.12  # lower == more similar (cosine distance)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CRAWLER] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("crawler")


# ---------------------------------------------------------------------------
# Helpers — Ollama
# ---------------------------------------------------------------------------

async def ollama_generate(
    client: httpx.AsyncClient,
    prompt: str,
    system: str = "",
    json_mode: bool = False,
    timeout: float = 300.0,
) -> str:
    """Call Ollama /api/generate with infinite retry on connection errors."""
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3},
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
            data = resp.json()
            return data.get("response", "").strip()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            log.warning("Ollama unavailable (%s), retrying in 15 s…", exc)
            await asyncio.sleep(15)
        except Exception as exc:  # noqa: BLE001
            log.error("Ollama error: %s — retrying in 30 s", exc)
            await asyncio.sleep(30)


async def ollama_embed(client: httpx.AsyncClient, text: str) -> list[float] | None:
    """Generate an embedding vector via Ollama /api/embeddings."""
    try:
        resp = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": OLLAMA_MODEL, "prompt": text[:2000]},
            timeout=120.0,
        )
        resp.raise_for_status()
        embedding: list[float] = resp.json().get("embedding", [])
        if not embedding:
            return None
        # Pad or truncate to exactly 1536 dimensions expected by the DB schema
        if len(embedding) < 1536:
            embedding.extend([0.0] * (1536 - len(embedding)))
        return embedding[:1536]
    except Exception as exc:  # noqa: BLE001
        log.warning("Embedding generation failed: %s", exc)
        return None


async def ollama_ensure_model(client: httpx.AsyncClient) -> None:
    """Pull the configured Ollama model if it is not already present."""
    log.info("Ensuring Ollama model %s is available…", OLLAMA_MODEL)
    while True:
        try:
            resp = await client.post(
                f"{OLLAMA_URL}/api/pull",
                json={"name": OLLAMA_MODEL, "stream": False},
                timeout=600.0,
            )
            resp.raise_for_status()
            log.info("Ollama model %s ready.", OLLAMA_MODEL)
            return
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            log.warning("Ollama not reachable yet (%s), retrying in 15 s…", exc)
            await asyncio.sleep(15)
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to pull Ollama model: %s — retrying in 30 s", exc)
            await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Helpers — Reddit scraping (no external API, plain HTTP)
# ---------------------------------------------------------------------------

async def scrape_subreddit(
    client: httpx.AsyncClient, subreddit: str
) -> list[dict[str, str]]:
    """Fetch top-weekly posts from Reddit JSON API, return list of {title, permalink, id}."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit=10"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ValidlyBot/1.0)"}
    try:
        resp = await client.get(
            url,
            headers=headers,
            follow_redirects=True,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Reddit scrape failed for r/%s: %s", subreddit, exc)
        return []

    posts: list[dict[str, str]] = []
    seen: set[str] = set()
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        permalink = post.get("permalink", "")
        post_id = post.get("id", "")
        title = post.get("title", "")
        if not permalink or permalink in seen or not title:
            continue
        seen.add(permalink)
        posts.append({"title": title, "permalink": permalink, "id": post_id})
        if len(posts) >= 8:
            break

    log.info("Scraped %d posts from r/%s", len(posts), subreddit)
    return posts


async def fetch_comments(
    client: httpx.AsyncClient, permalink: str
) -> list[str]:
    """Fetch top comments for a Reddit post via JSON API."""
    url = f"https://www.reddit.com{permalink}.json?limit=5"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ValidlyBot/1.0)"}
    try:
        resp = await client.get(
            url,
            headers=headers,
            follow_redirects=True,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Comment fetch failed for %s: %s", permalink, exc)
        return []

    comments: list[str] = []
    seen: set[str] = set()
    # Reddit JSON API returns a two-element list; comments are in the second element
    comment_listing = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], dict) else {}
    for child in comment_listing.get("data", {}).get("children", []):
        body = child.get("data", {}).get("body", "")
        text = body.strip()[:400]
        if len(text) < 20 or text in seen:
            continue
        seen.add(text)
        comments.append(text)
        if len(comments) >= 3:
            break

    return comments


# ---------------------------------------------------------------------------
# Helpers — SearXNG
# ---------------------------------------------------------------------------

async def searxng_search(
    client: httpx.AsyncClient, query: str, num_results: int = 5
) -> list[dict[str, str]]:
    """Query SearXNG and return a list of {title, url, content} results."""
    try:
        resp = await client.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", [])[:num_results]:
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:300],
                }
            )
        return results
    except Exception as exc:  # noqa: BLE001
        log.warning("SearXNG search failed for '%s': %s", query, exc)
        return []


async def fetch_page_text(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a web page and return stripped plain text (first 2 000 chars)."""
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ValidlyBot/1.0)"},
            follow_redirects=True,
            timeout=20.0,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:2000]
    except Exception as exc:  # noqa: BLE001
        log.debug("Page fetch failed for %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def get_pool() -> asyncpg.Pool:
    """Create an asyncpg connection pool, retrying until Postgres is ready."""
    while True:
        try:
            pool = await asyncpg.create_pool(POSTGRES_URL, min_size=2, max_size=10)
            log.info("Connected to Postgres")
            return pool
        except Exception as exc:  # noqa: BLE001
            log.warning("Postgres not ready (%s), retrying in 5 s…", exc)
            await asyncio.sleep(5)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


async def is_url_fresh(pool: asyncpg.Pool, url: str) -> bool:
    """Return True when the URL has been scraped and is not yet stale."""
    row = await pool.fetchrow(
        "SELECT stale_after FROM scraped_urls WHERE url_hash=$1",
        url_hash(url),
    )
    if row is None:
        return False
    return row["stale_after"] > datetime.now(timezone.utc)


async def mark_url_scraped(pool: asyncpg.Pool, url: str) -> None:
    stale_after = datetime.now(timezone.utc) + timedelta(days=STALENESS_DAYS)
    await pool.execute(
        """
        INSERT INTO scraped_urls (url, url_hash, scraped_at, stale_after)
        VALUES ($1, $2, now(), $3)
        ON CONFLICT (url_hash) DO UPDATE
            SET scraped_at  = now(),
                stale_after = EXCLUDED.stale_after
        """,
        url,
        url_hash(url),
        stale_after,
    )


async def upsert_raw_post(
    pool: asyncpg.Pool, subreddit: str, post: dict[str, Any]
) -> None:
    post_id = url_hash(post["permalink"])
    await pool.execute(
        """
        INSERT INTO raw_posts (post_id, subreddit, title, comments, permalink)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (post_id) DO UPDATE
            SET comments   = EXCLUDED.comments,
                scraped_at = now()
        """,
        post_id,
        subreddit,
        post["title"],
        json.dumps(post.get("comments", [])),
        post["permalink"],
    )


async def find_similar_idea(
    pool: asyncpg.Pool, embedding: list[float]
) -> dict[str, Any] | None:
    """Return the nearest idea if its cosine distance is below SIMILARITY_THRESHOLD."""
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    row = await pool.fetchrow(
        f"""
        SELECT id, name, problem, opportunity, target_customers, competitors,
               score, urgency, verdict, sources, times_seen,
               embedding <=> '{vec_str}'::vector AS distance
        FROM   ideas
        WHERE  embedding IS NOT NULL
        ORDER  BY embedding <=> '{vec_str}'::vector
        LIMIT  1
        """,
    )
    if row and row["distance"] < SIMILARITY_THRESHOLD:
        return dict(row)
    return None


async def insert_idea(pool: asyncpg.Pool, idea: dict[str, Any]) -> int:
    embedding = idea.get("embedding")
    vec_str = (
        "[" + ",".join(str(v) for v in embedding) + "]" if embedding else None
    )
    row = await pool.fetchrow(
        """
        INSERT INTO ideas
            (name, problem, opportunity, target_customers, competitors,
             score, urgency, verdict, sources, embedding, times_seen)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,
                CASE WHEN $10::text IS NULL THEN NULL ELSE $10::vector END,
                1)
        RETURNING id
        """,
        idea["name"],
        idea["problem"],
        idea["opportunity"],
        json.dumps(idea.get("target_customers", [])),
        json.dumps(idea.get("competitors", [])),
        float(idea.get("score", 0)),
        float(idea.get("urgency", 0)),
        idea.get("verdict", "Weak"),
        json.dumps(idea.get("sources", [])),
        vec_str,
    )
    return row["id"]


async def merge_idea(
    pool: asyncpg.Pool, existing_id: int, idea: dict[str, Any]
) -> None:
    """Merge new evidence into an existing idea, raising times_seen."""
    existing = await pool.fetchrow("SELECT * FROM ideas WHERE id=$1", existing_id)
    if not existing:
        return

    # Merge sources without duplicates
    old_sources: list[dict] = json.loads(existing["sources"])
    new_sources: list[dict] = idea.get("sources", [])
    merged_sources = old_sources.copy()
    existing_urls = {s.get("url") for s in old_sources}
    for s in new_sources:
        if s.get("url") not in existing_urls:
            merged_sources.append(s)

    # Merge competitors
    old_competitors: list[str] = json.loads(existing["competitors"])
    new_competitors: list[str] = idea.get("competitors", [])
    merged_competitors = list(set(old_competitors + new_competitors))

    # Take the higher score
    new_score = max(float(existing["score"]), float(idea.get("score", 0)))
    new_urgency = max(float(existing["urgency"]), float(idea.get("urgency", 0)))

    await pool.execute(
        """
        UPDATE ideas
        SET    sources      = $1,
               competitors  = $2,
               score        = $3,
               urgency      = $4,
               times_seen   = times_seen + 1,
               updated_at   = now()
        WHERE  id = $5
        """,
        json.dumps(merged_sources),
        json.dumps(merged_competitors),
        new_score,
        new_urgency,
        existing_id,
    )
    log.info("Merged idea id=%d (times_seen+1)", existing_id)


async def prune_ideas(pool: asyncpg.Pool) -> None:
    """Keep only MAX_IDEAS rows, deleting lowest-scored unsent ones first."""
    count = await pool.fetchval("SELECT COUNT(*) FROM ideas")
    if count and count > MAX_IDEAS:
        excess = count - MAX_IDEAS
        await pool.execute(
            """
            DELETE FROM ideas
            WHERE id IN (
                SELECT id FROM ideas
                WHERE  sent_at IS NULL
                ORDER  BY score ASC, updated_at ASC
                LIMIT  $1
            )
            """,
            excess,
        )
        log.info("Pruned %d low-score ideas (limit=%d)", excess, MAX_IDEAS)


async def load_memory(pool: asyncpg.Pool) -> str:
    """Load the most recent crawler context summary from agent_runs."""
    row = await pool.fetchrow(
        """
        SELECT context_summary FROM agent_runs
        WHERE  agent_type = 'crawler'
          AND  context_summary IS NOT NULL
        ORDER  BY started_at DESC
        LIMIT  1
        """
    )
    return row["context_summary"] if row else ""


async def load_queue_status(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT subreddit, priority, last_scraped_at, times_scraped
        FROM   subreddit_queue
        ORDER  BY priority DESC, last_scraped_at NULLS FIRST
        LIMIT  20
        """
    )
    return [dict(r) for r in rows]


async def load_recent_ideas_summary(pool: asyncpg.Pool) -> str:
    rows = await pool.fetch(
        """
        SELECT name, score, verdict, times_seen, updated_at
        FROM   ideas
        ORDER  BY updated_at DESC
        LIMIT  10
        """
    )
    if not rows:
        return "No ideas in DB yet."
    lines = [f"- {r['name']} (score={r['score']:.1f}, {r['verdict']}, seen={r['times_seen']})" for r in rows]
    return "\n".join(lines)


async def log_run_start(pool: asyncpg.Pool) -> int:
    row = await pool.fetchrow(
        "INSERT INTO agent_runs (agent_type) VALUES ('crawler') RETURNING id"
    )
    return row["id"]


async def log_run_end(
    pool: asyncpg.Pool,
    run_id: int,
    actions: list[dict],
    summary: str = "",
) -> None:
    await pool.execute(
        """
        UPDATE agent_runs
        SET ended_at        = now(),
            actions_taken   = $1,
            context_summary = $2
        WHERE id = $3
        """,
        json.dumps(actions),
        summary,
        run_id,
    )


async def update_subreddit_scraped(pool: asyncpg.Pool, subreddit: str) -> None:
    await pool.execute(
        """
        UPDATE subreddit_queue
        SET last_scraped_at = now(),
            times_scraped   = times_scraped + 1
        WHERE subreddit = $1
        """,
        subreddit,
    )


async def maybe_add_subreddit(pool: asyncpg.Pool, subreddit: str) -> None:
    await pool.execute(
        """
        INSERT INTO subreddit_queue (subreddit, priority, added_by)
        VALUES ($1, 5.0, 'agent')
        ON CONFLICT (subreddit) DO NOTHING
        """,
        subreddit,
    )


# ---------------------------------------------------------------------------
# Agent decision-making via Ollama
# ---------------------------------------------------------------------------

async def decide_next_subreddit(
    client: httpx.AsyncClient,
    queue: list[dict],
    memory: str,
    recent_ideas: str,
) -> str:
    """Ask Ollama which subreddit to visit next."""
    queue_text = "\n".join(
        f"- r/{r['subreddit']} priority={r['priority']:.1f} "
        f"last_scraped={r['last_scraped_at'] or 'never'}"
        for r in queue
    )
    prompt = f"""You are an autonomous SaaS opportunity hunting agent.

Your memory from previous runs:
{memory or 'No prior memory.'}

Recent ideas discovered:
{recent_ideas}

Subreddit queue (ordered by priority):
{queue_text}

Pick ONE subreddit to scrape next. Choose based on:
1. High priority score
2. Not scraped recently (prefer null or oldest last_scraped)
3. Likely to surface fresh SaaS pain points
4. Variety — avoid repeating the last visited subreddit

Respond with ONLY the subreddit name (no r/ prefix, no explanation)."""

    response = await ollama_generate(client, prompt)
    # Extract just the subreddit name (strip whitespace/r/)
    name = response.strip().lstrip("r/").split()[0].strip()
    # Basic sanity check
    if re.match(r"^[A-Za-z0-9_]{2,50}$", name):
        return name
    # Fallback: pick the highest-priority unscraped
    return queue[0]["subreddit"] if queue else "SaaS"


async def extract_pain_points(
    client: httpx.AsyncClient, posts: list[dict]
) -> list[dict[str, str]]:
    """Ask Ollama to extract actionable pain points from the scraped posts."""
    posts_text = json.dumps(
        [{"title": p["title"], "comments": p.get("comments", [])} for p in posts],
        indent=2,
    )
    system = (
        "You are an expert product researcher. Extract concrete SaaS pain points from "
        "Reddit posts. Return a JSON array of objects with keys: "
        '"pain_point" (string), "search_query" (string for web search to find existing solutions). '
        "Return 3 to 6 pain points. Return ONLY valid JSON, no commentary."
    )
    response = await ollama_generate(
        client, posts_text, system=system, json_mode=True
    )
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return data
        # Ollama sometimes wraps in {"pain_points": [...]}
        for v in data.values():
            if isinstance(v, list):
                return v
    except (json.JSONDecodeError, AttributeError):
        pass
    log.warning("Could not parse pain points JSON, skipping")
    return []


async def reason_about_idea(
    client: httpx.AsyncClient,
    pain_point: str,
    search_results: list[dict],
    page_texts: list[str],
    subreddit: str,
    posts: list[dict],
) -> dict[str, Any] | None:
    """Ask Ollama to decide whether this pain point is a new idea, an update, or nothing."""
    search_text = json.dumps(search_results, indent=2)
    page_excerpt = "\n---\n".join(page_texts[:2])[:1500]

    system = (
        "You are an expert startup analyst. Given a Reddit pain point, web search results "
        "about existing solutions, and page excerpts, decide whether this is a strong SaaS "
        "opportunity. Return a JSON object with keys:\n"
        '"worth_storing": boolean,\n'
        '"name": string (short idea name),\n'
        '"problem": string,\n'
        '"opportunity": string,\n'
        '"target_customers": [string],\n'
        '"competitors": [string],\n'
        '"score": float 0-10,\n'
        '"urgency": float 0-10,\n'
        '"verdict": "Weak"|"Decent"|"Strong",\n'
        '"sources": [{"title":string,"url":string}]\n'
        "Return ONLY valid JSON."
    )
    prompt = (
        f"Pain point from r/{subreddit}: {pain_point}\n\n"
        f"Web search results:\n{search_text}\n\n"
        f"Top page content:\n{page_excerpt}"
    )

    response = await ollama_generate(client, prompt, system=system, json_mode=True)
    try:
        data = json.loads(response)
        if not isinstance(data, dict):
            return None
        if not data.get("worth_storing"):
            return None
        return data
    except (json.JSONDecodeError, AttributeError):
        log.warning("Could not parse idea JSON")
        return None


async def extract_mentioned_subreddits(
    client: httpx.AsyncClient, posts: list[dict]
) -> list[str]:
    """Extract any subreddit names mentioned in post titles/comments."""
    text = " ".join(p["title"] for p in posts) + " ".join(
        c for p in posts for c in p.get("comments", [])
    )
    mentions = re.findall(r"r/([A-Za-z0-9_]{2,50})", text)
    return list({m.lower() for m in mentions if m.lower() not in {"me", "the", "a"}})


async def summarise_context(
    client: httpx.AsyncClient, actions: list[dict]
) -> str:
    """Summarise the current run's actions for the next spawn's memory."""
    actions_text = json.dumps(actions[-30:], indent=2)  # last 30 actions
    prompt = (
        "Summarise the following crawler agent actions into 3-5 sentences. "
        "Focus on: which subreddits were visited, what pain points were found, "
        "what ideas were stored or merged, and any notable patterns.\n\n"
        f"{actions_text}"
    )
    return await ollama_generate(client, prompt, timeout=120.0)


async def pre_reason_top_candidates(
    pool: asyncpg.Pool, client: httpx.AsyncClient
) -> None:
    """Pre-reason top 5 digest candidates and cache scores (called 1h before DIGEST_HOUR)."""
    log.info("Pre-reasoning top digest candidates…")
    rows = await pool.fetch(
        """
        SELECT id, name, problem, opportunity, score, urgency, times_seen, sources
        FROM   ideas
        WHERE  sent_at IS NULL AND score >= 5
        ORDER  BY score DESC, times_seen DESC
        LIMIT  5
        """
    )
    if not rows:
        log.info("No candidates for pre-reasoning")
        return

    for row in rows:
        idea_text = (
            f"Name: {row['name']}\n"
            f"Problem: {row['problem']}\n"
            f"Opportunity: {row['opportunity']}\n"
            f"Score: {row['score']:.1f}, Urgency: {row['urgency']:.1f}, "
            f"Times seen: {row['times_seen']}"
        )
        prompt = (
            "Briefly reassess this SaaS idea's potential right now (2-3 sentences). "
            "Consider market readiness, urgency, and novelty.\n\n"
            f"{idea_text}"
        )
        reasoning = await ollama_generate(client, prompt, timeout=120.0)
        # Persist the reassessed urgency as a small boost so digest picks the best
        await pool.execute(
            "UPDATE ideas SET urgency = LEAST(urgency + 0.5, 10), updated_at = now() WHERE id = $1",
            row["id"],
        )
        log.info("Pre-reasoned candidate: %s — %s", row["name"], reasoning[:80])


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def run_once(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    context_actions: list[dict],
    context_tokens: list[int],
    run_id: int,
) -> None:
    """Execute one crawl cycle."""
    # --- Load memory & queue ---
    memory = await load_memory(pool)
    queue = await load_queue_status(pool)
    recent_ideas = await load_recent_ideas_summary(pool)

    if not queue:
        log.warning("Subreddit queue is empty, sleeping…")
        await asyncio.sleep(60)
        return

    # --- Decide which subreddit to visit ---
    subreddit = await decide_next_subreddit(client, queue, memory, recent_ideas)
    log.info("Selected subreddit: r/%s", subreddit)

    # --- Check staleness ---
    sub_url = f"https://old.reddit.com/r/{subreddit}/top/?t=week"
    if await is_url_fresh(pool, sub_url):
        log.info("r/%s is still fresh, skipping", subreddit)
        context_actions.append({"action": "skip_fresh", "subreddit": subreddit})
        return

    # --- Scrape posts ---
    posts = await scrape_subreddit(client, subreddit)
    if not posts:
        log.warning("No posts scraped from r/%s", subreddit)
        return

    # Fetch comments concurrently (max 4 at a time)
    sem = asyncio.Semaphore(4)

    async def fetch_with_sem(post: dict) -> dict:
        async with sem:
            post["comments"] = await fetch_comments(client, post["permalink"])
            return post

    posts = list(await asyncio.gather(*[fetch_with_sem(p) for p in posts]))

    # Store raw posts
    for post in posts:
        await upsert_raw_post(pool, subreddit, post)

    await mark_url_scraped(pool, sub_url)
    await update_subreddit_scraped(pool, subreddit)

    # Discover mentioned subreddits and add to queue
    mentioned = await extract_mentioned_subreddits(client, posts)
    for sub in mentioned[:5]:
        await maybe_add_subreddit(pool, sub)

    # --- Extract pain points ---
    pain_points = await extract_pain_points(client, posts)
    log.info("Extracted %d pain points from r/%s", len(pain_points), subreddit)

    ideas_stored = 0
    ideas_merged = 0

    for pp in pain_points:
        pain_text: str = pp.get("pain_point", "")
        search_query: str = pp.get("search_query", pain_text)
        if not pain_text:
            continue

        # --- Search for existing solutions ---
        search_results = await searxng_search(client, search_query)

        # Fetch top result page
        page_texts: list[str] = []
        if search_results:
            top_url = search_results[0].get("url", "")
            if top_url:
                page_text = await fetch_page_text(client, top_url)
                if page_text:
                    page_texts.append(page_text)

        # --- Reason about idea ---
        idea = await reason_about_idea(
            client, pain_text, search_results, page_texts, subreddit, posts
        )
        if not idea:
            continue

        # Add source info
        idea.setdefault("sources", [])
        idea["sources"].append(
            {
                "title": f"r/{subreddit}",
                "url": f"https://www.reddit.com/r/{subreddit}/top/?t=week",
            }
        )

        # --- Generate embedding ---
        embed_text = f"{idea['name']} {idea['problem']} {idea['opportunity']}"
        embedding = await ollama_embed(client, embed_text)
        idea["embedding"] = embedding

        # --- Deduplicate via pgvector ---
        if embedding:
            existing = await find_similar_idea(pool, embedding)
            if existing:
                await merge_idea(pool, existing["id"], idea)
                ideas_merged += 1
                context_actions.append(
                    {
                        "action": "merge_idea",
                        "name": idea["name"],
                        "existing_id": existing["id"],
                        "subreddit": subreddit,
                    }
                )
                continue

        # --- Insert new idea ---
        idea_id = await insert_idea(pool, idea)
        ideas_stored += 1
        log.info(
            "Stored idea id=%d '%s' score=%.1f", idea_id, idea["name"], idea.get("score", 0)
        )
        context_actions.append(
            {
                "action": "store_idea",
                "id": idea_id,
                "name": idea["name"],
                "score": idea.get("score", 0),
                "subreddit": subreddit,
            }
        )

    # Prune old low-score ideas if over limit
    await prune_ideas(pool)

    log.info(
        "Cycle complete: r/%s — %d stored, %d merged",
        subreddit, ideas_stored, ideas_merged,
    )
    context_actions.append(
        {
            "action": "crawl_complete",
            "subreddit": subreddit,
            "posts": len(posts),
            "pain_points": len(pain_points),
            "stored": ideas_stored,
            "merged": ideas_merged,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    # Rough context size estimate (1 token ≈ 4 chars)
    context_tokens[0] = sum(len(json.dumps(a)) // 4 for a in context_actions)


async def main() -> None:
    log.info("Crawler agent starting…")
    pool = await get_pool()

    async with httpx.AsyncClient(
        **({"proxy": DECODO_PROXY} if DECODO_PROXY else {})
    ) as client:
        await ollama_ensure_model(client)
        context_actions: list[dict] = []
        context_tokens: list[int] = [0]
        run_id = await log_run_start(pool)
        last_prereason_date: datetime | None = None

        while True:
            try:
                now = datetime.now(timezone.utc)

                # --- Pre-reason candidates 1 h before DIGEST_HOUR ---
                prereason_target = now.replace(
                    hour=DIGEST_HOUR - 1 if DIGEST_HOUR > 0 else 23,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                if (
                    now >= prereason_target
                    and (
                        last_prereason_date is None
                        or last_prereason_date.date() < now.date()
                    )
                ):
                    await pre_reason_top_candidates(pool, client)
                    last_prereason_date = now

                # --- Context window management ---
                if context_tokens[0] > CONTEXT_TOKEN_BUDGET:
                    log.info(
                        "Context budget exceeded (%d tokens), summarising…",
                        context_tokens[0],
                    )
                    summary = await summarise_context(client, context_actions)
                    await log_run_end(pool, run_id, context_actions, summary)
                    # Restart fresh
                    context_actions = []
                    context_tokens[0] = 0
                    run_id = await log_run_start(pool)
                    log.info("Context reset. New run_id=%d", run_id)

                # --- One crawl cycle ---
                await run_once(pool, client, context_actions, context_tokens, run_id)

            except Exception as exc:  # noqa: BLE001
                log.error("Unhandled error in crawl cycle: %s", exc, exc_info=True)
                context_actions.append(
                    {"action": "error", "message": str(exc),
                     "timestamp": datetime.now(timezone.utc).isoformat()}
                )

            log.info("Sleeping %d s before next cycle…", CRAWL_DELAY)
            await asyncio.sleep(CRAWL_DELAY)


if __name__ == "__main__":
    asyncio.run(main())
