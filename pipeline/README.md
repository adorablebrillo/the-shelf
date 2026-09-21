# The Shelf — pipeline

Zero-dependency (pure Python stdlib) monthly engine for The Shelf.
Runs anywhere — your Mac, your server's cron, or GitHub Actions. No Hermes
involved: the only external calls are OpenRouter curation requests — one per run,
up to three when a thin lane needs its window widened (the shape rule).

## Layout

```
pipeline/
├── config.json        # model, rules, deploy target
├── taste-prompt.md    # the curator brain — the reader's profile + rules (repo ships a generic default; a deployed shelf keeps its own in /config)
├── fetch.py           # Apple Books search (lane terms + author lane), publisher/language/series per book
├── filter.py          # hard rules + your shelf's verdicts (read/not-for-me never return)
├── curate.py          # OpenRouter call(s) → curated month JSON, shaped 3/3/3 (ticket #6)
├── build.py           # month JSON → dist/index.html (design/app.html + manifest.webmanifest + assets/app-icon-*.png; blank installs get a valid empty-state page)
├── lanes.py           # one lane mapping shared by curate/build/tests
├── windows.py         # target month + window end, shared by filter/curate
├── bookids.py         # the canonical book identity (book_key), shared by engine + app
├── shelf_state.py     # your verdicts: the exclusion set + split (ticket #7)
├── paths.py           # personal files: config volume first, repo copy as fallback
├── test_shape.py      # the shape rule's deterministic tests
├── test_shelf.py      # your-shelf exclusion tests
├── test_filter.py     # the pairing screen's tests
├── test_watches.py    # author watches: page series extraction + the radar merge
├── design/            # the live design — app.html + support.js + vendored React
├── run.sh             # one-shot: fetch → filter → curate → build [--deploy]
└── data/              # candidates-*.json, filtered-*.json, month-*.json (history)
```

## One-time setup

1. **OpenRouter key** — https://openrouter.ai → Keys → create.
   ```
   export OPENROUTER_API_KEY=sk-or-v1-...          # env, or
   mkdir -p ~/.config/the-shelf && echo 'sk-or-...' > ~/.config/the-shelf/openrouter.key
   ```
2. **Deploy** (optional): edit `config.json → deploy` (host, path, enabled: true),
   make sure you can `ssh host` without a password (key auth).

## Run

```
./run.sh            # fetch + filter + curate + build
./run.sh --deploy   # + rsync dist/ to your server
```

## Cron

**Server (always on):**
```
# crontab -e
0 9 1 * * cd /path/to/pipeline && ./run.sh --deploy >> monthly.log 2>&1
```

**Mac (launchd)** — or just leave it to the server. If the server can run Python 3, that's the canonical home. If it can't, run this on the Mac with `launchd`:

```
# ~/Library/LaunchAgents/com.theshelf.monthly.plist
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>com.theshelf.monthly</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd /path/to/the-shelf/pipeline && ./run.sh --deploy &gt;&gt; monthly.log 2&gt;&amp;1</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer><key>Day</key><integer>1</integer></dict>
</dict></plist>
```
```
launchctl load ~/Library/LaunchAgents/com.theshelf.monthly.plist
```

**GitHub Actions** — the included `.github/workflows/docker.yml` builds the
container image to GHCR on every push to `main`; the Unraid template pulls it.

## Troubleshooting

- **fetch prints failed calls** → Apple Books search is the only discovery
  source left (charts-RSS, Reddit, Goodreads, romance.io are dead and removed).
  Every call is counted and the report at the end of a fetch run shows it.
- **`NO OPENROUTER API KEY`** → step 1 above.
- **curate HTTP 401** → key wrong or expired (check `data/curate-*.error.json`).
- **curate JSON error** → model wrapped text oddly; bump the model in `config.json`
  (e.g. `anthropic/claude-3.5-haiku` costs a bit more, parses cleaner).
- **want to re-run a previous month** → `python3 build.py` picks the newest
  `data/month-*.json`; keep old months as history.

Every run is auditable: candidates, filtered set, and the curated month are all
saved as JSON in `data/`.
