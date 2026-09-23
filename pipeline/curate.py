#!/usr/bin/env python3
"""The Shelf pipeline — stage 3: OpenRouter curation, with the shape rule.

Calls an LLM (any model available via OpenRouter) with the taste profile and
the filtered candidates. Strict JSON in, curated month out.

The shape rule (settled in the v5 grilling): target 3/3/3 — nine books when
every lane has three qualifying; every lane keeps a floor of two; a lane that
cannot fill its floor widens ITS OWN window 30 -> 60 -> 90 days before it is
dropped; gaps are filled from the strongest leftovers across ALL lanes; the
month file records the shape it shipped. Nothing is ever padded.
"""
import json, os, sys, re, base64, urllib.request
import paths  # shared resolver: reader data lives on the volume (CFG_DIR)
from datetime import datetime, date, timedelta
from lanes import LANES, lane_of, counts, shape_str, shape_line
from windows import target_month, window_end

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
# SHELF_MODE=scheduled -> the 1st-of-month drop curates the PREVIOUS month
# SHELF_MODE=adhoc     -> "curate now": rolling last 30 days ending today
MODE = os.environ.get('SHELF_MODE', 'scheduled')


def api_key():
    k = os.environ.get('OPENROUTER_API_KEY')
    if k: return k
    for p in (os.path.expanduser('~/.config/the-shelf/openrouter.key'),
              os.path.join(BASE, '.openrouter.key')):
        if os.path.exists(p):
            return open(p).read().strip()
    return None


def age_days(d, end):
    """Days between a release date and the window end. None = unknown date
    (kept — the curator judges those, same as before)."""
    try:
        return (end - date.fromisoformat(str(d)[:10])).days
    except Exception:
        return None


def lane_availability(cands, end, attempts):
    """Per lane, per widening window: how many candidates exist. Lets the
    retry loop skip pointless calls (a lane that cannot fill even at 90d is
    dropped honestly, not retried)."""
    aged = [(b, age_days(b.get('date'), end)) for b in cands]
    av = {}
    for l in LANES:
        av[l] = {d: sum(1 for b, a in aged if lane_of(b) == l and (a is None or a <= d))
                 for d in attempts}
    return av


def _key(b):
    return ((b.get('title') or '').lower().strip(), (b.get('author') or '').lower().strip())


def gap_fill(picks, cands, hi, lane_days, end):
    """Fill remaining slots from the strongest leftovers across ALL lanes —
    only books that earn it: inside their lane's window (the widening ladder
    bounds every fill), rating >= 4.0, and indie/unknown publishers need the
    same proof the filter demands. Never filler."""
    have = {_key(p) for p in picks}
    earn = CFG.get('trad_pub_score_rating', 4.0)
    leftovers = [c for c in cands if _key(c) not in have]
    leftovers.sort(key=lambda c: (c.get('rating') if isinstance(c.get('rating'), (int, float)) else 0,
                                  c.get('rating_count') or 0), reverse=True)
    out = []
    for c in leftovers:
        if len(picks) + len(out) >= hi:
            break
        age = age_days(c.get('date'), end)
        if age is not None and age > lane_days[lane_of(c)]:
            continue  # outside its lane's window
        r = c.get('rating')
        if not (isinstance(r, (int, float)) and r >= earn):
            continue  # the earn-it bar
        if not (c.get('trad') or c.get('indie_proven')):
            continue  # indie/unknown need proven ratings (the filter's rule)
        out.append(c)
    return out


# The taste prompt says M/F only, but a cheap model still picked an MM hockey
# romance on 2026-09-22 whose genre read "LGBTQIA+ Romance Books Romance". The
# deterministic screen in filter.py is the real gate; this block is a second
# wall so the model itself refuses too.
HARD_RULES = ('\n\nHard rules the engine also enforces — never break them: M/F only. '
              'Reject any book whose title, genre, or description indicates MM/FF/LGBTQ+ '
              'content (genre strings like "LGBTQIA+", "Lesbian", "Gay", "Sapphic"; title '
              'markers M/M, MM, F/F, WLW, MMF). Dark romance is welcome — especially dark '
              'academia: gothic settings, anti-heroes, morally gray love interests and '
              'bully romance are a plus, never a flag. No cowboy, cowgirl, '
              'rancher, ranch or western-setting romance — she is not into those '
              'characters. When unsure, leave the book out — a missing pick beats a '
              'wrong one.')


def call_model(key, payload, taste):
    """One curation call. Separated so tests can mock it deterministically."""
    body = json.dumps({
        'model': CFG.get('model', 'openai/gpt-4o-mini'),
        'messages': [
            {'role': 'system', 'content': taste + HARD_RULES},
            {'role': 'user', 'content': "Here are this month's candidates JSON. Curate them:\n\n" + payload},
        ],
        'temperature': 0.6,
        'response_format': {'type': 'json_object'},
    }).encode()
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                 'HTTP-Referer': 'https://the-shelf.local', 'X-Title': 'The Shelf'})
    with urllib.request.urlopen(req, timeout=240) as r:
        data = json.loads(r.read().decode())
    content = data['choices'][0]['message']['content']
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r'\{[\s\S]*\}', content)
        return json.loads(m.group(0)) if m else None


def build_payload(mon, window_rule, lane_days, av, cands, seq):
    return json.dumps({
        'month': mon,
        'window_rule': window_rule,
        'shape_rule': ('target 3 sport romance / 3 romantasy / 3 contemporary romance '
                       '(nine books); every lane keeps a floor of 2; fill any gap from the '
                       'strongest leftovers across ALL lanes; never filler'),
        'lane_windows': lane_days,
        'lane_availability': av,
        'genre_mix': CFG.get('genre_mix', {}),
        'candidates': cands,
        'sequels_map': seq,
    }, indent=1)


def curate(key, filtered, taste, seq, mon, window_rule, call=None, log=print):
    """The widening loop + shape enforcement. Returns the curated dict.
    `call` is the model seam (tests inject a deterministic fake)."""
    call = call or call_model
    cands = filtered.get('books', [])
    attempts = CFG.get('lane_widen_days', [30, 60, 90])
    floor = CFG.get('lane_floor', 2)
    hi = CFG['target_books'][1]
    end = window_end(MODE)
    av = lane_availability(cands, end, attempts)
    lane_days = {l: attempts[0] for l in LANES}
    cur = None
    for i, d in enumerate(attempts):
        payload = build_payload(mon, window_rule, lane_days, av, cands, seq)
        cur = call(key, payload, taste)
        if not cur or 'books' not in cur:
            log('CURATE output not valid JSON — try another model in config.json')
            return None
        c = counts(cur['books'])
        deficient = [l for l in LANES if c[l] < floor]
        log('shape attempt %d: %s (windows %s)' % (i + 1, shape_str(c),
            ' '.join('%s=%dd' % (l, lane_days[l]) for l in LANES)))
        if not deficient:
            break
        widened = False
        for l in deficient:
            # find the first rung at or beyond the next one that can reach the
            # floor — a lane whose candidates sit at 80 days still widens to 90
            for nxt in attempts[i + 1:]:
                if av[l][nxt] >= floor:
                    lane_days[l] = nxt
                    widened = True
                    break
        if not widened:
            break
    picks = cur['books']
    fills = gap_fill(picks, cands, hi, lane_days, end)
    if fills:
        log('gap fill: +%d from the strongest leftovers (%s)' %
            (len(fills), ', '.join(lane_of(f) for f in fills)))
        picks = picks + fills
    c = counts(picks)
    dropped = [l for l in LANES if c[l] < floor]
    if dropped:
        log('lane(s) below floor after widening + fill: %s' % ', '.join(dropped))
    cur['books'] = picks
    cur['lanes'] = c
    cur['shape'] = shape_str(c)
    cur['shape_line'] = shape_line(c)
    cur['light'] = len(picks) < CFG['target_books'][0]
    cur['dropped_lanes'] = dropped
    cur['widen'] = {l: lane_days[l] for l in LANES if lane_days[l] > attempts[0]}
    return cur


def main():
    key = api_key()
    if not key:
        print('NO OPENROUTER API KEY — set OPENROUTER_API_KEY env var or put it in ~/.config/the-shelf/openrouter.key')
        return 2
    # target month by mode: adhoc = now (rolling 30 days) · scheduled = previous month
    import glob
    mon = target_month(MODE)
    fp = os.path.join(BASE, CFG['output_dir'], 'filtered-%s.json' % mon)
    if not os.path.exists(fp):
        files = sorted(glob.glob(os.path.join(BASE, CFG['output_dir'], 'filtered-*.json')))
        if not files:
            print('no filtered candidates — run fetch.py + filter.py first'); return 1
        mon = os.path.basename(files[-1])[len('filtered-'):-len('.json')]
        fp = files[-1]
    filtered = json.load(open(fp))
    taste_path, taste_src = paths.personal('taste-prompt.md')
    taste = open(taste_path).read()
    seq_path, seq_src = paths.personal('sequels.json')
    print('data: taste-prompt.md <- %s · sequels.json <- %s' % (taste_src, seq_src))
    seq = {}
    if os.path.exists(seq_path):
        seq = json.load(open(seq_path))

    if MODE == 'adhoc':
        window_rule = ('released within the last 30 days — a rolling window ending today (%s). '
                       'This is an ad-hoc "curate now" run.' % datetime.now().strftime('%Y-%m-%d'))
    else:
        window_rule = ('only books released in the specific month being curated (the drop runs on the '
                       '1st for the entire PREVIOUS month)')

    try:
        cur = curate(key, filtered, taste, seq, mon, window_rule)
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', 'replace')[:600]
        open(os.path.join(BASE, CFG['output_dir'], 'curate-%s.error.json' % mon), 'w').write(json.dumps({'code': e.code, 'body': err}, indent=1))
        print('CURATE HTTP %s — see error file. %s' % (e.code, err[:180]))
        return 2
    except Exception as e:
        print('CURATE failed: %s' % str(e)[:180])
        return 2
    if cur is None:
        return 2
    n = len(cur['books'])
    lo, hi = CFG['target_books']
    if n == 0:
        print('CURATE returned 0 books — refusing to overwrite the existing month file (keeping the good shelf)')
        return 3
    if not (lo <= n <= hi):
        print('WARNING: %d books (expected %d–%d) — check the prompt/model' % (n, lo, hi))
    out = os.path.join(BASE, CFG['output_dir'], 'month-%s.json' % mon)
    cur['mode'] = MODE
    if MODE == 'adhoc':
        cur['window'] = {'from': (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
                         'to': datetime.now().strftime('%Y-%m-%d')}
    else:
        cur['window'] = {'month': mon}
    json.dump(cur, open(out, 'w'), indent=1)
    extra = ' · light month' if cur['light'] else ''
    print('curated (%s): %d books, shape %s%s, top pick "%s" -> %s'
          % (MODE, n, cur['shape'], extra, cur.get('top_pick', '?'), out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
