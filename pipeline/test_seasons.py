"""The season table (build.SEASONS) — one clock for drink, look and quote.

Intent (the Christmas plan): Christmas runs 1 November to 6 January, autumn
ends on 31 October, winter starts on 7 January, and every day of the year
belongs to exactly one season, so the page never shows no season or two.
Intent (the four-season plan): every season carries a complete look — six
corner colours, a drink whose art exists, 24 quotes — and every line of text
on the reading corner reaches 4.5:1 contrast on the corner's inner colour.
Run: cd pipeline && python3 -m unittest test_seasons
"""
import sys, os, unittest
from datetime import date, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build import SEASONS, season_of

ART = os.path.join(os.path.dirname(HERE), '.lavish', 'assets')


def _luminance(hex_colour):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _holders(d):
    md = d.strftime('%m-%d')
    out = []
    for s in SEASONS:
        a, b = s['start'], s['end']
        if (a <= md <= b) if a <= b else (md >= a or md <= b):
            out.append(s['key'])
    return out


class TestSeasonTable(unittest.TestCase):
    def test_every_day_of_a_leap_year_has_exactly_one_season(self):
        d = date(2028, 1, 1)
        while d.year == 2028:
            self.assertEqual(len(_holders(d)), 1, '%s -> %s' % (d, _holders(d)))
            self.assertEqual(season_of(d.month, d.day), _holders(d)[0])
            d += timedelta(days=1)

    def test_christmas_boundaries(self):
        self.assertEqual(season_of(10, 31), 'autumn')
        self.assertEqual(season_of(11, 1), 'christmas')
        self.assertEqual(season_of(1, 6), 'christmas')
        self.assertEqual(season_of(1, 7), 'winter')


class TestSeasonLooks(unittest.TestCase):
    def test_every_season_has_a_complete_look(self):
        for s in SEASONS:
            with self.subTest(season=s['key']):
                corner = s['corner']
                self.assertEqual(sorted(corner), sorted(['outer', 'inner', 'border', 'eyebrow', 'quote', 'recent']))
                for v in corner.values():
                    self.assertRegex(v, r'^#[0-9A-Fa-f]{6}$')
                self.assertEqual(len(s['quotes']), 24)
                self.assertEqual(len(set(s['quotes'])), 24, 'a quote repeats')
                d = s['drink']
                self.assertTrue(d['alt'] and d['label'])
                self.assertTrue(os.path.isfile(os.path.join(ART, os.path.basename(d['img']))), d['img'])

    def test_each_drink_belongs_to_one_season(self):
        imgs = [s['drink']['img'] for s in SEASONS]
        self.assertEqual(len(imgs), len(set(imgs)))

    def test_corner_text_reaches_4_5_to_1(self):
        for s in SEASONS:
            c = s['corner']
            for part in ('eyebrow', 'quote', 'recent'):
                with self.subTest(season=s['key'], part=part):
                    self.assertGreaterEqual(_contrast(c[part], c['inner']), 4.5)


if __name__ == '__main__':
    unittest.main()
