# Validly 🎯

> Turn Reddit discussions into validated SaaS opportunities with AI-powered market research

Validly is a Next.js application that scrapes weekly Reddit discussions from any subreddit and uses AI to identify genuine SaaS opportunities, market gaps, and user pain points.

![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?style=flat&logo=typescript&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=flat&logo=tailwind-css&logoColor=white)

## ✨ Features

- 🔍 **Smart Reddit Scraping** - Fetches top posts and comments from any subreddit
- 🤖 **AI-Powered Analysis** - Uses Insforge AI to identify actionable SaaS ideas
- 📊 **Opportunity Scoring** - Rates each idea with market viability and urgency scores
- 💡 **Market Intelligence** - Extracts target customers, pricing insights, and competitors
- 🎨 **Clean UI** - Beautiful, responsive interface built with Tailwind CSS v4
- ⚡ **Fast & Type-Safe** - Built with Next.js App Router and TypeScript

## 🚀 How It Works

1. **Scrape** - Uses Decodo API to fetch Reddit HTML from top weekly posts
2. **Structure** - Parses titles and top comments with Cheerio
3. **Analyze** - Sends structured data to Insforge AI for market analysis
4. **Score** - Returns validated SaaS ideas with viability scores and market insights

## 📋 Prerequisites

- Node.js 20+ installed
- A [Decodo](https://visit.decodo.com/oNza7b) API key (for Reddit scraping)
- An [Insforge](https://insforge.dev) API key (for AI analysis)

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/validly.git
   cd validly
   ```

2. **Install dependencies**
   ```bash
   npm install
   ```

3. **Set up environment variables**
   
   Create a `.env.local` file in the root directory:
   ```bash
   # Required
   DECODO_API_KEY=your_decodo_api_key_here
   INSFORGE_API_KEY=your_insforge_api_key_here

   # Optional - Customize Insforge configuration
   INSFORGE_URL=https://api.insforge.dev
   INSFORGE_MODEL=openai/gpt-4o-mini
   INSFORGE_RESULTS_TABLE=validated_saas_ideas

   # Optional - Customize Decodo scraping behavior
   DECODO_PROXY_POOL=residential
   DECODO_HEADLESS_MODE=true
   DECODO_TIMEOUT_MS=30000
   INSFORGE_TIMEOUT_MS=60000
   ```

4. **Run the development server**
   ```bash
   npm run dev
   ```

5. **Open your browser**
   
   Navigate to [http://localhost:3000](http://localhost:3000)

## 🔑 Getting API Keys

### Decodo API Key
1. Visit [Decodo](https://visit.decodo.com/oNza7b)
2. Sign up for an account
3. Navigate to your dashboard
4. Copy your API key

### Insforge API Key
1. Visit [insforge.dev](https://insforge.dev)
2. Create an account
3. Go to your project settings
4. Generate and copy your API key

## 📁 Project Structure

```
validly/
├── app/
│   ├── api/
│   │   └── analyze/
│   │       └── route.ts          # API endpoint for Reddit analysis
│   ├── globals.css               # Global styles
│   ├── layout.tsx                # Root layout
│   └── page.tsx                  # Main UI page
├── lib/
│   ├── env.ts                    # Environment variable validation
│   ├── insforge.ts               # Insforge AI integration
│   ├── reddit.ts                 # Reddit scraping & parsing
│   └── types.ts                  # TypeScript type definitions
├── public/                       # Static assets
├── .env.local                    # Environment variables (create this)
├── next.config.ts                # Next.js configuration
├── package.json                  # Dependencies
└── tsconfig.json                 # TypeScript configuration
```

## 🔌 API Endpoint

### `POST /api/analyze`

Analyzes a subreddit for SaaS opportunities.

**Request Body:**
```json
{
  "subreddit": "saas"
}
```

**Response:**
```json
{
  "ideas": [
    {
      "title": "AI-Powered Email Automation for SMBs",
      "description": "...",
      "target_customers": ["Small businesses", "Marketing agencies"],
      "estimated_pricing": "$29-99/month",
      "market_score": 8,
      "urgency_score": 7,
      "competitors": ["Mailchimp", "ActiveCampaign"],
      "source_threads": [
        {
          "title": "Struggling with email automation...",
          "thread_url": "https://reddit.com/r/saas/..."
        }
      ]
    }
  ],
  "posts": [...],
  "metadata": {
    "subreddit": "saas",
    "analyzedAt": "2026-05-02T..."
  }
}
```

## 🏗️ Tech Stack

- **Framework:** Next.js 16 (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS v4
- **Web Scraping:** Cheerio + Decodo API
- **AI Analysis:** Insforge SDK
- **Validation:** Zod
- **JSON Repair:** jsonrepair

## 🎨 Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DECODO_API_KEY` | ✅ Yes | - | Your Decodo API key for Reddit scraping |
| `INSFORGE_API_KEY` | ✅ Yes | - | Your Insforge API key for AI analysis |
| `INSFORGE_URL` | ❌ No | `https://api.insforge.dev` | Insforge API base URL |
| `INSFORGE_MODEL` | ❌ No | `openai/gpt-4o-mini` | AI model to use |
| `INSFORGE_RESULTS_TABLE` | ❌ No | - | Optional database table name |
| `DECODO_PROXY_POOL` | ❌ No | `residential` | Proxy pool type for scraping |
| `DECODO_HEADLESS_MODE` | ❌ No | `true` | Headless browser mode |
| `DECODO_TIMEOUT_MS` | ❌ No | `30000` | Scraping timeout in milliseconds |
| `INSFORGE_TIMEOUT_MS` | ❌ No | `60000` | AI analysis timeout in milliseconds |

## 📝 Available Scripts

```bash
npm run dev      # Start development server
npm run build    # Build for production
npm run start    # Start production server
npm run lint     # Run ESLint
```

## 🤖 Autonomous Agent

Validly ships with a fully autonomous, 24/7 SaaS opportunity hunting system that runs alongside the Next.js app via Docker Compose.

### Architecture

| Service | Role |
|---------|------|
| **postgres** | Postgres 16 + pgvector — stores ideas, embeddings, queue, logs |
| **ollama** | Local AI (runs `OLLAMA_MODEL` from `.env`) |
| **searxng** | Self-hosted web search (no API key required) |
| **crawler** | Python agent — continuous scrape → reason → store loop |
| **digest** | Python cron — fires daily at `DIGEST_HOUR`, picks best idea, sends to Telegram / Discord |
| **nextjs** | The existing Validly app (only public-facing service) |

> **No external API keys are needed for autonomous mode.** All AI reasoning runs locally via Ollama.

### ⚡ Quick start (recommended)

```bash
./setup.sh
```

The interactive script will:
1. Guide you through creating a Telegram bot (~60 seconds)
2. Auto-detect your chat ID
3. Send a test message to confirm everything works
4. Write your `.env` configuration file
5. Start the full stack with `docker compose up -d`

---

### Manual setup

#### 1. Copy and edit the environment file

```bash
cp .env.example .env
```

Key variables to configure:

```bash
# Local AI model (pulled automatically on first start)
OLLAMA_MODEL=qwen2.5:14b

# Telegram bot for the daily idea digest (recommended)
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_CHAT_ID=123456789

# Discord webhook (optional alternative)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN

# What hour (UTC, 0-23) to fire the digest
DIGEST_HOUR=8
```

The existing Next.js variables (`DECODO_API_KEY`, `INSFORGE_API_KEY`, etc.) go in `.env.local` — they are only needed for the manual analysis feature in the web UI.

#### 2. Run with Docker Compose

```bash
docker compose up -d
```

That's it. All services start automatically. Ollama pulls the model on first boot (may take a few minutes). The crawler starts scraping once all services are healthy.

```bash
docker compose logs -f crawler   # watch the crawler
docker compose logs -f digest    # watch the digest agent
docker compose ps                # check service status
```

### Setting up Telegram notifications

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to create a bot
3. Copy the **bot token** (looks like `123456789:ABCdef…`)
4. Send any message to your new bot
5. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` — find `"chat":{"id":…}` — that's your chat ID
6. Add both values to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCdef...
   TELEGRAM_CHAT_ID=123456789
   ```

Every day at `DIGEST_HOUR` UTC the digest agent posts the top-scored SaaS idea with its problem, opportunity, scores, competitors, and a "why now" reasoning.

### Setting up Discord notifications (optional)

1. Open your Discord server → **Server Settings → Integrations → Webhooks**
2. Click **New Webhook**, choose the target channel, copy the **Webhook URL**
3. Add it to `.env`:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
   ```

> You can configure both Telegram and Discord — the digest agent will send to whichever are configured.

### Add subreddits manually

Connect to Postgres and insert into `subreddit_queue`:

```bash
docker compose exec postgres psql -U agent -d validly
```

```sql
INSERT INTO subreddit_queue (subreddit, priority, added_by)
VALUES ('YourSubreddit', 8.0, 'human');
```

Higher `priority` values are visited sooner. The crawler also automatically discovers and enqueues subreddits mentioned in posts.

### View the ideas database

```bash
# Open psql
docker compose exec postgres psql -U agent -d validly

# Top 10 ideas by score
SELECT id, name, score, urgency, verdict, times_seen, sent_at
FROM   ideas
ORDER  BY score DESC
LIMIT  10;

# All unsent high-score ideas
SELECT name, score, verdict FROM ideas
WHERE  sent_at IS NULL AND score >= 7
ORDER  BY score DESC;
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is open source and available under the [MIT License](LICENSE).

## 🙏 Acknowledgments

- [Decodo](https://visit.decodo.com/oNza7b) for powerful web scraping API
- [Insforge](https://insforge.dev) for AI infrastructure
- [Next.js](https://nextjs.org) team for the amazing framework

---

**Built with ❤️ using Next.js, TypeScript, and AI**

`POST /api/analyze`

Request body:

```json
{
	"subreddit": "saas"
}
```

Response shape:

```json
{
	"subreddit": "saas",
	"source": {
		"subreddit": "saas",
		"scrapedAt": "2026-04-13T00:00:00.000Z",
		"posts": [
			{
				"title": "...",
				"comments": ["...", "..."],
				"permalink": "/r/saas/comments/..."
			}
		]
	},
	"ideas": [
		{
			"idea_name": "...",
			"problem": "...",
			"demand_level": "High",
			"existing_solutions": ["..."],
			"user_complaints": ["..."],
			"opportunity": "...",
			"score": 8,
			"verdict": "Strong"
		}
	]
}
```

## Notes

- The Decodo integration is intentionally resilient and tries multiple auth and payload conventions because Decodo account setups can differ.
- Optional Insforge persistence is disabled unless `INSFORGE_RESULTS_TABLE` is set and the target table already exists.
- The route validates both request input and AI output before returning data to the UI.
