#!/usr/bin/env bash
# Pull the task images PatchBench evaluates in, in parallel.
#
#   ./pull_images.sh                     # all 213 vulnerable images
#   ./pull_images.sh --jobs 8            # more parallelism
#   ./pull_images.sh --ids "11351 42859" # just these tasks
#   ./pull_images.sh --suffixes "vul fix"   # also the reference-patched images
#
# The images are large; the full set is on the order of a terabyte.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA="$HERE/data/metadata.json"
REPO="b4drequest/vulpatch"
SUFFIXES="vul"
IDS=""
JOBS=4

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)     REPO="$2";     shift 2 ;;
    --suffixes) SUFFIXES="$2"; shift 2 ;;
    --ids)      IDS="$2";      shift 2 ;;
    --jobs|-j)  JOBS="$2";     shift 2 ;;
    -h|--help)  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
[ -f "$METADATA" ] || { echo "metadata not found: $METADATA" >&2; exit 1; }

if [ -z "$IDS" ]; then
  IDS=$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))))' "$METADATA") \
    || { echo "could not read task ids from $METADATA" >&2; exit 1; }
fi

TAGS=""
for id in $IDS; do
  for suf in $SUFFIXES; do TAGS="$TAGS $REPO:$id-$suf"; done
done
TOTAL=$(printf '%s\n' $TAGS | grep -c .)

echo "pulling $TOTAL image(s) from $REPO with $JOBS parallel jobs"
echo

pull_one() {
  if docker pull -q "$1" >/dev/null 2>&1; then
    echo "  ok      $1"
  else
    echo "  FAILED  $1"
  fi
}
export -f pull_one

printf '%s\n' $TAGS | xargs -P "$JOBS" -I{} bash -c 'pull_one "$@"' _ {} | tee /tmp/pull_images.$$.log

FAILED=$(grep -c '^  FAILED' /tmp/pull_images.$$.log)
echo
echo "pulled $(grep -c '^  ok' /tmp/pull_images.$$.log)/$TOTAL, failed $FAILED"
if [ "$FAILED" -gt 0 ]; then
  grep '^  FAILED' /tmp/pull_images.$$.log
  echo "Re-run to retry; layers already downloaded are skipped."
fi
rm -f /tmp/pull_images.$$.log
[ "$FAILED" -eq 0 ]
