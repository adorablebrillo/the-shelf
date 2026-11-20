#!/usr/bin/env python3
"""The book brew tab (THS-37 piece 2) — the server contract behind
/api/interests, shared with the survey (the other writer of these routes):
the page reads a payload the server shapes (never the raw file), saves
through the same helpers, and asks /api/interests/split for the mix the run
would pick.

Run: cd container && python3 -m unittest test_bookameter

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume.
"""
import json
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix='shelf-bookameter-test-')
os.environ['CFG_DIR'] = TMP

import server  # noqa: E402


def _clear():
    if os.path.exists(server.INTERESTS):
        os.remove(server.INTERESTS)


class LoadTests(unittest.TestCase):
    """A blank install: the tab reads the same defaults the run would make."""

    def setUp(self):
        _clear()

    def test_blank_volume_reads_the_default_book_brew(self):
        d = server.load_interests()
        self.assertEqual(d['name'], 'The book brew')
        self.assertEqual(d['picks'], 12)
        self.assertEqual(d['never'], ['cowboys'])
        self.assertEqual([i['label'] for i in d['interests']],
                         ['Sport romance', 'Romantasy', 'Contemporary romance'])
        self.assertFalse(os.path.exists(server.INTERESTS))

    def _volume_with_name(self, name):
        doc = server.load_interests()
        if name is None:
            doc.pop('name', None)
        else:
            doc['name'] = name
        server.save_interests(doc)
        return open(server.INTERESTS).read()

    def test_an_old_default_name_shows_the_new_name_and_the_file_is_untouched(self):
        raw = self._volume_with_name('Book-a-meter')
        self.assertEqual(server.interests_payload(server.load_interests())['name'], 'The book brew')
        self.assertEqual(open(server.INTERESTS).read(), raw)
        self.assertEqual(json.loads(raw)['name'], 'Book-a-meter')

    def test_a_file_with_no_name_shows_the_new_name(self):
        self._volume_with_name(None)
        self.assertEqual(server.interests_payload(server.load_interests())['name'], 'The book brew')

    def test_a_custom_name_is_kept_through_the_payload_and_a_save(self):
        self._volume_with_name('My taste')
        self.assertEqual(server.interests_payload(server.load_interests())['name'], 'My taste')
        doc = server.interests_save({'name': 'My taste', 'interests': []})
        self.assertEqual(doc['name'], 'My taste')

    def test_a_save_with_no_name_files_the_new_default(self):
        self.assertEqual(server.interests_save({'interests': []})['name'], 'The book brew')

    def test_the_payload_shapes_what_the_page_reads(self):
        p = server.interests_payload(server.load_interests())
        self.assertEqual(p['name'], 'The book brew')
        self.assertEqual(p['picks'], 12)
        self.assertEqual(p['never'], ['cowboys'])
        self.assertIsNone(p['season_goal'])
        self.assertIsNone(p['surveyed'])
        self.assertTrue(p['need_survey'])
        self.assertTrue(isinstance(p['catalog'], list))
        self.assertEqual([i['id'] for i in p['interests']], ['sport', 'romantasy', 'contemp'])
        first = p['interests'][0]
        self.assertEqual((first['label'], first['kind'], first['dial'], first['mode'], first['romance']),
                         ('Sport romance', 'story', 'into it', 'new', True))
        self.assertEqual(first['reading'], [])
        # the computed mix, by the same rule the run uses
        self.assertEqual([s['n'] for s in p['split']], [4, 4, 4])


class SaveTests(unittest.TestCase):
    """A save goes through the same helpers the survey uses: the page sends
    its answers, the server bounds them and writes the file the runs read."""

    def setUp(self):
        _clear()

    def test_save_round_trips_through_the_payload(self):
        doc = server.interests_save({
            'name': 'The book brew', 'picks': 9, 'never': ['graphic violence'],
            'surveyed': '2026-11-18',
            'interests': [
                {'id': 'sport', 'label': 'Sport romance', 'kind': 'story',
                 'dial': 'obsessed', 'mode': 'new'},
                {'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                 'dial': 'curious', 'mode': 'both',
                 'reading': [{'title': 'Cribsheet', 'author': 'Emily Oster'}]},
            ]})
        self.assertEqual(doc['surveyed'], '2026-11-18')
        self.assertEqual(server.load_interests(), doc)
        p = server.interests_payload(doc)
        self.assertFalse(p['need_survey'])
        self.assertEqual(p['picks'], 9)
        self.assertEqual(p['interests'][1]['reading'],
                         [{'title': 'Cribsheet', 'author': 'Emily Oster'}])
        # a later save without surveyed leaves the old date alone (a Settings
        # tab save must never un-answer the survey)
        doc2 = server.interests_save({'interests': doc['interests']})
        self.assertEqual(doc2['surveyed'], '2026-11-18')

    def test_junk_entries_are_skipped_and_defaults_fill_the_rest(self):
        doc = server.interests_save({
            'picks': 999, 'never': ['Cowboys & Westerns', '', 7],
            'interests': [
                {'id': 'sport', 'label': 'Sport romance', 'kind': 'weird',
                 'dial': 'zany', 'mode': 'sometimes'},
                {'id': 'x', 'label': ''},           # no name: skipped
                'not an interest',                  # skipped
                {'id': '', 'label': 'no id'},       # skipped
            ]})
        self.assertEqual(doc['picks'], 60)                       # clamped
        # a never word is a word: the loop keeps what survives the clean
        self.assertEqual(doc['never'], ['cowboys & westerns', '7'])
        self.assertEqual([i['id'] for i in doc['interests']], ['sport'])
        i = doc['interests'][0]
        self.assertEqual(i['kind'], 'topic')   # an unknown kind is a real-life topic
        self.assertEqual(i['dial'], 'into it')                   # the run's fallback
        self.assertEqual(i['mode'], 'both')    # a topic's mode is both by default
        self.assertTrue(i['romance'])                            # the catalog decides
        self.assertEqual(i['reading'], [])

    def test_search_words_already_on_the_volume_win(self):
        server.save_interests({'v': 1, 'name': 'The book brew', 'picks': 12,
                               'never': [], 'season_goal': None,
                               'interests': [{'id': 'baby', 'label': 'Baby development',
                                              'kind': 'topic', 'terms': ['infant sleep']}]})
        doc = server.interests_save({
            'interests': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic'}]})
        self.assertEqual(doc['interests'][0]['terms'], ['infant sleep'])

    def test_split_comes_from_the_same_rule_the_run_uses(self):
        server.interests_save({'picks': 12, 'interests': [
            {'id': 'sport', 'label': 'Sport romance', 'kind': 'story', 'dial': 'obsessed'},
            {'id': 'romantasy', 'label': 'Romantasy', 'kind': 'story', 'dial': 'curious'},
            {'id': 'baby', 'label': 'Baby development', 'kind': 'topic', 'dial': 'off'}]})
        r = server.interests_split(server.load_interests())
        self.assertEqual([(s['id'], s['n']) for s in r], [('sport', 9), ('romantasy', 3)])

    def test_interest_name_resolves_id_and_label(self):
        server.interests_save({'interests': [
            {'id': 'baby', 'label': 'Baby development', 'kind': 'topic'}]})
        self.assertEqual(server._interest_name('baby'), 'baby development')
        self.assertEqual(server._interest_name('Baby Development'), 'baby development')
        self.assertEqual(server._interest_name('sourdough'), 'sourdough')  # unknown stays
        self.assertEqual(server._interest_name(''), '')


if __name__ == '__main__':
    unittest.main()
