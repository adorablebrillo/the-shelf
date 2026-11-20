#!/usr/bin/env python3
"""Add a book by search (ticket #84) — the server contract behind the
"add a book" panel: /api/search, and /api/books add, list and remove.

Run: cd container && python3 -m unittest test_books

CFG_DIR must be set BEFORE importing server (the module resolves its config
paths at import time), so the suite runs against a throwaway volume. Apple is
never called: the stand-in reader serves a real saved search response
(pipeline/testdata/apple-search-fourthwing.json, descriptions dropped) and a
real saved Apple book page,
trimmed to its schema block and series breadcrumb
(pipeline/testdata/apple-page-fourthwing.html).
"""
import json
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix='shelf-books-test-')
os.environ['CFG_DIR'] = TMP

import server  # noqa: E402

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline', 'testdata')
SEARCH = open(os.path.join(TESTDATA, 'apple-search-fourthwing.json')).read()
ITEM = json.loads(SEARCH)['results'][0]
PAGE = open(os.path.join(TESTDATA, 'apple-page-fourthwing.html')).read()
BOOK_KEY = server._pipeline_import('bookids').book_key


class Reader:
    """Stands in for the network: answers Apple's search and book page, and
    records every URL asked for."""

    def __init__(self):
        self.urls = []

    def __call__(self, url, timeout=20):
        self.urls.append(url)
        if url.startswith('https://itunes.apple.com/search?'):
            return SEARCH
        if url.startswith('https://books.apple.com/'):
            return PAGE
        raise AssertionError('unexpected fetch: ' + url)


class SearchTests(unittest.TestCase):
    def test_results_carry_what_the_panel_shows(self):
        rd = Reader()
        res = server.search_books('fourth wing', get_text=rd)
        # Apple answers 12 results with three editions of Fourth Wing: the
        # panel shows at most 10 rows, one per book
        ids = [x['id'] for x in res]
        self.assertLessEqual(len(res), 10)
        self.assertEqual(len(ids), len(set(ids)))
        r = res[0]
        self.assertEqual(r['id'], BOOK_KEY(ITEM['trackName'], ITEM['artistName']))
        self.assertEqual((r['title'], r['author']), (ITEM['trackName'], ITEM['artistName']))
        self.assertEqual(r['date'], ITEM['releaseDate'][:10])
        self.assertEqual(r['appleId'], str(ITEM['trackId']))
        self.assertIn('600x600bb', r['cover'])
        self.assertEqual(r['url'], ITEM['trackViewUrl'].split('?')[0])
        self.assertIn('country=' + server.apple_country(), rd.urls[0])
        self.assertIn('media=ebook', rd.urls[0])

    def test_empty_query_asks_apple_nothing(self):
        rd = Reader()
        self.assertEqual(server.search_books('   ', get_text=rd), [])
        self.assertEqual(rd.urls, [])


class AddedBooksTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(server.ADDED):
            os.remove(server.ADDED)
        self.hit = server.search_books('fourth wing', get_text=Reader())[0]

    def test_blank_config_lists_nothing_and_writes_nothing(self):
        self.assertEqual(server.load_added()['books'], [])
        self.assertFalse(os.path.exists(server.ADDED))

    def test_add_reads_series_once_and_persists(self):
        rd = Reader()
        rec, err = server.added_add(self.hit, get_text=rd)
        self.assertIsNone(err)
        self.assertEqual(rec['id'], self.hit['id'])
        self.assertEqual((rec['series'], rec['series_num']), ('The Empyrean', '1'))
        self.assertEqual(rec['img'], self.hit['cover'])
        on_disk = json.load(open(server.ADDED))['books']
        self.assertEqual([b['id'] for b in on_disk], [self.hit['id']])
        # adding the same book again keeps one record and reads no page
        again, err = server.added_add(self.hit, get_text=rd)
        self.assertIsNone(err)
        self.assertEqual(again, rec)
        self.assertEqual(len(server.load_added()['books']), 1)
        self.assertEqual(len([u for u in rd.urls if u.startswith('https://books.apple.com/')]), 1)

    def test_remove_takes_it_off_the_list(self):
        server.added_add(self.hit, get_text=Reader())
        self.assertEqual(server.added_remove(self.hit['id']), [])
        self.assertEqual(server.load_added()['books'], [])

    def test_only_apple_book_pages_are_fetched(self):
        rd = Reader()
        hit = dict(self.hit, url='http://169.254.169.254/latest/meta-data')
        rec, err = server.added_add(hit, get_text=rd)
        self.assertIsNone(err)
        self.assertEqual(rd.urls, [])
        self.assertEqual(rec['series'], '')

    def test_a_book_needs_a_title_and_an_author(self):
        rec, err = server.added_add({'title': 'Fourth Wing'}, get_text=Reader())
        self.assertIsNone(rec)
        self.assertTrue(err)
        self.assertFalse(os.path.exists(server.ADDED))


class InterestFilingTests(unittest.TestCase):
    """THS-37 piece 2: the book brew tab's "+ add a book" saves an added
    book with an interest field and the reading-now flag. The flag rides the
    same reading channel (#57) as a verdict-row press."""

    def setUp(self):
        for f in (server.ADDED, server.STATE, server.INTERESTS):
            if os.path.exists(f):
                os.remove(f)
        self.hit = server.search_books('fourth wing', get_text=Reader())[0]

    def test_add_under_an_interest_files_it_and_marks_reading_now(self):
        rec, err = server.added_add(dict(self.hit, interest='sport', reading=True), get_text=Reader())
        self.assertIsNone(err)
        # the tab sends the interest's id; the record keeps the run's name
        self.assertEqual(rec['interest'], 'sport romance')
        st = server.load_state()
        self.assertEqual(st['states'][rec['id']]['s'], 'want')   # reading now = want + flag
        self.assertTrue(st['reading'][rec['id']]['s'])

    def test_add_without_interest_or_reading_leaves_state_alone(self):
        rec, err = server.added_add(self.hit, get_text=Reader())
        self.assertIsNone(err)
        self.assertNotIn('interest', rec)
        self.assertFalse(os.path.exists(server.STATE))

    def test_readding_files_a_book_that_has_no_interest_yet(self):
        first, _ = server.added_add(self.hit, get_text=Reader())
        self.assertNotIn('interest', first)
        again, err = server.added_add(dict(self.hit, interest='romantasy', reading=True), get_text=Reader())
        self.assertIsNone(err)
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(again['interest'], 'romantasy')
        st = server.load_state()
        self.assertEqual(st['states'][again['id']]['s'], 'want')
        self.assertTrue(st['reading'][again['id']]['s'])

    def test_a_book_already_under_another_interest_stays_there(self):
        first, _ = server.added_add(dict(self.hit, interest='baby'), get_text=Reader())
        again, err = server.added_add(dict(self.hit, interest='sport'), get_text=Reader())
        self.assertIsNone(err)
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(again['interest'], 'baby')
        self.assertEqual(len(server.load_added()['books']), 1)


if __name__ == '__main__':
    unittest.main()
