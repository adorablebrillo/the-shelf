#!/usr/bin/env python3
"""The reader state — the server contract behind /api/state, including ticket
#57's reading channel (a reading flag travels beside the verdict marks, merged
by the same last-write-wins rule, and never touches 'states').

Run: cd container && python3 -m unittest test_state

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume.
"""
import os
import json
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
