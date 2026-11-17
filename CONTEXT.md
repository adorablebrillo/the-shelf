# The Shelf

A personal book-curation app: a monthly curated page of new romance releases plus the reader's own library, self-hosted on the reader's server. The public repo ships blank; one reader per install.

## Language

### Sections

**Home**:
The landing section and the action surface — everything still awaiting a verdict lives here (the current month's picks first, then anything open from earlier issues), together with the reading corner, anticipation, read & loved, and series at a glance.
_Avoid_: dashboard, landing page

**My Shelf**:
The aggregate of every book marked *want*, across all months, added books included. Ordered by issue, newest first; within an issue, the curated order; added books after the picks. Its page header reads **My TBR list**.
_Avoid_: reading list, want list

**Series**:
The section showing every open series with its full run, its next book, and per-volume markers. Ordered by urgency — out-now first, then soonest coming, then announced. The header counts honestly ("N open · M finished and closed"); fully-read series leave this page.
_Avoid_: the lane

**Archive**:
The resolved side of the app — **Read & loved** (the stacks, everything read by series, standalones) and **Not for me** (set-aside books, each with *put it back*).
_Avoid_: library

**Settings**:
The setup page: OpenRouter key, model, the curate-now run, watched authors, and the Goodreads import.

### Verdicts

**Verdict**:
The reader's mark on a book — one of **want**, **read**, **loved**, **not for me**. A book with no verdict is **open**; with one, **decided**.

**want**:
I want to read this. Files the book on My Shelf.
_Avoid_: save, tbr (as a verdict)

**read**:
I have read this. Files the book in the Archive.

**loved**:
I have read this and loved it. Counts as read everywhere; carries a loved marker in the Archive.
_Avoid_: favorite

**not for me**:
A verdict, not a browsing gesture. Sets the book aside in the Archive; nothing is deleted, and it can be put back.
_Avoid_: skip, dismiss

### Series

**Tracked series**:
A series she is in. It comes from `library.json`, from `sequels.json`, or from her marks: a book marked *read* or *loved* tracks its series, worked out again at each run (no file is written, and clearing the mark stops tracking at the next run). The author of a tracked series is searched every run, and a new book in it is a guaranteed pick (the sequel guarantee). A series tracked from marks shows on the Series page once a next book is known. A series she left unticked on the Goodreads import is never tracked from marks (the `untracked` list in `added-books.json`).
_Avoid_: followed series, the lane

**Open series** / **Closed series**:
A series with at least one unread volume is open (it shows on the Series page); one whose every volume is read is closed (it leaves the page; its volumes stay in the Archive).

**Series volume states**: **read** · **out** (released, unread) · **coming** (dated, upcoming) · **announced** (no date).

**Anticipation**:
The Home block of upcoming releases from tracked series, each with a countdown. Not markable — on release, a book leaves anticipation and becomes *out* (actionable) or a pick.

**Out now (unread)**:
A released volume in a tracked series that hasn't been marked. Actionable from My Shelf's "Out now in your series" block and the Series page.

### Surfaces

**The month's picks**:
The curated set for the current issue ("No. N · MONTH · x titles"). A decided pick clears from Home and lives in its section.

**Issue**:
One month's curated drop, numbered.

**Lane**:
One of the three curation lanes — sport romance · romantasy · contemporary romance.

**Reading corner**:
The panel at the top of Home that shows the season's quote of the day.

**Season**:
One of five date ranges that every day of the year falls into exactly once — autumn (1 Sep–31 Oct), Christmas (1 Nov–6 Jan), winter (7 Jan–end of February), spring (1 Mar–31 May), summer (1 Jun–31 Aug). The season, read from the reader's local date, sets the sidebar drink and its label, the quote of the day (24 per season, in order from its first day) and the look: the drawings around the seal and its rim words, four small sidebar drawings, a sprig and a colour on the reading corner — autumn maple leaves on rust, Christmas holly on oxblood with lights, a countdown and gentle snow that falls the whole time the page is open (never under reduced motion), winter pine and snow on midnight, spring blossom on rose, summer lemons on sea glass. Outside Christmas, a season also has its **moment**: petals, leaves or snow fall, or bubbles rise, once across the page on the first open of the reader's day (never under reduced motion). The one table lives in `pipeline/build.py` (`SEASONS`); the drawings live in `pipeline/design/app.html`.
_Avoid_: brew season, month season

**Read & loved**:
The Home block of everything marked read or loved in the past 30 days, dated by the day it was marked.

**The stacks**:
The bookcase rendering of read books in the Archive. Spines are clickable (mark unread); the plate follows the pointer.

**Plate**:
The instant title · author · series line shown inside the case. Never a native browser tooltip.

**Standalone**:
A read book that isn't part of a series.

**Added book**:
A book the reader added herself with **+ add a book** (an Apple Books search at the top of My Shelf and the Archive) or brought in with the **Goodreads import**, not one a run picked. It lives in `added-books.json` on the config volume, keyed by the same book identity as every pick, and takes a verdict like any book. It files on My Shelf or in the Archive only — never on Home — and taking its verdict back takes it off the shelf.
_Avoid_: manual book, custom book

**Goodreads import**:
The Settings **Import** tab: she chooses her Goodreads export file, sees a preview, then imports it. Read with 5 stars is *loved*; read with fewer or no stars is *read*; to-read is *want*; currently-reading is *want* plus reading now; a dnf or did-not-finish shelf is *not for me*; any other shelf is left out and counted. A mark is dated by Date Read, or Date Added when Date Read is empty. A mark already made in the app always wins, so importing the same file again adds nothing. The preview lists the series of her read books, ticked first when she read 2 or more of them or gave one 4 or 5 stars; only ticked series are tracked. Each imported book is an **added book**. The import makes no web lookups.

**Watched authors**:
Authors whose new releases every run looks for.

## Settings (ticket #41)

**Settings is a page, not a sheet.** The old modal (veil, dialog, focus trap, Escape-to-close) is retired; the nav's Settings button renders the page. The same controls, endpoints and tab machinery as the shipped sheet — a page script binds them when the view enters and stops the status poll when it leaves.

**Tabs**: Shelf (key · model · save · curate now · status), Authors (watched list with lanes, add + remove, the empty state) and Import (the Goodreads export file, its preview with series ticks, import). Roving tabindex + arrow keys, as the sheet had.

**Panels use inline `display`, not the `hidden` attribute** — the design runtime drops `hidden` during render, so `display:none` is the only reliable hide inside the dc root.
