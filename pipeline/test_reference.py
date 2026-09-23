#!/usr/bin/env python3
"""The Goodreads release reference (#47).

Run: cd pipeline && python3 -m unittest test_reference

The parser fixtures are real pages saved from 2026-09-23 (the month list and
one book page, trimmed to the nodes the parser reads — structure kept). The
failure paths are pinned too: a broken fetch or a markup change must never
break the run.
"""
import json
import os
import tempfile
import unittest

os.environ.setdefault('CFG_DIR', tempfile.mkdtemp(prefix='shelf-ref-test-'))

import reference  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LIST_FIXTURE = os.path.join(HERE, 'testdata', 'gr-popular_by_date-2026-08.html')
BOOK_FIXTURE = os.path.join(HERE, 'testdata', 'gr-book-243596193.html')


class ParseListTests(unittest.TestCase):
    def setUp(self):
        self.entries = reference.parse_list(open(LIST_FIXTURE, encoding='utf-8').read())

    def test_the_real_month_list_parses(self):
        self.assertTrue(self.entries, 'the saved list fixture must parse')
        self.assertGreaterEqual(len(self.entries), 10)

    def test_every_entry_has_a_title_author_and_url(self):
        for e in self.entries:
            self.assertTrue(e['title'], e)
            self.assertTrue(e['author'], e)
            self.assertTrue(e['url'].startswith('https://www.goodreads.com/book/show/'), e)

    def test_ratings_come_through(self):
        rated = [e for e in self.entries if e['rating'] and e['rating_count']]
        self.assertGreaterEqual(len(rated), len(self.entries) - 2)

    def test_markup_change_fails_soft(self):
        self.assertIsNone(reference.parse_list('<html>nothing here</html>'))
        self.assertIsNone(reference.parse_list(''))


class ParseBookTests(unittest.TestCase):
    def setUp(self):
        self.book = reference.parse_book(open(BOOK_FIXTURE, encoding='utf-8').read())

    def test_the_real_book_page_parses(self):
        self.assertIsNotNone(self.book)
        self.assertEqual(self.book['title'], 'The Unknown')
        self.assertTrue(self.book['author'])
        self.assertEqual(self.book['publisher'], 'Dutton')
        self.assertRegex(self.book['date'] or '', r'^\d{4}-\d{2}-\d{2}$')
        self.assertTrue(self.book['genres'])
        self.assertTrue(self.book['rating'] and self.book['rating_count'])

    def test_markup_change_fails_soft(self):
        self.assertIsNone(reference.parse_book('<html>nope</html>'))


class TitleMatchTests(unittest.TestCase):
    def test_containment_both_ways(self):
        self.assertTrue(reference._title_match('The Unknown', 'The Unknown (A Novel)'))
        self.assertTrue(reference._title_match('Big Little Truths', 'Big Little Truths'))

    def test_token_overlap(self):
        self.assertTrue(reference._title_match('Eternal is the Night', 'Eternal Is the Night'))

    def test_a_different_book_is_not_a_match(self):
        self.assertFalse(reference._title_match('The Unknown', 'Fruit Fly'))
        self.assertFalse(reference._title_match('The Unknown', 'Unknown Soldier'))
        self.assertFalse(reference._title_match('', 'anything'))


class DiffTests(unittest.TestCase):
    def test_seen_keys_normalize_both_ways(self):
        e = {'title': 'The Unknown', 'author': 'Josh Silver'}
        keys = reference._entry_keys(e)
        # a pool book with the same title/author is seen via either key
        import fetch, bookids
        self.assertIn(fetch.normkey('The Unknown', 'Josh Silver'), keys)
        self.assertIn(bookids.book_key('The Unknown', 'Josh Silver'), keys)

    def test_a_miss_is_a_miss(self):
        import fetch, bookids
        seen = {fetch.normkey('Something Else', 'Another Author'),
                bookids.book_key('Something Else', 'Another Author')}
        e = {'title': 'The Unknown', 'author': 'Josh Silver'}
        self.assertFalse(reference._entry_keys(e) & seen)


class FailurePathTests(unittest.TestCase):
    """A broken reference can never break the run: it reports why and exits 0."""

    def test_list_fetch_failure_writes_the_file_and_returns_zero(self):
        import fetch
        orig = reference.fetch_month
        tmp = tempfile.mkdtemp(prefix='shelf-ref-run-')
        old_out = fetch.CFG.get('output_dir')
        try:
            reference.fetch_month = lambda mon: (_ for _ in ()).throw(OSError('503'))
            fetch.CFG['output_dir'] = tmp
            rc = reference.main()
            self.assertEqual(rc, 0)
            files = [f for f in os.listdir(tmp) if f.startswith('reference-')]
            self.assertEqual(len(files), 1)
            blob = json.load(open(os.path.join(tmp, files[0])))
            self.assertFalse(blob['ok'])
            self.assertIn('list fetch failed', blob['reason'])
        finally:
            reference.fetch_month = orig
            if old_out is not None:
                fetch.CFG['output_dir'] = old_out

    def test_parse_failure_writes_the_file_and_returns_zero(self):
        import fetch
        orig = reference.fetch_month
        tmp = tempfile.mkdtemp(prefix='shelf-ref-run2-')
        old_out = fetch.CFG.get('output_dir')
        try:
            reference.fetch_month = lambda mon: '<html>changed markup</html>'
            fetch.CFG['output_dir'] = tmp
            rc = reference.main()
            self.assertEqual(rc, 0)
            files = [f for f in os.listdir(tmp) if f.startswith('reference-')]
            blob = json.load(open(os.path.join(tmp, files[0])))
            self.assertIn('parse failed', blob['reason'])
        finally:
            reference.fetch_month = orig
            if old_out is not None:
                fetch.CFG['output_dir'] = old_out


class KindleCandidateTests(unittest.TestCase):
    """A miss with no Apple presence gets a normal candidate from its page —
    publisher, date, ratings, genres — and the existing gate accepts the
    Goodreads numbers (the indie-with-proof case)."""

    def test_book_page_becomes_a_candidate(self):
        orig = reference._get
        try:
            reference._get = lambda url, timeout=0: open(BOOK_FIXTURE, encoding='utf-8').read()
            c = reference.kindle_candidate({'title': 'The Unknown', 'author': 'Josh Silver',
                                            'url': 'https://www.goodreads.com/book/show/243596193-the-unknown',
                                            'cover': '', 'description': ''}, '2026-08')
        finally:
            reference._get = orig
        self.assertIsNotNone(c)
        self.assertEqual(c['title'], 'The Unknown')
        self.assertEqual(c['publisher'], 'Dutton')
        self.assertEqual(c['found_by'], ['goodreads'])
        self.assertEqual(c['pub_source'], 'goodreads-page')
        self.assertTrue(c['date'].startswith('2026-'))
        self.assertTrue(c['rating'] and c['rating_count'])

    def test_a_kindle_first_self_pub_passes_the_existing_gate(self):
        import filter as flt
        c = {'publisher': 'Independently published', 'rating': 4.2, 'rating_count': 921}
        cls = flt.pub_class(c['publisher'])
        self.assertEqual(cls, 'indie')
        proven = (c['rating'] >= flt.CFG['trad_pub_score_rating']
                  and c['rating_count'] >= flt.CFG.get('trad_pub_score_count', 100))
        self.assertTrue(cls == 'indie' and proven)

    def test_an_unreadable_page_is_none_not_a_raise(self):
        orig = reference._get
        try:
            reference._get = lambda url, timeout=0: (_ for _ in ()).throw(OSError('503'))
            c = reference.kindle_candidate({'title': 'X', 'author': 'Y', 'url': 'u',
                                            'cover': '', 'description': ''}, '2026-08')
        finally:
            reference._get = orig
        self.assertIsNone(c)


class MatchStrictnessTests(unittest.TestCase):
    """The Apple guard must reject a same-title, different-writer result — a
    shared first name is not a match — and fail closed on a nameless side."""

    def test_a_shared_first_name_is_not_a_match(self):
        self.assertFalse(reference._author_match('Sarah Pekkanen', 'Sarah J. Maas'))

    def test_initials_and_variants_still_pass(self):
        self.assertTrue(reference._author_match('J.K. Maclaren', 'JK Maclaren'))
        self.assertTrue(reference._author_match('Sarah Pekkanen', 'Sarah Pekkanen'))

    def test_one_side_nameless_fails_closed(self):
        self.assertFalse(reference._author_match('', 'Someone Else'))
        self.assertFalse(reference._author_match('Someone Else', ''))


class KindleUndatedTests(unittest.TestCase):
    def test_an_undated_page_yields_no_date(self):
        raw = open(BOOK_FIXTURE, encoding='utf-8').read()
        stripped = raw.replace('"publicationTime":1785826800000', '"publicationTime":null')
        self.assertNotEqual(raw, stripped, 'the fixture must carry the timestamp this test strips')
        orig = reference._get
        try:
            reference._get = lambda url, timeout=0: stripped
            c = reference.kindle_candidate({'title': 'The Unknown', 'author': 'Riley Sager',
                                            'url': 'https://www.goodreads.com/book/show/243596193-the-unknown',
                                            'cover': '', 'description': ''}, '2026-08')
        finally:
            reference._get = orig
        self.assertIsNotNone(c)
        self.assertIsNone(c['date'])       # never invented — the filter lets the model judge


class WrongPageTests(unittest.TestCase):
    def test_a_page_that_is_not_the_entry_is_rejected(self):
        orig = reference._get
        try:
            reference._get = lambda url, timeout=0: open(BOOK_FIXTURE, encoding='utf-8').read()
            c = reference.kindle_candidate({'title': 'A Completely Different Book', 'author': 'X',
                                            'url': 'https://www.goodreads.com/book/show/243596193-the-unknown',
                                            'cover': '', 'description': ''}, '2026-08')
        finally:
            reference._get = orig
        self.assertIsNone(c)


class GateBranchTests(unittest.TestCase):
    """The ticket's indie-with-proof case, through the REAL filter run: an
    unknown publisher sourced from a Goodreads page with proven ratings passes
    the curator's gate; its Apple-page twin does not."""

    def test_unknown_goodreads_page_with_proof_passes_the_gate(self):
        import json
        import os
        import tempfile
        import filter as flt
        import windows
        tmp = tempfile.mkdtemp(prefix='shelf-ref-gate-')
        mon = windows.target_month(flt.MODE)
        books = [
            {'title': 'Kindle First Book', 'author': 'A Author', 'genre': 'Romantasy',
             'date': None, 'publisher': '', 'rating': 4.4, 'rating_count': 500,
             'pub_source': 'goodreads-page', 'found_by': ['goodreads']},
            {'title': 'Apple Twin Book', 'author': 'B Author', 'genre': 'Romantasy',
             'date': None, 'publisher': '', 'rating': 4.9, 'rating_count': 9000,
             'pub_source': 'apple-search', 'found_by': ['goodreads']},
        ]
        with open(os.path.join(tmp, 'candidates-%s.json' % mon), 'w') as f:
            json.dump({'books': books}, f)
        old = flt.CFG.get('output_dir')
        flt.CFG['output_dir'] = tmp
        try:
            rc = flt.main()
        finally:
            if old is not None:
                flt.CFG['output_dir'] = old
        self.assertEqual(rc, 0)
        with open(os.path.join(tmp, 'filtered-%s.json' % mon)) as f:
            kept = {b['title']: b for b in json.load(f)['books']}
        self.assertIn('Kindle First Book', kept)
        self.assertTrue(kept['Kindle First Book']['indie_proven'])
        self.assertIn('Apple Twin Book', kept)
        self.assertFalse(kept['Apple Twin Book']['indie_proven'])


class AppendHonestyTests(unittest.TestCase):
    """'Found but not appended' must read as a failure: the line says so, the
    file says ok:false, and nothing is claimed as added."""

    def test_append_failure_is_reported_not_hidden(self):
        import contextlib
        import io
        import json
        import os
        import tempfile
        import fetch
        tmp = tempfile.mkdtemp(prefix='shelf-ref-append-')
        old_out = fetch.CFG.get('output_dir')
        orig_month, orig_get, orig_search, orig_resolve = (
            reference.fetch_month, reference._get, fetch.search, fetch.resolve_product)

        def fake_search(term, limit=100):
            return [{'trackName': 'The Unknown', 'artistName': 'Riley Sager',
                     'releaseDate': '2026-08-04T07:00:00Z', 'genres': ['Romance'],
                     'trackViewUrl': 'https://books.apple.com/x/id1', 'trackId': 1,
                     'averageUserRating': 4.5, 'userRatingCount': 500, 'description': ''}]

        try:
            fetch.CFG['output_dir'] = tmp
            reference.fetch_month = lambda mon: open(LIST_FIXTURE, encoding='utf-8').read()
            reference._get = lambda url, timeout=0: (_ for _ in ()).throw(OSError('no page'))
            fetch.search = fake_search
            fetch.resolve_product = lambda rec, cache: None
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = reference.main()
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn('APPEND FAILED', out)      # nothing entered the pool
            files = [f for f in os.listdir(tmp) if f.startswith('reference-')]
            blob = json.load(open(os.path.join(tmp, files[0])))
            self.assertFalse(blob['ok'])
            self.assertIn('append failed', blob['reason'])
            self.assertEqual(blob['added'], [])
            self.assertTrue(blob['capped'])          # 15 misses -> the top 8 by rank
        finally:
            reference.fetch_month, reference._get = orig_month, orig_get
            fetch.search, fetch.resolve_product = orig_search, orig_resolve
            if old_out is not None:
                fetch.CFG['output_dir'] = old_out


if __name__ == '__main__':
    unittest.main()
