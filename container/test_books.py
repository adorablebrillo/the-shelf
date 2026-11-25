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
(pipeline/testdata/apple-page-fourthwing.html). Goodreads is never called
either: the stand-in serves its real saved search page for "fourth wing"
(gr-search-next-fourth-wing.html) and a real saved book page
(gr-book-243596193.html, Riley Sager's The Unknown).
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
GR_SEARCH = open(os.path.join(TESTDATA, 'gr-search-next-fourth-wing.html')).read()
GR_PAGE = open(os.path.join(TESTDATA, 'gr-book-243596193.html')).read()
APPLE_NONE = '{"resultCount":0,"results":[]}'   # Apple's own answer when nothing matches
BOOK_KEY = server._pipeline_import('bookids').book_key
UNKNOWN = {'title': 'The Unknown', 'author': 'Riley Sager', 'gr': '243596193', 'source': 'goodreads'}


class Reader:
    """Stands in for the network: answers Apple's search and book page and
    Goodreads' search and book page, and records every URL asked for. A
    keyword sets what one place answers; an Exception value is raised."""

    def __init__(self, apple=SEARCH, goodreads=GR_SEARCH, gr_page=GR_PAGE):
        self.urls = []
        self.apple, self.goodreads, self.gr_page = apple, goodreads, gr_page

    def __call__(self, url, timeout=20):
        self.urls.append(url)
        if url.startswith('https://itunes.apple.com/search?'):
            ans = self.apple
        elif url.startswith('https://books.apple.com/'):
            ans = PAGE
        elif url.startswith('https://www.goodreads.com/search?'):
            ans = self.goodreads
        elif url.startswith('https://www.goodreads.com/book/show/'):
            ans = self.gr_page
        else:
            raise AssertionError('unexpected fetch: ' + url)
        if isinstance(ans, Exception):
            raise ans
        return ans


def search(q, rd=None):
    rd = rd or Reader()
    return server.search_books(q, get_text=rd, get_page=rd)


# the page Goodreads serves a client it takes for a bot: ~2 KB, no results
CHALLENGE = '<html><script>window.awsWafCookieDomainList = []; window.gokuProps = {}</script></html>'


class SearchTests(unittest.TestCase):
    def test_results_carry_what_the_panel_shows(self):
        rd = Reader()
        res = search('fourth wing', rd)
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
        apple_url = [u for u in rd.urls if u.startswith('https://itunes.apple.com/')][0]
        self.assertIn('country=' + server.apple_country(), apple_url)
        self.assertIn('media=ebook', apple_url)

    def test_empty_query_asks_apple_nothing(self):
        rd = Reader()
        self.assertEqual(search('   ', rd), [])
        self.assertEqual(rd.urls, [])


class AddedBooksTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(server.ADDED):
            os.remove(server.ADDED)
        self.hit = search('fourth wing')[0]

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


class GoodreadsSearchTests(unittest.TestCase):
    """THS-114 part 2: a Kindle-only book is not in Apple Books, so every
    search also asks Goodreads and lists the books Apple lacks."""

    def test_a_book_apple_lacks_comes_from_goodreads_with_its_id_and_series(self):
        res = search('fourth wing', Reader(apple=APPLE_NONE))
        first = res[0]
        self.assertEqual((first['title'], first['author']), ('Fourth Wing', 'Rebecca Yarros'))
        self.assertEqual(first['source'], 'goodreads')
        self.assertEqual(first['gr'], '61431922')   # the real edition: the first row is a stub edition
        self.assertEqual((first['series'], first['series_num']), ('The Empyrean', '1'))
        self.assertEqual(first['id'], BOOK_KEY('Fourth Wing', 'Rebecca Yarros'))

    def test_goodreads_noise_is_left_out_and_each_book_is_listed_once(self):
        res = search('fourth wing', Reader(apple=APPLE_NONE))
        titles = [r['title'] for r in res]
        self.assertNotIn('Study Guide: Fourth Wing by Rebecca Yarros', titles)   # a study guide
        self.assertFalse([t for t in titles if t.startswith('Fourth wing: Rebecca Yarros')])   # no writer
        self.assertNotIn('Fourth Wing by Rebecca Yarros', titles)   # the title repeats the author
        ids = [r['id'] for r in res]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len(res), server.GOODREADS_ROWS)

    def test_a_book_apple_lists_is_not_listed_twice(self):
        res = search('fourth wing')
        self.assertEqual([r['id'] for r in res].count(BOOK_KEY('Fourth Wing', 'Rebecca Yarros')), 1)
        self.assertNotIn('source', res[0])    # Apple's row stays first, as before

    def test_goodreads_rows_follow_apples_unless_the_title_is_the_one_typed(self):
        rd = Reader(apple=json.dumps({'results': [
            {'trackName': 'Down Bad', 'artistName': 'Deborah Collins', 'releaseDate': '2015-04-07T00:00:00Z'},
            {'trackName': 'Fourth Wing', 'artistName': 'Rebecca Yarros', 'releaseDate': '2023-05-02T00:00:00Z'}]}))
        res = search('fourth wing', rd)
        self.assertEqual([r['title'] for r in res][:2], ['Fourth Wing', 'Down Bad'])

    def test_goodreads_failing_leaves_apples_rows_and_says_so(self):
        for bad in (CHALLENGE, RuntimeError('timed out')):
            rows, ok = server.search_all('fourth wing', get_text=Reader(), get_page=Reader(goodreads=bad))
            self.assertFalse(ok)
            self.assertEqual(rows, server._apple_rows('fourth wing', Reader()))

    def test_a_real_goodreads_no_match_is_not_a_failure(self):
        with open(os.path.join(TESTDATA, 'gr-search-next-no-results.html')) as f:
            none = f.read()
        rows, ok = server.search_all('zzqx', get_text=Reader(apple=APPLE_NONE),
                                     get_page=Reader(goodreads=none))
        self.assertEqual((rows, ok), ([], True))

    def test_apple_failing_still_lists_goodreads_books(self):
        res = search('fourth wing', Reader(apple=RuntimeError('503')))
        self.assertEqual(res[0]['source'], 'goodreads')

    def test_both_failing_raises_so_the_panel_says_the_search_failed(self):
        rd = Reader(apple=RuntimeError('503'), goodreads=CHALLENGE)
        with self.assertRaises(RuntimeError):
            search('fourth wing', rd)


class GoodreadsAddTests(unittest.TestCase):
    def setUp(self):
        for f in (server.ADDED, server.STATE):
            if os.path.exists(f):
                os.remove(f)

    def test_adding_a_goodreads_book_keeps_its_id_and_reads_its_page_once(self):
        rd = Reader()
        rec, err = server.added_add(dict(UNKNOWN, series='A Series', series_num='2'), get_text=rd, get_page=rd)
        self.assertIsNone(err)
        self.assertEqual(rec['gr'], '243596193')
        self.assertEqual(rec['id'], BOOK_KEY('The Unknown', 'Riley Sager'))
        self.assertEqual(rec['date'], '2026-08-04')          # from its page
        self.assertTrue(rec['img'].startswith('https://'))   # its cover, from its page
        self.assertIn('Thriller', rec['genre'])
        self.assertEqual((rec['url'], rec['appleId']), ('', ''))
        self.assertEqual((rec['series'], rec['series_num']), ('A Series', '2'))
        self.assertEqual(rd.urls, ['https://www.goodreads.com/book/show/243596193'])
        again, _ = server.added_add(UNKNOWN, get_text=rd, get_page=rd)
        self.assertEqual(again, rec)
        self.assertEqual(len(rd.urls), 1)
        self.assertEqual(json.load(open(server.ADDED))['books'][0]['gr'], '243596193')

    def test_the_page_failing_still_saves_the_book_without_a_date_or_cover(self):
        rd = Reader(gr_page=CHALLENGE)
        rec, err = server.added_add(UNKNOWN, get_text=rd, get_page=rd)
        self.assertIsNone(err)
        self.assertEqual((rec['date'], rec['img'], rec['gr']), ('', '', '243596193'))

    def test_a_goodreads_book_files_on_my_shelf_as_reading_now(self):
        rd = Reader()
        rec, err = server.added_add(dict(UNKNOWN, reading=True), get_text=rd, get_page=rd)
        self.assertIsNone(err)
        self.assertEqual(server.load_state()['states'][rec['id']]['s'], 'want')

    def test_only_a_goodreads_book_page_is_ever_read(self):
        rd = Reader()
        rec, _ = server.added_add(dict(UNKNOWN, gr='243596193/../../9', url='http://169.254.169.254/'),
                                  get_text=rd, get_page=rd)
        self.assertEqual(rec['gr'], '2435961939')      # digits only: the path trick is gone
        self.assertEqual(rd.urls, ['https://www.goodreads.com/book/show/2435961939'])


class InterestFilingTests(unittest.TestCase):
    """THS-37 piece 2: the book brew tab's "+ add a book" saves an added
    book with an interest field and the reading-now flag. The flag rides the
    same reading channel (#57) as a verdict-row press."""

    def setUp(self):
        for f in (server.ADDED, server.STATE, server.INTERESTS):
            if os.path.exists(f):
                os.remove(f)
        self.hit = search('fourth wing')[0]

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
