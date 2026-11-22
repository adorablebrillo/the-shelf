#!/usr/bin/env python3
"""A cut-off run never blocks the next one.

The bug: run_pipeline set 'running' in settings.json and cleared it only at
its end. A container restart mid-run, or a stage that ran past its time limit
(subprocess.TimeoutExpired, never caught), left the flag on for good: Settings
showed "running…", curate now answered 409 "a run is already in progress",
and the monthly run never started again. Separately, a monthly run that came
due with no key saved ended the scheduler loop, so saving the key later did
not bring the run back until a restart.

Run: cd container && python3 -m unittest test_run

The stand-in pipeline below has the five stage scripts the real run calls.
Each writes nothing; fetch.py sleeps when told to, standing in for a stage
that hangs.
"""
import json
import os
import tempfile
import time
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime

TMP = tempfile.mkdtemp(prefix='shelf-run-test-')
os.environ.setdefault('CFG_DIR', os.path.join(TMP, 'config'))
os.environ.setdefault('DIST_DIR', os.path.join(TMP, 'dist'))

import server  # noqa: E402

QUICK_STAGE = 'import sys; sys.exit(0)\n'
HANGING_STAGE = 'import time; time.sleep(30)\n'
STAND_IN_BUILD = r'''
import os
dist = os.environ.get('DIST_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist')
os.makedirs(dist, exist_ok=True)
open(os.path.join(dist, 'index.html'), 'w').write('page')
'''


class RunTests(unittest.TestCase):

    def setUp(self):
        root = tempfile.mkdtemp(dir=TMP)
        self.cfg = os.path.join(root, 'config')
        self.pipeline = os.path.join(root, 'pipeline')
        os.makedirs(self.cfg)
        os.makedirs(os.path.join(self.pipeline, 'data'))
        for stage in ('fetch.py', 'reference.py', 'filter.py', 'curate.py'):
            self._stage(stage, QUICK_STAGE)
        self._stage('build.py', STAND_IN_BUILD)
        self._old = {k: getattr(server, k) for k in
                     ('CONFIG_DIR', 'SETTINGS', 'LOGSD', 'PIPELINE', 'DIST', 'STAGE_TIMEOUT')}
        server.CONFIG_DIR = self.cfg
        server.SETTINGS = os.path.join(self.cfg, 'settings.json')
        server.LOGSD = os.path.join(self.cfg, 'logs')
        server.PIPELINE = self.pipeline
        server.DIST = os.environ['DIST_DIR']

    def tearDown(self):
        self._wait_idle()
        for k, v in self._old.items():
            setattr(server, k, v)

    def _stage(self, name, code):
        with open(os.path.join(self.pipeline, name), 'w') as f:
            f.write(code)

    def _settings(self, **kw):
        server.save_settings({**server.DEFAULTS, **kw})

    def _wait_idle(self, seconds=20):
        deadline = time.time() + seconds
        while server.RUN_LOCK.locked() and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(server.RUN_LOCK.locked(), 'the run never ended')

    def _call(self, srv, path, method='GET'):
        url = 'http://127.0.0.1:%d%s' % (srv.server_address[1], path)
        req = urllib.request.Request(url, method=method, data=b'{}' if method == 'POST' else None)
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_restart_mid_run_leaves_curate_now_working(self):
        # settings.json as a restart leaves it: the run that set the flag is gone
        self._settings(api_key='sk-test', running=True)
        srv, full = server.boot(port=0, host='127.0.0.1')
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            full.join(20)
            code, status = self._call(srv, '/api/status')
            self.assertEqual(code, 200)
            self.assertFalse(status['running'])
            self.assertEqual(status['last_result'], 'stopped by a restart (see logs)')
            code, started = self._call(srv, '/api/run', 'POST')
            self.assertEqual((code, started.get('started')), (200, True))
            self._wait_idle()
            self.assertEqual(self._call(srv, '/api/status')[1]['last_result'], 'success')
        finally:
            srv.shutdown()
            srv.server_close()

    def test_a_stage_past_its_time_limit_ends_the_run(self):
        self._stage('fetch.py', HANGING_STAGE)
        server.STAGE_TIMEOUT = 1
        self._settings(api_key='sk-test')
        self.assertTrue(server.start_run('adhoc'))
        self._wait_idle()
        s = server.load_settings()
        self.assertFalse(s['running'])
        self.assertEqual(s['last_result'], 'failed (see logs)')
        # and the next curate now starts
        self._stage('fetch.py', QUICK_STAGE)
        self.assertTrue(server.start_run('adhoc'))
        self._wait_idle()
        self.assertEqual(server.load_settings()['last_result'], 'success')

    def test_a_second_run_waits_for_the_first(self):
        self._stage('fetch.py', 'import time; time.sleep(1)\n')
        self._settings(api_key='sk-test')
        self.assertTrue(server.start_run('adhoc'))
        self.assertFalse(server.start_run('adhoc'))
        self._wait_idle()

    def test_the_monthly_run_starts_once_the_key_is_saved_late(self):
        self._settings(api_key='', last_run='2026-11-05T09:00:00')
        first = datetime(2026, 12, 1, 9, 0)
        warned = server.scheduler_tick(first)
        self.assertFalse(server.RUN_LOCK.locked(), 'no key, no run')
        # she saves the key ten minutes later; the scheduler is still looking
        s = server.load_settings()
        s['api_key'] = 'sk-test'
        server.save_settings(s)
        server.scheduler_tick(datetime(2026, 12, 1, 9, 10), warned)
        self._wait_idle()
        s = server.load_settings()
        self.assertEqual(s['last_result'], 'success')
        self.assertTrue(s['last_run'].startswith(datetime.now().strftime('%Y-%m')))


if __name__ == '__main__':
    unittest.main()
