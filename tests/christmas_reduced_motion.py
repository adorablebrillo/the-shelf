#!/usr/bin/env python3
"""THS-61: with reduced motion the Christmas scene gives immediate results.

Run: python3 tests/christmas_reduced_motion.py http://127.0.0.1:8811
Needs the made-up Shelf at Christmas, Python Playwright and a local Chromium
(set CHROME_PATH when Playwright's own is not installed).
"""
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        page = browser.new_page(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce')
        page.goto(url, wait_until='networkidle')
        page.locator('#christmas-play').wait_for()
        page.locator('[data-slot="0"]').click()
        page.locator('[data-snow="plough"]').click()
        status = page.locator('#snow-status').text_content()
        assert 'ground is clear' in status, f'plough was not immediate: {status}'
        assert page.locator('[data-slot="0"]').text_content().startswith('Remove'), 'plough removed the tree'
        assert page.evaluate("document.getElementById('snow-plough').childElementCount") == 0, 'a vehicle was drawn'
        print('reduced motion: plough immediate, tree kept, no vehicle', flush=True)
    finally:
        browser.close()
