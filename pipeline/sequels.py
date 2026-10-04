#!/usr/bin/env python3
"""#76 — the sequel guarantee.

Her rule (2026-10-04, verbatim intent): a book in a series she is already in
"should override all criteria and make sure it appears in the top picks list".
The pipeline matches candidates against EVERY series she is in — library.json
(what she has read / owns) and sequels.json (the tracked next books) — marks
them `aseq`, and then neither a screen, the cap, nor the curator's judgment may
drop one (her own verdicts and the hard screens still apply — a book she
already marked never returns, and an M/F or cowboy title is never hers).

This is deterministic on purpose: the taste prompt asks the model to mark
sequels, but the model is not a gate here (it dropped "Threshing Day" from the
September candidates, 2026-10-01 — the reader's Empyrean sequel — even though
it later picked it as the top pick from the marked pool).
"""
import json, re

import paths


def norm_name(s):
    """Series keys for matching: parentheticals dropped, alphanumerics only.
    (Same semantics as build.norm_name — kept local so filter/curate never
    import the build stage.)"""
    s = re.sub(r'\([^)]*\)', ' ', s or '')
    return re.sub(r'[^a-z0-9]', '', s.lower())


def tracked_series():
    """Every series name she is in, normalized. Best-effort, but LOUD: an
    unreadable file must never silently masquerade as 'no series' (the review
    of #76: a corrupt sequels.json would quietly turn the guarantee off)."""
    names = set()
    for fname in ('library.json', 'sequels.json'):
        try:
            path, src = paths.personal(fname)
            if src == 'missing':
                continue
            with open(path) as f:
                data = json.load(f)
            for s in (data or {}).get('series', []):
                if not isinstance(s, dict):
                    continue
                for k in ('series', 'name'):
                    n = norm_name(s.get(k))
                    if n:
                        names.add(n)
        except Exception as e:
            print('sequels: %s unreadable (%s) — those series cannot be matched this run'
                  % (fname, str(e)[:60]))
    return names


def is_sequel(book, names):
    """True when the candidate continues a series she is already in.

    Exact normalized match first; then a guarded containment fallback, because
    real name drift is normal ('The Empyrean' vs 'Empyrean' vs 'The Empyrean
    #4') and build.py's own series matching is fuzzy for the same reason. The
    6-char floor keeps a short series word from matching half the catalog."""
    if not names:
        return False
    n = norm_name((book or {}).get('series'))
    if not n:
        return False
    if n in names:
        return True
    if len(n) < 6:
        return False
    return any(len(t) >= 6 and (n in t or t in n) for t in names)
