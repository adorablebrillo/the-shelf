#!/usr/bin/env bash
# The Shelf — one-shot monthly pipeline. Run from cron or by hand.
#   ./run.sh          # fetch + filter + curate + build
#   ./run.sh --deploy # ... and rsync to your server (see config.json deploy)
set -euo pipefail
cd "$(dirname "$0")"

echo "== fetch =="
python3 fetch.py
echo "== filter =="
python3 filter.py
echo "== curate (OpenRouter) =="
python3 curate.py || echo "!! curation failed (no key? bad model?) — skipping build"
if [ -f "$(python3 -c "import json,os;c=json.load(open('config.json'));print('data/month-%s.json'%__import__('datetime').datetime.now().strftime('%Y-%m'))")" ]; then
  echo "== build =="
  python3 build.py
fi

if [ "$1" = "--deploy" ] && python3 -c "import json,sys;sys.exit(0 if json.load(open('config.json'))['deploy']['enabled'] else 1)"; then
  HOST=$(python3 -c "import json;print(json.load(open('config.json'))['deploy']['host'])")
  PATH_=$(python3 -c "import json;print(json.load(open('config.json'))['deploy']['path'])")
  echo "== deploy → $HOST:$PATH_ =="
  rsync -az --delete -e ssh dist/ "$HOST:$PATH_"
  echo "== live =="
fi
echo "done."
