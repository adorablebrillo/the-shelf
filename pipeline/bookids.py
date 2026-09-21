#!/usr/bin/env python3
"""The Shelf — the canonical book identity, shared by filter/build/tests.

One definition of book_key (ticket #1), so the engine and the app can never
disagree about what a book is.
"""
import re


def book_key(title, author):
    """THE identity for a book: deterministic from title + author, stable across
    runs, months and sources. Month picks, series volumes, the archive and the
    reader's marks all key on this, so one book is one thing everywhere."""
    def n(s):
        s = re.sub(r'\([^)]*\)', ' ', s or '')
        s = s.split(';')[0]
        return re.sub(r'[^a-z0-9]', '', s.lower())
    t, a = n(title), n(author)
    if not t:
        return ''
    return ('%s--%s' % (t[:72], a[:30])).rstrip('-')
