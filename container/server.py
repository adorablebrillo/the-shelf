#!/usr/bin/env python3
"""The Shelf — container server.
Serves the built page, holds settings (OpenRouter key, model), schedules the
monthly run (1st, 09:00), exposes a small JSON API used by the in-page
Settings pane. Pure stdlib — no pip installs."""
import json, os, re, shutil, glob, sys, subprocess, tempfile, threading, time, urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

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
    """fetch → filter → curate → build. Uses the in-container pipeline dir.
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


def ensure_default():
    """Never serve a blank page: rebuild from the volume's months at boot when
    any exist (a redeploy must never serve a stale baked page over live data),
    else fall back to the baked page or the design placeholder."""
    try:
        months = sorted(glob.glob(os.path.join(PIPELINE, 'data', 'month-*.json')))
        if months:
            r = subprocess.run([sys.executable, os.path.join(PIPELINE, 'build.py')],
                               capture_output=True, text=True, timeout=300, cwd=PIPELINE)
            if r.returncode == 0 and os.path.isfile(os.path.join(DIST, 'index.html')):
                log('boot: rebuilt the page from %d volume months' % len(months))
                return
            log('boot: rebuild failed — keeping the baked page (%s)'
                % (r.stderr or r.stdout or '')[-160:])
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
        r = subprocess.run([sys.executable, os.path.join(PIPELINE, 'build.py')],
                           capture_output=True, text=True, timeout=300, cwd=PIPELINE)
        if r.returncode == 0 and os.path.isfile(os.path.join(DIST, 'index.html')):
            log('boot: built the blank-state page')
            return
        log('boot: no page yet — press curate now in shelf settings, or wait for the 1st')
    except Exception as e:
        log('boot: default page error: %s' % e)


def main():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LOGSD, exist_ok=True)
    if not os.path.isdir(DIST):
        os.makedirs(DIST, exist_ok=True)
    ensure_personal_data()
    seed_baselines()
    ensure_default()
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), H)
    log('The Shelf server on 0.0.0.0:%d' % PORT)
    srv.serve_forever()

if __name__ == '__main__':
    main()
