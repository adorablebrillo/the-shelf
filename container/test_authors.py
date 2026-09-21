#!/usr/bin/env python3
"""The author watch list — the server contract behind ticket #8's Authors tab.

Run: cd container && python3 -m unittest test_authors

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume.
"""
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix='shelf-authors-test-')
os.environ['CFG_DIR'] = TMP

import server  # noqa: E402


class AuthorsTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(server.AUTHORS):
            os.remove(server.AUTHORS)

    def test_blank_config_lists_nothing_and_writes_nothing(self):
        self.assertEqual(server.load_authors()['authors'], [])
        self.assertFalse(os.path.exists(server.AUTHORS))

    def test_add_appears_and_persists(self):
        lst, err = server.authors_add('Demo Author', 'romantasy')
        self.assertIsNone(err)
        self.assertEqual(lst, [{'name': 'Demo Author', 'lane': 'romantasy'}])
        # survived a reload from disk
        self.assertEqual(server.load_authors()['authors'], lst)

    def test_duplicate_answers_already_on_the_list(self):
        server.authors_add('Demo Author', None)
        lst, err = server.authors_add('  demo   author!! ', 'sport romance')
        self.assertEqual(err, 'author already on the list')
        self.assertEqual(len(lst), 1)
        self.assertIsNone(lst[0]['lane'])  # the first entry is untouched

    def test_add_needs_a_name(self):
        lst, err = server.authors_add('   ', 'romantasy')
        self.assertTrue(err)
        self.assertEqual(lst, [])
        self.assertFalse(os.path.exists(server.AUTHORS))

    def test_lane_is_optional(self):
        lst, _ = server.authors_add('No Lane', '')
        self.assertIsNone(lst[0]['lane'])
        lst2, _ = server.authors_add('With Lane', 'romantasy')
        self.assertEqual(lst2[1]['lane'], 'romantasy')

    def test_remove_takes_one_out_and_persists(self):
        server.authors_add('Keep Me', None)
        server.authors_add('Drop Me', 'romantasy')
        lst = server.authors_remove('drop me')
        self.assertEqual([a['name'] for a in lst], ['Keep Me'])
        self.assertEqual([a['name'] for a in server.load_authors()['authors']], ['Keep Me'])

    def test_remove_unknown_is_a_no_op(self):
        server.authors_add('Keep Me', None)
        lst = server.authors_remove('Nobody Here')
        self.assertEqual([a['name'] for a in lst], ['Keep Me'])


if __name__ == '__main__':
    unittest.main()
