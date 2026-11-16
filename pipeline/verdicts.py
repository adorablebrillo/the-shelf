#!/usr/bin/env python3
"""The Shelf — her verdicts teach the model (#83).

The reader state stores one code per marked book (the canonical book_key) and
no titles. Before the curation call, this module turns those codes back into
books the model can read — title, author, series, lane, tropes — and hands
curate three lists, newest mark first:

- loved      (at most 25)  lean toward these
- want       (at most 15)  a mild yes
- not for me (at most 25)  lean away from these

It also owns the one rule for the model's optional `because` field: it is kept
only when it names a book in her loved or want list.
"""
import glob, json, os, re
import paths
from bookids import book_key
from lanes import lane_of

CAPS = {'loved': 25, 'want': 15, 'not_for_me': 25}
# reader-state value -> list name ('skip' is the stored value of "not for me")
STATE_LIST = {'loved': 'loved', 'want': 'want', 'skip': 'not_for_me'}
BECAUSE_VERDICTS = ('loved', 'want')


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print('verdicts: %s unreadable (%s)' % (os.path.basename(path), str(e)[:80]))
        return None


def book_details(data_dir):
    """Canonical id -> {title, author, series, lane, tropes} for every book the
    shelf has ever shown: past month picks (richest: lane and tropes), then the
    books she added by search (added-books.json, #84), then the volumes of
    library.json and sequels.json. The first source to name a book wins, so a
    month pick's details beat a bare series volume."""
    out = {}

    def add(title, author, **kw):
        k = book_key(title, author)
        if not k or k in out:
            return
        d = {'title': title, 'author': author or ''}
        d.update({x: v for x, v in kw.items() if v})
        out[k] = d

    for mf in sorted(glob.glob(os.path.join(data_dir, 'month-*.json')), reverse=True):
        body = _load(mf) or {}
        for b in body.get('books', []):
            add(b.get('title') or '', b.get('author') or '', series=b.get('series') or '',
                series_num=str(b.get('series_num') or ''),
                lane=lane_of(b) if b.get('genre') else '', tropes=b.get('tropes') or [])

    added = _load(os.path.join(paths.cfg_dir(), 'added-books.json')) or {}
    for b in added.get('books', []) or []:
        add(b.get('title') or '', b.get('author') or '', series=b.get('series') or '',
            series_num=str(b.get('series_num') or ''),
            lane=lane_of(b) if b.get('genre') else '')

    lib_path = paths.personal('library.json')[0]
    seq_path = paths.personal('sequels.json')[0]
    seq = (_load(seq_path) or {}).get('series', [])
    for ser in seq:
        for nb in ser.get('next_books', []) or []:
            add(nb.get('title') or nb.get('t') or '', ser.get('author') or '',
                series=ser.get('series') or '')
    seq_authors = {re.sub(r'[^a-z0-9]', '', (s.get('series') or '').lower()): s.get('author')
                   for s in seq if s.get('author')}
    for ser in (_load(lib_path) or {}).get('series', []):
        name = ser.get('name') or ''
        a = (ser.get('author') or '').strip() or seq_authors.get(
            re.sub(r'[^a-z0-9]', '', re.sub(r'\([^)]*\)', ' ', name).lower()), '')
        for t in ser.get('books', []):
            add(t, a, series=name)
    return out


def load_marks(cfg_dir=None, keep=STATE_LIST):
    """[(id, state, t)] from the server's reader-state.json, for the states in
    `keep` (default: the three lists the model reads). A cleared mark (s: null)
    and the reading flag are not verdicts."""
    rs = os.path.join(cfg_dir or paths.cfg_dir(), 'reader-state.json')
    state = _load(rs) or {}
    out = []
    for bid, st in (state.get('states') or {}).items():
        if isinstance(st, dict) and st.get('s') in keep:
            out.append((bid, st['s'], int(st.get('t') or 0)))
    return out


def her_verdicts(marks, details, caps=CAPS):
    """-> (lists, missing). lists: {'loved': [...], 'want': [...],
    'not_for_me': [...]}, each newest mark first and capped. missing: how many
    marks had no book details (counted, never sent)."""
    lists = {k: [] for k in caps}
    missing = 0
    for bid, s, _t in sorted(marks, key=lambda m: m[2], reverse=True):
        d = details.get(bid)
        if not d:
            missing += 1
            continue
        name = STATE_LIST[s]
        if len(lists[name]) < caps[name]:
            lists[name].append(dict(d))
    return lists, missing


def report_line(lists, missing):
    return ('verdicts: sent %d loved · %d want · %d not for me to the model '
            '(%d marks had no book details)'
            % (len(lists['loved']), len(lists['want']), len(lists['not_for_me']), missing))


def _title_key(s):
    return book_key(s, '')


def keep_because(book, lists):
    """The model's `because` is kept only when it names a book in her loved or
    want list; it is then stored as {title, verdict} with her book's own title.
    Anything else — a not-for-me book, an unmarked book, junk — is dropped."""
    raw = book.pop('because', None)
    if isinstance(raw, dict):
        raw = raw.get('title')
    if not isinstance(raw, str) or not raw.strip():
        return book
    want = _title_key(raw)
    for verdict in BECAUSE_VERDICTS:
        for d in lists.get(verdict, []):
            if _title_key(d['title']) == want:
                book['because'] = {'title': d['title'], 'verdict': verdict}
                return book
    return book


def because_line(because):
    """The one line a pick card shows, or '' when there is nothing kept."""
    if not isinstance(because, dict):
        return ''
    t = (because.get('title') or '').strip()
    v = because.get('verdict')
    if not t or v not in BECAUSE_VERDICTS:
        return ''
    return 'because you %s %s' % ('loved' if v == 'loved' else 'wanted', t)
