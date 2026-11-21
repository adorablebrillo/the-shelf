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
from datetime import datetime, timezone
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


# noon (UTC) on 15 November 2026, inside Christmas 2026 (1 November to 6 January)
MID_CHRISTMAS_2026 = int(datetime(2026, 11, 15, 12, tzinfo=timezone.utc).timestamp() * 1000)


def utc_ms(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp() * 1000)


class SeasonBooksTests(unittest.TestCase):
    """The server's season count, which a season stamp must meet: the same
    days the page's ring counts, from her local day."""

    def test_a_season_that_wraps_the_new_year_counts_both_years(self):
        states = {'a': {'s': 'read', 't': utc_ms(2026, 11, 1, 12)},
                  'b': {'s': 'loved', 't': utc_ms(2027, 1, 6, 12)},
                  'c': {'s': 'read', 't': utc_ms(2026, 10, 31, 12)},   # autumn
                  'd': {'s': 'read', 't': utc_ms(2027, 1, 7, 12)},     # winter
                  'e': {'s': 'want', 't': utc_ms(2026, 11, 20, 12)},
                  'f': {'s': 'read'}}                                  # no time
        self.assertEqual(server.season_books(states, 'season:christmas:2026', 0), 2)
        self.assertEqual(server.season_books(states, 'season:christmas:2025', 0), 0)

    def test_her_local_day_decides_the_season(self):
        """23:30 UTC on 31 October is 00:30 on 1 November in Madrid."""
        states = {'a': {'s': 'read', 't': utc_ms(2026, 10, 31, 23, 30)}}
        self.assertEqual(server.season_books(states, 'season:christmas:2026', 60), 1)
        self.assertEqual(server.season_books(states, 'season:christmas:2026', 0), 0)

    def test_a_mark_before_the_clock_change_keeps_its_own_day(self):
        """00:30 on 1 September in Madrid is 22:30 UTC on 31 August (summer
        time). A stamp sent in November carries the winter offset (+60); her
        time zone's own rules still put the mark in autumn, as her ring does."""
        states = {'a': {'s': 'read', 't': utc_ms(2026, 8, 31, 22, 30)}}
        self.assertEqual(server.season_books(states, 'season:autumn:2026', 60, 'Europe/Madrid'), 1)
        self.assertEqual(server.season_books(states, 'season:summer:2026', 60, 'Europe/Madrid'), 0)
        # an unknown zone name falls back to the offset
        self.assertEqual(server.season_books(states, 'season:summer:2026', 60, 'Nowhere/Else'), 1)


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

    def _goal(self, n, surveyed='2026-11-01'):
        doc = server.load_interests()
        doc['season_goal'], doc['surveyed'] = n, surveyed
        server.save_interests(doc)

    def _reads(self, n, t=MID_CHRISTMAS_2026):
        """n books marked read inside Christmas 2026, as the page posts them."""
        self._post({'states': {'b%d' % i: {'s': 'read', 't': t} for i in range(n)}})

    def test_a_season_stamp_earned_on_one_device_shows_on_the_other(self):
        self._goal(6)
        self._reads(6)
        self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 11}}, 'season_goal': 6, 'tz': 0})
        j = self._post({'stamps': {'issue:2': {'s': True, 't': 12}}})
        self.assertEqual(sorted(j['stamps']), ['issue:2', 'season:christmas:2026'])
        self.assertEqual(json.load(open(server.STATE))['stamps']['season:christmas:2026']['s'], True)

    def test_a_season_stamp_checked_against_an_older_goal_is_not_kept(self):
        """The page checked 6, but another device raised the goal to 8 before
        the stamp arrived: the server holds it back, and the issue stamp in
        the same post is still kept."""
        self._goal(8)
        j = self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 11},
                                   'issue:2': {'s': True, 't': 11}}, 'season_goal': 6})
        self.assertEqual(sorted(j['stamps']), ['issue:2'])

    def test_a_season_stamp_without_her_goal_is_not_kept(self):
        """No goal sent (an old outbox), the survey still owed, or the goal
        skipped: no season stamp."""
        self._goal(6)
        self.assertEqual(self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 1}}})['stamps'], {})
        self._goal(6, surveyed=None)
        self.assertEqual(self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 2}},
                                     'season_goal': 6})['stamps'], {})
        self._goal(None)
        self.assertEqual(self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 3}},
                                     'season_goal': 6})['stamps'], {})

    def test_a_kept_season_stamp_stays_when_the_goal_changes(self):
        self._goal(6)
        self._reads(6)
        self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 11}}, 'season_goal': 6, 'tz': 0})
        self._goal(9)
        j = self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 12}}})
        self.assertTrue(j['stamps']['season:christmas:2026']['s'])

    def test_a_season_stamp_after_a_read_was_taken_back_is_not_kept(self):
        """The page counted six reads, but another device cleared one before
        the stamp arrived: the marks the server holds no longer meet the
        goal, so the stamp is held back."""
        self._goal(6)
        self._reads(6)
        self._post({'states': {'b0': {'s': None, 't': MID_CHRISTMAS_2026 + 1000}}})
        j = self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 11}}, 'season_goal': 6, 'tz': 0})
        self.assertEqual(j['stamps'], {})

    def test_an_issue_stamp_and_a_reading_day_do_not_wait_on_the_goal(self):
        """An unreadable interests file holds back only a season stamp: an
        issue stamp and a reading day in the same post are still kept."""
        self._reads(6)
        with open(server.INTERESTS, 'w') as f:
            f.write('{not json')
        self.addCleanup(os.remove, server.INTERESTS)
        j = self._post({'stamps': {'issue:2': {'s': True, 't': 11}}, 'days': {'b1': ['2026-11-15']}})
        self.assertEqual(sorted(j['stamps']), ['issue:2'])
        self.assertEqual(j['days'], {'b1': ['2026-11-15']})
        j = self._post({'stamps': {'season:christmas:2026': {'s': True, 't': 12},
                                   'series:dawn': {'s': True, 't': 12}}, 'season_goal': 6, 'tz': 0})
        self.assertEqual(sorted(j['stamps']), ['issue:2', 'series:dawn'])

    def test_a_state_without_stamps_answers_an_empty_stamp_map(self):
        self.assertEqual(self._get()['stamps'], {})
        self.assertEqual(self._get()['days'], {})


if __name__ == '__main__':
    unittest.main()
