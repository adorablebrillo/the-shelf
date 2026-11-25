#!/usr/bin/env python3
"""#51 — a real synopsis for every book the shelf renders.

Her words (2026-09-22): the cards' model-written one-line hooks are "extremely
scarce or none at all" — they don't tell her whether she'll like a book. The
real blurbs exist at the sources, so every book the shelf renders carries one:

  cache  ->  the book's Goodreads page  ->  the Apple description  ->  honest none

The Goodreads side is a title+author search, then the matched book page's own
description (the #47 plumbing: the page's Next.js payload, never the markup).
The Apple side is the iTunes catalog description for the same title+author —
the issue's fallback. When neither has one, the book says so plainly; a blurb
is never invented.

Cache: pipeline/data/synopsis-cache.json (the volume), keyed by the canonical
book id — a book is looked up ONCE ever; rebuilds, container boots and
pageviews never refetch. A definitive miss caches 'none' (delete the entry to
re-attempt by hand); a request failure is never cached — the next build
retries it. An Apple copy taken only because Goodreads did not answer (its bot
challenge, an outage, a page we cannot read) is shown at once but cached with
`retry: 'goodreads'`: a later build asks Goodreads again, after the books with
no blurb at all, and the Apple copy becomes final only when Goodreads answers
that it has none.

Politeness: one book at a time, >=1.2s between requests and >=10s between
Goodreads requests (config `goodreads_gap_seconds`), no more Goodreads
requests in a build once Goodreads has answered with its bot challenge, new
books ask Goodreads only in the first two-thirds of the build, and a
per-build time budget (config `synopsis_budget_seconds`, default 180s) so a
cold cache can never blow the boot rebuild's 300s timeout — the fill continues on the next
build, and the run report says exactly how far it got. Everything is wrapped:
a synopsis failure never breaks a build or a run.

Scraping is technically against Goodreads' ToS — keep the volume tiny,
read-only, never on the critical path. The markup can change; the parsers fail
soft (None, never a raise).
"""
import html as htmllib
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime

import bookids
import reference as R   # the #47 plumbing: polite GET, Next.js parse, matchers

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))

CACHE_NAME = 'synopsis-cache.json'
DESC_CAP = 2000       # a blurb, not a chapter
GAP = 1.2             # polite: one request at a time, never faster than this
# Goodreads answers a client without a browser with its bot challenge after a
# few requests. Measured 2026-11 from one address: at a 1.2s pace the second
# book's search was challenged in 2 runs of 2; at a 10s pace 3 runs of 4 read
# every search and book page, and the other was challenged at the second
# search. The pace lowers the odds; attach() handles the challenge itself.
GOODREADS_GAP = float(CFG.get('goodreads_gap_seconds', 10))
# At that pace a new book costs about 20s of Goodreads (search + page), so a
# big batch — a Goodreads import — would leave most books 'not fetched yet'
# for many builds. A new book asks Goodreads only in this first share of the
# build's budget; past it, new books take Apple's copy, marked for retry.
GOODREADS_SHARE = 2 / 3
DEFAULT_BUDGET = 180  # seconds of fetching per build (config-overridable)

_last = {'t': 0.0, 'goodreads': 0.0}


def _get(url, timeout=25):
    """One polite GET: at least GAP seconds after the previous request, and
    at least GOODREADS_GAP after the previous Goodreads request."""
    goodreads = '//www.goodreads.com/' in url
    now = time.time()
    wait = GAP - (now - _last['t'])
    if goodreads:
        wait = max(wait, GOODREADS_GAP - (now - _last['goodreads']))
    if wait > 0:
        time.sleep(wait)
    _last['t'] = time.time()
    if goodreads:
        _last['goodreads'] = _last['t']
    return R._get(url, timeout=timeout)


def _norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def _clean(raw, cap=0):
    """Description HTML -> honest plain text (paragraph breaks kept as \\n).
    Never invents text. Unescape FIRST: Apple's copy arrives with its markup
    HTML-escaped ('&lt;b&gt;'), so a strip before the unescape would leave
    literal tags in the blurb."""
    s = htmllib.unescape(raw or '')
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'[ \t\r\f\v]+', ' ', s)
    s = re.sub(r'\s*\n\s*', '\n', s)
    s = re.sub(r'\n{2,}', '\n', s).strip()
    return s[:cap].strip() if cap else s


# Apple's catalog copy (and some publisher blurbs) open with marketing — a
# bestseller line, a '•'-separated accolade list, a 'now a movie' tagline —
# before the actual blurb. With the card's clamped preview showing only the
# first lines, that lead is what the reader would see instead of the story.
_MKT = ('bestseller', 'best seller', 'bestselling', 'new york times', 'usa today',
        'tv series', 'now a movie', 'acclaim', 'award', 'praise for', 'book of the year',
        'copies sold', 'tiktok sensation', 'amazon best', 'apple best', 'barnes & noble',
        'npr ', 'audible', 'hudson book', 'nominated', 'winner of', 'instant #1',
        'discover the', 'reading order', 'edition')


def _lead_trim(text):
    """Drop a LEADING run of marketing/praise so the card shows story, not ads.

    Two conservative stages:
      · paragraph stage — while more than one paragraph remains, drop a leading
        paragraph that is SHORT and carries a marketing or quotation signal
        (praise quotes, taglines and accolade blocks all do; the blurb is the
        substantial paragraph and is never dropped);
      · sentence stage — drop leading short sentences that carry a marketing
        marker, or an accolade LIST (bullet-separated).

    The last unit is never eaten, and a trim that would leave a stub leaves the
    original standing."""
    s = (text or '').strip()
    if not s:
        return s
    paras = [p.strip() for p in s.split('\n') if p.strip()]
    while len(paras) > 1 and _lead_para(paras[0]):
        paras = paras[1:]
    parts = re.split(r'(?<=[.!?])\s+', ' '.join(paras))
    i = 0
    while i < len(parts) - 1:
        u = parts[i]
        low = u.lower()
        bullet = '\u2022' in u or ' \u2219 ' in u
        mkt = len(u) < 100 and any(m in low for m in _MKT)
        if bullet or mkt or low.startswith(('accolades', 'praise for')):
            i += 1
            continue
        break
    out = ' '.join(parts[i:]).strip()
    return out if len(out) >= 40 else s


def _lead_para(p):
    """A leading paragraph that is not the story. The blurb is the first
    SUBSTANTIAL paragraph that is not a bullet list — that one stops the trim.
    Anything before it must carry a marketing or quotation signal (praise
    quotes, taglines and accolade blocks all do)."""
    if len(p) >= 200 and p.count('\u2022') < 3:
        return False
    low = p.lower()
    return (any(m in low for m in _MKT) or '"' in p or '\u201d' in p
            or '\u2014' in p or '\u2022' in p)


def _final(text):
    """The text a source hands over: cleaned (both sources can arrive with
    markup — Apple's is even HTML-escaped), lead-trimmed, then capped."""
    return _lead_trim(_clean(text))[:DESC_CAP].strip()


MIN_BLURB = 80   # a real blurb is longer; '1' is a page artifact, not a blurb


def _usable(text):
    """A description worth publishing: long enough to be a blurb. A stub (a
    stray '1', a placeholder) is treated as nothing — never shipped."""
    t = _final(text or '')
    return t if len(t) >= MIN_BLURB else ''


def eligible(title):
    """A book that can be looked up at all: a real title — never an
    unannounced stub ('Untitled', 'TBA'), which gets no lookup."""
    t = (title or '').strip()
    if not t:
        return False
    n = re.sub(r'[^a-z0-9]', '', t.lower())
    return bool(n) and not n.startswith('untitled') and n not in ('tba', 'tbd', 'titletba')


def _entry_ok(want_title, want_author, got_title, got_author):
    """A search result is this book only when the title matches AND — when the
    entry names a writer — the author matches too. A single shared word is not
    a match (#42's lesson, #47's matchers), and a boxed set / study guide that
    happens to carry this book's name is not this book."""
    if _junk_title(got_title):
        return False
    if not R._title_match(want_title, got_title):
        return False
    if (want_author or '').strip():
        return R._author_match(want_author, got_author)
    return _norm(want_title) == _norm(got_title)   # no writer to check: exact title only


# A collection/boxed set that CONTAINS this book carries its name in the title
# ('The Empyrean Series 3 Books Collection Set: Fourth Wing, Iron Flame, Onyx
# Storm', 'Throne of Glass, A Court of Thorns and Roses 2 Book Set Collection')
# — matching it would publish a set's blurb as the book's. The same junk
# titles fetch.py drops (one list, same intent).
_JUNK = ('summary of', 'study guide', 'sparknotes', 'workbook', 'box set', 'boxset',
         'collection set', 'books collection', 'series set', 'omnibus', 'cliffsnotes')
_JUNK_SET = re.compile(r'\bbooks? set\b')


def _junk_title(t):
    low = (t or '').lower()
    return any(j in low for j in _JUNK) or bool(_JUNK_SET.search(low))


# ---------- parsers (fail soft: None, never a raise) ----------
_ROW = re.compile(r'<tr[^>]*itemtype="http://schema\.org/Book"', re.I)
_BTITLE = re.compile(r'''<a[^>]*class="bookTitle"[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>''', re.S | re.I)
_BAUTH = re.compile(r'''<a[^>]*class="authorName"[^>]*>(.*?)</a>''', re.S | re.I)


def parse_search(html):
    """A Goodreads search page -> [{title, author, url}] in rank order, or
    None when the page is not what we expect (a markup change fails soft).

    Two page shapes: the classic table of rows, and the Next.js page Goodreads
    serves since 2026-11 ('Book search results for ... | Goodreads'), whose
    results live in its streamed data. A row from the Next.js page also
    carries `description` — the result's own blurb as the search shows it
    ('' when it has none, None when the page's data cannot say), and the
    result's series name and placement ('' when it has none)."""
    if not html:
        return None
    out = []
    for chunk in _ROW.split(html)[1:]:
        m = _BTITLE.search(chunk)
        if not m:
            continue
        url = htmllib.unescape(m.group(1)).split('?')[0]
        title = _clean(m.group(2), 200)
        a = _BAUTH.search(chunk)
        author = _clean(a.group(1), 120) if a else ''
        if title and url.startswith('/book/show/'):
            out.append({'title': title, 'author': author,
                        'url': 'https://www.goodreads.com' + url})
    return out or _parse_search_next(html)


# The Next.js search page streams its content as React flight rows inside
# `self.__next_f.push([1,"..."])` scripts. Each result is a props object
# {"position": N, ..., "book": {"__typename": "Book", ...}}; a long string
# (a blurb) is a "$<id>" reference to a text row '<id>:T<hex byte length>,'.
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_POSITION = re.compile(r'\{"position":(\d+),')


def _flight(html):
    """The page's streamed flight data as one string, or '' (fail soft)."""
    try:
        return ''.join(json.loads('"%s"' % p) for p in _PUSH.findall(html or ''))
    except Exception:
        return ''


def _flight_text(raw, ref):
    """Resolve a '$<id>' text reference against the flight data (UTF-8 bytes:
    the row length counts bytes); a plain string is itself, no value is ''.
    None when the reference cannot be resolved — unknown, not empty."""
    if ref is None:
        return ''
    if not isinstance(ref, str):
        return None
    if not re.match(r'\$[0-9a-f]+$', ref):
        return ref
    m = re.search(rb'(?:^|\n)' + ref[1:].encode() + rb':T([0-9a-f]+),', raw)
    if not m:
        return None
    return raw[m.end():m.end() + int(m.group(1), 16)].decode('utf-8', 'replace')


def _first_book(o):
    """The first Book node (one with a page) inside a result's props."""
    if isinstance(o, dict):
        if o.get('__typename') == 'Book' and o.get('webUrl'):
            return o
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            b = _first_book(v)
            if b:
                return b
    return None


def _parse_search_next(html):
    """The Next.js search page -> rows in rank order (by `position`), or None."""
    data = _flight(html)
    if not data:
        return None
    raw = data.encode('utf-8')
    dec = json.JSONDecoder()
    ranked = {}
    for m in _POSITION.finditer(data):
        try:
            props, _ = dec.raw_decode(data, m.start())
        except ValueError:
            continue
        b = _first_book(props)
        if not b:
            continue
        url = (b.get('webUrl') or '').split('?')[0]
        title = _clean(b.get('title'), 200)
        node = (b.get('primaryContributorEdge') or {}).get('node')
        author = _clean((node or {}).get('name') if isinstance(node, dict) else '', 120)
        if title and url.startswith('https://www.goodreads.com/book/show/'):
            desc = _flight_text(raw, b.get('description'))
            ser = next((x for x in (b.get('bookSeries') or []) if isinstance(x, dict)), {})
            # a repeated series is a "$..." back-reference to its first use:
            # that row has the name, this one reads as no series
            sdata = ser.get('series') if isinstance(ser.get('series'), dict) else {}
            ranked.setdefault(int(m.group(1)), {
                'title': title, 'author': author, 'url': url,
                'description': None if desc is None else _clean(desc),
                'series': _clean(sdata.get('title'), 120),
                'series_num': _clean(ser.get('seriesPlacement'), 8)})
    seen, out = set(), []
    for _, row in sorted(ranked.items()):
        if row['url'] not in seen:
            seen.add(row['url'])
            out.append(row)
    return out or None


def _book_node(ap, url=None):
    """The Book node that IS this page's book (a page can hold several; the
    URL's own id wins when it is there — mirroring reference.parse_book)."""
    m = re.search(r'/show/(\d+)', url or '')
    want = m.group(1) if m else None
    first = None
    for k, v in (ap or {}).items():
        if not (k.startswith('Book:') and isinstance(v, dict)):
            continue
        if want and (str(v.get('legacyId') or '') == want or want in (v.get('webUrl') or '')):
            return v
        if first is None:
            first = v
    return first


def parse_book_page(html, url=None):
    """A Goodreads book page -> {title, author, description, id} or None."""
    j = R._next_data(html)
    if not j:
        return None
    ap = R._apollo(j)
    b = _book_node(ap, url)
    if not isinstance(b, dict):
        return None
    author = ''
    c = ap.get(R._ref((b.get('primaryContributorEdge') or {}).get('node'), 'Contributor:'))
    if isinstance(c, dict):
        author = (c.get('name') or '').strip()
    desc = ''
    for key in ('description({"stripped":true})', 'description'):
        v = b.get(key)
        if isinstance(v, str) and v.strip():
            desc = _clean(v)
            if desc:
                break
    return {'title': (b.get('title') or '').strip(), 'author': author, 'description': desc,
            'id': gr_id(url) or re.sub(r'\D', '', str(b.get('legacyId') or ''))}

# ---------- the lookup chain ----------
def search_url(title, author):
    q = urllib.parse.urlencode({'q': ('%s %s' % (title, author)).strip()})
    return 'https://www.goodreads.com/search?' + q


def gr_id(url):
    """The Goodreads book id inside a /book/show/ address, or ''."""
    m = re.search(r'/book/show/(\d+)', url or '')
    return m.group(1) if m else ''


def gr_url(gid):
    """A book's own Goodreads page from its id (no title slug needed: Goodreads
    redirects to the full address)."""
    return 'https://www.goodreads.com/book/show/' + gid


def _suspect(html):
    """A response that is not a real page: an empty body, or the AWS WAF
    challenge Goodreads serves once an IP asks too often (a 200 with a ~2KB
    CAPTCHA body — the #47 note's rate limit, now with a marker). A suspect
    response is TRANSIENT: it must never be cached as 'no blurb here'."""
    if not html or len(html) < 3000:
        return True
    low = html[:5000].lower()
    return any(m in low for m in ('awswafcookiedomainlist', 'gokuprops', 'captcha', 'challenge.js'))


def _looks_like_search(html):
    """A real search page that shows no result rows: a genuine no-match.
    The Next.js page carries 'searchresults' on every search (its other tabs'
    loaders), so for it only its own no-results block counts — a results page
    we cannot read must stay a transient 'fail', never a cached miss."""
    low = (html or '').lower()
    if 'book search results for' in low[:20000]:
        return 'no-book-search-results' in low or 'nobooksearchresults' in low
    low = low[:200000]
    return 'booktitle' in low or 'searchresults' in low


def goodreads_lookup(title, author, page=True):
    """(text, outcome, gr): outcome 'goodreads' | 'miss' | 'fail' | 'challenged'.

    One search, then the matched book page. A search that redirects straight
    to a single book page is honored in place (no second request). A request
    failure is 'fail'; a bot-challenge page (or an empty body) is
    'challenged'. Both are transient, never cached as a miss, retried by a
    later build — and 'challenged' tells attach() to stop asking Goodreads
    this build. A real page with nothing to give is a 'miss'.

    gr is the Goodreads book id of the page the title and author check
    matched ('' when nothing matched), kept even when that page has no blurb
    or could not be read — the match, not the blurb, is what makes it sure.

    page=False is the id-only ask for a book whose blurb is already cached:
    it stops after the search and answers ('', 'found', gr) when a result
    matches (the one request a cached book costs)."""
    try:
        html = _get(search_url(title, author))
    except Exception:
        return ('', 'fail', '')
    if _suspect(html):
        return ('', 'challenged', '')
    rows = parse_search(html)
    if rows is None:
        found = parse_book_page(html)         # the search redirected to a book
        if found is not None:
            if not _entry_ok(title, author, found['title'], found['author']):
                return ('', 'miss', '')
            d = _usable(found['description'])
            if not page:
                return ('', 'found', found['id'])
            return (d, 'goodreads' if d else 'miss', found['id'])
        # a real search page with no result rows is a genuine no-match; any
        # other shape is a page we do not understand — retry, never poison
        return ('', 'miss', '') if _looks_like_search(html) else ('', 'fail', '')
    url = None
    for r in rows:
        # a result whose own blurb the search already shows as a stub ('1')
        # is a placeholder edition: its page has nothing more — the next
        # matching result (the real edition) is the one to read
        if r.get('description') is not None and not _usable(r['description']):
            continue
        if _entry_ok(title, author, r['title'], r['author']):
            url = r['url']
            break
    if not url:
        return ('', 'miss', '')
    gid = gr_id(url)
    if not page:
        return ('', 'found', gid)
    try:
        page_html = _get(url)
    except Exception:
        return ('', 'fail', gid)
    if _suspect(page_html):
        return ('', 'challenged', gid)
    found = parse_book_page(page_html, url)
    if found is None:
        return ('', 'fail', gid)              # markup change: retried, never a false 'none'
    # the page must still be this book: a matched row can link a set or an
    # edition whose own title says so (the box-set lesson)
    if found.get('title') and (not R._title_match(title, found['title']) or _junk_title(found['title'])):
        return ('', 'miss', '')
    desc = _usable(found.get('description'))
    if desc:
        return (desc, 'goodreads', gid)
    return ('', 'miss', gid)                  # the page itself carries no blurb


def apple_lookup(title, author):
    """('text', 'apple') | ('', 'miss') | ('', 'fail').

    The Apple catalog description (iTunes search) — the issue's fallback for
    books Goodreads cannot supply. Title AND author are verified, same rules."""
    q = urllib.parse.urlencode({'term': ('%s %s' % (title, author)).strip(),
                                'media': 'ebook', 'entity': 'ebook',
                                'limit': 8, 'country': CFG.get('apple_country', 'us')})
    try:
        raw = _get('https://itunes.apple.com/search?' + q)
        results = (json.loads(raw) or {}).get('results') or []
    except Exception:
        return ('', 'fail')
    for it in results:
        t = (it.get('trackName') or '').strip()
        a = (it.get('artistName') or '').strip()
        if not t or not _entry_ok(title, author, t, a):
            continue
        d = _usable(it.get('description') or '')
        if d:
            return (d, 'apple')
    return ('', 'miss')


def lookup(title, author, goodreads=True):
    """The chain, plus what attach() needs from Goodreads: (text, src, gr, gid).

    src is 'goodreads' | 'apple' | 'none' | 'fail', as resolve() returns it.
    gr is what Goodreads said: goodreads_lookup()'s outcome, or 'skipped' when
    the caller asked not to ask it (goodreads=False). An Apple copy with any
    gr but 'miss' is an Apple copy Goodreads may still beat. gid is the
    matched Goodreads book id ('' when none matched)."""
    gr_text, gr, gid = goodreads_lookup(title, author) if goodreads else ('', 'skipped', '')
    if gr_text:
        return (gr_text, 'goodreads', gr, gid)
    apple_text, apple_src = apple_lookup(title, author)
    if apple_text:
        return (apple_text, 'apple', gr, gid)
    if gr != 'miss' or apple_src == 'fail':
        return ('', 'fail', gr, gid)
    return ('', 'none', gr, gid)


def resolve(title, author):
    """The chain: Goodreads page -> Apple description -> honest none.

    A Goodreads request failure falls through to Apple (an outage must not
    leave books blank); if either source failed and neither produced text the
    book stays pending — retried by the next build, never cached as empty."""
    text, src = lookup(title, author)[:2]
    return (text, src)


# ---------- the volume cache ----------
def cache_path():
    return os.path.join(BASE, CFG.get('output_dir', 'data'), CACHE_NAME)


def load(path=None):
    try:
        d = json.load(open(path or cache_path()))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(cache, path=None):
    """Atomic write (unique temp + replace): two builds must never interleave
    into one file. Returns False on failure — the caller reports it."""
    path = path or cache_path()
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.syn-', suffix='.tmp')
        with os.fdopen(fd, 'w') as f:
            json.dump(cache, f, indent=0)
        os.replace(tmp, path)
        return True
    except Exception:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False


# ---------- the pass build.py runs ----------
def attach(entries, cache, budget=None):
    """Ensure every rendered book carries synopsis + synopsisSrc, and grUrl
    when its own Goodreads page is known.

    `entries` = [(book_dict, title, author)] in PRIORITY order — the caller
    puts the picks first so the decision surface fills before the long tail.
    One lookup per NEW book ever; cached books cost nothing (no request) —
    except a cached Apple copy marked `retry: 'goodreads'`, which a second pass
    asks Goodreads about once the books with no blurb have had their turn.
    Once Goodreads answers with its bot challenge, no more Goodreads requests
    go out this build: new books take Apple's copy (marked for retry) and the
    retry pass waits for the next build. New books also stop asking Goodreads
    once GOODREADS_SHARE of the budget is spent, so a big batch fills from
    Apple instead of waiting blank; the retry and id passes may use the whole
    budget.

    The Goodreads book id a lookup matches is kept in the cache entry as `gr`
    ('' = Goodreads has no sure match, final). A cached book that has no `gr`
    yet gets it in a last pass, one search each, after the new books and the
    retries; the fill continues on the next build. A book that already
    carries a grUrl (an imported Book Id) keeps it and is never asked.

    The buckets are disjoint and sum to the books considered: fetched (this
    build, with text) + cached (with text) + none (no blurb anywhere, fresh or
    cached — unannounced stubs included) + pending (budget) + failed (retried).
    'retry' counts, apart from the buckets, the books whose Apple copy still
    waits for Goodreads; 'linked' the cached books given their id this build.
    Returns the counts the run report prints."""
    if budget is None:
        budget = CFG.get('synopsis_budget_seconds', DEFAULT_BUDGET)
    stats = {'fetched': 0, 'goodreads': 0, 'apple': 0, 'cached': 0,
             'none': 0, 'pending': 0, 'failed': 0, 'retry': 0, 'linked': 0}
    started = time.time()
    got, meta, order, retries, fills, ids = {}, {}, [], [], [], {}
    goodreads = {'on': True}
    for book, title, author in entries or []:
        k = book.get('id') or bookids.book_key(title, author)
        if not k or k in meta or k in got:
            continue
        if not eligible(title):
            # an unannounced stub ('Untitled', 'TBA'): nothing to look up —
            # and the page says so honestly rather than showing an empty block
            got[k] = ('', 'unannounced')
            stats['none'] += 1                  # no blurb exists: a miss, not a fetch
            continue
        meta[k] = (title, author)
        order.append(k)
    for book, title, author in entries or []:
        # an id the book already carries (a Goodreads import's Book Id) wins
        # over anything the lookup finds, for every place the book renders
        k = book.get('id') or bookids.book_key(title, author)
        if k in meta and gr_id(book.get('grUrl')) and k not in ids:
            ids[k] = gr_id(book['grUrl'])

    def heard(gr):
        if gr == 'challenged':
            goodreads['on'] = False             # Goodreads said stop: stop, this build

    def keep_id(k, gr, gid):
        """Put what Goodreads said about the book's id in its cache entry: the
        id when it matched, '' when it answered that nothing does, nothing
        when it did not answer (asked again later)."""
        ent = cache.get(k)
        if not isinstance(ent, dict) or k in ids:
            return
        if gid:
            ent['gr'] = ids[k] = gid
        elif gr == 'miss':
            ent['gr'] = ''

    for k in order:
        ent = cache.get(k) if isinstance(cache, dict) else None
        if isinstance(ent, dict) and ent.get('src') in ('goodreads', 'apple', 'none'):
            # _usable on read: entries stored before the lead-trim / stub guard
            # existed heal on the next build without a refetch — and a stored
            # stub ('1') is dropped so the book is retried instead of shipped
            text = '' if ent['src'] == 'none' else _usable(ent.get('text') or '')
            if ent['src'] != 'none' and not text:
                cache.pop(k, None)
            else:
                got[k] = (text, ent['src'])
                if ent.get('gr') and k not in ids:
                    ids[k] = ent['gr']
                retry = ent['src'] == 'apple' and ent.get('retry') == 'goodreads'
                if 'gr' not in ent and k not in ids and not retry:
                    fills.append(k)             # blurb cached, id not asked yet
                if ent['src'] == 'none':
                    stats['none'] += 1          # a miss counts once — in 'none'
                elif retry:
                    retries.append(k)           # shown now; Goodreads asked below
                else:
                    stats['cached'] += 1
                continue
        spent = time.time() - started
        if spent >= budget:
            got[k] = ('', 'pending')
            stats['pending'] += 1
            continue
        title, author = meta[k]
        ask = goodreads['on'] and spent < budget * GOODREADS_SHARE
        text, src, gr, gid = lookup(title, author, goodreads=ask)
        heard(gr)
        if src == 'fail':
            got[k] = ('', 'pending')          # transient: never cached, retried
            stats['failed'] += 1
            continue
        got[k] = (text, src)
        cache[k] = {'text': text, 'src': src, 'at': datetime.now().date().isoformat()}
        keep_id(k, gr, gid)
        if src == 'none':
            stats['none'] += 1
        else:
            stats['fetched'] += 1
            stats['goodreads' if src == 'goodreads' else 'apple'] += 1
            if src == 'apple' and gr != 'miss':
                cache[k]['retry'] = 'goodreads'     # Goodreads did not answer: ask again
                stats['retry'] += 1
    for k in retries:
        title, author = meta[k]
        if goodreads['on'] and time.time() - started < budget:
            text, gr, gid = goodreads_lookup(title, author)
            heard(gr)
            if text:
                got[k] = (text, 'goodreads')
                cache[k] = {'text': text, 'src': 'goodreads',
                            'at': datetime.now().date().isoformat()}
                keep_id(k, gr, gid)
                stats['fetched'] += 1
                stats['goodreads'] += 1
                continue
            keep_id(k, gr, gid)                 # a match with an unreadable page still counts
            if gr == 'miss':
                cache[k].pop('retry', None)     # Goodreads has none: Apple's copy is final
                stats['cached'] += 1
                continue
        stats['cached'] += 1                    # Apple's copy stands until Goodreads answers
        stats['retry'] += 1
    for k in fills:
        if not goodreads['on'] or time.time() - started >= budget:
            break
        title, author = meta[k]
        _, gr, gid = goodreads_lookup(title, author, page=False)
        heard(gr)
        keep_id(k, gr, gid)
        if gid:
            stats['linked'] += 1
    for book, title, author in entries or []:
        k = book.get('id') or bookids.book_key(title, author)
        if k in got:
            book['synopsis'], book['synopsisSrc'] = got[k]
        if ids.get(k) and not gr_id(book.get('grUrl')):
            book['grUrl'] = gr_url(ids[k])
    return stats


def report_line(stats):
    """The run report line — the issue's shape: 'synopses: 12 fetched / 9
    cached / 2 none', with the extras only when they happened."""
    line = 'synopses: %d fetched' % stats['fetched']
    if stats['fetched']:
        line += ' (%d goodreads, %d apple)' % (stats['goodreads'], stats['apple'])
    line += ' / %d cached / %d none' % (stats['cached'], stats['none'])
    if stats['pending']:
        line += ' / %d pending (next build continues)' % stats['pending']
    if stats['failed']:
        line += ' / %d failed (retried next build)' % stats['failed']
    if stats.get('retry'):
        line += ' / %d apple until goodreads answers' % stats['retry']
    if stats.get('linked'):
        line += ' / %d goodreads pages linked' % stats['linked']
    return line
