# The Shelf 📚

Monthly new-romance page + self-driving pipeline. A cream-journal web app that
curates **6–8 new sport-romance & romantasy releases** for one reader, every
1st of the month: fetch → filter → OpenRouter curation → build → serve.

## What's inside

| Path | Purpose |
|---|---|
| `pipeline/` | fetch.py / filter.py / curate.py / build.py + `taste-prompt.md` (the curator's brief) |
| `container/` | server.py (web UI + settings API + scheduler) and Dockerfile |
| `templates/` | Unraid Community Applications template (`my-the-shelf.xml`) + icon |
| `.lavish/assets/` | the design's images (covers, coffee art, stickers, reader art) |
| `.lavish/the-shelf-v4.html` | the approved design (reference) |
| `DESIGN.md` | Google-format design spec — the visual identity, lint-clean |
| `docker-compose.yml` | Unraid-friendly compose (port 8787, appdata volumes) |

## Deploy on Unraid

**Apps → Settings → Custom repositories →** add
`https://github.com/adorablebrillo/the-shelf` → search "The Shelf" → Install.
Then open `http://[unraid-ip]:8787` → **shelf settings** → paste your OpenRouter
key, pick a model, save. It runs the 1st of every month at 09:00 (TZ) and
rebuilds the page.

Full steps: [`UNRAID-INSTALL.md`](UNRAID-INSTALL.md)

## How it works

1. **fetch** — Apple Books (charts + recent releases), best-effort Goodreads/Reddit/romance.io
2. **filter** — the reader's hard rules: M/F only, no dark romance, spice 3–5, past-two-months window, trad-pub first (indie only with proven ratings)
3. **curate** — one OpenRouter LLM call (`taste-prompt.md`) → 6–8 books, hooks, top pick, MMC vibe scores
4. **build** — injects the month into the approved template → `index.html`
5. **serve + schedule** — Python-stdlib server, settings in `/config`, cron in-container

No Node, no pip installs, no databases. The whole thing is stdlib Python.
