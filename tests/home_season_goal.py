#!/usr/bin/env python3
"""THS-43: the season goal she gives counts on Home at once.

Intent — her ruling on the season goal: "Use the saved goal now; ask on Home
if skipped." The number the survey saves fills the ring straight away, with no
new run of the shelf; a survey that skipped the number leaves Home to ask it,
and the answer from Home is saved and kept. A season stamp is kept for good,
so none is pressed while the survey is still owed, while Home still asks, or
against a goal another device has since raised — not when the goal read
fails, nor when the goal changes while the stamp is on its way to the server.
A save of her goal outranks a goal read that overlaps it, and a double click
saves once. On a phone the question sits
under the issue line, so the reading-now card and the issue line keep the
first screen.

Drives the made-up shelf served by verify-the-shelf through the real survey,
so it writes the served volume's interests.json and reader-state.json. Run it
on a scratch volume seeded WITHOUT --surveyed (the survey must still be owed),
and delete both files between runs.

Run: python3 tests/home_season_goal.py http://127.0.0.1:8811
Requires Python Playwright and a locally installed Chromium browser. Set
CHROME_PATH when Playwright's own Chromium is not installed.
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline'))
from interests import DEFAULT_SEASON_GOAL   # the plan's goal when she gives none

URL = sys.argv[1].rstrip('/')
NOW_MS = int(datetime.now().timestamp() * 1000)


def api(path, payload=None):
    req = urllib.request.Request(URL + path, method='POST' if payload is not None else 'GET',
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def brew():
    return api('/api/interests')


def season_stamps():
    return [k for k, v in (api('/api/state').get('stamps') or {}).items()
            if k.startswith('season:') and (v or {}).get('s')]


def no_season_stamp(page, why):
    """The page presses stamps a moment after the state lands: give it time,
    then the server must still hold no season stamp."""
    page.wait_for_timeout(2500)
    assert season_stamps() == [], '%s: %r' % (why, season_stamps())


def page_season_stamps(page):
    """The season stamps the page itself holds as kept (its stored state,
    which the stamp row draws)."""
    return page.evaluate("""() => { const m = JSON.parse(localStorage.getItem('shelf.marks') || '{}');
      return Object.keys(m.stamps || {}).filter(k => k.startsWith('season:') && m.stamps[k].s); }""")


def tab_return(page):
    page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")


def wait_for(page, cond, why, secs=8):
    end = time.time() + secs
    while not cond():
        assert time.time() < end, why
        page.wait_for_timeout(100)


def read_marks(ids):
    api('/api/state', {'states': {i: {'s': 'read', 't': NOW_MS} for i in ids}})


def survey_to_last_step(page):
    survey = page.locator('#shelf-survey')
    expect(survey).to_be_visible()
    for _ in range(4):
        survey.get_by_role('button', name='next', exact=True).click()
    expect(survey.get_by_role('button', name='save to my shelf')).to_be_visible()
    return survey


def ring_goal(page):
    return page.locator('[data-m="ringgoal"]')


def asks(page):
    return page.locator('[data-m="goalask"]:visible')


assert brew().get('need_survey') is True, 'the volume is already surveyed: seed it without --surveyed'
assert season_stamps() == [], 'reader-state.json already holds a season stamp: delete it first'

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or None)
    desk = browser.new_page(viewport={'width': 1280, 'height': 900})
    desk.goto(URL + '/', wait_until='networkidle')
    built = desk.evaluate("() => (window.SHELF_DATA || {}).seasonGoal")
    ids = desk.evaluate("""() => {
      const d = window.SHELF_DATA || {}, out = [];
      (d.books || []).forEach(b => b.id && out.push(b.id));
      (d.series || []).forEach(s => (s.books || []).forEach(v => v.id && out.push(v.id)));
      return out; }""")
    assert len(ids) >= 9, 'need 9 book ids, the shelf has %d' % len(ids)
    reading = ids[0]    # a month's pick in progress, as on the agreed first screen
    api('/api/state', {'states': {reading: {'s': 'want', 't': NOW_MS}},
                       'reading': {reading: {'s': True, 't': NOW_MS}}})

    # 1 · the survey is still owed: six books read meet the fallback goal of
    #     six, and still no season stamp is kept
    read_marks(ids[1:7])
    desk.reload(wait_until='networkidle')
    expect(desk.locator('#shelf-survey')).to_be_visible()
    no_season_stamp(desk, 'a stamp was kept before she gave a goal')

    # 2 · the survey saves 8 books: the ring reads it at once, no new run
    survey = survey_to_last_step(desk)
    survey.get_by_role('button', name='more books this season').click()     # 6 → 7
    survey.get_by_role('button', name='more books this season').click()     # 7 → 8
    survey.get_by_role('button', name='save to my shelf').click()
    expect(desk.locator('#shelf-survey')).to_have_count(0)
    expect(ring_goal(desk)).to_have_text('of 8')
    expect(asks(desk)).to_have_count(0)
    assert brew()['season_goal'] == 8
    desk.reload(wait_until='networkidle')
    assert desk.evaluate("() => (window.SHELF_DATA || {}).seasonGoal") == built, \
        'the shelf was rebuilt; the test proves nothing'
    expect(ring_goal(desk)).to_have_text('of 8')

    # 3 · a phone left open at 8 while another device raises the goal to 9:
    #     two more books meet the phone's old 8, and no stamp is kept
    #     First the phone opens while its goal reads fail: the six books meet
    #     the plan's six, and still no stamp; back on the tab, the read works
    phone = browser.new_page(viewport={'width': 390, 'height': 844})
    reads_fail = [True]
    phone.route('**/api/interests', lambda route: route.abort()
                if reads_fail[0] and route.request.method == 'GET' else route.fallback())
    phone.goto(URL + '/', wait_until='networkidle')
    no_season_stamp(phone, 'a stamp was kept when the goal read failed')
    assert page_season_stamps(phone) == []
    reads_fail[0] = False
    tab_return(phone)
    expect(ring_goal(phone)).to_have_text('of 8')
    assert api('/api/interests/season-goal', {'season_goal': 9})['season_goal'] == 9
    read_marks(ids[7:9])
    phone.evaluate("() => window.dispatchEvent(new Event('shelf:imported'))")   # the marks only
    no_season_stamp(phone, 'a stamp was kept at a goal another device raised')
    expect(ring_goal(phone)).to_have_text('of 9')

    # 4 · the survey again, the number skipped: Home asks for it, the ring
    #     shows the plan's goal, the head claims no goal reached, and no stamp
    #     is kept while it asks
    desk.evaluate("() => window.SHELF_SURVEY.open()")
    survey = survey_to_last_step(desk)
    survey.get_by_role('button', name='skip', exact=True).click()
    survey.get_by_role('button', name='save to my shelf').click()
    expect(desk.locator('#shelf-survey')).to_have_count(0)
    expect(asks(desk)).to_have_count(1)
    expect(desk.locator('[data-m="season"] [data-m="goalask"]')).to_be_visible()
    expect(ring_goal(desk)).to_have_text('of %d' % DEFAULT_SEASON_GOAL)
    expect(desk.locator('[data-m="season"] h2')).to_have_text(re.compile(r'^\d+ books? this season$'))
    assert brew()['season_goal'] is None
    no_season_stamp(desk, 'a stamp was kept while Home still asks the goal')

    # 5 · on the phone the question sits under the issue line; the
    #     reading-now card and the issue line stay on the first screen
    phone.reload(wait_until='networkidle')
    ask = asks(phone)
    expect(ask).to_have_count(1)
    assert ask.get_attribute('data-at') == 'picks'
    fit = phone.evaluate("""() => {
      const b = s => document.querySelector(s).getBoundingClientRect();
      const line = document.querySelector('[data-m="issuebar"]').nextElementSibling.getBoundingClientRect();
      return {readnow: b('[data-m="readnow"]').bottom, line: line.bottom, bar: b('[data-m="bottomnav"]').top,
              ask: document.querySelector('[data-m="goalask"][data-at="picks"]').getBoundingClientRect().top}; }""")
    assert fit['readnow'] <= fit['bar'] and fit['line'] <= fit['bar'], fit
    assert fit['ask'] >= fit['line'], fit

    # 6 · she answers on the phone: 5 books. The network is out of order on
    #     purpose: a goal read from before the save comes back after it, a
    #     read made during the save comes back first, and she double-clicks
    surveyed = brew()['surveyed']
    held = {}

    def hold_read(route):
        if route.request.method == 'GET' and 'read' not in held and 'open' not in held:
            held['read'] = (route, route.fetch())       # the server's answer now: no goal
        else:
            route.continue_()

    def hold_save(route):
        if 'open' in held:
            return route.continue_()
        held.setdefault('saves', []).append(route)

    def hold_stamp(route):
        if (route.request.method == 'POST' and 'season_goal' in (route.request.post_data or '')
                and 'stamp' not in held and 'open' not in held):
            held['stamp'] = route
        else:
            route.continue_()

    phone.route('**/api/interests', hold_read)
    tab_return(phone)                                                       # read A, held
    wait_for(phone, lambda: 'read' in held, 'the page made no goal read on the tab return')
    phone.route('**/api/interests/season-goal', hold_save)
    phone.route('**/api/state', hold_stamp)
    ask.get_by_role('button', name='fewer books this season').click()       # 6 → 5
    expect(ask.locator('[data-m="goaldraft"]')).to_have_text('5')
    ask.get_by_role('button', name='set my goal').dblclick()
    wait_for(phone, lambda: held.get('saves'), 'the page sent no goal save')
    tab_return(phone)                                                       # read B, during the save
    phone.wait_for_timeout(1500)
    assert len(held['saves']) == 1, 'a double click saved %d times' % len(held['saves'])
    held['saves'][0].continue_()
    expect(phone.locator('[data-m="goalask"]')).to_have_count(0)
    expect(ring_goal(phone)).to_have_text('of 5')
    route, answer = held['read']
    route.fulfill(response=answer)                                          # read A lands last
    phone.wait_for_timeout(1500)
    expect(phone.locator('[data-m="goalask"]')).to_have_count(0)
    expect(ring_goal(phone)).to_have_text('of 5')
    saved = brew()
    assert saved['season_goal'] == 5 and saved['surveyed'] == surveyed, saved

    # 7 · her eight books meet 5, so the page sends the stamp; another device
    #     raises the goal to 20 before it arrives: the server keeps no stamp,
    #     and the page does not show one
    wait_for(phone, lambda: 'stamp' in held, 'the page sent no season stamp at her goal')
    assert api('/api/interests/season-goal', {'season_goal': 20})['season_goal'] == 20
    held['stamp'].continue_()
    phone.wait_for_timeout(2500)
    assert season_stamps() == [], 'a stamp was kept at a goal changed on its way: %r' % season_stamps()
    assert page_season_stamps(phone) == [], 'the page shows a stamp the server refused'

    # 8 · the goal goes back to 5; back on the tab the stamp is kept, on the
    #     server and on the page, and both survive a reload
    assert api('/api/interests/season-goal', {'season_goal': 5})['season_goal'] == 5
    tab_return(phone)
    wait_for(phone, lambda: len(season_stamps()) == 1, 'no season stamp at her own goal: %r' % season_stamps())
    wait_for(phone, lambda: len(page_season_stamps(phone)) == 1, 'the page does not show the kept stamp')
    held['open'] = True                                                      # the network in order again
    phone.reload(wait_until='networkidle')
    expect(ring_goal(phone)).to_have_text('of 5')
    expect(phone.locator('[data-m="goalask"]')).to_have_count(0)
    assert page_season_stamps(phone) == season_stamps()
    browser.close()

print('ok: the saved goal counts at once; a skipped goal is asked and kept on Home; '
      'no stamp at an owed, asked or raised goal, a failed read or a goal changed on the '
      "stamp's way; a save outranks overlapping reads and saves once; the phone keeps its first screen")
