#!/usr/bin/env python3
"""The Goodreads new-release lists, one per interest (releases.py).

Run: cd pipeline && python3 -m unittest test_releases

Fixtures are real pages saved 2026-11 (the sports-romance list, trimmed to its
first eight books; the Goodreads genre that lists none; two book pages; Apple's
answer for Fourth Wing). The intents under test:

  - Apple first, the book's Goodreads page otherwise, and a page-sourced book
    keeps the 100-rating proof (the goal)
  - best-effort: Goodreads or the pool file failing never fails the run
  - book pages are cached, capped, and end at Goodreads' bot check (a measured
    limit, synopses.py)
  - a typed interest's Goodreads genre is asked of the curator once and kept
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

os.environ.setdefault('CFG_DIR', tempfile.mkdtemp(prefix='shelf-rel-test-'))

import fetch  # noqa: E402
import filter as flt  # noqa: E402
import interests  # noqa: E402
import reference  # noqa: E402
import releases  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
read = lambda n: open(os.path.join(HERE, 'testdata', n), encoding='utf-8').read()
LIST = read('gr-genre-new_releases-sports-romance.html')
EMPTY = read('gr-genre-new_releases-baby-empty.html')
BOOK = read('gr-book-243596193.html')
NO_LINE_CHANGE = read('gr-book-254939637.html')      # a list entry's own page: no publisher on record, 4.39 from 378
APPLE = json.load(open(os.path.join(HERE, 'testdata', 'apple-search-fourthwing.json')))['results']
# Goodreads' bot check, as test_synopses saves it: a short body with the AWS WAF markers
CHALLENGE = ('<html><head><script>window.awsWafCookieDomainList = [];'
             'window.gokuProps = {"key":"AQID"};</script></head><body></body></html>')


class ParseGenreListTests(unittest.TestCase):
    def setUp(self):
        self.entries = releases.parse_genre_list(LIST)

    def test_the_real_list_parses(self):
        self.assertEqual(len(self.entries), 8)
        keeper = self.entries[0]
        self.assertEqual(keeper['id'], '239708533')
        self.assertEqual(keeper['author'], 'Ana Huang')
        self.assertEqual(keeper['url'], 'https://www.goodreads.com/book/show/239708533-the-keeper')
        self.assertEqual((keeper['rating'], keeper['rating_count']), (3.96, 14643))

    def test_the_series_tag_is_not_part_of_the_name(self):
        keeper = self.entries[0]
        self.assertEqual(keeper['title'], 'The Keeper (Gods of the Game, #3)')
        self.assertEqual(keeper['name'], 'The Keeper')
        self.assertEqual(releases.strip_series('One Moore Time'), 'One Moore Time')
        self.assertEqual(releases.strip_series('One True Annoyance (Vinewood U #1)'), 'One True Annoyance')

    def test_a_genre_with_no_books_and_a_markup_change_give_no_list(self):
        self.assertEqual(releases.parse_genre_list(EMPTY), [])
        self.assertEqual(releases.parse_genre_list('<html>changed</html>'), [])
        self.assertEqual(releases.parse_genre_list(None), [])


class InterestSlugTests(unittest.TestCase):
    def test_catalog_interests_have_a_fixed_genre_and_typed_ones_none(self):
        self.assertEqual(interests.gr_slug({'id': 'sport'}), 'sports-romance')
        self.assertEqual(interests.gr_slug({'id': 'x1', 'label': 'Hockey romance'}), '')

    def test_the_slug_a_file_keeps_wins_and_a_bad_one_is_never_used(self):
        self.assertEqual(interests.gr_slug({'id': 'sport', 'gr_slug': 'hockey-romance'}), 'hockey-romance')
        for bad in ('../x', 'a b', 'UP', 'x' * 41, 7, ''):
            self.assertEqual(interests.gr_slug({'id': 'x1', 'gr_slug': bad}), '')


def entry(i=0):
    return releases.parse_genre_list(LIST)[i]


class CandidateTests(unittest.TestCase):
    """Apple's record when it has one with a date, else the Goodreads page."""

    def setUp(self):
        self._orig = (fetch.search, fetch.resolve_product, reference._get)
        fetch.search = lambda term, limit=100: APPLE
        fetch.resolve_product = lambda rec, cache: None
        reference._get = lambda url, timeout=0: BOOK

    def tearDown(self):
        fetch.search, fetch.resolve_product, reference._get = self._orig

    def reader(self):
        return releases.Reader({}, sleep=lambda s: None)

    def test_an_apple_record_comes_first_and_no_goodreads_page_is_read(self):
        e = dict(entry(), name='Fourth Wing', author='Rebecca Yarros')
        r = self.reader()
        c, via, why = releases.candidate_for(e, 'romantasy', 'romantasy', '2026-11', {}, r, lambda: True)
        self.assertEqual((via, why), ('apple', ''))
        self.assertEqual(c['pub_source'], 'apple-search')
        self.assertEqual((c['lane'], c['lanes']), ('romantasy', ['romantasy']))
        self.assertEqual(c['found_by'], ['goodreads-genre:romantasy'])
        self.assertEqual(r.reads, 0)

    def test_with_no_apple_match_the_goodreads_page_makes_the_candidate(self):
        fetch.search = lambda term, limit=100: []
        e = dict(entry(), id='243596193', name='The Unknown', author='Riley Sager',
                 url='https://www.goodreads.com/book/show/243596193-the-unknown')
        r = self.reader()
        c, via, why = releases.candidate_for(e, 'sport romance', 'sports-romance', '2026-11', {}, r, lambda: True)
        self.assertEqual((via, why), ('goodreads-page', ''))
        self.assertEqual(c['pub_source'], 'goodreads-page')
        self.assertEqual(c['title'], 'The Unknown')
        self.assertEqual((c['lane'], c['lanes']), ('sport romance', ['sport romance']))   # the list's interest, not the page's genre
        self.assertEqual(c['found_by'], ['goodreads-genre:sports-romance'])
        self.assertEqual(c['gr'], '243596193')
        self.assertTrue(c['rating'] and c['rating_count'])

    def test_apple_is_not_asked_once_it_keeps_failing(self):
        asked = []
        fetch.search = lambda term, limit=100: asked.append(term) or []
        e = dict(entry(), id='243596193', name='The Unknown', author='Riley Sager',
                 url='https://www.goodreads.com/book/show/243596193-the-unknown')
        releases.candidate_for(e, 'x', 's', '2026-11', {}, self.reader(), lambda: False)
        self.assertEqual(asked, [])

    def test_a_page_that_is_another_book_makes_no_candidate(self):
        fetch.search = lambda term, limit=100: []
        e = dict(entry(), id='243596193', name='A Different Book', author='Riley Sager',
                 url='https://www.goodreads.com/book/show/243596193-the-unknown')
        c, via, why = releases.candidate_for(e, 'x', 's', '2026-11', {}, self.reader(), lambda: True)
        self.assertEqual((c, why), (None, 'wrong page'))


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self._get = reference._get
        self.gets = []

    def tearDown(self):
        reference._get = self._get

    def serve(self, *pages):
        pages = list(pages)

        def get(url, timeout=0):
            self.gets.append(url)
            p = pages.pop(0)
            if isinstance(p, Exception):
                raise p
            return p
        reference._get = get

    E = {'id': '243596193', 'url': 'https://www.goodreads.com/book/show/243596193-the-unknown'}

    def test_a_book_is_read_once_and_then_comes_from_the_cache(self):
        self.serve(BOOK)
        cache = {}
        r1 = releases.Reader(cache, sleep=lambda s: None)
        self.assertEqual(r1.read(self.E)[0]['publisher'], 'Dutton')
        r2 = releases.Reader(cache, sleep=lambda s: None)
        self.assertEqual(r2.read(self.E)[0]['publisher'], 'Dutton')
        self.assertEqual((len(self.gets), r2.reads, r2.cached), (1, 0, 1))

    def test_a_cached_read_older_than_the_limit_is_read_again(self):
        cache = {'243596193': {'at': '2026-01-01', 'page': {'title': 'old'}}}
        self.assertIsNone(releases.cached_page(cache, '243596193'))
        self.assertEqual(releases.cached_page(cache, '243596193', today=releases.date(2026, 1, 10)), {'title': 'old'})

    def test_the_cap_stops_the_reads(self):
        self.serve(BOOK)
        r = releases.Reader({}, cap=1, sleep=lambda s: None)
        r.read(self.E)
        self.assertEqual(r.read(dict(self.E, id='2'))[1], 'cap')
        self.assertEqual(len(self.gets), 1)

    def test_the_reads_keep_the_gap(self):
        self.serve(BOOK, BOOK)
        waits = []
        r = releases.Reader({}, gap=10, sleep=waits.append)
        r.read(self.E)
        r.read(dict(self.E, id='2'))
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(0 < w <= 10 for w in waits))

    def test_the_first_bot_check_ends_the_reads_and_is_not_cached(self):
        self.serve(CHALLENGE)
        cache = {}
        r = releases.Reader(cache, sleep=lambda s: None)
        self.assertEqual(r.read(self.E)[1], 'challenged')
        self.assertEqual(r.read(dict(self.E, id='2'))[1], 'challenged')
        self.assertEqual((len(self.gets), cache), (1, {}))

    def test_an_unreadable_page_is_a_miss_not_a_raise_and_not_cached(self):
        self.serve(OSError('503'))
        cache = {}
        r = releases.Reader(cache, sleep=lambda s: None)
        self.assertEqual(r.read(self.E), (None, 'unreadable'))
        self.assertEqual(cache, {})


class CuratorAskTests(unittest.TestCase):
    """The two curator questions share one call: the words and the genres
    come out of whatever JSON the model wraps, and a bad answer is an empty
    list, never a raise."""

    def ask(self, content):
        import urllib.request
        orig = urllib.request.urlopen

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return json.dumps({'choices': [{'message': {'content': content}}]}).encode()
        urllib.request.urlopen = lambda req, timeout=0: R()
        try:
            return (releases.curate.suggest_slugs('k', 'Hockey romance'),
                    releases.curate.suggest_terms('k', 'Hockey romance'))
        finally:
            urllib.request.urlopen = orig

    def test_slugs_are_cleaned_and_unsafe_ones_dropped(self):
        slugs, _ = self.ask('Here: {"slugs": ["Sports Romance", "../etc", "sports-romance", "hockey_romance", "x"]}')
        self.assertEqual(slugs, ['sports-romance', 'hockey-romance', 'x'])

    def test_terms_still_need_three(self):
        _, terms = self.ask('{"queries": ["a b", "c d", "e f"]}')
        self.assertEqual(terms, ['a b', 'c d', 'e f'])
        _, few = self.ask('{"queries": ["a b"]}')
        self.assertEqual(few, [])

    def test_an_answer_that_is_not_json_is_empty(self):
        self.assertEqual(self.ask('no idea'), ([], []))
        self.assertEqual(self.ask('["a"]'), ([], []))


class PickEntriesTests(unittest.TestCase):
    def test_seen_books_and_repeats_across_lists_are_left_out(self):
        a = [dict(id='1', name='One', author='A'), dict(id='2', name='Two', author='B')]
        b = [dict(id='2', name='Two', author='B'), dict(id='3', name='Three', author='C')]
        seen = reference._entry_keys({'title': 'One', 'author': 'A'})
        todo, left = releases.pick_entries([('x', 'x', a), ('y', 'y', b)], seen, 10)
        self.assertEqual([(n, e['id']) for n, s, e in todo], [('x', '2'), ('y', '3')])
        self.assertEqual(left, 0)

    def test_interests_take_turns_so_a_long_list_cannot_use_the_cap_alone(self):
        long = [dict(id=str(k), name='Long %d' % k, author='L') for k in range(10)]
        short = [dict(id='s%d' % k, name='Short %d' % k, author='S') for k in range(2)]
        todo, left = releases.pick_entries([('long', 'l', long), ('short', 's', short)], set(), 4)
        self.assertEqual([n for n, s, e in todo], ['long', 'short', 'long', 'short'])
        self.assertEqual(left, 8)


class RunTests(unittest.TestCase):
    """releases.main() on a scratch install: the interests file, the month's
    candidates file and the run's own report, with the network stood in."""

    def setUp(self):
        import windows
        self.tmp = tempfile.mkdtemp(prefix='shelf-rel-run-')
        self.cfg = tempfile.mkdtemp(prefix='shelf-rel-cfg-')
        self.mon = windows.target_month(fetch.MODE)
        self.cand = os.path.join(self.tmp, 'candidates-%s.json' % self.mon)
        with open(self.cand, 'w') as f:
            json.dump({'books': [{'title': 'Already Here', 'author': 'Pool Author'}]}, f)
        self.ipath = os.path.join(self.cfg, 'interests.json')
        self.set_interests([{'id': 'sport', 'label': 'Sport romance', 'kind': 'story', 'dial': 'into it'}])
        self._saved = (fetch.CFG.get('output_dir'), reference._get, fetch.search, fetch.resolve_product,
                       os.environ.get('CFG_DIR'), releases.fetch.CACHE_PATH, releases.PAGE_GAP,
                       releases.curate.api_key, releases.curate.suggest_slugs, releases.time.sleep)
        os.environ['CFG_DIR'] = self.cfg
        fetch.CFG['output_dir'] = self.tmp
        fetch.CACHE_PATH = os.path.join(self.tmp, 'publisher-cache.json')
        fetch.search = lambda term, limit=100: []
        fetch.resolve_product = lambda rec, cache: None
        releases.time.sleep = lambda s: None
        releases.curate.api_key = lambda: ''
        releases.PAGE_GAP = 0
        self.slug_calls = []
        self.gets = []

    def tearDown(self):
        (out, reference._get, fetch.search, fetch.resolve_product, cfg, fetch.CACHE_PATH,
         releases.PAGE_GAP, releases.curate.api_key, releases.curate.suggest_slugs, releases.time.sleep) = self._saved
        if out is not None:
            fetch.CFG['output_dir'] = out
        if cfg is None:
            os.environ.pop('CFG_DIR', None)
        else:
            os.environ['CFG_DIR'] = cfg

    def set_interests(self, ints):
        with open(self.ipath, 'w') as f:
            json.dump({'v': 1, 'name': 'The book brew', 'picks': 12, 'never': [], 'interests': ints}, f)

    def interest(self):
        with open(self.ipath) as f:
            return json.load(f)['interests'][0]

    def run_main(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = releases.main()
        self.assertEqual(rc, 0)
        with open(os.path.join(self.tmp, 'releases-%s.json' % self.mon)) as f:
            report = json.load(f)
        return buf.getvalue(), report

    def pages(self):
        """Goodreads as it answers: the list, one book's page, a 503 for the rest."""
        return {'new_releases/sports-romance': LIST, '254939637': NO_LINE_CHANGE,
                '/book/show/': OSError('503')}

    def goodreads(self, pages):
        """A Goodreads that answers each address from `pages` (address part -> html)."""
        def get(url, timeout=0):
            self.gets.append(url)
            for part, body in pages.items():
                if part in url:
                    if isinstance(body, Exception):
                        raise body
                    return body
            raise OSError('404 ' + url)
        reference._get = get

    def test_a_run_adds_the_new_books_with_the_interest_and_the_list_as_their_source(self):
        self.goodreads(self.pages())
        out, rep = self.run_main()
        with open(self.cand) as f:
            books = json.load(f)['books']
        added = [b for b in books if b['title'] != 'Already Here']
        self.assertEqual([b['title'] for b in added], ['No Line Change'])
        b = added[0]
        self.assertEqual(b['pub_source'], 'goodreads-page')
        self.assertEqual(b['publisher'], '')                    # Goodreads names none: the proof rule decides, not the publisher
        self.assertEqual((b['rating'], b['rating_count']), (4.39, 378))
        self.assertEqual(b['lane'], 'sport romance')
        self.assertEqual(b['found_by'], ['goodreads-genre:sports-romance'])
        self.assertTrue(rep['ok'])
        self.assertEqual(rep['interests']['sport romance']['goodreads'], 1)
        self.assertEqual(rep['interests']['sport romance']['missed'], 7)
        self.assertEqual(rep['interests']['sport romance']['listed'], 8)
        self.assertIn('Sport romance', out)
        self.assertIn('sports-romance', out)

    def test_goodreads_down_is_reported_and_the_run_goes_on(self):
        self.goodreads({'new_releases': OSError('timed out')})
        out, rep = self.run_main()
        self.assertFalse(rep['ok'])
        self.assertIn('no list could be read', rep['reason'])
        with open(self.cand) as f:
            self.assertEqual(len(json.load(f)['books']), 1)

    def test_a_list_that_cannot_be_appended_to_is_a_failure_not_a_success(self):
        os.remove(self.cand)
        self.goodreads(self.pages())
        out, rep = self.run_main()
        self.assertFalse(rep['ok'])
        self.assertIn('APPEND FAILED', out)
        self.assertEqual(rep['added'], [])

    def test_the_bot_check_stops_the_page_reads_and_says_so(self):
        self.goodreads({'new_releases/sports-romance': LIST, '/book/show/': CHALLENGE})
        out, rep = self.run_main()
        self.assertTrue(rep['challenged'])
        self.assertEqual(rep['page_reads'], 1)
        self.assertIn("bot check", out)
        self.assertEqual({u['reason'] for u in rep['unobtainable']}, {'challenged'})

    def test_the_second_run_reads_no_page_the_first_cached(self):
        self.goodreads(self.pages())
        _, first = self.run_main()
        self.assertEqual(first['page_reads'], 8)
        with open(self.cand, 'w') as f:
            json.dump({'books': []}, f)
        self.gets.clear()
        _, second = self.run_main()
        self.assertEqual(second['page_cache_hits'], 1)
        self.assertEqual(second['page_reads'], 7)                # the seven that answered 503 are asked again
        self.assertFalse([u for u in self.gets if '254939637' in u])

    def test_off_and_best_ever_interests_read_no_list(self):
        self.set_interests([
            {'id': 'sport', 'label': 'Sport romance', 'kind': 'story', 'dial': 'off'},
            {'id': 'romantasy', 'label': 'Romantasy', 'kind': 'story', 'dial': 'into it', 'mode': 'best ever'},
        ])
        asked = []
        reference._get = lambda url, timeout=0: asked.append(url) or ''
        self.run_main()
        self.assertEqual(asked, [])

    def test_an_interest_that_wants_new_and_best_ever_books_reads_its_list(self):
        self.set_interests([{'id': 'sport', 'label': 'Sport romance', 'kind': 'story',
                             'dial': 'into it', 'mode': 'both'}])
        self.goodreads(self.pages())
        _, rep = self.run_main()
        self.assertEqual(rep['interests']['sport romance']['listed'], 8)

    def test_a_typed_interest_asks_the_curator_once_and_keeps_the_slug(self):
        self.set_interests([{'id': 'hockey', 'label': 'Hockey romance', 'kind': 'story', 'dial': 'into it'}])
        releases.curate.api_key = lambda: 'key'
        releases.curate.suggest_slugs = lambda key, label: self.slug_calls.append(label) or ['not-a-genre', 'sports-romance']
        self.goodreads({'new_releases/not-a-genre': EMPTY, 'new_releases/sports-romance': LIST,
                        '/book/show/': OSError('503')})
        self.run_main()
        kept = self.interest()
        self.assertEqual(kept['gr_slug'], 'sports-romance')       # not the first one: its list showed no books
        self.run_main()
        self.assertEqual(self.slug_calls, ['Hockey romance'])      # the second run asks no one

    def test_a_suggested_genre_with_no_books_is_not_kept_and_the_curator_is_asked_again(self):
        self.set_interests([{'id': 'hockey', 'label': 'Hockey romance', 'kind': 'story', 'dial': 'into it'}])
        releases.curate.api_key = lambda: 'key'
        releases.curate.suggest_slugs = lambda key, label: self.slug_calls.append(label) or ['not-a-genre']
        self.goodreads({'new_releases/not-a-genre': EMPTY})
        out, rep = self.run_main()
        self.assertNotIn('gr_slug', self.interest())
        self.assertEqual(rep['interests']['hockey romance']['reason'], 'no Goodreads genre')
        self.run_main()
        self.assertEqual(self.slug_calls, ['Hockey romance', 'Hockey romance'])

    def test_no_key_means_a_typed_interest_has_no_list_and_the_rest_still_run(self):
        self.set_interests([{'id': 'sport', 'label': 'Sport romance', 'kind': 'story', 'dial': 'into it'},
                            {'id': 'hockey', 'label': 'Hockey romance', 'kind': 'story', 'dial': 'into it'}])
        self.goodreads(self.pages())
        out, rep = self.run_main()
        self.assertIn('no OpenRouter key', rep['interests']['hockey romance']['reason'])
        self.assertEqual(rep['interests']['sport romance']['listed'], 8)

    def test_the_stage_stops_at_its_time_budget_and_keeps_what_it_found(self):
        self.goodreads(self.pages())
        served = reference._get
        real_sleep = self._saved[-1]      # setUp stood in for sleep; this wait is real

        def slow(url, timeout=0):
            if 'new_releases' not in url:
                real_sleep(0.3)          # a slow book page: 0.3 s of the 0.5 s budget
            return served(url)
        reference._get = slow
        old = releases.BUDGET
        releases.BUDGET = 0.5
        try:
            out, rep = self.run_main()
        finally:
            releases.BUDGET = old
        self.assertTrue(rep['ok'])
        self.assertEqual(rep['page_reads'], 2)
        self.assertIn('time budget', rep['reason'])
        self.assertEqual(sum(1 for u in rep['unobtainable'] if u['reason'] == 'time budget'), 6)


class ProofRuleTests(unittest.TestCase):
    """A book that came from a Goodreads page keeps the existing proof: 4.0 or
    more from 100 readers. Loving Her Enemy (4.62 from 72 readers) is the
    captain's own example of a new book that fails it."""

    def prove(self, rating, count):
        import windows
        tmp = tempfile.mkdtemp(prefix='shelf-rel-gate-')
        mon = windows.target_month(flt.MODE)
        book = {'title': 'Loving Her Enemy', 'author': 'A Author', 'genre': 'Contemporary romance',
                'date': None, 'publisher': '', 'rating': rating, 'rating_count': count,
                'pub_source': 'goodreads-page', 'lane': 'contemporary romance',
                'found_by': ['goodreads-genre:contemporary-romance']}
        json.dump({'books': [book]}, open(os.path.join(tmp, 'candidates-%s.json' % mon), 'w'))
        old = flt.CFG.get('output_dir')
        flt.CFG['output_dir'] = tmp
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(flt.main(), 0)
        finally:
            if old is not None:
                flt.CFG['output_dir'] = old
        return json.load(open(os.path.join(tmp, 'filtered-%s.json' % mon)))['books'][0]

    def test_72_readers_is_not_proof(self):
        self.assertFalse(self.prove(4.62, 72)['indie_proven'])

    def test_100_readers_at_4_is_proof(self):
        self.assertTrue(self.prove(4.0, 100)['indie_proven'])


if __name__ == '__main__':
    unittest.main()
