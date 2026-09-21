#!/usr/bin/env python3
"""The Shelf — lane mapping, shared by curate/build/tests.

One definition of what "lane" a book belongs to, so the shape rule, the page
and the tests can never disagree.
"""
import re

LANES = ('sport romance', 'romantasy', 'contemporary romance')

SPORT = re.compile(r'hockey|f1|formula|football|baseball|sport|tennis|golf|soccer|racing', re.I)
FANTASY = re.compile(r'fae|dragon|fantasy|romantasy|vampire|fairy|witch', re.I)


def lane_of(book):
    g = (book.get('genre') or '')
    if FANTASY.search(g):
        return 'romantasy'
    if SPORT.search(g):
        return 'sport romance'
    return 'contemporary romance'


def counts(books):
    c = {l: 0 for l in LANES}
    for b in books:
        c[lane_of(b)] += 1
    return c


def shape_str(c):
    """'3/3/3' — the compact shape the page/report states."""
    return '/'.join(str(c[l]) for l in LANES)


def shape_line(c):
    """'3 sport romance · 3 romantasy · 3 contemporary romance'"""
    return ' · '.join('%d %s' % (c[l], l) for l in LANES)
