#!/usr/bin/env python3
"""The Book-a-meter widget on Home (THS-35 piece 3) — the build ships her
interests to the page.

The widget reads interests.json (the Book-a-meter, THS-37 piece 1): label,
kind and dial per interest, in the file's order, so Home shows her meter.
A blank install (no interests.json) falls back to the three default romance
interests, each "into it" — the same doc the run reads.

Run: cd pipeline && python3 -m unittest test_home_meter

Each run is the real build.py in a throwaway copy of the pipeline, offline
(the same harness test_quick_build.py runs).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


def _last_month():
    t = date.today().replace(day=1)
    y, m = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return '%04d-%02d' % (y, m)


class MeterDataTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='shelf-meter-')
        self.pipe = os.path.join(self.tmp, 'pipeline')
        shutil.copytree(HERE, self.pipe, ignore=shutil.ignore_patterns(
            'data', 'dist', '__pycache__', 'test_*', 'testdata'))
        data = os.path.join(self.pipe, 'data')
        os.makedirs(os.path.join(data, 'covers'))
        self.ym = _last_month()
        books = [
            {'id': 'b1', 'title': 'Onyx Storm', 'author': 'Rebecca Yarros',
             'genre': 'romantasy', 'spice': 3},
        ]
        with open(os.path.join(data, 'month-%s.json' % self.ym), 'w') as f:
            json.dump({'books': books, 'top_pick': 'b1', 'mode': 'scheduled'}, f)
        self.cfg = os.path.join(self.tmp, 'config')
        os.makedirs(self.cfg)
        self.dist = os.path.join(self.tmp, 'dist')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self):
        env = dict(os.environ, CFG_DIR=self.cfg, DIST_DIR=self.dist,
                   SHELF_OFFLINE='1')
        env.pop('http_proxy', None), env.pop('https_proxy', None)
        r = subprocess.run([sys.executable, 'build.py'], cwd=self.pipe, env=env,
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout[-600:] + r.stderr[-600:])
        with open(os.path.join(self.dist, 'shelf-data.js')) as f:
            raw = f.read()
        return json.loads(raw[len('window.SHELF_DATA='):].rstrip().rstrip(';'))

    def test_the_build_ships_her_interests_to_the_page(self):
        # a made-up meter: one topic interest at "curious", one romance
        # interest at "obsessed", an off dial and a best-ever mode — the
        # widget must carry them all through, in the file's order
        with open(os.path.join(self.cfg, 'interests.json'), 'w') as f:
            json.dump({'v': 1, 'name': 'Book-a-meter', 'picks': 12, 'never': [],
                       'season_goal': None, 'interests': [
                           {'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                            'dial': 'curious', 'mode': 'new'},
                           {'id': 'sport', 'label': 'Sport romance', 'kind': 'story',
                            'dial': 'obsessed', 'romance': True, 'mode': 'new'},
                           {'id': 'fae', 'label': 'Fae courts', 'kind': 'story',
                            'dial': 'off', 'romance': True, 'mode': 'both'},
                       ]}, f)
        data = self._build()
        meter = data['meter']
        self.assertEqual(meter['name'], 'Book-a-meter')
        self.assertEqual([i['label'] for i in meter['interests']],
                         ['Baby development', 'Sport romance', 'Fae courts'])
        self.assertEqual(meter['interests'][0],
                         {'label': 'Baby development', 'kind': 'topic', 'dial': 'curious'})
        self.assertEqual(meter['interests'][1]['dial'], 'obsessed')
        self.assertEqual(meter['interests'][2]['dial'], 'off')

    def test_a_blank_install_ships_the_three_default_dials(self):
        # no interests.json on the volume: the same doc the run reads — the
        # three romance interests the shelf starts with, each "into it"
        data = self._build()
        meter = data['meter']
        self.assertEqual(meter['name'], 'Book-a-meter')
        self.assertEqual(meter['interests'], [
            {'label': 'Sport romance', 'kind': 'story', 'dial': 'into it'},
            {'label': 'Romantasy', 'kind': 'story', 'dial': 'into it'},
            {'label': 'Contemporary romance', 'kind': 'story', 'dial': 'into it'},
        ])


if __name__ == '__main__':
    unittest.main()
