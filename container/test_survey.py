#!/usr/bin/env python3
"""The book brew over the server (THS-37 piece 3) — the survey's two
doors: what the survey shows (GET /api/interests) and what it saves
(POST /api/interests). These tests own the intents:
  · a shelf whose file carries no surveyed day owes the survey, and the
    survey shows the three romance interests, already ticked;
  · the survey's answers are saved whole — the interests and their dials, the
    never list, the picks, the season goal — and the file carries the day it
    was answered;
  · the run's search words survive the survey's save;
  · the mix the page shows comes from the run's own split rule, not a second
    copy of it.
Run: cd container && python3 -m unittest test_survey -v

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume.
"""
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix='shelf-interests-test-')
os.environ['CFG_DIR'] = TMP

import server  # noqa: E402


def survey_body(**over):
    """The answers the survey posts: the reader's three romance interests,
    the never list she keeps, 12 picks an issue and no season goal."""
    body = {
        'name': 'The book brew',
        'picks': 12,
        'never': ['cowboys'],
        'season_goal': None,
        'surveyed': '2026-11-18',
        'interests': [
            {'id': 'sport', 'label': 'Sport romance', 'kind': 'story',
             'dial': 'into it', 'mode': 'new', 'reading': []},
            {'id': 'romantasy', 'label': 'Romantasy', 'kind': 'story',
             'dial': 'into it', 'mode': 'new', 'reading': []},
            {'id': 'contemp', 'label': 'Contemporary romance', 'kind': 'story',
             'dial': 'into it', 'mode': 'new', 'reading': []},
        ],
    }
    body.update(over)
    return body


class BlankInstallTests(unittest.TestCase):
    """A new install: the file is not there yet, so the survey is owed and
    the three romance interests come in ticked."""

    def setUp(self):
        if os.path.exists(server.INTERESTS):
            os.remove(server.INTERESTS)

    def test_a_blank_install_owes_the_survey(self):
        doc = server.load_interests()
        payload = server.interests_payload(doc)
        self.assertTrue(payload['need_survey'])
        self.assertIsNone(payload['surveyed'])
        self.assertEqual([i['label'] for i in payload['interests']],
                         ['Sport romance', 'Romantasy', 'Contemporary romance'])
        for i in payload['interests']:
            self.assertEqual(i['dial'], 'into it')
            self.assertEqual(i['mode'], 'new')
            self.assertTrue(i['romance'])

    def test_the_survey_shows_its_shelves(self):
        payload = server.interests_payload(server.load_interests())
        ids = [c['id'] for c in payload['catalog']]
        self.assertIn('baby', ids)
        self.assertIn('romantasy', ids)
        self.assertIn('thriller', ids)
        kinds = {c['id']: c['kind'] for c in payload['catalog']}
        self.assertEqual(kinds['baby'], 'topic')
        self.assertEqual(kinds['thriller'], 'story')

    def test_an_answered_file_owes_nothing(self):
        server.interests_save(survey_body())
        payload = server.interests_payload(server.load_interests())
        self.assertFalse(payload['need_survey'])
        self.assertEqual(payload['surveyed'], '2026-11-18')


class SurveySaveTests(unittest.TestCase):
    """What the survey writes: her answers, whole, in the file the run reads."""

    def setUp(self):
        if os.path.exists(server.INTERESTS):
            os.remove(server.INTERESTS)

    def test_the_survey_saves_her_answers(self):
        body = survey_body(season_goal=6)
        body['interests'].append({'id': 'baby', 'label': 'Baby development',
                                   'kind': 'topic', 'dial': 'obsessed', 'mode': 'both',
                                   'reading': [{'title': 'Cribsheet', 'author': 'Emily Oster'}]})
        server.interests_save(body)
        raw = json.loads(open(server.INTERESTS).read())
        self.assertEqual(raw['name'], 'The book brew')
        self.assertEqual(raw['picks'], 12)
        self.assertEqual(raw['never'], ['cowboys'])
        self.assertEqual(raw['season_goal'], 6)
        self.assertEqual(raw['surveyed'], '2026-11-18')
        baby = [i for i in raw['interests'] if i['id'] == 'baby'][0]
        self.assertEqual(baby['dial'], 'obsessed')
        self.assertEqual(baby['mode'], 'both')
        self.assertEqual(baby['reading'], [{'title': 'Cribsheet', 'author': 'Emily Oster'}])
        # a real-life topic is not a romance interest
        self.assertFalse(baby['romance'])

    def test_the_romance_interests_keep_the_romance_rules(self):
        server.interests_save(survey_body())
        raw = json.loads(open(server.INTERESTS).read())
        for i in raw['interests']:
            self.assertTrue(i['romance'])

    def test_a_typed_interest_is_a_topic(self):
        body = survey_body()
        body['interests'].append({'id': 'c-sourdough', 'label': 'Sourdough',
                                   'kind': 'topic', 'dial': 'into it', 'mode': 'both'})
        server.interests_save(body)
        raw = json.loads(open(server.INTERESTS).read())
        own = [i for i in raw['interests'] if i['id'] == 'c-sourdough'][0]
        self.assertEqual(own['kind'], 'topic')
        self.assertFalse(own['romance'])

    def test_a_bad_dial_or_mode_is_refused(self):
        body = survey_body()
        body['interests'][0]['dial'] = 'very much'
        body['interests'][1]['mode'] = 'forever'
        server.interests_save(body)
        raw = json.loads(open(server.INTERESTS).read())
        self.assertEqual(raw['interests'][0]['dial'], 'into it')
        self.assertEqual(raw['interests'][1]['mode'], 'new')

    def test_a_second_save_keeps_the_day_it_was_answered(self):
        """The Settings tab writes the same file without a date of its own —
        the survey's day stays."""
        server.interests_save(survey_body())
        body = survey_body()
        body.pop('surveyed')
        server.interests_save(body)
        raw = json.loads(open(server.INTERESTS).read())
        self.assertEqual(raw['surveyed'], '2026-11-18')

    def test_the_runs_search_words_survive_the_surveys_save(self):
        """The run gave a typed interest its words; the survey saves the same
        file — the words must not be lost."""
        doc = server.load_interests()
        doc['interests'].append({'id': 'baby', 'label': 'Baby development',
                                 'kind': 'topic', 'dial': 'into it', 'mode': 'both',
                                 'terms': ['baby development', 'infant sleep']})
        server.save_interests(doc)
        body = survey_body()
        body['interests'].append({'id': 'baby', 'label': 'Baby development',
                                   'kind': 'topic', 'dial': 'into it', 'mode': 'both'})
        server.interests_save(body)
        raw = json.loads(open(server.INTERESTS).read())
        baby = [i for i in raw['interests'] if i['id'] == 'baby'][0]
        self.assertEqual(baby.get('terms'), ['baby development', 'infant sleep'])


class HomeSeasonGoalTests(unittest.TestCase):
    """Her ruling on the season goal: a survey that skipped it gets the
    question on Home, and the answer sets only the goal — a topic's birth
    month, the run's search words and the survey's day stay as they were."""

    def setUp(self):
        if os.path.exists(server.INTERESTS):
            os.remove(server.INTERESTS)
        server.interests_save(survey_body())
        doc = server.load_interests()
        doc['interests'].append({'id': 'baby', 'label': 'Baby development',
                                 'kind': 'topic', 'dial': 'into it', 'mode': 'both',
                                 'birth': '2026-05', 'terms': ['infant sleep']})
        server.save_interests(doc)

    def test_homes_answer_sets_only_the_goal(self):
        before = json.loads(open(server.INTERESTS).read())
        doc, err = server.interests_set_season_goal({'season_goal': 4})
        self.assertIsNone(err)
        raw = json.loads(open(server.INTERESTS).read())
        self.assertEqual(raw['season_goal'], 4)
        before['season_goal'] = 4
        self.assertEqual(raw, before)
        self.assertEqual(server.interests_payload(doc)['season_goal'], 4)

    def test_a_book_brew_tab_save_keeps_homes_goal_and_the_birth(self):
        """The book brew tab sends no season goal: a dial change saved after
        Home set the goal must not put an older goal back, nor drop a topic's
        birth month."""
        server.interests_set_season_goal({'season_goal': 8})
        body = survey_body()
        body.pop('season_goal')
        body.pop('surveyed')
        body['interests'].append({'id': 'baby', 'label': 'Baby development',
                                  'kind': 'topic', 'dial': 'obsessed', 'mode': 'both'})
        server.interests_save(body)
        raw = json.loads(open(server.INTERESTS).read())
        self.assertEqual(raw['season_goal'], 8)
        baby = [i for i in raw['interests'] if i['id'] == 'baby'][0]
        self.assertEqual((baby['dial'], baby.get('birth')), ('obsessed', '2026-05'))

    def test_a_survey_that_skips_the_goal_clears_it(self):
        server.interests_set_season_goal({'season_goal': 8})
        server.interests_save(survey_body(season_goal=None))
        self.assertIsNone(json.loads(open(server.INTERESTS).read())['season_goal'])

    def test_the_runs_save_waits_for_the_servers_writers(self):
        """The run's search-word save is another process in production: it
        waits for the same lock as the server's writers and then reads the
        file again, so a goal Home saved meanwhile is not rolled back."""
        m = server._interests()
        # the run finds the file from CFG_DIR, as the server does; other test
        # modules point CFG_DIR elsewhere when the whole suite runs
        env = mock.patch.dict(os.environ, {'CFG_DIR': server.CONFIG_DIR})
        env.start()
        self.addCleanup(env.stop)
        run_doc = m.load()   # what the run read when it started
        for i in run_doc['interests']:
            if i['id'] == 'sport':
                i['terms'] = ['sports romance']
        done = threading.Event()
        with server.interests_locked():
            t = threading.Thread(target=lambda: (m.save_terms(run_doc, log=lambda *a: None), done.set()))
            t.start()
            self.assertFalse(done.wait(0.4), 'the run wrote while the server held the lock')
            doc = server.load_interests()
            doc['season_goal'] = 8
            server.save_interests(doc)
        self.assertTrue(done.wait(5))
        raw = json.loads(open(server.INTERESTS).read())
        self.assertEqual(raw['season_goal'], 8)
        self.assertEqual([i.get('terms') for i in raw['interests'] if i['id'] == 'sport'], [['sports romance']])

    def test_an_impossible_goal_is_refused_and_nothing_is_written(self):
        before = open(server.INTERESTS).read()
        for bad in (0, -3, 366, 'many', None, True, [6]):
            doc, err = server.interests_set_season_goal({'season_goal': bad})
            self.assertIsNone(doc, bad)
            self.assertTrue(err, bad)
        self.assertEqual(open(server.INTERESTS).read(), before)


class SplitTests(unittest.TestCase):
    """The mix the survey shows is the run's own rule — one definition."""

    def test_the_mix_follows_the_dials(self):
        draft = server.interests_from_body(survey_body())
        rows = server.interests_split(draft)
        self.assertEqual([(r['label'], r['n']) for r in rows],
                         [('Sport romance', 4), ('Romantasy', 4),
                          ('Contemporary romance', 4)])

    def test_a_turned_down_interest_gets_nothing(self):
        body = survey_body()
        body['interests'][1]['dial'] = 'off'
        draft = server.interests_from_body(body)
        rows = server.interests_split(draft)
        self.assertEqual([(r['label'], r['n']) for r in rows],
                         [('Sport romance', 6), ('Contemporary romance', 6)])

    def test_an_off_interest_is_not_in_the_mix(self):
        body = survey_body()
        for i in body['interests']:
            i['dial'] = 'off'
        draft = server.interests_from_body(body)
        self.assertEqual(server.interests_split(draft), [])


if __name__ == '__main__':
    unittest.main()
