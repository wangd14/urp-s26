#!/usr/bin/env bash
# Apply local init SQL to Postgres: product reviews base data + lab `poc_*` fixtures.
# By default, drops all objects in the `public` schema first (or only `poc_%` tables with
# --poc-only), then re-applies 01/02. Use --no-wipe to run SQL without dropping (will fail
# if objects already exist).
#
# Examples:
#   ./seed_database.sh
#   ./seed_database.sh --docker
#   ./seed_database.sh --poc-only
#   ./seed_database.sh --no-wipe
#   PGPASSWORD=... ./seed_database.sh
#
# Requires: psql (or Docker with the compose stack up for --docker).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

: "${POSTGRES_USER:=poc}"
: "${POSTGRES_PASSWORD:=pocsecret}"
: "${POSTGRES_DB:=pocdb}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_HOST:=127.0.0.1}"

POC_ONLY=0
USE_DOCKER=0
NO_WIPE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      sed -n '1,25p' "$0" | tail -n +2
      exit 0
      ;;
    --poc-only) POC_ONLY=1; shift ;;
    --docker) USE_DOCKER=1; shift ;;
    --no-wipe) NO_WIPE=1; shift ;;
    *)
      echo "Unknown option: $1 (try --help)" >&2
      exit 1
      ;;
  esac
done

if [[ $USE_DOCKER -eq 0 ]] && ! command -v psql &>/dev/null; then
  echo "psql not found. Install the Postgres client, or start the stack and run: $0 --docker" >&2
  exit 1
fi

SEED_BASE="$SCRIPT_DIR/initdb/01_seed.sql"
SEED_POC="$SCRIPT_DIR/initdb/02_poc_stored_injection.sql"
for f in "$SEED_BASE" "$SEED_POC"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing SQL file: $f" >&2
    exit 1
  fi
done

run_file() {
  local sqlfile=$1
  echo "Applying: $sqlfile" >&2
  if [[ $USE_DOCKER -eq 1 ]]; then
    docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec -T postgres \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f - <"$sqlfile"
  elif [[ -n "${DATABASE_URL:-}" ]]; then
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$sqlfile"
  else
    PGPASSWORD="${POSTGRES_PASSWORD}" psql \
      -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -v ON_ERROR_STOP=1 -f "$sqlfile"
  fi
}

# Execute SQL from stdin.
run_raw() {
  echo "Applying: inline SQL" >&2
  if [[ $USE_DOCKER -eq 1 ]]; then
    docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec -T postgres \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f -
  elif [[ -n "${DATABASE_URL:-}" ]]; then
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f -
  else
    PGPASSWORD="${POSTGRES_PASSWORD}" psql \
      -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -v ON_ERROR_STOP=1 -f -
  fi
}

# Remove everything in public (all tables, sequences, etc.) for a full re-seed.
wipe_public_schema() {
  run_raw <<'EOSQL'
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
EOSQL
}

# Drop only tables that initdb/02 creates (keeps base tables from 01).
wipe_poc_tables() {
  run_raw <<'EOSQL'
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public' AND tablename LIKE 'poc\_%' ESCAPE '\'
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
  END LOOP;
END;
$$;
EOSQL
}

if [[ $NO_WIPE -eq 0 ]]; then
  if [[ $POC_ONLY -eq 1 ]]; then
    echo "Dropping public.poc_% tables only..." >&2
    wipe_poc_tables
  else
    echo "Dropping schema public and recreating (removes all tables)..." >&2
    wipe_public_schema
  fi
fi

if [[ $POC_ONLY -eq 1 ]]; then
  run_file "$SEED_POC"
else
  run_file "$SEED_BASE"
  run_file "$SEED_POC"
fi

echo "Done." >&2
