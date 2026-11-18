#!/usr/bin/env python3
"""The build ships books she added by search (ticket #84).

Run: cd pipeline && python3 -m unittest test_added

The record is the one the server writes for the real saved Apple search result
(testdata/apple-search-fourthwing.json). Its cover is already in the volume's cover
cache, so the build stays offline.
"""
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ['CFG_DIR'] = tempfile.mkdtemp(prefix='shelf-added-')

import build  # noqa: E402
from bookids import book_key  # noqa: E402

ITEM = json.load(open(os.path.join(HERE, 'testdata', 'apple-search-fourthwing.json')))['results'][0]


class AddedShipTests(unittest.TestCase):
    def setUp(self):
        self.covers = tempfile.mkdtemp(prefix='shelf-covers-')
        self.rec = {'id': book_key(ITEM['trackName'], ITEM['artistName']),
                    'title': ITEM['trackName'], 'author': ITEM['artistName'],
                    'date': ITEM['releaseDate'][:10], 'img': '',
                    'genre': ' '.join(ITEM.get('genres', [])[:3]), 'appleId': str(ITEM['trackId']),
                    'url': ITEM['trackViewUrl'].split('?')[0],
                    'series': 'The Empyrean', 'series_num': '1', 'added': '2026-11-16'}
        with open(os.path.join(os.environ['CFG_DIR'], 'added-books.json'), 'w') as f:
            json.dump({'v': 1, 'books': [self.rec, dict(self.rec)]}, f)
        cached = build.slug({'title': self.rec['title'], 'author': self.rec['author']}) + '.jpg'
        with open(os.path.join(self.covers, cached), 'wb') as f:
            f.write(b'\xff\xd8' + b'0' * 2000)
        self.cached = 'assets/covers/' + cached

    def test_ships_each_added_book_once_with_its_identity(self):
        got = build.added_data(self.covers)
        self.assertEqual(len(got), 1)
        b = got[0]
        self.assertEqual(b['id'], book_key(ITEM['trackName'], ITEM['artistName']))
        self.assertTrue(b['added'])
        self.assertEqual((b['title'], b['author']), (ITEM['trackName'], ITEM['artistName']))
        # the card's series line follows the picks' rule ('The Empyrean #1')
        self.assertEqual((b['series'], b['seriesNum']), (build.pick_series(self.rec), '1'))
        self.assertEqual(b['img'], self.cached)

    def test_an_imported_goodreads_book_id_ships_as_the_books_own_page(self):
        # THS-16 keeps the export's Book Id as `gr`; the link opens that page
        self.rec['gr'] = '61431922'
        with open(os.path.join(os.environ['CFG_DIR'], 'added-books.json'), 'w') as f:
            json.dump({'v': 1, 'books': [self.rec]}, f)
        self.assertEqual(build.added_data(self.covers)[0]['grUrl'],
                         'https://www.goodreads.com/book/show/61431922')

    def test_a_book_without_a_book_id_ships_no_goodreads_page(self):
        self.assertNotIn('grUrl', build.added_data(self.covers)[0])

    def test_no_file_ships_nothing(self):
        os.remove(os.path.join(os.environ['CFG_DIR'], 'added-books.json'))
        self.assertEqual(build.added_data(self.covers), [])


if __name__ == '__main__':
    unittest.main()
