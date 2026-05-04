-- =============================================================================
-- Validly Autonomous Agent — Database Schema + Seed
-- Runs automatically on first Postgres container start via
-- /docker-entrypoint-initdb.d/init.sql
-- =============================================================================

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- scraped_urls
-- Tracks every URL the crawler has visited so it doesn't re-fetch fresh pages.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scraped_urls (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT        NOT NULL,
    url_hash    TEXT        NOT NULL UNIQUE,  -- sha256 hex of the url
    scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    stale_after TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scraped_urls_stale_after ON scraped_urls (stale_after);

-- ---------------------------------------------------------------------------
-- raw_posts
-- Individual Reddit posts that were collected during a crawl cycle.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_posts (
    id          BIGSERIAL PRIMARY KEY,
    post_id     TEXT        NOT NULL UNIQUE,
    subreddit   TEXT        NOT NULL,
    title       TEXT        NOT NULL,
    comments    JSONB       NOT NULL DEFAULT '[]',
    permalink   TEXT        NOT NULL,
    scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_posts_subreddit   ON raw_posts (subreddit);
CREATE INDEX IF NOT EXISTS idx_raw_posts_scraped_at  ON raw_posts (scraped_at DESC);

-- ---------------------------------------------------------------------------
-- ideas
-- The central store of discovered SaaS opportunities.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ideas (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT        NOT NULL,
    problem          TEXT        NOT NULL,
    opportunity      TEXT        NOT NULL,
    target_customers JSONB       NOT NULL DEFAULT '[]',
    competitors      JSONB       NOT NULL DEFAULT '[]',
    score            FLOAT       NOT NULL DEFAULT 0,
    urgency          FLOAT       NOT NULL DEFAULT 0,
    verdict          TEXT        NOT NULL DEFAULT 'Weak',
    sources          JSONB       NOT NULL DEFAULT '[]',
    embedding        vector(1536),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    times_seen       INT         NOT NULL DEFAULT 1,
    sent_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ideas_score      ON ideas (score DESC);
CREATE INDEX IF NOT EXISTS idx_ideas_sent_at    ON ideas (sent_at);
CREATE INDEX IF NOT EXISTS idx_ideas_updated_at ON ideas (updated_at DESC);
-- Approximate nearest-neighbour index for deduplication via cosine similarity
CREATE INDEX IF NOT EXISTS idx_ideas_embedding
    ON ideas USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- ---------------------------------------------------------------------------
-- subreddit_queue
-- Priority queue of subreddits the crawler works through.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subreddit_queue (
    id             BIGSERIAL PRIMARY KEY,
    subreddit      TEXT        NOT NULL UNIQUE,
    priority       FLOAT       NOT NULL DEFAULT 5.0,
    last_scraped_at TIMESTAMPTZ,
    times_scraped  INT         NOT NULL DEFAULT 0,
    added_by       TEXT        NOT NULL DEFAULT 'human'  -- 'human' | 'agent'
);

CREATE INDEX IF NOT EXISTS idx_subreddit_queue_priority ON subreddit_queue (priority DESC, last_scraped_at NULLS FIRST);

-- ---------------------------------------------------------------------------
-- agent_runs
-- Audit log for every crawler / digest execution.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    agent_type      TEXT        NOT NULL,   -- 'crawler' | 'digest'
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    context_summary TEXT,
    actions_taken   JSONB       NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_type  ON agent_runs (agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_runs_started_at  ON agent_runs (started_at DESC);

-- ---------------------------------------------------------------------------
-- Seed: 30 high-signal subreddits
-- ---------------------------------------------------------------------------
INSERT INTO subreddit_queue (subreddit, priority, added_by) VALUES
    ('entrepreneur',        9.5, 'human'),
    ('SaaS',                9.5, 'human'),
    ('startups',            9.0, 'human'),
    ('smallbusiness',       8.8, 'human'),
    ('indiehackers',        8.8, 'human'),
    ('sideproject',         8.5, 'human'),
    ('ProductHunt',         8.5, 'human'),
    ('Nocode',              8.0, 'human'),
    ('freelance',           7.8, 'human'),
    ('digitalnomad',        7.5, 'human'),
    ('webdev',              7.5, 'human'),
    ('programming',         7.0, 'human'),
    ('devops',              7.0, 'human'),
    ('datascience',         7.0, 'human'),
    ('MachineLearning',     7.0, 'human'),
    ('artificial',          6.8, 'human'),
    ('ChatGPT',             6.8, 'human'),
    ('automation',          7.2, 'human'),
    ('productivity',        7.0, 'human'),
    ('marketing',           6.8, 'human'),
    ('ecommerce',           6.8, 'human'),
    ('agency',              6.5, 'human'),
    ('consulting',          6.5, 'human'),
    ('accounting',          6.0, 'human'),
    ('legaladvice',         6.0, 'human'),
    ('CustomerSuccess',     6.5, 'human'),
    ('projectmanagement',   6.5, 'human'),
    ('recruiting',          6.0, 'human'),
    ('humanresources',      6.0, 'human'),
    ('ycombinator',         8.0, 'human')
ON CONFLICT (subreddit) DO NOTHING;
