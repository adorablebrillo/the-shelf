#!/usr/bin/env python3
"""The Shelf pipeline — stage 2: apply the reader's hard rules to candidates."""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))

NO_DARK = ('dark', 'academy', 'bully', 'anti-hero', 'morally gray')
NO_QUEER = ('mm romance', 'male/male', 'mlm', 'gay romance', 'ff romance', 'female/female', 'wlw', 'queer', 'nonbinary')
TRAD_HINTS = ('avon', 'berkley', 'dell', 'forever', 'kensington', "st. martin's", 'penguin',
              'random house', 'little brown', 'tor', 'orbit', 'bloom books', 'quercus',
              'harlequin', 'mira', 'cornerstone', 'simon & schuster', 'hachette', 'pan macmillan')
INDIE_HINTS = ('t. howard', 'montlake', 'amazon publishing', 'smashwords', 'kdp', 'self-pub')

def is_trad(pub):
    p = (pub or '').lower()
    return any(h in p for h in TRAD_HINTS)

def is_indie(pub):
    p = (pub or '').lower()
    return any(h in p for h in INDIE_HINTS) or (not is_trad(p) and p != '')

def in_window(d, mon):
    if not d: return True  # unknown date -> keep for LLM to judge
    try:
        y, m = map(int, d[:7].split('-'))
        cur_y, cur_m = map(int, mon.split('-'))
        for i in range(0, CFG['window_months']):
            yy, mm = cur_y, cur_m - i
            while mm <= 0: mm += 12; yy -= 1
            if (y, m) == (yy, mm): return True
        return False
    except Exception:
        return True

def main():
    mon = datetime.now().strftime('%Y-%m')
    src_path = os.path.join(BASE, CFG['output_dir'], 'candidates-%s.json' % mon)
    if not os.path.exists(src_path):
        print('no candidates file — run fetch.py first'); return 1
    cands = json.load(open(src_path)).get('books', [])
    kept = []
    for b in cands:
        title = (b.get('title') or '').lower()
        genre = (b.get('genre') or '').lower()
        if any(k in genre for k in NO_QUEER): continue
        if any(k in title for k in NO_QUEER): continue
        # dark-romance signal: let the LLM make the final call, but tag it
        b['dark_flag'] = any(k in title or k in genre for k in NO_DARK)
        if not in_window(b.get('date'), mon): continue
        pub = b.get('publisher') or ''
        trad = is_trad(pub); indie = is_indie(pub)
        r = b.get('ratings')
        ok_ratings = isinstance(r, (int, float)) and r >= CFG['trad_pub_score_rating']
        b['trad'] = trad
        b['indie'] = indie and not trad
        b['indie_proven'] = bool(indie and ok_ratings)
        kept.append(b)
    kept = kept[:CFG['max_candidates']]
    out = os.path.join(BASE, CFG['output_dir'], 'filtered-%s.json' % mon)
    json.dump({'month': mon, 'books': kept, 'rules': {
        'mf_only': True, 'no_dark': True, 'spice_min': CFG['spice_min'],
        'trad_first_indie_with_proof': True}}, open(out, 'w'), indent=1)
    print('filtered: %d / %d -> %s' % (len(kept), len(cands), out))
    return 0

if __name__ == '__main__':
    sys.exit(main())
