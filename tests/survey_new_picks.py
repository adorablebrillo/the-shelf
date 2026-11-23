#!/usr/bin/env python3
"""Saving the survey starts new picks right away.

The reader's choice for the fix to "I was never recommended my other
interests": the survey's save asks the server to start a curate-now run, and
the toast she sees says what happened to it (brewing, no key yet, or a brew
already under way). Before, the save only wrote the file and the toast said
"the next run follows it", so Home kept the old issue until the 1st.

Run: python3 tests/survey_new_picks.py http://127.0.0.1:8811 [evidence-dir]
Serve a made-up shelf (see verify-the-shelf). The test answers /api/interests
itself, so it saves nothing and starts no run on the served build. Requires
Python Playwright and Chromium; set CHROME_PATH when Playwright's own Chromium
is not installed.
"""
import copy
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
evidence = sys.argv[2] if len(sys.argv) > 2 else None

FILE = {'name': 'The book brew', 'picks': 12, 'never': [], 'season_goal': 6,
        'surveyed': '2026-11-01', 'need_survey': False, 'split': [],
        'catalog': [{'id': 'thriller', 'label': 'Thriller', 'kind': 'story'},
                    {'id': 'romantasy', 'label': 'Romantasy', 'kind': 'story'}],
        'interests': [
            {'id': 'romantasy', 'label': 'Romantasy', 'kind': 'story', 'dial': 'into it', 'mode': 'new', 'romance': True, 'reading': []},
            {'id': 'thriller', 'label': 'Thriller', 'kind': 'story', 'dial': 'into it', 'mode': 'new', 'romance': False, 'reading': []},
        ]}
posts = []
run_answer = {'run': 'started'}


def interests(route):
    if route.request.method == 'POST':
        posts.append(route.request.post_data_json)
        route.fulfill(json={**copy.deepcopy(FILE), **run_answer})
    else:
        route.fulfill(json=copy.deepcopy(FILE))


def save_from_survey(page):
    page.get_by_role('button', name='Retake the survey').click()
    page.wait_for_selector('#shelf-survey')
    for _ in range(4):
        page.get_by_role('button', name='Next').click()
    page.get_by_role('button', name='Save to my shelf').click()
    page.wait_for_function("() => !document.getElementById('shelf-survey')")
    return page.evaluate("() => document.getElementById('shelf-toast').textContent")


with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
        page.route('**/api/interests', interests)
        page.goto(url, wait_until='networkidle')
        page.get_by_role('button', name='Settings').first.click()
        page.locator('#tab-bookameter').click()
        page.wait_for_selector('#bm-meter .meter')

        for answer, words in (('started', 'new picks are brewing now'),
                              ('busy', 'a brew is already under way'),
                              ('no-key', 'add your OpenRouter key')):
            run_answer['run'] = answer
            posts.clear()
            toast = save_from_survey(page)
            assert len(posts) == 1 and posts[0].get('start_run') is True, f'the save did not ask for new picks: {posts}'
            assert words in toast, f'run {answer}: the toast says {toast!r}'
            if evidence and answer == 'started':
                page.screenshot(path=os.path.join(evidence, 'survey-saved-brewing-1280.png'))
            page.evaluate("() => document.getElementById('shelf-toast').remove()")
            print(f'PASS run {answer}: the save asked for new picks, the toast says "{toast}"', flush=True)
        page.close()
    finally:
        browser.close()
