"""The season table (build.SEASONS) — one clock for drink, look and quote.

Intent (the Christmas plan): Christmas runs 1 November to 6 January, autumn
ends on 31 October, winter starts on 7 January, and every day of the year
belongs to exactly one season, so the page never shows no season or two.
Run: cd pipeline && python3 -m unittest test_seasons
"""
import sys, os, unittest
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import SEASONS, season_of


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


if __name__ == '__main__':
    unittest.main()
