#!/usr/bin/env python3
"""Series cover lookups: a refusal is not a miss (blank series thumbnails).

A cover lookup that a provider refused (Apple Books 403/429, Google Books
"Quota exceeded") used to be saved as a permanent '<slug>.none' miss, so the
volume stayed blank on the Series page for good. These tests drive
ensure_cover — the call the Series build makes per volume — against the
network seam (_get_json), with a saved real Apple Books answer and the error
urllib raises when a provider refuses.
Run from pipeline/:  python3 -m unittest test_covers -v
"""
import io, json, os, shutil, tempfile, time, unittest, urllib.error

import build

HERE = os.path.dirname(os.path.abspath(__file__))
# a real Apple Books search answer — for any other title it is a genuine no-match
APPLE = json.load(open(os.path.join(HERE, 'testdata', 'apple-search-fourthwing.json')))
TITLE, AUTHOR = 'Magnolia Bloom', 'J. Hart'


def refused(url, code, msg):
    return urllib.error.HTTPError(url, code, msg, {}, io.BytesIO(b''))


class Providers:
    """The three cover providers as _get_json sees them; counts requests."""

    def __init__(self, refuse=False):
        self.refuse = refuse
        self.calls = []

    def __call__(self, url, timeout=25):
        self.calls.append(url)
        if 'itunes.apple.com' in url:
            if self.refuse:
                raise refused(url, 429, 'Too Many Requests')
            return APPLE
        if 'googleapis.com' in url:
            if self.refuse:
                raise refused(url, 429, 'Quota exceeded for quota metric Queries per day')
            return {'kind': 'books#volumes', 'totalItems': 0}
        if 'openlibrary.org' in url:
            return {'numFound': 0, 'docs': []}
        raise AssertionError('unexpected request ' + url)


class RefusalIsNotAMissTests(unittest.TestCase):
    def setUp(self):
        self.covers = tempfile.mkdtemp(prefix='shelf-covers-')
        self._get = build._get_json
        self._offline = build.OFFLINE
        build.OFFLINE = False
        self.miss = os.path.join(
            self.covers, build.slug({'title': TITLE, 'author': AUTHOR}) + '.none')

    def tearDown(self):
        build._get_json = self._get
        build.OFFLINE = self._offline
        shutil.rmtree(self.covers)

    def build_once(self, providers):
        build._get_json = providers
        return build.ensure_cover('', TITLE, AUTHOR, self.covers)

    def test_a_refused_lookup_is_retried_by_the_next_build(self):
        self.assertEqual(self.build_once(Providers(refuse=True)), '')
        self.assertFalse(os.path.exists(self.miss), 'a refusal was saved as a miss')
        again = Providers(refuse=True)
        self.build_once(again)
        self.assertTrue(any('itunes.apple.com' in u for u in again.calls),
                        'the next build did not look the cover up again')

    def test_a_genuine_miss_is_saved_and_not_looked_up_again(self):
        first = Providers()
        self.assertEqual(self.build_once(first), '')
        self.assertEqual(len(first.calls), 3)
        self.assertTrue(os.path.exists(self.miss))
        again = Providers()
        self.build_once(again)
        self.assertEqual(again.calls, [])

    def test_an_old_saved_miss_is_looked_up_again(self):
        # misses saved by older builds include refusals: they must not stay forever
        with open(self.miss, 'w') as f:
            f.write('no cover found\n')
        old = time.time() - (build.COVER_MISS_DAYS + 1) * 86400
        os.utime(self.miss, (old, old))
        again = Providers()
        self.build_once(again)
        self.assertEqual(len(again.calls), 3)
        self.assertGreater(os.path.getmtime(self.miss), old, 'the miss was not saved again')


if __name__ == '__main__':
    unittest.main()
