#!/usr/bin/env python3
"""The Shelf — the reader's interests (the Book-a-meter), read by every run.

One list of interests replaces the three fixed romance lanes. It lives in
interests.json on the config volume (CFG_DIR, /config on Unraid): the
interests, the never list, picks per issue and the season goal. The public
repo ships blank — when the file is missing, the run makes it from
config.json lane_terms: the three romance interests, each "into it", mode new
(the shelf every install starts with, per the accepted Book-a-meter plan).

An interest is one kind of book the reader wants: a story genre or a
real-life topic. It has an id, a label (its name, as the reader sees it), a
kind (story or topic), a dial (off, curious, into it, obsessed), a mode
(new, best ever, both) and its own rules — `romance: true` marks the
interests the romance rules (M/F only, no cowboys, spice, dark welcome)
apply to. A book's interest comes from the search that found it; the genre
regex in lanes.py is only the fallback for a book with no search provenance.

Search words: a catalog interest (one of the story genres config.json
`lane_terms` knows) takes its words from that table; a typed interest gets
3-5 words suggested by the curator call once, and the file keeps them.

A topic interest may keep the baby's birth month and year (`birth`,
"YYYY-MM", never a day); the run works out the age in whole months and names
the stage it curates for (STAGES), so the picks follow the baby's age.
"""
import json, os, re
from datetime import date
import lanes  # the genre fallback for books with no search provenance
import paths

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))

# the reader's answers to the Book-a-meter plan (THS-37): the name, 12 picks
# and the never list are hers, not derivable from lane_terms
DEFAULT_NAME = 'Book-a-meter'
DEFAULT_PICKS = 12
DEFAULT_NEVER = ['cowboys']

# the three romance interests every install starts with, in the order the
# shape line shows them. Labels are the lane_terms keys as the reader names
# them; search words come from lane_terms (the catalog table in code).
DEFAULT_INTERESTS = (
    {'id': 'sport', 'label': 'Sport romance'},
    {'id': 'romantasy', 'label': 'Romantasy'},
    {'id': 'contemp', 'label': 'Contemporary romance'},
)

DIAL_WEIGHT = {'off': 0, 'curious': 1, 'into it': 2, 'obsessed': 3}
DEFAULT_DIAL = 'into it'
DEFAULT_MODE = 'new'

# The baby's stages, from the reader's answers to the Book-a-meter plan
# (THS-37 piece 4): five stages, in whole months, with the themes the plan
# showed her. A topic interest older than the last stage gets no stage.
STAGES = (
    ((0, 3), '0–3 months', 'newborn sleep, feeding, crying'),
    ((4, 6), '4–6 months', 'sleep regressions, first solids, rolling'),
    ((7, 12), '7–12 months', 'crawling, first words, separation'),
    ((13, 24), '13–24 months', 'toddler talk, tantrums, walking'),
    ((25, 36), '25–36 months', 'potty learning, play, preschool'),
)


def _norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def defaults():
    """The file a blank install starts from, built from config.json
    lane_terms: the three romance interests, each "into it", mode new."""
    ints = []
    seen = set()
    for d in DEFAULT_INTERESTS:
        if d['label'].lower() in (CFG.get('lane_terms') or {}):
            ints.append({'id': d['id'], 'label': d['label'], 'kind': 'story',
                         'dial': DEFAULT_DIAL, 'mode': DEFAULT_MODE, 'romance': True})
            seen.add(_norm(d['label']))
    # a lane_terms key the default table does not name still becomes an
    # interest (id from its first word) so an edited config never loses a lane
    for lane in (CFG.get('lane_terms') or {}):
        if _norm(lane) not in seen:
            ints.append({'id': (_norm(lane) or 'lane').split()[0], 'label': lane,
                         'kind': 'story', 'dial': DEFAULT_DIAL, 'mode': DEFAULT_MODE,
                         'romance': True})
    return {'v': 1, 'name': DEFAULT_NAME, 'picks': DEFAULT_PICKS,
            'never': list(DEFAULT_NEVER), 'season_goal': None, 'interests': ints}


def vol_path():
    """Where the run writes the file: the config volume (CFG_DIR — /config on
    Unraid, the local container/config in dev). The repo ships blank."""
    return os.path.join(paths.cfg_dir(), 'interests.json')


def path():
    return paths.personal('interests.json')


def load():
    """The interests doc: the volume file when it exists, the defaults when
    it does not (the run writes them with ensure()). A corrupt file raises —
    the reader must not get silent default picks over her own list."""
    p, src = path()
    if src != 'missing':
        try:
            doc = json.load(open(p))
        except Exception as e:
            raise ValueError('interests.json unreadable (%s): %s' % (p, str(e)[:120]))
        if not isinstance(doc, dict) or not isinstance(doc.get('interests'), list):
            raise ValueError('interests.json has no interests list: %s' % p)
        return doc
    return defaults()


def ensure(log=print):
    """Load, and when the file is missing, make it: the run's first act on a
    blank install. Returns the doc."""
    doc = load()
    p, src = path()
    if src == 'missing':
        try:
            os.makedirs(os.path.dirname(vol_path()), exist_ok=True)
            with open(vol_path(), 'w') as f:
                json.dump(doc, f, indent=1)
            log('interests: no interests.json — made the default one (%s) from config lane_terms' % vol_path())
        except Exception as e:
            log('interests: could not write the default file (%s): %s' % (vol_path(), str(e)[:80]))
    return doc


def save(doc, log=print):
    """Write the doc back to the volume (typed interests keep their suggested
    search words this way)."""
    p = vol_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
            json.dump(doc, f, indent=1)
        return True
    except Exception as e:
        log('interests: could not save (%s): %s' % (p, str(e)[:80]))
        return False


def name(i):
    """The run's key for an interest: its label, lowercased. The defaults'
    names are today's lane names, so month files and reports stay readable."""
    return (i.get('label') or i.get('id') or '').lower()


def names(doc):
    return [name(i) for i in doc.get('interests') or []]


def dial(i):
    return i.get('dial') or DEFAULT_DIAL


def weight(i):
    return DIAL_WEIGHT.get(dial(i), DIAL_WEIGHT[DEFAULT_DIAL])


def mode(i):
    return i.get('mode') or DEFAULT_MODE


def best_ever(i):
    """mode best ever (or both): books of any date, the window rule skips
    this interest, and its books need a 4.0+ rating as their quality proof."""
    return mode(i) in ('best ever', 'both')


def active(doc):
    """Interests with the dial not off — the ones a run searches and splits
    picks across."""
    return [i for i in doc.get('interests') or [] if dial(i) != 'off']


def romance(i):
    """The romance rules (M/F only, no cowboys, spice, dark welcome) apply to
    this interest? Stored on the interest; a file written before the flag
    existed falls back to the catalog: a lane_terms name is a romance lane."""
    if 'romance' in i:
        return bool(i['romance'])
    return _norm(name(i)) in {_norm(l) for l in (CFG.get('lane_terms') or {})}


def birth(i):
    """The baby's birth month and year, as (year, month), or None. Only
    "YYYY-MM" is read: the plan keeps the month and year, never a day."""
    m = re.match(r'^\s*(\d{4})-(\d{1,2})', str(i.get('birth') or ''))
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    return (y, mo) if 1 <= mo <= 12 else None


def months_old(i, today=None):
    """Whole months since the birth month, counted by calendar month — a
    month and a year are all the file keeps. None without a birth."""
    b = birth(i)
    if not b:
        return None
    t = today or date.today()
    return (t.year - b[0]) * 12 + (t.month - b[1])


def stage(i, today=None):
    """The stage this topic interest curates for, as {months, name, themes},
    or None: a story interest never has one, nor does a topic with no birth,
    a birth still to come, or a child past the plan's fifth stage."""
    if (i.get('kind') or '').lower() != 'topic':
        return None
    n = months_old(i, today)
    if n is None or n < 0:
        return None
    for (lo, hi), label, themes in STAGES:
        if lo <= n <= hi:
            return {'months': n, 'name': label, 'themes': themes}
    return None


def catalog_terms(i):
    """A catalog interest's search words: the lane_terms table in code (one
    definition, shared with the lanes it replaces)."""
    return list((CFG.get('lane_terms') or {}).get(name(i)) or [])


def terms(i):
    """This interest's search words: its own (kept in the file), else the
    catalog table's. Empty means the run must ask the curator for words."""
    t = i.get('terms') or []
    return list(t) if t else catalog_terms(i)


def split(doc):
    """Picks per interest: dial weight (curious 1, into it 2, obsessed 3),
    every active interest at least 1, rounding by largest remainder, a tie to
    the interest listed first. Returns {name: target}."""
    act = active(doc)
    n = int(doc.get('picks') or DEFAULT_PICKS)
    out = {name(a): 0 for a in act}
    if not act or n <= 0:
        return out
    if len(act) >= n:
        # more (or exactly as many) interests than picks: one each to the
        # strongest dials first, file order breaking ties
        order = sorted(range(len(act)), key=lambda k: (-weight(act[k]), k))
        for k in order[:n]:
            out[name(act[k])] = 1
        return out
    total = sum(weight(a) for a in act)
    shares = {name(a): n * weight(a) for a in act}
    for a in act:
        out[name(a)] = shares[name(a)] // total
    left = n - sum(out.values())
    if left > 0:
        # largest remainder first; sorted() is stable, so equal remainders
        # go to the interest listed first
        order = sorted(act, key=lambda a: -(shares[name(a)] % total))
        for a in order[:left]:
            out[name(a)] += 1
    # the floor: every active interest gets at least 1, taken from the
    # richest interest (the last listed among equals)
    idx = {name(a): k for k, a in enumerate(act)}
    for a in [x for x in act if out[name(x)] < 1]:
        while out[name(a)] < 1:
            donor = max(act, key=lambda d: (out[name(d)], -idx[name(d)]))
            if out[name(donor)] <= 1:
                break  # nothing to give — n is below the interest count after all
            out[name(donor)] -= 1
            out[name(a)] += 1
    return out


def never(doc):
    """Words the reader never wants, applied to every interest."""
    return [str(w).lower() for w in doc.get('never') or [] if str(w).strip()]


def for_book(b, doc):
    """A book's interest name: the search that found it (its lane field,
    set by fetch), else an interest its genre names, else None (the caller
    falls back to the lanes.py genre mapping)."""
    ln = (b.get('lane') or '').lower()
    if ln and ln in set(names(doc)):
        return ln
    g = _norm(b.get('genre'))
    if len(g) >= 5:
        for i in doc.get('interests') or []:
            nm = _norm(name(i))
            if len(nm) >= 5 and (nm in g or g in nm):
                return name(i)
    return None


def of(b, doc):
    """A book's interest name, never empty: the search that found it, else a
    genre match against the interests, else the genre fallback in lanes.py
    (one of the three default catalog names)."""
    return for_book(b, doc) or lanes.interest_of(b)


def by_name(doc, nm):
    """The interest object with this name, or None."""
    for i in doc.get('interests') or []:
        if name(i) == (nm or '').lower():
            return i
    return None
