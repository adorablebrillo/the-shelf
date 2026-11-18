# Series

## Sub-features

- Every open series, urgency first: out-now first, then soonest coming, then announced.
- The full run per series: cover strip with volume markers (read ✓ · out ◆ · soon ○ · tba ·), the peek line, tap-to-open verdict rows.
- `mark <next> read` / `loved it` with an undo until the next mark or view change.
- The header counts honestly (`N open · M finished and closed`); closed series leave the page.

## How to get to it (user POV)

Tap **Series** in the section bar.

## Driving it with chrome-devtools-axi

- Hover a cover for the plate-style peek (`volTipText`), tap it for the same plus its verdict row.
- Click `mark <title> read` then `undo — <title> read` and confirm both marks land in `reader-state.json` and the series' read count moves and back.
- The demo shelf ships one closed series (`The Harbor Letters`) which must not appear on the page.

## Gotchas

- The tap-first-then-peek behaviour is deliberate on touch; the undo button disappears after the next mark anywhere or a view change.
- A `soon` volume whose date has passed reads as `out` on its own (client-side, on the reader's local date) — freeze time expectations accordingly.
