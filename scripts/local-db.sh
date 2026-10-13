#!/usr/bin/env bash
#
# local-db.sh — local PostgreSQL for development.
#
# Brings up the project's Postgres container, ensures the application database
# (and the test database) exist, applies Alembic migrations, and optionally
# seeds demo data. Safe to re-run: it never removes data or volumes.
#
# This is the "each dev works locally" path from TEAM_PLAN.md: one command to
# get a ready database in a Docker Postgres container.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
local-db.sh — local PostgreSQL (Docker) for development.

  ./scripts/local-db.sh          postgres + database + migrations
  ./scripts/local-db.sh --seed   ... and demo data (Ирина/Анна/Борис)
  ./scripts/local-db.sh --help   show this help

Safe to re-run: it never removes data or volumes.
EOF
}

SEED=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) SEED=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

log() { printf '\033[1;34m[local-db]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[local-db] error:\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "docker compose v2 is required"

# Compose reads DB credentials from .env. Only .env.example is committed, so
# create a local .env on first run (it is gitignored).
if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || die ".env.example not found; cannot create .env"
  cp .env.example .env
  log "created .env from .env.example"
fi

get_env() { grep -E "^$1=" .env | head -n1 | cut -d= -f2-; }
PG_USER="$(get_env POSTGRES_USER)"; PG_USER="${PG_USER:-app}"
PG_DB="$(get_env POSTGRES_DB)"; PG_DB="${PG_DB:-agreements}"
TEST_DB="agreements_test"

log "starting Postgres"
docker compose up -d postgres >/dev/null

log "waiting for Postgres to become healthy"
cid="$(docker compose ps -q postgres)"
[[ -n "$cid" ]] || die "postgres container not found"
status=""
for _ in $(seq 1 60); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo unknown)"
  [[ "$status" == "healthy" ]] && break
  sleep 1
done
[[ "$status" == "healthy" ]] || die "Postgres did not become healthy (status: $status)"

ensure_db() {
  local db="$1"
  if docker compose exec -T postgres psql -U "$PG_USER" -d postgres -tAc \
       "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    log "database '$db' already exists"
  else
    docker compose exec -T postgres psql -U "$PG_USER" -d postgres \
      -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$db\"" >/dev/null
    log "created database '$db'"
  fi
}
ensure_db "$PG_DB"
ensure_db "$TEST_DB"

log "applying migrations (alembic upgrade head via the 'migrate' service)"
docker compose run --rm --no-deps migrate

if [[ "$SEED" == "1" ]]; then
  log "seeding demo data"
  docker compose run --rm --no-deps api uv run python -m app.cli seed
fi

log "done"
cat <<EOF

Postgres is up on localhost:5432
    user:      $PG_USER
    database:  $PG_DB
    test DB:   $TEST_DB
    URL:       postgresql://$PG_USER:<POSTGRES_PASSWORD>@localhost:5432/$PG_DB

Run the API against this database:
    cd services/api && uv run uvicorn app.main:app --reload
EOF
