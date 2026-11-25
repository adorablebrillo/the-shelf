# The Shelf

A personal book-curation app: a monthly curated page of new releases across the reader's interests (the book brew) plus the reader's own library, self-hosted on the reader's server. The public repo ships blank; one reader per install.

## Language

### Sections

**Home**:
The landing section and the action surface — the reading corner at the top, then one row holding the reading-now card (every book she is reading now, newest first, each with its own one tap *I read today*; or choose your next book) beside the season panel (the goal as a receipt, her week and the streak), then the month's picks with their issue line in a two-column grid (then anything still open from earlier issues), then one row of three small blocks: the book brew widget (display only: each interest's dial and the reads its topic books count; it reads interests.json, never edits it), anticipation and series at a glance. The columns apply when Home is 720 px wide or more; below that, every block stacks in one column, and a pick card keeps a small cover at the left with its four choices in one row. On a phone the sections sit in a bar at the bottom of the screen.
_Avoid_: dashboard, landing page

**My Shelf**:
The aggregate of every book marked *want*, across all months, added books included. Ordered by issue, newest first; within an issue, the curated order; added books after the picks. Its page header reads **My TBR list**.
_Avoid_: reading list, want list

**Series**:
The section showing every open series with its full run, its next book, and per-volume markers. Ordered by urgency — out-now first, then soonest coming, then announced. The header counts honestly ("N open · M finished and closed"); fully-read series leave this page.
_Avoid_: the lane

**Finished Brews**:
The page that was called the Archive: the reader's library of finished books, and the resolved side of the app. A count line ("N books read · N loved · N not for me") and three filter buttons — **Read & loved** (one bookcase per season, newest first), **Loved only** (one *House favourites* bookcase) and **Not for me** (one bookcase under the heading *The returns cart*). The filters are not tabs. A book opens its **Book card** on a tap, and marks change only there. In the code and in older notes the page is still called the Archive (`goArchive`, `arc-*`).
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
I have read this. Files the book in Finished Brews.

**loved**:
I have read this and loved it. Counts as read everywhere; carries a *♥ loved it* tag in Finished Brews.
_Avoid_: favorite

**not for me**:
A verdict, not a browsing gesture. Sets the book aside on the returns cart in Finished Brews; nothing is deleted, and it can be put back.
_Avoid_: skip, dismiss

**reading now**:
A book she is reading at the moment: *want* plus a reading flag that travels beside the verdicts, never as one. She can be reading more than one book. The book takes the first spot on My Shelf with a star, a series volume shows a star on the Series page, and it has its own row in the reading-now card at the top of Home, newest first, with a one-tap *finished it*. Pressing it again leaves *want*; any other verdict clears the flag.

**Verdict row**:
The one control for a book's mark, on every book card and row: reading now · want · read · loved · not for me. The lit choice is the mark now; pressing it again takes the mark off (a pick goes back to Home as open, an added book leaves the shelf, a series volume goes back to out). In a list, the row shows only the current mark until she taps it. Home's picks keep their own four verdicts (they are open books only), and coming or announced volumes take no mark.

### Reading progress

**Reading day**:
One of her own calendar days on which she read. The one tap *I read today* on the reading-now card logs it, and marking a book *read* or *loved* logs that day too. Days are kept per book in `reader-state.json` under `days` and merge between devices by union: the phone's days and the desktop's days both count, and a day logged twice is one day. A logged day is a fact about a day, never a mark to be flipped — nothing takes it back.
_Avoid_: check-in, streak (for a single day)

**The streak**:
How many weeks of the current season, counted back from this one, hold at least one *reading day*. This week counts as soon as it holds a day. A week with none is a rest week: one rest week a season keeps the run, a second ends it there. The streak takes nothing back and does not reach before the season began.

**Season goal**:
How many books she means to finish in a season. The number is the book brew's `season_goal` when it has one, and 6 otherwise; Home reads it live, so a saved answer counts at once. Home counts it from her marks — the books marked *read* or *loved* inside the season's own days — and fills a ring with it; reaching it presses that season's *kept stamp* in.

**Season panel**:
The Home block beside the reading-now card: the season-goal ring, this season's week with every day she read lit, the streak line, and the **receipt**.

**Receipt**:
The list inside the season panel of every book she finished this season, one line each, oldest first, with the date and the verdict row, and a total (`N of G`). It lists the same read and loved marks the ring counts, so the lines always add up to the ring. On a phone it folds behind a button.

**Kept stamp**:
A round mark she has earned and keeps: a season whose *season goal* she reached, an issue she decided to its last pick, a series whose every volume she read. Stamps live in `reader-state.json` under `stamps`, travel between devices like a verdict, and are pressed in once — clearing the mark or the pick behind one never removes it. Home no longer shows them as a row; the season panel's line names a season stamp in the moment it is pressed in.
_Avoid_: badge, achievement

### Series

**Tracked series**:
A series she is in. It comes from `library.json`, from `sequels.json`, or from her marks: a book marked *read* or *loved*, or one she is reading now, tracks its series, worked out again at each run (no file is written, and clearing the mark stops tracking at the next run). The author of a tracked series is searched every run, and a new book in it is a guaranteed pick (the sequel guarantee). A series tracked from marks shows on the Series page once a next book is known. A series she left unticked on the Goodreads import is never tracked from marks (the `untracked` list in `added-books.json`).
_Avoid_: followed series, the lane

**Open series** / **Closed series**:
A series with at least one unread volume is open (it shows on the Series page); one whose every volume is read is closed (it leaves the page; its volumes stay in Finished Brews).

**Series volume states**: **read** · **out** (released, unread) · **coming** (dated, upcoming) · **announced** (no date).

**Anticipation**:
The Home list of countdown cards for upcoming releases from tracked series, soonest first. Not markable — on release, a book leaves anticipation and becomes *out* (actionable) or a pick.

**Out now (unread)**:
A released volume in a tracked series that hasn't been marked. Actionable from My Shelf's "Out now in your series" block and the Series page (its cover strip and the full run). The Series "mark next read" and "loved it" buttons offer an undo for the book just marked, until the next mark or a change of view.

### Surfaces

**The month's picks**:
The curated set for the current issue ("No. N · MONTH · x titles"). Home carries its issue line — how many picks are still open, with the days to the next issue — and a thin progress bar; deciding the last pick presses an issue-complete stamp in, once, and keeps it among her *kept stamps*. A decided pick clears from Home and lives in its section.

**Issue**:
One month's curated drop, numbered.

**Interest**:
One kind of book the reader wants: a story genre or a real-life topic. It has a name, a kind (story or topic), a dial (off, curious, into it, obsessed), a mode (new, best ever, both) and its own rules — the romance rules (M/F only, no cowboys, spice 3–5, dark welcome) hold only for romance interests, and the never list holds for every interest. The run searches each interest's own words and reads its Goodreads new-release list (the interest's `gr_slug`: fixed for a catalog interest, suggested once by the curator for a typed one and kept in the file), and splits the picks by dial weight; a pick carries the interest of the search that found it. A best-ever interest takes books of any date, rated 4.0 or more. A topic interest may also keep the baby's birth month and year (never a day): every run counts the age in whole months and names the **stage** it curates for. The list lives in interests.json on the config volume; a blank install starts with three romance interests — sport romance · romantasy · contemporary romance.
_Avoid_: the lane

**Stage**:
The baby's age band a topic interest curates for, one of five: 0–3, 4–6, 7–12, 13–24 and 25–36 months, each with its themes (newborn sleep and feeding, first solids, first words, toddler talk, preschool play). The run works it out from the birth month and year and names it in the curator request; a child past 36 months has no stage, so the interest is curated as a plain topic. A birth the run cannot use — one that does not read as a month and year, or one on a story interest — is named in the run's report, never passed over in silence.

**The book brew**:
The name of the interests list, shown as **The book brew** unless the reader types her own name (a file that still says "Book-a-meter", its old name, shows the new one; the file is not rewritten). It holds the interests, the never list, picks per issue and the season goal; the run makes the file on a first open. A topic interest in it may keep the baby's birth month and year, which the run reads as the stage.
_Avoid_: Book-a-meter (the old name), meter, counter

**Survey**:
The five-step setup that fills the book brew: the shelves, the dials, the never list, what she reads now, and the mix with the season goal. It shows while the interests file carries no surveyed day — on a new install, and once on a shelf that already has interests, which come in ticked. Its answers are the interests file the run reads; saving it starts a curate-now run at once (new picks right away), or says what is missing — no OpenRouter key yet, or a run already going; the book brew tab changes the same file later and starts none. The last step asks the season goal, and skipping it is allowed; Home then asks it in the season panel.
_Avoid_: onboarding quiz, interest wizard

**Reading corner**:
The panel at the top of Home that shows the season's quote of the day.

**Season**:
One of five date ranges that every day of the year falls into exactly once — autumn (1 Sep–31 Oct), Christmas (1 Nov–6 Jan), winter (7 Jan–end of February), spring (1 Mar–31 May), summer (1 Jun–31 Aug). The season, read from the reader's local date, sets the sidebar drink and its label, the quote of the day (24 per season, in order from its first day) and the look: the drawings around the seal and its rim words, four small sidebar drawings, a sprig and a colour on the reading corner — autumn maple leaves on rust, Christmas holly on oxblood with lights, a countdown and gentle snow while the page is visible (never under reduced motion), winter pine and snow on midnight, spring blossom on rose, summer lemons on sea glass. Snow falls over the page through Christmas and winter (1 Nov to the end of February) while the page is visible, and it stops by itself when spring starts. There are no snow controls. Outside Christmas, a season also has its **moment**: petals, leaves or snow fall, or bubbles rise, once across the page on the first open of the reader's day (never under reduced motion). The one table lives in `pipeline/build.py` (`SEASONS`); the drawings live in `pipeline/design/app.html`.
_Avoid_: brew season, month season

**Read & loved**:
The Finished Brews filter of everything marked read or loved, shown as one **bookcase** per season, newest first. A book stands in the season of the date of its read or loved mark, by the season table in `pipeline/build.py`; a book with no dated mark (the library's baked reads) stands in a last case, *Earlier reads*. Under each case: "N books this season". Home lists this season's finished books in the receipt, and its corner keeps a one-line count of the past 30 days.

**Bookcase**:
One season's books in Finished Brews: an arched dark-wood top with a gilt line and the plate, a dark back wall, a wooden shelf with a gold edge under each row, 3 books a shelf on a phone and 6 on a laptop. Real books stand face-out; the old leather spines and the one candle on each shelf are decoration only (hidden from screen readers and not pressable). The book that finishes a series carries a gold *✦ Series complete* plate.

**Plate**:
The brass name plate on a bookcase's arched top: the season's drink label and the year it started in, such as "Christmas cocoa season 2026" (a January date belongs to the Christmas that began the year before). *House favourites* and *Not for me* name the other two cases.

**House edition**:
The cover Finished Brews draws for a book that has no art: a cloth colour (the same book always the same colour), a thin gold frame, a cup mark, and the title and author in gold.

**Book card**:
What opens when a book in Finished Brews is tapped: the cover, title, author, series and volume ("book 3 of 3 · series complete"), interest, the read date and its season, the Goodreads link and the verdict row. A bottom sheet on a phone, centred on a laptop; Escape and Close shut it and focus goes back to the book. The only place a mark changes in Finished Brews.

**Standalone**:
A read book that isn't part of a series.

**Added book**:
A book the reader added herself with **+ add a book** (an Apple Books search at the top of My Shelf and Finished Brews) or brought in with the **Goodreads import**, not one a run picked. It lives in `added-books.json` on the config volume, keyed by the same book identity as every pick, and takes a verdict like any book. It files on My Shelf or in Finished Brews only — never on Home as a pick, with one exception: the book she is reading now shows in Home's reading-now card as a progress book. Taking its verdict back takes it off the shelf.
_Avoid_: manual book, custom book

**Goodreads link**:
The small "goodreads ↗" link on every book (not unannounced volumes), opening in a new tab. It opens the book's own Goodreads page when the shelf is sure of it — the Book Id of a Goodreads import, else the page the synopsis lookup matched by title and author, kept as `gr` in `synopsis-cache.json` — and a Goodreads search for the title and author otherwise.

**Goodreads import**:
The Settings **Import** tab: she chooses her Goodreads export file, sees a preview, then imports it. Read with 5 stars is *loved*; read with fewer or no stars is *read*; to-read is *want*; currently-reading is *want* plus reading now; a dnf or did-not-finish shelf is *not for me*; any other shelf is left out and counted. A mark is dated by Date Read, or Date Added when Date Read is empty. A mark already made in the app always wins, so importing the same file again adds nothing. The preview lists the series of her read books, ticked first when she read 2 or more of them or gave one 4 or 5 stars; only ticked series are tracked. Each imported book is an **added book**. The import makes no web lookups.

**Watched authors**:
Authors whose new releases every run looks for.

## Settings (ticket #41)

**Settings is a page, not a sheet.** The old modal (veil, dialog, focus trap, Escape-to-close) is retired; the nav's Settings button renders the page. The same controls, endpoints and tab machinery as the shipped sheet — a page script binds them when the view enters and stops the status poll when it leaves.

**Tabs**: Shelf (key · model · save · curate now · status), The book brew (the interests: one dial and a mode per interest, its reading list with **+ add a book**, the never list, picks per issue — every change saves to interests.json at once, and a book added for an interest is an added book marked reading now), Authors (watched list with interests, add + remove, the empty state) and Import (the Goodreads export file, its preview with series ticks, import). Roving tabindex + arrow keys, as the sheet had.

**Panels use inline `display`, not the `hidden` attribute** — the design runtime drops `hidden` during render, so `display:none` is the only reliable hide inside the dc root.
