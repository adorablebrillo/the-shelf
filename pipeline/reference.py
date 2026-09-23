#!/usr/bin/env python3
"""#47 — Goodreads as a monthly release reference.

Once per run, fetch that month's "most popular releases" list (one polite
request) and cross-check it against what the shelf already saw. For every
miss the job is find, not just flag:

  - on Apple: the normal search; found + in-window + screens pass -> enters
    the candidate pool source-tagged (found_by: ['goodreads']) and flows
    through filter/curate like any other candidate
  - Kindle-first: the book's own Goodreads page supplies publisher, release
    date, genres, ratings and cover -> a normal recommendable candidate with
    honest provenance (a Kindle-first self-pub with strong ratings is the
    indie-with-proof case, and the existing gate accepts Goodreads numbers)
  - only genuinely unobtainable data stays report-only — never dropped
    silently

Everything here is best-effort by design: any failure prints why, writes the
month's file with ok:false and the run continues. A missing reference line is
acceptable; a broken run is not. Volume stays tiny: the list + the pages of
missed books only, one request at a time with a polite gap.

Scraping is technically against Goodreads' ToS — keep the volume tiny,
read-only, and never on the critical path. The markup can change; the parsers
fail soft (None, never a raise).
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

import bookids
import fetch
import lanes
import paths
from shelf_state import exclusion_set
from windows import target_month

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
GAP = 1.2          # polite: one request at a time, with a gap
TIMEOUT = 25
CAP = 8            # at most this many misses are looked up per run (top of the list)


def _get(url, timeout=TIMEOUT):
    """One plain GET, browser-shaped, gzip-safe. Raises on failure — callers
    decide what a failure means (never the run)."""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if (r.headers.get('Content-Encoding') or '').lower() == 'gzip':
            raw = gzip.decompress(raw)
    return raw.decode('utf-8', 'replace')


def _next_data(html):
    """The page's Next.js data blob, or None (markup change -> fail soft)."""
    try:
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                      html or '', re.S)
        return json.loads(m.group(1)) if m else None
    except Exception:
        return None


def _apollo(j):
    try:
        return j['props']['pageProps']['apolloState']
    except Exception:
        return {}


def _ref(node, prefix):
    r = (node or {}).get('__ref') or ''
    return r if isinstance(r, str) and r.startswith(prefix) else None


def _strip(s, n=400):
    return re.sub(r'<[^>]+>', ' ', s or '').strip()[:n]


def parse_list(html):
    """The month's ranked list -> [{rank,title,author,url,cover,rating,
    rating_count,description}], or None when the page is not what we expect."""
    j = _next_data(html)
    if not j:
        return None
    ap = _apollo(j)
    tl = None
    for k, v in (ap.get('ROOT_QUERY') or {}).items():
        if k.startswith('getTopList'):
            tl = v
            break
    if not isinstance(tl, dict) or not tl.get('edges'):
        return None
    out = []
    for e in tl['edges']:
        b = ap.get(_ref(e.get('node'), 'Book:'))
        if not isinstance(b, dict):
            continue
        title = (b.get('title') or '').strip()
        if not title:
            continue                     # a title-less stub is a parse change, not a miss
        author = ''
        c = ap.get(_ref((b.get('primaryContributorEdge') or {}).get('node'), 'Contributor:'))
        if isinstance(c, dict):
            author = (c.get('name') or '').strip()
        rating = count = None
        w = ap.get(_ref(b.get('work'), 'Work:'))
        if isinstance(w, dict):
            st = w.get('stats') or {}
            rating, count = st.get('averageRating'), st.get('ratingsCount')
        out.append({
            'rank': e.get('rank'),
            'title': title,
            'author': author,
            'url': b.get('webUrl') or '',
            'cover': b.get('imageUrl') or '',
            'rating': rating,
            'rating_count': count,
            'description': _strip(b.get('description')),
        })
    return out or None


def parse_book(html, url=None):
    """A Goodreads book page -> {title,author,publisher,date,rating,
    rating_count,genres,cover,description}, or None (fail soft). When the
    requested URL carries a book id, prefer the node that IS that book — a
    page can hold several Book nodes, and publishing the wrong one under the
    entry's URL is worse than none."""
    j = _next_data(html)
    if not j:
        return None
    ap = _apollo(j)
    m = re.search(r'/show/(\d+)', url or '')
    want = m.group(1) if m else None
    b = None
    for k, v in ap.items():
        if k.startswith('Book:') and isinstance(v, dict):
            if want and (str(v.get('legacyId') or '') == want or want in (v.get('webUrl') or '')):
                b = v
                break
            if b is None:
                b = v
    if not isinstance(b, dict):
        return None
    author = ''
    c = ap.get(_ref((b.get('primaryContributorEdge') or {}).get('node'), 'Contributor:'))
    if isinstance(c, dict):
        author = (c.get('name') or '').strip()
    det = b.get('details') or {}
    rating = count = None
    w = ap.get(_ref(b.get('work'), 'Work:'))
    if isinstance(w, dict):
        st = w.get('stats') or {}
        rating, count = st.get('averageRating'), st.get('ratingsCount')
    genres = []
    for g in (b.get('bookGenres') or []):
        gn = ((g or {}).get('genre') or {}).get('name') if isinstance(g, dict) else None
        if gn:
            genres.append(gn)
    return {
        'title': (b.get('title') or '').strip(),
        'author': author,
        'publisher': (det.get('publisher') or '').strip(),
        'date': _ms_date(det.get('publicationTime')),
        'rating': rating,
        'rating_count': count,
        'genres': genres,
        'cover': b.get('imageUrl') or '',
        'description': _strip(b.get('description')),
    }


def _ms_date(ts):
    try:
        return datetime.utcfromtimestamp(int(ts) / 1000.0).strftime('%Y-%m-%d')
    except Exception:
        return None


def _title_match(a, b):
    """Loose match for an Apple result against a Goodreads title: containment
    either way, or enough distinctive-token overlap. (The #42 lesson: a first
    result is not the book — a single shared word is not a match.)"""
    x = re.sub(r'[^a-z0-9 ]+', ' ', (a or '').lower()).strip()
    y = re.sub(r'[^a-z0-9 ]+', ' ', (b or '').lower()).strip()
    if not x or not y:
        return False
    if x in y or y in x:
        return True
    tx = {w for w in x.split() if len(w) > 3}
    ty = {w for w in y.split() if len(w) > 3}
    shared = tx & ty
    if not shared:
        return False
    if len(tx) <= 1 or len(ty) <= 1:
        # a one-word title only matches a one-word title with the same word
        return len(tx) == 1 and len(ty) == 1
    return len(shared) >= 2


def _author_match(a, b):
    """Loose author check: punctuation/initials vary between catalogs, so a
    shared meaningful token counts. Strict enough to reject a same-title,
    different-writer result (a shared first name is not a match), and it fails
    CLOSED when one side carries a name and the other does not."""
    def toks(s):
        return {w for w in re.sub(r'[^a-z ]+', ' ', (s or '').lower()).split() if len(w) > 2}
    ta, tb = toks(a), toks(b)
    if not ta and not tb:
        return True                      # nothing to compare on either side
    if not ta or not tb:
        return False                     # one side names the writer — the other must too
    return len(ta & tb) >= min(2, len(ta), len(tb))


def fetch_month(mon):
    """mon 'YYYY-MM' -> the month page's html. Raises on failure."""
    y, m = mon.split('-')
    return _get('https://www.goodreads.com/book/popular_by_date/%s/%d' % (y, int(m)))


def seen_keys():
    """Everything the shelf already saw, in both normalizations."""
    keys = set()
    try:
        ex = exclusion_set()
        for k in ex:
            keys.add(k)
    except Exception:
        pass
    try:
        outdir = os.path.join(paths.BASE, fetch.CFG.get('output_dir', 'data'))
        files = sorted([f for f in os.listdir(outdir) if f.startswith('candidates-')])
        if files:
            pool = json.load(open(os.path.join(outdir, files[-1]))).get('books', [])
            for b in pool:
                keys.add(fetch.normkey(b.get('title'), b.get('author')))
                keys.add(bookids.book_key(b.get('title'), b.get('author')))
    except Exception:
        pass
    return keys


def _entry_keys(e):
    return {fetch.normkey(e.get('title'), e.get('author')),
            bookids.book_key(e.get('title'), e.get('author'))}


def apple_candidate(e, mon, cache=None):
    """Look the miss up on Apple with the normal search, then read its Apple
    page once (the same resolve the fetch does — without it the publisher is
    unknown and the curator's gate would skip a real find). Returns a
    candidate dict (source-tagged) or None."""
    try:
        recs = fetch.search('%s %s' % (e['title'], e['author']))
    except Exception:
        return None
    for it in recs or []:
        title = (it.get('trackName') or it.get('collectionName') or '').strip()
        if not title or not _title_match(e['title'], title):
            continue
        author = (it.get('artistName') or '').strip()
        if not _author_match(e.get('author'), author):
            continue                     # same title, different writer
        if not (e.get('author') or '').strip():
            # the entry carries no writer: only an exact title may stand in
            norm = lambda s: re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()
            if norm(e['title']) != norm(title):
                continue
        cand = {
            'source': 'apple-search', 'title': title, 'author': author,
            'date': fetch.norm_date(it.get('releaseDate')),
            'genre': ' '.join((it.get('genres') or [])[:3]),
            'url': (it.get('trackViewUrl') or '').split('?')[0],
            'trackId': it.get('trackId'),
            'rating': it.get('averageUserRating'),
            'rating_count': it.get('userRatingCount'),
            'publisher': '', 'pub_known': False, 'language': '', 'isbn': '',
            'audio': False, 'ebook': True,
            'lane': '', 'lanes': [], 'found_by': ['goodreads'],
            'pub_source': 'apple-search',
        }
        try:
            lane = lanes.lane_of(cand['genre']) or ''
        except Exception:
            lane = ''
        cand['lane'] = lane
        cand['lanes'] = ([lane] if lane else [])
        try:
            info = fetch.resolve_product(cand, cache if cache is not None else {})
            if info:
                cand['publisher'] = info.get('publisher') or ''
                cand['pub_known'] = bool(cand['publisher'])
                cand['language'] = info.get('language') or ''
                cand['isbn'] = info.get('isbn') or ''
                cand['audio'] = bool(info.get('audio'))
        except Exception:
            pass
        return cand
    return None


def kindle_candidate(e, mon):
    """No Apple presence: the book's own Goodreads page supplies what a
    candidate needs. Returns a candidate dict or None."""
    try:
        time.sleep(GAP)
        data = parse_book(_get(e['url']), e['url'])
    except Exception:
        return None
    if not data or not data.get('title'):
        return None
    if e.get('title') and not _title_match(e['title'], data['title']):
        return None                      # the page did not answer for this entry
    genres = data.get('genres') or []
    try:
        lane = lanes.lane_of(' '.join(genres)) or ''
    except Exception:
        lane = ''
    return {
        'source': 'goodreads-page', 'title': data['title'], 'author': data['author'] or e['author'],
        # never invented: an undated book stays undated and the filter lets
        # the model judge it (a synthetic month-day would read as in-window)
        'date': data.get('date'),
        'genre': ' '.join(genres[:3]),
        'url': e['url'],
        'trackId': None,
        'rating': data.get('rating'), 'rating_count': data.get('rating_count'),
        'publisher': data.get('publisher') or '', 'pub_known': bool(data.get('publisher')),
        'language': 'English', 'isbn': '', 'audio': False, 'ebook': True,
        'lane': lane, 'lanes': ([lane] if lane else []), 'found_by': ['goodreads'],
        'pub_source': 'goodreads-page',
        'cover': data.get('cover') or e.get('cover') or '',
        'description': data.get('description') or e.get('description') or '',
    }


def main():
    mon = target_month(fetch.MODE)
    outdir = os.path.join(paths.BASE, fetch.CFG.get('output_dir', 'data'))
    ref_path = os.path.join(outdir, 'reference-%s.json' % mon)
    report = {'month': mon, 'fetched_at': datetime.now().isoformat(), 'ok': False,
              'listed': 0, 'seen': 0, 'added': [], 'unobtainable': [], 'reason': ''}

    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception as ex:
        print('goodreads reference: 0 — output dir unwritable (%s) (run continues)'
              % str(ex)[:80])
        return 0

    def write():
        """Best-effort by design: a file that cannot be written must not break
        the run either."""
        try:
            with open(ref_path, 'w') as f:
                json.dump(report, f, indent=1)
            return True
        except Exception as ex:
            print('goodreads reference: %d listed — reference file unwritable (%s) (run continues)'
                  % (report['listed'], str(ex)[:80]))
            return False

    try:
        html = fetch_month(mon)
    except Exception as e:
        report['reason'] = 'list fetch failed: %s' % str(e)[:120]
        write()
        print('goodreads reference: 0 — %s (run continues)' % report['reason'])
        return 0

    entries = parse_list(html)
    if not entries:
        report['reason'] = 'list parse failed (markup change?)'
        write()
        print('goodreads reference: 0 — %s (run continues)' % report['reason'])
        return 0

    report['listed'] = len(entries)
    seen = seen_keys()
    misses = [e for e in entries if not (_entry_keys(e) & seen)]
    report['seen'] = len(entries) - len(misses)
    report['capped'] = len(misses) > CAP
    if report['capped']:
        misses = misses[:CAP]

    found = []                                   # (entry, candidate, via)
    cache = fetch.load_cache()
    for e in misses:
        try:
            c = apple_candidate(e, mon, cache)
            if c and c.get('date'):
                found.append((e, c, 'apple'))
                continue
            c = kindle_candidate(e, mon)
            if c:
                found.append((e, c, 'goodreads-page'))
            else:
                report['unobtainable'].append({'title': e['title'], 'author': e['author'],
                                               'url': e['url'],
                                               'reason': 'no Apple match, page unreadable'})
        except Exception as ex:
            report['unobtainable'].append({'title': e['title'], 'author': e['author'],
                                           'url': e['url'], 'reason': str(ex)[:120]})
    try:
        json.dump(cache, open(fetch.CACHE_PATH, 'w'), indent=0)
    except Exception:
        pass

    # a book counts as added only once it is IN the pool — the run line is the
    # operator's truth, and 'found but not appended' must read as a failure
    added = 0
    report['ok'] = True
    if found:
        try:
            src = os.path.join(outdir, 'candidates-%s.json' % mon)   # this month only
            if not os.path.exists(src):
                raise IOError('no candidates-%s.json to append to' % mon)
            blob = json.load(open(src))
            have = {fetch.normkey(b.get('title'), b.get('author')) for b in blob.get('books', [])}
            fresh = [c for (e, c, via) in found
                     if fetch.normkey(c.get('title'), c.get('author')) not in have]
            blob.setdefault('books', []).extend(fresh)
            with open(src, 'w') as f:
                json.dump(blob, f, indent=1)
            added = len(fresh)
            freshkeys = {fetch.normkey(c.get('title'), c.get('author')) for c in fresh}
            for (e, c, via) in found:
                if fetch.normkey(c.get('title'), c.get('author')) in freshkeys:
                    report['added'].append({'title': c.get('title') or e['title'],
                                            'entry_title': e['title'],
                                            'author': c.get('author') or e['author'],
                                            'via': via, 'url': e['url'],
                                            'trackId': c.get('trackId')})
        except Exception as ex:
            report['reason'] = 'candidates append failed: %s' % str(ex)[:120]
            report['ok'] = False
    write()

    n_apple = len([1 for (e, c, via) in found if via == 'apple'])
    n_kindle = len(found) - n_apple
    apple_calls = fetch.STATS['search']['calls'] + fetch.STATS['pages']['calls']
    apple_failed = fetch.STATS['search']['failed'] + fetch.STATS['pages']['failed']
    cap_note = (' (looked up the top %d by rank)' % CAP) if report['capped'] else ''
    if report['ok']:
        line = ('goodreads reference: %d listed, %d already seen, %d missed -> '
                '%d found (%d Apple, %d Kindle-first), %d unobtainable, %d added to the pool%s '
                '[apple %d calls/%d failed]'
                % (report['listed'], report['seen'], len(misses), len(found), n_apple, n_kindle,
                   len(report['unobtainable']), added, cap_note, apple_calls, apple_failed))
    else:
        line = ('goodreads reference: %d listed, %d already seen, %d missed -> '
                '%d found, %d unobtainable — APPEND FAILED (%s): nothing entered the pool%s'
                % (report['listed'], report['seen'], len(misses), len(found),
                   len(report['unobtainable']), report['reason'], cap_note))
    titles = ', '.join(a['title'] for a in report['added'][:6])
    print(line + ((' — %s' % titles) if titles else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
