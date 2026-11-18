#!/usr/bin/env python3
"""The Shelf — the genre fallback, shared by curate/build/tests.

The run curates the reader's interests (interests.py — the Book-a-meter),
not a fixed lane tuple: a book's interest comes from the search that found
it. This module is the fallback for books without search provenance (a
Goodreads reference find, an old month file): it maps a genre to one of the
three default romance catalog names. counts()/shape_str()/shape_line() take
a book's interest from its lane field first, so the shape counts and lines
follow the interests the run actually read; `order` and `labels` let the
caller show the interests in file order with their display names.
"""
import re

# the default romance catalog: the names interests.py builds a blank install
# from (config.json lane_terms keys), and the display order when the caller
# passes nothing richer
LANES = ('sport romance', 'romantasy', 'contemporary romance')

SPORT = re.compile(r'hockey|f1|formula|football|baseball|sport|tennis|golf|soccer|racing', re.I)
FANTASY = re.compile(r'fae|dragon|fantasy|romantasy|vampire|fairy|witch', re.I)


def lane_of(book):
    """The genre fallback: one of the three default catalog names."""
    g = (book.get('genre') or '')
    if FANTASY.search(g):
        return 'romantasy'
    if SPORT.search(g):
        return 'sport romance'
    return 'contemporary romance'


def interest_of(book):
    """A book's interest name: the search that found it (its lane field, set
    by fetch), else the genre fallback. Never empty."""
    ln = (book.get('lane') or '').strip().lower()
    if ln:
        return ln
    return lane_of(book)


def _order(c, order):
    if order is not None:
        return [l for l in order if l in c]
    return [l for l in LANES if l in c] + [k for k in c if k not in LANES]


def counts(books, order=None):
    """Interest name -> how many books. A book with a lane (search
    provenance) counts there; the rest fall back to the genre mapping, so
    counts works for candidate sets, model picks and built books alike."""
    c = {l: 0 for l in (order if order is not None else LANES)}
    for b in books:
        k = interest_of(b)
        c[k] = c.get(k, 0) + 1
    return c


def shape_str(c, order=None):
    """'3/3/3' — the compact shape the page/report states."""
    return '/'.join(str(c[l]) for l in _order(c, order))


def shape_line(c, order=None, labels=None):
    """'3 sport romance · 3 romantasy · 3 contemporary romance' — with the
    interests' display names when the caller passes them."""
    return ' · '.join('%d %s' % (c[l], (labels or {}).get(l, l)) for l in _order(c, order))
