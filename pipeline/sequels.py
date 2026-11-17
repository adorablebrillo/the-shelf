#!/usr/bin/env python3
"""#76 — the sequel guarantee.

Her rule (2026-10-04, verbatim intent): a book in a series she is already in
"should override all criteria and make sure it appears in the top picks list".
The pipeline matches candidates against EVERY series she is in — library.json
(what she has read / owns) and sequels.json (the tracked next books) — marks
them `aseq`, and then neither a screen, the cap, nor the curator's judgment may
drop one (her own verdicts and the hard screens still apply — a book she
already marked never returns, and an M/F or cowboy title is never hers).

This is deterministic on purpose: the taste prompt asks the model to mark
sequels, but the model is not a gate here (it dropped "Threshing Day" from the
September candidates, 2026-10-01 — the reader's Empyrean sequel — even though
it later picked it as the top pick from the marked pool).
"""
import glob, json, os, re

import paths
from bookids import book_key

# A read or loved book starts tracking its series (THS plan, piece 2): the
# series she has read into are worked out from her marks at each run, so no
# file is written and clearing the mark stops tracking at the next run.
TRACK_VERDICTS = ('read', 'loved')
DATA_DIR = os.path.join(paths.BASE, 'data')


def norm_name(s):
    """Series keys for matching: parentheticals dropped, alphanumerics only.
    (Same semantics as build.norm_name — kept local so filter/curate never
    import the build stage.)"""
    s = re.sub(r'\([^)]*\)', ' ', s or '')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def file_series():
    """Every series name in library.json and sequels.json, normalized.
    Best-effort, but LOUD: an unreadable file must never silently masquerade as
    'no series' (the review of #76: a corrupt sequels.json would quietly turn
    the guarantee off)."""
    names = set()
    for fname in ('library.json', 'sequels.json'):
        try:
            path, src = paths.personal(fname)
            if src == 'missing':
                continue
            with open(path) as f:
                data = json.load(f)
            for s in (data or {}).get('series', []):
                if not isinstance(s, dict):
                    continue
                for k in ('series', 'name'):
                    n = norm_name(s.get(k))
                    if n:
                        names.add(n)
        except Exception as e:
            print('sequels: %s unreadable (%s) — those series cannot be matched this run'
                  % (fname, str(e)[:60]))
    return names


def series_name(s):
    """A series name as a pick or candidate carries it, without a trailing
    volume number ('Mist Court #1' -> 'Mist Court')."""
    return re.sub(r'\s*(?:#|book|vol\.?)\s*[\d.]+\s*$', '', (s or '').strip(), flags=re.I).strip()


def _candidate_series(data_dir):
    """book id -> {title, author, series, series_num} from every candidates
    file, newest first. Older month files kept no series (the model's output
    has no series field), so their picks fall back to the candidate record."""
    out = {}
    for cf in sorted(glob.glob(os.path.join(data_dir, 'candidates-*.json')), reverse=True):
        try:
            with open(cf) as f:
                books = (json.load(f) or {}).get('books', [])
        except Exception as e:
            print('sequels: %s unreadable (%s)' % (os.path.basename(cf), str(e)[:60]))
            continue
        for b in books:
            k = book_key(b.get('title'), b.get('author'))
            if k and k not in out and (b.get('series') or '').strip():
                out[k] = {'title': b.get('title') or '', 'author': b.get('author') or '',
                          'series': b['series'], 'series_num': str(b.get('series_num') or '')}
    return out


def untracked(cfg_dir=None):
    """Series she left unticked on the Goodreads import (#93), normalized: the
    `untracked` list in added-books.json. Her marks never track these."""
    try:
        with open(os.path.join(cfg_dir or paths.cfg_dir(), 'added-books.json')) as f:
            names = (json.load(f) or {}).get('untracked') or []
    except FileNotFoundError:
        return set()
    except Exception as e:
        print('sequels: added-books.json unreadable (%s) — no series skipped' % str(e)[:60])
        return set()
    return {norm_name(n) for n in names if isinstance(n, str) and norm_name(n)}


def from_marks(data_dir=None, cfg_dir=None):
    """The series tracked from her marks: the series of every book marked read
    or loved that library.json and sequels.json do not already hold (by the
    same name match the sequel guarantee uses), less the series she left
    unticked on the Goodreads import. Nothing is written.

    -> [{'series': name, 'author': author, 'books': [{'title', 'num', 'id'}]}]
    sorted by series name."""
    import verdicts  # the reader-state reader and the book lookup (#83)
    data_dir = data_dir or DATA_DIR
    marks = verdicts.load_marks(cfg_dir, keep=TRACK_VERDICTS)
    if not marks:
        return []
    details = verdicts.book_details(data_dir)
    cands = _candidate_series(data_dir)
    existing = file_series()
    skip = untracked(cfg_dir)
    groups = {}
    for bid, _s, t in sorted(marks, key=lambda m: m[2]):
        d = details.get(bid) or {}
        c = cands.get(bid) or {}
        name = series_name(d.get('series') or c.get('series'))
        key = norm_name(name)
        if not key or key in skip or is_sequel({'series': name}, existing):
            continue
        title = d.get('title') or c.get('title') or ''
        author = d.get('author') or c.get('author') or ''
        g = groups.setdefault(key, {'series': name, 'author': author, 'books': []})
        if not g['author']:
            g['author'] = author
        num = str(d.get('series_num') or c.get('series_num') or '').strip()
        if not num:
            m = re.search(r'#\s*([\d.]+)', d.get('series') or c.get('series') or '')
            num = m.group(1) if m else ''
        g['books'].append({'title': title, 'num': num, 'id': bid})
    for g in groups.values():
        g['books'].sort(key=lambda b: (_num(b['num']), b['title'].lower()))
    return sorted(groups.values(), key=lambda g: g['series'].lower())


def _num(n):
    try:
        return float(n)
    except (TypeError, ValueError):
        return 9999.0


def report_line(marked):
    """The run report's line, zeros included."""
    names = ', '.join(g['series'] for g in marked)
    return 'series: %d tracked from your marks%s' % (len(marked), (' (%s)' % names) if names else '')


def tracked_series(data_dir=None, cfg_dir=None, log=None):
    """Every series name she is in, normalized: library.json, sequels.json and
    the series tracked from her read and loved marks."""
    names = file_series()
    marked = from_marks(data_dir, cfg_dir)
    if log:
        log(report_line(marked))
    for g in marked:
        names.add(norm_name(g['series']))
    return names


def is_sequel(book, names):
    """True when the candidate continues a series she is already in.

    Exact normalized match first; then a guarded containment fallback, because
    real name drift is normal ('The Empyrean' vs 'Empyrean' vs 'The Empyrean
    #4') and build.py's own series matching is fuzzy for the same reason. The
    6-char floor keeps a short series word from matching half the catalog."""
    if not names:
        return False
    n = norm_name((book or {}).get('series'))
    if not n:
        return False
    if n in names:
        return True
    if len(n) < 6:
        return False
    return any(len(t) >= 6 and (n in t or t in n) for t in names)
