#!/usr/bin/env python3
"""Her verdicts teach the model (#83).

The model call is injected (curate's own seam); the reader state, month file
and series files are real files in a scratch config volume, shaped like the
ones the server and the pipeline write.
Run from pipeline/:  python3 -m unittest test_verdicts -v
"""
import json, os, shutil, tempfile, unittest
from datetime import timedelta
import curate
import verdicts
from bookids import book_key
from build import pick_book


def write(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f)


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self.data = tempfile.mkdtemp()
        self._env = os.environ.get('CFG_DIR')
        os.environ['CFG_DIR'] = self.cfg
        # a past issue's picks, as curate writes them
        write(os.path.join(self.data, 'month-2026-09.json'), {'books': [
            {'id': 'ash-crown', 'title': 'Ash Crown', 'author': 'K. Hale', 'genre': 'Romantasy',
             'series': 'Mist Court #0', 'tropes': ['enemies to lovers', 'fae bargain']},
            {'id': 'power-play', 'title': 'Power Play', 'author': 'J. Marsh', 'genre': 'Hockey',
             'tropes': ['forbidden']},
            {'id': 'dust-trail', 'title': 'Dust Trail', 'author': 'T. Reed', 'genre': 'Small town',
             'tropes': ['cowboy']},
        ]})
        write(os.path.join(self.cfg, 'library.json'), {'series': [
            {'name': 'Iron Wings', 'author': 'M. Stone', 'books': ['Iron Wings', 'Iron Storm']}]})
        write(os.path.join(self.cfg, 'sequels.json'), {'series': [
            {'series': 'Glass Throne', 'author': 'P. Lane',
             'next_books': [{'title': 'Glass Heir', 'date': '2026-12-01'}]}]})

    def tearDown(self):
        shutil.rmtree(self.cfg)
        shutil.rmtree(self.data)
        if self._env is None:
            os.environ.pop('CFG_DIR', None)
        else:
            os.environ['CFG_DIR'] = self._env

    def mark(self, states):
        write(os.path.join(self.cfg, 'reader-state.json'), {'states': states})

    def lists(self):
        return verdicts.her_verdicts(verdicts.load_marks(self.cfg),
                                     verdicts.book_details(self.data))

    def test_lookup_resolves_ids_from_month_file_and_series_files(self):
        d = verdicts.book_details(self.data)
        ash = d[book_key('Ash Crown', 'K. Hale')]
        self.assertEqual((ash['title'], ash['lane'], ash['tropes'], ash['series']),
                         ('Ash Crown', 'romantasy', ['enemies to lovers', 'fae bargain'], 'Mist Court #0'))
        self.assertEqual(d[book_key('Iron Storm', 'M. Stone')]['series'], 'Iron Wings')
        self.assertEqual(d[book_key('Glass Heir', 'P. Lane')]['author'], 'P. Lane')

    def test_lists_are_newest_first_capped_and_count_unknown_marks(self):
        states = {book_key('Ash Crown', 'K. Hale'): {'s': 'loved', 't': 300},
                  book_key('Iron Wings', 'M. Stone'): {'s': 'loved', 't': 500},
                  book_key('Power Play', 'J. Marsh'): {'s': 'want', 't': 200},
                  book_key('Dust Trail', 'T. Reed'): {'s': 'skip', 't': 100},
                  book_key('Iron Storm', 'M. Stone'): {'s': 'read', 't': 400},   # read teaches nothing
                  book_key('Glass Heir', 'P. Lane'): {'s': None, 't': 600},      # cleared mark
                  'gone-book--nobody': {'s': 'loved', 't': 700}}                  # no details anywhere
        self.mark(states)
        lists, missing = self.lists()
        self.assertEqual([b['title'] for b in lists['loved']], ['Iron Wings', 'Ash Crown'])
        self.assertEqual([b['title'] for b in lists['want']], ['Power Play'])
        self.assertEqual([b['title'] for b in lists['not_for_me']], ['Dust Trail'])
        self.assertEqual(missing, 1)
        self.assertEqual(verdicts.report_line(lists, missing),
                         'verdicts: sent 2 loved · 1 want · 1 not for me to the model '
                         '(1 marks had no book details)')
        capped, _ = verdicts.her_verdicts(verdicts.load_marks(self.cfg), verdicts.book_details(self.data),
                                          caps={'loved': 1, 'want': 15, 'not_for_me': 25})
        self.assertEqual([b['title'] for b in capped['loved']], ['Iron Wings'])

    def test_blank_shelf_reports_zeros(self):
        lists, missing = self.lists()
        self.assertEqual(verdicts.report_line(lists, missing),
                         'verdicts: sent 0 loved · 0 want · 0 not for me to the model '
                         '(0 marks had no book details)')

    def run_curate(self, lists, because):
        end = curate.window_end(curate.MODE)
        d = (end - timedelta(days=5)).isoformat()
        cands = [{'title': '%s %d' % (g, i), 'author': 'A. Author', 'genre': g, 'date': d, 'trad': True}
                 for g in ('Hockey', 'Romantasy', 'Small town') for i in range(3)]
        out = [dict(c) for c in cands]
        for b, name in zip(out, because):
            if name is not None:
                b['because'] = name
        calls = []

        def fake(key, payload, taste):
            calls.append(json.loads(payload))
            return {'books': [dict(b) for b in out]}

        cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-10', 'rule',
                            call=fake, log=lambda *a: None, her_verdicts=lists)
        return cur, calls

    def test_request_carries_her_verdicts_and_because_is_kept_only_for_loved_or_want(self):
        self.mark({book_key('Ash Crown', 'K. Hale'): {'s': 'loved', 't': 3},
                   book_key('Power Play', 'J. Marsh'): {'s': 'want', 't': 2},
                   book_key('Dust Trail', 'T. Reed'): {'s': 'skip', 't': 1}})
        lists, _ = self.lists()
        cur, calls = self.run_curate(lists, ['ash crown', 'Power Play', 'Dust Trail', 'Some Unmarked Book', None])
        sent = calls[0]['her_verdicts']
        self.assertEqual({k: [b['title'] for b in v] for k, v in sent.items()},
                         {'loved': ['Ash Crown'], 'want': ['Power Play'], 'not_for_me': ['Dust Trail']})
        got = [b.get('because') for b in cur['books'][:5]]
        self.assertEqual(got, [{'title': 'Ash Crown', 'verdict': 'loved'},
                               {'title': 'Power Play', 'verdict': 'want'}, None, None, None])
        cards = [pick_book(b, None, '')['because'] for b in cur['books'][:3]]
        self.assertEqual(cards, ['because you loved Ash Crown', 'because you wanted Power Play', ''])


if __name__ == '__main__':
    unittest.main()
