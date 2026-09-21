#!/usr/bin/env python3
"""The Shelf — your verdicts steer the engine (ticket #7).

Books the shelf has resolved are never suggested again:
- 'skip' (not for me) and 'read'/'loved' marks from the app's server-side
  reader-state.json (CFG_DIR);
- every read volume in the library.
filter.py applies this after the hard rules and counts what it removed, so
every run reports how much the shelf steered it.
"""
import json, os, re
import paths
from bookids import book_key

NOT_FOR_ME = 'not_for_me'
READ = 'read'


def _warn(what, e):
    # a corrupt file must never masquerade as "nothing excluded"
    print('shelf: %s unreadable (%s) — nothing excluded from it' % (what, str(e)[:80]))


def _norm(s):
    """Series keys for matching — parentheticals dropped, alphanumerics only
    (mirrors build.py's norm_name)."""
    s = re.sub(r'\([^)]*\)', ' ', s or '')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def exclusion_set(cfg_dir=None):
    """Canonical ids the shelf has resolved -> reason. Missing/blank files =
    nothing excluded (a fresh install stays open)."""
    out = {}
    rs = os.path.join(cfg_dir or paths.cfg_dir(), 'reader-state.json')
    if os.path.exists(rs):
        try:
            state = json.load(open(rs))
            for bid, st in (state.get('states') or {}).items():
                s = st.get('s') if isinstance(st, dict) else None
                if s == 'skip':
                    out.setdefault(bid, NOT_FOR_ME)
                elif s in ('read', 'loved'):
                    out.setdefault(bid, READ)
        except Exception as e:
            _warn('reader-state.json', e)
    try:
        lib_path, _ = paths.personal('library.json')
        lib = json.load(open(lib_path))
    except FileNotFoundError:
        lib = {'series': []}
    except Exception as e:
        _warn('library.json', e)
        lib = {'series': []}
    seq_authors = {}
    try:
        seq_path, _ = paths.personal('sequels.json')
        for ser in json.load(open(seq_path)).get('series', []):
            k = _norm(ser.get('series') or ser.get('name'))
            if k and ser.get('author'):
                seq_authors[k] = ser['author']
    except Exception:
        pass  # the fallback only sharpens matching; missing sequels is fine
    for ser in lib.get('series', []):
        # the same author resolution build.py uses: the library's, or the
        # sequels map's — otherwise an author-less series gets ids the engine
        # can never match (and a read volume could be re-suggested)
        a = (ser.get('author') or '').strip() or seq_authors.get(_norm(ser.get('name')), '')
        for t in ser.get('books', []):
            k = book_key(t, a)
            if k:
                out.setdefault(k, READ)
    return out


def exclude_by_shelf(books, ex):
    """Split candidates against the exclusion set -> (kept, counts)."""
    counts = {'total': 0, 'not_for_me': 0, 'read': 0}
    kept = []
    for b in books:
        k = book_key(b.get('title'), b.get('author'))
        if k and k in ex:
            counts['total'] += 1
            if ex[k] in counts:
                counts[ex[k]] += 1
            continue
        kept.append(b)
    return kept, counts
