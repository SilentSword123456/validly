#!/usr/bin/env bash
# =============================================================
# Validly — Easy Setup Script
# Sets up Telegram notifications and creates the .env file,
# then optionally starts the Docker Compose stack.
# =============================================================

set -euo pipefail

# --- Colours ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Colour

# --- Helpers ---
info()    { echo -e "${CYAN}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✔${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✖${NC}  $*" >&2; }
prompt()  { echo -e "${BOLD}${CYAN}?${NC}  $*"; }

# Require curl for the Telegram auto-detect step
require_curl() {
    if ! command -v curl &>/dev/null; then
        error "curl is required but not installed. Please install it and re-run setup."
        exit 1
    fi
}

# Require docker / docker compose
require_docker() {
    if ! command -v docker &>/dev/null; then
        error "Docker is not installed. Visit https://docs.docker.com/get-docker/"
        exit 1
    fi
    if ! docker compose version &>/dev/null 2>&1; then
        error "Docker Compose v2 plugin is required. Visit https://docs.docker.com/compose/install/"
        exit 1
    fi
}

# ---------------------------------------------------------------
# Banner
# ---------------------------------------------------------------
clear
echo -e "${BOLD}"
echo "  ██╗   ██╗ █████╗ ██╗     ██╗██████╗ ██╗  ██╗   ██╗"
echo "  ██║   ██║██╔══██╗██║     ██║██╔══██╗██║  ╚██╗ ██╔╝"
echo "  ██║   ██║███████║██║     ██║██║  ██║██║   ╚████╔╝ "
echo "  ╚██╗ ██╔╝██╔══██║██║     ██║██║  ██║██║    ╚██╔╝  "
echo "   ╚████╔╝ ██║  ██║███████╗██║██████╔╝███████╗██║   "
echo "    ╚═══╝  ╚═╝  ╚═╝╚══════╝╚═╝╚═════╝ ╚══════╝╚═╝   "
echo -e "${NC}"
echo -e "${BOLD}  Autonomous SaaS Opportunity Hunter — Easy Setup${NC}"
echo "  ─────────────────────────────────────────────────"
echo ""
echo "  This script will:"
echo "    1. Help you create a Telegram bot for daily digests"
echo "    2. Optionally configure a Webshare static proxy"
echo "    3. Optionally configure a Decodo residential proxy"
echo "    4. Create your .env configuration file"
echo "    5. (Optional) Start the stack with Docker Compose"
echo ""
echo "  No external API keys are required for autonomous mode."
echo "  All AI runs locally via Ollama."
echo ""

require_curl
require_docker

# ---------------------------------------------------------------
# Step 1 — Check for existing .env
# ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    warn ".env already exists at $ENV_FILE"
    echo ""
    prompt "Overwrite it? [y/N]"
    read -r OVERWRITE
    if [[ ! "$OVERWRITE" =~ ^[Yy]$ ]]; then
        info "Keeping existing .env — skipping configuration."
        echo ""
        jump_to_start=true
    else
        jump_to_start=false
    fi
else
    jump_to_start=false
fi

# ---------------------------------------------------------------
# Step 2 — Telegram bot setup
# ---------------------------------------------------------------
TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
DISCORD_WEBHOOK_URL=""
DECODO_API_KEY=""
WEBSHARE_PROXY_URL=""

if [[ "$jump_to_start" != "true" ]]; then

    echo ""
    echo -e "${BOLD}─── Step 1 of 5: Telegram Bot ────────────────────────────${NC}"
    echo ""
    echo "  A Telegram bot sends you the daily best SaaS idea."
    echo "  It only takes ~60 seconds to create one."
    echo ""
    echo -e "  ${BOLD}How to create a bot:${NC}"
    echo "    1. Open Telegram and search for  @BotFather"
    echo "    2. Send:  /newbot"
    echo "    3. Follow the prompts (choose any name/username)"
    echo "    4. Copy the token that looks like:  123456789:ABCdef..."
    echo ""
    prompt "Paste your Telegram bot token here (or press Enter to skip):"
    read -r TELEGRAM_BOT_TOKEN
    TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN// /}"   # strip spaces

    if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
        # Validate the token
        info "Validating token with Telegram…"
        BOT_INFO=$(curl -sf "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || true)
        if echo "$BOT_INFO" | grep -q '"ok":true'; then
            BOT_NAME=$(echo "$BOT_INFO" | grep -o '"username":"[^"]*"' | head -1 | cut -d'"' -f4)
            success "Bot validated: @${BOT_NAME}"
        else
            warn "Could not validate the token. Check it and try again, or press Enter to skip."
            TELEGRAM_BOT_TOKEN=""
        fi
    fi

    if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
        echo ""
        echo -e "  ${BOLD}Now get your Chat ID:${NC}"
        echo "    1. Open Telegram and search for your bot (@${BOT_NAME:-yourbot})"
        echo "    2. Send it any message (e.g.  /start )"
        echo ""
        prompt "Press Enter once you've sent the message…"
        read -r _

        info "Fetching updates from Telegram…"
        for attempt in 1 2 3 4 5; do
            UPDATES=$(curl -sf "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" 2>/dev/null || true)
            TELEGRAM_CHAT_ID=$(echo "$UPDATES" | grep -o '"chat":{"id":[^,}]*' | head -1 | grep -o '[0-9-]*$' || true)
            if [[ -n "$TELEGRAM_CHAT_ID" ]]; then
                break
            fi
            if [[ $attempt -lt 5 ]]; then
                warn "No message found yet — waiting 3 s (attempt $attempt/5)…"
                sleep 3
            fi
        done

        if [[ -n "$TELEGRAM_CHAT_ID" ]]; then
            success "Chat ID detected: $TELEGRAM_CHAT_ID"

            # Send a test message
            TEST_RESULT=$(curl -sf -X POST \
                "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                -H "Content-Type: application/json" \
                -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"✅ <b>Validly is set up!</b>\\n\\nYou'll receive the daily SaaS opportunity digest here.\",\"parse_mode\":\"HTML\"}" \
                2>/dev/null || true)

            if echo "$TEST_RESULT" | grep -q '"ok":true'; then
                success "Test message sent to Telegram! Check your chat."
            else
                warn "Could not send test message (the configuration is still saved)."
            fi
        else
            warn "Could not auto-detect chat ID."
            echo ""
            prompt "Enter your chat ID manually (or press Enter to skip Telegram):"
            read -r TELEGRAM_CHAT_ID
            TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID// /}"
        fi
    fi

    # ---------------------------------------------------------------
    # Step 3 — Discord webhook (optional)
    # ---------------------------------------------------------------
    echo ""
    echo -e "${BOLD}─── Step 2 of 5: Discord Webhook (optional) ──────────────${NC}"
    echo ""
    echo "  You can also send digests to a Discord channel."
    echo "  Skip this if you're using Telegram."
    echo ""
    prompt "Paste your Discord webhook URL (or press Enter to skip):"
    read -r DISCORD_WEBHOOK_URL
    DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL// /}"

    # ---------------------------------------------------------------
    # Step 3 of 5 — Webshare static proxy (optional)
    # ---------------------------------------------------------------
    echo ""
    echo -e "${BOLD}─── Step 3 of 5: Webshare Proxy (optional) ───────────────${NC}"
    echo ""
    echo "  Webshare free static proxies work well for this project."
    echo "  Sign up for a free account at https://webshare.io"
    echo ""
    echo "  In the Webshare dashboard, copy a proxy line and paste it here"
    echo "  in  ip:port:username:password  format, e.g.:"
    echo "    31.59.20.176:6754:vzejosed:t8pmijt0bza0"
    echo ""
    prompt "Paste your Webshare proxy (or press Enter to skip):"
    read -r _ws_input
    _ws_input="${_ws_input// /}"   # strip spaces

    if [[ -n "$_ws_input" ]]; then
        IFS=':' read -r _ws_ip _ws_port _ws_user _ws_pass <<< "$_ws_input"
        if [[ -n "$_ws_ip" && -n "$_ws_port" && -n "$_ws_user" && -n "$_ws_pass" ]]; then
            WEBSHARE_PROXY_URL="http://${_ws_user}:${_ws_pass}@${_ws_ip}:${_ws_port}"
            info "Testing Webshare proxy…"
            _ws_ip_out=$(curl -sf --proxy "$WEBSHARE_PROXY_URL" --max-time 15 \
                "https://ipinfo.io/ip" 2>/dev/null || true)
            if [[ -n "$_ws_ip_out" ]]; then
                success "Proxy works! Outbound IP: ${_ws_ip_out}"
            else
                warn "Could not reach the proxy (timeout or bad credentials)."
                warn "The URL will still be saved — fix it later in .env if needed."
            fi
        else
            warn "Could not parse proxy — expected ip:port:username:password format. Skipping."
        fi
    fi

    # ---------------------------------------------------------------
    # Step 4 of 5 — Decodo residential proxy (optional)
    # ---------------------------------------------------------------
    echo ""
    echo -e "${BOLD}─── Step 4 of 5: Decodo Residential Proxy (optional) ─────${NC}"
    echo ""
    echo "  Decodo routes crawler requests through residential IPs so"
    echo "  Reddit and other sites don't block your server."
    echo "  Sign up (free trial available) at https://decodo.com"
    echo ""
    echo "  Paste your key in  user:password  format, or as the base64 string"
    echo "  Decodo provides (it will be decoded automatically)."
    echo "  e.g.  spuser1abc123:MySecret456"
    echo "  e.g.  VTAwMDA0MDUzMTI6UFdfMTMwNjNiNjljMmVkNDEwNTI3ZmNhNmYwM2MzMmFiMWY5"
    echo ""
    prompt "Decodo API key — or press Enter to skip:"
    read -r DECODO_API_KEY_INPUT
    DECODO_API_KEY="${DECODO_API_KEY_INPUT// /}"   # strip spaces

    if [[ -n "$DECODO_API_KEY" ]]; then
        if [[ "$DECODO_API_KEY" != *:* ]]; then
            # Try to base64-decode — Decodo sometimes gives a single base64 string
            _decoded=$(base64 --decode <<< "$DECODO_API_KEY" 2>/dev/null || true)
            if [[ "$_decoded" == *:* ]]; then
                info "Detected base64-encoded key — decoded to user:password format."
                DECODO_API_KEY="$_decoded"
            else
                warn "Key doesn't look like user:password format and couldn't be base64-decoded — skipping proxy test."
                DECODO_API_KEY=""
            fi
        fi
        if [[ -n "$DECODO_API_KEY" ]]; then
            _decodo_user="${DECODO_API_KEY%%:*}"
            _decodo_pass="${DECODO_API_KEY#*:}"
            info "Testing proxy connection via gate.decodo.com:10002 …"
            _proxy_url="http://${_decodo_user}:${_decodo_pass}@gate.decodo.com:10002"
            _proxy_ip=$(curl -sf --proxy "$_proxy_url" --max-time 15 \
                "https://ipinfo.io/ip" 2>/dev/null || true)
            if [[ -n "$_proxy_ip" ]]; then
                success "Proxy works! Outbound IP: ${_proxy_ip}"
            else
                warn "Could not reach the proxy (timeout or bad credentials)."
                warn "The key will still be saved — fix it later in .env if needed."
            fi
        fi
    fi

    # ---------------------------------------------------------------
    # Step 5 of 5 — Ollama model
    # ---------------------------------------------------------------
    echo ""
    echo -e "${BOLD}─── Step 5 of 5: AI Model ─────────────────────────────────${NC}"
    echo ""
    echo "  Validly uses a local Ollama model for reasoning."
    echo "  The model is downloaded automatically on first start."
    echo ""
    echo "  Options (by RAM requirement):"
    echo "    qwen2.5:14b  — best quality,  ~10 GB RAM  (default)"
    echo "    qwen2.5:7b   — good quality,  ~5 GB RAM"
    echo "    llama3.2:3b  — fast & light,  ~3 GB RAM"
    echo ""
    prompt "Model name [qwen2.5:14b]:"
    read -r OLLAMA_MODEL_INPUT
    OLLAMA_MODEL="${OLLAMA_MODEL_INPUT:-qwen2.5:14b}"

    # Digest hour
    echo ""
    prompt "Daily digest hour in UTC (0–23) [8]:"
    read -r DIGEST_HOUR_INPUT
    DIGEST_HOUR="${DIGEST_HOUR_INPUT:-8}"
    # Validate that DIGEST_HOUR is a number between 0 and 23
    if ! [[ "$DIGEST_HOUR" =~ ^[0-9]+$ ]] || (( DIGEST_HOUR < 0 || DIGEST_HOUR > 23 )); then
        warn "Invalid hour '$DIGEST_HOUR' — defaulting to 8."
        DIGEST_HOUR=8
    fi

    # ---------------------------------------------------------------
    # Write .env
    # ---------------------------------------------------------------
    echo ""
    info "Writing $ENV_FILE …"

    # Generate a random secret key for SearXNG
    SEARXNG_SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 64)

    cat > "$ENV_FILE" <<EOF
# Generated by setup.sh on $(date -u +"%Y-%m-%d %H:%M UTC")
# Edit this file to change settings, then run: docker compose up -d

OLLAMA_MODEL=${OLLAMA_MODEL}

# Telegram
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}

# Discord (optional)
DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}

# Digest
DIGEST_HOUR=${DIGEST_HOUR}

# SearXNG (auto-generated — do not share)
SEARXNG_SECRET_KEY=${SEARXNG_SECRET_KEY}

# Decodo residential proxy (optional — user:password format)
DECODO_API_KEY=${DECODO_API_KEY}

# Webshare static proxy (optional — http://user:pass@ip:port format)
WEBSHARE_PROXY_URL=${WEBSHARE_PROXY_URL}

# Crawler
CRAWL_DELAY_SECONDS=120
SUBREDDIT_STALENESS_DAYS=3
MAX_IDEAS_IN_DB=500
EOF

    success ".env written."

    # Create a minimal .env.local so the nextjs service doesn't fail to start
    ENV_LOCAL="$SCRIPT_DIR/.env.local"
    if [[ ! -f "$ENV_LOCAL" ]]; then
        info "Creating empty .env.local for the Next.js service…"
        cat > "$ENV_LOCAL" <<'EOF'
# Optional: fill in to enable the manual subreddit-analysis feature in the UI.
# Leave blank to run in autonomous-only mode (the crawler + digest will still work).
INSFORGE_API_KEY=
EOF
        success ".env.local written."
    fi
fi

# ---------------------------------------------------------------
# Optionally start Docker Compose
# ---------------------------------------------------------------
echo ""
echo -e "${BOLD}─── Ready to launch ───────────────────────────────────────${NC}"
echo ""
info "The stack includes:"
echo "    • postgres   — database"
echo "    • ollama     — local AI (model download on first run may take a few minutes)"
echo "    • searxng    — private web search"
echo "    • crawler    — continuously hunts for SaaS opportunities"
echo "    • digest     — sends daily digest at ${DIGEST_HOUR:-8}:00 UTC"
echo "    • nextjs     — web UI at http://localhost:3000"
echo ""
prompt "Start the stack now with 'docker compose up -d'? [Y/n]"
read -r START_NOW

if [[ ! "$START_NOW" =~ ^[Nn]$ ]]; then
    echo ""
    info "Starting services… (this may take a while on first run)"
    cd "$SCRIPT_DIR"
    docker compose up -d --build

    echo ""
    info "Pulling Ollama model $OLLAMA_MODEL (this may take a few minutes)..."
    _ollama_wait=0
    until docker exec validly-ollama-1 ollama list > /dev/null 2>&1; do
        sleep 2
        _ollama_wait=$(( _ollama_wait + 2 ))
        if (( _ollama_wait >= 120 )); then
            warn "Timed out waiting for Ollama container — skipping model pull."
            warn "Run manually once the container is healthy:"
            warn "  docker exec validly-ollama-1 ollama pull $OLLAMA_MODEL"
            break
        fi
    done
    if (( _ollama_wait < 120 )); then
        docker exec validly-ollama-1 ollama pull "$OLLAMA_MODEL"
        success "Model ready."
    fi

    echo ""
    success "Stack is starting up in the background."
    echo ""
    echo "  Useful commands:"
    echo "    docker compose logs -f crawler   # watch the crawler"
    echo "    docker compose logs -f digest    # watch the digest agent"
    echo "    docker compose ps                # check service status"
    echo "    docker compose down              # stop everything"
    echo "    docker compose down -v           # stop everything and remove volumes"
    echo ""
    echo "  Web UI:  http://localhost:3000"
    echo ""
    success "Setup complete. Happy hunting! 🚀"
else
    echo ""
    info "Run the following when ready:"
    echo ""
    echo "    docker compose up -d"
    echo ""
    success "Setup complete."
fi
