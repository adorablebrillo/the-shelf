#!/usr/bin/env python3
"""THS-51: drive the made-up shelf served by verify-the-shelf.

Run: python3 tests/series_glance.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
# At Christmas the reading area scrolls instead of the window, so the card
# aligns with its top and the refresh check reads its scroll position.
AREA = "(() => { const m = document.querySelector('[data-m=\"main\"]'); return m && getComputedStyle(m).overflowY === 'auto' ? m : null; })()"
with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        for width, height, name in [(1280, 900, 'Match Point Hearts'),
                                    (390, 844, 'Gilded Thorns Court')]:
            page = browser.new_page(viewport={'width': width, 'height': height}, reduced_motion='reduce')
            page.goto(url, wait_until='networkidle')
            page.get_by_role('region', name='Series at a glance').get_by_role('button', name=name).click()
            target = page.locator('[data-m="scard"]').filter(has=page.get_by_text(name, exact=True))
            target.wait_for()
            page.wait_for_function("([name, area]) => { const card = [...document.querySelectorAll('[data-m=scard]')].find(e => e.textContent.includes(name)); return card && Math.abs(card.getBoundingClientRect().top - (eval(area) ? eval(area).getBoundingClientRect().top : 0)) < 2; }", arg=[name, AREA], timeout=3000)
            top = target.evaluate('(e, area) => e.getBoundingClientRect().top - (eval(area) ? eval(area).getBoundingClientRect().top : 0)', AREA)
            print(f'{width}: {name} top={top:.1f}', flush=True)
            assert abs(top) < 2, f'{name} did not reach the top: {top}'
            page.evaluate('area => { const a = eval(area); if (a) a.scrollTop = 0; else window.scrollTo(0, 0); }', AREA)
            page.wait_for_timeout(7000)
            assert page.evaluate('area => { const a = eval(area); return a ? a.scrollTop : window.scrollY; }', AREA) == 0, 'periodic refresh repeated the scroll'
            page.close()
    finally:
        browser.close()
