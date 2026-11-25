# The Shelf — pipeline

Zero-dependency (pure Python stdlib) monthly engine for The Shelf.
Runs anywhere — your Mac, your server's cron, or GitHub Actions. No Hermes
involved: the only external calls are OpenRouter curation requests — one per run,
up to three when a thin interest needs its window widened (the shape rule).

## Layout

```
pipeline/
├── config.json        # model, rules, deploy target
├── taste-prompt.md    # the curator brain — the reader's profile + rules (repo ships a generic default; a deployed shelf keeps its own in /config)
├── fetch.py           # Apple Books search (her interests' words + author lane), publisher/language/series per book
├── releases.py        # Goodreads new releases per interest: Apple record first, the book's Goodreads page otherwise — best-effort, never breaks the run
├── reference.py       # Goodreads monthly release reference — best-effort, never breaks the run (#47)
├── filter.py          # hard rules + your shelf's verdicts (read/not-for-me never return)
├── curate.py          # OpenRouter call(s) → curated month JSON, split across her interests by dial (the book brew)
├── build.py           # month JSON → dist/index.html (design/app.html + manifest.webmanifest + assets/app-icon-*.png; blank installs get a valid empty-state page)
├── interests.py       # the book brew: interests.json (the volume file the run reads, made from lane_terms on a blank install), the dial split, the catalog terms, the baby's stages
├── lanes.py           # the genre fallback for books with no search provenance + the shape counts/lines
├── windows.py         # target month + window end, shared by filter/curate
├── bookids.py         # the canonical book identity (book_key), shared by engine + app
├── shelf_state.py     # your verdicts: the exclusion set + split (ticket #7)
├── sequels.py         # tracked series: library.json + sequels.json + the series her read, loved and reading-now marks track; the sequel guarantee's match
├── verdicts.py        # your verdicts teach the model: marked ids -> books, the her_verdicts lists, the kept `because` (#83)
├── paths.py           # personal files: config volume first, repo copy as fallback
├── test_shape.py      # the shape rule's deterministic tests
├── test_interests.py  # the book brew: defaults, the dial split, scoped rules, best-ever, the per-interest report, the baby's stages
├── test_shelf.py      # your-shelf exclusion tests
├── test_verdicts.py   # her_verdicts: the lookup, the capped lists, the `because` rule
├── test_releases.py   # the release lists: the genre-page parser (a real page), the Apple-first rule, the page cache and cap, the bot check, the kept slug
├── test_reference.py  # the Goodreads reference: parsers (real fixtures), matchers, failure paths, the fetch's redirect cookies
├── testdata/          # saved real pages for the Goodreads parsers (the month list, a book page, the classic and the Next.js search pages) and Apple Books answers
├── test_filter.py     # the pairing screen's tests
├── test_marked_series.py # a read, loved or reading-now pick tracks its series: marks, fallback, guarantee, author lane, Series page, curate's series copy
├── test_watches.py    # author watches: page series extraction + the radar merge
├── test_pick.py       # pick_book survives model field drift (string spice/mmc)
├── test_seasons.py    # the season table: one season a day, Christmas boundaries, complete looks, corner contrast
├── test_quick_build.py # the quick boot build (SHELF_OFFLINE=1): saved data only, no network request
├── test_added.py      # the build ships books she added by search (#84)
├── test_covers.py     # series cover lookups: a refused lookup is retried, a real miss is saved, old misses expire
├── design/            # the live design — app.html + support.js + vendored React
├── run.sh             # one-shot: fetch → releases → reference → filter → curate → build [--deploy]
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
./run.sh            # fetch + releases + reference + filter + curate + build
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

- **fetch prints failed calls** → Apple Books search is the fetch stage's only
  source (charts-RSS, Reddit and romance.io are dead and removed). Every call is
  counted and the report at the end of a fetch run shows it. Goodreads is read
  by the two stages after it (`releases.py`, `reference.py`).
- **`NO OPENROUTER API KEY`** → step 1 above.
- **curate HTTP 401** → key wrong or expired (check `data/curate-*.error.json`).
- **curate JSON error** → model wrapped text oddly; bump the model in `config.json`
  (e.g. `anthropic/claude-3.5-haiku` costs a bit more, parses cleaner).
- **want to re-run a previous month** → `python3 build.py` picks the newest
  `data/month-*.json`; keep old months as history.

Every run is auditable: candidates, filtered set, and the curated month are all
saved as JSON in `data/`.

## The Goodreads new releases (releases.py)

Runs right after fetch. For each interest whose dial is on (a best-ever interest
is skipped), it reads that interest's Goodreads genre list once
(`goodreads.com/genres/new_releases/<slug>`), drops the books the shelf already
saw, and looks up the rest — at most `releases_entry_cap` (80) per run, the
interests taking turns. A book is looked up on Apple Books first; with no Apple
record it is read from its own Goodreads page (publisher, date, ratings, cover)
and tagged `pub_source: goodreads-page`, so the filter's rule for books from
small publishers — 4.0 or more from 100 readers — applies unchanged. A find is
appended to the month's candidates, lane = the interest, `found_by:
goodreads-genre:<slug>`.

A catalog interest has a fixed genre (`gr_slug` in `interests.py`); a typed
interest asks the curator once for up to 3, keeps the first one whose list shows
books as `gr_slug` in `interests.json`, and asks no one again.

Goodreads answers a client without a browser with a bot check once it asks too
often (`synopses.py` measured it), so book pages are read `goodreads_gap_seconds`
(10) apart, at most `releases_page_cap` (30) per run, cached by Goodreads id for
14 days in `data/goodreads-cache.json`, and the first bot check ends the page
reads for that run. Everything is best-effort like the reference below: a
failure prints why, `data/releases-<month>.json` says `ok:false`, and the run
goes on with Apple alone.

## The Goodreads reference (reference.py, #47)

Runs between fetch and filter. One polite request for the month's
most-popular-releases list, then find-not-just-flag: an Apple miss is looked up
with the normal search (title AND author verified, product page resolved);
a Kindle-first miss gets its own Goodreads page read once (publisher, date,
genres, ratings, cover). At most 8 misses are looked up per run, one request at
a time with a 1.2s gap. Everything is best-effort: any failure prints why,
writes `data/reference-<month>.json` with `ok:false` and exits 0 — a missing
reference line is acceptable, a broken run is not. `./run.sh` therefore runs it
plain (it cannot fail the chain).
