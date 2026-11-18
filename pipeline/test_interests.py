#!/usr/bin/env python3
"""The Book-a-meter (THS-37 piece 1) — the run reads interests in place of
the three fixed lanes. These tests own the new intents:
  · interests.py builds the default file from config.json lane_terms with the
    captain's answers (Book-a-meter, 12 picks, never ["cowboys"]);
  · the split follows dial weights, every active interest keeps at least 1,
    rounding goes by largest remainder with ties to the first listed;
  · a pick carries the interest of the search that found it, not a genre
    regex;
  · the romance screens hold for romance interests only, the never list for
    every book; a best-ever interest skips the window and needs a 4.0+ rating;
  · the run report prints one line per interest, with an honest zero.
Run from pipeline/:  python3 -m unittest test_interests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

import curate
import filter as flt
import interests


def mk(title, genre, days_ago, rating=None, rcount=None, trad=True, lane=''):
    end = curate.window_end(curate.MODE)
    b = {'title': title, 'author': 'A. Author', 'genre': genre,
         'date': (end - timedelta(days=days_ago)).isoformat(),
         'trad': trad, 'lane': lane}
    if rating is not None:
        b['rating'] = rating
    if rcount is not None:
        b['rating_count'] = rcount
    return b


class DefaultsTests(unittest.TestCase):
    """A blank install: the run makes interests.json from config lane_terms,
    with the captain's Book-a-meter answers."""

    def test_defaults_match_her_answers(self):
        d = interests.defaults()
        self.assertEqual(d['name'], 'Book-a-meter')
        self.assertEqual(d['picks'], 12)
        self.assertEqual(d['never'], ['cowboys'])
        self.assertIsNone(d['season_goal'])
        self.assertEqual([i['label'] for i in d['interests']],
                         ['Sport romance', 'Romantasy', 'Contemporary romance'])
        for i in d['interests']:
            self.assertEqual(i['kind'], 'story')
            self.assertEqual(i['dial'], 'into it')
            self.assertEqual(i['mode'], 'new')
            self.assertTrue(i['romance'])
        # the three defaults are today's lanes, and their search words come
        # from the catalog table (config.json lane_terms)
        for i in d['interests']:
            self.assertEqual(interests.terms(i),
                             curate.CFG['lane_terms'][interests.name(i)])


class SplitTests(unittest.TestCase):
    """Picks per interest: dial weight, floor of one, largest remainder, ties
    to the interest listed first."""

    def doc(self, dials):
        return {'v': 1, 'name': 'Book-a-meter', 'picks': 12, 'never': [],
                'season_goal': None,
                'interests': [{'id': 'i%d' % k, 'label': 'Interest %d' % k,
                                'kind': 'story', 'dial': d, 'mode': 'new', 'romance': True}
                               for k, d in enumerate(dials)]}

    def test_her_default_three_into_it_split_4_4_4(self):
        sp = interests.split(self.doc(['into it', 'into it', 'into it']))
        self.assertEqual(sp, {'interest 0': 4, 'interest 1': 4, 'interest 2': 4})

    def test_weights_follow_the_dial(self):
        # curious 1 · into it 2 · obsessed 3 over 12 -> 2/4/6
        sp = interests.split(self.doc(['curious', 'into it', 'obsessed']))
        self.assertEqual(sp, {'interest 0': 2, 'interest 1': 4, 'interest 2': 6})

    def test_off_interests_get_nothing(self):
        sp = interests.split(self.doc(['off', 'into it', 'into it']))
        # an off interest is not searched and gets no picks at all
        self.assertEqual(sp, {'interest 1': 6, 'interest 2': 6})

    def test_every_active_interest_keeps_at_least_one(self):
        # 5 interests, one obsessed: proportions starve the small ones below 1
        d = self.doc(['curious', 'curious', 'curious', 'curious', 'obsessed'])
        sp = interests.split(d)
        self.assertEqual(sum(sp.values()), 12)
        self.assertTrue(all(v >= 1 for v in sp.values()),
                        'every active interest keeps at least 1: %s' % sp)

    def test_more_interests_than_picks_go_to_the_strongest_dials(self):
        d = self.doc(['into it', 'into it', 'curious', 'obsessed', 'curious'])
        d['picks'] = 2
        sp = interests.split(d)
        self.assertEqual(sum(sp.values()), 2)
        self.assertEqual(sp['interest 3'], 1)  # obsessed first
        self.assertEqual(max(sp.values()), 1)

    def test_a_tie_rounds_to_the_interest_listed_first(self):
        # 7 picks, two equal dials: bases 3/3, one left, remainders equal
        # -> the FIRST listed interest takes the odd pick
        d = self.doc(['curious', 'curious'])
        d['picks'] = 7
        sp = interests.split(d)
        self.assertEqual(sp, {'interest 0': 4, 'interest 1': 3})


class ProvenanceTests(unittest.TestCase):
    """A pick carries the interest of the search that found it — the lane
    field fetch sets — never a genre regex."""

    def test_of_prefers_the_search_over_the_genre(self):
        doc = interests.defaults()
        b = {'genre': 'Romantasy', 'lane': 'sport romance'}  # a romantasy-genre book found by the sport search
        self.assertEqual(interests.of(b, doc), 'sport romance')

    def test_of_falls_back_to_the_genre_when_no_search(self):
        self.assertEqual(interests.of({'genre': 'Hockey'}, interests.defaults()),
                         'sport romance')

    def test_the_curate_copy_puts_the_search_on_the_pick(self):
        cand = mk('Found By Search', 'Romantasy', 5, lane='sport romance')
        model_pick = {'title': 'Found By Search', 'author': 'A. Author', 'genre': 'Romantasy'}
        out = curate.copy_series([model_pick], [cand])
        self.assertEqual(out[0].get('lane'), 'sport romance')


class RulesScopeTests(unittest.TestCase):
    """The romance screens hold for romance interests only; the never list
    holds for every book."""

    def test_never_family_still_bites(self):
        # her "cowboys" names the whole cowboy/western family (issue #35)
        for t, g in (('Cowboy Up', 'romance'), ('Heart of the Ranch', 'romance'),
                     ('Reckless Skye', 'Western Romance Books Romance')):
            self.assertTrue(flt.never_words_screen(t, g, ['cowboys']), t)
        self.assertFalse(flt.never_words_screen('Second Serve', 'Sports Romance', ['cowboys']))

    def test_a_never_word_without_a_family_matches_itself(self):
        self.assertTrue(flt.never_words_screen('The Dragon Court', 'romance', ['dragon']))
        self.assertFalse(flt.never_words_screen('A Match Made', 'romance', ['dragon']))

    def test_topic_interests_are_not_romance(self):
        topic = {'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                 'dial': 'into it', 'mode': 'best ever', 'romance': False}
        self.assertFalse(interests.romance(topic))
        self.assertTrue(interests.best_ever(topic))
        self.assertTrue(interests.romance(interests.defaults()['interests'][0]))


class BestEverFlowTests(unittest.TestCase):
    """A hand-typed topic interest (mode best ever): any date stays, the 4.0
    rating is the proof, the romance screens do not apply, the never list
    does. Uses the REAL filter main() like test_filter's flow test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='shelf-ints-')
        self._old = os.environ.get('CFG_DIR')
        os.environ['CFG_DIR'] = self.tmp
        doc = interests.defaults()
        doc['interests'].append({'id': 'baby', 'label': 'Baby development',
                                 'kind': 'topic', 'dial': 'into it',
                                 'mode': 'best ever', 'romance': False})
        with open(os.path.join(self.tmp, 'interests.json'), 'w') as f:
            json.dump(doc, f)

    def tearDown(self):
        import shutil
        if self._old is None:
            os.environ.pop('CFG_DIR', None)
        else:
            os.environ['CFG_DIR'] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mon_books(self):
        import windows
        mon = windows.target_month(flt.MODE)
        old = '2015-04-02'
        return mon, [
            # a strongly-rated backlist topic book: any date, 4.0+ -> kept
            {'title': 'The Weird Baby', 'author': 'T. Author',
             'genre': 'Baby development MM sleep', 'date': old, 'lane': 'baby development',
             'publisher': 'Some Tiny Press', 'rating': 4.5, 'rating_count': 40,
             'language': 'English'},
            # the same interest, unrated: no proof -> dropped
            {'title': 'Unrated Baby Book', 'author': 'T. Author',
             'genre': 'Baby development', 'date': old, 'lane': 'baby development',
             'publisher': 'Some Tiny Press', 'language': 'English'},
            # the never list applies to every interest
            {'title': 'Ranch Baby Guide', 'author': 'T. Author',
             'genre': 'Baby development', 'date': old, 'lane': 'baby development',
             'publisher': 'Penguin', 'rating': 4.6, 'rating_count': 90,
             'language': 'English'},
            # a romance candidate: screened as today (MM -> dropped)
            {'title': 'An MM Hockey Romance', 'author': 'A. Author',
             'genre': 'Sports Romance', 'date': mon + '-15',
             'publisher': 'Avon', 'language': 'English'},
        ]

    def test_topic_rules_in_the_real_filter_run(self):
        mon, books = self.mon_books()
        with open(os.path.join(self.tmp, 'candidates-%s.json' % mon), 'w') as f:
            json.dump({'books': books}, f)
        old_out = flt.CFG.get('output_dir')
        flt.CFG['output_dir'] = self.tmp
        try:
            rc = flt.main()
        finally:
            if old_out is not None:
                flt.CFG['output_dir'] = old_out
        self.assertEqual(rc, 0)
        with open(os.path.join(self.tmp, 'filtered-%s.json' % mon)) as f:
            out = json.load(f)
        kept = {b['title']: b for b in out['books']}
        self.assertIn('The Weird Baby', kept)      # any date + 4.0 rating = the proof
        self.assertNotIn('Unrated Baby Book', kept)  # unrated best-ever is dropped
        self.assertNotIn('Ranch Baby Guide', kept)   # the never list applies to topics
        self.assertNotIn('An MM Hockey Romance', kept)  # the romance screen still bites
        self.assertTrue(kept['The Weird Baby']['in_window'])  # the window rule skips it
        self.assertTrue(kept['The Weird Baby']['best_ever_proven'])
        self.assertEqual(out['rules']['romance_rules'], 'romance interests only')
        self.assertEqual(out['rules']['never'], ['cowboys'])


class ReportTests(unittest.TestCase):
    """The run report prints one line per interest: candidates, picks, and an
    honest zero when there are none."""

    def run_curate(self, cands, responses):
        logs = []

        def fake(key, payload, taste):
            return responses[0]
        cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-08', 'rule',
                            call=fake, log=logs.append)
        return cur, logs

    def test_one_line_per_interest_with_a_zero(self):
        cands = ([mk('s%d' % i, 'Hockey', 5, lane='sport romance') for i in range(3)]
                 + [mk('r%d' % i, 'Romantasy', 5, lane='romantasy') for i in range(3)])
        nine = {'books': [{'title': 's%d' % i, 'author': 'A. Author', 'genre': 'Hockey'} for i in range(3)]
                + [{'title': 'r%d' % i, 'author': 'A. Author', 'genre': 'Romantasy'} for i in range(3)]}
        cur, logs = self.run_curate(cands, [nine])
        lines = [l for l in logs if l.startswith('[interest]')]
        self.assertEqual(len(lines), 3)  # every interest in the file, even the empty one
        self.assertTrue(any('Contemporary romance: 0 candidate(s) · 0 pick(s) — ZERO' in l for l in lines))
        self.assertTrue(any('Sport romance: 3 candidate(s) · 3 pick(s)' in l for l in lines))
        # picks carry their interest from the search
        lanes = [b.get('lane') for b in cur['books']]
        self.assertEqual(lanes.count('sport romance'), 3)


class WidenLoopProvenanceTests(unittest.TestCase):
    """The widening loop must count the model's picks by the interest of the
    search that found them, not by the genre fallback — otherwise a mode-new
    typed interest can never be seen to reach its floor and the run burns
    every curation call widening."""

    def test_typed_interest_reaches_its_floor_in_one_call(self):
        doc = interests.defaults()
        doc['interests'] = doc['interests'][:1]  # keep it small: one romance interest
        doc['interests'].append({'id': 'baby', 'label': 'Baby books', 'kind': 'topic',
                                 'dial': 'into it', 'mode': 'new', 'romance': False})
        old_ints, curate.INTS = curate.INTS, doc
        try:
            # two candidates whose genre would fall back to contemporary,
            # but the search that found them was the typed interest
            cands = ([mk('s%d' % i, 'Hockey', 5, lane='sport romance') for i in range(3)]
                     + [mk('b%d' % i, 'Sleep guide', 5, lane='baby books') for i in range(2)])
            picked = {'books': [{'title': 's%d' % i, 'author': 'A. Author', 'genre': 'Hockey'} for i in range(3)]
                      + [{'title': 'b%d' % i, 'author': 'A. Author', 'genre': 'Sleep guide'} for i in range(2)]}
            calls = []

            def fake(key, payload, taste):
                calls.append(payload)
                return picked
            cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-08', 'rule',
                                call=fake, log=lambda *a: None)
            # the typed interest reached its floor on the first count: one call
            self.assertEqual(len(calls), 1)
            self.assertEqual(cur['lanes'].get('baby books'), 2)
            self.assertEqual(cur['dropped_lanes'], [])
        finally:
            curate.INTS = old_ints


class GapFillWindowTests(unittest.TestCase):
    """gap_fill never treats a name the run does not know as any-date, and an
    empty or all-off Book-a-meter never pads a month."""

    def test_unknown_name_is_bounded_by_the_first_rung(self):
        # a leftover whose genre falls back to a name no interest owns, dated
        # 100 days back: bounded by the base window, not filled
        cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                 + [mk('old-unknown', 'Hockey', 100, 4.8, 900)])
        picks = [{'title': 's%d' % i, 'author': 'A. Author', 'genre': 'Hockey'} for i in range(3)]
        end = curate.window_end(curate.MODE)
        fills = curate.gap_fill(picks, cands, 12,
                                {'sport romance': 30, 'romantasy': 30, 'contemporary romance': 30},
                                end)
        self.assertEqual([f['title'] for f in fills], [])

    def test_no_active_interests_never_pads(self):
        # every dial off: the request said pick nothing — a leftover must not
        # become a fill
        doc = interests.defaults()
        for i in doc['interests']:
            i['dial'] = 'off'
        old_ints, curate.INTS = curate.INTS, doc
        try:
            cands = [mk('s0', 'Hockey', 5, 4.8, 900)]
            picked = {'books': []}
            calls = []

            def fake(key, payload, taste):
                calls.append(payload)
                return picked
            cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-08', 'rule',
                                call=fake, log=lambda *a: None)
            self.assertEqual(cur['books'], [])  # no model picks, and no padding fill
        finally:
            curate.INTS = old_ints


class CaptainPicksTests(unittest.TestCase):
    """The captain took the reviewer's pick on all four open findings; these
    pin what she chose, exactly as the review recorded them."""

    def test_the_block_overrides_the_hard_rules_for_topics(self):
        # pick 1: one line in the interests block names that the hard-rules
        # romance lines do not hold for a non-romance interest's books
        doc = interests.defaults()
        doc['interests'].append({'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                                 'dial': 'into it', 'mode': 'best ever', 'romance': False})
        old_ints, curate.INTS = curate.INTS, doc
        try:
            block = curate.interests_block()
            self.assertIn('do NOT apply', block)
            self.assertIn('hard-rules lines (M/F only, no cowboy)', block)
        finally:
            curate.INTS = old_ints
        # and a pure-romance meter carries no override line
        self.assertNotIn('do NOT apply', curate.interests_block())

    def test_the_blank_brief_teaches_the_fields_the_payload_carries(self):
        # pick 2: the shipped blank taste brief matches the interests payload
        import os
        tp = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'taste-prompt.md')).read()
        self.assertIn('interest_windows', tp)
        self.assertIn('interest_availability', tp)
        self.assertNotIn('lane_windows', tp)
        self.assertNotIn('lane_availability', tp)

    def test_a_topic_pick_carries_no_romance_score_rows(self):
        # pick 3: the spice/MMC row shows only for a romance interest's pick
        import build
        doc = interests.defaults()
        doc['interests'].append({'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                                 'dial': 'into it', 'mode': 'best ever', 'romance': False})
        old_ints, build.INTS = build.INTS, doc
        try:
            topic_pick = build.pick_book({'title': 'The Weird Baby', 'author': 'T. Author',
                                          'genre': 'Baby development', 'lane': 'baby development'}, None, '')
            self.assertFalse(topic_pick['scoreRows'])
            rom = build.pick_book({'title': 'Ice Hockey Hearts', 'author': 'A. Author',
                                   'genre': 'Hockey', 'lane': 'sport romance'}, None, '')
            self.assertTrue(rom['scoreRows'])
        finally:
            build.INTS = old_ints

    def test_the_shape_line_shows_an_interests_honest_zero(self):
        # pick 4: an interest that shipped zero keeps its zero on the line
        from lanes import counts, shape_str, shape_line
        c = counts([{'title': 'a', 'author': 'x', 'genre': 'Hockey', 'lane': 'sport romance'}],
                   order=['sport romance', 'romantasy'])
        self.assertEqual(c['romantasy'], 0)
        self.assertEqual(shape_str(c, order=['sport romance', 'romantasy']), '1/0')
        self.assertEqual(shape_line(c, order=['sport romance', 'romantasy'],
                                    labels={'sport romance': 'Sport romance', 'romantasy': 'Romantasy'}),
                         '1 Sport romance · 0 Romantasy')


class GapFillBestEverTests(unittest.TestCase):
    """A best-ever interest has no window: an old, strongly rated leftover
    earns a gap fill a new-release interest's window would refuse."""

    def test_old_best_ever_leftover_earns_the_fill(self):
        doc = interests.defaults()
        doc['interests'].append({'id': 'baby', 'label': 'Baby development',
                                 'kind': 'topic', 'dial': 'into it',
                                 'mode': 'best ever', 'romance': False})
        old_ints, curate.INTS = curate.INTS, doc
        try:
            cands = ([mk('s%d' % i, 'Hockey', 5) for i in range(3)]
                     + [mk('r%d' % i, 'Romantasy', 5) for i in range(3)]
                     + [mk('c%d' % i, 'Rom-com', 5) for i in range(3)]
                     + [mk('old1', 'Baby development', 4000, 4.7, 500,
                           lane='baby development')])
            picks = [{'title': 's%d' % i, 'author': 'A. Author', 'genre': 'Hockey'} for i in range(3)]
            end = curate.window_end(curate.MODE)
            fills = curate.gap_fill(picks, cands, 12,
                                    {'sport romance': 30, 'romantasy': 30,
                                     'contemporary romance': 30, 'baby development': None},
                                    end)
            self.assertIn('old1', [f['title'] for f in fills])
        finally:
            curate.INTS = old_ints


if __name__ == '__main__':
    unittest.main()
