#!/usr/bin/env python3
"""The Shelf pipeline — stage 3: OpenRouter curation.
Calls an LLM (any model available via OpenRouter) with the taste profile and
the filtered candidates. Strict JSON in, curated month out. No Hermes, no
other dependencies — just an API key."""
import json, os, sys, base64, urllib.request
from datetime import datetime, timedelta

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

def main():
    key = api_key()
    if not key:
        print('NO OPENROUTER API KEY — set OPENROUTER_API_KEY env var or put it in ~/.config/the-shelf/openrouter.key')
        return 2
    # target month by mode: adhoc = now (rolling 30 days) · scheduled = previous month
    import glob
    if MODE == 'adhoc':
        mon = datetime.now().strftime('%Y-%m')
    else:
        py, pm = (datetime.now().year - 1, 12) if datetime.now().month == 1 else (datetime.now().year, datetime.now().month - 1)
        mon = '%04d-%02d' % (py, pm)
    fp = os.path.join(BASE, CFG['output_dir'], 'filtered-%s.json' % mon)
    if not os.path.exists(fp):
        files = sorted(glob.glob(os.path.join(BASE, CFG['output_dir'], 'filtered-*.json')))
        if not files:
            print('no filtered candidates — run fetch.py + filter.py first'); return 1
        mon = os.path.basename(files[-1])[len('filtered-'):-len('.json')]
        fp = files[-1]
    filtered = json.load(open(fp))
    taste = open(os.path.join(BASE, 'taste-prompt.md')).read()
    seq = {}
    sp = os.path.join(BASE, os.pardir, 'data', 'sequels.json')
    if os.path.exists(sp):
        seq = json.load(open(sp))

    if MODE == 'adhoc':
        window_rule = ('released within the last 30 days — a rolling window ending today (%s). '
                       'This is an ad-hoc "curate now" run.' % datetime.now().strftime('%Y-%m-%d'))
    else:
        window_rule = ('only books released in the specific month being curated (the drop runs on the '
                       '1st for the entire PREVIOUS month)')
    payload = json.dumps({
        'month': mon,
        'window_rule': window_rule,
        'genre_mix': CFG.get('genre_mix', {}),
        'candidates': filtered.get('books', []),
        'sequels_map': seq,
    }, indent=1)

    body = json.dumps({
        'model': CFG.get('model', 'openai/gpt-4o-mini'),
        'messages': [
            {'role': 'system', 'content': taste},
            {'role': 'user', 'content': 'Here are this month\'s candidates JSON. Curate them:\n\n' + payload},
        ],
        'temperature': 0.6,
        'response_format': {'type': 'json_object'},
    }).encode()

    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                 'HTTP-Referer': 'https://the-shelf.local', 'X-Title': 'The Shelf'})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', 'replace')[:600]
        open(os.path.join(BASE, CFG['output_dir'], 'curate-%s.error.json' % mon), 'w').write(json.dumps({'code': e.code, 'body': err}, indent=1))
        print('CURATE HTTP %s — see error file. %s' % (e.code, err[:180]))
        return 2
    except Exception as e:
        print('CURATE failed: %s' % str(e)[:180])
        return 2

    content = data['choices'][0]['message']['content']
    try:
        cur = json.loads(content)
    except Exception:
        # the model wrapped JSON in fences — strip and retry
        import re
        m = re.search(r'\{[\s\S]*\}', content)
        cur = json.loads(m.group(0)) if m else None
    if not cur or 'books' not in cur:
        print('CURATE output not valid JSON — try another model in config.json')
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
    print('curated (%s): %d books, top pick "%s" -> %s' % (MODE, n, cur.get('top_pick', '?'), out))
    return 0

if __name__ == '__main__':
    sys.exit(main())
