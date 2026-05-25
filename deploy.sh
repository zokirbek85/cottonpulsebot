#!/usr/bin/env bash
# =============================================================================
# CottonPulseBot — First-time VPS deployment
# Run once on a fresh server.
# Usage: bash deploy.sh
# =============================================================================
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✔ $*${NC}"; }
info() { echo -e "${CYAN}▶ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
fail() { echo -e "${RED}✘ $*${NC}"; exit 1; }
hr()   { echo -e "${BOLD}──────────────────────────────────────────${NC}"; }

hr
echo -e "${BOLD}  CottonPulseBot — VPS Deployment${NC}"
hr

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
info "Checking prerequisites..."

command -v docker  >/dev/null 2>&1 || fail "Docker not found. Install: https://docs.docker.com/engine/install/"
command -v git     >/dev/null 2>&1 || fail "Git not found. Run: sudo apt install -y git"

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    fail "Docker Compose not found. Install: sudo apt install -y docker-compose-plugin"
fi

ok "Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"
ok "Docker Compose: $COMPOSE_CMD"

# ── 2. Verify we're in the project root ───────────────────────────────────────
[[ -f "docker-compose.yml" ]] || fail "Run this script from the project root (where docker-compose.yml is)"
[[ -f "Dockerfile" ]]         || fail "Dockerfile not found"
[[ -f ".env.example" ]]       || fail ".env.example not found"

# ── 3. Configure .env ─────────────────────────────────────────────────────────
hr
info "Configuring environment..."

if [[ -f ".env" ]]; then
    warn ".env already exists — skipping creation (delete it manually to reconfigure)"
else
    cp .env.example .env
    ok "Created .env from .env.example"
    echo ""
    warn "ACTION REQUIRED: Set your BOT_TOKEN in .env"
    echo ""
    echo "  Open the file:"
    echo -e "    ${BOLD}nano .env${NC}"
    echo ""
    echo "  Set this line:"
    echo -e "    ${BOLD}BOT_TOKEN=<your real token from @BotFather>${NC}"
    echo ""

    read -rp "Press ENTER when you have saved .env, or Ctrl+C to abort..."
fi

# Validate BOT_TOKEN is not placeholder
BOT_TOKEN_VAL=$(grep -E "^BOT_TOKEN=" .env | cut -d= -f2- | tr -d ' ')
if [[ -z "$BOT_TOKEN_VAL" || "$BOT_TOKEN_VAL" == "your_bot_token_here" ]]; then
    fail "BOT_TOKEN is not set in .env. Edit .env and re-run this script."
fi
ok "BOT_TOKEN is set"

# ── 4. Create required directories ────────────────────────────────────────────
info "Creating directories..."
mkdir -p logs
# UID 1000 = botuser inside container (must match Dockerfile)
chown -R 1000:1000 logs
chmod 755 logs
ok "logs/ directory ready (owned by botuser UID 1000)"

# ── 5. Build Docker image ─────────────────────────────────────────────────────
hr
info "Building Docker image (this takes ~3-5 minutes on first run)..."
$COMPOSE_CMD build --no-cache
ok "Docker image built"

# ── 6. Start container ────────────────────────────────────────────────────────
hr
info "Starting CottonPulseBot..."
$COMPOSE_CMD up -d
ok "Container started"

# ── 7. Wait for health check ──────────────────────────────────────────────────
info "Waiting for bot to initialize (up to 45s)..."
HEALTHY=false
for i in $(seq 1 15); do
    sleep 3
    STATUS=$(docker inspect cottonpulsebot --format='{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    if [[ "$STATUS" == "healthy" ]]; then
        HEALTHY=true
        break
    fi
    echo -n "."
done
echo ""

if $HEALTHY; then
    ok "Container is healthy"
else
    warn "Health check pending (container may still be starting — this is normal)"
fi

# ── 8. Verify startup ─────────────────────────────────────────────────────────
hr
info "Checking startup logs..."
sleep 2

if $COMPOSE_CMD logs --tail=30 cottonpulsebot 2>&1 | grep -q "Run polling for bot"; then
    ok "Bot is connected to Telegram and polling"
else
    warn "Could not confirm bot polling — check logs below:"
fi

if $COMPOSE_CMD logs --tail=30 cottonpulsebot 2>&1 | grep -q "Кэш прогрет"; then
    ok "Data cache warmed up (ICE, FX, Yarn loaded)"
fi

# ── 9. Show status ────────────────────────────────────────────────────────────
hr
echo ""
docker ps --filter "name=cottonpulsebot" --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
echo ""
docker stats cottonpulsebot --no-stream --format "  CPU: {{.CPUPerc}}  |  MEM: {{.MemUsage}}  |  MEM%: {{.MemPerc}}"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
hr
echo -e "${GREEN}${BOLD}  Deployment complete!${NC}"
hr
echo ""
echo "  Useful commands:"
echo -e "    ${BOLD}$COMPOSE_CMD logs -f cottonpulsebot${NC}   # watch live logs"
echo -e "    ${BOLD}$COMPOSE_CMD ps${NC}                       # check status"
echo -e "    ${BOLD}bash update.sh${NC}                        # update after code changes"
echo ""
