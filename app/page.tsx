"use client";

import { useEffect, useState } from "react";

import type { AnalyzeIdeasResponse, RedditPost, SaasIdea } from "@/lib/types";

const EXAMPLE_SUBREDDITS = ["saas", "smallbusiness", "freelance", "marketing"];
const LOADING_PHASES = [
  "Scraping this week’s top Reddit threads.",
  "Opening the strongest discussions and extracting comment signal.",
  "Grouping complaints into repeatable product opportunities.",
  "Scoring ideas and packaging the final market gaps.",
];
const FINAL_PHASE_BREAKDOWN = [
  "Ranking problems by urgency and buyer pain.",
  "Matching adjacent competitors and weak spots.",
  "Estimating pricing, revenue potential, and go-to-market.",
  "Linking each idea back to source Reddit threads.",
];

function scoreTone(score: number): string {
  if (score >= 8) {
    return "border-emerald-300 bg-emerald-50 text-emerald-700";
  }

  if (score >= 5) {
    return "border-amber-300 bg-amber-50 text-amber-700";
  }

  return "border-rose-300 bg-rose-50 text-rose-700";
}

function Field({
  label,
  value,
}: {
  label: string;
  value: string | string[];
}) {
  const values = Array.isArray(value) ? value.filter(Boolean) : [value];

  if (values.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <p className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
        {label}
      </p>
      <div className="flex flex-wrap gap-2 text-sm leading-6 text-slate-700">
        {Array.isArray(value)
          ? values.map((item) => (
              <span
                key={`${label}-${item}`}
                className="rounded-full border border-slate-200 bg-white px-3 py-1"
              >
                {item}
              </span>
            ))
          : <p>{value}</p>}
      </div>
    </div>
  );
}

function LinkField({
  label,
  items,
}: {
  label: string;
  items: Array<{ title: string; thread_url: string }>;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <p className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
        {label}
      </p>
      <div className="space-y-2 text-sm leading-6 text-slate-700">
        {items.map((item, index) => (
          <a
            key={`${item.thread_url}-${index}`}
            href={item.thread_url}
            target="_blank"
            rel="noreferrer"
            className="block rounded-2xl border border-slate-200 bg-white px-4 py-3 transition hover:border-slate-300 hover:bg-slate-50"
            title={item.title}
          >
            <span className="line-clamp-2 font-medium text-slate-800">{item.title}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

function SourcePill({ title, url }: { title: string; url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="block rounded-2xl border border-slate-200 bg-white px-4 py-3 transition hover:border-slate-300 hover:bg-slate-50"
      title={title}
    >
      <span className="line-clamp-2 text-sm font-medium leading-6 text-slate-800">{title}</span>
    </a>
  );
}

function IdeaCard({ idea }: { idea: SaasIdea }) {
  return (
    <article className="glass-panel rounded-[28px] p-6 sm:p-7">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <p className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
            {idea.verdict} Signal
          </p>
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
            {idea.idea_name}
          </h2>
        </div>
        <div
          className={`inline-flex items-center rounded-full border px-4 py-2 text-sm font-semibold ${scoreTone(
            idea.score,
          )}`}
        >
          Score {idea.score}/10
        </div>
      </div>

      <div className="mt-6 grid gap-5">
        <Field label="Problem" value={idea.problem} />
        <Field label="Demand" value={idea.demand_level} />
        <Field label="Existing Solutions" value={idea.existing_solutions} />
        <Field label="Similar Competitors" value={idea.similar_competitors} />
        <Field label="User Complaints" value={idea.user_complaints} />
        <Field label="Opportunity" value={idea.opportunity} />
        <Field label="Monetization" value={idea.monetization_model} />
        <Field label="Pricing Hint" value={idea.pricing_hint} />
        <Field label="Revenue Potential" value={idea.revenue_potential} />
        <Field label="Go To Market" value={idea.go_to_market} />
        <LinkField label="Source Threads" items={idea.source_threads} />
      </div>
    </article>
  );
}

function ThreadCard({ post }: { post: RedditPost }) {
  return (
    <article className="glass-panel rounded-[24px] p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-slate-500">
            Source Thread
          </p>
          <h3 className="text-lg font-semibold leading-7 text-slate-900">{post.title}</h3>
        </div>
        <a
          href={post.threadUrl}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
        >
          Open Thread
        </a>
      </div>

      <div className="mt-4 space-y-3">
        {post.comments.length > 0 ? post.comments.map((comment) => (
          <div key={`${post.permalink}-${comment}`} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-600">
            {comment}
          </div>
        )) : (
          <p className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-500">
            No comments were extracted for this thread, but the title still contributed to the analysis.
          </p>
        )}
      </div>
    </article>
  );
}

export default function Home() {
  const [subreddit, setSubreddit] = useState("saas");
  const [lastSubreddit, setLastSubreddit] = useState("saas");
  const [result, setResult] = useState<AnalyzeIdeasResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [finalPhaseStep, setFinalPhaseStep] = useState(0);

  useEffect(() => {
    if (!loading) {
      setLoadingStep(0);
      setElapsedSeconds(0);
      return;
    }

    const startedAt = Date.now();
    const interval = window.setInterval(() => {
      const seconds = Math.floor((Date.now() - startedAt) / 1000);
      setElapsedSeconds(seconds);
      setLoadingStep(Math.min(LOADING_PHASES.length - 1, Math.floor(seconds / 4)));
      if (seconds >= 12) {
        setFinalPhaseStep(Math.min(FINAL_PHASE_BREAKDOWN.length - 1, Math.floor((seconds - 12) / 3)));
      }
    }, 800);

    return () => window.clearInterval(interval);
  }, [loading]);

  async function runAnalysis(nextSubreddit = subreddit) {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          subreddit: nextSubreddit.trim().replace(/^r\//i, ""),
        }),
      });

      const payload = (await response.json()) as AnalyzeIdeasResponse & { error?: string };

      if (!response.ok) {
        throw new Error(payload.error ?? "Request failed.");
      }

      setResult(payload);
      setLastSubreddit(nextSubreddit);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unexpected request error.");
    } finally {
      setLoading(false);
    }
  }

  const normalizedSubreddit = subreddit.trim().replace(/^r\//i, "") || "saas";

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 py-8 sm:px-8 lg:px-10">
      <section className="glass-panel relative overflow-hidden rounded-[36px] px-6 py-7 sm:px-8 sm:py-9 lg:px-10">
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-orange-500 via-amber-400 to-sky-500" />
        <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div className="space-y-5">
            <p className="font-mono text-[0.72rem] uppercase tracking-[0.28em] text-slate-500">
              Reddit Scraping + AI Validation
            </p>
            <div className="space-y-4">
              <h1 className="max-w-3xl text-4xl font-semibold tracking-[-0.04em] text-slate-900 sm:text-5xl lg:text-6xl">
                Turn noisy Reddit threads into validated SaaS bets.
              </h1>
              <p className="max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
                Validly scrapes weekly Reddit discussions with Decodo, structures the strongest complaints, and sends them through Insforge AI to surface market gaps, demand, and stronger product angles.
              </p>
            </div>
          </div>

          <div className="rounded-[30px] border border-white/70 bg-[var(--surface-strong)] p-5 shadow-[0_18px_48px_rgba(51,38,21,0.08)]">
            <div className="space-y-4">
              <label className="block space-y-2">
                <span className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
                  Subreddit
                </span>
                <input
                  value={subreddit}
                  onChange={(event) => setSubreddit(event.target.value)}
                  placeholder="saas"
                  className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-base text-slate-900 outline-none transition focus:border-orange-400 focus:ring-4 focus:ring-orange-100"
                />
              </label>

              <div className="flex flex-wrap gap-2">
                {EXAMPLE_SUBREDDITS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setSubreddit(item)}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 transition hover:border-slate-300 hover:bg-slate-50"
                  >
                    r/{item}
                  </button>
                ))}
              </div>

              <div className="flex flex-col gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={() => runAnalysis()}
                  disabled={loading}
                  className="inline-flex items-center justify-center rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
                >
                  {loading ? "Analyzing Reddit signal..." : "Analyze Ideas"}
                </button>

                <button
                  type="button"
                  onClick={() => runAnalysis(lastSubreddit)}
                  disabled={loading}
                  className="inline-flex items-center justify-center rounded-full border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Retry Last Run
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        {[
          "Decodo scrapes the top weekly subreddit page and post threads.",
          "Cheerio structures titles plus top 2–3 comments from up to 8 higher-signal posts.",
          "Insforge scores each opportunity and returns strict JSON only.",
        ].map((item) => (
          <div key={item} className="glass-panel rounded-[24px] px-5 py-4 text-sm leading-6 text-slate-600">
            {item}
          </div>
        ))}
      </section>

      {error ? (
        <section className="glass-panel mt-6 rounded-[28px] border border-rose-200 bg-rose-50/80 p-5 text-rose-700">
          <p className="font-semibold">Analysis failed</p>
          <p className="mt-2 text-sm leading-6">{error}</p>
        </section>
      ) : null}

      {loading ? (
        <section className="glass-panel mt-6 rounded-[30px] p-6 sm:p-7">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-3">
              <p className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
                Analysis In Flight
              </p>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                Working through r/{normalizedSubreddit}
              </h2>
              <p className="max-w-2xl text-base leading-7 text-slate-600">
                {LOADING_PHASES[loadingStep]}
              </p>
            </div>
            <div className="rounded-[24px] border border-slate-200 bg-white px-5 py-4 text-sm text-slate-600">
              <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-slate-500">
                Elapsed
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">{elapsedSeconds}s</p>
            </div>
          </div>

          <div className="mt-6 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-2 rounded-full bg-gradient-to-r from-orange-500 via-amber-400 to-sky-500 transition-all duration-700"
              style={{ width: `${Math.min(92, 24 + loadingStep * 22 + elapsedSeconds * 2)}%` }}
            />
          </div>

          <div className="mt-6 grid gap-3 lg:grid-cols-4">
            {LOADING_PHASES.map((phase, index) => {
              const active = index <= loadingStep;

              return (
                <div
                  key={phase}
                  className={`rounded-[22px] border px-4 py-4 text-sm leading-6 transition ${
                    active
                      ? "border-orange-200 bg-orange-50 text-slate-700"
                      : "border-slate-200 bg-white text-slate-400"
                  }`}
                >
                  <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em]">
                    Step {index + 1}
                  </p>
                  <p className="mt-2">{phase}</p>
                </div>
              );
            })}
          </div>

          <div className="mt-5 rounded-[24px] border border-slate-200 bg-white p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em] text-slate-500">
                  Step 4 Breakdown
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  The last step still does a lot of work, so this breaks it down into smaller visible tasks.
                </p>
              </div>
              <div className="rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-700">
                {loadingStep < 3 ? "Queued" : "Running"}
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {FINAL_PHASE_BREAKDOWN.map((item, index) => {
                const active = loadingStep > 3 || (loadingStep === 3 && index <= finalPhaseStep);

                return (
                  <div
                    key={item}
                    className={`rounded-[20px] border px-4 py-4 text-sm leading-6 transition ${
                      active
                        ? "border-orange-200 bg-orange-50 text-slate-700"
                        : "border-slate-200 bg-slate-50 text-slate-400"
                    }`}
                  >
                    <p className="font-mono text-[0.68rem] uppercase tracking-[0.22em]">
                      4.{index + 1}
                    </p>
                    <p className="mt-2">{item}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      ) : null}

      {result ? (
        <section className="mt-6 space-y-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
                Results
              </p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">
                r/{result.subreddit} produced {result.ideas.length} validated ideas
              </h2>
            </div>
            <p className="text-sm text-slate-500">
              Analyzed {result.source.posts.length} deduplicated source threads and their strongest comments.
            </p>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            {result.ideas.map((idea) => (
              <IdeaCard key={`${idea.idea_name}-${idea.problem}`} idea={idea} />
            ))}
          </div>

          <div className="space-y-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="font-mono text-[0.72rem] uppercase tracking-[0.24em] text-slate-500">
                  Source Threads
                </p>
                <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">
                  Review the original Reddit discussions
                </h2>
              </div>
              <p className="text-sm text-slate-500">
                Open the original threads to validate the signal and dig deeper before building.
              </p>
            </div>

            <div className="grid gap-4 xl:grid-cols-3">
              {result.source.posts.map((post, index) => (
                <SourcePill key={`${post.permalink}-${index}`} title={post.title} url={post.threadUrl} />
              ))}
            </div>
          </div>
        </section>
      ) : (
        <section className="glass-panel mt-6 rounded-[28px] p-6 text-sm leading-7 text-slate-600">
          Enter a subreddit, run the workflow, and the app will return concise SaaS opportunities grounded in real weekly Reddit conversations.
        </section>
      )}
    </main>
  );
}
