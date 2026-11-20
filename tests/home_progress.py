#!/usr/bin/env python3
"""THS-43 (Home part 2): the reading day, the weekly streak, the season goal.

Intent — the accepted Home plan, part 2: one tap on the reading-now card logs
today as a reading day; the shelf unions the days each device logged, so a day
posted from a phone and a day tapped on the desktop both count, and the same day
posted twice is still one day; the streak counts the weeks of the season that
hold a reading day and keeps one rest week; the season ring counts the books
marked *read* or *loved* inside the season's own days, and reaching the goal
presses that season's stamp in for good.

Intent (the plan's part-1 rule, kept by part 2's stamps): under prefers-reduced-
motion a pressed stamp shows no press. The page is therefore opened with reduced
motion emulated for real, and the seal's own computed style is read back.

Drives the made-up shelf served by verify-the-shelf. It writes reading days and
marks into the served shelf's `reader-state.json` — and a reading day cannot be
taken back over the API — so run it against a scratch volume only, never a
reader's own, and delete `reader-state.json` between runs.

Run: python3 tests/home_progress.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'pipeline'))
from build import SEASONS            # the one season table the page and the corner read
from playwright.sync_api import sync_playwright

URL = sys.argv[1].rstrip('/')
API = URL + '/api/state'
TODAY = date.today()


def post(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'},
                                 method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def get():
    return json.loads(urllib.request.urlopen(API, timeout=15).read().decode())


def wait_for(what, fn, timeout=8.0):
    """Poll the server until the fact holds — the page posts asynchronously."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = fn()
        if last:
            return last
        time.sleep(0.2)
    raise AssertionError('%s: %r' % (what, last))


def season_start(today):
    """The season holding `today` and the day it began, from the shipped table.
    A season that wraps the new year (Christmas, 1 Nov – 6 Jan) began last year."""
    for s in SEASONS:
        a = date(today.year, int(s['start'][:2]), int(s['start'][3:]))
        b = date(today.year, int(s['end'][:2]), int(s['end'][3:]))
        if a <= b:
            if a <= today <= b:
                return s, a
        elif today >= a:
            return s, a
        elif today <= b:
            return s, date(today.year - 1, a.month, a.day)
    raise AssertionError('no season holds %s' % today)


SEASON, START = season_start(TODAY)
STAMP_KEY = 'season:%s:%d' % (SEASON['key'], START.year)
SEASON_LABEL = (SEASON['key'].capitalize() + ' ' + str(START.year)).lower()
out_of_season = START - timedelta(days=3)
rest_week_day = TODAY - timedelta(days=14)      # two Mondays back: one week between
in_season_gap = rest_week_day >= START

with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        page = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
        page.goto(URL, wait_until='networkidle')
        ids = page.evaluate("""() => {
          const d = window.SHELF_DATA || {}, out = [];
          (d.books || []).forEach(b => b.id && out.push(b.id));
          (d.added || []).forEach(b => b.id && out.push(b.id));
          (d.series || []).forEach(s => (s.books || []).forEach(v => v.id && out.push(v.id)));
          return out;
        }""")
        goal = page.evaluate("() => (window.SHELF_DATA || {}).seasonGoal")
        assert isinstance(goal, int) and goal > 0, 'the build shipped no season goal: %r' % (goal,)
        assert len(ids) >= goal + 2, 'need %d book ids, the shelf has %d' % (goal + 2, len(ids))
        now_ms = int(datetime.now().timestamp() * 1000)
        book = ids[0]

        # a known starting point: no mark on the books this run counts
        post({'states': {i: {'s': None, 't': now_ms} for i in ids[:goal + 2]}})

        # 1 · one tap on the card logs today, and the button says so
        post({'states': {book: {'s': 'want', 't': now_ms}},
              'reading': {book: {'s': True, 't': now_ms}}})
        page.reload(wait_until='networkidle')
        tap = page.get_by_role('button', name='log a reading day today for')
        tap.wait_for()
        # the card's own words, read back (the shelf sets these buttons in small
        # caps, so the comparison is case-insensitive)
        assert tap.inner_text().strip().lower() == 'i read today', 'the card reads %r' % tap.inner_text()
        tap.click()
        logged = wait_for('the tap did not reach the server',
                          lambda: (book in get().get('days', {})) and get()['days'][book])
        assert logged == [TODAY.isoformat()], 'the tap logged %r' % (logged,)
        done = page.get_by_role('button', name='reading day logged today for')
        done.wait_for()
        assert done.inner_text().strip().lower() == 'read today ✓', 'the tap button reads %r' % (done.inner_text(),)
        print('%s: one tap logged %s as a reading day, and the card reads logged'
              % (book, TODAY), flush=True)

        # 2 · the same day posted twice is one day; a second device's day joins it
        post({'days': {book: [TODAY.isoformat()]}})
        post({'days': {book: [rest_week_day.isoformat()]}})
        merged = wait_for('the phone day did not merge',
                          lambda: (len(get().get('days', {}).get(book, [])) == 2)
                          and get()['days'][book])
        assert merged == sorted([rest_week_day.isoformat(), TODAY.isoformat()]), \
            'the two devices did not merge: %r' % (merged,)
        page.reload(wait_until='networkidle')
        streak = wait_for('the streak line never appeared',
                          lambda: page.locator('[data-m="streakline"]').count()
                          and page.locator('[data-m="streakline"]').inner_text().lower())
        want_weeks = 2 if in_season_gap else 1
        assert streak == '%d reading week%s in a row' % (
            want_weeks, '' if want_weeks == 1 else 's'), \
            'the streak reads %r with days on %s and %s' % (streak, rest_week_day, TODAY)
        print('streak: %r (days %s + %s, one rest week kept, season began %s)'
              % (streak, rest_week_day, TODAY, START), flush=True)

        # 3 · the ring counts the season's own days only
        inside = ids[1:1 + goal - 2]
        late_id = ids[goal + 1]
        late_ms = int(datetime.combine(out_of_season, datetime.min.time()).timestamp() * 1000)
        post({'states': {i: {'s': 'read', 't': now_ms} for i in inside}})
        post({'states': {late_id: {'s': 'read', 't': late_ms}}})
        page.reload(wait_until='networkidle')
        head = page.locator('[data-m="season"] h2').inner_text().lower()
        assert head == '%d of %d books this season' % (len(inside), goal), \
            'the ring counted a mark dated %s, before the season began: %r' % (out_of_season, head)
        # the ring's own number is SVG text, so it is read as text, not as a box
        assert page.locator('[data-m="ringdone"]').text_content() == str(len(inside))
        print('ring: %r with one mark dated %s (before the season)'
              % (head, out_of_season), flush=True)

        # 4 · reaching the goal presses that season's stamp in, and the row keeps it
        page.set_viewport_size({'width': 1280, 'height': 900})
        post({'states': {i: {'s': 'loved', 't': now_ms} for i in ids[1 + goal - 2:1 + goal]}})
        page.reload(wait_until='networkidle')
        kept = wait_for('no kept stamp for %s on the server' % STAMP_KEY,
                        lambda: (get().get('stamps', {}).get(STAMP_KEY) or {}).get('s')
                        and get()['stamps'])
        head = page.locator('[data-m="season"] h2').inner_text().lower()
        assert head == '%s goal reached' % SEASON['key'], \
            'at %d marks the panel reads %r' % (goal, head)
        row = page.locator('[aria-label="Your stamps"]').inner_text().lower()
        assert SEASON_LABEL in row, 'the stamp row does not show it: %r' % (row[:200],)
        # the press shows no motion here: reduced motion is emulated for real
        seal = page.evaluate("""(label) => {
          const cell = [...document.querySelectorAll('[data-m="stampcell"]')]
            .find(e => (e.textContent || '').toLowerCase().includes(label));
          if (!cell) return 'no such stamp cell';
          const cs = getComputedStyle(cell.querySelector('svg'));
          return cs.animationName + ' ' + cs.animationDuration;
        }""", SEASON_LABEL)
        assert seal == 'none 0s', 'the pressed seal still animates under reduced motion: %r' % (seal,)
        print('stamp: %r, and %s is kept on the server and in the row (seal: %s under reduced motion)'
              % (head, STAMP_KEY, seal), flush=True)

        # 5 · the row comes back from the server on a clean local copy
        page.evaluate('() => localStorage.clear()')
        page.reload(wait_until='networkidle')
        wait_for('the stamp row never returned',
                 lambda: page.locator('[aria-label="Your stamps"]').count()
                 and SEASON_LABEL in page.locator('[aria-label="Your stamps"]').inner_text().lower())
        print('return: the stamp row survived a cleared local copy', flush=True)
        print('OK', flush=True)
    finally:
        browser.close()
