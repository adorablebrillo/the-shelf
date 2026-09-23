# Product

<!-- impeccable:product-schema 1 -->

<!-- Init ran 2026-09-23; the live interview probe timed out, so every fact below
     is inferred from the repository, the shipped copy and the run artifacts.
     All of it is open to correction — edit freely. -->

## Platform

web

## Users

One reader. She reads romance (hockey/F1/football and fae/dragon
romantasy), mostly on her phone, and her job on this page is small and clear:
decide what to read next from a short, hand-curated set of new releases.
Browsing happens in snatches (a phone in one hand), so every card must read at
390px before it reads anywhere else. No second audience exists today; there are
no accounts, no sharing, no growth loop.

## Product Purpose

A monthly romance page: new releases across three lanes — sport romance,
romantasy, contemporary romance — fetched from Apple Books (plus a Goodreads
release reference), curated by a model against her taste profile, and served
as one page from her own server. Success is a drop that feels hand-picked for
one person, where every verdict she gives visibly steers the next drop.

## Positioning

A single-reader curation engine whose verdicts feed back into its own
discovery net. A neighboring product could copy the page; it could not
truthfully copy "the shelf remembers every book it showed you, never
re-recommends a resolved one, and the engine's filters bend to one person's
marks." There is nothing to sell, no engagement metric, and no reason to
retain attention — the page is done when she has decided.

## Operating Context

- Self-hosted on her Unraid server; the container serves the page and runs the
  monthly drop (1st of the month, 09:00) plus a manual "curate now" button.
- Browsed mainly as a home-screen app on an iPhone (Chrome), phone-first at
  390; the desktop is the second screen, not the primary one.
- Reader state is server-side: marks follow her between phone and desktop.
- Her data (library, sequels, taste prompt, reader state, months, caches)
  lives only on her server volume. The public repo ships blank.
- Runs are inspectable: every stage prints an honest report line (counts,
  drops, misses), and a zero is printed, never silence.

## Capabilities and Constraints

- Content rules (hard): M/F only; trad-published first, indie only with proof
  (rating ≥ 4.0 and ≥ 100 ratings); dark romance — especially dark academia —
  welcome; no cowboy/cowgirl/western characters; spice 3–5; releases inside
  the run's own window; sequels only from series she is already in.
- Shape: 3/3/3 up to nine books when every lane qualifies, floor of two per
  lane, gaps filled from the strongest leftovers; thin months say so honestly.
- The reader flow: want · read · loved · not for me. Nothing expires; read and
  loved move to the archive; "not for me" sets a book aside and it never
  returns. No confirm dialogs; "not for me" everywhere (never "skip").
- No buy links — discovery, not commerce.
- Terminology that must survive: "My Shelf" (nav) with the page header
  "My TBR list"; "want to read"; "not for me"; the three lane names
  "SPORT ROMANCE · ROMANTASY · CONTEMPORARY ROMANCE".

## Brand Commitments

- The name is The Shelf.
- Privacy is structural, not a setting: her real name and email never appear
  in the public repo or its history; public commits use the no-reply identity.
- The copy speaks to one reader, quietly; it never advertises, upsells, or
  performs enthusiasm.

## Evidence on Hand

- Real run artifacts: month JSONs, candidate/filtered/reference files, the
  cover cache (on the server volume).
- Real page fixtures for the reference parsers (`pipeline/testdata/`).
- The design's own reference renders and the before/after evidence set
  (`docs/evidence/`).
- No testimonials, customers, benchmarks, pricing, or licensing claims exist
  and none may be fabricated.

## Product Principles

1. One reader, no growth. Every decision optimizes for her next click, not an
   audience.
2. The shelf steers the engine. Verdicts change what comes next; resolved
   books never return.
3. Privacy is structural. If a fact about her could ship, it does not belong
   in the repo.
4. Phone-first. 390px is the acceptance gate, not a breakpoint.
5. Nothing is dropped silently. Failures report why, zeros print, and a
   missing thing is said out loud.

## Accessibility & Inclusion

Phone-first use drives the shipped standard: every control holds a 44px floor
at phone widths, reduced-motion is respected (animations collapse, the
confetti is skipped), hover-only affordances always have a tap equivalent, and
information is never hidden behind native tooltips. No product-specific
assistive-technology requirement has been established beyond that.
