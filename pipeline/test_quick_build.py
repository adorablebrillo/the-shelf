#!/usr/bin/env python3
"""The quick boot build (SHELF_OFFLINE=1) builds the page from saved data with
no network request.

Her report: after a restart on the home server the page was not available for
minutes. The boot build retried every missing synopsis and cover lookup before
the server opened its port. The server now runs this quick build first; the
full build (with lookups) follows once the page is up.

Run: cd pipeline && python3 -m unittest test_quick_build

Each run is the real build.py in a throwaway copy of the pipeline, with every
HTTP and HTTPS request routed to a local proxy that counts and refuses it. The
full build is the control: it does try the network, so the proxy sees it.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))


class _CountingProxy(BaseHTTPRequestHandler):
    seen = []

    def _refuse(self):
        _CountingProxy.seen.append('%s %s' % (self.command, self.path))
        self.send_response(502)
        self.send_header('Content-Length', '0')
        self.end_headers()

    do_GET = do_CONNECT = do_HEAD = do_POST = _refuse

    def log_message(self, *a):
        pass


def _last_month():
    t = date.today().replace(day=1)
    y, m = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return '%04d-%02d' % (y, m)


class QuickBuildTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.proxy = ThreadingHTTPServer(('127.0.0.1', 0), _CountingProxy)
        threading.Thread(target=cls.proxy.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.proxy.shutdown()
        cls.proxy.server_close()

    def setUp(self):
        _CountingProxy.seen = []
        self.tmp = tempfile.mkdtemp(prefix='shelf-quick-build-')
        self.pipe = os.path.join(self.tmp, 'pipeline')
        shutil.copytree(HERE, self.pipe, ignore=shutil.ignore_patterns(
            'data', 'dist', '__pycache__', 'test_*', 'testdata'))
        data = os.path.join(self.pipe, 'data')
        os.makedirs(os.path.join(data, 'covers'))
        # last month's issue: one pick whose cover is cached on the volume,
        # one pick with neither a cached cover nor a cached synopsis
        self.ym = _last_month()
        books = [
            {'id': 'b1', 'title': 'Onyx Storm', 'author': 'Rebecca Yarros', 'genre': 'romantasy',
             'img': 'https://is1-ssl.mzstatic.com/image/thumb/onyx/600x600bb.jpg', 'spice': 3},
            {'id': 'b2', 'title': 'Hooked on You', 'author': 'Kathryn Nolan', 'genre': 'hockey romance',
             'img': '', 'spice': 4},
        ]
        with open(os.path.join(data, 'month-%s.json' % self.ym), 'w') as f:
            json.dump({'books': books, 'top_pick': 'b1', 'mode': 'scheduled'}, f)
        with open(os.path.join(data, 'covers', 'onyx-storm-rebecca-yarros.jpg'), 'wb') as f:
            f.write(b'\xff\xd8' + b'0' * 2000)
        self.cfg = os.path.join(self.tmp, 'config')
        os.makedirs(self.cfg)
        self.dist = os.path.join(self.tmp, 'dist')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self, offline):
        proxy = 'http://127.0.0.1:%d' % self.proxy.server_address[1]
        env = dict(os.environ, CFG_DIR=self.cfg, DIST_DIR=self.dist,
                   http_proxy=proxy, https_proxy=proxy, HTTP_PROXY=proxy, HTTPS_PROXY=proxy)
        env.pop('no_proxy', None)
        env.pop('NO_PROXY', None)
        env.pop('SHELF_OFFLINE', None)
        if offline:
            env['SHELF_OFFLINE'] = '1'
        r = subprocess.run([sys.executable, 'build.py'], cwd=self.pipe, env=env,
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout[-600:] + r.stderr[-600:])
        with open(os.path.join(self.dist, 'shelf-data.js')) as f:
            raw = f.read()
        return json.loads(raw[len('window.SHELF_DATA='):].rstrip().rstrip(';'))

    def test_quick_build_makes_the_page_without_a_network_request(self):
        data = self._build(offline=True)
        self.assertEqual(_CountingProxy.seen, [])
        self.assertTrue(os.path.isfile(os.path.join(self.dist, 'index.html')))
        books = {b['title']: b for b in data['books']}
        self.assertEqual(set(books), {'Onyx Storm', 'Hooked on You'})
        # the cached cover is used; the uncached book waits for the full build
        self.assertEqual(books['Onyx Storm']['img'], 'assets/covers/onyx-storm-rebecca-yarros.jpg')
        self.assertEqual(books['Hooked on You']['synopsisSrc'], 'pending')
        # no miss sentinel: the quick build cannot know a lookup would miss
        self.assertEqual(glob.glob(os.path.join(self.pipe, 'data', 'covers', '*.none')), [])

    def test_full_build_still_looks_up_what_is_missing(self):
        self._build(offline=False)
        self.assertTrue(_CountingProxy.seen, 'the full build must try the lookups')


if __name__ == '__main__':
    unittest.main()
