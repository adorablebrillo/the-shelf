#!/usr/bin/env python3
"""Goodreads import (ticket #93) — the server contract behind the Settings
Import tab: POST /api/import/goodreads previews, then imports.

Run: cd container && python3 -m unittest test_import

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume. The
fixture (pipeline/testdata/goodreads-export.csv) keeps Goodreads' real header
row and quoting, with public book rows; no reader's data.
"""
import os
import tempfile
import unittest
from datetime import datetime

TMP = tempfile.mkdtemp(prefix='shelf-import-test-')
os.environ['CFG_DIR'] = TMP

import server  # noqa: E402

CSV = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'pipeline', 'testdata', 'goodreads-export.csv'), encoding='utf-8').read()
KEY = server._pipeline_import('bookids').book_key
FOURTH = KEY('Fourth Wing', 'Rebecca Yarros')
IRON = KEY('Iron Flame', 'Rebecca Yarros')
ONYX = KEY('Onyx Storm', 'Rebecca Yarros')
ICE = KEY('Icebreaker', 'Hannah Grace')
TWISTED = KEY('Twisted Love', 'Ana Huang')
LOVERS = KEY('Book Lovers', 'Emily Henry')
ACOTAR = KEY('A Court of Thorns and Roses', 'Sarah J. Maas')
HAPPY = KEY('Happy Place', 'Emily Henry')
POWER = KEY('Powerless', 'Lauren Roberts')


def ms(y, m, d):
    return int(datetime(y, m, d, 12).timestamp() * 1000)


class ImportTests(unittest.TestCase):
    def setUp(self):
        for p in (server.STATE, server.ADDED):
            if os.path.exists(p):
                os.remove(p)

    def states(self):
        return server.load_state()['states']

    def test_preview_counts_each_verdict_and_writes_nothing(self):
        res, err = server.import_goodreads(CSV, dry=True)
        self.assertIsNone(err)
        self.assertEqual(res['counts'], {'loved': 2, 'read': 3, 'want': 2, 'skip': 1})
        self.assertEqual((res['total'], res['reading'], res['already']), (8, 1, 0))
        self.assertEqual(res['left_out'], 1)
        self.assertEqual(res['left_why'], [{'why': 'on the shelf “owned”', 'n': 1}])
        # read 2 books, or gave one 4 or 5 stars: ticked first
        self.assertEqual([(g['name'], g['read'], g['ticked']) for g in res['series']],
                         [('The Empyrean', 2, True), ('The Powerless Trilogy', 1, True),
                          ('Maple Hills', 1, False)])
        self.assertFalse(os.path.exists(server.STATE))
        self.assertFalse(os.path.exists(server.ADDED))

    def test_import_marks_each_book_with_its_goodreads_date(self):
        res, err = server.import_goodreads(CSV, dry=False, track=['The Empyrean', 'The Powerless Trilogy'])
        self.assertIsNone(err)
        self.assertEqual(res['imported'], 8)
        st = self.states()
        self.assertEqual(st[FOURTH], {'s': 'loved', 't': ms(2024, 3, 10)})   # 5 stars, Date Read
        self.assertEqual(st[IRON], {'s': 'read', 't': ms(2024, 5, 2)})       # 4 stars is read
        self.assertEqual(st[ICE], {'s': 'read', 't': ms(2023, 8, 14)})       # no Date Read: Date Added
        self.assertEqual(st[LOVERS]['s'], 'loved')
        self.assertEqual(st[TWISTED], {'s': 'want', 't': ms(2024, 6, 30)})
        self.assertEqual(st[ONYX]['s'], 'want')
        self.assertEqual(st[ACOTAR]['s'], 'skip')                            # did-not-finish
        self.assertNotIn(HAPPY, st)                                          # another shelf: left out
        self.assertEqual(server.load_state()['reading'], {ONYX: {'s': True, 't': ms(2025, 1, 21)}})
        added = server.load_added()
        byid = {b['id']: b for b in added['books']}
        self.assertEqual(len(byid), 8)
        self.assertEqual((byid[FOURTH]['title'], byid[FOURTH]['series'], byid[FOURTH]['series_num']),
                         ('Fourth Wing', 'The Empyrean', '1'))
        self.assertEqual(byid[FOURTH]['isbn13'], '9781649374042')
        self.assertEqual(byid[LOVERS]['series'], '')
        self.assertEqual(added['untracked'], ['Maple Hills'])

    def test_a_second_import_changes_nothing(self):
        server.import_goodreads(CSV, dry=False)
        before = (server.load_state()['states'], server.load_added()['books'])
        preview, _ = server.import_goodreads(CSV, dry=True)
        self.assertEqual((preview['total'], preview['already']), (0, 8))
        res, _ = server.import_goodreads(CSV, dry=False)
        self.assertEqual(res['imported'], 0)
        self.assertEqual((server.load_state()['states'], server.load_added()['books']),
                         before)

    def test_a_mark_made_in_the_app_wins(self):
        server.save_state({'states': {FOURTH: {'s': 'skip', 't': 5},       # set aside in the app
                                      TWISTED: {'s': None, 't': 6}}})      # marked, then cleared
        res, _ = server.import_goodreads(CSV, dry=False)
        self.assertEqual(res['already'], 2)
        st = self.states()
        self.assertEqual(st[FOURTH], {'s': 'skip', 't': 5})
        self.assertEqual(st[TWISTED], {'s': None, 't': 6})
        self.assertEqual(st[IRON]['s'], 'read')

    def test_a_later_tick_takes_a_series_off_the_untracked_list(self):
        server.import_goodreads(CSV, dry=False, track=[])
        self.assertEqual(server.load_added()['untracked'],
                         ['Maple Hills', 'The Empyrean', 'The Powerless Trilogy'])
        server.save_state({'states': {}})
        server.import_goodreads(CSV, dry=False, track=['Maple Hills', 'The Empyrean', 'The Powerless Trilogy'])
        self.assertEqual(server.load_added()['untracked'], [])

    def test_a_file_that_is_not_a_goodreads_export_is_refused(self):
        res, err = server.import_goodreads('title,author\nFourth Wing,Rebecca Yarros\n', dry=True)
        self.assertIsNone(res)
        self.assertIn('not a Goodreads export file', err)


if __name__ == '__main__':
    unittest.main()
