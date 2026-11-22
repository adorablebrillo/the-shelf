#!/usr/bin/env python3
"""Home's reading-now card shows every book she is reading now.

Intent — the reader's ask: "if i am reading multiple books, then i want them to
show too under reading now section". Every want book with the reading flag gets
its own row in the card, newest first; each row keeps its own I read today and
finished it; on a laptop the card still sits beside the season goal.

Drives the made-up shelf served by verify-the-shelf. It writes marks and a
reading day into the served shelf's `reader-state.json` — and a reading day
cannot be taken back over the API — so run it against a scratch volume only,
seeded with `seed-demo.py <cfg> <root> --surveyed`, and delete
`reader-state.json` between runs.

Run: python3 tests/home_reading_now.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import date

from playwright.sync_api import sync_playwright

URL = sys.argv[1].rstrip('/')
API = URL + '/api/state'
NOW_MS = int(time.time() * 1000)

# made-up picks of the verify skill's shelf: id -> title as the page prints it,
# flagged oldest first so the page must list them newest first
READING = [('thepenaltybox--rubycalder', 'The Penalty Box'),
           ('queenofthornsanddusk--selenemarr', 'Queen of Thorns and Dusk'),
           ('faceoffatmidnight--domenicpace', 'Faceoff at Midnight')]


def post(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def get():
    return json.loads(urllib.request.urlopen(API, timeout=15).read().decode())


def box(page, selector):
    return page.evaluate("""(s) => { const r = document.querySelector(s).getBoundingClientRect();
      return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; }""", selector)


post({'states': {i: {'s': 'want', 't': NOW_MS} for i, _ in READING},
      'reading': {i: {'s': True, 't': NOW_MS + k} for k, (i, _) in enumerate(READING)}})
newest_first = [t for _, t in reversed(READING)]

with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        # 1 · laptop: one row per reading book, newest first, beside the goal
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
        page.goto(URL + '/', wait_until='networkidle')
        card = page.get_by_role('region', name='Reading now')
        titles = card.locator('h2').all_inner_texts()
        assert titles == newest_first, titles
        assert card.get_by_text('Reading now · 3 books').is_visible()
        rn, season = box(page, '[data-m="readnow"]'), box(page, '[data-m="season"]')
        assert rn['right'] <= season['left'] and abs(rn['top'] - season['top']) < 2, (rn, season)
        print('laptop: %d rows %r, beside the season goal' % (len(titles), titles), flush=True)

        # 2 · each row's I read today logs a day for its own book only
        middle_id, middle = READING[1]
        card.get_by_role('button', name='log a reading day today for ' + middle).click()
        pressed = card.get_by_role('button', name='reading day logged today for ' + middle)
        pressed.wait_for()
        assert pressed.get_attribute('aria-pressed') == 'true'
        assert card.get_by_role('button', name='log a reading day today for ' + READING[0][1]).is_visible()
        for _ in range(30):
            days = get().get('days', {})
            if days.get(middle_id):
                break
            time.sleep(0.2)
        assert days.get(middle_id) == [date.today().isoformat()], days
        assert not days.get(READING[0][0]) and not days.get(READING[2][0]), days
        print('I read today: logged for %r only' % middle, flush=True)

        # 3 · each row's finished it files its own book; the others stay
        card.get_by_role('button', name='mark %s read — finished it' % middle).click()
        page.wait_for_function("""(t) => ![...document.querySelectorAll(
          'section[aria-label="Reading now"] h2')].some(h => h.textContent === t)""", arg=middle)
        left = card.locator('h2').all_inner_texts()
        assert left == [t for t in newest_first if t != middle], left
        for _ in range(30):
            state = get()
            if (state.get('states', {}).get(middle_id) or {}).get('s') == 'read':
                break
            time.sleep(0.2)
        assert state['states'][middle_id]['s'] == 'read', state['states'].get(middle_id)
        print('finished it: %r filed read, %r stay' % (middle, left), flush=True)
        page.close()

        # 4 · a phone: the rows stack in the card, nothing overflows the page
        page = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
        page.goto(URL + '/', wait_until='networkidle')
        card = page.get_by_role('region', name='Reading now')
        assert card.locator('h2').all_inner_texts() == left
        heights = card.evaluate("""(c) => [...c.querySelectorAll('[data-m=verdicts] button')]
          .map(b => b.getBoundingClientRect().height)""")
        assert min(heights) >= 44, heights
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        print('phone 390: %d rows, 44 px buttons, no sideways scroll' % len(left), flush=True)
        page.close()
    finally:
        browser.close()
print('OK')
