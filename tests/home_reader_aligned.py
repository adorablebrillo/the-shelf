#!/usr/bin/env python3
"""The reader drawing on Home sits where the man drawing sits on My Shelf.

Intent — the captain's ask: the drawings line up from page to page, so the
woman reading on Home moves to the man's place under My Shelf, and neither
drawing changes size. This test opens Home and My Shelf at the same window
size and compares the two drawings: the same top, the same right edge, the
drawings' own sizes kept, and no corner words (eyebrow, countdown, quote)
under the woman. On a phone the woman stays inside the corner card's border,
so her right edge may sit up to that border's distance short of the man's.

Run: python3 tests/home_reader_aligned.py http://127.0.0.1:8811
Serve a made-up shelf with at least one book marked want (see
verify-the-shelf), so My Shelf shows its man drawing. Requires Python
Playwright and Chromium; set CHROME_PATH when Playwright's own Chromium is not
installed.
"""
import os
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1].rstrip('/')

# Laptop and tablet windows, where both drawings are full size, and a phone.
WINDOWS = [(1440, 900), (1280, 800), (800, 900), (720, 900), (390, 844)]

BOX = """s => { const e = document.querySelector(s); if (!e) return null;
  const b = e.getBoundingClientRect();
  return {left: b.left, top: b.top + scrollY, right: b.right, bottom: b.bottom + scrollY,
          width: b.width, height: b.height}; }"""

# The rectangles of the words themselves, not their padded boxes.
WORDS = """() => ['eyebrow', 'countdown', 'cornerquote'].flatMap(k => {
  const e = document.querySelector('[data-m="' + k + '"]'); if (!e) return [];
  const r = document.createRange(); r.selectNodeContents(e);
  return [...r.getClientRects()].map(b => ({k, left: b.left, top: b.top + scrollY,
                                            right: b.right, bottom: b.bottom + scrollY})); })"""

CARD = """() => { const e = document.querySelector('[data-m="cornerin"]').getBoundingClientRect();
  return e.right - parseFloat(getComputedStyle(document.querySelector('[data-m="cornerin"]')).borderRightWidth); }"""


def open_section(page, label):
    page.get_by_role('button', name=label).first.click()
    page.wait_for_timeout(400)
    page.evaluate('scrollTo(0, 0)')


with sync_playwright() as p:
    options = {'headless': True}
    if os.environ.get('CHROME_PATH'):
        options['executable_path'] = os.environ['CHROME_PATH']
    browser = p.chromium.launch(**options)
    try:
        for w, h in WINDOWS:
            tag = f'{w}x{h}'
            page = browser.new_page(viewport={'width': w, 'height': h}, reduced_motion='reduce')
            page.goto(url, wait_until='networkidle')
            open_section(page, 'Home')
            woman = page.evaluate(BOX, '[data-m="woman-art"]')
            words = page.evaluate(WORDS)
            card_inner = page.evaluate(CARD)
            open_section(page, 'My Shelf')
            man = page.evaluate(BOX, '[data-m="populated-art"]')
            assert woman and man, f'{tag}: a drawing is missing: woman={woman} man={man}'

            phone = w <= 700
            size = (56, 48) if phone else (181, 155)
            assert (round(woman['width']), round(woman['height'])) == size, f'{tag}: the woman changed size: {woman}'

            assert abs(woman['top'] - man['top']) <= 1, f'{tag}: tops differ: woman {woman["top"]} man {man["top"]}'
            if phone:
                assert woman['right'] <= card_inner, f'{tag}: the woman crosses the corner border: {woman} / {card_inner}'
                assert man['right'] - woman['right'] <= 8, f'{tag}: right edges differ: woman {woman["right"]} man {man["right"]}'
            else:
                assert abs(woman['right'] - man['right']) <= 1, f'{tag}: right edges differ: woman {woman["right"]} man {man["right"]}'

            for r in words:
                clear = (r['right'] <= woman['left'] or r['left'] >= woman['right']
                         or r['bottom'] <= woman['top'] or r['top'] >= woman['bottom'])
                assert clear, f'{tag}: the woman covers the {r["k"]} words: {r} / {woman}'
            print(f'ok {tag}: woman top {woman["top"]:.0f} right {woman["right"]:.0f} · '
                  f'man top {man["top"]:.0f} right {man["right"]:.0f}')
            page.close()
    finally:
        browser.close()
