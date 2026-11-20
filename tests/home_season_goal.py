#!/usr/bin/env python3
"""THS-43: the season goal she gives counts on Home at once.

Intent — her ruling on the season goal: "Use the saved goal now; ask on Home
if skipped." The number the survey saves fills the ring straight away, with no
new run of the shelf; a survey that skipped the number leaves Home to ask it,
and the answer from Home is saved and kept.

Drives the made-up shelf served by verify-the-shelf through the real survey,
so it writes the served volume's interests.json. Run it on a scratch volume
seeded WITHOUT --surveyed (the survey must still be owed), and delete that
volume's interests.json between runs.

Run: python3 tests/home_season_goal.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import json
import os
import sys
import urllib.request
from playwright.sync_api import sync_playwright, expect

URL = sys.argv[1].rstrip('/')


def brew():
    return json.loads(urllib.request.urlopen(URL + '/api/interests', timeout=15).read().decode())


def build_goal(page):
    return page.evaluate("() => (window.SHELF_DATA || {}).seasonGoal")


def survey_to_last_step(page):
    survey = page.locator('#shelf-survey')
    expect(survey).to_be_visible()
    for _ in range(4):
        survey.get_by_role('button', name='next', exact=True).click()
    expect(survey.get_by_role('button', name='save to my shelf')).to_be_visible()
    return survey


def ring_goal(page):
    return page.locator('[data-m="ringgoal"]')


start = brew()
assert start.get('need_survey') is True, 'the volume is already surveyed: seed it without --surveyed'

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or None)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})
    page.goto(URL + '/', wait_until='networkidle')
    built = build_goal(page)

    # 1 · the survey saves 4 books: the ring reads it at once, no new run
    survey = survey_to_last_step(page)
    survey.get_by_role('button', name='fewer books this season').click()   # 6 → 5
    survey.get_by_role('button', name='fewer books this season').click()   # 5 → 4
    survey.get_by_role('button', name='save to my shelf').click()
    expect(page.locator('#shelf-survey')).to_have_count(0)
    expect(ring_goal(page)).to_have_text('of 4')
    expect(page.locator('[data-m="goalask"]')).to_have_count(0)
    assert brew()['season_goal'] == 4
    page.reload(wait_until='networkidle')
    assert build_goal(page) == built, 'the shelf was rebuilt; the test proves nothing'
    expect(ring_goal(page)).to_have_text('of 4')

    # 2 · the survey again, the number skipped: Home asks for it
    page.evaluate("() => window.SHELF_SURVEY.open()")
    survey = survey_to_last_step(page)
    survey.get_by_role('button', name='skip', exact=True).click()
    survey.get_by_role('button', name='save to my shelf').click()
    expect(page.locator('#shelf-survey')).to_have_count(0)
    ask = page.locator('[data-m="goalask"]')
    expect(ask).to_be_visible()
    expect(ring_goal(page)).to_have_text('of %d' % built)
    assert brew()['season_goal'] is None

    # 3 · she answers on Home: 5 books, saved, the question gone, kept on reload
    surveyed = brew()['surveyed']
    ask.get_by_role('button', name='fewer books this season').click()       # 6 → 5
    expect(ask.locator('[data-m="goaldraft"]')).to_have_text('5')
    ask.get_by_role('button', name='set my goal').click()
    expect(page.locator('[data-m="goalask"]')).to_have_count(0)
    expect(ring_goal(page)).to_have_text('of 5')
    saved = brew()
    assert saved['season_goal'] == 5 and saved['surveyed'] == surveyed, saved
    page.reload(wait_until='networkidle')
    expect(ring_goal(page)).to_have_text('of 5')
    expect(page.locator('[data-m="goalask"]')).to_have_count(0)
    browser.close()

print('ok: the saved goal counts at once; a skipped goal is asked and kept on Home')
