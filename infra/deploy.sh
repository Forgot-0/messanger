#!/usr/bin/env bash
# Runs ON the production server. Invoked by CI over SSH after lint + tests are green.
#
# Preconditions (already handled by the CI step that calls this):
#   - CWD is the repo root
#   - `git pull --ff-only` has just updated the working tree
#   - `.env` is present on the server (it is gitignored, managed by hand)
#
# Safe to run by hand too:  cd ~/social_github && git pull --ff-only && bash infra/deploy.sh
set -euo pipefail

COMPOSE=(docker compose -f docker-compose.yaml -f docker-compose.monitoring.yml)

echo "==> $(date -Is)  deploying $(git rev-parse --short HEAD) on $(hostname)"

# Both compose files declare `app-network` as external — create it once.
docker network inspect app-network >/dev/null 2>&1 || docker network create app-network


"${COMPOSE[@]}" down
"${COMPOSE[@]}" up -d --build

# `migrations` runs here as a one-shot service (restart: "no"); alembic upgrade is idempotent.

docker image prune -f
docker builder prune -f

"${COMPOSE[@]}" ps
echo "==> deploy done"
