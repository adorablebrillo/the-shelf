#!/usr/bin/env python3
"""Anticipation is a vertical list: every countdown card shows without a
sideways scroll.

Intent — the reader's ask: "make arriving in your series vertical instead of
scrolling horizontal". A sideways row hid every card after the first behind a
scroll. This checks, on a phone and on a desktop, that the cards stack one
under the other, soonest first, each as wide as its section, and that nothing
in the section scrolls sideways.

Drives the made-up shelf served by verify-the-shelf (seeded with --surveyed,
so Home is not under the first-open survey). The made-up shelf tracks four
upcoming releases. Read-only: it writes no marks.

Run: python3 tests/anticipation_list.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
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
        for width, height in [(390, 844), (1280, 900)]:
            page = browser.new_page(viewport={'width': width, 'height': height}, reduced_motion='reduce')
            page.goto(url, wait_until='networkidle')
            section = page.get_by_role('region', name='Arriving in your series')
            section.wait_for()
            geo = section.evaluate("""s => {
                const list = s.querySelector('[data-m="rail"]');
                const box = list.getBoundingClientRect();
                return {
                    listWidth: box.width,
                    scrollWidth: list.scrollWidth,
                    clientWidth: list.clientWidth,
                    cards: [...list.children].map(c => {
                        const r = c.getBoundingClientRect();
                        return {left: r.left - box.left, top: r.top, bottom: r.bottom, width: r.width,
                                days: Number(c.querySelector(':scope > div > span').textContent)};
                    }),
                };
            }""")
            cards = geo['cards']
            print(f"{width}: {len(cards)} cards, tops {[round(c['top']) for c in cards]}, "
                  f"widths {[round(c['width']) for c in cards]}, list {geo['listWidth']:.0f}", flush=True)
            assert len(cards) >= 2, 'the made-up shelf should show more than one countdown card'
            assert geo['scrollWidth'] <= geo['clientWidth'], f'the list scrolls sideways at {width}px'
            for c in cards:
                assert abs(c['left']) < 1, f'a card is not at the left edge at {width}px: {c}'
                assert abs(c['width'] - geo['listWidth']) < 1, f'a card is not full width at {width}px: {c}'
            for a, b in zip(cards, cards[1:]):
                assert b['top'] >= a['bottom'], f'cards overlap or sit side by side at {width}px'
                assert b['days'] >= a['days'], f'cards are not soonest first at {width}px'
            page.close()
    finally:
        browser.close()
