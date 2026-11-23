---
name: verify-the-shelf
description: Launch, drive and photograph The Shelf (the self-hosted book-curation web app) for live verification — a served build from a made-up shelf, at 390px and 1280px, with verdict flows and captures. Open when a task needs live proof of a page, a verdict flow or the server's behaviour.
---

# Verify The Shelf

The Shelf is a self-hosted web app: a Python pipeline (`pipeline/build.py`) builds a static page (`container/dist`) from month JSONs plus the reader's volume files, and a stdlib server (`container/server.py`) serves it with a small JSON API (`/api/state` for marks, `/api/books` for added books). The real reader's data never lives in the repo — it ships blank — so verification runs on a **made-up shelf**, served locally.

## Launch

1. Seed a made-up shelf (never the reader's own files):

   ```
   python3 .claude/skills/verify-the-shelf/seed-demo.py <scratch-cfg-dir> "$(pwd)"
   ```

   Writes made-up `library.json`, `sequels.json`, `added-books.json` into the scratch cfg dir and made-up `month-2026-10.json` / `month-2026-11.json` into `pipeline/data/` (git-ignored). A current-month file must carry `"mode": "adhoc"` or the build purges it. A fresh volume opens on the first-open survey; add `--surveyed` to also write a surveyed `interests.json` (a blank install's defaults, season goal 6) when the check starts on Home.

2. Build the page offline (no network lookups at all):

   ```
   CFG_DIR=<scratch-cfg-dir> SHELF_OFFLINE=1 DIST_DIR="$(pwd)/container/dist" python3 pipeline/build.py
   ```

   Ends with `built dist (current: 2026-11, 6 books, 4 series, issue no. 2)`.

3. Serve it with the real container server:

   ```
   CFG_DIR=<scratch-cfg-dir> PORT=8811 \
     http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 \
     python3 container/server.py &
   ```

   The dead-proxy env keeps the server's background full build from doing cover/synopsis lookups: it rebuilds the same page instantly instead of hitting Apple Books. Ready when the log prints `The Shelf server on 0.0.0.0:8811` and `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8811/` answers `200`. Record the PID for shutdown.

Shutdown: `kill <pid>`. Never leave the server running past the task.

## Doctor

```
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8811/
```

`200` plus a page outline that starts with `THE SHELF` and shows `navigation "Sections"` means the copy is worth driving. If the port answers but the outline is wrong, check that the build wrote `container/dist/index.html` (the server serves `container/dist`, not `pipeline/dist`, unless you point `DIST_DIR` there).

## Drive

Use Chrome through `npx -y chrome-devtools-axi` (resize is not supported; use emulation):

```
npx -y chrome-devtools-axi open http://127.0.0.1:8811
npx -y chrome-devtools-axi emulate --viewport 390x844x1     # phone
npx -y chrome-devtools-axi emulate --viewport 1280x900x1     # desktop
npx -y chrome-devtools-axi snapshot                            # outline with uid= refs
npx -y chrome-devtools-axi click @<uid>                        # click by ref
npx -y chrome-devtools-axi eval '<js expression>'             # geometry, state
npx -y chrome-devtools-axi console                             # errors since open
```

Stable handles: aria-labels, not coordinates — the verdict buttons read `want to read X`, `mark X read`, `loved X`, `not for me — X`, `reading now — X`; the sections read `Home`, `My Shelf N`, `Series N`, `Finished Brews`, `Settings`; sections are regions (`My reading corner`, `Reading now`, `This month's picks`, `Arriving in your series`, `Series at a glance`).

**Gotchas:** the app re-renders every 6.5 s, which bumps snapshot generations and stales refs — snapshot and click in the same shell command, and re-snapshot after any click. `eval` takes a single expression: pass an IIFE `(function(){...})()`, and prefer a quoted heredoc file over shell-escaped quoting. There is no reduced-motion emulation in this CLI; verify reduced-motion paths against the live stylesheet (`document.styleSheets`, the `prefers-reduced-motion: reduce` blocks) instead of faking the setting.

Marks travel client → `POST /api/state` → `reader-state.json` in the CFG dir, and back via `GET /api/state`; read that file (or `curl http://127.0.0.1:8811/api/state`) to confirm a verdict round trip. The same endpoint carries the reading flags (`reading`), the reading days (`days`: per book id, a list of `YYYY-MM-DD`, merged by union) and the kept stamps (`stamps`: `season:<key>:<year>`, `issue:<n>`, `series:<name>`). Seeding a mark server-side (the same channel a phone would use) is `curl -X POST .../api/state -d '{"states":{"<book-id>":{"s":"want","t":<ms>}},"reading":{"<book-id>":{"s":true,"t":<ms>}}}'`, and a day from the other device is `curl -X POST .../api/state -d '{"days":{"<book-id>":["2026-11-17"]}}'`.

Book ids are the pipeline's canonical `book_key(title, author)`: lowercased alphanumerics of the title, `--`, then of the author (read them from `container/dist/shelf-data.js`).

## Evidence

- Captures: `screenshot <path>` (viewport) or `screenshot <path> --full-page`; phone captures at the emulated 390 first, then 1280. Keep them in the task's evidence folder, never in the repo working copy.
- The repo's own convention: finished PRs commit selected, downscaled captures under `docs/evidence/` and reference them from the PR body by raw commit-SHA URL (this machine's gh has no `--attach`).
- Privacy: captures must show made-up books only — never the reader's real shelf, real names or real covers. The offline build ships no cover art (honest striped placeholders), which keeps captures UI-only.
- Capture the action and the result, not only the end state: e.g. the issue line before and after a verdict, and `reader-state.json` beside what the page shows.
- Geometry checks (fold fit, the 44px control floor, bar clearance) are `eval` measurements of `getBoundingClientRect`; save the outputs as transcripts.

## Cleanup

Stop what the run started, in this order:

```
kill <server-pid>
rm -rf <scratch-cfg-dir>
rm -f pipeline/data/month-2026-10.json pipeline/data/month-2026-11.json
rm -rf container/dist
```

`pipeline/data/` and `container/dist` are git-ignored; leaving them behind only confuses the next run. Never delete the evidence folder.

## Helpers

- `seed-demo.py` (beside this file) — writes the made-up shelf and months. Usage is in its docstring; it is idempotent and safe to re-run, except with `--surveyed`, which refuses an existing `interests.json`: seed each surveyed run into a fresh scratch volume.

## Feature map

See `features/README.md`. A proof that drives one convenient entry point is incomplete when the map lists other entry points — cover the ones your change touches.
