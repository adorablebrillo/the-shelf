#!/usr/bin/env python3
"""The Shelf — container server.
Serves the built page, holds settings (OpenRouter key, model), schedules the
monthly run (1st, 09:00), exposes a small JSON API used by the in-page
Settings pane. Pure stdlib — no pip installs."""
import json, os, re, shutil, glob, sys, subprocess, tempfile, threading, time, urllib.request
from contextlib import nullcontext
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)))
# repo root: /app in the image; the checkout root locally (container/ holds the
# server + symlinks there). data/ + seed-reads.json + pipeline/ hang off it.
REPO = BASE if os.path.isdir(os.path.join(BASE, 'data')) else os.path.dirname(BASE)
PIPELINE = os.path.join(BASE, 'pipeline')
CONFIG_DIR = os.environ.get('CFG_DIR') or (
    '/config' if (os.path.isdir('/config') and os.access('/config', os.W_OK)) else os.path.join(BASE, 'config'))
DIST = os.path.join(BASE, 'dist')
PORT = int(os.environ.get('PORT', 8787))
SETTINGS = os.path.join(CONFIG_DIR, 'settings.json')
# the reader's own shelves: every verdict, keyed by book identity. Lives beside
# settings so the mounted volume keeps it across redeploys.
STATE = os.path.join(CONFIG_DIR, 'reader-state.json')
# the author watch list the Authors tab (ticket #8) writes; fetch.py reads it
# every run (missing file is fine — nothing watched yet)
AUTHORS = os.path.join(CONFIG_DIR, 'authors.json')
# books she adds herself by search (ticket #84): the "add a book" panel on My
# Shelf and the Archive writes here; build.py ships them as `added`
ADDED = os.path.join(CONFIG_DIR, 'added-books.json')
LOGSD = os.path.join(CONFIG_DIR, 'logs')

# ---- personal data lives on the VOLUME -----------------------------------
# The repo ships blank defaults; a real shelf keeps its reader data in /config:
# library.json, sequels.json, seed-reads.json, taste-prompt.md. The pipeline
# resolves /config first (pipeline/paths.py); on the first boot of an install
# whose image still carries real data, ensure_personal_data() copies it in
# once. A blank image (fresh install) seeds nothing.
PERSONAL_SEEDS = [
    ('library.json', os.path.join('data', 'library.json'), 'series'),
    ('sequels.json', os.path.join('data', 'sequels.json'), 'series'),
    ('seed-reads.json', 'seed-reads.json', 'books'),
    ('taste-prompt.md', os.path.join('pipeline', 'taste-prompt.md'), 'text'),
]
GENERIC_TASTE_MARKER = 'generic default'


def _personal_meaningful(src, kind):
    """True when a seed source carries real data (never copies blanks)."""
    if not os.path.isfile(src):
        return False
    try:
        if kind == 'text':
            txt = open(src, encoding='utf-8', errors='replace').read()
            return len(txt) > 400 and GENERIC_TASTE_MARKER not in txt
        d = json.load(open(src))
        return bool(isinstance(d, dict) and d.get(kind))
    except Exception:
        return False


def ensure_personal_data():
    """Copy image -> volume once, never overwriting what is already there."""
    seeded, missing = [], []
    for name, rel, kind in PERSONAL_SEEDS:
        dst = os.path.join(CONFIG_DIR, name)
        if os.path.exists(dst):
            continue
        src = os.path.join(REPO, rel)
        if _personal_meaningful(src, kind):
            try:
                shutil.copy2(src, dst)
                seeded.append(name)
            except Exception as e:
                log('personal seed %s failed: %s' % (name, str(e)[:80]))
        else:
            missing.append(name)
    if seeded:
        log('personal data seeded into /config: ' + ', '.join(seeded))
    if 'library.json' in missing:
        log('note: no reader library yet — series lanes stay empty until /config/library.json exists (README: Bring your own data)')


def data_origins():
    """Where each personal file resolved from — the redeploy sanity check."""
    out = {}
    for name, rel, kind in PERSONAL_SEEDS:
        if os.path.exists(os.path.join(CONFIG_DIR, name)):
            out[name] = 'config'
        else:
            src = os.path.join(REPO, rel)
            out[name] = ('image' if _personal_meaningful(src, kind) else ('blank' if os.path.exists(src) else 'missing'))
    out['months'] = len(glob.glob(os.path.join(PIPELINE, 'data', 'month-*.json')))
    return out


def seed_baselines():
    """Bake-time baseline months -> the volume (same rule as run_pipeline's re-seed)."""
    try:
        for mf in glob.glob(os.path.join(PIPELINE, 'baseline', 'month-*.json')):
            dst = os.path.join(PIPELINE, 'data', os.path.basename(mf))
            if not os.path.exists(dst):
                shutil.copy2(mf, dst)
                log('baseline seeded: %s' % os.path.basename(mf))
    except Exception as e:
        log('baseline seed: %s' % str(e)[:80])

DEFAULTS = {
    'api_key': '', 'model': 'openai/gpt-4o-mini',
    'schedule': '0 9 1 * *', 'last_run': None, 'last_result': '', 'last_books': 0,
    'running': False,
}

# recommendations list: (model id, why, tier)
RECS = [
    ('openai/gpt-4o-mini', 'balanced pick — fast, clean JSON, cheap', 'recommended'),
    ('deepseek/deepseek-chat', 'cheapest good quality — cost-effective', 'cost'),
    ('google/gemini-2.5-flash', 'very fast, great value', 'cost'),
    ('anthropic/claude-3.5-haiku', 'best instruction-following for JSON curation', 'quality'),
    ('openrouter/auto', 'OpenRouter auto-routes to smartest value', 'balanced'),
]

def load_settings():
    try:
        s = json.load(open(SETTINGS))
    except Exception:
        s = {}
    return {**DEFAULTS, **s}

def _atomic_json(path, d, indent=None):
    """Write JSON via a UNIQUE temp file + rename: two concurrent writers can
    never share a temp (the #57 fold — a verdict fires two posts at once)."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or '.', prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(d, f, indent=indent)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_settings(s):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    _atomic_json(SETTINGS, s, indent=1)

def log(msg, level='run'):
    os.makedirs(LOGSD, exist_ok=True)
    line = '%s [%s] %s' % (datetime.now().isoformat(), level, msg)
    print(line, flush=True)
    with open(os.path.join(LOGSD, 'monthly.log'), 'a') as f:
        f.write(line + '\n')

def api_key():
    return load_settings().get('api_key', '')

def fetch_models():
    """OpenRouter public model list; filter to the curated shortlist + live
    pricing. Falls back to a cached list when unreachable."""
    try:
        req = urllib.request.Request('https://openrouter.ai/api/v1/models',
                                     headers={'User-Agent': 'the-shelf/1.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
        by_id = {m.get('id'): m for m in d.get('data', [])}
    except Exception as e:
        log('models fetch failed: %s' % str(e)[:80])
        by_id = {}
    out = []
    for mid, why, tier in RECS:
        m = by_id.get(mid) or {}
        p = m.get('pricing') or {}
        p_in = float(p.get('prompt', 0)) * 1e6
        p_out = float(p.get('completion', 0)) * 1e6
        out.append({
            'id': mid, 'name': m.get('name', mid), 'tier': tier, 'why': why,
            'in_mtok': round(p_in, 3), 'out_mtok': round(p_out, 3),
            'ctx': m.get('context_length', None),
        })
    if not out:
        raise RuntimeError('no models')
    return out

def run_pipeline(settings, mode='adhoc'):
    """fetch → reference → filter → curate → build. Uses the in-container pipeline dir.
    mode='adhoc'     — "curate now": rolling last-30-days window (manual button)
    mode='scheduled' — the 1st-of-month drop: the previous month's books"""
    settings['running'] = True
    settings['last_result'] = ''
    save_settings(settings)
    env = dict(os.environ, OPENROUTER_API_KEY=settings.get('api_key', ''), SHELF_MODE=mode)
    # seed any missing baseline months into the mounted data dir so the archive
    # (June/July) survives the volume shadowing the image's baked files
    try:
        import shutil as _sh, glob as _gl
        for mf in _gl.glob(os.path.join(PIPELINE, 'baseline', 'month-*.json')):
            dst = os.path.join(PIPELINE, 'data', os.path.basename(mf))
            if not os.path.exists(dst):
                _sh.copy2(mf, dst)
    except Exception as e:
        log('baseline seed: %s' % e)
    steps = ['fetch.py', 'reference.py', 'filter.py', 'curate.py', 'build.py']
    code = 0
    for s in steps:
        log('stage: %s (%s)' % (s, mode))
        # one page build at a time: a run started during the boot full build
        # waits for it here instead of writing the page beside it
        with (BUILD_LOCK if s == 'build.py' else nullcontext()):
            r = subprocess.run(['python3', os.path.join(PIPELINE, s)], capture_output=True,
                               text=True, env=env, timeout=1500, cwd=PIPELINE)
        log((r.stdout or '')[-800:] + (r.stderr or '')[-400:])
        if r.returncode != 0:
            code = r.returncode
            break
    mon = datetime.now().strftime('%Y-%m')
    n = 0
    try:
        # count the newest VALID month the page actually shows: past months
        # always count; a current-month file only when an ad-hoc run wrote it
        files = sorted(glob.glob(os.path.join(PIPELINE, 'data', 'month-*.json')))
        for mf in reversed(files):
            ym = os.path.basename(mf)[len('month-'):-len('.json')]
            if not re.match(r'^\d{4}-\d{2}$', ym) or ym > mon:
                continue
            if ym == mon:
                try:
                    if json.load(open(mf)).get('mode') != 'adhoc':
                        continue
                except Exception:
                    continue
            n = len(json.load(open(mf)).get('books', []))
            break
    except Exception:
        pass
    s = load_settings()
    s['running'] = False
    s['last_run'] = datetime.now().isoformat()
    s['last_result'] = 'success' if code == 0 else 'failed (see logs)'
    s['last_books'] = n
    save_settings(s)
    log('pipeline done: %s (%d books)' % (s['last_result'], n))

# ---------- scheduler thread ----------
def scheduler():
    while True:
        try:
            s = load_settings()
            now = datetime.now()
            if not s['running'] and now.day == 1 and now.hour >= 9 and now.minute >= 0:
                last = s.get('last_run') or ''
                if not last.startswith(now.strftime('%Y-%m')):
                    if not s.get('api_key'):
                        log('monthly run due — no API key saved yet, add it in shelf settings')
                        break
                    log('monthly run triggered')
                    threading.Thread(target=run_pipeline, args=(s, 'scheduled'), daemon=True).start()
        except Exception as e:
            log('scheduler err: %s' % str(e)[:100])
        time.sleep(60)

# ---------- HTTP ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    KINDS = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
             '.webmanifest': 'application/manifest+json; charset=utf-8',
             '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg',
             '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.webp': 'image/webp',
             '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.woff': 'font/woff'}

    def _static(self, path):
        path = path.lstrip('/') or 'index.html'
        if '..' in path:
            return self._json({'error': 'bad path'}, 400)
        ext = os.path.splitext(path)[1].lower()
        full = os.path.join(DIST, path)
        if ext not in self.KINDS or not os.path.isfile(full):
            # unknown route or missing file -> the page itself (single-page app)
            full = os.path.join(DIST, 'index.html')
            ext = '.html'
        try:
            data = open(full, 'rb').read()
        except Exception:
            return self._json({'error': 'no build yet'}, 404)
        self.send_response(200)
        self.send_header('Content-Type', self.KINDS[ext])
        self.send_header('Content-Length', str(len(data)))
        # The page and its data must never come from a stale cache: a redeploy
        # pairs a NEW app with the data file it shipped, and an old cached
        # shelf-data.js blanks the archive (no book identities in it). Cover art
        # and the vendored runtime are static enough to cache briefly.
        self.send_header('Cache-Control',
                         'no-store' if ext in ('.html', '.js') else 'public, max-age=3600')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/api/state':
            self._json(load_state())
        elif u.path == '/api/authors':
            self._json({'authors': load_authors()['authors']})
        elif u.path == '/api/search':
            q = (parse_qs(u.query).get('q') or [''])[0]
            try:
                self._json({'results': search_books(q)})
            except Exception as e:
                log('book search failed: %s' % str(e)[:80])
                self._json({'error': 'Apple Books did not answer — try again', 'results': []}, 502)
        elif u.path == '/api/books':
            self._json({'books': load_added()['books']})
        elif u.path == '/api/status':
            s = load_settings()
            self._json({'key_set': bool(s.get('api_key')), 'model': s.get('model'),
                        'schedule': s.get('schedule'), 'last_run': s.get('last_run'),
                        'last_result': s.get('last_result'), 'last_books': s.get('last_books'),
                        'running': s.get('running'), 'cron': 'in-container scheduler',
                        'data': data_origins()})
        elif u.path == '/api/models':
            try:
                self._json({'models': fetch_models()})
            except Exception as e:
                self._json({'error': str(e)[:120]}, 500)
        elif u.path == '/api/logs':
            try:
                lines = open(os.path.join(LOGSD, 'monthly.log')).read()[-4000:]
                self._json({'log': lines})
            except Exception:
                self._json({'log': ''})
        else:
            self._static(u.path)

    def _body(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        except Exception:
            return {}

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        if u.path == '/api/state':
            # one writer at a time: the merge is read-modify-write, and a
            # verdict now fires two posts (states + reading) at once
            with STATE_LOCK:
                cur = load_state()
                cur['states'] = merge_states(cur.get('states'), body.get('states') or {})
                # #57: the reading channel — its own map beside the marks, merged
                # by the same last-write-wins rule (a reading flag must never
                # enter 'states': the pipeline reads that as verdicts)
                if 'reading' in body:
                    cur['reading'] = merge_states(cur.get('reading'), body.get('reading') or {})
                save_state(cur)
            live = [k for k, v in cur['states'].items() if isinstance(v, dict) and v.get('s')]
            gone = [k for k, v in cur['states'].items() if isinstance(v, dict) and v.get('s') is None]
            log('reader state: %d marked, %d cleared' % (len(live), len(gone)))
            self._json({'ok': True, 'v': 2, 'states': cur['states'],
                        'reading': cur.get('reading') or {}, 'updated': cur['updated']})
        elif u.path == '/api/settings':
            s = load_settings()
            if body.get('api_key') is not None:
                s['api_key'] = str(body['api_key']).strip()
            if body.get('model'):
                s['model'] = str(body['model']).strip()
            save_settings(s)
            log('settings saved (key %s, model %s)' %
                ('set' if s['api_key'] else 'cleared', s['model']))
            self._json({'ok': True, 'key_set': bool(s['api_key']), 'model': s['model']})
        elif u.path == '/api/authors':
            lst, err = authors_add(body.get('name'), body.get('lane'))
            if err:
                return self._json({'error': err, 'authors': lst}, 400)
            log('author watch added: %s' % lst[-1]['name'])
            self._json({'ok': True, 'authors': lst})
        elif u.path == '/api/books':
            rec, err = added_add(body)
            if err:
                return self._json({'error': err}, 400)
            log('book added: %s' % rec['id'][:60])
            self._json({'ok': True, 'book': rec, 'books': load_added()['books']})
        elif u.path == '/api/import/goodreads':
            text = body.get('text')
            if not isinstance(text, str) or not text.strip():
                return self._json({'error': 'Choose your Goodreads export file first.'}, 400)
            if len(text) > GR_MAX_BYTES:
                return self._json({'error': 'That file is too large for a Goodreads export.'}, 400)
            dry = body.get('dry') is not False
            res, err = import_goodreads(text, dry=dry, track=body.get('track'))
            if err:
                return self._json({'error': err}, 400)
            if not dry:
                log('goodreads import: %d books (%s), %d left out, %d already marked, %d series not tracked'
                    % (res['imported'], ', '.join('%d %s' % (n, k) for k, n in res['counts'].items()),
                       res['left_out'], res['already'], len(res['untracked'])))
            self._json({'ok': True, 'dry': dry, **res})
        elif u.path == '/api/run':
            s = load_settings()
            if not s.get('api_key'):
                return self._json({'error': 'add your OpenRouter key in Settings first'}, 400)
            if s.get('running'):
                return self._json({'error': 'a run is already in progress'}, 409)
            threading.Thread(target=run_pipeline, args=(s, 'adhoc'), daemon=True).start()
            self._json({'ok': True, 'started': True, 'mode': 'adhoc'})
        else:
            self._json({'error': 'not found'}, 404)

    def do_DELETE(self):
        u = urlparse(self.path)
        body = self._body()
        if u.path == '/api/authors':
            lst = authors_remove(body.get('name'))
            log('author watch removed: %s' % str(body.get('name'))[:60])
            self._json({'ok': True, 'authors': lst})
        elif u.path == '/api/books':
            lst = added_remove(body.get('id'))
            log('book removed: %s' % str(body.get('id'))[:60])
            self._json({'ok': True, 'books': lst})
        else:
            self._json({'error': 'not found'}, 404)

def load_state():
    """The reader's marks. Returns {v, states:{<book id>:{s,t}}, updated}."""
    try:
        d = json.load(open(STATE))
        if isinstance(d.get('states'), dict):
            return d
    except Exception:
        pass
    return {'v': 2, 'states': {}, 'updated': ''}


def save_state(d):
    """Atomic write — a mark must never be lost to a half-written file."""
    d['v'] = 2
    d['updated'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    _atomic_json(STATE, d)


STATE_LOCK = threading.Lock()


def merge_states(server_states, incoming):
    """Per-key merge keyed on each mark's own timestamp, so a mark made on the
    phone and a mark made on the desktop both survive. A null state is a
    tombstone: an un-mark that has to travel between devices too."""
    out = dict(server_states or {})
    for k, v in (incoming or {}).items():
        if isinstance(v, dict):
            vs, vt = v.get('s'), int(v.get('t') or 0)
        else:
            vs, vt = v, 0
        cur = out.get(k)
        cur_t = int((cur or {}).get('t') or 0) if isinstance(cur, dict) else 0
        if vt < cur_t:
            continue
        out[k] = {'s': vs, 't': vt}
    return out


def norm_author(name):
    """The fetch's normalization (fetch.py normkey — keep the two in step):
    lowercase, non-alphanumerics dropped."""
    return re.sub(r'[^a-z0-9]', '', str(name or '').lower())


def load_authors():
    """The watch list — only the authors she added. {v, authors:[{name,lane}]}."""
    try:
        d = json.load(open(AUTHORS))
        if isinstance(d.get('authors'), list):
            return d
    except Exception:
        pass
    return {'authors': []}


def save_authors(d):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    _atomic_json(AUTHORS, d, indent=1)


def authors_add(name, lane):
    """(authors, error). A duplicate answers 'author already on the list'."""
    name = ' '.join(str(name or '').split())
    if not name:
        return load_authors()['authors'], 'give the author a name'
    d = load_authors()
    key = norm_author(name)
    if any(norm_author(a.get('name')) == key for a in d['authors']):
        return d['authors'], 'author already on the list'
    lane = str(lane or '').strip() or None
    d['authors'].append({'name': name, 'lane': lane})
    save_authors(d)
    return d['authors'], None


def authors_remove(name):
    d = load_authors()
    key = norm_author(name)
    keep = [a for a in d['authors'] if norm_author(a.get('name')) != key]
    if len(keep) != len(d['authors']):
        d['authors'] = keep
        save_authors(d)
    return d['authors']


# Only one page build writes dist at a time (the boot full build, a run's build).
BUILD_LOCK = threading.Lock()


def run_build(offline=False, timeout=300):
    """pipeline/build.py once. offline=True is the quick boot build: saved
    data only (SHELF_OFFLINE=1 — cached covers and synopses, no network)."""
    env = dict(os.environ)
    env.pop('SHELF_OFFLINE', None)
    if offline:
        env['SHELF_OFFLINE'] = '1'
    return subprocess.run([sys.executable, os.path.join(PIPELINE, 'build.py')], env=env,
                          capture_output=True, text=True, timeout=timeout, cwd=PIPELINE)


# ---------- added books (ticket #84) ----------
# A book the runs never picked, found by an Apple Books search. One record per
# book identity (book_key, the id every mark keys on), so the reader's verdict
# on it travels through /api/state like any other mark.
ADDED_LOCK = threading.Lock()
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36'}


def _pipeline_import(name):
    """A pipeline module (bookids, fetch) — /app/pipeline in the image, the
    repo's pipeline/ in a checkout."""
    for d in (PIPELINE, os.path.join(REPO, 'pipeline')):
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
    return __import__(name)


def apple_country():
    try:
        cfg = json.load(open(os.path.join(os.path.dirname(_pipeline_import('bookids').__file__), 'config.json')))
        return str(cfg.get('apple_country') or 'us')
    except Exception:
        return 'us'


def _get_text(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def _clean(v, n=200):
    return ' '.join(str(v or '').split())[:n]


def search_books(q, get_text=_get_text):
    """Up to 10 Apple Books ebook results for a free-text query."""
    q = _clean(q, 120)
    if not q:
        return []
    url = 'https://itunes.apple.com/search?' + urlencode(
        {'term': q, 'media': 'ebook', 'entity': 'ebook', 'limit': 10, 'country': apple_country()})
    book_key = _pipeline_import('bookids').book_key
    out, seen = [], set()
    for it in (json.loads(get_text(url)) or {}).get('results') or []:
        title, author = _clean(it.get('trackName')), _clean(it.get('artistName'))
        bid = book_key(title, author)
        if not title or not author or not bid or bid in seen:
            continue   # Apple lists some books twice (two editions): one row each
        seen.add(bid)
        art = it.get('artworkUrl100') or it.get('artworkUrl60') or ''
        out.append({'id': bid, 'title': title, 'author': author,
                    'date': str(it.get('releaseDate') or '')[:10],
                    'cover': art.replace('100x100bb', '600x600bb').replace('60x60bb', '600x600bb'),
                    'genre': ' '.join((it.get('genres') or [])[:3]),
                    'appleId': str(it.get('trackId') or ''),
                    'url': str(it.get('trackViewUrl') or '').split('?')[0]})
    return out[:10]


def load_added():
    """{v, books:[{id,title,author,date,img,genre,appleId,url,series,series_num,added}]}"""
    try:
        d = json.load(open(ADDED))
        if isinstance(d.get('books'), list):
            return d
    except Exception:
        pass
    return {'v': 1, 'books': []}


def save_added(d):
    d['v'] = 1
    _atomic_json(ADDED, d, indent=1)


def added_add(book, get_text=_get_text):
    """(record, error). Saves one searched book; adding it twice returns the
    first record. Its Apple page is read once, outside the lock, for series."""
    book = book if isinstance(book, dict) else {}
    title, author = _clean(book.get('title')), _clean(book.get('author'))
    bid = _pipeline_import('bookids').book_key(title, author)
    if not title or not author or not bid:
        return None, 'a book needs a title and an author'
    same = [b for b in load_added()['books'] if b.get('id') == bid]
    if same:
        return same[0], None
    url = str(book.get('url') or '').split('?')[0]
    if not re.match(r'^https://books\.apple\.com/', url):
        url = ''   # only Apple's own book pages are ever fetched
    ser = {'series': '', 'num': ''}
    if url:
        try:
            ser = _pipeline_import('fetch').page_series(get_text(url))
        except Exception as e:
            log('added book series lookup failed: %s' % str(e)[:80])
    cover = str(book.get('cover') or '')
    rec = {'id': bid, 'title': title, 'author': author,
           'date': _clean(book.get('date'), 10), 'img': cover if cover.startswith('https://') else '',
           'genre': _clean(book.get('genre'), 80), 'appleId': _clean(book.get('appleId'), 20),
           'url': url, 'series': _clean(ser.get('series'), 120), 'series_num': _clean(ser.get('num'), 8),
           'added': datetime.now().strftime('%Y-%m-%d')}
    with ADDED_LOCK:
        d = load_added()
        same = [b for b in d['books'] if b.get('id') == bid]
        if same:
            return same[0], None
        d['books'].append(rec)
        save_added(d)
    return rec, None


def added_remove(bid):
    with ADDED_LOCK:
        d = load_added()
        keep = [b for b in d['books'] if b.get('id') != bid]
        if len(keep) != len(d['books']):
            d['books'] = keep
            save_added(d)
    return d['books']


# ---------- Goodreads import (ticket #93) ----------
# The Settings Import tab sends the Goodreads export file (My Books → Import
# and export → Export Library). A dry call previews; the second call imports.
# Every imported book is an added book (added-books.json) with its mark in the
# reader state. No web lookups: covers and blurbs fill over later page builds.
GR_REQUIRED = ('Title', 'Author', 'Exclusive Shelf')
GR_DNF = ('dnf', 'didnotfinish')          # shelf names, letters and digits only
GR_MAX_BYTES = 20 * 1024 * 1024


def _gr_shelf(s):
    return re.sub(r'[^a-z0-9]', '', str(s or '').lower())


def gr_title(raw):
    """'Fourth Wing (The Empyrean, #1)' -> ('Fourth Wing', 'The Empyrean', '1').
    Goodreads writes the series and number in brackets at the end of a title."""
    raw = _clean(raw)
    m = re.search(r'\s*\(([^()]+?),?\s+#\s*(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?\)\s*$', raw)
    if not m:
        return raw, '', ''
    return raw[:m.start()].strip() or raw, m.group(1).strip(), m.group(2)


def gr_time(*dates):
    """The mark's time in ms: the first date given (Date Read, then Date Added),
    at noon local time so the day never shifts. No date at all is 1 — the
    oldest possible mark, still newer than no mark."""
    for d in dates:
        m = re.match(r'\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(d or ''))
        if m:
            try:
                return int(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 12).timestamp() * 1000)
            except (ValueError, OverflowError):
                continue
    return 1


def gr_verdict(exclusive, shelves, rating):
    """(verdict, reading now, why left out). The agreed mapping: read with 5
    stars is loved; read with fewer or no stars is read; to-read is want;
    currently-reading is want plus reading now; a dnf shelf is not for me;
    any other shelf is left out."""
    ex = _gr_shelf(exclusive)
    if ex in GR_DNF or any(_gr_shelf(s) in GR_DNF for s in shelves):
        return 'skip', False, ''
    if ex == 'read':
        return ('loved' if rating == 5 else 'read'), False, ''
    if ex == 'toread':
        return 'want', False, ''
    if ex == 'currentlyreading':
        return 'want', True, ''
    return None, False, 'on the shelf “%s”' % (_clean(exclusive, 60) or 'none')


def parse_goodreads(text):
    """-> (books, left_out, error). books: one dict per book in the file;
    left_out: [{title, author, why}]."""
    import csv, io
    book_key = _pipeline_import('bookids').book_key
    text = str(text or '').lstrip('﻿')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or any(c not in reader.fieldnames for c in GR_REQUIRED):
        return [], [], 'This is not a Goodreads export file: it has no Title, Author and Exclusive Shelf columns.'
    books, left, seen = [], [], set()
    for row in reader:
        title, series, num = gr_title(row.get('Title'))
        author = _clean(row.get('Author'))
        bid = book_key(title, author)
        if not title or not author or not bid:
            left.append({'title': title, 'author': author, 'why': 'no title or author'})
            continue
        if bid in seen:
            left.append({'title': title, 'author': author, 'why': 'listed twice'})
            continue
        try:
            rating = int(str(row.get('My Rating') or '0').strip() or 0)
        except ValueError:
            rating = 0
        shelves = [s for s in str(row.get('Bookshelves') or '').split(',') if s.strip()]
        verdict, reading, why = gr_verdict(row.get('Exclusive Shelf'), shelves, rating)
        if not verdict:
            left.append({'title': title, 'author': author, 'why': why})
            continue
        seen.add(bid)
        books.append({'id': bid, 'title': title, 'author': author, 'series': series,
                      'series_num': num, 'rating': rating, 's': verdict, 'reading': reading,
                      't': gr_time(row.get('Date Read'), row.get('Date Added')),
                      'isbn13': re.sub(r'[^0-9Xx]', '', str(row.get('ISBN13') or ''))[:13]})
    return books, left, None


def gr_series(books):
    """The series of the read and loved books, ticked first when she read 2 or
    more of its books or gave one 4 or 5 stars. Sorted ticked first, then by
    how many she read."""
    norm = _pipeline_import('sequels').norm_name
    groups = {}
    for b in books:
        if b['s'] not in ('read', 'loved') or not b['series']:
            continue
        key = norm(b['series'])
        if not key:
            continue
        g = groups.setdefault(key, {'name': b['series'], 'author': b['author'], 'read': 0, 'top': 0})
        g['read'] += 1
        g['top'] = max(g['top'], b['rating'])
    out = []
    for g in groups.values():
        out.append({'name': g['name'], 'author': g['author'], 'read': g['read'],
                    'ticked': g['read'] >= 2 or g['top'] >= 4})
    out.sort(key=lambda g: (not g['ticked'], -g['read'], g['name'].lower()))
    return out


def import_goodreads(text, dry=True, track=None):
    """The preview (dry) or the import itself. track: the series names she
    ticked; on an import, every other series found goes to the untracked list
    in added-books.json, which the series tracked from marks skip. A mark the
    app already holds — set or cleared — is never changed, so a second import
    of the same file adds nothing."""
    books, left, err = parse_goodreads(text)
    if err:
        return None, err
    states = load_state().get('states') or {}
    fresh = [b for b in books if b['id'] not in states]
    already = [b for b in books if b['id'] in states]
    series = gr_series(fresh)
    counts = {'loved': 0, 'read': 0, 'want': 0, 'skip': 0}
    for b in fresh:
        counts[b['s']] += 1
    why = {}
    for x in left:
        why[x['why']] = why.get(x['why'], 0) + 1
    out = {'counts': counts, 'reading': sum(1 for b in fresh if b['reading']),
           'total': len(fresh), 'left_out': len(left),
           'left_why': [{'why': k, 'n': n} for k, n in sorted(why.items(), key=lambda kv: -kv[1])],
           'already': len(already), 'series': series}
    if dry:
        return out, None

    norm = _pipeline_import('sequels').norm_name
    if track is None:
        track = [g['name'] for g in series if g['ticked']]
    ticked = {norm(n) for n in track if isinstance(n, str)}
    unticked = {norm(g['name']): g['name'] for g in series if norm(g['name']) not in ticked}
    try:
        verdicts = _pipeline_import('verdicts')   # every book the shelf already shows
        shown = verdicts.book_details(os.path.join(os.path.dirname(verdicts.__file__), 'data'))
    except Exception as e:
        log('goodreads import: book lookup failed (%s)' % str(e)[:80])
        shown = {}
    today = datetime.now().strftime('%Y-%m-%d')
    with ADDED_LOCK:
        d = load_added()
        have = {b.get('id') for b in d['books']}
        for b in fresh:
            if b['id'] in have or b['id'] in shown:
                continue   # a pick or a series volume already: the mark is enough
            d['books'].append({'id': b['id'], 'title': b['title'], 'author': b['author'],
                               'date': '', 'img': '', 'genre': '', 'appleId': '', 'url': '',
                               'series': b['series'], 'series_num': b['series_num'],
                               'isbn13': b['isbn13'], 'added': today, 'from': 'goodreads'})
            have.add(b['id'])
        keep = [n for n in (d.get('untracked') or []) if isinstance(n, str) and norm(n) not in ticked]
        keep_keys = {norm(n) for n in keep}
        d['untracked'] = sorted(keep + [n for k, n in unticked.items() if k not in keep_keys], key=str.lower)
        save_added(d)
    with STATE_LOCK:
        cur = load_state()
        st = cur.get('states') or {}
        rd = cur.get('reading') or {}
        for b in fresh:
            if b['id'] in st:
                continue   # marked while the preview was open: the app's mark wins
            st[b['id']] = {'s': b['s'], 't': b['t']}
            if b['reading'] and b['id'] not in rd:
                rd[b['id']] = {'s': True, 't': b['t']}
        cur['states'], cur['reading'] = st, rd
        save_state(cur)
    out['imported'] = len(fresh)
    out['untracked'] = sorted(unticked.values(), key=str.lower)
    return out, None


def ensure_default(offline=False):
    """Never serve a blank page: rebuild from the volume's months at boot when
    any exist (a redeploy must never serve a stale baked page over live data),
    else fall back to the baked page or the design placeholder.
    offline=True is the quick build before the port opens; the full build
    (lookups for new covers and synopses) runs after it, in the background."""
    kind = 'quick' if offline else 'full'
    try:
        months = sorted(glob.glob(os.path.join(PIPELINE, 'data', 'month-*.json')))
        if months:
            r = run_build(offline, timeout=120 if offline else 300)
            if r.returncode == 0 and os.path.isfile(os.path.join(DIST, 'index.html')):
                log('boot: %s rebuild of the page from %d volume months' % (kind, len(months)))
                return
            log('boot: %s rebuild failed — keeping the page already there (%s)'
                % (kind, (r.stderr or r.stdout or '')[-160:]))
            # the writer may have targeted pipeline/dist instead (flattened layouts)
            bd = os.path.join(PIPELINE, 'dist', 'index.html')
            if os.path.isfile(bd):
                shutil.copy2(bd, os.path.join(DIST, 'index.html'))
                bm = os.path.join(PIPELINE, 'dist', 'manifest.webmanifest')
                if os.path.isfile(bm):  # ticket #12 — install metadata rides along
                    shutil.copy2(bm, os.path.join(DIST, 'manifest.webmanifest'))
                ba = os.path.join(PIPELINE, 'dist', 'assets')
                da = os.path.join(DIST, 'assets')
                if os.path.isdir(ba):
                    shutil.copytree(ba, da, dirs_exist_ok=True)
                log('boot: mirrored pipeline dist into served dist')
                return
        if os.path.isfile(os.path.join(DIST, 'index.html')):
            return
        # nothing baked and nothing on the volume: build the blank-state page
        r = run_build(offline, timeout=120 if offline else 300)
        if r.returncode == 0 and os.path.isfile(os.path.join(DIST, 'index.html')):
            log('boot: built the blank-state page')
            return
        log('boot: no page yet — press curate now in shelf settings, or wait for the 1st')
    except Exception as e:
        log('boot: %s default page error: %s' % (kind, e))


def full_build():
    """The boot full build, after the port is open: new covers and synopses."""
    with BUILD_LOCK:
        ensure_default(offline=False)


def boot(port=None, host='0.0.0.0'):
    """Quick build from saved data, open the port, then start the full build
    in the background. A restart serves the page in seconds instead of after
    every lookup (the full build alone can take minutes). Returns the bound
    server and the full build's thread."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LOGSD, exist_ok=True)
    if not os.path.isdir(DIST):
        os.makedirs(DIST, exist_ok=True)
    ensure_personal_data()
    seed_baselines()
    ensure_default(offline=True)
    srv = ThreadingHTTPServer((host, PORT if port is None else port), H)
    log('The Shelf server on %s:%d' % (host, srv.server_address[1]))
    full = threading.Thread(target=full_build, daemon=True)
    full.start()
    return srv, full


def main():
    srv, _ = boot()
    threading.Thread(target=scheduler, daemon=True).start()
    srv.serve_forever()

if __name__ == '__main__':
    main()
