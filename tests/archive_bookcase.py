#!/usr/bin/env python3
"""THS-105: the Archive (named Finished Brews) as bookcases.

Intent — the captain's approved Archive design: a count line and three filters
(Read & loved, Loved only, Not for me); one bookcase per season, newest first,
the plate naming the season and year from build.py's SEASONS; 3 books a shelf
on a phone and 6 on a laptop; real books face-out with a house edition cover
where there is no art; a "loved it" tag on loved books; the "series complete"
plate on the book that finished a series; decoration the reader cannot press;
a book card that opens on a tap and is the one place a mark changes; the
stacks and click-to-unread spines gone; the page named Finished Brews.

Drives the made-up shelf served by verify-the-shelf. It writes marks into the
served shelf's `reader-state.json`, so run it against a scratch volume only,
seeded with `seed-demo.py <cfg> <root>` before launch (a fresh volume: the
book counts below are the seed's).

Run: python3 tests/archive_bookcase.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline'))
os.environ.setdefault('CFG_DIR', '/nonexistent-cfg')
import build  # noqa: E402  the one season table (SEASONS)

URL = sys.argv[1].rstrip('/')
API = URL + '/api/state'
NOW = datetime.datetime.now()
DAY_MS = 86400000

# made-up books of the verify skill's shelf: id -> title as the page prints it
THIS = [('slipstream--nadiakerr', 'Slipstream', 'read'),
        ('lastcallatrosies--hannahbell', "Last Call at Rosie's", 'loved'),
        ('thewinterguest--irisvale', 'The Winter Guest', 'read'),
        ('thepenaltybox--rubycalder', 'The Penalty Box', 'read'),
        ('queenofthornsanddusk--selenemarr', 'Queen of Thorns and Dusk', 'read'),
        ('faceoffatmidnight--domenicpace', 'Faceoff at Midnight', 'read'),
        ('wildfireseason--adaquill', 'Wildfire Season', 'read')]
HARBOR = [('theharborletters--junemarlowe', 250), ('thesaltroad--junemarlowe', 120),
          ('thelastferry--junemarlowe', 3)]   # the last one finishes the series
SENT_BACK = 'bluelinebillionaire--sawyerkent'


def post(payload):
    req = urllib.request.Request(API, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def mark_of(book_id):
    return (json.loads(urllib.request.urlopen(API, timeout=15).read().decode())['states'].get(book_id) or {}).get('s')


def plate_for(days_ago):
    """The plate build.py's table gives a day: the season's drink label and the
    year the season started in (Christmas in January belongs to the year before)."""
    d = NOW - datetime.timedelta(days=days_ago)
    md = '%02d-%02d' % (d.month, d.day)
    s = [x for x in build.SEASONS if x['key'] == build.season_of(d.month, d.day)][0]
    year = d.year - 1 if (s['start'] > s['end'] and md <= s['end']) else d.year
    return ('%s %d' % (s['drink']['label'], year)).upper()


BAKED = 5   # the made-up library lists five volumes as read, with no dated mark of hers


def seed():
    """Her marks, dated now: this season's books a minute apart, the Harbor
    Letters in two older seasons, one book sent back. Fresh dates every call,
    so they win over a mark a previous check cleared."""
    now_ms = int(time.time() * 1000)
    states = {i: {'s': v, 't': now_ms - k * 60000} for k, (i, _, v) in enumerate(THIS)}
    for i, ago in HARBOR:
        states[i] = {'s': 'read', 't': now_ms - ago * DAY_MS}
    states[SENT_BACK] = {'s': 'skip', 't': now_ms - 2 * DAY_MS}
    post({'states': states})


with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    for width, height, per_shelf in ((1280, 900, 6), (390, 844, 3)):
        seed()
        page = browser.new_page(viewport={'width': width, 'height': height})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(URL)
        page.locator('nav[aria-label="Sections"]').filter(visible=True).first.wait_for()
        page.locator('nav[aria-label="Sections"] button', has_text='Finished Brews').filter(visible=True).first.click()
        page.wait_for_selector('[data-m="arccount"]')

        # the page is named Finished Brews; the tabs and the stacks are gone
        assert page.locator('h2', has_text='Finished Brews').count() == 1, 'page heading'
        assert page.locator('[role="tablist"]').filter(visible=True).count() == 0, 'no tabs on the Archive'
        assert 'The stacks' not in page.inner_text('main'), 'the stacks are removed'

        # count line and three filters, 44 px tall, reachable by Tab from + add a book
        n_read = len(THIS) + len(HARBOR) + BAKED
        n_loved = sum(1 for _, _, v in THIS if v == 'loved')
        count = page.inner_text('[data-m="arccount"]')
        assert re.match(r'^\d+ books read · \d+ loved · \d+ not for me$', count), count
        assert count.startswith('%d books read · %d loved' % (n_read, n_loved)), count
        names = page.locator('[data-m="arcfilters"] button').all_inner_texts()
        assert [re.sub(r' · \d+$', '', n).lower() for n in names] == ['read & loved', 'loved only', 'not for me'], names
        heights = page.evaluate("() => Array.from(document.querySelectorAll('[data-m=arcfilters] button')).map(b => b.getBoundingClientRect().height)")
        assert all(h >= 44 for h in heights), heights
        page.get_by_role('button', name='+ add a book').focus()
        page.keyboard.press('Tab')
        assert page.evaluate("() => document.activeElement.closest('[data-m=arcfilters]') !== null"), 'Tab reaches the filters'

        # one bookcase per season, newest first; the plate is the season and the year
        plates = page.evaluate("() => Array.from(document.querySelectorAll('.arc-plate')).map(x => x.textContent.toUpperCase())")
        expected = []
        for ago in (0, 3, 120, 250):   # the days the marks above are dated
            if plate_for(ago) not in expected:
                expected.append(plate_for(ago))
        assert plates[:len(expected)] == expected, (plates, expected)
        assert page.locator('text=/\\d+ books this season/').count() >= 1, 'books this season line'

        # shelves hold 3 books on a phone and 6 on a laptop; this season holds more than one shelf
        rows = page.evaluate("() => Array.from(document.querySelector('.arc-case').querySelectorAll('.arc-row')).map(r => r.querySelectorAll('.arc-cover').length)")
        first_case = len(THIS) + (1 if plate_for(3) == plate_for(0) else 0)   # the Last Ferry, if marked in this season
        assert rows[0] == per_shelf and sum(rows) == first_case, rows
        assert page.locator('.arc-case').first.locator('.arc-candle').count() == len(rows), 'one candle a shelf'

        # decoration cannot be pressed; real books stand face-out and open a card
        assert page.evaluate("() => Array.from(document.querySelectorAll('.arc-deco')).every(d => d.getAttribute('aria-hidden') === 'true' && !d.querySelector('button, a, [tabindex]'))")
        assert page.evaluate("() => document.querySelectorAll('.arc-deco .arc-sp').length > 0")
        # no art on this shelf: the house edition shows the title and the author
        house = page.locator('[data-arc-book="slipstream--nadiakerr"] .arc-house')
        assert 'Slipstream' in house.inner_text() and 'NADIA KERR' in house.inner_text().upper(), 'house edition'
        # a loved book carries its tag; the book that finished the series carries the plate
        assert page.locator('[data-arc-book="lastcallatrosies--hannahbell"] .arc-tag').count() == 1, 'loved tag'
        assert page.locator('[data-arc-book="slipstream--nadiakerr"] .arc-tag').count() == 0, 'no tag on a read book'
        assert page.locator('.arc-done').count() == 1, 'one series complete plate'
        assert page.locator('[data-arc-book="thelastferry--junemarlowe"] .arc-done').count() == 1, 'plate on the last read'

        # the book card: opens on a tap, focus on Close, Escape shuts it, focus returns to the book
        book = page.locator('[data-arc-book="thelastferry--junemarlowe"]')
        book.scroll_into_view_if_needed()
        book.click()
        dialog = page.locator('[role="dialog"]')
        dialog.wait_for()
        page.wait_for_function("() => document.activeElement && document.activeElement.id === 'arc-card-close'", timeout=3000)
        text = dialog.inner_text()
        for want in ('The Last Ferry', 'June Marlowe', 'The Harbor Letters · book 3 of 3 · series complete', 'Read on', 'goodreads'):
            assert want.lower() in text.lower(), (want, text)
        assert dialog.locator('[data-m="verdicts"] button').count() == 5, 'the verdict row'
        page.keyboard.press('Escape')
        assert dialog.count() == 0, 'Escape shuts the card'
        page.wait_for_function("() => document.activeElement.getAttribute('data-arc-book') === 'thelastferry--junemarlowe'", timeout=3000)   # focus returns on the next tick
        assert page.evaluate("() => document.activeElement.getAttribute('data-arc-book')") == 'thelastferry--junemarlowe'
        book.click()
        page.get_by_role('button', name='Close').click()
        page.wait_for_function("() => document.activeElement.getAttribute('data-arc-book') === 'thelastferry--junemarlowe'", timeout=3000)
        assert dialog.count() == 0 and page.evaluate("() => document.activeElement.getAttribute('data-arc-book')") == 'thelastferry--junemarlowe'

        # a verdict round trip from the card: loved -> not for me -> on the returns cart -> put back
        sid = 'slipstream--nadiakerr'
        page.locator('[data-arc-book="%s"]' % sid).click()
        page.get_by_role('button', name='loved Slipstream').click()
        page.wait_for_timeout(600)
        assert mark_of(sid) == 'loved' and dialog.count() == 1, 'loved from the card keeps the card open'
        page.get_by_role('button', name='not for me — Slipstream').click()
        page.wait_for_timeout(600)
        assert mark_of(sid) == 'skip', 'not for me from the card'
        assert page.inner_text('[data-m="arccount"]').endswith('2 not for me'), page.inner_text('[data-m="arccount"]')
        page.get_by_role('button', name='Close').click()
        page.get_by_role('button', name=re.compile('^Not for me')).click()
        assert page.locator('h3', has_text='The returns cart').count() == 1
        assert 'press not for me again to put it back' in page.inner_text('main')
        assert page.evaluate("() => Array.from(document.querySelectorAll('.arc-plate')).map(x => x.textContent)") == ['Not for me']
        page.locator('[data-arc-book="%s"]' % sid).click()
        page.get_by_role('button', name=re.compile('^not for me — Slipstream')).click()   # again: put back
        page.wait_for_timeout(600)
        assert mark_of(sid) is None, 'pressing not for me again puts the book back'
        assert dialog.count() == 0 and 'left Finished Brews' in page.inner_text('#arc-gone')

        # Loved only: one House favourites bookcase
        page.get_by_role('button', name=re.compile('^Loved only')).click()
        assert page.evaluate("() => Array.from(document.querySelectorAll('.arc-plate')).map(x => x.textContent)") == ['House favourites']
        assert page.locator('.arc-cover').count() == n_loved, 'only the loved books'
        assert not errors, errors
        print('archive bookcase at %d px: ok' % width)
        page.close()
    browser.close()
