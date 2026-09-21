#!/usr/bin/env python3
"""The Shelf — your verdicts steer the engine (ticket #7).

Books the shelf has resolved are never suggested again:
- 'skip' (not for me) and 'read'/'loved' marks from the app's server-side
  reader-state.json (CFG_DIR);
- every read volume in the library.
filter.py applies this after the hard rules and counts what it removed, so
every run reports how much the shelf steered it.
"""
import json, os
import paths
from bookids import book_key

NOT_FOR_ME = 'not for me'
READ = 'read'


def exclusion_set(cfg_dir=None):
    """Canonical ids the shelf has resolved -> reason. Missing/blank files =
    nothing excluded (a fresh install stays open)."""
    out = {}
    rs = os.path.join(cfg_dir or paths.cfg_dir(), 'reader-state.json')
    try:
        state = json.load(open(rs))
        for bid, st in (state.get('states') or {}).items():
            s = st.get('s') if isinstance(st, dict) else None
            if s == 'skip':
                out.setdefault(bid, NOT_FOR_ME)
            elif s in ('read', 'loved'):
                out.setdefault(bid, READ)
    except Exception:
        pass
    try:
        lib_path, _ = paths.personal('library.json')
        lib = json.load(open(lib_path))
        for ser in lib.get('series', []):
            a = ser.get('author') or ''
            for t in ser.get('books', []):
                k = book_key(t, a)
                if k:
                    out.setdefault(k, READ)
    except Exception:
        pass
    return out


def exclude_by_shelf(books, ex):
    """Split candidates against the exclusion set -> (kept, counts)."""
    counts = {'total': 0, 'not_for_me': 0, 'read': 0}
    kept = []
    for b in books:
        k = book_key(b.get('title'), b.get('author'))
        if k and k in ex:
            counts['total'] += 1
            counts['not_for_me' if ex[k] == NOT_FOR_ME else 'read'] += 1
            continue
        kept.append(b)
    return kept, counts
