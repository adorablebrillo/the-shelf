# Home

## Sub-features

- Decorative reader artwork sits in the reading corner. The desktop sidebar shows a bookshop only above 880 px wide and 860 px high.
- The reading-now card at the top: the book she is reading now (a pick, a series volume, or an added book — the one place an added book shows on Home, never as a pick) with a one-tap **I read today** and a one-tap **finished it**; when nothing is in progress, **choose your next book** with start buttons from My Shelf.
- The season panel below it: the goal ring (the books she marked *read* or *loved* inside the season's own days, against her goal — the book brew's `season_goal`, read live from `GET /api/interests` so a saved answer counts with no new run; 6 while there is none), this season's week Monday to Sunday with every day she read lit, and the streak line (weeks of the season holding a reading day, one rest week kept). On a phone the panel keeps to ring, count and streak: the days-left line, the week cells and the season's own name are the wider screen's detail.
- When the survey skipped the goal (surveyed, `season_goal` null), Home asks **How many books this season?** with − / + and **set my goal** — inside the season panel on a wider screen, under the issue line on a phone (≤700 px), so the first screen keeps the reading-now card and the issue line. The answer goes to `POST /api/interests/season-goal`, which sets only that field. While the question is open the panel's head reads `N books this season` and claims no goal reached.
- A season stamp is kept for good, so the page presses it only against a goal the server has just confirmed she gave: none while the survey is owed, none while Home asks, and none at a goal another device has since raised (the page reads the goal again before it keeps one, and again when the tab comes back). The server has the last word: it keeps a new season stamp only when the goal the page sent is still the saved one and the marks it holds still meet it (each mark on her local day, by her time zone's own rules, which the page sends), and the page shows the seal only once the server's answer holds it. A refused stamp is checked again a few times, a few seconds apart, from fresh marks and a fresh goal — also past a failed state read — and once more when a slow save of her marks lands. Each new mark of hers starts its own few checks, even after an earlier refused stamp spent its checks. A state read answered late never takes a stamp the page has seen kept off the page.
- The issue line under the month's picks: `N of M still open · next issue in D days` with a thin progress bar; deciding the last pick presses an issue-complete stamp in, once.
- The month's picks (lead card + grid), each with its four verdicts; decided picks clear from Home; carry-overs from earlier issues follow.
- The book brew widget: one row per interest in the file's order (label · dial name · four strength dots — off 0, curious 2, into it 3, obsessed 4), a `Reading for a reason: X of Y … books read` line when any topic-interest picks exist, and a `change in Settings` link. Read-only: the dials come from the build's `meter` doc in `container/dist/shelf-data.js`; the count is computed at render time from the marks, so deciding a topic pick moves the number without a rebuild.
- Anticipation: a row of countdown cards for tracked series, soonest first, horizontally scrollable on a phone.
- At Christmas, the page has a lower snow ledge with three tree buttons on it (on a phone the header scrolls away with the page and only the ledge and bottom bar stay fixed), plus brushing, sweeping, a plough, clearing, undo, pause and an effects preference. Frost stays on cover tops. The scene remains separate from verdicts.
- Read & loved (past 30 days) and series at a glance, below. A series card opens Series at that series; the all-series link opens the section without a target.
- Her kept stamps, last: one seal per season goal reached, issue decided to its last pick and series finished, oldest first, in the `stamps` channel of `reader-state.json` — plus a dashed mark for each one she can still earn now.

## How to get to it (user POV)

Open the served page — Home is the landing section. On a phone (≤880 px) the sections sit in a fixed bar at the bottom of the screen; the sidebar keeps its compact masthead.

## Driving it with chrome-devtools-axi

- Set a reading-now book the honest way: click `want to read <pick>` on Home, open **My Shelf** from the bar, click `reading now — <title>`, return Home. An added book can instead be seeded server-side: `POST /api/state` with `states {id:{s:'want'}}` and `reading {id:{s:true}}` (ids from `container/dist/shelf-data.js`).
- Press `mark <title> read — finished it` on the card and confirm: the card falls back (to another reading flag, or to choose your next book), the book files into the Archive, `reader-state.json` records `read` and a cleared reading flag.
- Press `I read today` on the reading-now card and confirm: the button reads `read today ✓` with `aria-pressed="true"`, `days` in `reader-state.json` holds her local date (`YYYY-MM-DD`) under that book id, and the week strip lights today. Pressing it again the same day changes nothing.
- Log a day the way a phone does: `POST /api/state` with `{"days":{"<book id>":["2026-11-17"]}}`, reload, and confirm the page counts both devices' days in the streak line and the same one day twice stays one day.
- Decide every open pick (`want`/`mark read`/`loved`/`not for me`) and watch the last one: the issue line reads `every pick decided · next issue in D days`, the stamp panel appears, confetti only for `read`/`loved`. Leave Home and return: the stamp is gone, the line stays.
- Fill the season ring: mark books *read* or *loved* and watch the line read `N of G books this season`, where `G` is the goal the volume saved (`season_goal` in `GET /api/interests`: 6 on a `--surveyed` volume, otherwise the number the survey or Home saved); at the goal it reads `<Season> goal reached`, `stamps` gains `season:<key>:<year>`, and **Your stamps** shows the seal. Reopening a mark leaves the kept stamp in the row.
- Tap a series at a glance and confirm its card reaches the top of Series. Scroll elsewhere and wait through the 6.5-second refresh; the page must not jump back. Check at phone and desktop widths.
- Geometry: the reading card and the issue line must sit above the phone's bottom bar; measure with `eval` IIFEs over `getBoundingClientRect` (see SKILL.md's Drive).

- For the repeatable Christmas journey, start `python3 tests/christmas-proxy.py` beside the made-up Shelf server, open `http://127.0.0.1:8812/journey`, and run ten journeys. Stop the proxy afterward. With Playwright, `python3 tests/christmas_reduced_motion.py <url>` checks the reduced-motion plough, and `python3 tests/series_glance.py <url>` checks opening a series from Home; at Christmas on a desktop with effects on the reading area scrolls instead of the window, while phones scroll the window, so check a 1440 px width too.
- At Christmas, use the three tree buttons on the lower snow ledge. Plant all three trees, remove one and undo. Sweep, plough and clear; plough retains frost and trees, while clear removes frost but retains trees. Pause and turn effects off; confirm navigation and verdicts still work.
- On a phone at Christmas, scroll the page and tap the ledge where a verdict button sits behind it: nothing behind it may react, and Tab must stop above the ledge.
- Check the reserved drift strip with brush mode on and off. Compare the 120-second drift and frost caps, then check a hidden page and reduced motion. The effects preference persists on the device; trees and snow do not persist after closing the page.

## Gotchas

- A fresh volume opens on the first-open survey, which covers Home. Answer it first, or seed the volume with `seed-demo.py <cfg> <root> --surveyed` before launch to start on Home.

- `finished it` marks read, which files the book read — to undo, use the Archive's read row, not Home.
- The issue-complete panel above the picks is session state (it shows once per completion, per visit); the kept stamp for the same issue lives in `reader-state.json` under `stamps` and never comes off.
- A reading day is never a verdict: it travels on its own `days` channel, which the run does not read, and it merges by union — no device can clear another's day.
- The line's `M` counts only the current month's picks; carry-overs are counted by the carried-over line below the grid.
