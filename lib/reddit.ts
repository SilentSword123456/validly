import * as cheerio from "cheerio";
import type { AnyNode } from "domhandler";

import { getServerEnv } from "@/lib/env";
import type { RedditPost, StructuredRedditData } from "@/lib/types";

const DECODO_ENDPOINT = "https://scraper-api.decodo.com/v2/scrape";
const MAX_POSTS = 8;
const MAX_COMMENTS = 3;
const COMMENT_FETCH_CONCURRENCY = 4;
const MAX_TITLE_LENGTH = 180;
const MAX_COMMENT_LENGTH = 320;

type DecodoStrategy = {
  name: string;
  headers: (apiKey: string) => HeadersInit;
  body: (url: string, proxyPool: string, headlessMode: string) => Record<string, unknown>;
};

function buildDecodoAuthorizationHeader(apiKey: string): string {
  if (/^(Basic|Bearer)\s+/i.test(apiKey)) {
    return apiKey;
  }

  return `Basic ${apiKey}`;
}

const decodoStrategies: DecodoStrategy[] = [
  {
    name: "web-scraping-api-fast",
    headers: (apiKey) => ({ Authorization: buildDecodoAuthorizationHeader(apiKey) }),
    body: (url, proxyPool) => ({
      url,
      proxy_pool: proxyPool,
    }),
  },
  {
    name: "web-scraping-api",
    headers: (apiKey) => ({ Authorization: buildDecodoAuthorizationHeader(apiKey) }),
    body: (url, proxyPool, headlessMode) => ({
      url,
      proxy_pool: proxyPool,
      headless: headlessMode,
    }),
  },
  {
    name: "web-scraping-api-render-flag",
    headers: (apiKey) => ({
      Authorization: buildDecodoAuthorizationHeader(apiKey),
    }),
    body: (url, proxyPool, headlessMode) => ({
      url,
      proxy_pool: proxyPool,
      headless: headlessMode,
      render: true,
    }),
  },
];

let cachedStrategyIndex: number | null = null;

function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function trimText(value: string, maxLength: number): string {
  const normalized = normalizeWhitespace(value);

  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function toAbsoluteRedditUrl(href: string): string {
  if (/^https?:\/\//.test(href)) {
    return href;
  }

  return `https://www.reddit.com${href.startsWith("/") ? href : `/${href}`}`;
}

function toScrapeableRedditUrl(href: string): string {
  const absoluteUrl = toAbsoluteRedditUrl(href);

  try {
    const url = new URL(absoluteUrl);
    url.hostname = "old.reddit.com";
    return url.toString();
  } catch {
    return absoluteUrl.replace("www.reddit.com", "old.reddit.com");
  }
}

function normalizePermalink(href: string): string {
  const absoluteUrl = toAbsoluteRedditUrl(href);

  try {
    const url = new URL(absoluteUrl);
    return `${url.pathname}${url.search}`;
  } catch {
    return absoluteUrl;
  }
}

function extractHtmlCandidate(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();

    if (trimmed.startsWith("<") && trimmed.includes("html")) {
      return trimmed;
    }

    return null;
  }

  if (!value || typeof value !== "object") {
    return null;
  }

  const record = value as Record<string, unknown>;
  const commonKeys = [
    "html",
    "content",
    "body",
    "result",
    "results",
    "data",
    "response",
    "source",
  ];

  for (const key of commonKeys) {
    const html = extractHtmlCandidate(record[key]);
    if (html) {
      return html;
    }
  }

  for (const nestedValue of Object.values(record)) {
    const html = extractHtmlCandidate(nestedValue);
    if (html) {
      return html;
    }
  }

  return null;
}

async function requestDecodo(url: string, strategy: DecodoStrategy): Promise<string> {
  const { decodoApiKey, decodoProxyPool, decodoHeadlessMode, decodoTimeoutMs } = getServerEnv();
  
  console.log(`\n📡 [DECODO REQUEST] Strategy: ${strategy.name}`);
  console.log(`   URL: ${url}`);
  console.log(`   Proxy Pool: ${decodoProxyPool}`);
  console.log(`   Headless Mode: ${decodoHeadlessMode}`);
  console.log(`   Timeout: ${decodoTimeoutMs}ms`);
  
  const requestBody = strategy.body(url, decodoProxyPool, decodoHeadlessMode);
  console.log(`   Request Body:`, JSON.stringify(requestBody, null, 2));
  
  const startTime = Date.now();
  const response = await fetch(DECODO_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/html;q=0.9, */*;q=0.8",
      ...strategy.headers(decodoApiKey),
    },
    body: JSON.stringify(requestBody),
    cache: "no-store",
    signal: AbortSignal.timeout(decodoTimeoutMs),
  });
  
  const elapsed = Date.now() - startTime;
  console.log(`   ⏱️  Response Time: ${elapsed}ms`);
  console.log(`   Status: ${response.status} ${response.statusText}`);

  const rawText = await response.text();
  console.log(`   📦 Response Size: ${rawText.length} bytes`);

  if (!response.ok) {
    console.error(`❌ [DECODO ERROR] Failed with status ${response.status}:`, rawText.slice(0, 500));
    throw new Error(
      `Decodo request failed (${strategy.name}): ${response.status} ${rawText.slice(0, 180)}`,
    );
  }

  if (rawText.trim().startsWith("<")) {
    console.log(`   ✅ Direct HTML response detected`);
    return rawText;
  }

  console.log(`   🔍 Parsing response as JSON...`);
  let payload: unknown = rawText;

  try {
    payload = JSON.parse(rawText);
    console.log(`   ✅ JSON parsed successfully`);
  } catch {
    console.log(`   ⚠️  Not JSON, treating as plain text`);
    payload = rawText;
  }

  console.log(`   🔎 Extracting HTML from payload...`);
  const html = extractHtmlCandidate(payload);

  if (!html) {
    console.error(`   ❌ No HTML found in response structure`);
    throw new Error(`Decodo returned a response without HTML content using ${strategy.name}.`);
  }

  console.log(`   ✅ HTML extracted (${html.length} bytes)`);
  return html;
}

async function scrapeUrl(url: string): Promise<string> {
  console.log(`\n🌐 [SCRAPE URL] Starting scrape for: ${url}`);
  
  const strategyOrder = cachedStrategyIndex === null
    ? decodoStrategies.map((_, index) => index)
    : [cachedStrategyIndex, ...decodoStrategies.map((_, index) => index).filter((index) => index !== cachedStrategyIndex)];

  console.log(`   📋 Strategy Order: [${strategyOrder.map(i => decodoStrategies[i].name).join(", ")}]`);
  if (cachedStrategyIndex !== null) {
    console.log(`   💾 Using cached strategy preference: ${decodoStrategies[cachedStrategyIndex].name}`);
  }

  const failures: string[] = [];

  for (const index of strategyOrder) {
    const strategy = decodoStrategies[index];
    console.log(`\n🔄 [ATTEMPT ${failures.length + 1}/${strategyOrder.length}] Trying: ${strategy.name}`);

    try {
      const html = await requestDecodo(url, strategy);
      cachedStrategyIndex = index;
      console.log(`\n✨ [SUCCESS] Strategy ${strategy.name} worked!`);
      console.log(`   💾 Caching this strategy for future requests`);
      console.log(`   📄 HTML Size: ${html.length} bytes\n`);
      return html;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : "Unknown Decodo error";
      console.error(`\n❌ [FAILED] Strategy ${strategy.name}:`, errorMsg);
      failures.push(errorMsg);
    }
  }

  console.error(`\n💥 [CRITICAL] All strategies exhausted!`);
  console.error(`   Failed attempts: ${failures.length}`);
  throw new Error(`Unable to fetch HTML from Decodo. ${failures.join(" | ")}`);
}

function extractTitleFromNode($: cheerio.CheerioAPI, element: AnyNode): string {
  const node = $(element);
  const titledElement = node.find("h3, .title a, [slot='title'], a[data-click-id='body'], a h3").first();
  const explicitText = trimText(titledElement.text() || node.attr("post-title") || "", MAX_TITLE_LENGTH);

  if (explicitText) {
    return explicitText;
  }

  const linkText = trimText(
    node.find("a[href*='/comments/']").first().text() || node.text(),
    MAX_TITLE_LENGTH,
  );

  return linkText;
}

function extractPermalinkFromNode(
  $: cheerio.CheerioAPI,
  element: AnyNode,
): string | null {
  const node = $(element);
  const permalink =
    node.attr("permalink") ||
    node.attr("content-href") ||
    node.attr("data-permalink") ||
    node.find("a[href*='/comments/']").first().attr("href") ||
    null;

  return permalink ? normalizePermalink(permalink) : null;
}

function extractPostCandidates(html: string): Array<{ title: string; permalink: string }> {
  console.log(`\n🔍 [EXTRACT POSTS] Parsing HTML with Cheerio...`);
  console.log(`   HTML Size: ${html.length} bytes`);
  
  const $ = cheerio.load(html);
  const candidates: Array<{ title: string; permalink: string }> = [];
  const seenPermalinks = new Set<string>();

  const collect = (selector: string) => {
    const matches = $(selector);
    console.log(`   🎯 Selector "${selector}": ${matches.length} matches`);
    
    $(selector).each((_, element) => {
      const title = extractTitleFromNode($, element);
      const permalink = extractPermalinkFromNode($, element);

      if (!title || !permalink) {
        return;
      }

      if (seenPermalinks.has(permalink) || !permalink.includes("/comments/")) {
        return;
      }

      seenPermalinks.add(permalink);
      candidates.push({ title, permalink });
      console.log(`      ✓ Found: "${title.slice(0, 60)}${title.length > 60 ? '...' : ''}"}`);
    });
  };

  console.log(`\n   📦 Collecting posts from structured elements...`);
  collect("shreddit-post");
  collect(".thing");
  collect("article");

  console.log(`\n   🔗 Collecting posts from comment links...`);
  $("a[href*='/comments/']").each((_, element) => {
    const link = $(element);
    const permalink = link.attr("href");
    const title = trimText(link.text(), MAX_TITLE_LENGTH);

    if (!permalink || title.length < 12) {
      return;
    }

    const normalizedPermalink = normalizePermalink(permalink);
    if (seenPermalinks.has(normalizedPermalink)) {
      return;
    }

    seenPermalinks.add(normalizedPermalink);
    candidates.push({ title, permalink: normalizedPermalink });
  });

  console.log(`\n   📊 Extraction Complete:`);
  console.log(`      Total unique posts found: ${candidates.length}`);
  console.log(`      Returning top ${Math.min(candidates.length, MAX_POSTS)} posts`);
  
  return candidates.slice(0, MAX_POSTS);
}

function extractTopComments(html: string): string[] {
  const $ = cheerio.load(html);
  const comments: string[] = [];
  const seen = new Set<string>();
  const selectors = [
    "shreddit-comment",
    "[data-testid='comment']",
    "article[id^='t1_']",
    "div.Comment",
    ".comment",
  ];
  
  console.log(`      🔎 Extracting comments using ${selectors.length} selectors...`);

  $(selectors.join(",")).each((_, element) => {
    const node = $(element);
    const richText = trimText(
      node
        .find("p, [slot='comment'], [data-testid='comment-body'], .md, .richtext, .entry .md")
        .map((__, child) => $(child).text())
        .get()
        .join(" "),
      MAX_COMMENT_LENGTH,
    );

    const fallbackText = trimText(node.text(), MAX_COMMENT_LENGTH);
    const comment = richText || fallbackText;

    if (
      !comment ||
      comment.length < 24 ||
      /^(deleted|removed)$/i.test(comment) ||
      seen.has(comment)
    ) {
      return;
    }

    seen.add(comment);
    comments.push(comment);
  });

  console.log(`      💬 Extracted ${comments.length} unique comments (max ${MAX_COMMENTS})`);
  return comments.slice(0, MAX_COMMENTS);
}

async function fetchCommentsForPost(permalink: string): Promise<string[]> {
  console.log(`\n   🔗 Fetching comments for: ${permalink}`);
  try {
    const html = await scrapeUrl(toScrapeableRedditUrl(permalink));
    const comments = extractTopComments(html);
    console.log(`   ✅ Retrieved ${comments.length} comments`);
    return comments;
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : 'Unknown error';
    console.error(`   ⚠️  Failed to fetch comments: ${errorMsg}`);
    return [];
  }
}

async function mapInBatches<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = [];
  const totalBatches = Math.ceil(items.length / concurrency);

  console.log(`\n🔄 [BATCH PROCESSING] ${items.length} items in ${totalBatches} batches (concurrency: ${concurrency})`);

  for (let index = 0; index < items.length; index += concurrency) {
    const batchNum = Math.floor(index / concurrency) + 1;
    const chunk = items.slice(index, index + concurrency);
    
    console.log(`\n📦 [BATCH ${batchNum}/${totalBatches}] Processing ${chunk.length} items...`);
    const batchStart = Date.now();
    
    const chunkResults = await Promise.all(
      chunk.map((item, offset) => mapper(item, index + offset)),
    );

    const batchElapsed = Date.now() - batchStart;
    console.log(`✅ [BATCH ${batchNum}/${totalBatches}] Complete in ${batchElapsed}ms`);
    
    results.push(...chunkResults);
  }

  console.log(`\n🎉 [ALL BATCHES COMPLETE] ${results.length} results`);
  return results;
}

export async function scrapeReddit(subreddit: string): Promise<string> {
  const normalizedSubreddit = subreddit.trim().replace(/^r\//i, "");
  const url = `https://old.reddit.com/r/${normalizedSubreddit}/top/?t=week`;

  console.log(`\n\n${'='.repeat(80)}`);
  console.log(`🚀 [REDDIT SCRAPER] Starting scrape for r/${normalizedSubreddit}`);
  console.log(`   Target: ${url}`);
  console.log(`   Time: ${new Date().toISOString()}`);
  console.log('='.repeat(80));

  return scrapeUrl(url);
}

export async function structureRedditData(subreddit: string): Promise<StructuredRedditData> {
  console.log(`\n🏗️  [STRUCTURE DATA] Building structured data for r/${subreddit}...`);
  
  const subredditHtml = await scrapeReddit(subreddit);
  const candidates = extractPostCandidates(subredditHtml);

  if (candidates.length === 0) {
    console.error(`\n❌ [ERROR] No posts found!`);
    throw new Error("No Reddit posts were extracted from the scraped HTML.");
  }

  console.log(`\n📝 [POST PROCESSING] Fetching comments for ${candidates.length} posts...`);
  console.log(`   Concurrency: ${COMMENT_FETCH_CONCURRENCY} simultaneous requests`);
  
  const posts = await mapInBatches(candidates, COMMENT_FETCH_CONCURRENCY, async (candidate): Promise<RedditPost> => {
    const comments = await fetchCommentsForPost(candidate.permalink);

    return {
      title: candidate.title,
      comments,
      permalink: candidate.permalink,
      threadUrl: toAbsoluteRedditUrl(candidate.permalink),
    };
  });

  console.log(`\n🔧 [FINAL PROCESSING] Filtering and sorting posts...`);
  console.log(`   Posts before filtering: ${posts.length}`);
  
  const filtered = posts.filter((post) => post.title);
  console.log(`   Posts after filtering: ${filtered.length}`);
  
  const sorted = filtered.sort((left, right) => right.comments.length - left.comments.length);
  console.log(`   Sorted by comment count (top post has ${sorted[0]?.comments.length || 0} comments)`);
  
  const deduped = Array.from(new Map(
    sorted.map((post) => [post.permalink, post]),
  ).values()).slice(0, MAX_POSTS);
  
  console.log(`   Final post count: ${deduped.length}`);
  
  const totalComments = deduped.reduce((sum, post) => sum + post.comments.length, 0);
  
  console.log(`\n✨ [STRUCTURE COMPLETE]`);
  console.log(`   Subreddit: r/${subreddit}`);
  console.log(`   Posts: ${deduped.length}`);
  console.log(`   Total Comments: ${totalComments}`);
  console.log(`   Avg Comments/Post: ${(totalComments / deduped.length).toFixed(1)}`);
  console.log(`   Scraped At: ${new Date().toISOString()}`);
  console.log(`${'='.repeat(80)}\n`);

  return {
    subreddit: subreddit.trim().replace(/^r\//i, ""),
    scrapedAt: new Date().toISOString(),
    posts: deduped,
  };
}