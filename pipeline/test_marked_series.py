#!/usr/bin/env python3
"""A read or loved pick starts tracking its series (the "Do first" plan, piece 2).

The reader state, month files, candidates files and series files are real
files in a scratch config volume and data folder, shaped like the ones the
server and the pipeline write. The model call is curate's own seam.
Run from pipeline/:  python3 -m unittest test_marked_series -v
"""
import json, os, shutil, tempfile, unittest
from datetime import date, timedelta

import build
import curate
import fetch
import sequels
from bookids import book_key


def write(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f)


EMBER = book_key('Ember Vow', 'K. Hale')
STONE = book_key('Stone Heart', 'R. Vale')
POWER = book_key('Power Play', 'J. Marsh')
DUST = book_key('Dust Trail', 'T. Reed')
IRON = book_key('Iron Storm', 'M. Stone')


class MarkedSeriesTests(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp(prefix='shelf-marked-cfg-')
        self.root = tempfile.mkdtemp(prefix='shelf-marked-root-')
        self.data = os.path.join(self.root, 'data')
        os.makedirs(self.data)
        self._env = os.environ.get('CFG_DIR')
        os.environ['CFG_DIR'] = self.cfg
        # an issue's picks as curate now writes them: series copied from the candidate
        write(os.path.join(self.data, 'month-2026-10.json'), {'books': [
            {'title': 'Ember Vow', 'author': 'K. Hale', 'genre': 'Romantasy',
             'series': 'Mist Court', 'series_num': '1'},
            {'title': 'Power Play', 'author': 'J. Marsh', 'genre': 'Hockey',
             'series': 'Boston Blades', 'series_num': '2'},
            {'title': 'Dust Trail', 'author': 'T. Reed', 'genre': 'Small town',
             'series': 'Dry Creek', 'series_num': '1'},
            {'title': 'Iron Storm', 'author': 'M. Stone', 'genre': 'Romantasy',
             'series': 'Iron Wings', 'series_num': '2'},
        ]})
        # an older issue, written before curate kept the series
        write(os.path.join(self.data, 'month-2026-08.json'), {'books': [
            {'title': 'Stone Heart', 'author': 'R. Vale', 'genre': 'Contemporary Romance'}]})
        write(os.path.join(self.data, 'candidates-2026-08.json'), {'books': [
            {'title': 'Stone Heart', 'author': 'R. Vale', 'series': 'Harbor Lights',
             'series_num': '1', 'date': '2026-08-12'}]})
        write(os.path.join(self.cfg, 'library.json'), {'series': [
            {'name': 'Iron Wings', 'author': 'M. Stone', 'books': ['Iron Wings']}]})
        write(os.path.join(self.cfg, 'sequels.json'), {'series': []})
        self._orig_base = build.BASE
        self._orig_data = sequels.DATA_DIR
        self._orig_lookup = build.lookup_cover_url

    def tearDown(self):
        build.BASE = self._orig_base
        sequels.DATA_DIR = self._orig_data
        build.lookup_cover_url = self._orig_lookup
        shutil.rmtree(self.cfg)
        shutil.rmtree(self.root)
        if self._env is None:
            os.environ.pop('CFG_DIR', None)
        else:
            os.environ['CFG_DIR'] = self._env

    def mark(self, states):
        write(os.path.join(self.cfg, 'reader-state.json'), {'states': states})

    def names(self):
        return [g['series'] for g in sequels.from_marks(self.data, self.cfg)]

    def test_read_or_loved_tracks_want_and_not_for_me_do_not(self):
        self.mark({EMBER: {'s': 'loved', 't': 3}, STONE: {'s': 'read', 't': 4},
                   POWER: {'s': 'want', 't': 2}, DUST: {'s': 'skip', 't': 1}})
        marked = sequels.from_marks(self.data, self.cfg)
        self.assertEqual([g['series'] for g in marked], ['Harbor Lights', 'Mist Court'])
        mist = marked[1]
        self.assertEqual(mist['author'], 'K. Hale')
        self.assertEqual(mist['books'], [{'title': 'Ember Vow', 'num': '1', 'id': EMBER}])
        self.assertEqual(sequels.report_line(marked),
                         'series: 2 tracked from your marks (Harbor Lights, Mist Court)')

    def test_older_month_file_falls_back_to_the_candidates_series(self):
        self.mark({STONE: {'s': 'read', 't': 1}})
        marked = sequels.from_marks(self.data, self.cfg)
        self.assertEqual(marked[0]['series'], 'Harbor Lights')
        self.assertEqual(marked[0]['books'][0]['num'], '1')

    def test_cleared_mark_stops_tracking(self):
        self.mark({EMBER: {'s': 'loved', 't': 3}})
        self.assertEqual(self.names(), ['Mist Court'])
        self.mark({EMBER: {'s': None, 't': 5}})
        self.assertEqual(self.names(), [])
        self.assertEqual(sequels.report_line([]), 'series: 0 tracked from your marks')

    def test_series_left_unticked_on_the_goodreads_import_is_not_tracked(self):
        # the import (#93) writes the series she left unticked beside the added books
        write(os.path.join(self.cfg, 'added-books.json'), {'v': 1, 'books': [], 'untracked': ['Mist Court']})
        self.mark({EMBER: {'s': 'loved', 't': 3}, STONE: {'s': 'read', 't': 4}})
        self.assertEqual(self.names(), ['Harbor Lights'])
        names = sequels.tracked_series(self.data, self.cfg)
        self.assertFalse(sequels.is_sequel({'title': 'Ember Crown', 'series': 'Mist Court'}, names))

    def test_series_already_in_the_library_is_not_doubled(self):
        self.mark({IRON: {'s': 'loved', 't': 1}})
        self.assertEqual(self.names(), [])

    def test_a_later_candidate_in_that_series_is_a_guaranteed_sequel(self):
        self.mark({EMBER: {'s': 'read', 't': 1}})
        logged = []
        names = sequels.tracked_series(self.data, self.cfg, log=logged.append)
        self.assertTrue(sequels.is_sequel({'title': 'Ember Crown', 'series': 'Mist Court'}, names))
        self.assertTrue(sequels.is_sequel({'series': 'Iron Wings'}, names))   # the library still counts
        self.assertFalse(sequels.is_sequel({'series': 'Dry Creek'}, names))   # not for me tracks nothing
        self.assertEqual(logged, ['series: 1 tracked from your marks (Mist Court)'])

    def test_author_lane_searches_the_marked_series_author(self):
        self.mark({EMBER: {'s': 'loved', 't': 1}})
        sequels.DATA_DIR = self.data
        self.assertIn('K. Hale', [a['name'] for a in fetch.author_lane()])
        self.mark({})
        self.assertNotIn('K. Hale', [a['name'] for a in fetch.author_lane()])

    def series_page(self):
        build.BASE = self.root
        build.lookup_cover_url = lambda title, author: ''   # hermetic: no live cover lookups
        series = build.series_data(covers_dir=tempfile.mkdtemp(prefix='shelf-covers-', dir=self.root))
        return [s for s in series if s['name'] == 'Mist Court']

    def test_series_page_lists_a_marked_series_once_a_next_book_is_known(self):
        self.mark({EMBER: {'s': 'loved', 't': 1}})
        self.assertEqual(self.series_page(), [])   # no next book known yet
        soon = (date.today() + timedelta(days=40)).isoformat()
        write(os.path.join(self.data, 'candidates-2026-11.json'), {'books': [
            {'title': 'Ember Crown', 'author': 'K. Hale', 'series': 'Mist Court', 'series_num': '2',
             'date': soon, 'found_by': ['author:K. Hale']}]})
        mist = self.series_page()
        self.assertEqual(len(mist), 1)
        self.assertEqual(mist[0]['author'], 'K. Hale')
        self.assertEqual([(b['t'], b['n'], b['state']) for b in mist[0]['books']],
                         [('Ember Vow', '#1', 'read'), ('Ember Crown', '#2', 'soon')])
        self.assertEqual(mist[0]['books'][0]['id'], EMBER)   # the app's mark lands on the same book

    def test_curate_copies_the_candidate_series_onto_model_picks(self):
        end = curate.window_end(curate.MODE)
        d = (end - timedelta(days=5)).isoformat()
        cands = [{'title': '%s %d' % (g, i), 'author': 'A. Author', 'genre': g, 'date': d, 'trad': True}
                 for g in ('Hockey', 'Romantasy', 'Small town') for i in range(3)]
        cands[3].update({'series': 'Mist Court', 'series_num': '1'})

        def fake(key, payload, taste):
            # the output schema has no series field: the model leaves it out
            return {'books': [{k: v for k, v in c.items() if not k.startswith('series')} for c in cands]}

        cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-10', 'rule',
                            call=fake, log=lambda *a: None)
        pick = [b for b in cur['books'] if b['title'] == 'Romantasy 0'][0]
        self.assertEqual((pick['series'], pick['series_num']), ('Mist Court', '1'))
        self.assertEqual(build.pick_book(pick, None, '')['series'], 'Mist Court #1')
        self.assertNotIn('series', [b for b in cur['books'] if b['title'] == 'Hockey 0'][0])


if __name__ == '__main__':
    unittest.main()
