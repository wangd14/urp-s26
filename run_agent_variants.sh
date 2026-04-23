#!/usr/bin/env bash
# Run agent_pipeline.py for each selected .sql under queries/ (or explicit paths).
# Each file may declare:   -- @tags: foo, bar, baz
# Use -t / --tag to run only files whose @tags: line contains at least one tag (OR).
# With no -t, all matching .sql in the directory run. Files without @tags: are
# included when -t is unused; with -t they are skipped.
#
# Examples:
#   ./run_agent_variants.sh
#   ./run_agent_variants.sh -n
#   ./run_agent_variants.sh -t low_rating
#   ./run_agent_variants.sh -t escalation
#   ./run_agent_variants.sh -d queries -g 'poc_*.sql'
#   ./run_agent_variants.sh queries/poc_03_gated_assembly.sql
#   ./run_agent_variants.sh -- --model qwen2.5:3b --tools
#   ./run_agent_variants.sh -B   # answer-only (brief) for each file

set -uo pipefail

usage() {
  cat <<'EOF'
Usage: run_agent_variants.sh [options] [file.sql ...]
  -d, --dir DIR      Scan directory (default: ./queries next to this script);
                     relative paths are from the current working directory
  -g, --glob PAT     glob under -d (default: *.sql)
  -t, --tag TAG      Only run .sql with @tags: containing TAG (repeatable, OR)
  -B, --brief        Print only the model reply for each file (passes --brief to agent_pipeline.py; default is full SQL + prompt + output)
  -n, --dry-run      Print commands, do not run
  -h, --help         Help
  --                 Remaining args go to agent_pipeline.py
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT="${SCRIPT_DIR}/agent_pipeline.py"
BRIEF=0
# Default: queries/ beside this script; override with -d
QUERIES_DIR="${SCRIPT_DIR}/queries"
GLOB="*.sql"
DRY=0
TAGS=()
EXPLICIT=()
AGENT_PASS=()
PASS=0
PYTHON="${PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  if [[ "$PASS" -eq 1 ]]; then
    AGENT_PASS+=("$1")
    shift
    continue
  fi
  case "$1" in
    -d|--dir)
      if [[ "${2:0:1}" = / ]]; then
        QUERIES_DIR=$2
      else
        QUERIES_DIR="$(pwd)/$2"
      fi
      shift 2
      ;;
    -g|--glob)
      GLOB="${2:?need glob pattern}"
      shift 2
      ;;
    -t|--tag)
      TAGS+=("$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')")
      shift 2
      ;;
    -B|--brief) BRIEF=1; shift ;;
    -n|--dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) PASS=1; shift ;;
    -*)
      echo "Unknown option: $1 (use -- before arguments for agent_pipeline.py)" >&2
      exit 1
      ;;
    *)
      EXPLICIT+=("$1")
      shift
      ;;
  esac
done

if [[ ! -f "$AGENT" ]]; then
  echo "Missing: $AGENT" >&2
  exit 1
fi

read_file_tags() {
  local f=$1
  local line
  line=$(grep -E -m1 '^--[[:space:]]*@tags?:' "$f" 2>/dev/null || true)
  [[ -n "$line" ]] || { echo ""; return 0; }
  printf '%s' "$line" | sed -E 's/^--[[:space:]]*@tags?:[[:space:]]*//I' | tr ',' ' ' | tr 'A-Z' 'a-z' | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//'
}

should_run() {
  local f=$1
  local ftags
  ftags=$(read_file_tags "$f")
  if [[ ${#TAGS[@]} -eq 0 ]]; then
    return 0
  fi
  if [[ -z "$ftags" ]]; then
    return 1
  fi
  local t req
  for req in "${TAGS[@]}"; do
    for t in $ftags; do
      if [[ "$t" == "$req" ]]; then
        return 0
      fi
    done
  done
  return 1
}

RUNLIST=()
if [[ ${#EXPLICIT[@]} -gt 0 ]]; then
  for f in "${EXPLICIT[@]}"; do
    p=""
    if [[ -f "$f" ]]; then
      p=$f
    elif [[ -f "${SCRIPT_DIR}/$f" ]]; then
      p="${SCRIPT_DIR}/$f"
    else
      echo "Not a file: $f" >&2
      exit 1
    fi
    p="$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
    if should_run "$p"; then
      RUNLIST+=("$p")
    fi
  done
else
  if [[ ! -d "$QUERIES_DIR" ]]; then
    echo "Not a directory: $QUERIES_DIR" >&2
    exit 1
  fi
  while IFS= read -r p; do
    [[ -n "$p" ]] || continue
    if should_run "$p"; then
      RUNLIST+=("$p")
    fi
  done < <(find "$QUERIES_DIR" -maxdepth 1 -type f -name "$GLOB" -print | sort)
fi

if [[ ${#RUNLIST[@]} -eq 0 ]]; then
  echo "No query files to run (see --dir, --glob, -t, and @tags: lines)." >&2
  exit 1
fi

any_fail=0
i=0
n=${#RUNLIST[@]}
for qpath in "${RUNLIST[@]}"; do
  i=$((i + 1))
  printf '\n======== [%d/%d] %s ========\n\n' "$i" "$n" "$(basename "$qpath")"
  extra=("${AGENT_PASS[@]}")
  if [[ "$BRIEF" -eq 1 ]]; then
    extra=("--brief" "${extra[@]}")
  fi
  if [[ ${#extra[@]} -gt 0 ]]; then
    cmd=("$PYTHON" "$AGENT" --query-file "$qpath" "${extra[@]}")
  else
    cmd=("$PYTHON" "$AGENT" --query-file "$qpath")
  fi
  if [[ "$DRY" -eq 1 ]]; then
    printf '%q' "${cmd[0]}"
    c=${#cmd[@]}
    for ((j=1;j<c;j++)); do
      printf ' %q' "${cmd[j]}"
    done
    echo
  else
    if ! "${cmd[@]}"; then
      any_fail=1
    fi
  fi
done
exit "$any_fail"
