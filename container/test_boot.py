#!/usr/bin/env python3
"""The boot order: a restart serves the page before the slow full build.

Her report: after a restart on the home server the page was not available for
minutes, because the server ran the whole build (cover and synopsis lookups)
before it opened its port. Now boot() runs the quick build from saved data,
opens the port, and only then runs the full build in the background.

Run: cd container && python3 -m unittest test_boot

The stand-in pipeline/build.py below writes the page the way the real one does
(DIST_DIR/index.html). Its full build (no SHELF_OFFLINE) holds until the test
releases it, standing in for minutes of lookups.
"""
import os
import tempfile
import threading
import unittest
import urllib.request

TMP = tempfile.mkdtemp(prefix='shelf-boot-test-')
os.environ['CFG_DIR'] = os.path.join(TMP, 'config')
os.environ['DIST_DIR'] = os.path.join(TMP, 'dist')

import server  # noqa: E402

STAND_IN_BUILD = r'''
import os, sys, time
dist = os.environ['DIST_DIR']
os.makedirs(dist, exist_ok=True)
if os.environ.get('SHELF_OFFLINE') == '1':
    page = 'quick page'
else:
    release = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'release')
    deadline = time.time() + 30
    while not os.path.exists(release) and time.time() < deadline:
        time.sleep(0.05)
    page = 'full page'
open(os.path.join(dist, 'index.html'), 'w').write(page)
'''


class BootOrderTests(unittest.TestCase):

    def setUp(self):
        self.pipeline = os.path.join(TMP, 'pipeline')
        os.makedirs(os.path.join(self.pipeline, 'data'), exist_ok=True)
        with open(os.path.join(self.pipeline, 'build.py'), 'w') as f:
            f.write(STAND_IN_BUILD)
        # a volume with saved months: the boot rebuilds from them
        with open(os.path.join(self.pipeline, 'data', 'month-2026-10.json'), 'w') as f:
            f.write('{"books": [{"title": "Onyx Storm", "author": "Rebecca Yarros"}]}')
        self.release = os.path.join(self.pipeline, 'release')
        if os.path.exists(self.release):
            os.remove(self.release)
        self._old = (server.PIPELINE, server.DIST)
        server.PIPELINE = self.pipeline
        server.DIST = os.environ['DIST_DIR']

    def tearDown(self):
        server.PIPELINE, server.DIST = self._old
        open(self.release, 'w').close()  # never leave a stand-in build waiting

    def _get(self, srv):
        url = 'http://127.0.0.1:%d/' % srv.server_address[1]
        return urllib.request.urlopen(url, timeout=5).read().decode()

    def test_port_serves_the_quick_page_while_the_full_build_runs(self):
        srv, full = server.boot(port=0, host='127.0.0.1')
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertTrue(full.is_alive(), 'the full build must still be running')
            self.assertEqual(self._get(srv), 'quick page')
            open(self.release, 'w').close()
            full.join(30)
            self.assertFalse(full.is_alive())
            self.assertEqual(self._get(srv), 'full page')
        finally:
            srv.shutdown()
            srv.server_close()

    def test_a_run_build_waits_for_the_boot_full_build(self):
        """A curate-now run reaching build.py during the boot full build must
        not write the page beside it: both take the one build lock."""
        srv, full = server.boot(port=0, host='127.0.0.1')
        try:
            self.assertTrue(full.is_alive())
            self.assertFalse(server.BUILD_LOCK.acquire(blocking=False))
            open(self.release, 'w').close()
            full.join(30)
            self.assertTrue(server.BUILD_LOCK.acquire(timeout=5))
            server.BUILD_LOCK.release()
        finally:
            srv.server_close()


if __name__ == '__main__':
    unittest.main()
