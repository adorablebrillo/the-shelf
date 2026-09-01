---
version: alpha
name: The Shelf
description: Monthly new-romance magazine page — cream editorial journal with a cute, deliberate touch. Elegant and sophisticated first; whimsy only where it belongs.
colors:
  primary: "#1A1815"
  secondary: "#9BA98A"
  tertiary: "#C8704A"
  neutral: "#F7F1E7"
  paper: "#F7F1E7"
  card: "#FBF6EC"
  ruling: "#F2EBDE"
  line: "#E4DAC7"
  rose: "#E8C4C6"
  sage: "#CBD6C0"
  blue: "#C9D6E0"
  butter: "#F0E3C4"
  autumn-orange: "#D89A6E"
  autumn-rust: "#C8704A"
  autumn-sage: "#9BA98A"
  autumn-rose: "#B8788A"
typography:
  h1:
    fontFamily: "Bodoni 72, Didot, Bodoni MT, Georgia"
    fontSize: 80px
    fontWeight: 600
    letterSpacing: "0.045em"
    lineHeight: 1.02
  heading:
    fontFamily: "Bodoni 72, Didot, Bodoni MT, Georgia"
    fontSize: 17px
    fontWeight: 600
    letterSpacing: "0.14em"
    lineHeight: 1.25
  kicker:
    fontFamily: "Bodoni 72, Didot, Bodoni MT, Georgia"
    fontSize: 11px
    fontWeight: 600
    letterSpacing: "0.38em"
    lineHeight: 1.4
  body-md:
    fontFamily: "Baskerville, Baskerville Old Face, Georgia"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: "Baskerville, Baskerville Old Face, Georgia"
    fontSize: "12px"
    fontWeight: 400
    letterSpacing: "0.04em"
  hand:
    fontFamily: "Bradley Hand, Noteworthy, Chalkboard SE, Marker Felt, cursive"
    fontSize: "13.5px"
    fontWeight: 700
    lineHeight: 1.45
  script:
    fontFamily: "Snell Roundhand, Apple Chancery, Segoe Script, Bradley Hand, cursive"
    fontSize: 34px
    fontWeight: 700
    lineHeight: 1.05
rounded:
  sm: 0px
  md: 0px
  pill: 999px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
  xl: 44px
components:
  masthead-wordmark:
    typography: "{typography.h1}"
    textColor: "{colors.primary}"
  kicker:
    typography: "{typography.kicker}"
    textColor: "{colors.primary}"
  mast-art:
    backgroundColor: "{colors.card}"
    size: 158px
    height: auto
  mast-tape:
    backgroundColor: "{colors.rose}"
    width: 84px
    height: 22px
  soon-strip:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 16px 20px
  soon-tag:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.primary}"
    padding: 6px 12px
  soon-book-title:
    typography: "{typography.script}"
    textColor: "{colors.primary}"
  soon-days-chip:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
    padding: 5px 11px
  coffee-img:
    size: 116px
    height: 116px
  coffee-quotes:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 11px 16px
  quote:
    typography: "{typography.hand}"
    textColor: "{colors.primary}"
  tracker-panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 26px 22px 16px
  tracker-spine:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    height: 132px
    width: 47px
  tracker-spine-read:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
  tracker-spine-loved:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
  tracker-spine-want:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
  tracker-spine-skip:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    height: 132px
  month-row-current:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
    padding: 13px 18px
  month-select:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 9px 12px
  book-card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 16px 18px 18px
  cover:
    size: 152px
    height: 228px
  cover-tape-a:
    backgroundColor: "{colors.rose}"
    width: 84px
    height: 22px
  cover-tape-b:
    backgroundColor: "{colors.sage}"
    width: 84px
    height: 22px
  badge-fresh:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
    padding: 4px 10px
  seal-top-pick:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
    size: 88px
    height: 88px
  seal-top-pick-core:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
  chip-trope:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
    padding: 3px 8px
  chip-genre:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
  chip-genre-sage:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.primary}"
  chip-genre-blue:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.primary}"
  chip-genre-butter:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
  chip-anticipated-sequel:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
  pill-state:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 5px 9px
  pill-state-selected:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
  pill-state-read:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.primary}"
  pill-state-loved:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
  pill-state-skip:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
  mmc-meter-dot:
    backgroundColor: "{colors.rose}"
    size: 7px
    height: 7px
  mmc-meter-dot-empty:
    backgroundColor: transparent
    size: 7px
    height: 7px
  sticker-spot:
    backgroundColor: "{colors.butter}"
    size: 70px
    height: 56px
  sticker-spot-rose:
    backgroundColor: "{colors.rose}"
    size: 70px
    height: 56px
  sticker-art:
    size: 44px
    height: 44px
  series-lane:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    padding: 12px 14px
  lane-chip:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
    padding: 4px 8px
  lane-chip-on:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
  lb-chip-read:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.primary}"
    padding: 5px 8px
  lb-chip-out:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
  lb-chip-soon:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
  seq-item:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
    padding: 9px 11px
  seq-series-tag:
    backgroundColor: "{colors.rose}"
    textColor: "{colors.primary}"
    padding: 2px 7px
  read-pill:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
    padding: 3px 7px
  read-pill-on:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.primary}"
  seq-dismiss:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    size: 19px
    height: 19px
  why-note:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
  how-picks-btn:
    backgroundColor: "{colors.butter}"
    textColor: "{colors.primary}"
    padding: 13px 26px
  seasonal-leaf-orange:
    backgroundColor: "{colors.autumn-orange}"
  seasonal-leaf-rust:
    backgroundColor: "{colors.autumn-rust}"
  seasonal-leaf-sage:
    backgroundColor: "{colors.autumn-sage}"
  seasonal-leaf-rose:
    backgroundColor: "{colors.autumn-rose}"
  page-ground:
    backgroundColor: "{colors.neutral}"
  hairline:
    backgroundColor: "{colors.line}"
  tracker-scrollbar-track:
    backgroundColor: "{colors.ruling}"
---

## Overview

The Shelf is a monthly book-discovery page: 6–8 new romance titles (sport romance
and romantasy, 50/50), curated the 1st of every month for one reader. It is a
**magazine editorial first** — cream paper, Bodoni serif, Baskerville metadata,
ruled margins — with just enough hand-made charm (handwritten annotations,
washi tape, stickers) to feel like a beloved journal. Cute is only ever
*purposeful*: a sticker appears because it names the book's own vibe (dragon book
→ dragon sticker), never as decoration for its own sake. The page is fully
interactive: every clickable thing acts (tracker pills, lane chips, read/dismiss
buttons, month dropdown).

The readers' content rules are load-bearing and belong to the design:
Trad-pub first, indie only with proven early ratings. M/F romance only. No dark
romance. Spice moderate → explicit. Sequels shown only for series the reader is
already in. Anticipated sequels carry an `ANTICIPATED SEQUEL` chip and, when
released, join the recommendations. The tracker (want/read/loved/skip) feeds
next month's fit scores. No buy/borrow links. Top pick must be proven (never a
gamble).

## Colors

- **Primary ink (#1A1815):** everything that is text, border, or line. No
  grey-scale; ink stays true black-brown on cream.
- **Neutral paper (#F7F1E7):** page ground. One step lighter card (#FBF6EC)
  lifts panels; #F2EBDE ruling and #E4DAC7 lines do the quiet structuring.
- **Rose (#E8C4C6) and sage (#CBD6C0):** the two supporting "crayon" colors —
  romance = rose, read/status = sage. Powder blue (#C9D6E0) and butter
  (#F0E3C4) round out card accents (butter = highlight/current, never text on
  its own).
- **Autumn quartet (#D89A6E / #C8704A / #9BA98A / #B8788A):** reserved for the
  coffee corner + seasonal artwork only (steam, fall leaves, winter berries).
  Never used for interactive states.
- All fills are **solid hexes**. No translucency anywhere except the two
  sanctioned places: the coffee steam wisps and the quote crossfade.

## Typography

- **Masthead & headers:** Bodoni 72 → Didot → Bodoni MT → Georgia, large,
  uppercase with wide letterspacing (h1 80px max, kicker 11px @ 0.38em).
- **Metadata:** Baskerville → Georgia, quiet and small (12px).
- **Handwritten:** Bradley Hand → Noteworthy → Chalkboard SE → Marker Felt —
  for the hooks, coffee quotes, and short notes; bold, dark ink.
- **Script:** Snell Roundhand → Apple Chancery — big, elegant, single use: the
  featured upcoming book's name (e.g. "Threshing Day") in the Your Series
  strip.
- **No CDN fonts, ever.** System stacks only, so the page renders identically
  opened from disk or in the sandboxed preview.

## Layout

- Content column max-width **1180px**, centered; page padding 30px 26px.
- Vertical rhythm: masthead → Your Series strip → coffee corner → global
  bookshelf tracker → month index → shelf grid (main) + sequels column (side).
- The bookshelf tracker is a **global horizontal scroller** — one slim strip,
  month chips inline, spines coloured by state; no stacked month rows.
- Month index: **current month always visible + a dropdown picker** for past
  months (it never grows into a list).
- Sequels column is sticky; its series-lane (chips per series → read / out /
  coming chips) is the single source of truth for read-sequel state.
- 800px-wide preview must show zero horizontal overflow.

## Elevation & Depth

Flat and confident: no shadows on cards. Depth comes from *overlap and
rotation* — washi tapes crossing corners, the top-pick seal overhanging the
cover's bottom-left, tilted handwritten notes. The how-picks button is the
single element allowed a hard offset shadow (3px 4px 0). Hover states move
elements (translateY -2px, seal pulse), never fade them.

## Shapes

- Paper cut-outs: straight edges, clipped-corner badges, tilted rectangles —
  nothing soft.
- Only two rounded things in the whole system: pill-shaped status chips
  (`border-radius 999px`) and the top-pick seal's centre disc. Everything else
  is square.

## Components

- **Book card:** cover (152×228, 2:3) with two washi tapes; sticker sits in its
  own **tape-backed spot under the title** (never on the artwork); top pick
  gets the opaque **bottom-left seal**. Body: title, author/publisher/date/GR,
  hook (handwritten, rotated ±1-2°), trope chips, spice row, **MMC vibe meter**
  (5 dots + archetype note: "Xaden · Rhysand · Raihn energy" for romantasy,
  "same energy, no magic" for sport romance), tracker pills, fit note.
- **Tracker spine states:** read = rose fill, loved = rose + heart, want =
  outline + dot, **skip = faded (no slash)**.
- **Sequels:** each item has only two actions — `read` and dismiss (✕).
  Marking read moves the item into its series lane as a read chip. No want
  button.
- **Seasonal coffee corner:** the seasonal drink is a free-standing image (not
  boxed) with animated steam + gentle bob; the quote sits in a small bordered
  card beside it. Season config lives in one map (fall/winter/spring/summer —
  drink art, caption, garland art).

## Do's and Don'ts

**Do:**
- Magazine editorial hierarchy first; cute only as garnish.
- Stickers only: on the tape-backed spot under a title, or in the series lane —
  always relevant to the book's content.
- Let the read/loved/skip piano play clean: colors first, words second.
- Keep solid hexes, keep the cream, keep Bodoni.

**Don't:**
- No garlands, in any form (tried, user vetoed; seasonality lives in the
  coffee corner).
- No lined-paper background, no notebook margin line — crisp editor's sheet.
- No dotted/dashed borders — hard lines only.
- No random sticker placement, no sticker covering cover art, no childish
  labels ("sport romance corner" style).
- No slash marks on skip state; no want button on sequels; no separate read
  section (the lane owns read state).
- No emoji anywhere; no external fonts; no dead buttons.
