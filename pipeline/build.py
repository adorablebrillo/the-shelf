#!/usr/bin/env python3
"""The Shelf pipeline — stage 4: build dist/ for the redesigned app.

The page (pipeline/design/app.html) is a design-component runtime page; this
script feeds it live data via dist/shelf-data.js:

  month   — the current drop (label, issue number, count)
  hero    — the soonest upcoming release in ANY series she is reading
  books   — this month's picks (top pick first)
  series  — EVERY series she is in: read volumes (data/library.json) merged
            with released-unread / upcoming / announced (data/sequels.json)
  seasons — the season table: dates, drink and quote pool for each season
  criteria — the filtering rules, shown in the footer
  added   — books she added herself by search (/config/added-books.json, #84);
            the app files them on My Shelf or in the Archive, never on Home

Pure stdlib; assets + vendored runtime are copied into dist/ here too, so the
same code path runs at image-bake time and after every pipeline run.
"""
import json, os, re, shutil, sys, time, urllib.request, urllib.parse, hashlib, calendar, glob
from datetime import datetime
import paths  # shared resolver: reader data lives on the volume (CFG_DIR)
import synopses  # #51: the synopsis chain + its volume cache
import lanes
from lanes import counts as lane_counts, shape_str, shape_line
import interests
from bookids import book_key
from shelf_state import exclusion_set
from verdicts import because_line
import sequels  # the series her read and loved marks track

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CFG = json.load(open(os.path.join(BASE, 'config.json')))
INTS = interests.load()  # her Book-a-meter: the names and labels the page shows
DESIGN = os.path.join(BASE, 'design')
# In the container the SERVER serves /app/dist (server.py lives at /app).
# Docker COPY flattens the repo's container/dist -> pipeline/dist symlink, so
# the pipeline and server MUST share one dist dir via DIST_DIR (set in the
# Dockerfile). Locally it stays pipeline/dist for repo layout compat.
DIST = os.environ.get('DIST_DIR') or os.path.join(BASE, 'dist')
# The quick boot build (server.py, before it opens the port): SHELF_OFFLINE=1
# builds from saved data only — cached covers and cached synopses, no network
# request at all — so a restart serves the page in seconds. The full build that
# follows in the background fills what the quick one left out.
OFFLINE = os.environ.get('SHELF_OFFLINE') == '1'

MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
WORDS = {1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine', 10: 'ten'}
CRITERIA = ('M/F only · dark romance & dark academia welcome · no cowboy/western · spice 3–5 · trad-pub first, indie with proof · '
            'released last month · sequels only for series you are already in')


def criteria_line():
    """The criteria strip, honest about her interests: the default text holds
    while every active interest is a new-release romance and the never list is
    her cowboys rule (the blank install's shelf). Anything else — a topic
    interest, a best-ever mode, another never word — is said plainly."""
    act = interests.active(INTS)
    non_rom = [i for i in act if not interests.romance(i)]
    best = [i for i in act if interests.best_ever(i)]
    nv = interests.never(INTS)
    if not non_rom and not best and nv == [w.lower() for w in interests.DEFAULT_NEVER]:
        return CRITERIA
    bits = []
    rom = 'M/F only · dark romance & dark academia welcome · spice 3–5'
    bits.append('romance interests: ' + rom if non_rom else rom)
    if nv:
        bits.append('never: ' + ' · '.join('no ' + w for w in nv))
    bits.append('trad-pub first, indie with proof')
    if best:
        bits.append('new releases last month; best-ever interests any date, rated 4.0+')
    else:
        bits.append('released last month')
    bits.append('sequels only for series you are already in')
    return ' · '.join(bits)

# The season table: ONE clock for the sidebar drink, its label, the seasonal
# look and the reading-corner quote. Each season runs from its start day to its
# end day inclusive ('MM-DD'); a season whose end is before its start wraps the
# new year. Every day of the year belongs to exactly one season (test_seasons.py
# owns that). The table ships to the page in shelf-data.js and the page picks
# the season from the reader's LOCAL date (same clock as the daily quote, #55),
# so it flips at local midnight — never at build time.
#
# Each season's quotes show one a day, in order from the season's first day
# (day index = days since the start, modulo the pool). The four non-Christmas
# pools alternate a new line with one of the original twelve.
_POOLS = {
    'winter': ['a snow day is a reading day.',
              'cocoa swirl, two marshmallows, one more chapter.',
              'new year, new book boyfriend.',
              'snow outside — a whole shelf inside.',
              'frost on the glass, a fae king at the gate.',
              'hot cocoa, cold nights, warm plots.',
              'valentines are nice; book boyfriends are better.',
              'cocoa in hand, epilogue in sight.',
              'the snow piles up; so does the TBR.',
              'winter chapters read best under a blanket.',
              'a long night, a longer book, a warm mug.',
              'a marshmallow melts; a plot thickens.',
              'cold rink, hot captain, warm cocoa.',
              'tea for the throat, romance for the soul.',
              'slippers, a blanket and forced proximity.',
              'the kettle sings; the story hums.',
              'a winter cabin, one bed, no wifi.',
              'frost on the window, fire in the plot.',
              "the kettle's on and the snow won't stop.",
              'one cup, one chapter, one very long night.',
              'cold days are for warm endings.',
              'cocoa season: stir slowly, read fast.',
              'short days, long chapters, slow kisses.',
              'cold hands, warm book, perfect evening.'],
    'spring': ['new buds, new books, new crushes.',
              'cherry-blossom latte and a fresh TBR.',
              'pink petals, pink latte, a meet-cute.',
              'bloom season is plot season.',
              'open the window, open the book.',
              'petals fall — you fall into books.',
              'a rainy afternoon and a second-chance romance.',
              'a warm latte for the first chapter.',
              'lights out: a new race season and a racing romance.',
              'spring cleaning, except the shelf.',
              'fresh flowers on the table, fresh pages in hand.',
              'new season, new shelf, same coffee.',
              'the cherry trees bloom for exactly one chapter.',
              'april showers, may flowers, always chapters.',
              'soft rain, warm latte, a slow-burn bloom.',
              'iced or hot, the book is the point.',
              'a garden party, a rival, a very good book.',
              'the garden can wait; the chapter cannot.',
              'longer evenings mean longer chapters.',
              'fresh pages smell like spring.',
              'a flower crown for the fae queen, a latte for me.',
              'one latte, one love story, one afternoon.',
              "bloom where you're reading.",
              'buds and beginnings, chapters and cream.'],
    'summer': ['a lemon iced latte and a holiday romance.',
              'lemon ice, a lounger, a slow-burn.',
              'beach bag: one towel, three paperbacks.',
              'the sun is up — so is your TBR.',
              'long light, long chapters, no alarm.',
              'iced hands, warmer pages.',
              'a summer fling on the page, ice in the glass.',
              'iced coffee, hot plot.',
              'the hammock is my reading room now.',
              'sand in the pages, salt in the air.',
              'salt on the skin, spice on the page.',
              'the shade, the stack, the refill.',
              'the pool can wait; the grovel cannot.',
              'pages turn faster in the sun.',
              'late sunsets were made for one more chapter.',
              'an iced latte and a slow afternoon.',
              'a lemon slice, a slow afternoon, a fast plot.',
              'sunscreen, sunglasses, a very good book.',
              'off-season for football, on-season for football romance.',
              'chapters by the pool, condensation on the glass.',
              'a road trip, a fake date, a tall iced coffee.',
              'sweet reads, cold drinks, long days.',
              'warm nights, cold brew, hot heroes.',
              "heatwave? perfect — the book's in charge."],
    'autumn': ['a maple latte and a dark academia romance.',
              'pumpkin spice on the shelf, spice on the page.',
              'rain on the window, a rival in the library.',
              "a good book, a warm cup — that's the whole agenda.",
              'crisp leaves outside, a slow burn inside.',
              'curl up. the leaves changed, so did your TBR.',
              'candles lit, blanket on, one more chapter.',
              'one more chapter, one more cup — the fire can wait.',
              'apple cider and a forbidden kiss.',
              'autumn is for slow mornings, long chapters, warm mugs.',
              'the nights grow longer; so does the TBR.',
              'a spiced latte and a slow burn — seasonal perfection.',
              'pumpkin spice and a very morally grey hero.',
              'the leaves turn; so do the pages.',
              'a haunted manor, a brooding lord, a second cup.',
              'paperbacks by the window, steam on the glass.',
              'fog on the hills, a fae prince at the door.',
              'cinnamon on the foam, cliffhangers on the nightstand.',
              'cardigan on, phone off, plot twist ahead.',
              'sweater weather, paperback weather.',
              'a warm mug, a cold night, a slow-burn kiss.',
              'the best plots brew slowly.',
              'hockey season starts; so does the hockey romance.',
              'every good book deserves a refill.'],
    'christmas': ['november counts as christmas if the mug says so.',
                  'peppermint mocha, fairy lights, one more chapter.',
                  'deck the halls with paperbacks.',
                  'a gingerbread latte and a slow-burn by the fire.',
                  'all i want for christmas is an uninterrupted chapter.',
                  'candy cane in the cocoa, cliffhanger on the page.',
                  'the best presents have spines.',
                  'wrapped in a blanket, wrapped up in a plot.',
                  'tree lights on, phone down, book open.',
                  'snowed in with a grumpy hero and a cocoa.',
                  'mistletoe in the story, a book under the tree.',
                  'an eggnog latte and an enemies-to-lovers.',
                  'dear santa: more hours for reading, please.',
                  'the fire crackles; so does the banter.',
                  'silent night, loud plot twist.',
                  'frosted windows, hot mocha, a happily-ever-after.',
                  'cinnamon, clove and a very good book.',
                  'stockings hung, mugs filled, chapters waiting.',
                  'the lights are up, the mugs are out, the book is open.',
                  'the prettiest pile under the tree is the book pile.',
                  'a mountain of whipped cream, a page-turner to match.',
                  "it's the most wonderful time to read in bed.",
                  'jingle bells, turning pages, one warm mug.',
                  'christmas morning: coffee first, then the epilogue.'],
}

# A season's corner: the reading-corner colours (outer band, inner panel, border,
# small caps, quote, bottom line). Each season's drawings — the seal garland
# with its rim words, the four small sidebar drawings and the corner sprig —
# live in design/app.html under the season's key (SVG text cannot take a
# template value, so the rim words are drawn there too).
def _corner(outer, inner, border, eyebrow, quote, recent):
    return {'outer': outer, 'inner': inner, 'border': border,
            'eyebrow': eyebrow, 'quote': quote, 'recent': recent}


SEASONS = [
    {'key': 'autumn', 'start': '09-01', 'end': '10-31',
     'drink': {'img': 'assets/coffee-2.png', 'alt': 'Ink drawing of a pumpkin spice latte', 'label': 'pumpkin spice season'},
     'corner': _corner('#6F3519', '#8A4524', '#D9B77A', '#F0D3A8', '#FBF1E4', '#F0D3A8')},  # rust
    {'key': 'christmas', 'start': '11-01', 'end': '01-06',
     'drink': {'img': 'assets/coffee-winter-b.png', 'alt': 'Ink drawing of a candy cane cocoa', 'label': 'christmas cocoa season'},
     'corner': _corner('#5A2121', '#6E2A2A', '#C8B27A', '#E3D1A0', '#F6EFE2', '#E3D1A0')},  # oxblood
    {'key': 'winter', 'start': '01-07', 'end': '02-29',
     'drink': {'img': 'assets/coffee-3.png', 'alt': 'Ink drawing of a cinnamon latte', 'label': 'cinnamon latte season'},
     'corner': _corner('#1E2A3B', '#26364C', '#C8B27A', '#E3D1A0', '#F3EDE1', '#E3D1A0')},  # midnight
    {'key': 'spring', 'start': '03-01', 'end': '05-31',
     'drink': {'img': 'assets/coffee-spring-b.png', 'alt': 'Ink drawing of a flower latte', 'label': 'blossom season'},
     'corner': _corner('#D9A9AE', '#E8C4C6', '#8A6C31', '#5A3E40', '#211E19', '#7A2F3E')},  # rose
    {'key': 'summer', 'start': '06-01', 'end': '08-31',
     'drink': {'img': 'assets/coffee-summer-b.png', 'alt': 'Ink drawing of an iced coffee with lemon', 'label': 'iced coffee season'},
     'corner': _corner('#B8CDD0', '#D6E4E5', '#8A6C31', '#3F5458', '#211E19', '#2B5559')},  # sea glass
]
for _s in SEASONS:
    _s['quotes'] = _POOLS[_s['key']]


def season_of(month, day):
    """The season key for a calendar day — the same test the page runs on the
    reader's local date (app.html seasonNow)."""
    md = '%02d-%02d' % (month, day)
    for s in SEASONS:
        a, b = s['start'], s['end']
        if (a <= md <= b) if a <= b else (md >= a or md <= b):
            return s['key']
    return None


# a saved cover miss is looked up again after this many days
COVER_MISS_DAYS = 30
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


def _norm_title(s):
    return re.sub(r'[^a-z0-9]+', '', (s or '').lower())


def _title_ok(want, got):
    """#42 review: only accept art whose candidate title really is this book —
    a long substring match or a distinctive shared word. Never for empty,
    'untitled' or 'tba' titles, so an unannounced volume can't borrow a
    neighbour's cover."""
    w = _norm_title(want)
    if len(w) < 3 or w.startswith('untitled') or w in ('tba', 'tbd', 'titletba'):
        return False
    g = _norm_title(got)
    if not g:
        return False
    if len(w) >= 8 and (w in g or (len(g) >= 8 and g in w)):
        return True
    if w == g:
        return True
    wt = [t for t in re.split(r'[^a-z0-9]+', (want or '').lower()) if len(t) >= 5]
    gt = set(t for t in re.split(r'[^a-z0-9]+', (got or '').lower()) if len(t) >= 5)
    return any(t in gt for t in wt)


def lookup_cover_url(title, author):
    """Real cover art for a book: iTunes ebooks -> Google Books -> Open Library.
    No API keys needed; returns a full-size-ish image URL, '' when every
    provider answered and none has art (a real miss), or None when a provider
    failed (refused with 403/429, quota, timeout) and none had art — a failure
    is not a miss: the caller must not save it, the next build retries.
    Every provider must pass _title_ok — a wrong cover is worse than a
    placeholder (the #42 review found 'Untitled' borrowing Iron Flame's art)."""
    t = (title or '').strip()
    a = (author or '').strip()
    if not t or not _title_ok(t, t):
        return ''
    last = a.split()[-1].lower() if a else ''
    failed = False
    try:
        q = urllib.parse.urlencode({'term': ('%s %s' % (t, a)).strip(), 'media': 'ebook',
                                    'entity': 'ebook', 'limit': 8, 'country': CFG.get('apple_country', 'us')})
        results = _get_json('https://itunes.apple.com/search?' + q).get('results', [])
        for it in results:
            name = it.get('trackName') or ''
            art = it.get('artworkUrl100') or it.get('artworkUrl60') or ''
            author_ok = (not last) or (last in (it.get('artistName') or '').lower())
            if art and author_ok and _title_ok(t, name):
                return art.replace('100x100bb', '600x600bb').replace('60x60bb', '600x600bb').replace('100x100', '600x600')
    except Exception as e:
        failed = True
        print('cover lookup (itunes): %s' % str(e)[:70])
    try:
        q = urllib.parse.quote('intitle:"%s"%s' % (t, (' inauthor:"%s"' % a) if a else ''))
        d = _get_json('https://www.googleapis.com/books/v1/volumes?q=%s&maxResults=5&country=US' % q)
        for it in d.get('items', []):
            vi = it.get('volumeInfo') or {}
            links = (vi.get('imageLinks') or {})
            u = links.get('thumbnail') or links.get('smallThumbnail')
            auts = [x.lower() for x in (vi.get('authors') or [])]
            author_ok = (not last) or (not auts) or any(last in x for x in auts)
            if u and author_ok and _title_ok(t, vi.get('title')):
                return u.replace('http://', 'https://').replace('&edge=curl', '')
    except Exception as e:
        failed = True
        print('cover lookup (google): %s' % str(e)[:70])
    try:
        q = urllib.parse.quote(('%s %s' % (t, a)).strip())
        d = _get_json('https://openlibrary.org/search.json?q=%s&limit=3&fields=cover_i,title,author_name' % q)
        for doc in d.get('docs', []):
            auts = [x.lower() for x in (doc.get('author_name') or [])]
            author_ok = (not last) or (not auts) or any(last in x for x in auts)
            if doc.get('cover_i') and author_ok and _title_ok(t, doc.get('title')):
                return 'https://covers.openlibrary.org/b/id/%s-L.jpg' % doc['cover_i']
    except Exception as e:
        failed = True
        print('cover lookup (openlibrary): %s' % str(e)[:70])
    return None if failed else ''


def ensure_cover(img, title, author, covers_dir):
    """A usable LOCAL cover path — the declared image when it works, otherwise
    fetched real cover art (cached by slug so rebuilds stay offline).
    OFFLINE: the slug cache or the declared image, never a request and never a
    miss sentinel (a quick build cannot know a lookup would miss)."""
    name = slug({'title': title or 'x', 'author': author or 'y'}) + '.jpg'
    if img:
        if img.startswith('assets/') and os.path.isfile(os.path.join(DIST, img)):
            return img
        if img.startswith('http') and not OFFLINE:
            local = download_cover({'img': img, 'title': title, 'author': author}, covers_dir)
            if local:
                return local
    if os.path.isfile(os.path.join(covers_dir, name)):
        return 'assets/covers/%s' % name
    if OFFLINE:
        return img or ''
    # #42 review: cache the miss too — a '<slug>.none' sentinel keeps rebuilds
    # offline (no re-attempting three providers per artless volume). Only a
    # real miss is saved: a refused or failed lookup is retried by the next
    # build. A saved miss expires after COVER_MISS_DAYS, so art published
    # later — and misses older builds saved for refusals — get a new lookup.
    miss = os.path.join(covers_dir, name[:-4] + '.none')
    try:
        if time.time() - os.path.getmtime(miss) < COVER_MISS_DAYS * 86400:
            return img or ''
    except OSError:
        pass                                  # no saved miss
    url = lookup_cover_url(title, author)
    if url:
        local = download_cover({'img': url, 'title': title, 'author': author}, covers_dir)
        if local:
            print('cover fetched: %s' % (title or '')[:44])
            return local
        return img or ''                      # the art did not download: retried, not a miss
    if url is None:
        return img or ''                      # a provider failed: retried, not a miss
    try:
        with open(miss, 'w') as f:
            f.write('no cover found %s\n' % datetime.now().date().isoformat())
    except Exception:
        pass
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


def series_data(covers_dir=None):
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

    # the series her read, loved and reading-now marks track: they join the tracked map so
    # their next books merge the same way, and list only once one is known
    marked = {}
    for g in sequels.from_marks(os.path.join(BASE, 'data')):
        k = norm_name(g['series'])
        if k and k not in seqmap:
            marked[k] = g
            seqmap[k] = {'series': g['series'], 'author': g['author'], 'next_books': []}

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

    covers_dir = covers_dir or os.path.join(BASE, 'data', 'covers')
    os.makedirs(covers_dir, exist_ok=True)
    cov = {'resolved': 0, 'cached': 0, 'fetched': 0, 'placeholder': 0, 'noart': 0, 'preset': 0}
    handled = set()

    def attach_covers(books, author):
        """#42: every volume gets cover art when art exists anywhere — the same
        iTunes -> Google Books -> Open Library resolution the picks use, cached
        by slug so rebuilds stay offline. No art anywhere -> deliberate
        placeholder (an empty img — the app keeps its striped treatment)."""
        for b in books:
            if b.get('img'):
                cov['preset'] += 1
                continue
            # #42 review: an unannounced volume ('tba', or a title that is
            # empty/'untitled') never gets a lookup — a deliberate placeholder.
            if (b.get('state') or '').lower() == 'tba' or not _title_ok(b.get('t') or '', b.get('t') or ''):
                cov['placeholder'] += 1
                continue
            name = slug({'title': b.get('t') or 'x', 'author': author or 'y'}) + '.jpg'
            was = name in handled or os.path.isfile(os.path.join(covers_dir, name))
            img = ensure_cover('', b.get('t') or '', author or '', covers_dir)
            b['img'] = img or ''
            handled.add(name)
            if img:
                cov['resolved'] += 1
                cov['cached' if was else 'fetched'] += 1
            else:
                cov['noart'] += 1             # looked up, no art yet (a miss or a failed lookup)

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
        attach_covers(books, ls.get('author') or (entry.get('author') if entry is not None else '') or '')
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
        if k2 in marked:
            # a book she is reading now is out and unread: it is a next book too
            if not nb_list and not any(rb.get('reading') for rb in marked[k2]['books']):
                continue  # no next book known yet: the Series page waits for one
            read = [{'t': rb['title'], 'n': ('#' + rb['num']) if rb['num'] else '',
                     'd': 'reading' if rb.get('reading') else 'read',
                     'state': 'out' if rb.get('reading') else 'read', 'iso': '', 'id': rb['id']}
                    for rb in marked[k2]['books']]
            have = {x['t'].lower() for x in read}
            nb_list = read + [b for b in nb_list if b['t'].lower() not in have]
        attach_covers(nb_list, v2.get('author') or '')
        out.append({'name': nm, 'author': v2.get('author') or '', 'publisher': publisher,
                    'books': nb_list})
    if merged_total:
        print('author watches: %d upcoming series book(s) merged into the series lane' % merged_total)
    total = cov['resolved'] + cov['noart'] + cov['placeholder']
    extra = (', %d pre-set' % cov['preset']) if cov['preset'] else ''
    print('series covers: %d of %d volumes resolved real art (%d from cache, %d fetched%s), %d without art, %d deliberate placeholders'
          % (cov['resolved'], total, cov['cached'], cov['fetched'], extra, cov['noart'], cov['placeholder']))
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


def _int(v, default):
    """Model-written numbers arrive as anything: '3.5', '3', 3.5, None.
    Coerce leniently — a bad value must never take the shelf down."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def pick_series(b):
    """The series line on a pick card: its name, with the volume number when
    curate copied one from the candidate ('Mist Court #1')."""
    ser = (b.get('series') or '').strip()
    num = str(b.get('series_num') or '').strip()
    if ser and num and '#' not in ser:
        ser = '%s #%s' % (ser, num)
    return ser


def pick_book(b, top_id, img):
    genre = (b.get('genre') or '').strip()
    # a pick's interest: the search that found it (its lane field, set by
    # fetch and copied onto the pick in curate), else the genre fallback —
    # Home shows the interest name where it showed the lane name. The full
    # name stays: the shape line counts these keys, and nothing on the card
    # needs the old short forms (only 'romantasy' is compared, unchanged).
    lane = lanes.interest_of(b)
    # the romance score rows (spice, MMC vibe, the archetype note) show only
    # for a romance interest's picks — a real-life topic book's card reads
    # like its book. An interest the file does not name keeps the rows (the
    # pre-interests months rendered them for every pick).
    _iobj = interests.by_name(INTS, lane)
    score_rows = True if _iobj is None else interests.romance(_iobj)
    rating = b.get('rating')
    if isinstance(rating, str):
        gr = rating
    elif isinstance(rating, (int, float)):
        gr = 'GR %s' % rating
    else:
        gr = 'GR —'
    canon = book_key(b.get('title'), b.get('author')) or b.get('id') or slug(b)
    # the model drifts: spice arrives as '3.5', mmc as a bare '4' instead of an
    # object. A bare int() here killed the whole build (and with it the page).
    mmc_raw = b.get('mmc')
    mmc_score = mmc_raw.get('score') if isinstance(mmc_raw, dict) else mmc_raw
    return {
        'id': canon,
        'rawId': b.get('id') or '',
        'img': img or b.get('img') or '',
        'title': b.get('title') or '', 'series': pick_series(b),
        'author': b.get('author') or '', 'publisher': b.get('publisher') or '',
        'date': b.get('date') or '', 'genre': genre, 'lane': lane, 'scoreRows': score_rows,
        'spice': _int(b.get('spice'), 3), 'mmc': _int(mmc_score, 3),
        'fresh': bool(b.get('fresh')), 'gr': gr,
        'rating': rating if isinstance(rating, (int, float)) else None, 'count': '',
        'formats': b.get('formats') or ['Ebook'], 'tropes': b.get('tropes') or [],
        'hook': b.get('hook') or '', 'fit': b.get('fit') or '',
        'why': b.get('why') or b.get('fit') or '',
        # #83: the one line naming the loved/want book that steered the pick
        'because': because_line(b.get('because')),
        'top': b.get('id') == top_id,
    }


def write_dist(name, text):
    """Write one served file via a temp file + rename: the server keeps
    serving while a build runs (the boot full build, a curate-now run), and a
    request must never read a half-written page or data file."""
    os.makedirs(DIST, exist_ok=True)
    path = os.path.join(DIST, name)
    tmp = '%s.tmp-%d' % (path, os.getpid())
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def added_data(covers_dir):
    """Books she added by search (#84), shaped like picks so the app's My Shelf
    and Archive rows render them unchanged. A missing file is an empty list."""
    try:
        raw = json.load(open(os.path.join(paths.cfg_dir(), 'added-books.json'))).get('books') or []
    except FileNotFoundError:
        raw = []
    except Exception as e:
        print('added books: unreadable (%s) — shipping none' % str(e)[:60])
        raw = []
    out, seen = [], set()
    for b in raw:
        if not isinstance(b, dict):
            continue
        ab = pick_book(b, None, ensure_cover(b.get('img'), b.get('title'), b.get('author'), covers_dir))
        if not ab['id'] or ab['id'] in seen:
            continue
        seen.add(ab['id'])
        ab['added'] = True
        ab['seriesNum'] = b.get('series_num') or ''
        # a Goodreads import keeps the export's Book Id: its own page, surer
        # than any lookup (synopses.attach keeps it over a found id)
        gid = re.sub(r'\D', '', str(b.get('gr') or ''))
        if gid:
            ab['grUrl'] = synopses.gr_url(gid)
        out.append(ab)
    return out


def copy_static():
    """Design runtime + art into dist (support.js, vendored React, .lavish assets)."""
    os.makedirs(os.path.join(DIST, 'assets', 'vendor'), exist_ok=True)
    pairs = [
        (os.path.join(DESIGN, 'support.js'), os.path.join(DIST, 'support.js')),
        (os.path.join(DESIGN, 'manifest.webmanifest'), os.path.join(DIST, 'manifest.webmanifest')),
        (os.path.join(DESIGN, 'vendor', 'react.production.min.js'), os.path.join(DIST, 'assets', 'vendor', 'react.production.min.js')),
        (os.path.join(DESIGN, 'vendor', 'react-dom.production.min.js'), os.path.join(DIST, 'assets', 'vendor', 'react-dom.production.min.js')),
    ]
    for src, dst in pairs:
        if os.path.exists(src):
            shutil.copy2(src, dst)
        else:
            print('missing static: %s' % src)
    # every app icon (adding a size = drop the file + a manifest entry)
    icons = os.path.join(DESIGN, 'assets')
    if os.path.isdir(icons):
        for fn in sorted(os.listdir(icons)):
            if fn.startswith('app-icon') and fn.endswith('.png'):
                shutil.copy2(os.path.join(icons, fn), os.path.join(DIST, 'assets', fn))
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
        covers_dir = os.path.join(BASE, 'data', 'covers')
        os.makedirs(covers_dir, exist_ok=True)
        added = added_data(covers_dir)
        if added:
            syn_cache = synopses.load()
            synopses.attach([(b, b.get('title'), b.get('author')) for b in added], syn_cache,
                            budget=0 if OFFLINE else None)
            synopses.save(syn_cache)
        try:
            shutil.copytree(covers_dir, os.path.join(DIST, 'assets', 'covers'), dirs_exist_ok=True)
        except Exception as e:
            print('covers mirror: %s' % str(e)[:80])
        data = {'month': {'label': 'Awaiting first run', 'short': '\u2014', 'drop': '', 'count': 0,
                          'issue': 0, 'titles': 'no titles yet', 'shapeLine': '', 'light': False},
                'hero': None, 'books': [], 'pending': [], 'series': [], 'resolved': [],
                'added': added, 'seasons': SEASONS,
                'criteria': CRITERIA}
        write_dist('shelf-data.js', 'window.SHELF_DATA=' + json.dumps(data, ensure_ascii=False) + ';\n')
        tpl = open(os.path.join(DESIGN, 'app.html')).read()
        tpl = tpl.replace('__SHELF_TITLE__', 'The Shelf \u2014 awaiting first run')
        write_dist('index.html', tpl)
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
    shelf_ex = exclusion_set()  # your verdicts steer this month's picks too (#7)
    top_id = cur.get('top_pick')
    src = [b for b in sorted(cur.get('books', []), key=lambda b: 0 if b.get('id') == top_id else 1)
           if book_key(b.get('title'), b.get('author')) not in shelf_ex]
    month_held = len(cur.get('books', [])) - len(src)
    if month_held:
        print('month picks held back by your shelf: %d' % month_held)
    book_list = [pick_book(b, top_id, ensure_cover(b.get('img'), b.get('title'), b.get('author'), covers_dir)) for b in src]

    # ---- resolved books still ship their metadata --------------------------
    # A book she has decided on leaves book_list/pending (it must not come back
    # as a pick) — but the Archive still needs it: read / loved / set-aside
    # rows, the stacks, and a reversal returning it to Home as open.
    resolved, res_seen = [], set()
    cur_issue = {'n': (order.index(cur_ym) + 1) if cur_ym in order else 0, 'label': ml, 'ym': cur_ym}
    for b in cur.get('books', []):
        if book_key(b.get('title'), b.get('author')) not in shelf_ex:
            continue
        rb = pick_book(b, None, ensure_cover(b.get('img'), b.get('title'), b.get('author'), covers_dir))
        if not rb.get('id') or rb['id'] in res_seen:
            continue
        res_seen.add(rb['id'])
        rb['issue'] = cur_issue
        resolved.append(rb)

    # ---- still on your list: unresolved books from EARLIER issues ----------
    # Every earlier issue's picks ship so the app can carry forward whatever she
    # never decided on. Resolution belongs to the app: it owns the reader state.
    # Newest issue first, one entry per book (a re-recommendation wins).
    pending, seen_pending = [], set()
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
                pb['issue'] = {'n': (order.index(ym) + 1) if ym in order else 0,
                               'label': mlp['label'], 'ym': ym}
                if pb['id'] not in res_seen:
                    res_seen.add(pb['id'])
                    resolved.append(pb)
                held_back += 1
                continue
            seen_pending.add(pb['id'])
            pb['issue'] = {'n': (order.index(ym) + 1) if ym in order else 0,
                           'label': mlp['label'], 'ym': ym}
            pending.append(pb)
    print('carried over: %d unresolved books from %d earlier issues (%d held back by your shelf)'
          % (len(pending), len(set(p['issue']['ym'] for p in pending)), held_back))

    added = added_data(covers_dir)
    if added:
        print('added books: %d shipped' % len(added))

    series = series_data(covers_dir)
    hero = hero_data(series)
    if hero:
        hero['cover'] = ensure_cover('', hero.get('title'), hero.get('author'), covers_dir)

    # ---- every rendered book carries a real synopsis (#51) -----------------
    # Her complaint: the one-line hooks are too thin to judge a book by. Each
    # book below gets its Goodreads blurb (Apple description as fallback), the
    # miss cached honestly. PRIORITY is the point: the picks she decides on
    # fill first, then the hero, then the volumes she can still pick up, then
    # the read ones — a cold cache fills across builds inside the politeness
    # budget (synopsis_budget_seconds), never blowing the boot rebuild's
    # timeout, and the report says exactly how far it got.
    syn_entries = [(b, b.get('title'), b.get('author')) for b in book_list]
    syn_entries += [(b, b.get('title'), b.get('author')) for b in pending]
    if hero:
        syn_entries.append((hero, hero.get('title'), hero.get('author')))
    syn_entries += [(b, b.get('title'), b.get('author')) for b in resolved]
    syn_entries += [(b, b.get('title'), b.get('author')) for b in added]
    vol_rank = {'out': 0, 'soon': 1, 'tba': 2, 'read': 3}
    vol_entries = [(b, b.get('t'), s.get('author') or '')
                   for s in series for b in (s.get('books') or [])]
    vol_entries.sort(key=lambda e: vol_rank.get(e[0].get('state'), 9))  # stable: series order holds
    syn_entries += vol_entries
    syn_cache = synopses.load()
    # OFFLINE: cached synopses only — a budget of 0 marks the rest pending
    syn_stats = synopses.attach(syn_entries, syn_cache, budget=0 if OFFLINE else None)
    if not synopses.save(syn_cache):
        print('synopsis cache: write failed — rebuilds will refetch')

    y, m = int(cur_ym[:4]), int(cur_ym[5:7])
    month = {
        'label': '%s %d' % (ml['name'].upper(), y),
        'short': '%s %d' % (MONTH_NAMES[m - 1], y),
        'drop': 'Dropped 1 %s %d' % (ml['name'], y),
        'count': len(book_list),
        'issue': len(order),
        'titles': WORDS.get(len(book_list), str(len(book_list))) + (' title' if len(book_list) == 1 else ' titles'),
    }
    _inames = [interests.name(i) for i in interests.active(INTS)]  # interests.json owns the order
    _ilabels = {interests.name(i): (i.get('label') or interests.name(i))
                for i in interests.active(INTS)}
    _lc = lane_counts(book_list, order=_inames)  # a zero-pick interest shows its honest zero
    month['shape'] = shape_str(_lc, order=_inames)   # the shape it shipped (ticket #6)
    month['shapeLine'] = shape_line(_lc, order=_inames, labels=_ilabels)
    month['light'] = len(book_list) < CFG['target_books'][0]  # under the floor -> light month

    for b in book_list:                      # this issue's own provenance
        b['issue'] = {'n': month['issue'], 'label': ml['label'], 'ym': cur_ym}

    copy_static()
    # mirror the volume cover cache into the served dist
    try:
        shutil.copytree(covers_dir, os.path.join(DIST, 'assets', 'covers'), dirs_exist_ok=True)
    except Exception as e:
        print('covers mirror: %s' % str(e)[:80])
    # identity guard: every book the app can mark must carry a canonical id
    orphans = [b['t'] for s in series for b in s['books'] if not b.get('id')]
    orphans += [b['title'] for b in book_list if not b.get('id')]
    if orphans:
        print('WARNING: %d books have no identity: %s' % (len(orphans), orphans[:5]))
    data = {'month': month, 'hero': hero, 'books': book_list, 'pending': pending,
            'series': series, 'seasons': SEASONS, 'criteria': criteria_line(), 'resolved': resolved,
            'added': added}
    write_dist('shelf-data.js', 'window.SHELF_DATA=' + json.dumps(data, ensure_ascii=False) + ';\n')

    tpl = open(os.path.join(DESIGN, 'app.html')).read()
    _tlabels = [i.get('label') or interests.name(i) for i in interests.active(INTS)]
    tpl = tpl.replace('__SHELF_TITLE__', 'The Shelf — %s%s' % (ml['label'],
                     ((' · ' + ' · '.join(_tlabels)) if _tlabels else '')))
    write_dist('index.html', tpl)
    print('built dist (current: %s, %d books, %d series, issue no. %d)'
          % (cur_ym, len(book_list), len(series), month['issue']))
    # last line on purpose: the server keeps the run log's tail, and the
    # synopsis counts are the one line a reader of the log must not lose
    print(synopses.report_line(syn_stats))
    return 0


if __name__ == '__main__':
    sys.exit(main())
