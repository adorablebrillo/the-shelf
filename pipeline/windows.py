#!/usr/bin/env python3
"""The Shelf — one definition of the run's target month and window end,
shared by filter/curate so the two can never drift apart."""
import calendar
from datetime import date


def target_month(mode):
    """adhoc -> this month; scheduled -> the previous month."""
    if mode == 'adhoc':
        return date.today().strftime('%Y-%m')
    t = date.today()
    py, pm = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return '%04d-%02d' % (py, pm)


def window_end(mode, mon=None):
    """The last day a pick may be released in."""
    if mode == 'adhoc':
        return date.today()
    if mon is None:
        t = date.today()
        py, pm = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    else:
        py, pm = int(mon[:4]), int(mon[5:7])
    return date(py, pm, calendar.monthrange(py, pm)[1])
