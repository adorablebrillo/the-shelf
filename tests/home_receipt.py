#!/usr/bin/env python3
"""THS-98: Home's layout — the counter, with the season goal as a café receipt.

Intent — the captain's choices on the Home layout plan: reading now sits beside
the season goal; the goal is a receipt that lists each book finished this
season, one line each, with a total; the picks are compact cards on a phone
(small cover at the left, the four choices in one row, the 44 px tap floor); a
laptop shows the picks in a wide grid and the small blocks three across.

Drives the made-up shelf served by verify-the-shelf. It writes marks into the
served shelf's `reader-state.json`, so run it against a scratch volume only,
seeded with `seed-demo.py <cfg> <root> --surveyed` before launch.

Run: python3 tests/home_receipt.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

URL = sys.argv[1].rstrip('/')
API = URL + '/api/state'
DAY_MS = 86400000
NOW_MS = int(time.time() * 1000)

# made-up books of the verify skill's shelf: id -> title as the page prints it
FINISHED = [('slipstream--nadiakerr', 'Slipstream', 'read', 6),
            ('lastcallatrosies--hannahbell', "Last Call at Rosie's", 'loved', 4),
            ('thewinterguest--irisvale', 'The Winter Guest', 'read', 2)]
READING = 'bluelinebillionaire--sawyerkent'


def post(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def box(page, selector):
    return page.evaluate("""(s) => { const r = document.querySelector(s).getBoundingClientRect();
      return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; }""", selector)


# the season's own days: marks well inside it for the receipt, and one dated
# before it began, which the ring does not count and the receipt must not list
states = {i: {'s': v, 't': NOW_MS - d * DAY_MS} for i, _, v, d in FINISHED}
states[READING] = {'s': 'want', 't': NOW_MS - DAY_MS}
states['wildfireseason--adaquill'] = {'s': 'read', 't': NOW_MS - 400 * DAY_MS}
post({'states': states, 'reading': {READING: {'s': True, 't': NOW_MS}}})

with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        # 1 · laptop: reading now beside the goal, the receipt adds up to the ring
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
        page.goto(URL + '/', wait_until='networkidle')
        rn, season = box(page, '[data-m="readnow"]'), box(page, '[data-m="season"]')
        assert rn['right'] <= season['left'] and abs(rn['top'] - season['top']) < 2, (rn, season)
        lines = page.locator('[data-m="rcptlines"] > li')
        assert lines.count() == len(FINISHED), 'receipt lines: %d' % lines.count()
        text = [t.lower() for t in lines.all_inner_texts()]
        for (_, title, _, _), line in zip(sorted(FINISHED, key=lambda f: -f[3]), text):
            assert title.lower() in line, (title, line)   # oldest first
        assert page.locator('[data-m="rcptlines"] .lv').count() == 1     # the loved heart
        ring = page.locator('[data-m="ringdone"]').text_content()
        assert ring == str(len(FINISHED)), ring
        total = page.locator('[data-m="rcpttotal"] .v').text_content()
        assert total == '%d of 6' % len(FINISHED), total
        assert page.locator('[data-m="receipt"]').inner_text().lower().count('wildfire') == 0
        print('laptop: %d receipt lines, ring %s, total %r' % (lines.count(), ring, total), flush=True)

        # 2 · laptop: the picks in two columns, the three small blocks in one row
        cards = page.locator('[data-m="pickcard"]:not([data-lead])')
        lefts = {round(cards.nth(i).bounding_box()['x']) for i in range(cards.count())}
        assert len(lefts) == 2, 'pick columns: %r' % (lefts,)
        small = page.evaluate("""() => [...document.querySelectorAll('[data-m="smallrow"] > section')]
          .map(s => Math.round(s.getBoundingClientRect().top))""")
        assert len(small) >= 2 and len(set(small)) == 1, 'small blocks are not in one row: %r' % (small,)
        print('laptop: 2 pick columns, %d small blocks in one row' % len(small), flush=True)
        page.close()

        # 3 · a phone: one column, the receipt folded behind a button, compact
        #     cards with the four choices in one row at the 44 px floor
        for width in (390, 360):
            page = browser.new_page(viewport={'width': width, 'height': 844}, reduced_motion='reduce')
            page.goto(URL + '/', wait_until='networkidle')
            assert page.locator('[data-m="rcptlines"]').is_hidden()
            toggle = page.get_by_role('button', name='receipt')
            assert toggle.bounding_box()['height'] >= 44
            toggle.click()
            assert page.locator('[data-m="rcptlines"] > li').first.is_visible()
            for card in page.locator('[data-m="pickcard"]').all():
                rows = card.evaluate("""(c) => new Set([...c.querySelectorAll(':scope > [data-m=verdicts] button')]
                  .map(b => Math.round(b.getBoundingClientRect().top))).size""")
                heights = card.evaluate("""(c) => [...c.querySelectorAll(':scope > [data-m=verdicts] button')]
                  .map(b => b.getBoundingClientRect().height)""")
                assert rows == 1, 'the four choices wrap at %d px' % width
                assert min(heights) >= 44, 'tap floor at %d px: %r' % (width, heights)
                assert card.evaluate('c => c.scrollWidth <= c.clientWidth + 1'), 'a card overflows at %d px' % width
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            print('phone %d: receipt folded, compact cards, choices in one row' % width, flush=True)
            page.close()
    finally:
        browser.close()
print('OK')
