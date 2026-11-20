"""The season calendar: each season's first and last day ('MM-DD', both
inclusive; a season whose end is before its start wraps the new year). One
table for the build's season look (build.SEASONS) and the server's check of
a season stamp. It imports nothing and reads nothing, so the server can load
it under its write locks."""

SEASON_DATES = {
    'autumn': ('09-01', '10-31'),
    'christmas': ('11-01', '01-06'),
    'winter': ('01-07', '02-29'),
    'spring': ('03-01', '05-31'),
    'summer': ('06-01', '08-31'),
}
