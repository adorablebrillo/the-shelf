#!/usr/bin/env python3
"""#51 tests — the synopsis chain, its parsers, and the volume cache.

Fixtures are REAL pages (saved under testdata, trimmed to the parsed nodes):
the search page for 'Fourth Wing' (three ranked rows, incl. a junk 'Study
Guide' result and a foreign edition) and a real book page. Goodreads' newer
Next.js search page is saved twice: the 'Fourth Wing' results (the first six
ranked results of the page's streamed data) and a search with no result. The
parsers must return None (never raise) on any mutation of them.

No test may hit the network: every lookup goes through a fake _get.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import synopses as S

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH_FX = os.path.join(HERE, 'testdata', 'gr-search-fourth-wing.html')
BOOK_FX = os.path.join(HERE, 'testdata', 'gr-book-243596193.html')
NEXT_SEARCH_FX = os.path.join(HERE, 'testdata', 'gr-search-next-fourth-wing.html')
NEXT_EMPTY_FX = os.path.join(HERE, 'testdata', 'gr-search-next-no-results.html')


def _read(path):
    with open(path) as f:
        return f.read()


def search_html():
    return _read(SEARCH_FX)


def book_html():
    return _read(BOOK_FX)


def next_search_html():
    return _read(NEXT_SEARCH_FX)


# the real AWS WAF body Goodreads serves a client it challenges (a ~2KB page
# that runs a script instead of the page), trimmed to its markers
WAF_PAGE = ('<!DOCTYPE html><html><head><title></title></head><body>'
            '<script>window.awsWafCookieDomainList = [];window.gokuProps = {"key":"AQID"};</script>'
            '</body></html>')


def search_for(title, author):
    """The real search fixture, with its first ranked row answering for
    `title`/`author` — the row structure stays exactly the real page's."""
    html = search_html()
    html, n1 = re.subn(r"(<a class=\"bookTitle\"[^>]*>\s*<span itemprop='name' role='heading' aria-level='4'>)[^<]*(</span>)",
                       lambda m: m.group(1) + title + m.group(2), html, count=1)
    html, n2 = re.subn(r"(<a class=\"authorName\"[^>]*>\s*<span itemprop=\"name\">)[^<]*(</span>)",
                       lambda m: m.group(1) + author + m.group(2), html, count=1)
    assert n1 == 1 and n2 == 1, 'fixture rewrite broke — check the saved page'
    return html


class FakeNet:
    """A deterministic _get: routes by URL, counts calls, fails on demand.
    `search` may be a list: each search takes the next page, the last repeats."""

    def __init__(self, search=None, book=None, apple=None, fail_on=()):
        self.search = search
        self.book = book
        self.apple = apple if apple is not None else {'results': []}
        self.fail_on = tuple(fail_on)
        self.calls = []

    def __call__(self, url, timeout=25):
        self.calls.append(url)
        for pat in self.fail_on:
            if pat in url:
                raise IOError('fake network failure: %s' % pat)
        if 'itunes.apple.com' in url:      # also contains '/search?' — route it FIRST
            return json.dumps(self.apple)
        if '/search?' in url:
            if self.search is None:
                raise IOError('no fake search page')
            if isinstance(self.search, list):
                return self.search.pop(0) if len(self.search) > 1 else self.search[0]
            return self.search
        if '/book/show/' in url:
            if self.book is None:
                raise IOError('no fake book page')
            return self.book
        raise IOError('unrouted fake URL: %s' % url)


class FakeClock:
    """A deterministic clock: each time() call advances `step` seconds."""

    def __init__(self, step=10.0):
        self.t = 0.0
        self.step = step

    def time(self):
        v = self.t
        self.t += self.step
        return v

    def sleep(self, s):
        self.t += s


class Base(unittest.TestCase):
    def setUp(self):
        self._gap = (S.GAP, S.GOODREADS_GAP, S.GOODREADS_SHARE)
        self._get = S._get
        self._time = S.time
        S.GAP = S.GOODREADS_GAP = 0     # never sleep in tests
        S.GOODREADS_SHARE = 1           # the whole budget, unless a test owns the share
        self.tmp = tempfile.mkdtemp(prefix='syn-test-')

    def tearDown(self):
        S.GAP, S.GOODREADS_GAP, S.GOODREADS_SHARE = self._gap
        S._get = self._get
        S.time = self._time
        shutil.rmtree(self.tmp, ignore_errors=True)

    def net(self, **kw):
        f = FakeNet(**kw)
        S._get = f
        return f


# ---------- the pace ----------
class PaceTests(Base):
    """Goodreads answers a client without a browser with its bot challenge:
    measured 2026-11, at the build's 1.2 s pace the second book's search was
    challenged in 2 runs of 2; at 10 s, 3 runs of 4 read every search and book
    page. The pace lowers the odds; CacheTests own what a challenge does."""

    def setUp(self):
        super().setUp()
        slept = self.slept = []

        class Clock:
            t = 1000.0

            def time(self):
                return self.t

            def sleep(self, d):
                slept.append(round(d, 3))
                self.t += d

        S.time = Clock()
        S.GAP, S.GOODREADS_GAP = 1.2, 10.0
        self._rget, self._lastv = S.R._get, dict(S._last)
        S._last.update(t=0.0, goodreads=0.0)
        S.R._get = lambda url, timeout=25: ''

    def tearDown(self):
        S.R._get = self._rget
        S._last.clear()
        S._last.update(self._lastv)
        super().tearDown()

    def test_goodreads_requests_are_paced_apart_and_apple_is_not_held_back(self):
        S._get(S.search_url('Iron Flame', 'Rebecca Yarros'))              # first: no wait
        S._get('https://www.goodreads.com/book/show/90202302-iron-flame')  # Goodreads pace
        S._get('https://itunes.apple.com/search?term=Iron+Flame+Rebecca+Yarros')  # Apple: GAP only
        S._get(S.search_url('Book Lovers', 'Emily Henry'))                # 10 s after the page
        self.assertEqual(self.slept, [10.0, 1.2, 8.8])


# ---------- the parsers ----------
class SearchParseTests(Base):
    def test_real_page_parses_in_rank_order(self):
        rows = S.parse_search(search_html())
        self.assertIsInstance(rows, list)
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(rows[0]['title'], 'Fourth Wing')
        self.assertEqual(rows[0]['author'], 'Rebecca Yarros')
        self.assertTrue(rows[0]['url'].startswith('https://www.goodreads.com/book/show/'))
        self.assertNotIn('?', rows[0]['url'])          # query junk stripped

    def test_junk_and_empty_fail_soft(self):
        self.assertIsNone(S.parse_search(''))
        self.assertIsNone(S.parse_search(None))
        self.assertIsNone(S.parse_search('<html><body>not a search page</body></html>'))

    def test_mutations_never_raise(self):
        html = search_html()
        for cut in (0, 100, len(html) // 2, len(html) - 50):
            out = S.parse_search(html[:cut])
            self.assertTrue(out is None or isinstance(out, list))

    def test_row_without_author_is_kept_with_empty_author(self):
        html = search_html().replace('class="authorName"', 'class="somethingElse"')
        rows = S.parse_search(html)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['author'], '')


class NextSearchParseTests(Base):
    """The Next.js search page Goodreads serves since 2026-11 ('Book search
    results for ... | Goodreads'): no result rows in the markup — the results
    live in the page's streamed data. The classic-row parser read 0 rows from
    it, so every lookup failed over to Apple."""

    def test_real_page_parses_in_rank_order(self):
        rows = S.parse_search(next_search_html())
        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 6)                 # the six results the fixture keeps
        self.assertEqual(rows[0]['title'], 'Fourth Wing')
        self.assertEqual(rows[0]['author'], 'Rebecca Yarros')
        self.assertEqual(rows[0]['url'], 'https://www.goodreads.com/book/show/217165422-fourth-wing')
        self.assertEqual(rows[1]['author'], 'SuperSummary')   # the study guide ranks second
        self.assertEqual(rows[2]['url'], 'https://www.goodreads.com/book/show/61431922-fourth-wing')

    def test_a_result_carries_its_series_name_and_placement(self):
        # THS-114 part 2: + add a book files a Goodreads-only book with it. A
        # repeated series is a back-reference in the data, so that row reads as none
        rows = S.parse_search(next_search_html())
        self.assertEqual((rows[0]['series'], rows[0]['series_num']), ('The Empyrean', '1'))
        self.assertEqual(rows[1]['series'], '')

    def test_a_result_blurb_is_read_whole_from_its_text_row(self):
        # a long blurb is a separate text row whose length counts UTF-8 bytes;
        # the blurb holds curly quotes and bullets, so a character count would
        # run past its end into the next row's data
        rows = S.parse_search(next_search_html())
        self.assertEqual(rows[0]['description'], '1')  # the placeholder edition's stub
        d = rows[2]['description']
        self.assertIn('Violet Sorrengail', d)
        self.assertNotIn('"$"', d)
        self.assertTrue(d.endswith('Book #3 Onyx Storm'), d[-60:])   # the blurb's own last line

    def test_mutations_never_raise(self):
        html = next_search_html()
        for cut in (0, 100, len(html) // 3, len(html) // 2, len(html) - 50):
            out = S.parse_search(html[:cut])
            self.assertTrue(out is None or isinstance(out, list))


class BookPageTests(Base):
    def test_real_page_gives_the_full_blurb(self):
        page = S.parse_book_page(book_html())
        self.assertIsInstance(page, dict)
        self.assertEqual(page['title'], 'The Unknown')
        self.assertTrue(page['description'])
        # the full blurb, not reference.parse_book's 400-char trim
        self.assertGreater(len(page['description']), 400)
        self.assertIn('New Avalon', page['description'])

    def test_description_is_plain_text(self):
        d = S.parse_book_page(book_html())['description']
        self.assertNotIn('<', d)
        self.assertNotIn('&amp;', d)
        # the parser keeps paragraph breaks (the lead-trim reads the structure);
        # what ships is one clean paragraph
        self.assertNotIn('\n', S._final(d))

    def test_page_without_a_description_is_not_a_crash(self):
        html = book_html().replace('"description"', '"zzz"')
        html = html.replace('description({\\"stripped\\":true})', 'zzz({\\"stripped\\":true})')
        page = S.parse_book_page(html)
        self.assertTrue(page is None or page['description'] == '')

    def test_mutations_never_raise(self):
        html = book_html()
        for cut in (0, 100, len(html) // 2, len(html) - 50):
            out = S.parse_book_page(html[:cut])
            self.assertTrue(out is None or isinstance(out, dict))

    def test_the_parser_hands_the_text_over_and_the_lookup_caps_it(self):
        html = re.sub(r'"description":\s*"[^"]{0,80}',
                      '"description": "%s' % ('x' * 6000), book_html(), count=1)
        page = S.parse_book_page(html)
        self.assertIsInstance(page, dict)
        self.assertGreater(len(page['description']), 400)         # not capped at the parser
        self.assertLessEqual(len(S._final(page['description'])), S.DESC_CAP)


class LeadTrimTests(Base):
    """Apple's catalog copy opens with marketing before the blurb — pinned on
    the real strings the sim fetched, plus innocent negatives that must NOT be
    touched (blurb-length prose stays whole even when it mentions an accolade)."""

    def test_real_apple_copy_is_trimmed_to_the_blurb(self):
        # the real iTunes description for Fourth Wing: an accolade list, two
        # praise quotes and a tagline before the story — plus HTML-escaped
        # markup. The card must show the story, in plain text.
        raw = _read(os.path.join(HERE, 'testdata', 'apple-fourthwing.json'))
        raw = json.loads(raw)['description']
        got = S._final(raw)
        self.assertTrue(got.startswith('Twenty-year-old Violet Sorrengail'), got[:90])
        self.assertNotIn('<', got)
        self.assertNotIn('&lt;', got)
        self.assertNotIn('Accolades', got[:80])
        self.assertGreater(len(got), 400)

    def test_a_substantial_first_paragraph_is_the_blurb_and_stays(self):
        blurb = ('The third in the New York Times bestselling Maple Hills series follows fan-favorite '
                 'Henry and a bookish fellow student who come up with a plan to help them both overcome '
                 'their respective challenges in a difficult year.\n'
                 'When his procrastination lands him in a difficult class, Henry needs a plan.')
        self.assertEqual(S._lead_trim(S._clean(blurb)), S._clean(blurb).replace('\n', ' '))

    def test_escaped_markup_is_stripped_not_shown(self):
        got = S._clean('&lt;b&gt;The third in the &lt;i&gt;New York Times&lt;/i&gt; bestselling '
                       'series follows Henry and a bookish fellow student.&lt;/b&gt;')
        self.assertNotIn('<', got)
        self.assertTrue(got.startswith('The third in the New York Times bestselling series'))

    def test_real_apple_leads_are_trimmed_to_the_blurb(self):
        cases = [
            ('Accolades: AN INSTANT #1 NEW YORK TIMES BESTSELLER \u2022 TV series now in development '
             'at Amazon MGM Studios \u2022 Amazon Best Romantasy Books of the Year 2025. '
             'A storm is coming...and not everyone can survive its wrath.',
             'A storm is coming'),
            ('FROM THE #1 NEW YORK TIMES BESTSELLING AUTHOR OF FUNNY STORY ! A romance writer who no '
             'longer believes in love and a literary writer stuck in a rut engage in a summer-long challenge.',
             'A romance writer who no longer believes'),
            ('#1 NEW YORK TIMES BESTSELLER Over two million copies sold! Sparks fly when a competitive '
             'figure skater and a hockey team captain are forced to share a rink.',
             'Sparks fly when'),
            ('INSTANT #1 NEW YORK TIMES BESTSELLER! From Hannah Grace, author of the #1 New York Times '
             'bestselling Icebreaker , sparks fly when a one-night stand becomes a summer of forced proximity.',
             'From Hannah Grace, author'),
            ('Discover the instant #1 New York Times bestseller! TV series now in development at MGM. '
             'Twenty-year-old Violet Sorrengail was supposed to enter the Scribe Quadrant.',
             'Twenty-year-old Violet'),
        ]
        for raw, want in cases:
            got = S._lead_trim(raw)
            self.assertTrue(got.startswith(want), '%r -> %r' % (raw[:40], got[:60]))
            self.assertLess(len(got), len(raw))

    def test_blurb_length_prose_is_never_trimmed(self):
        s = ('A #1 New York Times bestseller about two sisters who run a bookshop on a small island, '
             'and the summer that changes everything for them both.')
        self.assertEqual(S._lead_trim(s), s)

    def test_plain_blurbs_pass_through_untouched(self):
        s = 'Nora Stephens is a cutthroat literary agent who agrees to a month in a small town.'
        self.assertEqual(S._lead_trim(s), s)

    def test_a_trim_never_leaves_a_stub(self):
        s = 'INSTANT #1 NEW YORK TIMES BESTSELLER! ok'
        self.assertEqual(S._lead_trim(s), s)          # a 2-char tail: the original stands

    def test_empty_inputs_are_safe(self):
        self.assertEqual(S._lead_trim(''), '')
        self.assertEqual(S._lead_trim(None), '')

    def test_the_stored_text_is_capped_after_the_trim(self):
        self.assertLessEqual(len(S._final('x' * 5000)), S.DESC_CAP)
        long_blurb = ('A storm is coming...and not everyone can survive its wrath. ' + 'More story. ' * 400)
        self.assertLessEqual(len(S._final(long_blurb)), S.DESC_CAP)

    def test_a_pre_trim_cache_entry_heals_on_read(self):
        b = {'id': 'onyxstorm--rebeccayarros', 'title': 'Onyx Storm', 'author': 'Rebecca Yarros'}
        cache = {b['id']: {'text': 'Accolades: AN INSTANT #1 NEW YORK TIMES BESTSELLER \u2022 TV series. '
                                   'The real blurb starts here and runs long enough to stand on its own, sentence after sentence.',
                           'src': 'apple', 'at': '2026-09-23', 'gr': ''}}
        net = self.net()                               # nothing may be fetched
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])
        self.assertEqual(stats['cached'], 1)
        self.assertTrue(b['synopsis'].startswith('The real blurb starts here'))

    def test_a_cached_stub_is_dropped_and_retried(self):
        b = {'id': 'fourthwing--rebeccayarros', 'title': 'The Unknown', 'author': 'Riley Sager'}
        cache = {b['id']: {'text': '1', 'src': 'goodreads', 'at': '2026-09-23'}}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(len(net.calls), 2)            # the stub was not shipped: refetched
        self.assertEqual(stats['fetched'], 1)
        self.assertIn('New Avalon', b['synopsis'])


# ---------- the chain ----------
class ChainTests(Base):
    def test_goodreads_hit_uses_search_then_page(self):
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        text, src = S.resolve('The Unknown', 'Riley Sager')
        self.assertEqual(src, 'goodreads')
        self.assertIn('New Avalon', text)
        self.assertEqual(len(net.calls), 2)            # search + page, never more
        self.assertIn('/search?', net.calls[0])

    def test_search_that_redirects_straight_to_a_book_page(self):
        net = self.net(search=book_html())             # the search URL answers with a page
        text, src = S.resolve('The Unknown', 'Riley Sager')
        self.assertEqual(src, 'goodreads')
        self.assertEqual(len(net.calls), 1)            # honored in place
        self.assertIn('New Avalon', text)

    def test_no_matching_row_falls_back_to_apple(self):
        net = self.net(search=search_html(),
                       apple={'results': [{'trackName': 'Iron Flame', 'artistName': 'Rebecca Yarros',
                                           'description': 'Everyone expected Violet Sorrengail to die during her first year at Basgiath War College, but the first test was only the beginning.'}]})
        text, src = S.resolve('Iron Flame', 'Rebecca Yarros')
        self.assertEqual(src, 'apple')
        self.assertIn('Violet Sorrengail', text)
        self.assertEqual(len(net.calls), 2)            # search + apple, no book page

    def test_author_mismatch_is_not_a_match(self):
        self.net(search=search_html(), apple={'results': []})
        self.assertEqual(S.resolve('Fourth Wing', 'Somebody Else'), ('', 'none'))

    def test_neither_source_has_it_is_none(self):
        self.net(search=search_html(), apple={'results': []})
        self.assertEqual(S.resolve('Nobody Wrote This', 'No One'), ('', 'none'))

    def test_goodreads_outage_falls_through_to_apple(self):
        self.net(search=search_html(), fail_on=('goodreads.com/search',),
                 apple={'results': [{'trackName': 'The Unknown', 'artistName': 'Riley Sager',
                                     'description': 'In 1926, five women disappeared from a remote island in Vermont; one hundred years later, it is happening again.'}]})
        text, src = S.resolve('The Unknown', 'Riley Sager')
        self.assertEqual(src, 'apple')
        self.assertIn('five women', text)

    def test_failed_requests_are_fail_not_none(self):
        self.net(search=search_html(), fail_on=('goodreads.com/search',), apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'fail'))
        # the search matches, but the book page cannot be read: transient, not 'none'
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html(),
                 fail_on=('/book/show/',), apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'fail'))

    def test_apple_skips_the_wrong_first_result(self):
        self.net(search=search_for('Nobody Wrote This', 'No One'),
                 apple={'results': [{'trackName': 'Something Else Entirely', 'artistName': 'A N Other',
                                     'description': 'A blurb for the wrong book.'},
                                    {'trackName': 'Nobody Wrote This', 'artistName': 'No One',
                                     'description': 'The right blurb: a story that runs long enough to be a real synopsis and not a stub.'}]})
        self.assertEqual(S.resolve('Nobody Wrote This', 'No One'),
                         ('The right blurb: a story that runs long enough to be a real synopsis and not a stub.', 'apple'))

    def test_apple_result_verification_rejects_the_wrong_book(self):
        self.net(search=search_html(), apple={'results': [
            {'trackName': 'Something Else Entirely', 'artistName': 'A N Other',
             'description': 'A blurb for the wrong book.'}]})
        self.assertEqual(S.resolve('Iron Flame', 'Rebecca Yarros'), ('', 'none'))

    def test_a_rate_limit_challenge_is_transient_never_a_miss(self):
        # the real AWS WAF body Goodreads served after ~20 requests: a 200 with
        # a ~2KB CAPTCHA page. Treating it as "no blurb here" would poison the
        # cache with a false none — it must stay pending and be retried.
        self.net(search=WAF_PAGE, apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'fail'))

    def test_an_empty_body_is_transient(self):
        self.net(search='', apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'fail'))

    def test_a_real_search_page_with_no_rows_is_a_miss(self):
        big = '<html><body><div id="searchResults">No results.</div>' + 'x' * 4000 + '</body></html>'
        self.net(search=big, apple={'results': []})
        self.assertEqual(S.resolve('Nobody Wrote This', 'No One'), ('', 'none'))

    def test_a_page_we_do_not_understand_is_transient(self):
        big = '<html><body>' + 'x' * 5000 + '</body></html>'   # big, but not a search page
        self.net(search=big, apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'fail'))

    def test_next_page_skips_a_placeholder_edition_for_the_real_one(self):
        # the Next.js page's top 'Fourth Wing' result is a placeholder edition
        # whose blurb is '1'; the real edition ranks third. The book fixture
        # stands in for that edition's page, renamed to it.
        page = book_html().replace('"title":"The Unknown"', '"title":"Fourth Wing"')
        page = page.replace('"name":"Riley Sager"', '"name":"Rebecca Yarros"')
        net = self.net(search=next_search_html(), book=page)
        text, src = S.resolve('Fourth Wing', 'Rebecca Yarros')
        self.assertEqual(src, 'goodreads')
        self.assertIn('New Avalon', text)
        self.assertEqual(len(net.calls), 2)            # search + one page
        self.assertIn('/book/show/61431922', net.calls[1])

    def test_next_page_with_no_result_is_a_miss(self):
        net = self.net(search=_read(NEXT_EMPTY_FX), apple={'results': []})
        self.assertEqual(S.resolve('Nobody Wrote This', 'No One'), ('', 'none'))
        self.assertFalse([u for u in net.calls if '/book/show/' in u])

    def test_a_next_results_page_we_cannot_read_is_transient(self):
        # every Next.js search page names its other tabs' result loaders, so a
        # results page whose data no longer parses must not pass as 'no
        # result' — that would cache a false none
        html = next_search_html().replace('self.__next_f.push', 'self.__changed.push')
        self.net(search=html, apple={'results': []})
        self.assertEqual(S.resolve('Fourth Wing', 'Rebecca Yarros'), ('', 'fail'))

    def test_a_challenged_book_page_is_transient(self):
        # the search matched, but the book page came back as a challenge
        waf = ('<html><head><script>window.gokuProps = {"key":"AQID"};</script></head>'
               '<body></body></html>')
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=waf, apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'fail'))

    def test_a_boxed_set_that_carries_the_title_is_not_this_book(self):
        # the live case: Goodreads returned 'The Empyrean Series 3 Books
        # Collection Set: Fourth Wing, Iron Flame, Onyx Storm' for Onyx Storm
        # and its set blurb was about to ship as the book's
        set_title = 'The Empyrean Series 3 Books Collection Set: Fourth Wing, Iron Flame, Onyx Storm'
        self.net(search=search_for(set_title, 'Rebecca Yarros'),
                 apple={'results': [{'trackName': 'Onyx Storm', 'artistName': 'Rebecca Yarros',
                                     'description': 'A storm is coming, and not everyone can survive its wrath as the Empyrean series reaches its darkest hour.'}]})
        text, src = S.resolve('Onyx Storm', 'Rebecca Yarros')
        self.assertEqual(src, 'apple')                 # never the set's blurb
        self.assertIn('storm is coming', text)
        # the second live case (2026-11, the Next.js search): the first result
        # by the author for 'A Court of Thorns and Roses' was this two-book set
        self.assertFalse(S._entry_ok('A Court of Thorns and Roses', 'Sarah J. Maas',
                                     'Throne of Glass, A Court of Thorns and Roses 2 Book Set Collection',
                                     'Sarah J. Maas'))

    def test_a_junk_titled_page_is_not_this_book(self):
        page = book_html().replace('"title":"The Unknown"', '"title":"The Unknown Series Set"')
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=page, apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'none'))

    def test_a_stub_description_is_not_a_blurb(self):
        # the live case: a Fourth Wing page answered with the description '1'.
        # Mutate through the parsed JSON (the raw value contains escaped quotes).
        html = book_html()
        m = re.search(r'(<script id="__NEXT_DATA__" type="application/json">)(.*?)(</script>)', html, re.S)
        data = json.loads(m.group(2))
        for k, v in data['props']['pageProps']['apolloState'].items():
            if k.startswith('Book:') and isinstance(v, dict) and v.get('title') == 'The Unknown':
                v['description'] = '1'
                v.pop('description({"stripped":true})', None)
        html = html[:m.start(2)] + json.dumps(data) + html[m.end(2):]
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=html, apple={'results': []})
        self.assertEqual(S.resolve('The Unknown', 'Riley Sager'), ('', 'none'))

    def test_a_short_apple_description_is_not_a_blurb(self):
        self.net(search=search_for('Nobody Wrote This', 'No One'), book=book_html(),
                 apple={'results': [{'trackName': 'Nobody Wrote This', 'artistName': 'No One',
                                     'description': 'Too short.'}]})
        self.assertEqual(S.resolve('Nobody Wrote This', 'No One'), ('', 'none'))


# ---------- the cache ----------
class CacheTests(Base):
    def book(self, id='theunknown--rileysager', title='The Unknown', author='Riley Sager'):
        return {'id': id, 'title': title, 'author': author}

    def test_first_pass_fetches_then_caches(self):
        b = self.book()
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(stats['fetched'], 1)
        self.assertEqual(stats['goodreads'], 1)
        self.assertIn('New Avalon', b['synopsis'])
        self.assertEqual(b['synopsisSrc'], 'goodreads')
        self.assertEqual(cache[b['id']]['src'], 'goodreads')

    def test_second_pass_never_touches_the_network(self):
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(self.book(), 'The Unknown', 'Riley Sager')], cache)
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        b2 = self.book()
        stats = S.attach([(b2, b2['title'], b2['author'])], cache)
        self.assertEqual(net.calls, [])                 # cached: zero requests
        self.assertEqual(stats['cached'], 1)
        self.assertEqual(stats['fetched'], 0)
        self.assertIn('New Avalon', b2['synopsis'])

    def test_the_buckets_are_disjoint_and_sum(self):
        # a cached miss counts ONCE — in 'none', never in 'cached' (L1 of the
        # review: the segments must reconcile with the books considered)
        a = self.book(id='nobodywrotethis--noone', title='Nobody Wrote This', author='No One')
        b = self.book()
        cache = {a['id']: {'text': '', 'src': 'none', 'at': '2026-09-23', 'gr': ''},
                 b['id']: {'text': 'A real blurb that is long enough to be usable here, sentence '
                                   'one, and a second sentence to clear the minimum.',
                           'src': 'apple', 'at': '2026-09-23', 'gr': ''}}
        net = self.net()
        stats = S.attach([(a, a['title'], a['author']), (b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])
        self.assertEqual((stats['fetched'], stats['cached'], stats['none'],
                          stats['pending'], stats['failed']), (0, 1, 1, 0, 0))
        self.assertEqual(sum(stats[k] for k in ('fetched', 'cached', 'none', 'pending', 'failed')), 2)

    def test_a_definitive_miss_is_cached_as_none(self):
        b = self.book(id='nobodywrotethis--noone', title='Nobody Wrote This', author='No One')
        cache = {}
        self.net(search=search_html(), apple={'results': []})
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual((stats['none'], stats['fetched']), (1, 0))
        self.assertEqual(b['synopsisSrc'], 'none')
        self.assertEqual(cache[b['id']]['src'], 'none')
        net = self.net(search=search_html(), apple={'results': []})
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])                 # a miss never refetches
        self.assertEqual(stats['none'], 1)

    def test_a_transient_failure_is_never_cached(self):
        b = self.book()
        cache = {}
        self.net(fail_on=('/search?', 'itunes'))
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(stats['failed'], 1)
        self.assertEqual(b['synopsisSrc'], 'pending')
        self.assertNotIn(b['id'], cache)                # retried, not poisoned
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(stats['fetched'], 1)           # the retry succeeds
        self.assertEqual(len(net.calls), 2)

    def test_budget_zero_fetches_nothing_and_says_so(self):
        b = self.book()
        cache = {}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        stats = S.attach([(b, b['title'], b['author'])], cache, budget=0)
        self.assertEqual(net.calls, [])
        self.assertEqual(stats['pending'], 1)
        self.assertEqual(b['synopsisSrc'], 'pending')
        self.assertEqual(cache, {})

    def test_the_budget_stops_after_n_books_in_priority_order(self):
        a = self.book(id='aaa--x', title='The Unknown', author='Riley Sager')
        b = self.book(id='bbb--y', title='The Unknown', author='Riley Sager')
        c = self.book(id='ccc--z', title='The Unknown', author='Riley Sager')
        cache = {}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.time = FakeClock(step=10)                     # budget 25 -> two books fit
        stats = S.attach([(a, a['title'], a['author']), (b, b['title'], b['author']),
                          (c, c['title'], c['author'])], cache, budget=25)
        self.assertEqual(stats['fetched'], 2)           # the first two, in order
        self.assertEqual(stats['pending'], 1)           # the third waits for the next build
        self.assertEqual(a['synopsisSrc'], 'goodreads')
        self.assertEqual(b['synopsisSrc'], 'goodreads')
        self.assertEqual(c['synopsisSrc'], 'pending')
        self.assertEqual(len(net.calls), 4)             # two searches + two pages, no more

    def test_one_book_one_lookup_even_when_it_renders_twice(self):
        a = self.book()
        b = self.book()                                 # the same book, two dicts (pick + volume)
        cache = {}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        stats = S.attach([(a, a['title'], a['author']), (b, b['title'], b['author'])], cache)
        self.assertEqual(len(net.calls), 2)             # one search + one page, not four
        self.assertEqual(stats['fetched'], 1)
        self.assertEqual(a['synopsis'], b['synopsis'])
        self.assertEqual(b['synopsisSrc'], 'goodreads')

    def test_unannounced_stubs_get_no_lookup_and_say_so(self):
        # 'Untitled' has nothing to look up — but the page still gets an honest
        # state instead of an empty block (the volume rows render it)
        b = {'id': 'untitled--x', 't': 'Untitled'}
        cache = {}
        net = self.net(search=search_html(), book=book_html())
        stats = S.attach([(b, 'Untitled', '')], cache)
        self.assertEqual(net.calls, [])
        self.assertEqual(b['synopsisSrc'], 'unannounced')
        self.assertEqual(b['synopsis'], '')
        self.assertEqual(stats['none'], 1)               # no blurb exists: a miss
        self.assertNotIn(b['id'], cache)                 # never a cache entry

    # Goodreads challenges a client without a browser after a few requests
    # (measured live 2026-11: the second book's search, even at the 10 s
    # pace). The blurb must still come from Goodreads before Apple's copy.
    APPLE = {'results': [{'trackName': 'The Unknown', 'artistName': 'Riley Sager',
                          'description': 'In 1926, five women disappeared from a remote island '
                                         'in Vermont; one hundred years later, it is happening again.'}]}

    def retry_entry(self):
        return {'text': self.APPLE['results'][0]['description'], 'src': 'apple',
                'at': '2026-11-17', 'retry': 'goodreads'}

    def test_a_challenge_pauses_goodreads_and_marks_apple_copies_for_retry(self):
        a = self.book(id='aaa--x')
        b = self.book(id='bbb--y')
        c = self.book(id='ccc--z')
        cache = {}
        net = self.net(search=[search_for('The Unknown', 'Riley Sager'), WAF_PAGE],
                       book=book_html(), apple=self.APPLE)
        stats = S.attach([(x, x['title'], x['author']) for x in (a, b, c)], cache)
        self.assertEqual([x['synopsisSrc'] for x in (a, b, c)], ['goodreads', 'apple', 'apple'])
        goodreads = [u for u in net.calls if 'goodreads.com' in u]
        self.assertEqual(len(goodreads), 3)       # a: search + page; b: the challenged search
        self.assertEqual(len(net.calls), 5)       # then Apple for b and for c, nothing more
        self.assertNotIn('retry', cache['aaa--x'])
        self.assertEqual(cache['bbb--y']['retry'], 'goodreads')
        self.assertEqual(cache['ccc--z']['retry'], 'goodreads')
        self.assertEqual((stats['fetched'], stats['goodreads'], stats['apple'], stats['retry']),
                         (3, 1, 2, 2))
        self.assertTrue(S.report_line(stats).endswith(' / 2 apple until goodreads answers'))

    def test_the_next_build_asks_goodreads_again_and_takes_its_blurb(self):
        b = self.book()
        cache = {b['id']: self.retry_entry()}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html(),
                       apple=self.APPLE)
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(b['synopsisSrc'], 'goodreads')
        self.assertIn('New Avalon', b['synopsis'])
        self.assertEqual(len(net.calls), 2)       # search + page; Apple is not asked again
        self.assertEqual(cache[b['id']]['src'], 'goodreads')
        self.assertNotIn('retry', cache[b['id']])
        self.assertEqual((stats['fetched'], stats['goodreads'], stats['retry']), (1, 1, 0))

    def test_a_goodreads_miss_makes_the_apple_copy_final(self):
        b = self.book()
        cache = {b['id']: self.retry_entry()}
        self.net(search=_read(NEXT_EMPTY_FX), apple=self.APPLE)   # Goodreads: no such book
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(b['synopsisSrc'], 'apple')
        self.assertIn('five women', b['synopsis'])
        self.assertNotIn('retry', cache[b['id']])
        self.assertEqual((stats['cached'], stats['retry']), (1, 0))
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])           # final: never asked again

    def test_books_with_no_blurb_go_before_the_retries(self):
        # an outage must not leave books blank: the budget fills a book with no
        # blurb before it upgrades one that already shows Apple's copy
        old = self.book(id='aaa--x')
        new = self.book(id='bbb--y')
        cache = {old['id']: self.retry_entry()}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.time = FakeClock(step=10)                 # budget 15 -> one lookup fits
        stats = S.attach([(old, old['title'], old['author']), (new, new['title'], new['author'])],
                         cache, budget=15)
        self.assertEqual(new['synopsisSrc'], 'goodreads')
        self.assertEqual(old['synopsisSrc'], 'apple')      # still shows Apple's copy
        self.assertEqual(len(net.calls), 2)                 # only the new book's lookup
        self.assertEqual(cache[old['id']]['retry'], 'goodreads')
        self.assertEqual((stats['fetched'], stats['cached'], stats['retry']), (1, 1, 1))

    def test_a_big_batch_fills_from_apple_once_the_goodreads_share_is_spent(self):
        # at the Goodreads pace a new book costs about 20 s, so a big batch (a
        # Goodreads import) must not wait 'not fetched yet' build after build:
        # past the share, new books take Apple's copy, marked for retry
        S.GOODREADS_SHARE = 0.5
        books = [self.book(id=i) for i in ('aaa--w', 'bbb--x', 'ccc--y', 'ddd--z')]
        cache = {}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html(),
                       apple=self.APPLE)
        S.time = FakeClock(step=10)       # budget 40: Goodreads until 20 s, Apple until 40 s
        stats = S.attach([(x, x['title'], x['author']) for x in books], cache, budget=40)
        self.assertEqual([x['synopsisSrc'] for x in books], ['goodreads', 'apple', 'apple', 'pending'])
        self.assertEqual(len([u for u in net.calls if 'goodreads.com' in u]), 2)
        self.assertEqual(cache['bbb--x']['retry'], 'goodreads')
        self.assertEqual(cache['ccc--y']['retry'], 'goodreads')
        self.assertEqual((stats['fetched'], stats['pending'], stats['retry']), (3, 1, 2))

    def test_an_offline_build_never_asks_goodreads_again(self):
        b = self.book()
        cache = {b['id']: self.retry_entry()}
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(b, b['title'], b['author'])], cache, budget=0)
        self.assertEqual(net.calls, [])
        self.assertEqual(b['synopsisSrc'], 'apple')
        self.assertEqual(cache[b['id']]['retry'], 'goodreads')

    # ---- the book's own Goodreads page (THS-22 piece 2) ----
    # search_for() answers with the real fixture's first row, whose address is
    # /book/show/217165422-fourth-wing
    OWN_ID = '217165422'
    OWN_URL = 'https://www.goodreads.com/book/show/217165422'

    def no_blurb_page(self):
        html = book_html()
        m = re.search(r'(<script id="__NEXT_DATA__" type="application/json">)(.*?)(</script>)', html, re.S)
        data = json.loads(m.group(2))
        for k, v in data['props']['pageProps']['apolloState'].items():
            if k.startswith('Book:') and isinstance(v, dict) and v.get('title') == 'The Unknown':
                v['description'] = ''
                v.pop('description({"stripped":true})', None)
        return html[:m.start(2)] + json.dumps(data) + html[m.end(2):]

    def cached_goodreads(self, b, **extra):
        return {b['id']: dict({'text': 'In 1926, five women disappeared from a remote island in '
                                       'Vermont; one hundred years later, it is happening again.',
                               'src': 'goodreads', 'at': '2026-11-01'}, **extra)}

    def test_a_goodreads_match_keeps_its_id_and_the_book_ships_its_page(self):
        b = self.book()
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(cache[b['id']]['gr'], self.OWN_ID)
        self.assertEqual(b['grUrl'], self.OWN_URL)

    def test_a_matched_page_with_no_blurb_still_gives_its_id(self):
        # Apple's copy shows, and the link still opens the book's own page
        b = self.book()
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=self.no_blurb_page(),
                 apple=self.APPLE)
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(b['synopsisSrc'], 'apple')
        self.assertEqual(cache[b['id']]['gr'], self.OWN_ID)
        self.assertEqual(b['grUrl'], self.OWN_URL)
        self.assertNotIn('retry', cache[b['id']])       # Goodreads answered: nothing to retry

    def test_a_search_that_lands_on_a_book_page_takes_the_pages_own_id(self):
        b = self.book()
        cache = {}
        self.net(search=book_html())
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(cache[b['id']]['gr'], '243596193')

    def test_a_page_that_is_a_different_book_gives_no_id(self):
        # the box-set lesson: a matched row whose page says otherwise is no match
        b = self.book(title='Onyx Storm', author='Rebecca Yarros')
        cache = {}
        self.net(search=search_for('Onyx Storm', 'Rebecca Yarros'), book=book_html(),
                 apple={'results': []})
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(cache[b['id']].get('gr'), '')
        self.assertNotIn('grUrl', b)

    def test_no_match_on_goodreads_is_a_settled_no_page_not_a_retry(self):
        b = self.book(id='nobodywrotethis--noone', title='Nobody Wrote This', author='No One')
        cache = {}
        self.net(search=_read(NEXT_EMPTY_FX), apple={'results': []})
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(cache[b['id']]['gr'], '')
        self.assertNotIn('grUrl', b)
        net = self.net(search=_read(NEXT_EMPTY_FX))
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])

    def test_a_cached_book_with_no_id_gets_it_from_one_search_and_never_again(self):
        b = self.book()
        cache = self.cached_goodreads(b)
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        stats = S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(len(net.calls), 1)             # the search only: its blurb is cached
        self.assertIn('/search?', net.calls[0])
        self.assertEqual(cache[b['id']]['gr'], self.OWN_ID)
        self.assertEqual(b['grUrl'], self.OWN_URL)
        self.assertEqual((stats['cached'], stats['fetched'], stats['linked']), (1, 0, 1))
        self.assertTrue(S.report_line(stats).endswith(' / 1 goodreads pages linked'))
        net = self.net(search=search_for('The Unknown', 'Riley Sager'))
        b2 = self.book()
        S.attach([(b2, b2['title'], b2['author'])], cache)
        self.assertEqual(net.calls, [])
        self.assertEqual(b2['grUrl'], self.OWN_URL)     # from the cache, no request

    def test_a_cached_book_goodreads_has_no_match_for_is_settled_without_a_link(self):
        b = self.book(id='nobodywrotethis--noone', title='Nobody Wrote This', author='No One')
        cache = {b['id']: {'text': '', 'src': 'none', 'at': '2026-11-01'}}
        self.net(search=_read(NEXT_EMPTY_FX))
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(cache[b['id']]['gr'], '')
        self.assertNotIn('grUrl', b)
        net = self.net(search=_read(NEXT_EMPTY_FX))
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])

    def test_filling_ids_stops_at_a_challenge_and_asks_again_next_build(self):
        a = self.book(id='aaa--x')
        b = self.book(id='bbb--y')
        cache = self.cached_goodreads(a)
        cache.update(self.cached_goodreads(b))
        net = self.net(search=[WAF_PAGE])
        stats = S.attach([(x, x['title'], x['author']) for x in (a, b)], cache)
        self.assertEqual(len(net.calls), 1)             # the challenge ends Goodreads for this build
        self.assertNotIn('gr', cache['aaa--x'])         # unanswered: not settled
        self.assertNotIn('gr', cache['bbb--y'])
        self.assertEqual(stats['linked'], 0)
        net = self.net(search=search_for('The Unknown', 'Riley Sager'))
        S.attach([(x, x['title'], x['author']) for x in (a, b)], cache)
        self.assertEqual(len(net.calls), 2)
        self.assertEqual(cache['aaa--x']['gr'], self.OWN_ID)

    def test_filling_ids_stays_inside_the_budget_in_priority_order(self):
        books = [self.book(id=i) for i in ('aaa--x', 'bbb--y', 'ccc--z')]
        cache = {}
        for x in books:
            cache.update(self.cached_goodreads(x))
        net = self.net(search=search_for('The Unknown', 'Riley Sager'))
        S.time = FakeClock(step=10)                     # budget 25: two searches fit
        stats = S.attach([(x, x['title'], x['author']) for x in books], cache, budget=25)
        self.assertEqual(len(net.calls), 2)
        self.assertEqual(stats['linked'], 2)
        self.assertIn('grUrl', books[0])
        self.assertIn('grUrl', books[1])
        self.assertNotIn('grUrl', books[2])
        self.assertNotIn('gr', cache['ccc--z'])         # next build continues

    def test_an_offline_build_asks_for_no_ids(self):
        b = self.book()
        cache = self.cached_goodreads(b)
        net = self.net(search=search_for('The Unknown', 'Riley Sager'))
        S.attach([(b, b['title'], b['author'])], cache, budget=0)
        self.assertEqual(net.calls, [])
        self.assertNotIn('grUrl', b)

    def test_new_books_and_retries_go_before_the_id_fill(self):
        old = self.book(id='aaa--x')
        new = self.book(id='bbb--y')
        cache = self.cached_goodreads(old)
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.time = FakeClock(step=10)                     # budget 15: one request chain fits
        S.attach([(old, old['title'], old['author']), (new, new['title'], new['author'])],
                 cache, budget=15)
        self.assertEqual(new['synopsisSrc'], 'goodreads')
        self.assertIn('grUrl', new)
        self.assertNotIn('grUrl', old)                  # the cached book waits its turn
        self.assertEqual(len(net.calls), 2)

    def test_an_imported_book_id_wins_and_costs_no_request(self):
        imported = 'https://www.goodreads.com/book/show/61431922'
        b = dict(self.book(), grUrl=imported)
        cache = self.cached_goodreads(b, gr='999')      # even a cached id loses to the import
        net = self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(net.calls, [])
        self.assertEqual(b['grUrl'], imported)
        # the same book rendering elsewhere (a series volume) shows the same page
        v = {'id': b['id'], 't': 'The Unknown'}
        S.attach([(b, b['title'], b['author']), (v, 'The Unknown', 'Riley Sager')], cache)
        self.assertEqual(v['grUrl'], imported)

    def test_a_new_imported_book_keeps_its_id_through_the_lookup(self):
        imported = 'https://www.goodreads.com/book/show/61431922'
        b = dict(self.book(), grUrl=imported)
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(b['grUrl'], imported)
        self.assertEqual(b['synopsisSrc'], 'goodreads')
        self.assertNotIn('gr', cache[b['id']])          # the import owns the id

    def test_a_matched_row_whose_page_is_challenged_keeps_its_id(self):
        b = self.book()
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=WAF_PAGE, apple=self.APPLE)
        S.attach([(b, b['title'], b['author'])], cache)
        self.assertEqual(cache[b['id']]['retry'], 'goodreads')   # the blurb is still asked again
        self.assertEqual(cache[b['id']]['gr'], self.OWN_ID)
        self.assertEqual(b['grUrl'], self.OWN_URL)

    def test_series_volumes_key_on_their_canonical_id(self):
        # a volume dict (t, no author) still caches under the build's id
        v = {'id': 'theunknown--rileysager', 't': 'The Unknown'}
        cache = {}
        self.net(search=search_for('The Unknown', 'Riley Sager'), book=book_html())
        S.attach([(v, 'The Unknown', 'Riley Sager')], cache)
        self.assertEqual(v['synopsisSrc'], 'goodreads')
        self.assertIn('theunknown--rileysager', cache)


class CacheFileTests(Base):
    def test_roundtrip_and_corruption(self):
        p = os.path.join(self.tmp, 'synopsis-cache.json')
        self.assertTrue(S.save({'a--b': {'text': 'hi', 'src': 'goodreads', 'at': '2026-09-23'}}, p))
        self.assertEqual(S.load(p)['a--b']['text'], 'hi')
        self.assertEqual(S.load(os.path.join(self.tmp, 'missing.json')), {})
        with open(p, 'w') as f:
            f.write('{not json')
        self.assertEqual(S.load(p), {})
        # a list is not a cache
        with open(p, 'w') as f:
            f.write('[1,2,3]')
        self.assertEqual(S.load(p), {})

    def test_save_is_atomic_and_leaves_no_temp_files(self):
        p = os.path.join(self.tmp, 'synopsis-cache.json')
        cache = {}
        for i in range(5):
            cache['k%d' % i] = {'text': 't', 'src': 'none'}
            self.assertTrue(S.save(cache, p))
        self.assertEqual(sorted(os.listdir(self.tmp)), ['synopsis-cache.json'])
        self.assertEqual(len(S.load(p)), 5)

    def test_save_failure_reports_false(self):
        d = os.path.join(self.tmp, 'nope')
        os.makedirs(d)
        os.chmod(d, 0o500)
        try:
            self.assertFalse(S.save({'a': {}}, os.path.join(d, 'synopsis-cache.json')))
        finally:
            os.chmod(d, 0o700)


class ReportTests(Base):
    def test_line_matches_the_issue_shape(self):
        line = S.report_line({'fetched': 12, 'goodreads': 10, 'apple': 2, 'cached': 9,
                              'none': 2, 'pending': 0, 'failed': 0})
        self.assertEqual(line, 'synopses: 12 fetched (10 goodreads, 2 apple) / 9 cached / 2 none')

    def test_extras_appear_only_when_they_happened(self):
        line = S.report_line({'fetched': 0, 'goodreads': 0, 'apple': 0, 'cached': 180,
                              'none': 4, 'pending': 30, 'failed': 3})
        self.assertEqual(line, 'synopses: 0 fetched / 180 cached / 4 none'
                               ' / 30 pending (next build continues)'
                               ' / 3 failed (retried next build)')
        self.assertNotIn('goodreads', line)


if __name__ == '__main__':
    unittest.main()
