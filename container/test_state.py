#!/usr/bin/env python3
"""The reader state — the server contract behind /api/state, including ticket
#57's reading channel (a reading flag travels beside the verdict marks, merged
by the same last-write-wins rule, and never touches 'states').

THS-43 (Home part 2) adds the reading-day channel: per book, the days she
tapped "I read today", merged by UNION so the phone's days and the desktop's
days both count, and never readable as a verdict.

Run: cd container && python3 -m unittest test_state

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix='shelf-state-test-')
os.environ['CFG_DIR'] = TMP

import server  # noqa: E402


class MergeStatesTests(unittest.TestCase):
    """The verdict merge — the original contract, pinned so #57's channel reuse
    cannot drift it."""

    def test_newer_wins(self):
        out = server.merge_states({'a': {'s': 'read', 't': 5}}, {'a': {'s': 'loved', 't': 9}})
        self.assertEqual(out['a'], {'s': 'loved', 't': 9})

    def test_older_loses(self):
        out = server.merge_states({'a': {'s': 'read', 't': 9}}, {'a': {'s': 'loved', 't': 5}})
        self.assertEqual(out['a'], {'s': 'read', 't': 9})

    def test_tombstone_travels(self):
        out = server.merge_states({'a': {'s': 'read', 't': 5}}, {'a': {'s': None, 't': 9}})
        self.assertIsNone(out['a']['s'])
        self.assertEqual(out['a']['t'], 9)

    def test_phone_and_desktop_marks_both_survive(self):
        out = server.merge_states({'a': {'s': 'read', 't': 5}}, {'b': {'s': 'want', 't': 6}})
        self.assertEqual(out['a']['s'], 'read')
        self.assertEqual(out['b']['s'], 'want')


class ReadingChannelTests(unittest.TestCase):
    """#57: reading flags ride the same merge but their own map — a reading
    flag must never be readable as a verdict by the pipeline."""

    def test_flag_and_clear_travel_like_marks(self):
        out = server.merge_states({}, {'x': {'s': True, 't': 10}})
        self.assertEqual(out['x'], {'s': True, 't': 10})
        out = server.merge_states(out, {'x': {'s': False, 't': 20}})
        self.assertEqual(out['x'], {'s': False, 't': 20})
        # an older re-flag cannot beat a newer clear (the phone and desktop
        # cannot clobber each other)
        out = server.merge_states(out, {'x': {'s': True, 't': 15}})
        self.assertEqual(out['x'], {'s': False, 't': 20})

    def test_reading_never_leaks_into_states(self):
        states = server.merge_states({'a': {'s': 'read', 't': 5}}, {})
        reading = server.merge_states({}, {'a': {'s': True, 't': 6}})
        self.assertEqual(states['a']['s'], 'read')
        self.assertEqual(reading['a']['s'], True)
        # the pipeline reads only skip/read/loved from states; True is not one
        # of them, so a flag can never hide a book from the app or the engine
        self.assertNotIn(reading['a']['s'], ('skip', 'read', 'loved'))


class ConcurrentSaveTests(unittest.TestCase):
    """A verdict now fires two posts at once (states + reading) and the phone
    can post while the desktop posts. Concurrent saves must never corrupt the
    file — found in the #57 folds: a shared .tmp name interleaved two writes."""

    def test_parallel_saves_stay_parseable(self):
        import threading
        errs = []

        def w(i):
            try:
                for j in range(25):
                    server.save_state({'states': {'b%d' % i: {'s': 'want', 't': i * 100 + j}},
                                       'reading': {'b%d' % i: {'s': True, 't': i * 100 + j}}})
            except Exception as e:  # pragma: no cover - failure path
                errs.append(e)

        ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        raw = open(server.STATE).read()
        d = json.loads(raw)          # one whole document, no interleaved tail
        self.assertIn('states', d)
        self.assertIn('reading', d)
        self.assertEqual(server.load_state()['v'], 2)


class ReadingDayMergeTests(unittest.TestCase):
    """THS-43 (Home part 2): the reading-day merge, on its own."""

    def test_days_from_two_devices_both_survive(self):
        phone = {'cold-snap': ['2026-11-17']}
        desk = {'cold-snap': ['2026-11-18'], 'power-play': ['2026-11-18']}
        out, dropped = server.merge_days(phone, desk)
        self.assertEqual(out, {'cold-snap': ['2026-11-17', '2026-11-18'],
                               'power-play': ['2026-11-18']})
        self.assertEqual(dropped, 0)

    def test_the_union_is_order_free_and_never_repeats_a_day(self):
        a, _ = server.merge_days({}, {'b1': ['2026-11-01', '2026-11-03']})
        b, _ = server.merge_days(a, {'b1': ['2026-11-02']})
        c, _ = server.merge_days(b, {'b1': ['2026-11-01']})
        self.assertEqual(c['b1'], ['2026-11-01', '2026-11-02', '2026-11-03'])

    def test_a_value_that_is_not_a_date_is_dropped_and_counted(self):
        out, dropped = server.merge_days({}, {'b1': ['2026-11-18', 'today', '2026-13-45', None],
                                              'b2': 'not a list', '': ['2026-11-18']})
        self.assertEqual(out, {'b1': ['2026-11-18']})
        self.assertEqual(dropped, 5)   # three words, one value that is not a list, one book with no name

    def test_a_reading_day_is_never_a_verdict(self):
        # the pipeline reads 'states' for verdicts; a day must not reach it
        states = server.merge_states({'b1': {'s': 'read', 't': 5}}, {})
        days, _ = server.merge_days({}, {'b1': ['2026-11-18']})
        self.assertEqual(states['b1']['s'], 'read')
        self.assertNotIn('2026-11-18', str(states))
        self.assertEqual(days['b1'], ['2026-11-18'])


class ReadingDayApiTests(unittest.TestCase):
    """The contract a phone and a desktop actually use: POST /api/state with a
    days channel, GET /api/state reading the merged copy back, and the same
    merged copy written to the volume."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = 'http://127.0.0.1:%d/api/state' % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        if os.path.exists(server.STATE):
            os.remove(server.STATE)

    def _post(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())

    def _get(self):
        return json.loads(urllib.request.urlopen(self.url, timeout=5).read().decode())

    def test_days_logged_on_two_devices_are_both_kept_and_come_back(self):
        self._post({'days': {'cold-snap--tessa-rhine': ['2026-11-17']}})
        j = self._post({'days': {'cold-snap--tessa-rhine': ['2026-11-18'],
                                 'power-play--tessa-rhine': ['2026-11-18']}})
        self.assertEqual(j['days']['cold-snap--tessa-rhine'], ['2026-11-17', '2026-11-18'])
        self.assertEqual(self._get()['days']['power-play--tessa-rhine'], ['2026-11-18'])
        on_disk = json.load(open(server.STATE))['days']
        self.assertEqual(on_disk['cold-snap--tessa-rhine'], ['2026-11-17', '2026-11-18'])

    def test_a_verdict_post_leaves_the_days_it_did_not_send_untouched(self):
        self._post({'days': {'b1': ['2026-11-17']}})
        j = self._post({'states': {'b1': {'s': 'read', 't': 99}}})
        self.assertEqual(j['days']['b1'], ['2026-11-17'])
        self.assertEqual(j['states']['b1']['s'], 'read')

    def test_a_state_without_days_answers_an_empty_days_map(self):
        self.assertEqual(self._get()['days'], {})


class KeptStampTests(unittest.TestCase):
    """THS-43 (Home part 2): the stamps she keeps travel like marks, on keys
    that name a stamp and nothing else."""

    def test_two_devices_stamps_both_stay_kept(self):
        phone = {'season:christmas:2026': {'s': True, 't': 10}}
        desk = {'issue:2': {'s': True, 't': 11}}
        out, dropped = server.merge_stamps(phone, desk)
        self.assertEqual(sorted(out), ['issue:2', 'season:christmas:2026'])
        self.assertEqual(dropped, 0)

    def test_a_key_that_names_no_stamp_is_counted_and_left_out(self):
        out, dropped = server.merge_stamps({}, {'states': {'s': True, 't': 1},
                                                'season:notaseason:2026': {'s': True, 't': 2},
                                                'series:coldsnap': {'s': True, 't': 3}})
        self.assertEqual(list(out), ['series:coldsnap'])
        self.assertEqual(dropped, 2)

    def test_a_stamp_pressed_in_once_stays_pressed_in(self):
        out, _ = server.merge_stamps({'issue:2': {'s': True, 't': 20}}, {'issue:2': {'s': True, 't': 5}})
        self.assertEqual(out['issue:2'], {'s': True, 't': 20})


class KeptStampApiTests(unittest.TestCase):
    """The stamp channel over the contract the page uses."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = 'http://127.0.0.1:%d/api/state' % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        if os.path.exists(server.STATE):
            os.remove(server.STATE)

    def _post(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())

    def _get(self):
        return json.loads(urllib.request.urlopen(self.url, timeout=5).read().decode())

    def test_a_season_stamp_earned_on_one_device_shows_on_the_other(self):
        self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 11}}})
        j = self._post({'stamps': {'issue:2': {'s': True, 't': 12}}})
        self.assertEqual(sorted(j['stamps']), ['issue:2', 'season:christmas:2026'])
        self.assertEqual(json.load(open(server.STATE))['stamps']['season:christmas:2026']['s'], True)

    def test_a_state_without_stamps_answers_an_empty_stamp_map(self):
        self.assertEqual(self._get()['stamps'], {})
        self.assertEqual(self._get()['days'], {})


if __name__ == '__main__':
    unittest.main()
