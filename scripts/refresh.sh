#!/usr/bin/env bash
# Weekly refresh: conditional re-download of every source, then the full pipeline.
# LADBS republishes wholesale each week (a 304 costs nothing when unchanged); the BOE
# table and its geometry service refresh daily. Safe to run from cron; uses flock so two
# runs never overlap. Logs to data/logs/refresh-<date>.log.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
exec 9>data/logs/.refresh.lock
flock -n 9 || { echo "refresh already running"; exit 0; }
log="data/logs/refresh-$(date +%F).log"
{
  echo "== $(date -Is) acquire"
  uv run pc acquire --refresh
  echo "== $(date -Is) ingest"
  uv run pc ingest
  echo "== $(date -Is) geocode"
  uv run pc geocode
  echo "== $(date -Is) check"
  uv run pc check
  echo "== $(date -Is) analyze"
  uv run pc analyze
  echo "== $(date -Is) export"
  uv run pc export --inline
  echo "== $(date -Is) done"
} 2>&1 | tee -a "$log"
