#!/usr/bin/env python3
"""The Shelf pipeline — stage 1: fetch candidates, with provenance.

Discovery runs entirely on Apple Books (the only source still live — the old
charts-RSS / Reddit / Goodreads / romance.io fetches all died in 2026; see
the skill's references/sources-and-fetch.md). Two nets:

  · lane terms   — one query per entry in config.json `lane_terms`
  · author lane  — one query per author: the watched authors the reader keeps
                   in the app (CFG_DIR/authors.json — Settings → Authors; this
                   stage reads it, the UI ticket writes it) PLUS the authors of
                   every series she tracks (data/library.json, data/sequels.json,
                   seed-reads.json, config `author_lane_extra`).

Every record keeps WHERE it was found (query + lane). For each record inside
the pool window the book's own Apple page is read once — cached in
pipeline/data/publisher-cache.json — for publisher, language, isbn and
audiobook availability. Foreign-language editions are excluded; audiobook
availability rides ON the ebook record (no blank-title audiobook records,
no ebook/audio twins).

Stdlib only. Per-call failures are counted and reported: nothing fails
silently. The run ends with a per-lane report (candidates each lane produced,
in the run's window and over the rolling 30 days).
"""
import json, os, re, sys, time, urllib.request, urllib.parse, html as htmllib
from datetime import date, datetime, timedelta
import paths  # shared resolver: reader data lives on the volume (CFG_DIR)

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
# SHELF_MODE=scheduled -> the 1st-of-month drop curates the PREVIOUS month
# SHELF_MODE=adhoc     -> "curate now": rolling last 30 days ending today
MODE = os.environ.get('SHELF_MODE', 'scheduled')
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36'}
TODAY = date.today()
POOL_BACK = TODAY - timedelta(days=int(CFG.get('pool_back_days', 120)))
POOL_FWD = TODAY + timedelta(days=int(CFG.get('pool_forward_days', 60)))


def cfg_dir():
    """Where settings/state live — the shared resolver (volume first)."""
    return paths.cfg_dir()


# ---------- throttled, counted fetching ----------
_last = {'t': 0.0}
STATS = {'search': {'calls': 0, 'failed': 0}, 'pages': {'calls': 0, 'failed': 0, 'cache_hits': 0},
         'failures': []}


def _gap(sec):
    dt = time.time() - _last['t']
    if dt < sec:
        time.sleep(sec - dt)
    _last['t'] = time.time()


def _get(url, gap, bucket, tries=3):
    """Fetch a URL with a per-host politeness gap; count + report failures.
    Apple's search 429s in bursts — back off hard, retry, and only then give up."""
    err = ''
    for attempt in range(tries):
        _gap(gap)
        STATS[bucket]['calls'] += 1
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            err = str(e)[:110]
            if attempt < tries - 1:
                time.sleep(12 if '429' in err else 3)  # rate limit -> sit out; else short pause
    STATS[bucket]['failed'] += 1
    STATS['failures'].append('%s: %s' % (url[:95], err))
    return None


def search(term, limit=100):
    q = urllib.parse.urlencode({'term': term, 'media': 'ebook', 'entity': 'ebook',
                                'limit': limit, 'country': CFG.get('apple_country', 'us')})
    raw = _get('https://itunes.apple.com/search?%s' % q, 0.9, 'search')
    if not raw:
        return []
    try:
        return (json.loads(raw) or {}).get('results') or []
    except Exception as e:
        STATS['search']['failed'] += 1
        STATS['failures'].append('search "%s": bad JSON %s' % (term, str(e)[:60]))
        return []


# ---------- record pool ----------
RECORDS = {}   # normkey -> record
DESCS = {}     # normkey -> description (transient; used for the language screen)
JUNK = ('summary of', 'study guide', 'sparknotes', 'workbook', 'box set', 'boxset',
        'collection set', 'omnibus', 'cliffsnotes')


def normkey(a, b):
    return (re.sub(r'[^a-z0-9]', '', (a or '').lower()), re.sub(r'[^a-z0-9]', '', (b or '').lower()))


def norm_date(s):
    if not s:
        return None
    s = str(s).strip()
    if re.match(r'\d{4}-\d{2}-\d{2}', s):
        return s[:10]
    for fmt in ('%d %b %Y', '%b %d %Y', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def add(query, lane, it):
    """Add one Apple search result, with provenance, merging across queries."""
    title = (it.get('trackName') or it.get('collectionName') or '').strip()
    author = (it.get('artistName') or '').strip()
    if not title or title.lower() in ('untitled',):
        return None
    low = title.lower()
    if any(j in low for j in JUNK) or low.startswith(('summary', 'study guide', 'sparknotes')):
        return None
    key = normkey(title, author)
    rec = RECORDS.get(key)
    if rec is None:
        rec = {
            'source': 'apple-search', 'title': title, 'author': author,
            'date': norm_date(it.get('releaseDate')),
            'genre': ' '.join((it.get('genres') or [])[:3]),
            'url': (it.get('trackViewUrl') or '').split('?')[0],
            'trackId': it.get('trackId'),
            'rating': it.get('averageUserRating'),
            'rating_count': it.get('userRatingCount'),
            'publisher': '', 'pub_known': False, 'language': '', 'isbn': '',
            'audio': False, 'ebook': True,
            'lane': lane or '', 'lanes': ([lane] if lane else []), 'found_by': [query],
            'pub_source': '',
        }
        RECORDS[key] = rec
        DESCS[key] = it.get('description') or ''
    else:
        if query not in rec['found_by']:
            rec['found_by'].append(query)
        if lane and lane not in rec['lanes']:
            rec['lanes'].append(lane)
        if not rec['lane'] and lane:
            rec['lane'] = lane
        # fill anything the first sighting lacked
        for f, v in (('date', norm_date(it.get('releaseDate'))), ('genre', ' '.join((it.get('genres') or [])[:3])),
                     ('url', (it.get('trackViewUrl') or '').split('?')[0]), ('trackId', it.get('trackId')),
                     ('rating', it.get('averageUserRating')), ('rating_count', it.get('userRatingCount'))):
            if not rec.get(f) and v:
                rec[f] = v
        if not DESCS.get(key):
            DESCS[key] = it.get('description') or ''
    return rec


# ---------- the author lane ----------
def author_lane():
    """Watched authors (CFG_DIR/authors.json) + the authors of every tracked
    series. Returns list of {name, lane} — lane '' means "any lane"."""
    seen, out = {}, []

    def put(name, lane=''):
        name = (name or '').strip()
        k = re.sub(r'[^a-z0-9]', '', name.lower())
        if not k:
            return
        if k in seen:
            if lane and not seen[k].get('lane'):
                seen[k]['lane'] = lane
            return
        rec = {'name': name, 'lane': lane or '', 'why': []}
        seen[k] = rec
        out.append(rec)

    def lane_for(genre):
        g = (genre or '').lower()
        if 'sport' in g:
            return 'sport romance'
        if 'romantasy' in g or 'fantasy' in g:
            return 'romantasy'
        if 'contemporary' in g:
            return 'contemporary romance'
        return ''

    # 1) the watched list the reader keeps in the app (Settings → Authors)
    try:
        w = json.load(open(os.path.join(cfg_dir(), 'authors.json')))
        for a in (w.get('authors') or []):
            if isinstance(a, dict):
                nm = a.get('name') or ''
                put(nm, a.get('lane') or '')
            else:
                nm = a or ''
                put(nm)
            k = re.sub(r'[^a-z0-9]', '', str(nm).lower())
            if k and k in seen:
                seen[k]['why'].append('watched')
    except Exception:
        pass
    # 2) authors of every tracked series (volume first; blank installs stay quiet)
    lib_path, lib_src = paths.personal('library.json')
    if lib_src != 'missing':
        try:
            lib = json.load(open(lib_path))
            for s in lib.get('series', []):
                put(s.get('author'), lane_for(s.get('genre')))
        except Exception as e:
            STATS['failures'].append('library.json: %s' % str(e)[:60])
    seq_path, seq_src = paths.personal('sequels.json')
    if seq_src != 'missing':
        try:
            seq = json.load(open(seq_path))
            for s in seq.get('series', []):
                put(s.get('author'))
        except Exception as e:
            STATS['failures'].append('sequels.json: %s' % str(e)[:60])
    # 3) authors she reads 2+ books from (taste profile)
    seed_path, seed_src = paths.personal('seed-reads.json')
    if seed_src != 'missing':
        try:
            seed = json.load(open(seed_path))
            for a in (seed.get('taste_profile') or {}).get('authors_with_multiple_books', []):
                put(a)
        except Exception as e:
            STATS['failures'].append('seed-reads.json: %s' % str(e)[:60])
    # 4) the editorial extras (anchor authors outside the data files)
    for a in CFG.get('author_lane_extra', []):
        if isinstance(a, dict):
            put(a.get('name'), a.get('lane') or '')
        else:
            put(a)
    return out


# ---------- language screen ----------
EN_STOP = set(('the and of to a in is you her his she he it with for on that at from was were are as '
               'by an but not your their they this these those we our when what who how all one two '
               'will can her she has have had do does did been there here who what out up if into').split())


def foreign_reason(rec, key):
    """Cheap pre-screen before we spend a product-page fetch. Returns a reason
    string when the record is clearly not an English edition."""
    if any(ord(c) > 126 for c in rec['title']):
        return 'non-ascii title'
    desc = re.sub(r'&#?\w+;', ' ', re.sub(r'<[^>]+>', ' ', DESCS.get(key) or ''))
    words = re.findall(r"[a-zA-Z']+", desc)
    if len(words) >= 40:
        density = sum(1 for w in words if w.lower() in EN_STOP) / float(len(words))
        if density < 0.10:
            return 'description not English'
    return None


def english_lang(lang):
    return (not lang) or lang.lower().startswith('en')


# ---------- product pages: publisher · language · isbn · audiobook ----------
CACHE_PATH = os.path.join(BASE, CFG.get('output_dir', 'data'), 'publisher-cache.json')


def load_cache():
    try:
        return json.load(open(CACHE_PATH))
    except Exception:
        return {}


def page_series(html):
    """The series a book belongs to, from its Apple page: the JSON-LD
    isPartof block names it, the breadcrumb carries the number
    ('Book 3 - The Empyrean'). Returns {'series': str, 'num': str}."""
    ser = re.search(r'"isPartof"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"]{1,120})"', html)
    num = re.search(r'Book\s+(\d+)\s*-\s', html)
    return {'series': (ser.group(1).strip() if ser else ''),
            'num': (num.group(1) if num else '')}


def resolve_product(rec, cache):
    """Read the book's Apple page once (cached by trackId). Returns dict or None."""
    m = re.search(r'/id(\d+)', rec.get('url') or '')
    if not m:
        return None
    tid = m.group(1)
    if tid in cache:
        STATS['pages']['cache_hits'] += 1
        return cache[tid]
    html = _get(rec['url'], 0.35, 'pages')
    if html is None:
        return None
    pub = re.search(r'"publisher"\s*:\s*"([^"]{2,90})"', html)
    lang = re.search(r'"inLanguage"\s*:\s*"([^"]{2,20})"', html)
    isbn = re.search(r'"isbn"\s*:\s*"([^"]{8,20})"', html)
    audio = bool(re.search(r'books\.apple\.com/[a-z]{2}/audiobook/', html))
    ser = page_series(html)
    info = {'publisher': (pub.group(1).strip() if pub else ''),
            'language': (lang.group(1).strip() if lang else ''),
            'isbn': (isbn.group(1).strip() if isbn else ''),
            'audio': audio, 'series': ser['series'], 'num': ser['num'],
            'at': TODAY.isoformat()}
    cache[tid] = info
    return info


# ---------- main ----------
def run_window():
    """The window this RUN curates (what 'in window' means in the report)."""
    if MODE == 'adhoc':
        return TODAY - timedelta(days=30), TODAY
    y, m = TODAY.year, TODAY.month
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    first = date(py, pm, 1)
    nxt = date(y + 1, 1, 1) if (py, pm) == (y - 1, 12) else date(py, pm + 1, 1)
    return first, nxt - timedelta(days=1)


def in_range(d, lo, hi):
    if not d:
        return False
    return lo <= d <= hi


def main():
    outdir = os.path.join(BASE, CFG.get('output_dir', 'data'))
    os.makedirs(outdir, exist_ok=True)
    mon = TODAY.strftime('%Y-%m') if MODE == 'adhoc' else run_window()[0].strftime('%Y-%m')
    run_lo, run_hi = run_window()
    r30_lo = TODAY - timedelta(days=30)

    # ---- lane terms ----
    lane_terms = CFG.get('lane_terms') or {}
    term_count = 0
    for lane, terms in lane_terms.items():
        hits = 0
        for t in terms:
            term_count += 1
            for it in search(t, 100):
                if add(t, lane, it):
                    hits += 1
        print('[lane] %s: %d terms -> %d raw results' % (lane, len(terms), hits))

    # ---- author lane ----
    authors = author_lane()
    author_hits = {}
    for a in authors:
        n = 0
        for it in search(a['name'], 100):
            r = add('author:%s' % a['name'], a.get('lane') or '', it)
            if r:
                n += 1
        author_hits[a['name']] = n
    print('[author] %d authors queried -> %d raw results (%d authors with hits)'
          % (len(authors), sum(author_hits.values()),
             sum(1 for v in author_hits.values() if v)))

    # ---- pool window + language screens ----
    pooled, dropped_foreign = [], {'non-ascii title': 0, 'description not English': 0, 'page language': 0}
    undated = 0
    for key, rec in RECORDS.items():
        d = None
        try:
            d = date.fromisoformat(rec['date'][:10]) if rec.get('date') else None
        except Exception:
            d = None
        if d and not (POOL_BACK <= d <= POOL_FWD):
            continue  # outside the pool window (backlist or far future)
        if not d:
            undated += 1
        reason = foreign_reason(rec, key)
        if reason:
            dropped_foreign[reason] += 1
            continue
        pooled.append((key, rec))

    # ---- product pages (publisher / language / isbn / audio) ----
    cache = load_cache()
    kept = []
    for key, rec in pooled:
        info = resolve_product(rec, cache)
        if info:
            rec['publisher'] = info.get('publisher') or ''
            rec['pub_known'] = bool(rec['publisher'])
            rec['language'] = info.get('language') or ''
            rec['isbn'] = info.get('isbn') or ''
            rec['audio'] = bool(info.get('audio'))
            rec['pub_source'] = 'apple-page'
            rec['series'] = info.get('series') or ''
            rec['series_num'] = info.get('num') or ''
            if not english_lang(rec['language']):
                dropped_foreign['page language'] += 1
                continue
        kept.append(rec)
    try:
        json.dump(cache, open(CACHE_PATH, 'w'), indent=0)
    except Exception as e:
        STATS['failures'].append('publisher cache write: %s' % str(e)[:60])

    kept.sort(key=lambda r: (r.get('date') or '0000-00-00'), reverse=True)
    buckets = {}
    for r in kept:
        buckets.setdefault(r.get('lane') or 'author (any lane)', []).append(r)

    lanes_report = {}
    for lane in list(lane_terms.keys()) + ['author (any lane)']:
        recs = buckets.get(lane, [])
        lanes_report[lane] = {
            'pooled': len(recs),
            'run_window': sum(1 for r in recs if r.get('date') and in_range(date.fromisoformat(r['date']), run_lo, run_hi)),
            'last_30d': sum(1 for r in recs if r.get('date') and in_range(date.fromisoformat(r['date']), r30_lo, TODAY)),
            'terms': (lane_terms.get(lane) or []),
        }
    pub_n = sum(1 for r in kept if r.get('pub_known'))
    audio_n = sum(1 for r in kept if r.get('audio'))
    watched = {a['name'] for a in authors if 'watched' in (a.get('why') or [])}
    report = {
        'mode': MODE, 'generated': datetime.now().isoformat(),
        'pool_window': {'from': POOL_BACK.isoformat(), 'to': POOL_FWD.isoformat()},
        'run_window': {'from': run_lo.isoformat(), 'to': run_hi.isoformat()},
        'lanes': lanes_report,
        'authors': {'queried': len(authors), 'watched': sorted(watched),
                    'with_candidates': {k: v for k, v in author_hits.items() if v},
                    'watched_with_candidates': {k: v for k, v in author_hits.items() if v and k in watched}},
        'pool': {'kept': len(kept), 'undated': undated,
                 'foreign_dropped': dropped_foreign,
                 'publishers_resolved': pub_n, 'publishers_missing': len(kept) - pub_n, 'audio': audio_n},
        'sources': {'apple-search': dict(STATS['search']), 'product-pages': dict(STATS['pages']),
                    'removed_dead': ['apple-rss charts (404/timeout)', 'reddit (403)', 'goodreads (404)', 'romance.io (403)']},
        'failures': STATS['failures'][:20],
    }
    out = os.path.join(outdir, 'candidates-%s.json' % mon)
    json.dump({'fetched_at': datetime.now().isoformat(), 'window': {'mode': MODE, 'from': run_lo.isoformat(), 'to': run_hi.isoformat()},
               'report': report, 'books': kept}, open(out, 'w'), indent=1)

    # ---- the report (kept at the tail: the server logs the last 800 chars) ----
    rw = report['run_window']
    print('=== fetch report — mode %s · pool %s..%s · run window %s..%s ===' %
          (MODE, POOL_BACK, POOL_FWD, rw['from'], rw['to']))
    print('%-24s %7s %11s %9s' % ('lane', 'pooled', 'run-window', 'last-30d'))
    for lane in list(lane_terms.keys()) + ['author (any lane)']:
        lr = lanes_report[lane]
        print('%-24s %7d %11d %9d' % (lane, lr['pooled'], lr['run_window'], lr['last_30d']))
    print('queries: %d lane terms + %d authors · authors with candidates: %d'
          % (term_count, len(authors), len(report['authors']['with_candidates'])))
    wc = report['authors']['watched_with_candidates']
    print('watched authors: %d queried · %d with candidates%s'
          % (len(watched), len(wc), (' — ' + ', '.join(wc)) if wc else ''))
    print('pool: %d records · undated %d · foreign dropped %d %s · publishers %d/%d · audio %d'
          % (len(kept), undated, sum(dropped_foreign.values()), dropped_foreign, pub_n, len(kept), audio_n))
    print('sources: apple-search %d calls/%d failed · product pages %d calls/%d failed/%d cache-hits · removed dead: charts-rss, reddit, goodreads, romance.io'
          % (STATS['search']['calls'], STATS['search']['failed'], STATS['pages']['calls'], STATS['pages']['failed'], STATS['pages']['cache_hits']))
    for f in STATS['failures'][:5]:
        print('  ! %s' % f)
    print('candidates: %d -> %s' % (len(kept), out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
