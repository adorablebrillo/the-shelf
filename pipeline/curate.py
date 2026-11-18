#!/usr/bin/env python3
"""The Shelf pipeline — stage 3: OpenRouter curation, with the shape rule.

Calls an LLM (any model available via OpenRouter) with the taste profile and
the filtered candidates. Strict JSON in, curated month out.

The shape rule now follows the reader's interests (interests.json — the
Book-a-meter): picks split across the active interests by dial weight, every
active interest keeps a floor of two; an interest that cannot fill its floor
widens ITS OWN window 30 -> 60 -> 90 days before it is dropped (a best-ever
interest skips the window — any date, 4.0+ rated); gaps are filled from the
strongest leftovers across ALL interests; the month file records the shape
it shipped. Nothing is ever padded. With the default three romance interests
the rule is today's 3/3/3 shape rule, at her picked count.
"""
import json, os, sys, re, base64, urllib.request
import paths  # shared resolver: reader data lives on the volume (CFG_DIR)
import verdicts
import interests
from datetime import datetime, date, timedelta
from lanes import counts, shape_str, shape_line
from windows import target_month, window_end

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, 'config.json')))
INTS = interests.load()  # her interests — the run curates from these
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


def interest_names():
    """The run's interest names, in file order (the keys every count, window
    and report line uses)."""
    return interests.names(INTS)


def active_interests():
    """The interests a run searches and splits picks across."""
    return interests.active(INTS)


def interest_availability(cands, end, attempts):
    """Per interest, per widening window: how many candidates exist. Lets the
    retry loop skip pointless calls (an interest that cannot fill even at 90d
    is dropped honestly, not retried). A best-ever interest has no window —
    its availability is the same at every rung (any date counts)."""
    av = {}
    for i in active_interests():
        nm = interests.name(i)
        if interests.best_ever(i):
            av[nm] = {d: sum(1 for b in cands if interests.of(b, INTS) == nm)
                      for d in attempts}
        else:
            av[nm] = {d: sum(1 for b in cands
                             if interests.of(b, INTS) == nm
                             and (age_days(b.get('date'), end) is None
                                  or age_days(b.get('date'), end) <= d))
                      for d in attempts}
    return av


def _key(b):
    return ((b.get('title') or '').lower().strip(), (b.get('author') or '').lower().strip())


def gap_fill(picks, cands, hi, lane_days, end):
    """Fill remaining slots from the strongest leftovers across ALL interests
    — only books that earn it: inside their interest's window (the widening
    ladder bounds every fill; a best-ever interest has no window), rating
    >= 4.0, and indie/unknown publishers need the same proof the filter
    demands (a best-ever book's proof IS its 4.0+ rating, so those qualify).
    Never filler."""
    have = {_key(p) for p in picks}
    earn = CFG.get('trad_pub_score_rating', 4.0)
    leftovers = [c for c in cands if _key(c) not in have]
    leftovers.sort(key=lambda c: (c.get('rating') if isinstance(c.get('rating'), (int, float)) else 0,
                                  c.get('rating_count') or 0), reverse=True)
    out = []
    for c in leftovers:
        if len(picks) + len(out) >= hi:
            break
        nm = interests.of(c, INTS)
        if nm in lane_days:
            days = lane_days[nm]   # None here means one thing: a best-ever interest
        else:
            # a name the run does not know (a renamed default, a genre
            # fallback outside the file) is bounded by the first widening
            # rung — never any-date
            days = CFG.get('lane_widen_days', [30, 60, 90])[0]
        if days is not None:
            age = age_days(c.get('date'), end)
            if age is not None and age > days:
                continue  # outside its interest's window
        r = c.get('rating')
        if not (isinstance(r, (int, float)) and r >= earn):
            continue  # the earn-it bar
        if not (c.get('trad') or c.get('indie_proven') or c.get('best_ever_proven')):
            continue  # indie/unknown need proven ratings (the filter's rule)
        out.append(c)
    return out


def ensure_sequels(picks, cands, log=print):
    """#76: the sequel guarantee — a book continuing a series she is already in
    is a guaranteed pick. The filter marks `aseq`; this makes sure the model's
    judgment (or the cap, or a thin lane) never dropped one. Her rule: being a
    sequel overrides every criterion. Her own verdicts already ran in the
    filter, so a book she marked never returns."""
    import re as _re

    def _ntitle(b):
        # the review of #76: a model pick titled 'Threshing Day (The Empyrean
        # #4)' must not duplicate the candidate 'Threshing Day'
        return _re.sub(r'\s*\([^)]*\)', '', (b.get('title') or '').lower()).strip()

    have = {_key(p) for p in picks}
    seen_titles = {_ntitle(p) for p in picks}
    missing = [c for c in cands if c.get('aseq')
               and _key(c) not in have and _ntitle(c) not in seen_titles]
    for c in missing:
        c = dict(c)
        c['why'] = c.get('why') or 'your series — a guaranteed pick'
        picks.append(c)
        seen_titles.add(_ntitle(c))
    if missing:
        log('sequel guarantee: +%d never-droppable pick(s) (%s)'
            % (len(missing), ', '.join((c.get('title') or '')[:28] for c in missing[:4])))
    return picks


def copy_series(picks, cands):
    """The model's output schema has no series field, so a pick can come back
    without one. Copy series and series_num from the candidate record onto
    every pick (matched by book id, then by bare title), so the month file
    keeps the series a read or loved mark starts tracking. The same match
    copies the pick's interest (its lane field): a pick carries the interest
    of the search that found it, never a genre regex."""
    from bookids import book_key
    import re as _re

    def _ntitle(b):
        return _re.sub(r'\s*\([^)]*\)', '', (b.get('title') or '').lower()).strip()

    by_id, by_title = {}, {}
    for c in cands:
        by_id.setdefault(book_key(c.get('title'), c.get('author')), c)
        by_title.setdefault(_ntitle(c), c)
    for p in picks:
        c = by_id.get(book_key(p.get('title'), p.get('author'))) or by_title.get(_ntitle(p))
        if c is None:
            continue
        if (c.get('series') or '').strip():
            p['series'] = c['series']
            if c.get('series_num'):
                p['series_num'] = str(c['series_num'])
        if c.get('lane') and not p.get('lane'):
            p['lane'] = c['lane']
    return picks


# The taste prompt says M/F only, but a cheap model still picked an MM hockey
# romance on 2026-09-22 whose genre read "LGBTQIA+ Romance Books Romance". The
# deterministic screen in filter.py is the real gate; this block is a second
# wall so the model itself refuses too.
HARD_RULES = ('\n\nHard rules the engine also enforces — never break them: M/F only. '
              'Reject any book whose title, genre, or description indicates MM/FF/LGBTQ+ '
              'content (genre strings like "LGBTQIA+", "Lesbian", "Gay", "Sapphic"; title '
              'markers M/M, MM, F/F, WLW, MMF). Dark romance is welcome — especially dark '
              'academia: gothic settings, anti-heroes, morally gray love interests and '
              'bully romance are a plus, never a flag — dark, never cruel: abuse or '
              'humiliation played straight as romance is still out. No cowboy, cowgirl, '
              'rancher, ranch or western-setting romance — she is not into those '
              'characters. When unsure, leave the book out — a missing pick beats a '
              'wrong one.')

# #83: her verdicts teach the model. The request carries her_verdicts — books
# she loved, wants, and set aside as not for me, newest first. This paragraph
# lives in code (her deployed taste-prompt.md is never edited) and asks for an
# optional `because` the build keeps only when it names a loved or want book.
VERDICT_RULES = ('\n\nHer verdicts: the request carries her_verdicts — books she marked loved, '
                 'want (a mild yes) and not_for_me, newest first. Lean toward books like the ones '
                 'she loved and wanted (same interests, tropes, authors, energy) and away from books '
                 'like the ones she set aside. Never pick a book that is already in her_verdicts. '
                 'Each book may carry an optional "because" field: the exact title of ONE book from '
                 'her loved or want list that most steered this pick. Leave it out when no single '
                 'book did — never name a not_for_me book or a book outside those lists.')


def interests_block():
    """The Book-a-meter, built in code for every request — the interests,
    their dials, their pick targets and which of them the romance rules
    hold for. Her deployed taste-prompt.md is never edited; this block
    overrides its lane and shape wording."""
    act = active_interests()
    if not act:
        return '\n\nHer interests list is empty — pick nothing this month.'
    sp = interests.split(INTS)
    lines = ['\n\nHer interests (the Book-a-meter) — this block OVERRIDES any lane '
             'and shape wording earlier in the taste brief:']
    for i in act:
        nm = interests.name(i)
        label = i.get('label') or nm
        tgt = sp.get(nm, 0)
        mode = interests.mode(i)
        md = ('best-ever and new releases — any release date, when a book is '
              'strongly rated' if mode == 'both' else
              'best ever — any release date, when a book is strongly rated' if mode == 'best ever' else
              'new releases only')
        rules = ('the romance rules hold (M/F only, spice 3-5, dark welcome)'
                 if interests.romance(i) else
                 'the romance rules do NOT apply — real-life content is welcome')
        dial_w = {'curious': 'a mild yes', 'into it': 'a clear yes', 'obsessed': 'her favourite'}.get(
            interests.dial(i), 'a clear yes')
        lines.append('- %s (%s): %s; target %d of the %d picks; %s.'
                    % (label, dial_w, md, tgt, int(INTS.get('picks') or interests.DEFAULT_PICKS), rules))
    nv = interests.never(INTS)
    if nv:
        lines.append('She NEVER wants %s — in any interest; leave those out.' % ', '.join(nv))
    lines.append('Pick only books her interests ask for; when an interest '
                 'cannot reach its target honestly, pick fewer — never filler.')
    return '\n'.join(lines)


def suggest_terms(key, label):
    """A typed interest's search words: the curator call suggests 3 to 5 once,
    and interests.json keeps them. Returns a list (empty on failure — the
    caller falls back to searching the interest's own name)."""
    sysmsg = ('You suggest Apple Books search queries for the ebook store. Reply JSON '
              '{"queries": [...]} with 3 to 5 short queries, each 2 to 4 words, that find '
              'books about the topic. Plain topic words only — no author names, no '
              'bestseller list names, no quotes.')
    body = json.dumps({
        'model': CFG.get('model', 'openai/gpt-4o-mini'),
        'messages': [{'role': 'system', 'content': sysmsg},
                     {'role': 'user', 'content': 'The interest: "%s"' % label}],
        'temperature': 0.3,
        'response_format': {'type': 'json_object'},
    }).encode()
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                 'HTTP-Referer': 'https://the-shelf.local', 'X-Title': 'The Shelf'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        content = data['choices'][0]['message']['content']
        out = json.loads(re.search(r'\{[\s\S]*\}', content).group(0)) if not content.strip().startswith('{') else json.loads(content)
        qs = [str(q).strip() for q in (out.get('queries') or []) if str(q).strip()][:5]
        return qs if len(qs) >= 3 else []
    except Exception:
        return []


def call_model(key, payload, taste):
    """One curation call. Separated so tests can mock it deterministically."""
    body = json.dumps({
        'model': CFG.get('model', 'openai/gpt-4o-mini'),
        'messages': [
            {'role': 'system', 'content': taste + HARD_RULES + VERDICT_RULES + interests_block()},
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


def build_payload(mon, window_rule, lane_days, av, cands, seq, her_verdicts=None):
    """What the model reads: the month, the window, her interests with their
    targets and windows, and the candidates. `lane_days` (the field keeps its
    old name for continuity) is keyed by interest name; None = any date."""
    sp = interests.split(INTS)
    act = active_interests()
    labels = {interests.name(i): (i.get('label') or interests.name(i)) for i in act}
    ints = [{'name': nm, 'label': labels[nm],
             'dial': interests.dial(interests.by_name(INTS, nm) or {}),
             'mode': interests.mode(interests.by_name(INTS, nm) or {}),
             'target': sp.get(nm, 0),
             'romance': interests.romance(interests.by_name(INTS, nm) or {})}
            for nm in interest_names() if nm in labels]
    shape = shape_line(sp, order=list(labels), labels=labels)
    return json.dumps({
        'month': mon,
        'window_rule': window_rule,
        'shape_rule': ('target %s (%d books); every interest keeps a floor of %d; '
                       'fill any gap from the strongest leftovers across ALL interests; '
                       'never filler' % (shape, int(INTS.get('picks') or interests.DEFAULT_PICKS),
                                         CFG.get('lane_floor', 2))),
        'interests': ints,
        'interest_windows': {nm: ('any date' if lane_days.get(nm) is None else '%dd' % lane_days[nm])
                             for nm in labels},
        'interest_availability': {nm: av.get(nm) for nm in labels},
        'candidates': cands,
        'sequels_map': seq,
        'her_verdicts': her_verdicts or {k: [] for k in verdicts.CAPS},
    }, indent=1)


def curate(key, filtered, taste, seq, mon, window_rule, call=None, log=print, her_verdicts=None):
    """The widening loop + shape enforcement, across her interests. Returns
    the curated dict. `call` is the model seam (tests inject a deterministic
    fake)."""
    call = call or call_model
    cands = filtered.get('books', [])
    attempts = CFG.get('lane_widen_days', [30, 60, 90])
    floor = CFG.get('lane_floor', 2)
    hi = int(INTS.get('picks') or interests.DEFAULT_PICKS)
    end = window_end(MODE)
    inames = [interests.name(i) for i in active_interests()]
    labels = {interests.name(i): (i.get('label') or interests.name(i))
              for i in active_interests()}
    av = interest_availability(cands, end, attempts)
    # None = any date (a best-ever interest: the window rule skips it)
    lane_days = {nm: (None if interests.best_ever(interests.by_name(INTS, nm) or {}) else attempts[0])
                 for nm in inames}
    cur = None
    for i, d in enumerate(attempts):
        payload = build_payload(mon, window_rule, lane_days, av, cands, seq, her_verdicts)
        cur = call(key, payload, taste)
        if not cur or 'books' not in cur:
            log('CURATE output not valid JSON — try another model in config.json')
            return None
        # count by the interest of the search that found each book, not by
        # the genre fallback: copy candidate provenance onto the model's
        # picks before counting (copy_series is idempotent, so the copy
        # after the loop is unaffected). Without this, a mode-new typed
        # interest can never be seen to reach its floor and the run widens
        # 30 -> 60 -> 90, burning every curation call.
        copy_series(cur['books'], cands)
        c = counts(cur['books'], order=inames)
        deficient = [nm for nm in inames if c.get(nm, 0) < floor]
        log('shape attempt %d: %s (windows %s)' % (i + 1, shape_str(c, order=inames),
            ' '.join('%s=%s' % (nm, 'any date' if lane_days[nm] is None else '%dd' % lane_days[nm])
                     for nm in inames)))
        if not deficient:
            break
        widened = False
        for nm in deficient:
            if lane_days[nm] is None:
                continue  # best ever: any date already — nothing to widen into
            # find the first rung at or beyond the next one that can reach the
            # floor — an interest whose candidates sit at 80 days still widens to 90
            for nxt in attempts[i + 1:]:
                if av[nm][nxt] >= floor:
                    lane_days[nm] = nxt
                    widened = True
                    break
        if not widened:
            break
    # #83: a `because` survives only when it names a loved or want book
    picks = [verdicts.keep_because(b, her_verdicts or {}) for b in cur['books']]
    # the candidate's series and interest ride onto every model pick (gap
    # fills and guaranteed sequels are candidate records already)
    picks = copy_series(picks, cands)
    # no active interests: the request told the model to pick nothing — a
    # fill would be padding, and the never-pad rule holds over the cap
    fills = gap_fill(picks, cands, hi, lane_days, end) if inames else []
    if fills:
        log('gap fill: +%d from the strongest leftovers (%s)' %
            (len(fills), ', '.join(interests.of(f, INTS) for f in fills)))
        picks = picks + fills
    # #76: the sequel guarantee — a book in a series she is already in is a
    # pick no matter what the model or the cap decided
    picks = ensure_sequels(picks, cands, log)
    c = counts(picks, order=inames)
    dropped = [nm for nm in inames if c.get(nm, 0) < floor]
    if dropped:
        log('interest(s) below floor after widening + fill: %s' % ', '.join(dropped))
    cur['books'] = picks
    cur['lanes'] = c  # the month file keeps its old key: interest name -> picks
    cur['shape'] = shape_str(c, order=inames)
    cur['shape_line'] = shape_line(c, order=inames, labels=labels)
    cur['light'] = len(picks) < CFG['target_books'][0]
    cur['dropped_lanes'] = dropped
    cur['widen'] = {nm: lane_days[nm] for nm in inames
                    if lane_days[nm] is not None and lane_days[nm] > attempts[0]}
    # the report line the plan asks for: one line per interest — candidates,
    # picks, and a zero when there are none
    for i in INTS.get('interests') or []:
        nm = interests.name(i)
        cand_n = sum(1 for b in cands if interests.of(b, INTS) == nm)
        pick_n = c.get(nm, 0)
        log('[interest] %s: %d candidate(s) · %d pick(s)%s%s' %
            ((i.get('label') or nm), cand_n, pick_n,
             ' — ZERO' if pick_n == 0 else '',
             ' (off, not searched)' if interests.dial(i) == 'off' else ''))
    return cur


def main():
    # the run makes the interests file on a blank install (the Book-a-meter
    # the reader's answers fill — pieces 2 and 3 write it; the run reads it)
    global INTS
    INTS = interests.ensure()
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
    # #83: her verdicts, by name, for the model
    lists, missing = verdicts.her_verdicts(
        verdicts.load_marks(), verdicts.book_details(os.path.join(BASE, CFG['output_dir'])))
    print(verdicts.report_line(lists, missing))

    if MODE == 'adhoc':
        window_rule = ('released within the last 30 days — a rolling window ending today (%s). '
                       'This is an ad-hoc "curate now" run.' % datetime.now().strftime('%Y-%m-%d'))
    else:
        window_rule = ('only books released in the specific month being curated (the drop runs on the '
                       '1st for the entire PREVIOUS month)')

    try:
        cur = curate(key, filtered, taste, seq, mon, window_rule, her_verdicts=lists)
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
    lo = CFG['target_books'][0]
    hi = int(INTS.get('picks') or interests.DEFAULT_PICKS)  # her Book-a-meter answer: picks per issue
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
