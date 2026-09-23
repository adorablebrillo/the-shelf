# The Shelf 📚

Monthly new-romance page + self-driving pipeline. An editorial cream-and-gold
web app (Cormorant Garamond, forest-green hero panels) that curates **up to 9 new
releases across three lanes — sport romance, romantasy & contemporary romance**
— for one reader, every 1st of
the month: fetch → Goodreads reference → filter → OpenRouter curation → build → serve. Two views —
*This month* (the drop, the series hero, every series she is in) and *The
archive* (the reading room bookcase + everything she has read).

## What's inside

| Path | Purpose |
|---|---|
| `pipeline/` | fetch.py / reference.py / filter.py / curate.py / build.py + `taste-prompt.md` (the curator's brief) |
| `container/` | server.py (web UI + settings API + scheduler) and Dockerfile |
| `templates/` | Unraid Community Applications template (`my-the-shelf.xml`) + icon |
| `.lavish/assets/` | the design's art — the seasonal coffee illustrations |
| `pipeline/design/` | the live design (`app.html` + `support.js` + vendored React + the home-screen manifest and icons) |
| `compose.yaml` | Unraid-friendly compose (port 8787, appdata volumes) |

## Deploy on Unraid

**Apps → Settings → Custom repositories →** add
`https://github.com/adorablebrillo/the-shelf` → search "The Shelf" → Install.
Then open `http://[unraid-ip]:8787` → **shelf settings** → paste your OpenRouter
key, pick a model, save. It runs the 1st of every month at 09:00 (TZ) and
rebuilds the page.

Full steps: [`UNRAID-INSTALL.md`](UNRAID-INSTALL.md)

## Install it on your phone

The page is also a home-screen app: its own gold **S** icon and the name
"The Shelf", opening full-screen with no browser chrome.

1. On the phone, open the shelf's address in **Safari**
   (`http://[unraid-ip]:8787`).
2. Tap **Share → Add to Home Screen**, then **Add**.
3. Open it from the home screen — it launches full-screen, no browser
   chrome. The page stays cream; Android tints the bar forest (`theme-color`),
   iOS keeps its light status bar over the cream.

iOS only gives a true full-screen app when it is installed from Safari — keep
browsing day-to-day in Chrome if you like, the icon is independent of the
browser. The app points at the same LAN address, so it keeps working across
redeploys (the `/config` volume survives every image update).

## Bring your own data

This repo ships **blank** — no reader data in the tree or the image. A deployed
shelf keeps its reader data on the config volume (`/config`):

| File | What it is |
|---|---|
| `library.json` · `sequels.json` | the series you're in and their next books |
| `seed-reads.json` | your starting library + taste profile |
| `taste-prompt.md` | the curator's brief for your shelf |

Every run resolves these volume-first (a boot seeder copies them in once, only
from non-blank sources, and never overwrites). A fresh install stays blank until
you bring your own data.

## How it works

1. **fetch** — Apple Books only: a query per lane term + a query per author (the authors of every series you track + the authors you watch — **settings → Authors**), then each book's real publisher, language and audiobook availability read from its page
2. **filter** — the reader's hard rules (M/F only, dark romance & dark academia welcome, spice 3–5, a widening pool, trad-pub first) and **your shelf's verdicts**: not-for-me and already-read books never come back; every run reports how many candidates your shelf excluded
3. **curate** — one curation call per run, up to three when a thin lane widens (`taste-prompt.md`) → up to 9 books shaped 3/3/3 (floor two per lane; thin lanes widen 30→60→90 days before being dropped), hooks, top pick, MMC vibe scores
4. **build** — injects the month into the approved template → `index.html`
5. **serve + schedule** — Python-stdlib server, settings in `/config`, cron in-container

No Node, no pip installs, no databases. The whole thing is stdlib Python.
