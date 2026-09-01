#!/usr/bin/env python3
"""The Shelf pipeline — stage 4: build dist/index.html from curated months.
One page = one month (the 1st-of-month drop for the PREVIOUS month's books).
Rolls up every month-*.json in data/ into the archive; the newest is current.
Pure stdlib; template stays unmodified."""
import json, os, re, shutil, sys, urllib.request, urllib.parse, hashlib, calendar, glob
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CFG = json.load(open(os.path.join(BASE, 'config.json')))
TEMPLATE = os.path.join(BASE, 'template.html')

MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']


def month_label(ym):
    """('2026-08', 31) -> {'name':'August','label':'August 2026','win':'1 AUG – 31 AUG 2026','key':'aug'}"""
    y, m = int(ym[:4]), int(ym[5:7])
    last = calendar.monthrange(y, m)[1]
    full = datetime.strptime(ym, '%Y-%m').strftime('%B')
    return {
        'key': MONTH_NAMES[m - 1].lower(),
        'name': full,
        'label': '%s %d' % (full, y),
        'win': '1 %s – %d %s %d' % (MONTH_NAMES[m - 1], last, MONTH_NAMES[m - 1], y),
    }


def baseline_seqs():
    """Always-present sequels baseline from data/sequels.json (her 52-series map).
    Released-and-unread -> to read (cap 12, newest first); announced/future -> radar (cap 8)."""
    reads, radar = [], []
    try:
        seq = json.load(open(os.path.join(ROOT, 'data', 'sequels.json')))
        today = datetime.now().strftime('%Y-%m-%d')
        for ser in seq.get('series', []):
            for nb in ser.get('next_books', []):
                raw = nb.get('title') or ''
                if not raw:
                    continue
                m = re.match(r'^(.*?)\s*\((#[^)]*)\)\s*$', raw)
                if m:
                    t, n = m.group(1).strip(), m.group(2)
                else:
                    t = raw.split(' (')[0].strip()
                    n = str(nb.get('volume') or nb.get('number') or '')
                dt = str(nb.get('release_date') or '')[:10]
                disp = dt.replace('-', ' ') if re.match(r'^\d{4}-\d{2}-\d{2}$', dt) else ''
                ev = {'s': ser.get('series') or '', 't': t, 'n': n,
                      'a': ser.get('author') or '', 'd': disp, 'p': ''}
                if dt and dt <= today:
                    reads.append(ev)
                else:
                    radar.append(ev)
        reads.sort(key=lambda x: -len(x['d']))
        radar.sort(key=lambda x: -len(x['d']))
        reads, radar = reads[:12], radar[:8]
    except Exception as e:
        print('baseline sequels: %s' % e)
    return reads, radar


def merge(base, extra):
    out = [dict(x) for x in base]
    seen = {x.get('t') for x in out}
    for x in extra:
        if x.get('t') and x.get('t') not in seen:
            out.append(x)
            seen.add(x.get('t'))
    return out


HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36'}


def slug(b):
    s = ('%s %s' % (b.get('title', 'x'), b.get('author', 'y'))).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:40]


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


def main():
    month_files = sorted(glob.glob(os.path.join(BASE, 'data', 'month-*.json')))
    if not month_files:
        print('no curated month — run curate.py first (or drop month-*.json in data/)')
        return 1

    books, ids_all, spine_h, spine_pal = {}, {}, {}, {}
    months, order = {}, []

    for mf in month_files:
        try:
            cur = json.load(open(mf))
        except Exception as e:
            print('skip %s: %s' % (mf, e))
            continue
        ym = os.path.basename(mf)[len('month-'):-len('.json')]
        if not re.match(r'^\d{4}-\d{2}$', ym):
            print('skip %s (bad name)' % mf)
            continue
        ml = month_label(ym)
        ids = []
        for i, b in enumerate(cur.get('books', [])):
            bid = b.get('id') or slug(b)
            img = download_cover(b, os.path.join(BASE, 'dist', 'assets', 'covers'))
            spice = int(b.get('spice', 3) or 3)
            books[bid] = {
                'title': b.get('title'), 'author': b.get('author'),
                'publisher': b.get('publisher') or '', 'spine': b.get('title', '')[:18],
                'date': b.get('date') or '', 'gr': (b.get('rating') or 0), 'genre': b.get('genre') or '',
                'hook': b.get('hook') or '', 'tropes': b.get('tropes') or [],
                'spice': spice, 'formats': b.get('formats') or ['ebook'],
                'img': img or 'assets/real/cover-01.jpg',
                'fit': 'fit score %d — %s' % (98 - i * 3, b.get('genre') or ''),
                'mmc': b.get('mmc') or {'score': 3, 'archetype': 'same energy, no magic'},
                'fresh': bool(b.get('fresh')), 'aseq': bool(b.get('aseq')), 'url': b.get('url') or '',
            }
            ids.append(bid)
            spine_h[bid] = 132 + (i % 5) * 7
            spine_pal[bid] = ['#E8C4C6', '#CBD6C0', '#C9D6E0', '#F0E3C4'][i % 4]

        target_min = int(CFG.get('target_books', [6, 8])[0])
        months[ml['key']] = {
            'name': ml['name'], 'label': ml['label'], 'current': False,
            'topPick': cur.get('top_pick') or (ids[0] if ids else None),
            'books': ids, 'presets': {}, 'win': ml['win'],
            'light': len(ids) < target_min,
        }
        order.append(ml['key'])

    order.reverse()
    months[order[0]]['current'] = True

    br, bd = baseline_seqs()
    seqsort = sorted(glob.glob(os.path.join(BASE, 'data', 'month-*.json')))
    cur_latest = json.load(open(month_files[-1])) if month_files else {}
    seqread = merge(cur_latest.get('sequels_read', []), br)
    seqradar = merge(cur_latest.get('sequels_radar', []), bd)

    data = {
        'CURRENT': order[0],
        'BOOKS': books,
        'MONTHS': months,
        'ORDER': order,
        'SPINE_H': spine_h,
        'SPINE_PAL': spine_pal,
        'SEQ_READ': seqread,
        'SEQ_RADAR': seqradar,
    }
    inject = '<script>window.THE_SHELF_DATA=' + json.dumps(data) + ';</script>\n'

    tpl = open(TEMPLATE).read()
    for old, new in [
        ("<script>\n(function(){", inject + "<script>\n(function(){"),
        ("  var BOOKS={", "  var BOOKS=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.BOOKS)||{"),
        ("  var MONTHS={", "  var MONTHS=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.MONTHS)||{"),
        ("  var ORDER=['sep','aug','jul','jun'];", "  var ORDER=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.ORDER)||['sep','aug','jul','jun'];"),
        ("  var SEQ_READ=[", "  var SEQ_READ=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.SEQ_READ)||["),
        ("  var SEQ_RADAR=[", "  var SEQ_RADAR=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.SEQ_RADAR)||["),
        ("  var SPINE_H={", "  var SPINE_H=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.SPINE_H)||{"),
        ("  var SPINE_PAL={", "  var SPINE_PAL=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.SPINE_PAL)||{"),
    ]:
        if old not in tpl:
            print('anchor not found: %s' % old)
            return 1
        tpl = tpl.replace(old, new, 1)

    os.makedirs(os.path.join(BASE, 'dist'), exist_ok=True)
    open(os.path.join(BASE, 'dist', 'index.html'), 'w').write(tpl)
    print('built dist/index.html (%d months, current: %s, %d books total)' % (len(months), order[0], len(books)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
