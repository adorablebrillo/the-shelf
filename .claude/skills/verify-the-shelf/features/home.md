# Home

## Sub-features

- Decorative reader artwork sits in the reading corner. The desktop sidebar shows a bookshop only above 880 px wide and 860 px high.
- The reading-now card at the top: the book she is reading now (a pick, a series volume, or an added book — the one place an added book shows on Home, never as a pick) with a one-tap **finished it**; when nothing is in progress, **choose your next book** with start buttons from My Shelf.
- The issue line under the month's picks: `N of M still open · next issue in D days` with a thin progress bar; deciding the last pick presses an issue-complete stamp in, once.
- The month's picks (lead card + grid), each with its four verdicts; decided picks clear from Home; carry-overs from earlier issues follow.
- The Book-a-meter widget: one row per interest in the file's order (label · dial name · four strength dots — off 0, curious 2, into it 3, obsessed 4), a `Reading for a reason: X of Y … books read` line when any topic-interest picks exist, and a `change in Settings` link. Read-only: the dials come from the build's `meter` doc in `container/dist/shelf-data.js`; the count is computed at render time from the marks, so deciding a topic pick moves the number without a rebuild.
- Anticipation: a row of countdown cards for tracked series, soonest first, horizontally scrollable on a phone.
- Read & loved (past 30 days) and series at a glance, below. A series card opens Series at that series; the all-series link opens the section without a target.

## How to get to it (user POV)

Open the served page — Home is the landing section. On a phone (≤880 px) the sections sit in a fixed bar at the bottom of the screen; the sidebar keeps its compact masthead.

## Driving it with chrome-devtools-axi

- Set a reading-now book the honest way: click `want to read <pick>` on Home, open **My Shelf** from the bar, click `reading now — <title>`, return Home. An added book can instead be seeded server-side: `POST /api/state` with `states {id:{s:'want'}}` and `reading {id:{s:true}}` (ids from `container/dist/shelf-data.js`).
- Press `mark <title> read — finished it` on the card and confirm: the card falls back (to another reading flag, or to choose your next book), the book files into the Archive, `reader-state.json` records `read` and a cleared reading flag.
- Decide every open pick (`want`/`mark read`/`loved`/`not for me`) and watch the last one: the issue line reads `every pick decided · next issue in D days`, the stamp panel appears, confetti only for `read`/`loved`. Leave Home and return: the stamp is gone, the line stays.
- Tap a series at a glance and confirm its card reaches the top of Series. Scroll elsewhere and wait through the 6.5-second refresh; the page must not jump back. Check at phone and desktop widths.
- Geometry: the reading card and the issue line must sit above the phone's bottom bar; measure with `eval` IIFEs over `getBoundingClientRect` (see SKILL.md's Drive).

## Gotchas

- `finished it` marks read, which files the book read — to undo, use the Archive's read row, not Home.
- The stamp is session state (it shows once per completion, per visit); it is not in `reader-state.json`.
- The line's `M` counts only the current month's picks; carry-overs are counted by the carried-over line below the grid.
