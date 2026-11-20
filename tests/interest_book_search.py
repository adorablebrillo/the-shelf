#!/usr/bin/env python3
"""THS-69: Search in a Book-a-meter interest shows the books it found.

A pressed Search used to fetch the books and then draw them nowhere: the
completion handed the interest's id to a renderer that wants the interest.

Run: python3 tests/interest_book_search.py http://127.0.0.1:8811
Serve a made-up shelf (see verify-the-shelf), never the reader's own: the
test saves one topic interest through the server's /api/interests. It
answers /api/search with a real Apple Books reply
(tests/fixtures/search-whole-brain-child.json), so it needs no network. Requires Python Playwright and Chromium; set CHROME_PATH when
Playwright's own Chromium is not installed.
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url = sys.argv[1]
reply = json.loads((Path(__file__).parent / 'fixtures' / 'search-whole-brain-child.json').read_text())
first = reply['results'][0]['title']
interests = {'name': 'Book-a-meter', 'picks': 12, 'never': [], 'season_goal': None,
             'surveyed': '2026-11-01',
             'interests': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                            'dial': 'into it', 'mode': 'both', 'romance': False, 'reading': []}]}


with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        for submit in ('the Search button', 'the Enter key'):
            page = browser.new_page(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
            saved = page.request.post(url + '/api/interests', data=interests)
            assert saved.ok, f'could not save the test interest: {saved.status}'
            page.route('**/api/search?*', lambda route: route.fulfill(json=reply))
            page.goto(url, wait_until='networkidle')
            # The first-run survey opens on every load (a separate defect) and
            # has no close button; take it off so Settings can be reached.
            page.evaluate("() => { const s = document.getElementById('shelf-survey');"
                          " if (s) { s.remove(); document.body.style.overflow = ''; } }")
            page.get_by_role('button', name='Settings', exact=True).first.click()
            page.get_by_role('tab', name='Book-a-meter').click()
            card = page.locator('#bm-card-baby')
            card.get_by_role('button', name='+ add a book').click()
            box = card.get_by_role('searchbox')
            box.fill('the whole brain child')
            if submit == 'the Search button':
                card.get_by_role('button', name='search', exact=True).click()
            else:
                box.press('Enter')
            found = card.get_by_text(first, exact=True)
            try:
                found.wait_for(timeout=3000)
            except Exception:
                raise AssertionError(f'Search by {submit} showed no results in the interest card')
            print(f'PASS {submit}: "{first}" shows in the Baby development card', flush=True)
            page.close()
    finally:
        browser.close()
