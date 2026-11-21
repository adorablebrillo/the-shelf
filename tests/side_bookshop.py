#!/usr/bin/env python3
"""The bookshop drawing in the side panel shows on every laptop window.

The side-panel bookshop was merged (THS-92) but a rule hid it in any window
860 pixels tall or less, which covers most laptop windows. This test opens the
page at laptop sizes and checks that the drawing is on screen, sits between
the nav and the panel footer, and that the footer stays above the fold. It
also checks the phone layout, where the side panel is a header and the drawing
stays hidden.

Run: python3 tests/side_bookshop.py http://127.0.0.1:8811
Serve a made-up shelf (see verify-the-shelf). Requires Python Playwright and
Chromium; set CHROME_PATH when Playwright's own Chromium is not installed.
"""
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]

# Windows 701 px tall or more draw the shop; each size is a common laptop window.
LAPTOPS = [(1280, 800), (1512, 860), (1440, 790), (1280, 720), (1512, 900)]

READ = """() => {
  const box = s => { const e = document.querySelector(s).getBoundingClientRect();
    return {top: e.top, bottom: e.bottom, width: e.width, height: e.height}; };
  const img = document.querySelector('[data-m="shop-art"]');
  return {shown: getComputedStyle(img).display !== 'none', loaded: img.complete && img.naturalWidth > 0,
          shop: box('[data-m="shop-art"]'), nav: box('[data-m="sidenav"]'),
          footer: box('[data-m="sidepanel"] > :last-child'), vh: innerHeight};
}"""

with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        for w, h in LAPTOPS:
            page = browser.new_page(viewport={'width': w, 'height': h}, reduced_motion='reduce')
            page.goto(url, wait_until='networkidle')
            g = page.evaluate(READ)
            tag = f'{w}x{h}'
            assert g['shown'] and g['loaded'], f'{tag}: the bookshop is hidden or did not load: {g}'
            assert g['shop']['height'] >= 50 and g['shop']['width'] >= 100, f'{tag}: the bookshop is too small to see: {g}'
            assert g['nav']['bottom'] <= g['shop']['top'], f'{tag}: the bookshop overlaps the nav: {g}'
            assert g['shop']['bottom'] <= g['footer']['top'], f'{tag}: the bookshop overlaps the footer: {g}'
            assert g['footer']['bottom'] <= g['vh'], f'{tag}: the panel footer is below the fold: {g}'
            print(f'ok {tag}: shop {g["shop"]["width"]:.0f}x{g["shop"]["height"]:.0f}')
            page.close()

        page = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
        page.goto(url, wait_until='networkidle')
        g = page.evaluate(READ)
        assert not g['shown'], f'the bookshop shows on the phone layout: {g}'
        print('ok 390x844: hidden')
    finally:
        browser.close()
