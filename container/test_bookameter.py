#!/usr/bin/env python3
"""The Book-a-meter tab (THS-37 piece 2) — the server contract behind
/api/interests: the doc the runs read (pipeline/interests.py owns its shape)
is what the tab reads, and a save from the tab writes the same shape or
nothing at all.

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


def _vol():
    """The file the runs and the tab share, wherever this process's CFG_DIR
    points (several test modules set it in one process — the module constant
    of server may not match, but the pipeline resolves the env at call time)."""
    return server._pipeline_import('interests').vol_path()


class LoadTests(unittest.TestCase):
    """A blank install: the tab reads the same defaults the run would make."""

    def setUp(self):
        if os.path.exists(_vol()):
            os.remove(_vol())

    def test_blank_volume_reads_the_default_book_a_meter(self):
        d = server.load_interests()
        self.assertEqual(d['name'], 'Book-a-meter')
        self.assertEqual(d['picks'], 12)
        self.assertEqual(d['never'], ['cowboys'])
        self.assertEqual([i['label'] for i in d['interests']],
                         ['Sport romance', 'Romantasy', 'Contemporary romance'])
        self.assertFalse(os.path.exists(_vol()))

    def test_round_trip(self):
        doc, err = server.save_interests({
            'name': 'Book-a-meter', 'picks': 9, 'never': ['graphic violence'],
            'interests': [
                {'id': 'sport', 'label': 'Sport romance', 'kind': 'story',
                 'dial': 'obsessed', 'mode': 'new', 'romance': True},
                {'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                 'dial': 'curious', 'mode': 'both'},
            ]})
        self.assertIsNone(err)
        self.assertEqual(server.load_interests(), doc)
        on_disk = json.load(open(_vol()))
        self.assertEqual(on_disk, doc)


class SaveTests(unittest.TestCase):
    """A save from the tab is checked before it reaches the file a run reads:
    a bad save writes nothing."""

    def setUp(self):
        if os.path.exists(_vol()):
            os.remove(_vol())

    def test_a_bad_save_writes_nothing(self):
        for bad in (
            {},                                   # no interests list
            {'interests': 'sport'},               # not a list
            {'interests': [{'id': 'x', 'label': ''}]},       # no name
            {'interests': [{'id': 'x', 'label': 'A'}, {'id': 'x', 'label': 'B'}]},  # duplicate
            {'interests': ['sport']},             # an interest is not a string
        ):
            doc, err = server.save_interests(bad)
            self.assertIsNone(doc)
            self.assertTrue(err, str(bad))
            self.assertFalse(os.path.exists(_vol()))

    def test_known_fields_are_checked_and_defaults_fill_the_rest(self):
        doc, err = server.save_interests({
            'picks': 999, 'never': ['Cowboys & Westerns', '', 7],
            'season_goal': None,
            'interests': [{'id': 'x', 'label': 'Sourdough', 'kind': 'weird',
                           'dial': 'zany', 'mode': 'sometimes', 'romance': 'yes'}]})
        self.assertIsNone(err)
        self.assertEqual(doc['picks'], 60)                # clamped to the ceiling
        self.assertEqual(doc['never'], ['cowboys & westerns'])
        self.assertIsNone(doc['season_goal'])
        i = doc['interests'][0]
        self.assertEqual(i['kind'], 'story')              # the only other kind
        self.assertNotIn('dial', i)                       # junk never reaches the file
        self.assertNotIn('mode', i)
        self.assertNotIn('romance', i)
        # the run reads the doc with its own fallbacks, so a missing dial or
        # mode is the default: "into it", new
        import interests
        self.assertEqual(interests.dial(i), 'into it')
        self.assertEqual(interests.mode(i), 'new')
        self.assertFalse(interests.romance(i))

    def test_unknown_keys_ride_along_for_the_next_piece(self):
        doc, err = server.save_interests({
            'interests': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                           'follow_age': True, 'age_months': 5}]})
        self.assertIsNone(err)
        self.assertEqual(doc['interests'][0]['follow_age'], True)
        self.assertEqual(doc['interests'][0]['age_months'], 5)

    def test_terms_are_kept_as_a_short_word_list(self):
        doc, err = server.save_interests({
            'interests': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                           'terms': ['baby sleep', 'infant development', '', None, 'x' * 100]}]})
        self.assertIsNone(err)
        self.assertEqual(doc['interests'][0]['terms'], ['baby sleep', 'infant development', 'x' * 60])

    def test_interest_name_resolves_id_and_label(self):
        doc, _ = server.save_interests({
            'interests': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic'}]})
        self.assertEqual(server._interest_name('baby'), 'baby development')
        self.assertEqual(server._interest_name('Baby Development'), 'baby development')
        self.assertEqual(server._interest_name('sourdough'), 'sourdough')  # unknown stays
        self.assertEqual(server._interest_name(''), '')


if __name__ == '__main__':
    unittest.main()
