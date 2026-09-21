#!/usr/bin/env python3
"""The shape rule (ticket #6) — deterministic tests for the lane logic.
The model call is injected; everything else runs the real code path.
Run from pipeline/:  python3 -m unittest test_shape -v
"""
import unittest
from datetime import timedelta
import curate
from lanes import lane_of, counts, shape_str, shape_line


def mk(title, genre, days_ago, rating=None, rcount=None, trad=True, indie=False, proven=False):
    end = curate.window_end(curate.MODE)
    d = (end - timedelta(days=days_ago)).isoformat()
    b = {'title': title, 'author': 'A. Author', 'genre': genre, 'date': d,
         'trad': trad, 'indie': indie, 'indie_proven': proven}
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

        cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-08', 'rule',
                            call=fake, log=lambda *a: None)
        return cur, calls

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

    def test_widening_reaches_the_90_day_rung(self):
        # the second contemporary sits at 80 days: 60d cannot reach the floor,
        # 90d can — the loop must skip ahead, not stop at 60
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('c0', 'Rom-com', 5), mk('c1', 'Rom-com', 80)])
        first = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                           pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                           pick('c0', 'Rom-com')]}
        second = {'books': first['books'] + [pick('c1', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [first, second])
        self.assertEqual(len(calls), 2)
        self.assertEqual(cur['widen'], {'contemporary romance': 90})
        self.assertEqual(cur['shape'], '3/3/2')

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

    def test_dropped_recomputed_after_fill(self):
        # the model keeps missing a widened candidate; the gap fill lands it,
        # so the lane is NOT dropped and the record must say so
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('c0', 'Rom-com', 5), mk('c1', 'Rom-com', 45, 4.3, 200)])
        thin = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                          pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                          pick('c0', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [thin])
        self.assertEqual(cur['shape'], '3/3/2')
        self.assertEqual(cur['dropped_lanes'], [])
        titles = [b['title'] for b in cur['books']]
        self.assertIn('c1', titles)

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

    def test_gap_fill_respects_lane_windows(self):
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('s3', 'Hockey', 25, 4.7, 800)]           # in-window sport leftover
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('r3', 'Romantasy', 100, 4.8, 900)]       # 100 days back: outside every lane window
                 + [mk('c0', 'Rom-com', 5), mk('c1', 'Rom-com', 5)])
        eight = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                           pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                           pick('c0', 'Rom-com'), pick('c1', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [eight])
        titles = [b['title'] for b in cur['books']]
        self.assertIn('s3', titles)
        self.assertNotIn('r3', titles)     # the widening ladder bounds every fill
        self.assertEqual(cur['shape'], '4/3/2')

    def test_gap_fill_requires_proof_for_indie(self):
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                 + [mk('c0', 'Rom-com', 5), mk('c1', 'Rom-com', 5)]
                 + [mk('i0', 'Rom-com', 10, 4.4, 2, trad=False, indie=True, proven=False)]
                 + [mk('t0', 'Rom-com', 12, 4.1, 30, trad=True)])
        eight = {'books': [pick('s0', 'Hockey'), pick('s1', 'Hockey'), pick('s2', 'Hockey'),
                           pick('r0', 'Romantasy'), pick('r1', 'Romantasy'), pick('r2', 'Romantasy'),
                           pick('c0', 'Rom-com'), pick('c1', 'Rom-com')]}
        cur, calls = self.run_curate(cands, [eight])
        titles = [b['title'] for b in cur['books']]
        self.assertIn('t0', titles)        # trad book with a rating earns it
        self.assertNotIn('i0', titles)     # indie on 2 votes does not

    def test_light_month_flag(self):
        cands = [mk('s0', 'Hockey', 5), mk('r0', 'Romantasy', 5)]
        two = {'books': [pick('s0', 'Hockey'), pick('r0', 'Romantasy')]}
        cur, _ = self.run_curate(cands, [two])
        self.assertTrue(cur['light'])
        self.assertEqual(len(cur['books']), 2)


if __name__ == '__main__':
    unittest.main()
