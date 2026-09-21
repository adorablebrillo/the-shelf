#!/usr/bin/env python3
"""The Shelf pipeline — stage 4: build dist/ for the redesigned app.

The page (pipeline/design/app.html) is a design-component runtime page; this
script feeds it live data via dist/shelf-data.js:

  month   — the current drop (label, issue number, count)
  hero    — the soonest upcoming release in ANY series she is reading
  books   — this month's picks (top pick first)
  series  — EVERY series she is in: read volumes (data/library.json) merged
            with released-unread / upcoming / announced (data/sequels.json)
  quotes  — seasonal coffee-corner lines for the book month
  criteria — the filtering rules, shown in the footer

Pure stdlib; assets + vendored runtime are copied into dist/ here too, so the
same code path runs at image-bake time and after every pipeline run.
"""
import json, os, re, shutil, sys, urllib.request, urllib.parse, hashlib, calendar, glob
from datetime import datetime
import paths  # shared resolver: reader data lives on the volume (CFG_DIR)
from lanes import lane_of, counts as lane_counts, shape_str, shape_line
from bookids import book_key
from shelf_state import exclusion_set

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CFG = json.load(open(os.path.join(BASE, 'config.json')))
DESIGN = os.path.join(BASE, 'design')
# In the container the SERVER serves /app/dist (server.py lives at /app).
# Docker COPY flattens the repo's container/dist -> pipeline/dist symlink, so
# the pipeline and server MUST share one dist dir via DIST_DIR (set in the
# Dockerfile). Locally it stays pipeline/dist for repo layout compat.
DIST = os.environ.get('DIST_DIR') or os.path.join(BASE, 'dist')

MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten'}
CRITERIA = ('M/F only · no dark romance · spice 3–5 · trad-pub first, indie with proof · '
            'released last month · sequels only for series you are already in')

QUOTES = {
    'winter': ['cocoa swirl, two marshmallows, one more chapter.',
               'snow outside — a whole shelf inside.',
               'hot cocoa, cold nights, warm plots.'],
    'spring': ['cherry-blossom latte and a fresh TBR.',
               'bloom season is plot season.',
               'petals fall — you fall into books.'],
    'summer': ['lemon ice, a lounger, a slow-burn.',
               'the sun is up — so is your TBR.',
               'iced hands, warmer pages.'],
    'fall': ['september: pumpkin spice on the shelf, spice on the page.',
             "a good book, a warm cup — that's the whole agenda.",
             'curl up. the leaves changed, so did your TBR.'],
}
SEASON_OF = {12: 'winter', 1: 'winter', 2: 'winter', 3: 'spring', 4: 'spring', 5: 'spring',
             6: 'summer', 7: 'summer', 8: 'summer', 9: 'fall', 10: 'fall', 11: 'fall'}

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36'}


def month_label(ym):
    """('2026-08',) -> {'name':'August','label':'August 2026','win':'1 AUG – 31 AUG 2026','key':'aug'}"""
    y, m = int(ym[:4]), int(ym[5:7])
    last = calendar.monthrange(y, m)[1]
    full = datetime.strptime(ym, '%Y-%m').strftime('%B')
    return {
        'key': MONTH_NAMES[m - 1].lower(),
        'name': full,
        'label': '%s %d' % (full, y),
        'win': '1 %s – %d %s %d' % (MONTH_NAMES[m - 1], last, MONTH_NAMES[m - 1], y),
    }


def norm_name(s):
    """Series keys for matching: parentheticals dropped, alphanumerics only."""
    s = re.sub(r'\([^)]*\)', ' ', s or '')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def pretty_date(iso, title=False):
    try:
        d = datetime.strptime(iso[:10], '%Y-%m-%d')
        mon = MONTH_NAMES[d.month - 1]
        if title:
            mon = mon.capitalize()
        return '%d %s %d' % (d.day, mon, d.year)
    except Exception:
        return iso or ''


def pretty_upper(iso):
    return pretty_date(iso, title=False)


def month_is_past(ym):
    """A month file is only valid once that month is fully over. Junk files
    (e.g. month-2026-09.json written on Sept 1 by an older build) are ignored
    and purged — the legacy two-window run left exactly that behind."""
    return ym < datetime.now().strftime('%Y-%m')


def slug(b):
    s = ('%s %s' % (b.get('title', 'x'), b.get('author', 'y'))).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:60] or hashlib.md5(json.dumps(b, sort_keys=True).encode()).hexdigest()[:12]


def download_cover(b, covers_dir):
    img = b.get('img') or b.get('cover_url') or ''
    if not img:
        return ''
    if img.startswith('http'):
        try:
            req = urllib.request.Request(img, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
            if len(raw) < 1000:
                return ''
            name = slug(b) + '.jpg'
            open(os.path.join(covers_dir, name), 'wb').write(raw)
            return 'assets/covers/%s' % name
        except Exception as e:
            print('cover %s: %s' % (img[:60], str(e)[:60]))
    return img


def _get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def lookup_cover_url(title, author):
    """Real cover art for a book: iTunes ebooks -> Google Books -> Open Library.
    No API keys needed; returns a full-size-ish image URL or ''."""
    t = (title or '').strip()
    a = (author or '').strip()
    if not t:
        return ''
    tl = t.lower()
    try:
        q = urllib.parse.urlencode({'term': ('%s %s' % (t, a)).strip(), 'media': 'ebook',
                                    'entity': 'ebook', 'limit': 8, 'country': CFG.get('apple_country', 'us')})
        results = _get_json('https://itunes.apple.com/search?' + q).get('results', [])
        for it in results:
            name = (it.get('trackName') or '').lower()
            art = it.get('artworkUrl100') or it.get('artworkUrl60') or ''
            if art and (name.startswith(tl[:24]) or tl[:24] in name or name[:24] in tl):
                return art.replace('100x100bb', '600x600bb').replace('60x60bb', '600x600bb').replace('100x100', '600x600')
        if results and results[0].get('artworkUrl100'):
            last = a.split()[-1].lower() if a else ''
            if last and last in (results[0].get('artistName') or '').lower():
                return results[0]['artworkUrl100'].replace('100x100bb', '600x600bb')
    except Exception as e:
        print('cover lookup (itunes): %s' % str(e)[:70])
    try:
        q = urllib.parse.quote('intitle:"%s"%s' % (t, (' inauthor:"%s"' % a) if a else ''))
        d = _get_json('https://www.googleapis.com/books/v1/volumes?q=%s&maxResults=5&country=US' % q)
        for it in d.get('items', []):
            links = ((it.get('volumeInfo') or {}).get('imageLinks') or {})
            u = links.get('thumbnail') or links.get('smallThumbnail')
            if u:
                return u.replace('http://', 'https://').replace('&edge=curl', '')
    except Exception as e:
        print('cover lookup (google): %s' % str(e)[:70])
    try:
        q = urllib.parse.quote(('%s %s' % (t, a)).strip())
        d = _get_json('https://openlibrary.org/search.json?q=%s&limit=3&fields=cover_i,title' % q)
        for doc in d.get('docs', []):
            if doc.get('cover_i'):
                return 'https://covers.openlibrary.org/b/id/%s-L.jpg' % doc['cover_i']
    except Exception as e:
        print('cover lookup (openlibrary): %s' % str(e)[:70])
    return ''


def ensure_cover(img, title, author, covers_dir):
    """A usable LOCAL cover path — the declared image when it works, otherwise
    fetched real cover art (cached by slug so rebuilds stay offline)."""
    if img:
        if img.startswith('assets/') and os.path.isfile(os.path.join(DIST, img)):
            return img
        if img.startswith('http'):
            local = download_cover({'img': img, 'title': title, 'author': author}, covers_dir)
            if local:
                return local
    name = slug({'title': title or 'x', 'author': author or 'y'}) + '.jpg'
    if os.path.isfile(os.path.join(covers_dir, name)):
        return 'assets/covers/%s' % name
    url = lookup_cover_url(title, author)
    if url:
        local = download_cover({'img': url, 'title': title, 'author': author}, covers_dir)
        if local:
            print('cover fetched: %s' % (title or '')[:44])
            return local
    return img or ''


def next_books_for(entry, today):
    """sequels.json entry -> [{t,n,d,state,iso}] in series order."""
    out = []
    for nb in (entry or {}).get('next_books', []):
        raw = (nb.get('title') or '').strip()
        if not raw:
            continue
        m = re.match(r'^(.*?)\s*\((#[^)]*)\)\s*$', raw)
        if m:
            t, n = m.group(1).strip(), m.group(2)
        else:
            t, n = raw.split(' (')[0].strip(), ''
        if ';' in n:
            n = n.split(';')[0].strip()
        dt = str(nb.get('release_date') or '')[:10]
        iso = dt if re.match(r'^\d{4}-\d{2}-\d{2}$', dt) else (dt + '-01' if re.match(r'^\d{4}-\d{2}$', dt) else '')
        if nb.get('status') == 'out' or (iso and iso <= today):
            state = 'out'
        elif iso:
            state = 'soon'
        else:
            state = 'tba'
        if state == 'out':
            d = ('out ' + pretty_date(iso, title=True)) if iso else 'out'
        elif state == 'soon':
            d = pretty_upper(iso)
        else:
            d = 'announced, no date'
        out.append({'t': t, 'n': n, 'd': d, 'state': state, 'iso': iso})
    return out


def series_key_match(k, tracked):
    """A candidate's series name against the tracked map: exact, or a bare
    'the'-prefix variant. Deliberately NOT open substring matching — 'The
    Empyrean Legacy' must never merge into 'The Empyrean'."""
    if k in tracked:
        return k
    for k2 in tracked:
        if not k2 or len(k2) < 5 or len(k) < 5:
            continue
        if k2.endswith(k) and len(k2) - len(k) <= 3:
            return k2
        if k.endswith(k2) and len(k) - len(k2) <= 3:
            return k2
    return None


def author_upcoming(tracked, today, path=None):
    """Watched authors feed the tracked series (ticket #9): a candidates-file
    book whose Apple page names a series she tracks and whose release is still
    ahead becomes that series' next_books entry — the radar lane and the hero
    countdown pick it up like any other upcoming volume. Released books are
    never radar (they are picks once the window opens). Returns
    {normalized series name: [next_books entry]}."""
    if path is None:
        fs = sorted(glob.glob(os.path.join(BASE, 'data', 'candidates-*.json')))
        path = fs[-1] if fs else None
    if not path or not os.path.exists(path):
        return {}
    try:
        cands = json.load(open(path)).get('books', [])
    except Exception as e:
        print('watched authors: candidates unreadable (%s) — series lane unchanged' % str(e)[:60])
        return {}
    out = {}
    for b in cands:
        ser = (b.get('series') or '').strip()
        if not ser:
            continue
        if not any((f or '').startswith('author:') for f in b.get('found_by') or []):
            continue  # author watches feed the engine — lane-term hits don't merge (#9)
        dt = str(b.get('date') or '')[:10]
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', dt) or dt <= today:
            continue  # released -> a pick, never radar (#9)
        hit = series_key_match(norm_name(ser), tracked)
        if hit is None:
            continue  # not a series she tracks
        title = b.get('title') or ''
        num = str(b.get('series_num') or '').strip()
        if num:
            title = '%s (#%s)' % (title, num)
        out.setdefault(hit, []).append({'title': title, 'release_date': dt,
                                        'status': 'soon', 'publisher': b.get('publisher') or ''})
    return out


def series_data():
    """EVERY series she is in: reads from data/library.json + what's next from
    data/sequels.json. Powers both 'Your Series' and the archive views."""
    lib_path, lib_src = paths.personal('library.json')
    seq_path, seq_src = paths.personal('sequels.json')
    print('data: library.json <- %s · sequels.json <- %s' % (lib_src, seq_src))
    try:
        lib = json.load(open(lib_path))
    except Exception as e:
        print('series: library.json missing (%s)' % e)
        lib = {'series': []}
    try:
        seq = json.load(open(seq_path))
    except Exception:
        seq = {'series': []}
    today = datetime.now().strftime('%Y-%m-%d')
    seqmap = {}
    for ser in seq.get('series', []):
        seqmap[norm_name(ser.get('series'))] = ser

    upcoming = author_upcoming(seqmap, today)  # #9: author watches feed the tracked series
    merged_total = 0

    def merge_upcoming(entry, keys):
        """Append upcoming entries this series does not already know.
        Returns how many landed (the set is updated on append — two same-title
        candidates in one batch must not both land)."""
        have = {norm_name(x.get('title') or '') for x in (entry.get('next_books') or [])}
        n = 0
        for k2 in keys:
            for up in upcoming.get(k2, []):
                t = norm_name(up['title'])
                if t not in have:
                    entry.setdefault('next_books', []).append(up)
                    have.add(t)
                    n += 1
        return n

    used = set()
    out = []
    for ls in lib.get('series', []):
        name = ls.get('name') or ''
        k = norm_name(name)
        entry = seqmap.get(k)
        if entry is None:
            for k2, v2 in seqmap.items():
                if k2 and (k2 in k or k in k2):
                    entry = v2
                    break
        author = ls.get('author') or ''
        books = [{'t': t, 'n': '', 'd': 'read', 'state': 'read', 'iso': '',
                  'id': book_key(t, author)} for t in ls.get('books', [])]
        publisher = ''
        if entry is not None:
            keys = [k2 for k2 in seqmap if k2 and (k2 in k or k in k2)]
            for k2 in keys:
                used.add(k2)
            merged_total += merge_upcoming(entry, keys)
            for nb in entry.get('next_books', []):
                if nb.get('publisher') and not publisher:
                    publisher = nb['publisher']
            ser_author = ls.get('author') or entry.get('author') or ''
            for b in next_books_for(entry, today):
                if any(x['t'].lower() == b['t'].lower() for x in books):
                    continue
                b['id'] = b.get('id') or book_key(b['t'], ser_author)
                books.append(b)
        out.append({'name': name, 'author': ls.get('author') or '', 'publisher': publisher, 'books': books})

    # researched series the library never listed (safety net — nothing gets lost)
    for k2, v2 in seqmap.items():
        if k2 in used:
            continue
        nm = v2.get('series') or ''
        if not nm:
            continue
        merged_total += merge_upcoming(v2, [k2])
        publisher = ''
        for nb in v2.get('next_books', []):
            if nb.get('publisher') and not publisher:
                publisher = nb['publisher']
        nb_list = next_books_for(v2, today)
        for b in nb_list:
            b['id'] = b.get('id') or book_key(b['t'], v2.get('author'))
        out.append({'name': nm, 'author': v2.get('author') or '', 'publisher': publisher,
                    'books': nb_list})
    if merged_total:
        print('author watches: %d upcoming series book(s) merged into the series lane' % merged_total)
    return out


def hero_data(series):
    """The soonest upcoming release across every series — the dark-green hero."""
    cands = []
    for s in series:
        for b in s['books']:
            if b.get('state') == 'soon' and b.get('iso'):
                cands.append((b['iso'], s, b))
    if not cands:
        return None
    iso, s, b = min(cands, key=lambda x: x[0])
    reads = [x['t'] for x in s['books'] if x['state'] == 'read']
    unread = next((x for x in s['books'] if x['state'] == 'out'), None)

    def _join(names):
        if len(names) > 1:
            return ', '.join(names[:-1]) + ' and ' + names[-1]
        return names[0] if names else ''

    if reads:
        standing = 'You have read %s.' % _join(reads[:4])
        if unread:
            n = (' (%s)' % unread['n']) if unread.get('n') else ''
            standing += ' %s%s is still unread.' % (unread['t'], n)
        else:
            standing += ' You are up to date.'
    elif unread:
        n = (' (%s)' % unread['n']) if unread.get('n') else ''
        standing = '%s%s is still unread.' % (unread['t'], n)
    else:
        standing = 'A new chapter in a series you already love.'
    return {'title': b['t'], 'num': b.get('n') or '', 'author': s.get('author') or '',
            'id': b.get('id') or book_key(b['t'], s.get('author')),
            'publisher': s.get('publisher') or '', 'date': pretty_upper(iso), 'iso': iso,
            'seriesRef': s.get('name') or '', 'standing': standing}


def pick_book(b, top_id, img):
    genre = (b.get('genre') or '').strip()
    if re.search(r'fae|dragon|fantasy|romantasy|vampire|fairy|witch', genre, re.I):
        lane = 'romantasy'
    elif re.search(r'hockey|f1|formula|football|baseball|sport|tennis|golf|soccer|racing', genre, re.I):
        lane = 'sport'
    else:
        lane = 'contemporary'
    rating = b.get('rating')
    if isinstance(rating, str):
        gr = rating
    elif isinstance(rating, (int, float)):
        gr = 'GR %s' % rating
    else:
        gr = 'GR —'
    canon = book_key(b.get('title'), b.get('author')) or b.get('id') or slug(b)
    return {
        'id': canon,
        'rawId': b.get('id') or '',
        'img': img or b.get('img') or '',
        'title': b.get('title') or '', 'series': b.get('series') or '',
        'author': b.get('author') or '', 'publisher': b.get('publisher') or '',
        'date': b.get('date') or '', 'genre': genre, 'lane': lane,
        'spice': int(b.get('spice') or 3), 'mmc': int((b.get('mmc') or {}).get('score') or 3),
        'fresh': bool(b.get('fresh')), 'gr': gr,
        'rating': rating if isinstance(rating, (int, float)) else None, 'count': '',
        'formats': b.get('formats') or ['Ebook'], 'tropes': b.get('tropes') or [],
        'hook': b.get('hook') or '', 'fit': b.get('fit') or '',
        'why': b.get('why') or b.get('fit') or '',
        'top': b.get('id') == top_id,
    }


def copy_static():
    """Design runtime + art into dist (support.js, vendored React, .lavish assets)."""
    os.makedirs(os.path.join(DIST, 'assets', 'vendor'), exist_ok=True)
    pairs = [
        (os.path.join(DESIGN, 'support.js'), os.path.join(DIST, 'support.js')),
        (os.path.join(DESIGN, 'manifest.webmanifest'), os.path.join(DIST, 'manifest.webmanifest')),
        (os.path.join(DESIGN, 'assets', 'app-icon-180.png'), os.path.join(DIST, 'assets', 'app-icon-180.png')),
        (os.path.join(DESIGN, 'assets', 'app-icon-192.png'), os.path.join(DIST, 'assets', 'app-icon-192.png')),
        (os.path.join(DESIGN, 'assets', 'app-icon-512.png'), os.path.join(DIST, 'assets', 'app-icon-512.png')),
        (os.path.join(DESIGN, 'assets', 'app-icon-maskable-512.png'), os.path.join(DIST, 'assets', 'app-icon-maskable-512.png')),
        (os.path.join(DESIGN, 'vendor', 'react.production.min.js'), os.path.join(DIST, 'assets', 'vendor', 'react.production.min.js')),
        (os.path.join(DESIGN, 'vendor', 'react-dom.production.min.js'), os.path.join(DIST, 'assets', 'vendor', 'react-dom.production.min.js')),
    ]
    for src, dst in pairs:
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            print('missing static: %s' % src)
    for cand in (os.path.join(ROOT, 'assets'), os.path.join(ROOT, '.lavish', 'assets')):
        if os.path.isdir(cand):
            shutil.copytree(cand, os.path.join(DIST, 'assets'), dirs_exist_ok=True)
            break


def main():
    month_files = sorted(glob.glob(os.path.join(BASE, 'data', 'month-*.json')))
    cur_ym = datetime.now().strftime('%Y-%m')
    stale, valid = [], []
    for mf in month_files:
        ym = os.path.basename(mf)[len('month-'):-len('.json')]
        if not re.match(r'^\d{4}-\d{2}$', ym):
            valid.append(mf)
            continue
        if ym > cur_ym:
            stale.append(mf)   # future month — never valid
            continue
        if ym == cur_ym:
            # a CURRENT-month file is legit only when an ad-hoc rolling run
            # wrote it (mode: adhoc); anything else is legacy junk
            try:
                body = json.load(open(mf))
            except Exception:
                body = {}
            if body.get('mode') != 'adhoc':
                stale.append(mf)
                continue
        valid.append(mf)
    for mf in stale:
        try:
            os.remove(mf)
            print('purged stale month file: %s' % os.path.basename(mf))
        except Exception as e:
            print('could not purge %s: %s' % (mf, e))
    month_files = valid
    # defensive: an EMPTY month file (e.g. a bad model output that overwrote a
    # good one) is restored from the baked baseline — never render an empty shelf
    fixed = []
    for mf in month_files:
        try:
            cur = json.load(open(mf))
        except Exception:
            fixed.append(mf)
            continue
        if not cur.get('books'):
            bl = os.path.join(BASE, 'baseline', os.path.basename(mf))
            if os.path.exists(bl):
                shutil.copy2(bl, mf)
                print('restored empty month %s from baseline' % os.path.basename(mf))
            else:
                try:
                    os.remove(mf)
                    print('removed empty month file %s (no baseline)' % os.path.basename(mf))
                except Exception:
                    pass
                continue
        fixed.append(mf)
    month_files = fixed
    if not month_files:
        # A blank install (the repo ships blank): a valid, quiet page — never a
        # 404, never a crash. The app renders its own empty states from this.
        copy_static()
        data = {'month': {'label': 'Awaiting first run', 'short': '\u2014', 'drop': '', 'count': 0,
                          'issue': 0, 'titles': 'no titles yet', 'shapeLine': '', 'light': False},
                'hero': None, 'books': [], 'pending': [], 'series': [],
                'quotes': QUOTES.get(SEASON_OF.get(datetime.now().month, 'fall'), QUOTES['fall']),
                'criteria': CRITERIA}
        os.makedirs(DIST, exist_ok=True)
        open(os.path.join(DIST, 'shelf-data.js'), 'w').write(
            'window.SHELF_DATA=' + json.dumps(data, ensure_ascii=False) + ';\n')
        tpl = open(os.path.join(DESIGN, 'app.html')).read()
        tpl = tpl.replace('__SHELF_TITLE__', 'The Shelf \u2014 awaiting first run')
        open(os.path.join(DIST, 'index.html'), 'w').write(tpl)
        print('built blank-state page (no months yet)')
        return 0

    order = [os.path.basename(mf)[len('month-'):-len('.json')] for mf in month_files]
    cur_ym = order[-1]
    ml = month_label(cur_ym)
    cur = json.load(open(os.path.join(BASE, 'data', 'month-%s.json' % cur_ym)))

    # ---- this month's picks: top pick first ----
    # the cover cache lives on the VOLUME so a redeploy never re-downloads art;
    # it is mirrored into the served dist at the end of every build
    covers_dir = os.path.join(BASE, 'data', 'covers')
    os.makedirs(covers_dir, exist_ok=True)
    os.makedirs(os.path.join(DIST, 'assets', 'covers'), exist_ok=True)
    top_id = cur.get('top_pick')
    src = sorted(cur.get('books', []), key=lambda b: 0 if b.get('id') == top_id else 1)
    book_list = [pick_book(b, top_id, ensure_cover(b.get('img'), b.get('title'), b.get('author'), covers_dir)) for b in src]

    # ---- still on your list: unresolved books from EARLIER issues ----------
    # Every earlier issue's picks ship so the app can carry forward whatever she
    # never decided on. Resolution belongs to the app: it owns the reader state.
    # Newest issue first, one entry per book (a re-recommendation wins).
    pending, seen_pending = [], set()
    shelf_ex = exclusion_set()  # your verdicts steer the carry-over too (#7)
    held_back = 0
    for mf in reversed(month_files):
        ym = os.path.basename(mf)[len('month-'):-len('.json')]
        if ym == cur_ym:
            continue
        try:
            body = json.load(open(mf))
        except Exception:
            continue
        mlp = month_label(ym)
        for b in body.get('books', []):
            pb = pick_book(b, None, ensure_cover(b.get('img'), b.get('title'), b.get('author'), covers_dir))
            if not pb['id'] or pb['id'] in seen_pending:
                continue
            if pb['id'] in shelf_ex:
                held_back += 1
                continue
            seen_pending.add(pb['id'])
            pb['issue'] = {'n': (order.index(ym) + 1) if ym in order else 0,
                           'label': mlp['label'], 'ym': ym}
            pending.append(pb)
    print('carried over: %d unresolved books from %d earlier issues (%d held back by your shelf)'
          % (len(pending), len(set(p['issue']['ym'] for p in pending)), held_back))

    series = series_data()
    hero = hero_data(series)
    if hero:
        hero['cover'] = ensure_cover('', hero.get('title'), hero.get('author'), covers_dir)
    y, m = int(cur_ym[:4]), int(cur_ym[5:7])
    month = {
        'label': '%s %d' % (ml['name'].upper(), y),
        'short': '%s %d' % (MONTH_NAMES[m - 1], y),
        'drop': 'Dropped 1 %s %d' % (ml['name'], y),
        'count': len(book_list),
        'issue': len(order),
        'titles': WORDS.get(len(book_list), str(len(book_list))) + (' title' if len(book_list) == 1 else ' titles'),
    }
    _lc = lane_counts(book_list)
    month['shape'] = shape_str(_lc)          # the shape it shipped (ticket #6)
    month['shapeLine'] = shape_line(_lc)
    month['light'] = len(book_list) < CFG['target_books'][0]  # under the floor -> light month

    for b in book_list:                      # this issue's own provenance
        b['issue'] = {'n': month['issue'], 'label': ml['label'], 'ym': cur_ym}

    copy_static()
    # mirror the volume cover cache into the served dist
    try:
        shutil.copytree(covers_dir, os.path.join(DIST, 'assets', 'covers'), dirs_exist_ok=True)
    except Exception as e:
        print('covers mirror: %s' % str(e)[:80])
    # quotes follow the CALENDAR season — same clock the design's coffee art uses
    quotes = QUOTES.get(SEASON_OF.get(datetime.now().month, 'fall'), QUOTES['fall'])
    # identity guard: every book the app can mark must carry a canonical id
    orphans = [b['t'] for s in series for b in s['books'] if not b.get('id')]
    orphans += [b['title'] for b in book_list if not b.get('id')]
    if orphans:
        print('WARNING: %d books have no identity: %s' % (len(orphans), orphans[:5]))
    data = {'month': month, 'hero': hero, 'books': book_list, 'pending': pending,
            'series': series, 'quotes': quotes, 'criteria': CRITERIA}
    os.makedirs(DIST, exist_ok=True)
    open(os.path.join(DIST, 'shelf-data.js'), 'w').write(
        'window.SHELF_DATA=' + json.dumps(data, ensure_ascii=False) + ';\n')

    tpl = open(os.path.join(DESIGN, 'app.html')).read()
    tpl = tpl.replace('__SHELF_TITLE__', 'The Shelf — %s · Sport Romance · Romantasy · Contemporary Romance' % ml['label'])
    open(os.path.join(DIST, 'index.html'), 'w').write(tpl)
    print('built dist (current: %s, %d books, %d series, issue no. %d)'
          % (cur_ym, len(book_list), len(series), month['issue']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
