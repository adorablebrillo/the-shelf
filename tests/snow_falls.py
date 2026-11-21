#!/usr/bin/env python3
"""Falling snow runs through the winter, never under reduced motion, and stops
by itself when spring starts. Home has no snow controls.

Intent (the reader's request): snow always falls in winter, with no settings;
it goes away by itself when the next season starts; reduced motion still gets
no snow.
Run: python3 tests/snow_falls.py http://127.0.0.1:8811
Needs the made-up Shelf served (the verify-the-shelf skill), Python Playwright
and a local Chromium (set CHROME_PATH when Playwright's own is not installed).
"""
import os
import sys
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

url = sys.argv[1]

# Pixels the falling-snow canvas has painted. Zero when it is hidden or cleared.
LIT = """() => {
  const c = document.getElementById('christmas-fall');
  if (!c || getComputedStyle(c).display === 'none' || !c.width) return 0;
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
  return n;
}"""

# The snow controls the reader asked to remove. None may exist on Home.
REMOVED = ['Effects on', 'Effects off', 'Pause snow', 'Resume snow', 'Brush mode',
           'Sweep a path', 'Call the plough', 'Clear snow', 'Undo']

CHRISTMAS = datetime(2026, 12, 10, 12)
WINTER = datetime(2027, 2, 10, 12)
LAST_WINTER_DAY = datetime(2027, 2, 28, 12)
SPRING = datetime(2027, 3, 2, 12)


def open_home(browser, when, width=1280, reduced=False):
    page = browser.new_page(viewport={'width': width, 'height': 900},
                            reduced_motion='reduce' if reduced else 'no-preference')
    page.clock.set_fixed_time(when)
    page.goto(url, wait_until='networkidle')
    page.wait_for_timeout(1500)
    return page


def snow_lit(page):
    return page.evaluate(LIT)


with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        for width in (1280, 390):
            page = open_home(browser, CHRISTMAS, width)
            assert snow_lit(page) > 0, f'no snow fell at Christmas, width {width}'
            assert page.locator('#christmas-play').count() == 0, 'the snow panel is still on Home'
            for label in REMOVED:
                count = page.get_by_role('button', name=label, exact=True).count()
                assert count == 0, f'snow control still on Home: {label} ({width})'
            page.close()
            print(f'christmas: snow falls, no snow controls, width {width}', flush=True)

        page = open_home(browser, WINTER)
        assert snow_lit(page) > 0, 'no snow fell in winter'
        page.close()
        print('winter: snow falls', flush=True)

        page = open_home(browser, LAST_WINTER_DAY)
        assert snow_lit(page) > 0, 'no snow fell on the last winter day'
        # The page re-reads the season on its own render; wait for spring to clear the snow.
        page.clock.set_fixed_time(SPRING)
        deadline = time.time() + 20
        lit = snow_lit(page)
        while lit and time.time() < deadline:
            page.wait_for_timeout(500)
            lit = snow_lit(page)
        assert lit == 0, 'snow kept falling after spring started'
        page.close()
        print('spring: snow stopped by itself', flush=True)

        page = open_home(browser, CHRISTMAS, reduced=True)
        page.wait_for_timeout(1000)
        assert snow_lit(page) == 0, 'snow fell under reduced motion'
        page.close()
        print('reduced motion: no snow falls', flush=True)
    finally:
        browser.close()
