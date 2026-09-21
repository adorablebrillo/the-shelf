#!/usr/bin/env python3
"""Author watches feed the engine (ticket #9).

Run: cd pipeline && python3 -m unittest test_watches

Covers the three seams: the Apple page's series extraction (fetch), the
watched-marking in the author lane, and the candidates -> tracked-series merge
that gives the radar lane its countdown.
"""
import json
import os
import re
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ['CFG_DIR'] = tempfile.mkdtemp(prefix='shelf-watches-')

import fetch  # noqa: E402
import build  # noqa: E402
import filter as filt  # noqa: E402


PAGE_WITH_SERIES = '''<html><script type="application/ld+json">
{"@type":"Book","name":"Onyx Storm","isPartof":{"@type":"BookSeries","name":"The Empyrean"},
 "offers":{"@type":"Offer","price":14.99}}
</script><a href="/us/book-series/the-empyrean/id1669865976">Book 3 - The Empyrean</a></html>'''
PAGE_STANDALONE = '<html>{"@type":"Book","name":"A Standalone"}</html>'


class PageSeriesTests(unittest.TestCase):
    def test_series_and_number_from_the_page(self):
        got = fetch.page_series(PAGE_WITH_SERIES)
        self.assertEqual(got['series'], 'The Empyrean')
        self.assertEqual(got['num'], '3')

    def test_standalone_has_no_series(self):
        self.assertEqual(fetch.page_series(PAGE_STANDALONE), {'series': '', 'num': ''})


class WatchedMarkingTests(unittest.TestCase):
    def setUp(self):
        cfg = os.environ['CFG_DIR']
        with open(os.path.join(cfg, 'authors.json'), 'w') as f:
            json.dump({'authors': [{'name': 'Watched Writer', 'lane': 'romantasy'}]}, f)

    def test_watched_author_is_queried_and_marked(self):
        lane = fetch.author_lane()
        hit = [a for a in lane if a['name'] == 'Watched Writer']
        self.assertEqual(len(hit), 1)
        self.assertIn('watched', hit[0]['why'])
        self.assertEqual(hit[0]['lane'], 'romantasy')


class AuthorUpcomingTests(unittest.TestCase):
    def setUp(self):
        self.today = '2026-09-21'
        self.tracked = {build.norm_name('The Empyrean'): {'series': 'The Empyrean', 'author': 'Rebecca Yarros'}}
        self.dir = tempfile.mkdtemp(prefix='shelf-cands-')

    def write(self, books):
        p = os.path.join(self.dir, 'candidates-2026-09.json')
        json.dump({'books': books}, open(p, 'w'))
        return p

    def test_upcoming_in_a_tracked_series_becomes_next(self):
        p = self.write([
            {'title': 'Some Future Book', 'author': 'Rebecca Yarros', 'series': 'The Empyrean',
             'series_num': '4', 'date': '2026-11-03', 'publisher': 'Red Tower'},
        ])
        got = build.author_upcoming(self.tracked, self.today, path=p)
        entry = got[build.norm_name('The Empyrean')][0]
        self.assertEqual(entry['title'], 'Some Future Book (#4)')
        self.assertEqual(entry['release_date'], '2026-11-03')
        self.assertEqual(entry['status'], 'soon')

    def test_released_book_is_never_radar(self):
        p = self.write([{'title': 'Out Already', 'series': 'The Empyrean', 'date': '2026-09-01'}])
        self.assertEqual(build.author_upcoming(self.tracked, self.today, path=p), {})

    def test_standalone_and_untracked_are_skipped(self):
        p = self.write([
            {'title': 'No Series', 'date': '2026-11-01'},
            {'title': 'Other Series Book', 'series': 'Some Other Cycle', 'date': '2026-11-01'},
        ])
        self.assertEqual(build.author_upcoming(self.tracked, self.today, path=p), {})

    def test_missing_file_is_quiet(self):
        self.assertEqual(build.author_upcoming(self.tracked, self.today, path='/nonexistent.json'), {})


class SeriesMergeTests(unittest.TestCase):
    """series_data() with a stubbed author_upcoming: the entry lands in the
    series' books as an upcoming volume (countdown), deduped against what the
    sequels map already knows."""

    def setUp(self):
        self.cfg = os.environ['CFG_DIR']
        json.dump({'series': [{'name': 'The Empyrean', 'author': 'Rebecca Yarros', 'books': ['Fourth Wing']}]},
                  open(os.path.join(self.cfg, 'library.json'), 'w'))
        json.dump({'series': [{'series': 'The Empyrean', 'author': 'Rebecca Yarros',
                               'next_books': [{'title': 'Known Book (#2)', 'release_date': '2026-12-01'}]}]},
                  open(os.path.join(self.cfg, 'sequels.json'), 'w'))
        self._orig = build.author_upcoming

    def tearDown(self):
        build.author_upcoming = self._orig

    def test_upcoming_merges_with_countdown_and_dedupes(self):
        build.author_upcoming = lambda tracked, today, path=None: {
            build.norm_name('The Empyrean'): [
                {'title': 'Fresh Book (#3)', 'release_date': '2026-11-03', 'status': 'soon', 'publisher': ''},
                {'title': 'Known Book (#2)', 'release_date': '2026-12-01', 'status': 'soon', 'publisher': ''},
            ]}
        series = build.series_data()
        emp = [s for s in series if s['name'] == 'The Empyrean'][0]
        titles = [b['t'] for b in emp['books']]
        self.assertIn('Fresh Book', titles)          # merged
        self.assertEqual(titles.count('Known Book'), 1)  # deduped
        fresh = [b for b in emp['books'] if b['t'] == 'Fresh Book'][0]
        self.assertEqual(fresh['state'], 'soon')
        self.assertTrue(fresh['d'])                  # the countdown label exists


class FutureNeverPicksTests(unittest.TestCase):
    def test_future_dated_candidates_never_pass_the_window(self):
        fut = (date.today() + timedelta(days=30)).isoformat()
        self.assertFalse(filt.adhoc_window_ok(fut))
        mon = date.today().strftime('%Y-%m')
        self.assertFalse(filt.in_window(fut, mon))


if __name__ == '__main__':
    unittest.main()
