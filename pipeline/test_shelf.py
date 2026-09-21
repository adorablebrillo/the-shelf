#!/usr/bin/env python3
"""Ticket #7 — your shelf steers the engine. Deterministic tests.
Run from pipeline/:  python3 -m unittest test_shelf -v
"""
import glob, json, os, tempfile, unittest

import shelf_state
from bookids import book_key
from shelf_state import exclusion_set, exclude_by_shelf


def write(d, name, obj):
    open(os.path.join(d, name), 'w').write(json.dumps(obj))


class KeyTests(unittest.TestCase):
    def test_parentheticals_and_punctuation_collapse(self):
        self.assertEqual(book_key('Onyx Storm (Empyrean #3)', 'Rebecca Yarros'),
                         book_key('Onyx Storm', 'Rebecca Yarros'))
        self.assertEqual(book_key('J.K. MacLaren Book', 'A'),
                         book_key('J K MacLaren Book', 'A'))
        self.assertEqual(book_key('', 'A'), '')
        self.assertEqual(book_key('Connie\xa0Kitson Title', 'Connie\xa0Kitson'),
                         book_key('Connie Kitson Title', 'Connie Kitson'))

    def test_semicolon_suffix(self):
        self.assertEqual(book_key('Some Title; a note', 'A'), book_key('Some Title', 'A'))


class ExclusionSetTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self._old = os.environ.get('CFG_DIR')
        os.environ['CFG_DIR'] = self.d

    def tearDown(self):
        if self._old is None:
            os.environ.pop('CFG_DIR', None)
        else:
            os.environ['CFG_DIR'] = self._old

    def test_marks_and_library(self):
        write(self.d, 'reader-state.json', {'v': 2, 'states': {
            'skipped--author': {'s': 'skip', 't': 1},
            'readbook--author': {'s': 'read', 't': 2},
            'lovedbook--author': {'s': 'loved', 't': 3},
            'wanted--author': {'s': 'want', 't': 4},
            'tombstoned--author': None}})
        write(self.d, 'library.json', {'series': [{'name': 'S', 'author': 'Lib Author',
                                                   'books': ['A Read Volume (#1)']}]})
        ex = exclusion_set(self.d)
        self.assertEqual(ex['skipped--author'], 'not for me')
        self.assertEqual(ex['readbook--author'], 'read')
        self.assertEqual(ex['lovedbook--author'], 'read')
        self.assertNotIn('wanted--author', ex)
        self.assertNotIn('tombstoned--author', ex)
        self.assertIn(book_key('A Read Volume', 'Lib Author'), ex)

    def test_blank_volume_excludes_nothing(self):
        self.assertEqual(exclusion_set(self.d), {})


class ExcludeTests(unittest.TestCase):
    def test_counts_and_keeps_the_clean(self):
        ex = {'skipped--author': 'not for me', 'readbook--author': 'read'}
        books = [{'title': 'Skipped', 'author': 'Author'},
                 {'title': 'Readbook', 'author': 'Author'},
                 {'title': 'Fresh', 'author': 'Author'}]
        kept, c = exclude_by_shelf(books, ex)
        self.assertEqual([b['title'] for b in kept], ['Fresh'])
        self.assertEqual(c, {'total': 2, 'not_for_me': 1, 'read': 1})

    def test_a_read_sequel_never_returns(self):
        # the library's read volume and the candidate share the canonical id
        # even when one carries a series parenthetical
        lib_key = book_key('Onyx Storm', 'Rebecca Yarros')
        cand = {'title': 'Onyx Storm (Empyrean #3)', 'author': 'Rebecca Yarros'}
        kept, c = exclude_by_shelf([cand], {lib_key: 'read'})
        self.assertEqual(kept, [])
        self.assertEqual(c['read'], 1)

    def test_no_title_is_never_excluded(self):
        kept, c = exclude_by_shelf([{'title': '', 'author': 'A'}], {'--a': 'read'})
        self.assertEqual(len(kept), 1)
        self.assertEqual(c['total'], 0)

    def test_real_candidates_file(self):
        fs = sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'data', 'candidates-*.json')))
        if not fs:
            self.skipTest('no candidates file')
        books = json.load(open(fs[-1])).get('books') or []
        if not books:
            self.skipTest('empty candidates')
        b = books[0]
        ex = {book_key(b['title'], b['author']): 'not for me'}
        kept, c = exclude_by_shelf(books, ex)
        self.assertEqual(len(kept), len(books) - 1)
        self.assertEqual(c['not_for_me'], 1)


if __name__ == '__main__':
    unittest.main()
