# The Shelf — feature map

One file per user-facing feature, from the reader's point of view. When a task changes a feature, update its file in the same change. A proof that drives one convenient entry point is incomplete when the map lists others your change touches.

- [home.md](home.md) — the landing section: reading-now card, issue line, the month's picks, anticipation rail, read & loved, series at a glance; the phone's bottom bar.
- [my-shelf.md](my-shelf.md) — the TBR list: marks, reading now, add a book, out-now volumes.
- [series.md](series.md) — every open series: urgency order, the full run, marks with undo.
- [archive.md](archive.md) — the resolved side: read & loved, the stacks, not for me, reversals.
- [settings.md](settings.md) — the settings page: shelf key and curate-now status, watched authors, the Goodreads import.

All are reached from the section bar (sidebar above 880 px, bottom bar below). The server's JSON API backs marks (`/api/state`), added books (`/api/books`) and the import.
