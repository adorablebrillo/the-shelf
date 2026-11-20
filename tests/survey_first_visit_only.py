#!/usr/bin/env python3
"""The book brew survey opens only when the server says it is needed.

Her report: every time she opened the website, the first-run survey came
back, though her choices were saved. The server was right (GET /api/interests
answers need_survey false once a surveyed day is saved). The page ignored it:
its start-up ran start(event) from DOMContentLoaded, and the event counted as
the "open it on purpose" flag.

Run: python3 tests/survey_first_visit_only.py http://127.0.0.1:8811
Serve a made-up shelf (see verify-the-shelf). The test never saves anything:
it answers GET /api/interests itself, once as a saved shelf (need_survey
false) and once as a new one (need_survey true), so it runs on any served
build. Requires Python Playwright and Chromium; set CHROME_PATH when
Playwright's own Chromium is not installed.
"""
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]


def interests(need_survey):
    return {'name': 'The book brew', 'picks': 12, 'never': [], 'season_goal': None,
            'surveyed': None if need_survey else '2026-11-01', 'need_survey': need_survey,
            'interests': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic',
                           'dial': 'into it', 'mode': 'both', 'romance': False, 'reading': []}],
            'catalog': [], 'split': []}


def survey_is_open(page):
    return page.evaluate("() => !!document.getElementById('shelf-survey')")


with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')

        # 1. A saved shelf: opening the page (and reloading it) shows no survey.
        page.route('**/api/interests', lambda route: route.fulfill(json=interests(False)))
        for visit in ('first load', 'reload'):
            page.goto(url, wait_until='networkidle')
            page.wait_for_timeout(500)
            assert not survey_is_open(page), f'saved shelf: the survey opened on the {visit}'
            print(f'PASS saved shelf, {visit}: no survey', flush=True)

        # 2. Settings opens it on purpose, even on a saved shelf.
        page.evaluate('() => window.SHELF_SURVEY.open()')
        page.get_by_text('The book brew', exact=False).first.wait_for()
        assert survey_is_open(page), 'SHELF_SURVEY.open() did not open the survey on a saved shelf'
        print('PASS saved shelf, opened on purpose: survey shows', flush=True)

        # 3. A new shelf: the server asks for the survey and it opens.
        page.unroute('**/api/interests')
        page.route('**/api/interests', lambda route: route.fulfill(json=interests(True)))
        page.goto(url, wait_until='networkidle')
        page.wait_for_timeout(500)
        assert survey_is_open(page), 'new shelf: the survey did not open on the first visit'
        print('PASS new shelf: survey opens', flush=True)
        page.close()
    finally:
        browser.close()
