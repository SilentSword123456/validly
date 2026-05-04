export interface RedditPost {
  title: string;
  comments: string[];
  permalink: string;
  threadUrl: string;
}

export interface SourceThread {
  title: string;
  thread_url: string;
}

export interface StructuredRedditData {
  subreddit: string;
  scrapedAt: string;
  posts: RedditPost[];
}

export interface SaasIdea {
  idea_name: string;
  problem: string;
  demand_level: "Low" | "Medium" | "High";
  existing_solutions: string[];
  similar_competitors: string[];
  user_complaints: string[];
  opportunity: string;
  monetization_model: string;
  pricing_hint: string;
  revenue_potential: string;
  go_to_market: string;
  score: number;
  verdict: "Weak" | "Decent" | "Strong";
  source_threads: SourceThread[];
}

export interface AnalyzeIdeasResponse {
  subreddit: string;
  source: StructuredRedditData;
  ideas: SaasIdea[];
}