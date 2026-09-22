# The Shelf

A personal book-curation app: a monthly curated page of new romance releases plus the reader's own library, self-hosted on the reader's server. The public repo ships blank; one reader per install.

## Language

### Sections

**Home**:
The landing section and the action surface — everything still awaiting a verdict lives here (the current month's picks first, then anything open from earlier issues), together with the reading corner, anticipation, read & loved, and series at a glance.
_Avoid_: dashboard, landing page

**My Shelf**:
The aggregate of every book marked *want*, across all months. Ordered by issue, newest first; within an issue, the curated order. Its page header reads **My TBR list**.
_Avoid_: reading list, want list

**Series**:
The section showing every open series with its full run, its next book, and per-volume markers. Ordered by urgency — out-now first, then soonest coming, then announced. The header counts honestly ("N open · M finished and closed"); fully-read series leave this page.
_Avoid_: the lane

**Archive**:
The resolved side of the app — **Read & loved** (the stacks, everything read by series, standalones) and **Not for me** (set-aside books, each with *put it back*).
_Avoid_: library

**Settings**:
The setup page: OpenRouter key, model, the curate-now run, and watched authors.

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
The rotating quote and seasonal brew panel at the top of Home.

**Read & loved**:
The Home block of everything marked read or loved in the past 30 days, dated by the day it was marked.

**The stacks**:
The bookcase rendering of read books in the Archive. Spines are clickable (mark unread); the plate follows the pointer.

**Plate**:
The instant title · author · series line shown inside the case. Never a native browser tooltip.

**Standalone**:
A read book that isn't part of a series.

**Watched authors**:
Authors whose new releases every run looks for.
