#!/usr/bin/env python3
"""The Shelf pipeline — stage 2: apply the reader's hard rules to candidates."""
import json, os, re, sys
from datetime import datetime, date, timedelta

# SHELF_MODE=scheduled -> the 1st-of-month drop curates the PREVIOUS month
# SHELF_MODE=adhoc     -> "curate now": a rolling window of the last 30 days
MODE = os.environ.get('SHELF_MODE', 'scheduled')

from shelf_state import exclusion_set, exclude_by_shelf

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))


from windows import target_month, window_end  # one definition, shared with curate


def adhoc_window_ok(d):
    """Ad-hoc runs accept anything released within the last 30 days (rolling)."""
    if not d:
        return True  # unknown date -> let the LLM judge
    try:
        day = date.fromisoformat(str(d)[:10])
    except Exception:
        return True
    today = date.today()
    return (today - timedelta(days=30)) <= day <= today

# her rule (reversed 2026-09-23): dark romance is WANTED — especially dark
# academia. These signals tag a candidate as a wanted flavour (a hint the
# curator favours), never an exclusion.
DARK_HINTS = ('dark', 'academia', 'gothic', 'anti-hero', 'antihero', 'morally gray', 'morally grey', 'bully')


def dark_hint(title, genre, *extra):
    """True when a candidate carries a dark-romance signal (wanted, not screened).
    The fetch's candidate set carries no blurb, so title/genre (plus the series
    name) are the only text we can read — extra strings are accepted so a future
    description field joins the hint without another signature change."""
    hay = ' '.join(str(x or '') for x in (title, genre) + extra).lower()
    return any(k in hay for k in DARK_HINTS)
# her rule: no cowboy/cowgirl/western characters, any variant (2026-09-22).
# A hard drop — like the M/F screen, this is deterministic; the model gets a
# HARD_RULES reminder in curate.py but is never the gate.
NO_COWBOY = ('cowboy', 'cowgirl', 'ranch', 'rodeo', 'wrangler', 'buckaroo',
             'cattleman', 'western')


def cowboy_screen(title, genre):
    """True = excluded: cowboy/cowgirl/western character romance (her rule)."""
    title, genre = (title or '').lower(), (genre or '').lower()
    return any(k in title for k in NO_COWBOY) or any(k in genre for k in NO_COWBOY)


NO_QUEER = ('mm romance', 'male/male', 'mlm', 'gay romance', 'ff romance', 'female/female',
            'wlw', 'queer', 'nonbinary', 'non-binary', 'enby', 'lgbt', 'lesbian', 'sapphic',
            'achillean', 'boys love', 'gay fiction', 'transgender', 'trans romance',
            'two-spirit')
# standalone pairing markers the substring list misses ("MM Hockey Romance",
# "M/M", "m x m") — a real run let three MM titles through on 2026-09-21, and
# a live pick slipped in via the genre string "LGBTQIA+ Romance Books Romance"
# (2026-09-22) because no marker covered the LGBTQ spellings. Word boundaries
# keep "ff" out of "Office" and "gay" out of "Gaylord".
NO_QUEER_WORDS = (r'\bmm\b', r'\bm/m\b', r'\bm\s*x\s*m\b', r'\bff\b', r'\bf/f\b',
                  r'\bmmf\b', r'\bmfm\b', r'\bffm\b', r'\bgay\b', r'\bgl\b')
# Trad-pub detection now runs against the REAL publisher (fetch resolves it from
# each book's Apple page; the old code compared the author name to itself and
# never fired). Substring hints are safe; short hints need word boundaries
# ('tor' hides inside 'Editora', 'mira' inside 'Miraculous').
TRAD_HINTS = ('avon', 'berkley', 'grand central', "st. martin", 'random house', 'little brown',
              'bloom books', 'quercus', 'harlequin', 'cornerstone', 'simon & schuster', 'hachette',
              'pan macmillan', 'red tower', 'entangled', 'piatkus', 'headline', 'hodder', 'orion',
              'sourcebooks', 'celadon', 'putnam', 'dutton', 'bantam', 'bookouture', 'michael joseph',
              'flatiron', 'gallery books', 'atria', 'forever', 'sphere', 'orbit',
              # #47: imprints the Goodreads reference surfaced as 'unknown' —
              # all genuine big-5 houses, so the curator's gate must see them
              'penguin', 'crown', 'william morrow', 'knopf', 'doubleday', 'park row',
              'harper', 'macmillan')
TRAD_WORDS = ('tor', 'dell', 'mira')
INDIE_HINTS = ('montlake', 'amazon publishing', 'kdp', 'smashwords', 't. howard',
               'independently published', 'draft2digital')


def pub_class(pub):
    """trad | indie | unknown — three states, because 'no publisher resolved'
    must never masquerade as indie."""
    p = (pub or '').lower().strip()
    if not p:
        return 'unknown'
    if any(h in p for h in TRAD_HINTS):
        return 'trad'
    for w in TRAD_WORDS:
        if re.search(r'\b' + re.escape(w) + r'\b', p):
            return 'trad'
    if any(h in p for h in INDIE_HINTS):
        return 'indie'
    return 'unknown'

def pool_ok(d, mon):
    """The pool curate can draw from: the window's end back pool_back_days.
    Curate widens thin lanes 30 -> 60 -> 90 days; a stage that hard-windows
    here leaves curate nothing to widen into."""
    if not d: return True  # unknown date -> let the LLM judge
    try:
        day = date.fromisoformat(str(d)[:10])
    except Exception:
        return True
    end = window_end(MODE, mon)
    return (end - timedelta(days=CFG.get('pool_back_days', 120))) <= day <= end


def queer_screen(title, genre):
    """True = excluded by the M/F-only rule (substring list + word markers).
    Lowercases itself — the call site does too, but the screen must not depend
    on that (a direct call with an Apple genre string like 'LGBTQIA+ ...'
    missed the whole list once)."""
    title, genre = (title or '').lower(), (genre or '').lower()
    if any(k in genre for k in NO_QUEER): return True
    if any(k in title for k in NO_QUEER): return True
    return any(re.search(w, title, re.I) or re.search(w, genre, re.I) for w in NO_QUEER_WORDS)


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
    import glob
    # resolve the target month from the mode (leftover files can't shift it)
    mon = target_month(MODE)
    src_path = os.path.join(BASE, CFG['output_dir'], 'candidates-%s.json' % mon)
    if not os.path.exists(src_path):
        files = sorted(glob.glob(os.path.join(BASE, CFG['output_dir'], 'candidates-*.json')))
        if not files:
            print('no candidates file — run fetch.py first'); return 1
        mon = os.path.basename(files[-1])[len('candidates-'):-len('.json')]
        src_path = files[-1]
    cands = json.load(open(src_path)).get('books', [])
    kept = []
    dropped_cowboy = []
    for b in cands:
        title = (b.get('title') or '').lower()
        genre = (b.get('genre') or '').lower()
        if queer_screen(title, genre): continue
        if cowboy_screen(title, genre):
            dropped_cowboy.append(b.get('title') or '')
            continue
        # dark-romance hint: wanted, especially dark academia — the curator
        # favours these; it is never a screen
        b['dark_hint'] = dark_hint(title, genre, b.get('series'))
        # keep the whole widening pool; in_window tags the base window
        if MODE == 'adhoc':
            b['in_window'] = adhoc_window_ok(b.get('date'))
        else:
            b['in_window'] = in_window(b.get('date'), mon)
        if not pool_ok(b.get('date'), mon): continue
        pub = b.get('publisher') or ''
        cls = pub_class(pub)
        r = b.get('rating')
        rc = b.get('rating_count') or 0
        proven = isinstance(r, (int, float)) and r >= CFG['trad_pub_score_rating'] \
            and rc >= CFG.get('trad_pub_score_count', 100)
        b['trad'] = (cls == 'trad')
        b['indie'] = (cls == 'indie')
        b['pub_known'] = bool(pub)
        # #47: a Kindle-first book (sourced from its Goodreads page, no Apple
        # presence, publisher not on record) with strong ratings is the
        # indie-with-proof case — the Goodreads numbers carry it
        b['indie_proven'] = bool(proven and (cls == 'indie' or
                                             (cls == 'unknown' and b.get('pub_source') == 'goodreads-page')))
        kept.append(b)
    if dropped_cowboy:
        print('cowboy/western: dropped %d candidate(s) — %s'
              % (len(dropped_cowboy), ', '.join(dropped_cowboy[:4])))
    # your shelf steers the engine (ticket #7): resolved books never return
    kept, shelf_counts = exclude_by_shelf(kept, exclusion_set())
    print('shelf: excluded %d candidate(s) — %d not for me · %d already read'
          % (shelf_counts['total'], shelf_counts['not_for_me'], shelf_counts['read']))
    # newest first — the curator reads top-down
    kept.sort(key=lambda b: (b.get('date') or '0000-00-00'), reverse=True)
    total = len(kept)
    cap = CFG['max_candidates']
    if total > cap:
        # keep every lane fairly represented: round-robin across lanes instead of
        # truncating in insertion order (a late search lane used to lose wholesale)
        buckets = {}
        for b in kept:
            buckets.setdefault(b.get('lane') or 'unknown', []).append(b)
        picked = []
        while len(picked) < cap and any(buckets.values()):
            for lane in list(buckets):
                if buckets[lane] and len(picked) < cap:
                    picked.append(buckets[lane].pop(0))
        dropped = {lane: len(v) for lane, v in buckets.items() if v}
        print('cap: kept %d of %d — dropped per lane: %s (round-robin, never insertion order)'
              % (len(picked), total, dropped))
        kept = picked
    else:
        print('cap: kept %d of %d — under the %d cap, nothing dropped' % (total, total, cap))
    out = os.path.join(BASE, CFG['output_dir'], 'filtered-%s.json' % mon)
    json.dump({'month': mon, 'mode': MODE, 'books': kept,
               'shelf_excluded': shelf_counts,
               'cap': {'pool': total, 'kept': len(kept), 'max': cap},
               'rules': {
                   'mf_only': True, 'dark_romance_welcome': True, 'no_cowboy': True,
                   'spice_min': CFG['spice_min'],
                   'trad_first_indie_with_proof': True,
                   'pool_back_days': CFG.get('pool_back_days', 120)}}, open(out, 'w'), indent=1)
    nwin = sum(1 for b in kept if b.get('in_window'))
    print('filtered: %d / %d -> %s (%s; %d in-window + %d widened-pool, pool %dd)'
          % (len(kept), len(cands), out, MODE, nwin, len(kept) - nwin,
             CFG.get('pool_back_days', 120)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
