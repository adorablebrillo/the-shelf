#!/usr/bin/env python3
"""The shape rule (ticket #6) — deterministic tests for the lane logic.
The model call is mocked; everything else runs the real code path.
Run from pipeline/:  python3 -m unittest test_shape -v
"""
import unittest
from datetime import timedelta
import curate
from lanes import lane_of, counts, shape_str, shape_line


def mk(title, genre, days_ago, rating=None, rcount=None):
    end = curate.window_end()
    d = (end - timedelta(days=days_ago)).isoformat()
    b = {'title': title, 'author': 'A. Author', 'genre': genre, 'date': d}
    if rating is not None:
        b['rating'] = rating
    if rcount is not None:
        b['rating_count'] = rcount
    return b


def pick(t, genre):
    return {'title': t, 'author': 'A. Author', 'genre': genre}


class LaneTests(unittest.TestCase):
    def test_lane_of(self):
        self.assertEqual(lane_of({'genre': 'Hockey'}), 'sport romance')
        self.assertEqual(lane_of({'genre': 'Formula 1'}), 'sport romance')
        self.assertEqual(lane_of({'genre': 'Romantasy'}), 'romantasy')
        self.assertEqual(lane_of({'genre': 'Dragon Fantasy'}), 'romantasy')
        self.assertEqual(lane_of({'genre': 'Small town'}), 'contemporary romance')
        self.assertEqual(lane_of({}), 'contemporary romance')

    def test_counts_and_shape(self):
        bs = [pick('a', 'Hockey'), pick('b', 'Hockey'), pick('c', 'Romantasy'), pick('d', 'Rom-com')]
        c = counts(bs)
        self.assertEqual(c['sport romance'], 2)
        self.assertEqual(c['romantasy'], 1)
        self.assertEqual(c['contemporary romance'], 1)
        self.assertEqual(shape_str(c), '2/1/1')
        self.assertEqual(shape_line(c), '2 sport romance · 1 romantasy · 1 contemporary romance')


class ShapeRuleTests(unittest.TestCase):
    def run_curate(self, cands, responses):
        calls = []

        def fake(key, payload, taste):
            calls.append(payload)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        orig = curate.call_model
        curate.call_model = fake
        try:
            cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-08', 'rule',
                                log=lambda *a: None)
            return cur, calls
        finally:
            curate.call_model = orig

    def test_rich_month_ships_three_three_three(self):
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('c%d' % i, 'Rom-com', 5) for i in range(3)])
        nine = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                          pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                          pick('c0', 'Rom-com'), pick('c1', 'Rom-com'), pick('c2', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [nine])
        self.assertEqual(len(calls), 1)
        self.assertEqual(cur['shape'], '3/3/3')
        self.assertFalse(cur['light'])
        self.assertEqual(cur['dropped_lanes'], [])

    def test_thin_lane_widens_then_ships(self):
        # contemporary has 1 in-window but a second at 45 days -> widen to 60, retry
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('c0', 'Rom-com', 5), mk('c1', 'Rom-com', 45)])
        first = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                           pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                           pick('c0', 'Rom-com')]}
        second = {'books': first['books'] + [pick('c1', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [first, second])
        self.assertEqual(len(calls), 2)
        self.assertEqual(cur['shape'], '3/3/2')
        self.assertEqual(cur['widen'], {'contemporary romance': 60})
        self.assertEqual(cur['dropped_lanes'], [])

    def test_unfixable_lane_is_dropped_not_retried(self):
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('c0', 'Rom-com', 5)])  # only one contemporary anywhere
        first = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                           pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                           pick('c0', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [first])
        self.assertEqual(len(calls), 1)  # availability says widening cannot reach the floor
        self.assertEqual(cur['dropped_lanes'], ['contemporary romance'])
        self.assertEqual(cur['shape'], '3/3/1')

    def test_gap_fill_takes_only_earned_leftovers(self):
        cands = ([mk('s0', 'Hockey', 5), mk('s1', 'Hockey', 5),
                  mk('s2', 'Hockey', 5, 4.6, 900), mk('s3', 'Hockey', 5, 3.2, 5)]
                 + [mk('r0', 'Romantasy', 5), mk('r1', 'Romantasy', 5)]
                 + [mk('c0', 'Rom-com', 5), mk('c1', 'Rom-com', 5)])
        six = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'),
                         pick('r0', 'Romantasy'), pick('r1', 'Romantasy'),
                         pick('c0', 'Rom-com'), pick('c1', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [six])
        titles = [b['title'] for b in cur['books']]
        self.assertIn('s2', titles)        # strong leftover earns the gap
        self.assertNotIn('s3', titles)     # weak leftover is not padding
        self.assertEqual(cur['shape'], '3/2/2')

    def test_light_month_flag(self):
        cands = [mk('s0', 'Hockey', 5), mk('r0', 'Romantasy', 5)]
        two = {'books': [pick('s0', 'Hockey'), pick('r0', 'Romantasy')]}
        cur, _ = self.run_curate(cands, [two])
        self.assertTrue(cur['light'])
        self.assertEqual(len(cur['books']), 2)


if __name__ == '__main__':
    unittest.main()
