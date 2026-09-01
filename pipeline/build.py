#!/usr/bin/env python3
"""The Shelf pipeline — stage 4: build dist/index.html from the curated month.
Injects the month's data into the design template (the v4 page) and rewrites
local assets next to it. Pure stdlib; template stays unmodified."""
import json, os, re, shutil, sys, urllib.request, urllib.parse, hashlib
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
TEMPLATE = os.path.join(BASE, 'template.html')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36'}

def slug(b):
    s = ('%s %s' % (b.get('title', 'x'), b.get('author', 'y'))).lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:40]

def download_cover(b, covers_dir):
    img = b.get('img') or ''
    if not img or img.startswith('assets/'):
        return img
    try:
        req = urllib.request.Request(img, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
        if len(raw) < 1000: return ''
        name = slug(b) + '.jpg'
        open(os.path.join(covers_dir, name), 'wb').write(raw)
        return 'assets/covers/%s' % name
    except Exception as e:
        print('[cover] %s: %s' % (b.get('title', '?'), str(e)[:80]))
        return ''

def main():
    mon = datetime.now().strftime('%Y-%m')
    mp = os.path.join(BASE, CFG['output_dir'], 'month-%s.json' % mon)
    if not os.path.exists(mp):
        print('no curated month — run curate.py first (or drop month-*.json in data/)'); return 1
    cur = json.load(open(mp))
    if not os.path.exists(TEMPLATE):
        print('template.html missing — copy .lavish/the-shelf-v4.html -> pipeline/template.html'); return 1

    covers_dir = os.path.join(BASE, 'dist', 'assets', 'covers')
    os.makedirs(covers_dir, exist_ok=True)

    books, ids = {}, []
    for i, b in enumerate(cur.get('books', [])):
        bid = b.get('id') or slug(b)
        img = download_cover(b, covers_dir)
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

    tp = cur.get('top_pick') or (ids[0] if ids else None)
    name = datetime.now().strftime('%B')
    label = datetime.now().strftime('%B %Y')
    months = {'sep': {'name': name, 'label': label, 'current': True, 'topPick': tp, 'books': ids, 'presets': {}}}
    data = {
        'BOOKS': books,
        'MONTHS': months,
        'ORDER': ['sep'],
        'SPINE_H': {bid: 132 + (i % 5) * 7 for i, bid in enumerate(ids)},
        'SPINE_PAL': {bid: ['#E8C4C6', '#CBD6C0', '#C9D6E0', '#F0E3C4'][i % 4] for i, bid in enumerate(ids)},
        'SEQ_READ': cur.get('sequels_read', []),
        'SEQ_RADAR': cur.get('sequels_radar', []),
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
        ("  var SPINE_H=", "  var SPINE_H=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.SPINE_H)||"),
        ("  var SPINE_PAL=", "  var SPINE_PAL=(window.THE_SHELF_DATA&&window.THE_SHELF_DATA.SPINE_PAL)||"),
    ]:
        if new in tpl:
            print('[warn] already injected: %s' % old[:30])
        elif old not in tpl:
            print('[warn] anchor not found: %s' % old[:30])
        tpl = tpl.replace(old, new, 1)

    dist = os.path.join(BASE, 'dist')
    os.makedirs(dist, exist_ok=True)
    open(os.path.join(dist, 'index.html'), 'w').write(tpl)
    src_assets = os.path.join(BASE, os.pardir, '.lavish', 'assets')
    if os.path.isdir(src_assets) and not os.path.exists(os.path.join(dist, 'assets', 'real')):
        shutil.copytree(src_assets, os.path.join(dist, 'assets'), dirs_exist_ok=True)
    print('built dist/index.html (%d books, top pick: %s)' % (len(ids), tp))
    return 0

if __name__ == '__main__':
    sys.exit(main())
