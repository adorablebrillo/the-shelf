#!/usr/bin/env python3
"""The Shelf — container server.
Serves the built page, holds settings (OpenRouter key, model), schedules the
monthly run (1st, 09:00), exposes a small JSON API used by the in-page
Settings pane. Pure stdlib — no pip installs."""
import json, os, re, shutil, glob, sys, subprocess, threading, time, urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(BASE, 'pipeline')
CONFIG_DIR = os.environ.get('CFG_DIR') or (
    '/config' if (os.path.isdir('/config') and os.access('/config', os.W_OK)) else os.path.join(BASE, 'config'))
DIST = os.path.join(BASE, 'dist')
PORT = int(os.environ.get('PORT', 8787))
SETTINGS = os.path.join(CONFIG_DIR, 'settings.json')
LOGSD = os.path.join(CONFIG_DIR, 'logs')

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

def save_settings(s):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    json.dump(s, open(SETTINGS, 'w'), indent=1)

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

def run_pipeline(settings):
    """fetch → filter → curate → build. Uses the in-container pipeline dir."""
    settings['running'] = True
    settings['last_result'] = ''
    save_settings(settings)
    env = dict(os.environ, OPENROUTER_API_KEY=settings.get('api_key', ''))
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
    steps = ['fetch.py', 'filter.py', 'curate.py', 'build.py']
    code = 0
    for s in steps:
        log('stage: %s' % s)
        r = subprocess.run(['python3', os.path.join(PIPELINE, s)], capture_output=True,
                           text=True, env=env, timeout=1500, cwd=PIPELINE)
        log((r.stdout or '')[-800:] + (r.stderr or '')[-400:])
        if r.returncode != 0:
            code = r.returncode
            break
    mon = datetime.now().strftime('%Y-%m')
    n = 0
    try:
        # count the newest VALID (fully past) month — the same month build.py
        # treats as CURRENT; pipeline months live in PIPELINE/data
        files = sorted(glob.glob(os.path.join(PIPELINE, 'data', 'month-*.json')))
        for mf in reversed(files):
            ym = os.path.basename(mf)[len('month-'):-len('.json')]
            if re.match(r'^\d{4}-\d{2}$', ym) and ym < mon:
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
                    threading.Thread(target=run_pipeline, args=(s,), daemon=True).start()
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

    def _static(self, path):
        path = path.lstrip('/') or 'index.html'
        if path.startswith('assets/') or path.endswith('.html') or path == '':
            if '..' in path:
                return self._json({'error': 'bad path'}, 400)
            full = os.path.join(DIST, path)
            if not os.path.isfile(full):
                full = os.path.join(DIST, 'index.html')
            try:
                data = open(full, 'rb').read()
            except Exception:
                return self._json({'error': 'no build yet'}, 404)
            kind = 'image/png' if path.endswith('.png') else 'image/jpeg' if path.endswith(('.jpg', '.jpeg')) else 'text/html; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/api/status':
            s = load_settings()
            self._json({'key_set': bool(s.get('api_key')), 'model': s.get('model'),
                        'schedule': s.get('schedule'), 'last_run': s.get('last_run'),
                        'last_result': s.get('last_result'), 'last_books': s.get('last_books'),
                        'running': s.get('running'), 'cron': 'in-container scheduler'})
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

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        except Exception:
            body = {}
        if u.path == '/api/settings':
            s = load_settings()
            if body.get('api_key') is not None:
                s['api_key'] = str(body['api_key']).strip()
            if body.get('model'):
                s['model'] = str(body['model']).strip()
            save_settings(s)
            log('settings saved (key %s, model %s)' %
                ('set' if s['api_key'] else 'cleared', s['model']))
            self._json({'ok': True, 'key_set': bool(s['api_key']), 'model': s['model']})
        elif u.path == '/api/run':
            s = load_settings()
            if not s.get('api_key'):
                return self._json({'error': 'add your OpenRouter key in Settings first'}, 400)
            if s.get('running'):
                return self._json({'error': 'a run is already in progress'}, 409)
            threading.Thread(target=run_pipeline, args=(s,), daemon=True).start()
            self._json({'ok': True, 'started': True})
        else:
            self._json({'error': 'not found'}, 404)

def ensure_default():
    """Never serve a blank page: build from the newest curated month if any,
    else fall back to the design template (mock shelf + working settings)."""
    try:
        if os.path.isfile(os.path.join(DIST, 'index.html')):
            return
        months = sorted(glob.glob(os.path.join(PIPELINE, 'data', 'month-*.json')))
        if months:
            log('boot: building from %s' % os.path.basename(months[-1]))
            r = subprocess.run([sys.executable, os.path.join(PIPELINE, 'build.py')],
                               capture_output=True, text=True, timeout=180, cwd=PIPELINE)
            if r.returncode == 0 and os.path.isfile(os.path.join(DIST, 'index.html')):
                return
            log('boot: build wrote to pipeline dist? mirroring into served dist')
            bd = os.path.join(PIPELINE, 'dist', 'index.html')
            if os.path.isfile(bd):
                shutil.copy2(bd, os.path.join(DIST, 'index.html'))
                ba = os.path.join(PIPELINE, 'dist', 'assets')
                da = os.path.join(DIST, 'assets')
                if os.path.isdir(ba):
                    shutil.copytree(ba, da, dirs_exist_ok=True)
                log('boot: mirrored pipeline dist into served dist')
                return
            log('boot: build failed (%s)' % (r.stderr or r.stdout or '')[-200:])
        tpl = os.path.join(PIPELINE, 'template.html')
        if os.path.isfile(tpl):
            shutil.copy2(tpl, os.path.join(DIST, 'index.html'))
            log('boot: serving design placeholder until the first run')
        else:
            log('boot: no template found — will 404 until a month is curated')
    except Exception as e:
        log('boot: default page error: %s' % e)


def main():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LOGSD, exist_ok=True)
    if not os.path.isdir(DIST):
        os.makedirs(DIST, exist_ok=True)
    ensure_default()
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), H)
    log('The Shelf server on 0.0.0.0:%d' % PORT)
    srv.serve_forever()

if __name__ == '__main__':
    main()
