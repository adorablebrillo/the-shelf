# My Shelf

## Sub-features

- An armchair reader appears below the empty-state instructions, or beside the heading when My Shelf has a want-marked book (hidden below 380px wide).
- The TBR list: every book marked *want*, the reading-now book starred first.
- The verdict row on every row: reading now · want · read · loved · not for me (pressing the lit mark takes it off).
- **+ add a book**: Apple Books search, then a verdict files the found book as an added book.
- Out now in your series: released, unread volumes, markable in place.

## How to get to it (user POV)

Tap **My Shelf** in the section bar (the phone's bottom bar shows the want count).

## Driving it with chrome-devtools-axi

- Mark a pick want on Home, open My Shelf, click `reading now — <title>`; the book takes the first spot with its star.
- Press the lit mark again (it reads `reading now — <title> (press again to take the mark off)`): the book drops back to plain want.
- The add-a-book search hits Apple Books over the network; with the dead-proxy launch it fails honestly (`The shelf server did not answer — try again.` is the offline-shaped error). Verify added books by seeding `added-books.json` in the scratch cfg before the build instead.

## Gotchas

- `reading now` is *want* plus a flag — it never appears in `states` alone; check `reading` in `reader-state.json`.
- A want-marked series volume files here too (its row's series line names the series and volume).
