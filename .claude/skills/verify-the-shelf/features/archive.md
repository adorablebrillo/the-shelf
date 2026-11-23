# Finished Brews (the Archive)

## Sub-features

- Count line: "N books read · N loved · N not for me", then three 44 px filter buttons (not tabs): Read & loved, Loved only, Not for me.
- Read & loved: one bookcase per season, newest first. A book stands in the season of its read/loved mark's date (`SEASONS` in `pipeline/build.py`); the plate reads like "Christmas cocoa season 2026"; under it "N books this season". Baked reads with no dated mark stand in the last case, "Earlier reads". 3 books a shelf at 390 px, 6 at 1100 px and wider.
- Decoration (aria-hidden, not pressable): old leather spines and one candle per shelf. Real books stand face-out: real art, or a house edition (cloth, gold frame, cup, title and author) when there is none. Loved books carry "♥ loved it"; the book that finishes a series carries "✦ Series complete".
- Loved only: one "House favourites" case.
- Not for me: one case under "The returns cart".
- Book card: opens on a tap; bottom sheet on a phone, centred on a laptop; Escape and Close shut it and focus returns to the book. It is the only place marks change here.

## How to get to it (user POV)

Tap **Finished Brews** in the section bar (it wraps to two lines on a phone), then a filter button.

## Driving it with chrome-devtools-axi

- Tap a book (`[data-arc-book]`), press `not for me — X` in the card: `reader-state.json` records `skip`, and the book moves to the Not for me filter. Open it there and press `not for me — X` again: the mark clears, the card closes and the page says "X left Finished Brews."
- Pressing `want to read` or `reading now` also takes the book out and says "moved to My Shelf".
- Dated marks come from `reader-state.json` (`t` in ms). To see several seasons, POST `{"states": {id: {"s": "read", "t": ms}}}` to `/api/state` with dates in different seasons. `tests/archive_bookcase.py` does this on a scratch volume.

## Gotchas

- Marks made here behave exactly like marks anywhere else — the page is a view, not a separate store.
- The server keeps the newer timestamp per mark: to re-mark a book a check cleared, give it a fresh `t`.
- The art loader hides the first span in a cover's parent until the image loads; the offline build ships no covers, so every book shows its house edition.
- Run `python3 tests/archive_bookcase.py <url>` on a fresh scratch volume (it writes marks).
