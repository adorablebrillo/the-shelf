#!/usr/bin/env python3
"""Every interest the survey keeps reaches the issue, not only romantasy.

The reader's report: "why have i not been recommended any of the other books
outside of romantasy? all my interests should be added to the recommendations
once the survey highlights the interest." These tests own that intent:
  · the curator's instructions follow her interests: the blank brief has no
    romance-only genre list, and the request tells the model, over any brief
    (her deployed one included), that a pick's genre is its interest and the
    romance scores belong to romance interests only;
  · after the model answers, code holds each interest's share: an answer made
    only of romantasy ships every interest at its target, an interest over its
    target gives way only to make room, and nothing is padded when an interest
    has no book to give;
  · a pick the model retitled still counts for the interest that found it.
Run from pipeline/:  python3 -m unittest test_split -v
"""
import os
import unittest
from datetime import timedelta

import curate
import interests
from lanes import counts

HERE = os.path.dirname(os.path.abspath(__file__))


def survey_doc():
    """What the survey writes for the reader in the report: five interests,
    each 'into it', twelve picks. Targets: 3 romantasy, 3 thriller, 2 fantasy,
    2 memoir, 2 baby development."""
    def i(iid, label, kind, mode, romance=False):
        return {'id': iid, 'label': label, 'kind': kind, 'dial': 'into it',
                'mode': mode, 'romance': romance}
    return {'v': 1, 'name': 'The book brew', 'picks': 12, 'never': ['cowboys'],
            'surveyed': '2026-11-23', 'season_goal': 6, 'interests': [
                i('romantasy', 'Romantasy', 'story', 'new', True),
                i('thriller', 'Thriller', 'story', 'new'),
                i('fantasy', 'Fantasy', 'story', 'new'),
                i('memoir', 'Memoir', 'topic', 'both'),
                i('baby', 'Baby development', 'topic', 'both'),
            ]}


def cand(title, lane, days_ago=5, rating=4.3, author='A. Author', **kw):
    end = curate.window_end(curate.MODE)
    best = lane in ('memoir', 'baby development')
    b = {'title': title, 'author': author, 'genre': lane.title(), 'lane': lane,
         'date': (end - timedelta(days=days_ago)).isoformat(),
         'trad': True, 'rating': rating, 'rating_count': 500,
         'in_window': True, 'best_ever_proven': best}
    b.update(kw)
    return b


def pool(n=6, lanes=('romantasy', 'thriller', 'fantasy', 'memoir', 'baby development')):
    return [cand('%s %d' % (ln, k), ln, rating=4.9 - k * 0.1)
            for ln in lanes for k in range(n)]


def model_answer(cands, lane, n=12):
    """What the stand-in model says when it follows the romance-only brief:
    twelve books, all from one interest, each tagged with a romance genre."""
    return {'books': [{'title': c['title'], 'author': c['author'],
                       'genre': 'romantasy', 'spice': 3, 'mmc': {'score': 4}}
                      for c in cands if c['lane'] == lane][:n],
            'top_pick': ''}


class SplitHeldAfterTheModelAnswers(unittest.TestCase):

    def setUp(self):
        self._old = curate.INTS
        curate.INTS = survey_doc()

    def tearDown(self):
        curate.INTS = self._old

    def run_curate(self, cands, answer):
        calls, logs = [], []

        def fake(key, payload, taste):
            calls.append(payload)
            return {k: (list(v) if isinstance(v, list) else v) for k, v in answer.items()}
        cur = curate.curate('k', {'books': cands}, 'taste', {}, '2026-11', 'rule',
                            call=fake, log=logs.append)
        return cur, logs

    def test_a_romantasy_only_answer_ships_every_interest(self):
        # the reported failure: the model returns twelve romantasy books
        cands = pool(n=12)
        cur, logs = self.run_curate(cands, model_answer(cands, 'romantasy'))
        c = counts(cur['books'], order=curate.interest_names())
        self.assertEqual(c, {'romantasy': 3, 'thriller': 3, 'fantasy': 2,
                             'memoir': 2, 'baby development': 2})
        self.assertEqual(len(cur['books']), 12)
        self.assertEqual(cur['dropped_lanes'], [])
        self.assertTrue(any('split held' in l for l in logs))

    def test_the_strongest_books_of_an_interest_fill_its_share(self):
        cands = pool(n=12)
        cur, _ = self.run_curate(cands, model_answer(cands, 'romantasy'))
        thrillers = [b['title'] for b in cur['books'] if b.get('lane') == 'thriller']
        self.assertEqual(sorted(thrillers), ['thriller 0', 'thriller 1', 'thriller 2'])

    def test_a_pick_over_its_target_stays_when_there_is_room(self):
        # four romantasy picks, eight free slots, and no memoir to fill: the
        # other interests need seven slots, so romantasy keeps its fourth
        cands = pool(n=12, lanes=('romantasy', 'thriller', 'fantasy', 'baby development'))
        cur, logs = self.run_curate(cands, model_answer(cands, 'romantasy', n=4))
        c = counts(cur['books'], order=curate.interest_names())
        self.assertGreaterEqual(c['romantasy'], 4)
        for nm, floor in (('thriller', 3), ('fantasy', 2), ('baby development', 2)):
            self.assertGreaterEqual(c[nm], floor)
        self.assertEqual(len(cur['books']), 12)
        self.assertTrue(any('-0 past-target' in l for l in logs))

    def test_an_interest_with_no_book_is_not_padded(self):
        # no thriller candidate exists: the thriller share is not invented,
        # and the room goes to the interests that have books
        lanes = ('romantasy', 'fantasy', 'memoir', 'baby development')
        cands = pool(n=12, lanes=lanes)
        cur, logs = self.run_curate(cands, model_answer(cands, 'romantasy'))
        c = counts(cur['books'], order=curate.interest_names())
        self.assertEqual(c['thriller'], 0)
        self.assertEqual(cur['dropped_lanes'], ['thriller'])
        self.assertTrue(all(c[n] >= 2 for n in lanes))
        self.assertLessEqual(len(cur['books']), 12)

    def test_a_guaranteed_sequel_and_the_top_pick_are_never_trimmed(self):
        cands = pool(n=12)
        for c in cands:
            if c['title'] == 'romantasy 10':
                c['aseq'] = True
        ans = model_answer(cands, 'romantasy')
        ans['books'][11]['aseq'] = True          # the model kept her series book
        ans['books'][10]['id'] = 'the-face-of-the-month'
        ans['top_pick'] = 'the-face-of-the-month'
        cur, _ = self.run_curate(cands, ans)
        titles = [b['title'] for b in cur['books']]
        self.assertIn(ans['books'][11]['title'], titles)
        self.assertIn(ans['books'][10]['title'], titles)
        c = counts(cur['books'], order=curate.interest_names())
        self.assertEqual(c['thriller'], 3)

    def test_a_book_below_the_bar_never_fills_a_share(self):
        cands = pool(n=12)
        for c in cands:
            if c['lane'] == 'thriller':
                c['rating'] = 3.1      # rated, and not good enough
        cur, _ = self.run_curate(cands, model_answer(cands, 'romantasy'))
        c = counts(cur['books'], order=curate.interest_names())
        self.assertEqual(c['thriller'], 0)

    def test_a_new_release_with_no_rating_yet_can_fill_its_share(self):
        cands = pool(n=12)
        for c in cands:
            if c['lane'] == 'thriller':
                c.pop('rating'); c.pop('rating_count')
        cur, _ = self.run_curate(cands, model_answer(cands, 'romantasy'))
        c = counts(cur['books'], order=curate.interest_names())
        self.assertEqual(c['thriller'], 3)

    def test_a_retitled_pick_keeps_the_interest_that_found_it(self):
        # the model answers 'The Wrath Gods Reap: A Novel', genre romantasy,
        # for a book the Fantasy search found
        cands = pool(n=3)
        cands.append(cand('The Wrath Gods Reap', 'fantasy', author='Lydia Gale'))
        picks = [{'title': 'The Wrath Gods Reap: A Novel', 'author': 'Lydia Gale',
                  'genre': 'romantasy'}]
        out = curate.copy_series(picks, cands)
        self.assertEqual(out[0]['lane'], 'fantasy')


class CuratorInstructionsFollowTheInterests(unittest.TestCase):

    def test_the_blank_brief_has_no_romance_only_genre_list(self):
        with open(os.path.join(HERE, 'taste-prompt.md')) as f:
            tp = f.read()
        self.assertNotIn('"sport romance" | "romantasy" | "contemporary romance"', tp)
        self.assertIn('romance interests only', tp)   # spice and mmc are scoped

    def test_the_request_overrides_the_output_fields_for_every_brief(self):
        old, curate.INTS = curate.INTS, survey_doc()
        try:
            block = curate.interests_block()
        finally:
            curate.INTS = old
        # her deployed brief may still carry the old romance-only schema, so
        # the override lives in code, in every request
        self.assertIn('OVERRIDES the output schema', block)
        self.assertIn('genre is the name of its interest', block)
        self.assertIn('spice and mmc', block)

    def test_an_all_romance_shelf_gets_the_same_override(self):
        block = curate.interests_block()
        self.assertIn('OVERRIDES the output schema', block)


if __name__ == '__main__':
    unittest.main()
