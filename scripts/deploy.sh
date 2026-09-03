#!/usr/bin/env bash
# Atomic deploy of the atlas page to dronesclub.
#
# Builds data/site/ (the standalone atlas plus the GeoJSON/JSON exports), rsyncs it into
# a fresh timestamped release dir under /var/www/plancheck-releases/, swaps the
# /var/www/plancheck-current symlink atomically (ln -s + mv -T), prunes to KEEP releases.
#
# Usage: scripts/deploy.sh [--no-build] [--no-verify]
set -euo pipefail

exec 9>/tmp/plancheck-deploy.lock
if ! flock -n 9; then
  echo "another deploy is running; waiting…" >&2
  flock 9
fi

HOST=dronesclub
RELEASES=/var/www/plancheck-releases
CURRENT=/var/www/plancheck-current
KEEP=3
SITE_URL=https://plancheck.sorkinlabs.com

repo_root=$(cd "$(dirname "$0")/.." && pwd)
site_dir="$repo_root/data/site"

build=1 verify=1
for arg in "$@"; do
  case "$arg" in
    --no-build) build=0 ;;
    --no-verify) verify=0 ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done

if [[ $build == 1 ]]; then
  echo "==> building data/site"
  mkdir -p "$site_dir/data"
  (cd "$repo_root" && uv run python scripts/build_atlas.py --standalone "$site_dir/index.html")
  cp "$repo_root"/data/export/*.geojson "$repo_root"/data/export/*.json "$site_dir/data/"
fi
[[ -f "$site_dir/index.html" ]] || { echo "error: $site_dir/index.html missing" >&2; exit 1; }

ts=$(date -u +%Y%m%d-%H%M%S)
echo "==> deploying release $ts"
ssh "$HOST" "sudo install -d -o \$(whoami) -g \$(whoami) $RELEASES/$ts"
prev=$(ssh "$HOST" "readlink $CURRENT" || true)
rsync -a ${prev:+--link-dest="$prev"} "$site_dir/" "$HOST:$RELEASES/$ts/"

echo "==> swapping symlink"
ssh "$HOST" "set -e
  sudo ln -sfn $RELEASES/$ts $CURRENT.new
  sudo mv -T $CURRENT.new $CURRENT
  echo \"   current -> \$(readlink $CURRENT)\"
  cd $RELEASES
  ls -1d 2*/ | sort | head -n -$KEEP | while read -r old; do
    echo \"   pruning \$old\"
    sudo rm -rf \"$RELEASES/\$old\"
  done"

live=$(ssh "$HOST" "readlink $CURRENT")
[[ "$live" == "$RELEASES/$ts" ]] || { echo "error: symlink points at $live" >&2; exit 1; }
if [[ $verify == 0 ]]; then
  echo "==> deployed $ts (live-URL check skipped)"; exit 0
fi
echo "==> verifying"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$SITE_URL/?v=$ts")
[[ "$code" == 200 ]] || { echo "error: $SITE_URL/ returned HTTP $code" >&2; exit 1; }
want=$(python3 -c "import json;print(json.load(open('$site_dir/data/meta.json'))['generated'])")
got=$(curl -sS "$SITE_URL/data/meta.json?v=$ts" | python3 -c "import json,sys;print(json.load(sys.stdin)['generated'])")
[[ "$want" == "$got" ]] || { echo "error: live meta.json generated=$got, expected $want" >&2; exit 1; }
echo "==> deployed $ts ($SITE_URL live, HTTP $code, data $got)"
