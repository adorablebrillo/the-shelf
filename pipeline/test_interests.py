#!/usr/bin/env python3
"""The book brew (THS-37) — the run reads interests in place of the
three fixed lanes (piece 1), and a topic interest follows the baby's age
(piece 4). These tests own the new intents:
  · interests.py builds the default file from config.json lane_terms with the
    captain's answers (book brew, 12 picks, never ["cowboys"]);
  · the split follows dial weights, every active interest keeps at least 1,
    rounding goes by largest remainder with ties to the first listed;
  · a pick carries the interest of the search that found it, not a genre
    regex;
  · the romance screens hold for romance interests only, the never list for
    every book; a best-ever interest skips the window and needs a 4.0+ rating;
  · the run report prints one line per interest, with an honest zero;
  · a topic interest keeps the baby's birth month and year only, the age is
    counted in whole months, and the curator request names the stage
    (0–3, 4–6, 7–12, 13–24, 25–36 months);
  · a birth the run cannot use is named in the run's report, never swallowed;
  · the season goal the Home ring counts against is hers when the file has
    one, and the accepted Home plan's 6 books otherwise (THS-43 part 2).
Run from pipeline/:  python3 -m unittest test_interests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

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


class DisplayNameTests(unittest.TestCase):
    """THS-70: the feature is "The book brew". A file with no name, or one that
    still carries the old default, shows the new name; a typed name stays."""

    def test_missing_and_old_default_names_show_the_new_name(self):
        for saved in (None, '', '   ', 'Book-a-meter'):
            self.assertEqual(interests.display_name(saved), 'The book brew')

    def test_a_name_the_reader_typed_is_kept(self):
        self.assertEqual(interests.display_name('My taste'), 'My taste')
        self.assertEqual(interests.display_name('  My taste '), 'My taste')


class DefaultsTests(unittest.TestCase):
    """A blank install: the run makes interests.json from config lane_terms,
    with the captain's book brew answers."""

    def test_defaults_match_her_answers(self):
        d = interests.defaults()
        self.assertEqual(d['name'], 'The book brew')
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


class SeasonGoalTests(unittest.TestCase):
    """THS-43 (Home part 2): the season the Home ring counts against. The
    number is hers when the Book-a-meter has one (the survey writes
    season_goal); until then the accepted Home plan's 6 books holds."""

    def test_the_plan_number_holds_when_the_file_has_no_goal(self):
        self.assertEqual(interests.season_goal(interests.defaults()), 6)
        self.assertEqual(interests.season_goal({'season_goal': ''}), 6)
        self.assertEqual(interests.season_goal({}), 6)
        self.assertEqual(interests.season_goal(None), 6)

    def test_her_own_number_wins(self):
        for raw, want in ((4, 4), ('9', 9), (12, 12)):
            self.assertEqual(interests.season_goal({'season_goal': raw}), want)

    def test_an_impossible_number_falls_back_to_the_plan(self):
        for raw in (0, -3, 1000, 'six', 2.5, []):
            with self.subTest(goal=raw):
                self.assertEqual(interests.season_goal({'season_goal': raw}), 6)


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
    empty or all-off book brew never pads a month."""

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


class BabyAgeTests(unittest.TestCase):
    """THS-37 piece 4: a topic interest keeps the baby's birth month and
    year only, the age is counted in whole months, and the curator request
    names the stage — the plan's five, 0–3 to 25–36 months."""

    def topic(self, birth=None):
        i = {'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
             'dial': 'into it', 'mode': 'both', 'romance': False}
        if birth is not None:
            i['birth'] = birth
        return i

    def test_every_stage_boundary_by_month_and_year(self):
        # born August 2025; the plan's five stages, at each edge and one
        # month past the last
        i = self.topic('2025-08')
        for day, name in (
                (date(2025, 8, 1), '0–3 months'),     # the birth month itself
                (date(2025, 11, 30), '0–3 months'),   # 3 months
                (date(2025, 12, 1), '4–6 months'),    # 4 months
                (date(2026, 2, 28), '4–6 months'),    # 6 months
                (date(2026, 3, 1), '7–12 months'),    # 7 months
                (date(2026, 8, 31), '7–12 months'),   # 12 months
                (date(2026, 9, 1), '13–24 months'),   # 13 months
                (date(2027, 8, 1), '13–24 months'),   # 24 months
                (date(2027, 9, 1), '25–36 months'),   # 25 months
                (date(2028, 8, 1), '25–36 months')):  # 36 months
            st = interests.stage(i, day)
            self.assertIsNotNone(st, day)
            self.assertEqual(st['name'], name, day)
        # 37 months is past the plan's fifth stage: no stage is named
        self.assertIsNone(interests.stage(i, date(2028, 9, 1)))

    def test_the_age_counts_calendar_months_not_days(self):
        # a month and a year are all the file keeps, so the day of the run
        # never moves the age, and a day written into the birth is ignored
        self.assertEqual(interests.months_old(self.topic('2025-08'), date(2026, 3, 1)), 7)
        self.assertEqual(interests.months_old(self.topic('2025-08'), date(2026, 3, 31)), 7)
        self.assertEqual(interests.months_old(self.topic('2025-08-31'), date(2026, 3, 1)), 7)

    def test_only_a_born_topic_interest_has_a_stage(self):
        self.assertIsNone(interests.stage(self.topic()))                  # no birth kept
        self.assertIsNone(interests.stage(self.topic('not-a-month')))
        self.assertIsNone(interests.stage(self.topic('2025-13')))         # no such month
        self.assertIsNone(interests.stage({'kind': 'story', 'birth': '2025-08'}))
        self.assertIsNone(interests.stage(self.topic('2027-01'), date(2026, 3, 1)))  # not born yet

    def test_the_request_names_the_stage_for_the_age_at_the_run(self):
        # a baby 7 months old today: the plan's third stage, and the request
        # says so in words the curator can act on
        today = date.today()
        y, m = today.year, today.month - 7
        if m < 1:
            y, m = y - 1, m + 12
        birth = '%04d-%02d' % (y, m)
        doc = interests.defaults()
        doc['interests'].append(self.topic(birth))
        old_ints, curate.INTS = curate.INTS, doc
        try:
            block = curate.interests_block()
        finally:
            curate.INTS = old_ints
        self.assertIn('Her baby is 7 months old', block)
        self.assertIn('7–12 months: crawling, first words, separation', block)

        # the same interest with no birth: the request is the interest alone
        doc['interests'][-1] = self.topic()
        old_ints, curate.INTS = curate.INTS, doc
        try:
            plain = curate.interests_block()
        finally:
            curate.INTS = old_ints
        self.assertNotIn('months old', plain)


class BadBirthWarningTests(unittest.TestCase):
    """A birth month and year the run cannot use is named in the run's
    report, never swallowed: the reader sets it by hand until the
    book brew tab ships."""

    def report(self, interest):
        doc = interests.defaults()
        doc['interests'].append(interest)
        cands = [mk('s%d' % i, 'Hockey', 5, lane='sport romance') for i in range(3)]
        picked = {'books': [{'title': 's%d' % i, 'author': 'A. Author', 'genre': 'Hockey'}
                            for i in range(3)]}
        logs = []
        old_ints, curate.INTS = curate.INTS, doc
        try:
            curate.curate('k', {'books': cands}, 'taste', {}, '2026-08', 'rule',
                          call=lambda key, payload, taste: picked, log=logs.append)
        finally:
            curate.INTS = old_ints
        return [l for l in logs if 'the birth month and year' in l]

    def test_a_birth_that_does_not_read_is_named(self):
        lines = self.report({'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                             'dial': 'into it', 'mode': 'both', 'romance': False,
                             'birth': 'agust 2025'})
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('is not a month and year (YYYY-MM)', lines[0])
        self.assertIn('agust 2025', lines[0])

    def test_a_birth_on_a_story_interest_is_named(self):
        lines = self.report({'id': 'sportier', 'label': 'Sportier romance', 'kind': 'story',
                             'dial': 'into it', 'mode': 'new', 'romance': True,
                             'birth': '2025-08'})
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('does nothing on a story interest', lines[0])

    def test_a_usable_birth_says_nothing(self):
        self.assertEqual(self.report({'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                                      'dial': 'into it', 'mode': 'both', 'romance': False,
                                      'birth': '2025-08'}), [])

class CatalogTests(unittest.TestCase):
    """The survey's shelves: one table in code, so the tiles the reader picks
    from and the words the run searches for are the same list."""

    def test_the_catalog_carries_the_survey_shelves(self):
        cat = interests.catalog()
        ids = [c['id'] for c in cat]
        for want in ('sport', 'romantasy', 'contemp', 'thriller', 'baby', 'cooking'):
            self.assertIn(want, ids)
        kinds = {c['id']: c['kind'] for c in cat}
        self.assertEqual(kinds['romantasy'], 'story')
        self.assertEqual(kinds['baby'], 'topic')

    def test_a_catalog_interest_has_its_own_search_words(self):
        self.assertTrue(interests.terms({'id': 'baby', 'label': 'Baby development'}))
        self.assertTrue(interests.terms({'id': 'thriller', 'label': 'Thriller'}))

    def test_a_renamed_interest_keeps_its_words(self):
        """The lookup is by id, so a name the reader changed does not cost the
        interest its search words."""
        self.assertTrue(interests.terms({'id': 'baby', 'label': 'Books about my baby'}))

    def test_a_typed_interest_has_no_words_until_the_curator_suggests_them(self):
        self.assertEqual(interests.terms({'id': 'c-sourdough', 'label': 'Sourdough'}), [])


class SaveTests(unittest.TestCase):
    """The two writers of one file: the run adds the search words it found,
    the survey writes the reader's answers. Neither may lose the other's work.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='shelf-interests-file-')
        self.old = os.environ.get('CFG_DIR')
        os.environ['CFG_DIR'] = self.dir

    def tearDown(self):
        if self.old is None:
            os.environ.pop('CFG_DIR', None)
        else:
            os.environ['CFG_DIR'] = self.old

    def _read(self):
        return json.loads(open(interests.vol_path()).read())

    def _write(self, doc):
        """The file as it stands on the volume (what a writer leaves there)."""
        os.makedirs(self.dir, exist_ok=True)
        with open(interests.vol_path(), 'w') as f:
            json.dump(doc, f, indent=1)

    def test_the_runs_save_keeps_the_readers_answers(self):
        """The run started before the reader answered: its save must not roll
        the reader's answers back."""
        doc = interests.defaults()
        doc['interests'][0]['dial'] = 'obsessed'
        self._write(doc)
        run = interests.load()
        run['interests'][0]['terms'] = ['hockey romance']
        interests.save_terms(run)
        out = self._read()
        self.assertEqual(out['interests'][0]['dial'], 'obsessed')
        self.assertEqual(out['interests'][0]['terms'], ['hockey romance'])

    def test_the_shared_rule_gives_the_words_of_the_other_writer(self):
        """One rule for both writers: an interest with no words of its own
        takes the words the other writer gives it, and words that are already
        there are never overwritten."""
        base = {'interests': [{'id': 'baby', 'label': 'Baby development'}]}
        other = {'interests': [{'id': 'baby', 'label': 'Baby development',
                                'terms': ['baby development']}]}
        merged = interests.merge_terms(base, other)
        self.assertEqual(merged['interests'][0]['terms'], ['baby development'])
        kept = {'interests': [{'id': 'baby', 'terms': ['kept']}]}
        interests.merge_terms(kept, other)
        self.assertEqual(kept['interests'][0]['terms'], ['kept'])

    def test_the_goodreads_genre_the_run_found_survives_the_readers_save(self):
        """The run keeps the Goodreads genre of a typed interest in the file;
        the reader's own save (it carries none) must not drop it, and a genre
        the file already has is never overwritten."""
        self._write({'interests': [{'id': 'hockey', 'label': 'Hockey romance', 'gr_slug': 'sports-romance'}]})
        readers = {'interests': [{'id': 'hockey', 'label': 'Hockey romance', 'dial': 'obsessed'}]}
        interests.merge_terms(readers, self._read())
        self.assertEqual(readers['interests'][0]['gr_slug'], 'sports-romance')
        self.assertEqual(readers['interests'][0]['dial'], 'obsessed')
        run = {'interests': [{'id': 'hockey', 'gr_slug': 'hockey'}]}
        interests.save_terms(run)
        self.assertEqual(self._read()['interests'][0]['gr_slug'], 'sports-romance')



if __name__ == '__main__':
    unittest.main()
