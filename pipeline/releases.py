#!/usr/bin/env python3
"""The Shelf pipeline — stage 2: Goodreads new releases, one list per interest.

Apple Books cannot show a book it does not sell, and most Kindle-first books
are not there. Goodreads lists them: every genre has a new-release page
(goodreads.com/genres/new_releases/<slug>). For each interest whose dial is
on (an interest whose mode is 'best ever' is skipped: its books are not new;
'new' and 'both' are read), this stage:

  1. reads that interest's genre list once (one polite request);
  2. drops the books the shelf already saw (the pool, her marks);
  3. for each of the rest, tries Apple Books first — its record carries a
     date, a publisher and ratings — and otherwise reads the book's own
     Goodreads page (publisher, date, ratings, cover), tagged
     pub_source 'goodreads-page' so filter.py's indie-with-proof rule applies
     unchanged: 4.0 or more from 100 readers;
  4. appends the finds to the month's candidates file, lane = the interest,
     found_by 'goodreads-genre:<slug>'.

A catalog interest has a fixed genre slug (interests.CATALOG); a typed one is
asked of the curator, checked against the live list, and kept in
interests.json like the search words are once a suggestion lists books.

Everything here is best-effort, like reference.py: any failure prints why,
writes data/releases-<month>.json with ok:false and exits 0 — the run goes on
with Apple alone. Goodreads answers a client without a browser with a bot
challenge once it asks too often (synopses.py measured it): book pages are read
`goodreads_gap_seconds` apart, capped per run, cached by Goodreads id, and the
first challenge ends the page reads for the run. The stage also stops itself
at a time budget and writes what it has: the server ends the whole run when a
stage passes its limit, and that would lose the finds.
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime

import curate
import fetch
import interests
import paths
import reference
import synopses
from windows import target_month

CFG = fetch.CFG
LIST_URL = 'https://www.goodreads.com/genres/new_releases/%s'
PAGE_CAP = int(CFG.get('releases_page_cap', 30))     # Goodreads book pages read per run
ENTRY_CAP = int(CFG.get('releases_entry_cap', 80))   # list entries looked up per run, all interests
# The server stops a stage after 1500 s and ends the run before curate; a stage that
# stops itself earlier keeps its finds. The budget leaves room for the read in flight
# (an Apple search with 429 retries, a page read timing out at 25 s).
BUDGET = float(CFG.get('releases_budget_seconds', 600))
PAGE_GAP = float(CFG.get('goodreads_gap_seconds', 10))
CACHE_DAYS = 14      # ratings move: a page read older than this is read again
APPLE_FAILS = 3      # Apple searches that fail in this stage before it stops asking Apple
CACHE_NAME = 'goodreads-cache.json'


# ---------- the genre list ----------
def parse_genre_list(html):
    """A genre's new-release page -> [{id, title, name, author, url, cover,
    rating, rating_count}] in page order, or [] when it lists no books (an
    unknown genre answers a real page with none; a markup change looks the
    same, so the caller reports both as 'no list').

    Classic server-rendered markup, not the Next.js data the month list uses:
    each book is a coverWrapper (id, link, title, cover) plus a hover tip in
    a script that holds the author and the average rating."""
    out = []
    for chunk in (html or '').split('<div class="leftAlignedImage bookBox">')[1:]:
        m = re.search(r'id="bookCover\d+_(\d+)"\s*>\s*<a href="([^"]+)"><img alt="([^"]*)"[^>]*?src="([^"]*)"', chunk)
        if not m:
            continue
        gid, href, title, cover = m.groups()
        title = _unescape(title).strip()
        if not title:
            continue
        tip = ''
        t = re.search(r'new Tip\([^,]*,\s*"((?:[^"\\]|\\.)*)"', chunk)
        if t:
            tip = t.group(1).replace('\\"', '"').replace('\\/', '/')
        a = re.search(r'class="authorName"[^>]*>(.*?)</a>', tip, re.S)
        r = re.search(r'([\d.]+) avg rating[^0-9]*([\d,]+) ratings', tip)
        out.append({
            'id': gid,
            'title': title,
            'name': strip_series(title),
            'author': ' '.join(_unescape(re.sub(r'<[^>]+>', '', a.group(1))).split()) if a else '',
            'url': 'https://www.goodreads.com' + href.split('?')[0],
            'cover': cover,
            'rating': float(r.group(1)) if r else None,
            'rating_count': int(r.group(2).replace(',', '')) if r else None,
        })
    return out


def _unescape(s):
    import html as h
    return h.unescape(s or '')


def strip_series(title):
    """'The Keeper (Gods of the Game, #3)' -> 'The Keeper': the series tag is
    Goodreads' own, Apple's title and the shelf's book key do not carry it."""
    return re.sub(r'\s*\([^()]*#\s*\d[^()]*\)\s*$', '', title or '').strip()


# ---------- the page cache ----------
def cache_path():
    return os.path.join(fetch.BASE, CFG.get('output_dir', 'data'), CACHE_NAME)


def load_cache():
    try:
        with open(cache_path()) as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def cached_page(cache, gid, today=None):
    """The parsed page of a Goodreads book read within CACHE_DAYS, else None."""
    ent = cache.get(gid)
    try:
        age = ((today or date.today()) - date.fromisoformat(ent['at'])).days
        return ent['page'] if 0 <= age <= CACHE_DAYS else None
    except Exception:
        return None


class Reader:
    """Book-page reads for one run: the cache first, then Goodreads at its
    pace, up to the cap. The first bot challenge ends the reads — asking on
    would only prolong it. A page that could not be read is never cached."""

    def __init__(self, cache, cap=None, gap=None, sleep=None):
        self.cache = cache
        self.cap = PAGE_CAP if cap is None else cap
        self.gap = PAGE_GAP if gap is None else gap
        self.sleep = sleep or time.sleep
        self.reads = 0
        self.cached = 0
        self.challenged = False
        self._last = time.time()     # the list read just before counts as a request

    def read(self, e):
        """(data, why): the parsed page, or None with the reason it is not
        there — 'cap', 'challenged', 'unreadable'."""
        data = cached_page(self.cache, e['id'])
        if data:
            self.cached += 1
            return data, ''
        if self.challenged:
            return None, 'challenged'
        if self.reads >= self.cap:
            return None, 'cap'
        wait = self.gap - (time.time() - self._last)
        if wait > 0:
            self.sleep(wait)
        self.reads += 1
        try:
            html = reference._get(e['url'])
        except Exception:
            self._last = time.time()
            return None, 'unreadable'
        self._last = time.time()
        if synopses._suspect(html):
            self.challenged = True
            return None, 'challenged'
        data = reference.parse_book(html, e['url'])
        if not data or not data.get('title'):
            return None, 'unreadable'
        self.cache[e['id']] = {'at': date.today().isoformat(), 'page': data}
        return data, ''


# ---------- one entry -> a candidate ----------
def candidate_for(e, interest_name, slug, mon, apple_cache, reader, apple_ok):
    """(candidate, via, why): Apple's record when it has one with a date, else
    the book's Goodreads page; None and the reason otherwise. The candidate is
    the interest's own: the list it came from names the lane."""
    c, via = None, ''
    if apple_ok():
        c = reference.apple_candidate({'title': e['name'], 'author': e['author']}, mon, apple_cache)
        if c and c.get('date'):
            via = 'apple'
        else:
            c = None
    if c is None:
        data, why = reader.read(e)
        if not data:
            return None, '', why
        c = reference.page_candidate(dict(e, title=e['name']), data)
        if not c:
            return None, '', 'wrong page'
        via = 'goodreads-page'
        c['gr'] = e['id']
    c['lane'], c['lanes'] = interest_name, [interest_name]
    c['found_by'] = ['goodreads-genre:%s' % slug]
    return c, via, ''


def pick_entries(lists, seen, cap):
    """The entries to look up, interests taking turns so one long list cannot
    use the cap alone: lists is [(interest_name, slug, entries)]. A book the
    shelf saw, or an earlier list already took, is left out."""
    queues, taken = [], set()
    for nm, slug, entries in lists:
        q = []
        for e in entries:
            keys = reference._entry_keys({'title': e['name'], 'author': e['author']})
            if keys & seen or keys & taken or e['id'] in taken:
                continue
            taken |= keys | {e['id']}
            q.append((nm, slug, e))
        queues.append(q)
    out = []
    while len(out) < cap and any(queues):
        for q in queues:
            if q and len(out) < cap:
                out.append(q.pop(0))
    return out, sum(len(q) for q in queues)


def main():
    deadline = time.time() + BUDGET
    mon = target_month(fetch.MODE)
    outdir = os.path.join(paths.BASE, CFG.get('output_dir', 'data'))
    rep_path = os.path.join(outdir, 'releases-%s.json' % mon)
    report = {'month': mon, 'fetched_at': datetime.now().isoformat(), 'ok': False,
              'interests': {}, 'added': [], 'unobtainable': [], 'reason': '',
              'page_reads': 0, 'page_cache_hits': 0, 'challenged': False}

    def write():
        try:
            os.makedirs(outdir, exist_ok=True)
            with open(rep_path, 'w') as f:
                json.dump(report, f, indent=1)
        except Exception as ex:
            print('goodreads releases: report file unwritable (%s) (run continues)' % str(ex)[:80])

    try:
        doc = interests.load()
    except Exception as ex:
        report['reason'] = 'interests unreadable: %s' % str(ex)[:100]
        write()
        print('goodreads releases: 0 — %s (run continues)' % report['reason'])
        return 0

    key = curate.api_key()
    lists, slugs_found = [], False
    for i in doc.get('interests') or []:
        nm, label = interests.name(i), i.get('label') or interests.name(i)
        if interests.dial(i) == 'off' or interests.mode(i) == 'best ever':
            continue
        row = report['interests'][nm] = {'label': label, 'slug': '', 'listed': 0, 'new': 0,
                                         'apple': 0, 'goodreads': 0, 'missed': 0, 'reason': ''}
        slug = interests.gr_slug(i)
        html = None
        if time.time() > deadline:
            row['reason'] = 'time budget reached before its list was read'
            continue
        try:
            if slug:
                time.sleep(reference.GAP)
                html = reference._get(LIST_URL % slug)
            else:
                # a typed interest: the curator names its Goodreads genre once; the
                # file keeps the first slug whose list shows books
                for s in (curate.suggest_slugs(key, label) if key else []):
                    time.sleep(reference.GAP)
                    h = reference._get(LIST_URL % s)
                    if parse_genre_list(h):
                        slug, html = s, h
                        i['gr_slug'] = s
                        slugs_found = True
                        print('[releases] %s: curator suggested the Goodreads genre %s — kept in interests.json'
                              % (label, s))
                        break
                if not slug:
                    row['reason'] = 'no Goodreads genre' + ('' if key else ' (no OpenRouter key)')
        except Exception as ex:
            row['reason'] = 'list fetch failed: %s' % str(ex)[:80]
            html = None
        row['slug'] = slug
        entries = parse_genre_list(html) if html else []
        if slug and html and not entries:
            row['reason'] = 'list shows no books (empty genre or markup change?)'
        row['listed'] = len(entries)
        if entries:
            lists.append((nm, slug, entries))
    if slugs_found:
        interests.save_terms(doc)    # only the slugs: the reader's own answers survive a run that started before them

    if not lists:
        report['reason'] = 'no list could be read'
        write()
        print('goodreads releases: 0 — %s (run continues)' % report['reason'])
        return 0

    seen = reference.seen_keys()
    todo, left_over = pick_entries(lists, seen, ENTRY_CAP)
    for nm, slug, e in todo:
        report['interests'][nm]['new'] += 1
    if left_over:
        report['reason'] = '%d new list entries not looked up (cap %d per run)' % (left_over, ENTRY_CAP)

    apple_cache = fetch.load_cache()
    cache = load_cache()
    reader = Reader(cache)
    start_failed = fetch.STATS['search']['failed']
    apple_ok = lambda: fetch.STATS['search']['failed'] - start_failed < APPLE_FAILS
    found = []
    out_of_time = 0
    for nm, slug, e in todo:
        if time.time() > deadline:
            out_of_time += 1
            report['interests'][nm]['missed'] += 1
            report['unobtainable'].append({'title': e['name'], 'author': e['author'],
                                           'url': e['url'], 'reason': 'time budget'})
            continue
        try:
            c, via, why = candidate_for(e, nm, slug, mon, apple_cache, reader, apple_ok)
        except Exception as ex:
            c, via, why = None, '', str(ex)[:80]
        row = report['interests'][nm]
        if c:
            row['apple' if via == 'apple' else 'goodreads'] += 1
            found.append((nm, e, c, via))
        else:
            row['missed'] += 1
            report['unobtainable'].append({'title': e['name'], 'author': e['author'],
                                           'url': e['url'], 'reason': why})
    for path, blob in ((fetch.CACHE_PATH, apple_cache), (cache_path(), cache)):
        try:
            with open(path, 'w') as f:
                json.dump(blob, f, indent=0)
        except Exception:
            pass
    if out_of_time:
        report['reason'] = ('; '.join(x for x in (report['reason'], '%d not looked up (time budget %d s reached)'
                                                  % (out_of_time, BUDGET)) if x))
    report['page_reads'], report['page_cache_hits'] = reader.reads, reader.cached
    report['challenged'] = reader.challenged

    added = 0
    report['ok'] = True
    if found:
        try:
            src = os.path.join(outdir, 'candidates-%s.json' % mon)
            if not os.path.exists(src):
                raise IOError('no candidates-%s.json to append to' % mon)
            with open(src) as f:
                blob = json.load(f)
            have = {fetch.normkey(b.get('title'), b.get('author')) for b in blob.get('books', [])}
            fresh = []
            for nm, e, c, via in found:
                k = fetch.normkey(c.get('title'), c.get('author'))
                if k not in have:
                    have.add(k)
                    fresh.append(c)
                    report['added'].append({'title': c.get('title'), 'author': c.get('author'),
                                            'interest': nm, 'via': via, 'url': e['url']})
            blob.setdefault('books', []).extend(fresh)
            with open(src, 'w') as f:
                json.dump(blob, f, indent=1)
            added = len(fresh)
        except Exception as ex:
            report['reason'] = 'candidates append failed: %s' % str(ex)[:120]
            report['ok'] = False
    write()

    # the line the server's log keeps: how each interest's list did
    print('goodreads releases: %d added to the pool [Goodreads pages read %d of cap %d, from cache %d%s]%s'
          % (added, reader.reads, reader.cap, reader.cached,
             ', stopped by Goodreads\' bot check' if reader.challenged else '',
             '' if report['ok'] else ' — APPEND FAILED (%s): nothing entered the pool' % report['reason']))
    for nm, row in report['interests'].items():
        print('  %-24s %-22s %3d listed · %3d new · %2d Apple · %2d Goodreads page · %2d not found%s'
              % (row['label'], row['slug'] or '-', row['listed'], row['new'], row['apple'],
                 row['goodreads'], row['missed'], (' — ' + row['reason']) if row['reason'] else ''))
    if report['ok'] and report['reason']:
        print('  ' + report['reason'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
