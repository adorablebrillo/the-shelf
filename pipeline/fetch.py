#!/usr/bin/env python3
"""The Shelf pipeline — stage 1: fetch candidates from public sources.
Stdlib only. Best-effort: broken sources are logged, never fatal."""
import json, os, re, sys, time, urllib.request, urllib.parse
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36'}

def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')

def window():
    """Run for the PREVIOUS month: on Sept 1 we collect the August titles.
    The 1st-of-month drop shows that specific month's books only."""
    today = date.today()
    y, m = today.year, today.month
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return ['%04d-%02d' % (py, pm)]

def norm_date(s):
    if not s: return None
    s = s.strip()
    if re.match(r'\d{4}-\d{2}-\d{2}', s): return s[:10]
    for fmt in ('%d %b %Y', '%b %d %Y', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y'):
        try: return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError: pass
    return None

RECORDS = {}
def add(src, title, author, publisher='', date_s=None, genre='', spice=None,
        tropes=None, mf=None, ratings=None, url='', audio=False, ebook=True,
        raw=None, series=None):
    key = (title.lower(), author.lower())
    if key in RECORDS: return
    RECORDS[key] = {
        'source': src, 'title': title, 'author': author, 'publisher': publisher,
        'date': norm_date(date_s), 'genre': genre, 'spice': spice,
        'tropes': tropes or [], 'mf': mf, 'ratings': ratings,
        'url': url, 'audio': bool(audio), 'ebook': bool(ebook),
        'series': series or '', 'raw': raw,
    }

def fetch_apple():
    """Apple Books API: free, no key, elegant JSON. Charts + recent search."""
    n = 0
    slugs = ['romance', 'fiction-romance', 'fiction-fantasy', 'romance-fantasy']
    for slug in slugs:
        try:
            url = 'https://rss.applemarketingtools.com/api/v2/%s/books/top-40/%s/all.json' % (CFG['apple_country'], slug)
            d = json.loads(get(url))
            for it in (d.get('feed') or {}).get('results', []):
                add('apple-rss', it.get('name', ''), it.get('artistName', ''),
                    publisher=it.get('artistName', ''), date_s=it.get('releaseDate'),
                    genre=slug.replace('-', ' ').title(), url=it.get('url') or '',
                    audio=False, ebook=True)
                n += 1
        except Exception as e:
            print('[apple-rss:%s] skip: %s' % (slug, str(e)[:90]))
    for media, entity in (('ebook','ebook'), ('audiobook','audiobook')):
        try:
            q = urllib.parse.urlencode({'term': 'romance', 'media': media, 'entity': entity, 'limit': 100, 'country': CFG['apple_country'], 'sortBy': 'recent'})
            d = json.loads(get('https://itunes.apple.com/search?%s' % q))
            for it in d.get('results', []):
                add('apple-search', it.get('trackName',''), it.get('artistName',''),
                    publisher=it.get('artistName',''), date_s=it.get('releaseDate',''),
                    genre=' '.join(it.get('genres', [])[:3]), url=it.get('trackViewUrl') or '',
                    audio=(entity=='audiobook'), ebook=(entity=='ebook'))
                n += 1
        except Exception as e:
            print('[apple-search:%s] skip: %s' % (entity, str(e)[:90]))
    print('apple: %d records' % n)

def fetch_reddit(mon):
    n = 0
    for sub in CFG['reddit_subs']:
        try:
            url = 'https://www.reddit.com/r/%s/new.json?limit=100&t=week' % sub
            d = json.loads(get(url))
            for ch in (d.get('data') or {}).get('children', [])[:100]:
                p = ch.get('data') or {}
                title = p.get('title') or ''
                date_s = datetime.utcfromtimestamp(p.get('created_utc', 0)).strftime('%Y-%m-%d')
                if not any(k in title.lower() for k in ('release', 'out now', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')):
                    continue
                add('reddit', title, '(thread)', publisher='', date_s=None, genre='',
                    url='https://www.reddit.com%s' % (p.get('permalink') or ''), ebook=False, audio=False)
                n += 1
        except Exception as e:
            print('[reddit:%s] skip: %s' % (sub, str(e)[:90]))
    print('reddit: %d threads' % n)

def fetch_goodreads(mon):
    try:
        url = 'https://www.goodreads.com/genre/new_releases/new-romance'
        html = get(url)
        titles = re.findall(r'bookTitle[^>]*>\s*(?:<span[^>]*>)?([^<]+)<', html)
        counts = re.findall(r'minirating[^>]*>([\d.]+)', html)
        for i, t in enumerate(titles[:60]):
            author = ''
            am = re.search(r'authorName[^>]*>\s*(?:<span[^>]*>)?([^<]+)<', html[html.find(t):html.find(t)+400])
            if am: author = am.group(1).strip()
            add('goodreads', t.strip(), author, ratings=float(counts[i]) if i < len(counts) else None,
                date_s=mon, url='https://www.goodreads.com/genre/new_releases/new-romance')
        print('goodreads: %d titles' % len(titles))
    except Exception as e:
        print('[goodreads] skip: %s' % str(e)[:90])

def fetch_romanceio(mon):
    try:
        html = get('https://romance.io/books/release')
        if 'just a moment' in html.lower() or 'cf-chl' in html:
            print('[romance.io] Cloudflare shield up — skipped (browser pass needed)')
            return
        print('[romance.io] fetched %d chars, %d raw slots' % (len(html), html.count('release-date')))
    except Exception as e:
        print('[romance.io] skip: %s' % str(e)[:90])

def main():
    if not os.path.isdir(os.path.join(BASE, CFG['output_dir'])):
        os.makedirs(os.path.join(BASE, CFG['output_dir']), exist_ok=True)
    mon = datetime.now().strftime('%Y-%m')
    fetch_apple()
    fetch_reddit(mon)
    fetch_goodreads(mon)
    fetch_romanceio(mon)
    out = os.path.join(BASE, CFG['output_dir'], 'candidates-%s.json' % mon)
    json.dump({'fetched_at': datetime.now().isoformat(), 'window': window(), 'books': list(RECORDS.values())},
              open(out, 'w'), indent=1)
    print('candidates: %d -> %s' % (len(RECORDS), out))
    return 0

if __name__ == '__main__':
    sys.exit(main())
