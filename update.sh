#!/usr/bin/env bash
# =============================================================================
# CottonPulseBot — Update script
# Pulls latest code, rebuilds image, restarts container.
# Usage: bash update.sh [--no-rebuild]
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

NO_REBUILD=false
if [[ "${1:-}" == "--no-rebuild" ]]; then
    NO_REBUILD=true
fi

hr
echo -e "${BOLD}  CottonPulseBot — Update${NC}"
echo -e "  $(date '+%Y-%m-%d %H:%M:%S')"
hr

# ── Verify project root ───────────────────────────────────────────────────────
[[ -f "docker-compose.yml" ]] || fail "Run from project root (where docker-compose.yml is)"

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    fail "Docker Compose not found"
fi

# ── 1. Pull latest code ───────────────────────────────────────────────────────
if git rev-parse --git-dir >/dev/null 2>&1; then
    info "Pulling latest code from git..."
    BEFORE=$(git rev-parse --short HEAD)
    git pull --ff-only
    AFTER=$(git rev-parse --short HEAD)

    if [[ "$BEFORE" == "$AFTER" ]]; then
        warn "No new commits (already at $AFTER)"
        if [[ "$NO_REBUILD" == "true" ]]; then
            echo "Nothing to do. Exiting."
            exit 0
        fi
        warn "Proceeding with rebuild anyway (use --no-rebuild to skip)"
    else
        ok "Updated $BEFORE → $AFTER"
        git log --oneline "$BEFORE..HEAD" | sed 's/^/  /'
    fi
else
    warn "Not a git repository — skipping git pull"
    warn "Upload your updated files manually before running this script"
fi

# ── 2. Validate .env ──────────────────────────────────────────────────────────
info "Validating configuration..."
[[ -f ".env" ]] || fail ".env not found — run deploy.sh first"

BOT_TOKEN_VAL=$(grep -E "^BOT_TOKEN=" .env | cut -d= -f2- | tr -d ' ')
[[ -z "$BOT_TOKEN_VAL" || "$BOT_TOKEN_VAL" == "your_bot_token_here" ]] \
    && fail "BOT_TOKEN not set in .env"
ok ".env valid"

mkdir -p logs

# ── 3. Build (unless --no-rebuild) ───────────────────────────────────────────
if [[ "$NO_REBUILD" == "false" ]]; then
    hr
    info "Building new Docker image..."
    START_BUILD=$SECONDS
    $COMPOSE_CMD build --no-cache
    BUILD_TIME=$(( SECONDS - START_BUILD ))
    ok "Image built in ${BUILD_TIME}s"
fi

# ── 4. Restart container ─────────────────────────────────────────────────────
hr
info "Restarting container..."

$COMPOSE_CMD down --timeout 15
ok "Old container stopped"

$COMPOSE_CMD up -d
ok "New container started"

# ── 5. Wait for healthy ───────────────────────────────────────────────────────
info "Waiting for bot to come online (up to 45s)..."
HEALTHY=false
for i in $(seq 1 15); do
    sleep 3
    STATUS=$(docker inspect cottonpulsebot --format='{{.State.Health.Status}}' 2>/dev/null || echo "starting")
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
    warn "Health check still pending — checking logs..."
fi

# ── 6. Verify bot is actually polling ─────────────────────────────────────────
sleep 3
LOGS=$($COMPOSE_CMD logs --tail=40 cottonpulsebot 2>&1)

if echo "$LOGS" | grep -q "Run polling for bot"; then
    ok "Bot is connected to Telegram"
else
    warn "Could not confirm Telegram connection — showing last logs:"
    echo "$LOGS" | tail -20
fi

if echo "$LOGS" | grep -q "Кэш прогрет"; then
    ok "Data cache warmed up"
fi

if echo "$LOGS" | grep -qE "ERROR|CRITICAL"; then
    warn "Errors detected in startup logs:"
    echo "$LOGS" | grep -E "ERROR|CRITICAL" | head -5
fi

# ── 7. Status summary ─────────────────────────────────────────────────────────
hr
docker ps --filter "name=cottonpulsebot" --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
echo ""
docker stats cottonpulsebot --no-stream --format "  CPU: {{.CPUPerc}}  |  MEM: {{.MemUsage}}  |  MEM%: {{.MemPerc}}"
echo ""

hr
echo -e "${GREEN}${BOLD}  Update complete!${NC}"
hr
echo ""
echo "  Commands:"
echo -e "    ${BOLD}$COMPOSE_CMD logs -f cottonpulsebot${NC}   # watch live logs"
echo -e "    ${BOLD}bash update.sh --no-rebuild${NC}           # restart only (no rebuild)"
echo ""
