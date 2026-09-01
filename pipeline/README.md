# The Shelf — pipeline

Zero-dependency (pure Python stdlib) monthly engine for The Shelf.
Runs anywhere — your Mac, your server's cron, or GitHub Actions. No Hermes
involved: the only external call is one OpenRouter LLM request per month.

## Layout

```
pipeline/
├── config.json        # model, rules, deploy target
├── taste-prompt.md    # the curator brain — the reader's profile + rules
├── fetch.py           # Apple Books + Goodreads + Reddit + romance.io (best-effort)
├── filter.py          # hard rules: M/F, no dark, spice band, window, trad/pub-first
├── curate.py          # OpenRouter call → curated month JSON
├── build.py           # month JSON → dist/index.html (from DESIGN.md template)
├── run.sh             # one-shot: fetch → filter → curate → build [--deploy]
├── template.html      # the approved v4 design (data injected at build time)
└── data/              # candidates-*.json, filtered-*.json, month-*.json (history)
```

## One-time setup

1. **OpenRouter key** — https://openrouter.ai → Keys → create.
   ```
   export OPENROUTER_API_KEY=sk-or-v1-...          # env, or
   mkdir -p ~/.config/the-shelf && echo 'sk-or-...' > ~/.config/the-shelf/openrouter.key
   ```
2. **Template** (already done): `cp ../.lavish/the-shelf-v4.html template.html`
3. **Deploy** (optional): edit `config.json → deploy` (host, path, enabled: true),
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
    <string>cd /Users/aminazmitha/Documents/HermesApps/the-shelf/pipeline && ./run.sh --deploy &gt;&gt; monthly.log 2&gt;&amp;1</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer><key>Day</key><integer>1</integer></dict>
</dict></plist>
```
```
launchctl load ~/Library/LaunchAgents/com.theshelf.monthly.plist
```

**GitHub Actions** — if you push this repo to GitHub (private), the included
`.github/workflows/monthly.yml` fires on the 1st, needs the key as a repo
secret `OPENROUTER_API_KEY`, and publishes a ready-to-serve `dist/` artifact.
(Deployed to your server still needs `rsync` on the runner — or set
`RU_DEPLOY` creds; simplest: Actions builds, then your server pulls.)

## Troubleshooting

- **romance.io fetch skips** → Cloudflare shield; normal. Apple + Goodreads
  usually carry the month.
- **`NO OPENROUTER API KEY`** → step 1 above.
- **curate HTTP 401** → key wrong or expired (check `data/curate-*.error.json`).
- **curate JSON error** → model wrapped text oddly; bump the model in `config.json`
  (e.g. `anthropic/claude-3.5-haiku` costs a bit more, parses cleaner).
- **want to re-run a previous month** → `python3 build.py` picks the newest
  `data/month-*.json`; keep old months as history.

Every run is auditable: candidates, filtered set, and the curated month are all
saved as JSON in `data/`.
