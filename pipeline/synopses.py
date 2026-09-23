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
retries it.

Politeness: one book at a time, >=1.2s between requests, and a per-build time
budget (config `synopsis_budget_seconds`, default 180s) so a cold cache can
never blow the boot rebuild's 300s timeout — the fill continues on the next
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
DEFAULT_BUDGET = 180  # seconds of fetching per build (config-overridable)

_last = {'t': 0.0}


def _get(url, timeout=25):
    """One polite GET: at least GAP seconds after the previous request."""
    dt = time.time() - _last['t']
    if dt < GAP:
        time.sleep(GAP - dt)
    _last['t'] = time.time()
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
# Storm') — matching it would publish a set's blurb as the book's. The same
# junk titles fetch.py drops (one list, same intent).
_JUNK = ('summary of', 'study guide', 'sparknotes', 'workbook', 'box set', 'boxset',
         'collection set', 'books collection', 'series set', 'omnibus', 'cliffsnotes')


def _junk_title(t):
    low = (t or '').lower()
    return any(j in low for j in _JUNK)


# ---------- parsers (fail soft: None, never a raise) ----------
_ROW = re.compile(r'<tr[^>]*itemtype="http://schema\.org/Book"', re.I)
_BTITLE = re.compile(r'''<a[^>]*class="bookTitle"[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>''', re.S | re.I)
_BAUTH = re.compile(r'''<a[^>]*class="authorName"[^>]*>(.*?)</a>''', re.S | re.I)


def parse_search(html):
    """A Goodreads search page -> [{title, author, url}] in rank order, or
    None when the page is not what we expect (a markup change fails soft)."""
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
    """A Goodreads book page -> {title, author, description} or None."""
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
    return {'title': (b.get('title') or '').strip(), 'author': author, 'description': desc}

# ---------- the lookup chain ----------
def search_url(title, author):
    q = urllib.parse.urlencode({'q': ('%s %s' % (title, author)).strip()})
    return 'https://www.goodreads.com/search?' + q


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
    low = (html or '')[:200000].lower()
    return 'booktitle' in low or 'searchresults' in low


def goodreads_lookup(title, author):
    """('text', 'goodreads') | ('', 'miss') | ('', 'fail').

    One search, then the matched book page. A search that redirects straight
    to a single book page is honored in place (no second request). A request
    failure — or a rate-limit/challenge page — is 'fail': transient, never
    cached, retried by the next build. A real page with nothing to give is a
    'miss'."""
    try:
        html = _get(search_url(title, author))
    except Exception:
        return ('', 'fail')
    if _suspect(html):
        return ('', 'fail')
    rows = parse_search(html)
    if rows is None:
        page = parse_book_page(html)          # the search redirected to a book
        if page is not None:
            d = _usable(page['description'])
            if d and _entry_ok(title, author, page['title'], page['author']):
                return (d, 'goodreads')
            return ('', 'miss')
        # a real search page with no result rows is a genuine no-match; any
        # other shape is a page we do not understand — retry, never poison
        return ('', 'miss') if _looks_like_search(html) else ('', 'fail')
    url = None
    for r in rows:
        if _entry_ok(title, author, r['title'], r['author']):
            url = r['url']
            break
    if not url:
        return ('', 'miss')
    try:
        page_html = _get(url)
    except Exception:
        return ('', 'fail')
    if _suspect(page_html):
        return ('', 'fail')
    page = parse_book_page(page_html, url)
    if page is None:
        return ('', 'fail')                   # markup change: retried, never a false 'none'
    # the page must still be this book: a matched row can link a set or an
    # edition whose own title says so (the box-set lesson)
    if page.get('title') and (not R._title_match(title, page['title']) or _junk_title(page['title'])):
        return ('', 'miss')
    desc = _usable(page.get('description'))
    if desc:
        return (desc, 'goodreads')
    return ('', 'miss')                       # the page itself carries no blurb


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


def resolve(title, author):
    """The chain: Goodreads page -> Apple description -> honest none.

    A Goodreads request failure falls through to Apple (an outage must not
    leave books blank); if either source failed and neither produced text the
    book stays pending — retried by the next build, never cached as empty."""
    text, src = goodreads_lookup(title, author)
    if text:
        return (text, 'goodreads')
    apple_text, apple_src = apple_lookup(title, author)
    if apple_text:
        return (apple_text, 'apple')
    if src == 'fail' or apple_src == 'fail':
        return ('', 'fail')
    return ('', 'none')


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
    """Ensure every rendered book carries synopsis + synopsisSrc.

    `entries` = [(book_dict, title, author)] in PRIORITY order — the caller
    puts the picks first so the decision surface fills before the long tail.
    One lookup per NEW book ever; cached books cost nothing (no request).
    The buckets are disjoint and sum to the books considered: fetched (this
    build, with text) + cached (with text) + none (no blurb anywhere, fresh or
    cached — unannounced stubs included) + pending (budget) + failed (retried).
    Returns the counts the run report prints."""
    if budget is None:
        budget = CFG.get('synopsis_budget_seconds', DEFAULT_BUDGET)
    stats = {'fetched': 0, 'goodreads': 0, 'apple': 0, 'cached': 0,
             'none': 0, 'pending': 0, 'failed': 0}
    started = time.time()
    got, meta, order = {}, {}, []
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
                if ent['src'] == 'none':
                    stats['none'] += 1          # a miss counts once — in 'none'
                else:
                    stats['cached'] += 1
                continue
        if time.time() - started >= budget:
            got[k] = ('', 'pending')
            stats['pending'] += 1
            continue
        title, author = meta[k]
        text, src = resolve(title, author)
        if src == 'fail':
            got[k] = ('', 'pending')          # transient: never cached, retried
            stats['failed'] += 1
            continue
        got[k] = (text, src)
        cache[k] = {'text': text, 'src': src, 'at': datetime.now().date().isoformat()}
        if src == 'none':
            stats['none'] += 1
        else:
            stats['fetched'] += 1
            stats['goodreads' if src == 'goodreads' else 'apple'] += 1
    for book, title, author in entries or []:
        k = book.get('id') or bookids.book_key(title, author)
        if k in got:
            book['synopsis'], book['synopsisSrc'] = got[k]
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
    return line
