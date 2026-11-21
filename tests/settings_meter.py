#!/usr/bin/env python3
"""The book brew tab in Settings shows the meter, the same one the survey ends on.

The accepted interests plan (THS-37) put a 280-pixel meter under the intro
sentence of the Settings tab. The tab shipped without it, so the meter showed
only in the survey's last step. This test opens the tab and checks that the
meter is there, redraws with every dial change, and is the very drawing the
survey shows for the same interests.

Run: python3 tests/settings_meter.py http://127.0.0.1:8811 [evidence-dir]
Serve a made-up shelf (see verify-the-shelf). The test never saves anything:
it answers /api/interests itself, keeping the file in memory, so it runs on
any served build. Requires Python Playwright and Chromium; set CHROME_PATH
when Playwright's own Chromium is not installed. With an evidence dir, it
also writes two pictures of the tab.
"""
import copy
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
evidence = sys.argv[2] if len(sys.argv) > 2 else None

FILE = {'name': 'The book brew', 'picks': 12, 'never': [], 'season_goal': 6,
        'surveyed': '2026-11-01', 'need_survey': False, 'catalog': [], 'split': [],
        'interests': [
            {'id': 'baby', 'label': 'Baby development', 'kind': 'topic', 'dial': 'into it', 'mode': 'both', 'romance': False, 'reading': []},
            {'id': 'sport', 'label': 'Sport romance', 'kind': 'story', 'dial': 'obsessed', 'mode': 'new', 'romance': True, 'reading': []},
            {'id': 'mystery', 'label': 'Mystery', 'kind': 'story', 'dial': 'curious', 'mode': 'new', 'romance': False, 'reading': []},
        ]}
state = copy.deepcopy(FILE)


def interests(route):
    if route.request.method == 'POST':
        state.update({k: v for k, v in route.request.post_data_json.items() if k != 'season_goal'})
    route.fulfill(json=state)


GAUGE = """() => {
  const m = document.querySelector('#panel-bookameter #bm-meter .meter');
  if (!m) return null;
  const svg = m.querySelector('svg');
  return {label: svg.getAttribute('aria-label'), caption: m.querySelector('p').textContent,
          arcs: svg.querySelectorAll('path').length, width: svg.getBoundingClientRect().width,
          visible: m.getBoundingClientRect().height > 0,
          y: m.getBoundingClientRect().top,
          introY: document.getElementById('bm-intro').getBoundingClientRect().top,
          firstCardY: document.querySelector('#bm-interests > div').getBoundingClientRect().top};
}"""

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

        # 1. The meter is on the tab: under the intro sentence, above the first interest.
        g = page.evaluate(GAUGE)
        assert g and g['visible'], 'the book brew tab has no meter'
        assert g['introY'] < g['y'] < g['firstCardY'], f'the meter is not between the intro and the interests: {g}'
        assert g['arcs'] == 3, f'expected one arc for each of the 3 interests: {g}'
        assert g['label'] == 'The meter: Sport romance' and 'Sport romance' in g['caption'], g
        assert 270 <= g['width'] <= 280, f'the preview draws it 280 px wide: {g}'
        print('PASS the tab shows the meter, 280 px, mostly Sport romance', flush=True)
        if evidence:
            page.screenshot(path=os.path.join(evidence, 'settings-meter-1280.png'))

        # 2. A dial change redraws it: turn Sport romance off and Baby development up.
        page.locator('#bm-card-sport button[data-act=dial][data-v=off]').click()
        page.wait_for_function("() => document.querySelector('#bm-meter svg').getAttribute('aria-label') !== 'The meter: Sport romance'")
        page.locator('#bm-card-baby button[data-act=dial][data-v=obsessed]').click()
        page.wait_for_function("() => document.querySelector('#bm-meter svg').getAttribute('aria-label') === 'The meter: Baby development'")
        g = page.evaluate(GAUGE)
        assert g['arcs'] == 2, f'two interests are on: {g}'
        print('PASS a dial change redraws the meter', flush=True)

        # 3. Every interest off: the empty meter, with its prompt.
        for i in ('baby', 'mystery'):
            page.locator(f'#bm-card-{i} button[data-act=dial][data-v=off]').click()
        page.wait_for_function("() => document.querySelector('#bm-meter svg').getAttribute('aria-label') === 'The meter: no interest is on'")
        assert 'turn a dial up' in page.evaluate(GAUGE)['caption']
        print('PASS all dials off: the empty meter asks for a dial', flush=True)

        # 4. The survey draws the same gauge for the same interests.
        for i, d in (('baby', 'into it'), ('sport', 'obsessed'), ('mystery', 'curious')):
            page.locator(f'#bm-card-{i} button[data-act=dial][data-v="{d}"]').click()
        page.wait_for_function("() => document.querySelector('#bm-meter svg').getAttribute('aria-label') === 'The meter: Sport romance'")
        tab_paths = page.evaluate("() => [...document.querySelectorAll('#bm-meter svg path')].map(p => p.getAttribute('stroke'))")
        page.evaluate('() => window.SHELF_SURVEY.open()')
        page.wait_for_selector('#shelf-survey')
        for _ in range(4):
            page.get_by_role('button', name='Next').click()
        page.wait_for_selector('#shelf-survey .meter svg')
        survey_paths = page.evaluate("() => [...document.querySelectorAll('#shelf-survey .meter svg path')].map(p => p.getAttribute('stroke'))")
        assert tab_paths == survey_paths, f'tab {tab_paths} vs survey {survey_paths}'
        print('PASS the survey draws the same arcs for the same interests', flush=True)
        if evidence:
            page.screenshot(path=os.path.join(evidence, 'survey-meter-1280.png'))
        page.evaluate("() => document.getElementById('shelf-survey').remove()")

        # 5. A phone window: no sideways scroll, the meter fits.
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        g = page.evaluate(GAUGE)
        assert g['width'] <= 390 - 32, f'the meter overflows a phone: {g}'
        assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'), 'sideways scroll at 390 px'
        print('PASS 390 px: the meter fits, no sideways scroll', flush=True)
        if evidence:
            page.screenshot(path=os.path.join(evidence, 'settings-meter-390.png'))
    finally:
        browser.close()
