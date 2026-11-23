#!/usr/bin/env python3
"""The book brew tab in Settings has a "Retake the survey" button.

The accepted interests plan (THS-37, kept by THS-70) says the tab can retake
the survey, opening it filled in. The survey could open on purpose
(window.SHELF_SURVEY.open) but nothing called it. This test presses the button
on a saved shelf and checks the survey opens with her answers, that she can
leave without saving, and that a survey saved from the tab shows on the tab.

Run: python3 tests/settings_retake.py http://127.0.0.1:8811 [evidence-dir]
Serve a made-up shelf (see verify-the-shelf). The test never saves anything:
it answers /api/interests itself, keeping the file in memory, so it runs on
any served build. Requires Python Playwright and Chromium; set CHROME_PATH
when Playwright's own Chromium is not installed. With an evidence dir, it
also writes pictures of the tab and the opened survey.
"""
import copy
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
evidence = sys.argv[2] if len(sys.argv) > 2 else None

FILE = {'name': 'The book brew', 'picks': 12, 'never': [], 'season_goal': 6,
        'surveyed': '2026-11-01', 'need_survey': False, 'split': [],
        'catalog': [{'id': 'baby', 'label': 'Baby development', 'kind': 'topic'},
                    {'id': 'sport', 'label': 'Sport romance', 'kind': 'story'}],
        'interests': [
            {'id': 'baby', 'label': 'Baby development', 'kind': 'topic', 'dial': 'into it', 'mode': 'both', 'romance': False, 'reading': []},
            {'id': 'sport', 'label': 'Sport romance', 'kind': 'story', 'dial': 'obsessed', 'mode': 'new', 'romance': True, 'reading': []},
        ]}
state = copy.deepcopy(FILE)
posts = []


def interests(route):
    if route.request.method == 'POST':
        posts.append(route.request.post_data_json)
        state.update({k: v for k, v in route.request.post_data_json.items() if k != 'season_goal'})
    route.fulfill(json=state)


def survey_is_open(page):
    return page.evaluate("() => !!document.getElementById('shelf-survey')")


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
        page.wait_for_timeout(400)
        assert not survey_is_open(page), 'a saved shelf opened the survey on its own'

        # 1. The button is on the tab, under the meter and above the interests.
        button = page.get_by_role('button', name='Retake the survey')
        assert button.is_visible(), 'the book brew tab has no "Retake the survey" button'
        box = button.bounding_box()
        meter = page.locator('#bm-meter .meter').bounding_box()
        first_card = page.locator('#bm-interests > div').first.bounding_box()
        assert meter['y'] + meter['height'] <= box['y'] < first_card['y'], (meter, box, first_card)
        assert box['height'] >= 44, f'the button is too small to tap: {box}'
        print('PASS the tab shows "Retake the survey", under the meter', flush=True)
        if evidence:
            page.screenshot(path=os.path.join(evidence, 'retake-tab-1280.png'))

        # 2. Pressing it opens the survey, filled in with her saved answers.
        button.click()
        page.wait_for_selector('#shelf-survey')
        page.get_by_role('button', name='Baby development').wait_for()
        pressed = page.evaluate("() => [...document.querySelectorAll('#shelf-survey .tile[aria-pressed=true]')].map(t => t.textContent.trim())")
        assert any('Baby development' in t for t in pressed) and any('Sport romance' in t for t in pressed), pressed
        print('PASS the button opens the survey with her interests picked:', pressed, flush=True)
        if evidence:
            page.screenshot(path=os.path.join(evidence, 'retake-survey-1280.png'))

        # 3. She can leave without saving: the survey closes and nothing is sent.
        page.get_by_role('button', name='Leave without saving').click()
        assert not survey_is_open(page), 'leave without saving did not close the survey'
        assert not posts, f'leaving sent a save: {posts}'
        assert page.evaluate("() => document.body.style.overflow !== 'hidden'"), 'the page stayed locked'
        print('PASS leave without saving closes it and saves nothing', flush=True)

        # 4. Pressing it again re-reads the file: a change made on the tab shows in the survey.
        page.locator('#bm-card-baby button[data-act=dial][data-v=off]').click()
        page.wait_for_function("() => document.querySelector('#bm-msg').textContent.startsWith('saved')")
        posts.clear()
        button.click()
        page.wait_for_selector('#shelf-survey')
        page.get_by_role('button', name='Next').click()
        dial = page.evaluate("""() => {
          const card = [...document.querySelectorAll('#shelf-survey .card')].find(c => c.textContent.includes('Baby development'));
          return card ? card.querySelector('.seg button[aria-pressed=true]').textContent.trim() : null;
        }""")
        assert dial == 'off', f'the survey did not read the dial changed on the tab: {dial}'
        print('PASS the survey shows the dial she just changed on the tab', flush=True)

        # 5. Saving from the survey updates the tab, and the next tab change keeps it.
        page.locator('#shelf-survey .card', has_text='Baby development').get_by_role('button', name='obsessed').click()
        for _ in range(3):
            page.get_by_role('button', name='Next').click()
        page.get_by_role('button', name='Save to my shelf').click()
        page.wait_for_function("() => !document.getElementById('shelf-survey')")
        assert posts, 'saving the survey sent nothing'
        page.wait_for_function("() => getComputedStyle(document.querySelector('#bm-card-baby button[data-v=obsessed]')).backgroundColor === 'rgb(30, 58, 47)'")
        print('PASS saving closes the survey and the tab re-reads the file', flush=True)

        # 6. First-run survey on a new shelf has no way to leave: it must be answered.
        new_shelf = copy.deepcopy(FILE)
        new_shelf.update({'need_survey': True, 'surveyed': None})
        page.unroute('**/api/interests')
        page.route('**/api/interests', lambda route: route.fulfill(json=new_shelf))
        page.goto(url, wait_until='networkidle')
        page.wait_for_selector('#shelf-survey')
        assert page.get_by_role('button', name='Leave without saving').count() == 0, 'a first-run survey can be left'
        print('PASS a new shelf cannot leave its first survey', flush=True)
        page.close()
    finally:
        browser.close()
