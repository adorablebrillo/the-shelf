#!/usr/bin/env python3
"""Seed a made-up shelf for verification captures: scratch library.json,
sequels.json, added-books.json into a CFG_DIR of your choice, plus two made-up
month files into pipeline/data/. Made-up titles only — never the reader's own
shelf (the public repo ships blank; captures must show no real reader data).
Usage: python3 .claude/skills/verify-the-shelf/seed-demo.py <scratch-cfg-dir> [repo-root] [--surveyed]
--surveyed also writes the scratch volume's interests.json as a blank install's
defaults with the survey answered (a surveyed day, the plan's season goal of 6),
so the page opens straight on Home instead of the first-open survey and Home
asks no goal question. Leave it off to verify the survey itself. --surveyed
refuses a volume that already holds an interests.json.
"""
import json, os, sys
from datetime import date

flags = [a for a in sys.argv[1:] if a.startswith('--')]
args = [a for a in sys.argv[1:] if not a.startswith('--')]
cfg = args[0]
root = args[1] if len(args) > 1 else os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if '--surveyed' in flags and os.path.exists(os.path.join(cfg, 'interests.json')):
    # a surveyed fixture is made only in a fresh scratch volume: never write
    # over an interests file that is already there (it may be a reader's)
    sys.exit('seed-demo: %s already holds interests.json; use a fresh scratch volume for --surveyed'
             % cfg)
os.makedirs(cfg, exist_ok=True)
os.makedirs(os.path.join(root, 'pipeline', 'data'), exist_ok=True)

json.dump({
    "project": "demo",
    "description": "Made-up demo shelf for verification captures. No reader data.",
    "series": [
        {"name": "Gilded Thorns Court", "author": "Maren Ashby", "books": ["A Court of Gilded Thorns", "A Crown of Quiet Vows"]},
        {"name": "Match Point Hearts", "author": "Camille Ford", "books": ["Match Point Hearts"]},
        {"name": "Northbridge Wolves", "author": "Tessa Rhine", "books": ["Cold Snap", "Power Play"]},
        {"name": "The Harbor Letters", "author": "June Marlowe", "books": ["The Harbor Letters", "The Salt Road", "The Last Ferry"]}
    ]
}, open(os.path.join(cfg, 'library.json'), 'w'), indent=2)

json.dump({
    "project": "demo",
    "series": [
        {"series": "Gilded Thorns Court", "author": "Maren Ashby", "next_books": [
            {"title": "A Kingdom of Ash (#4)", "release_date": "2026-12-02", "status": "soon", "publisher": "Red Winter House"},
            {"title": "The Glass Oath (#5)", "release_date": "2026-12-29", "status": "soon", "publisher": "Red Winter House"}
        ]},
        {"series": "Match Point Hearts", "author": "Camille Ford", "next_books": [
            {"title": "Sudden Death (#2)", "release_date": "2027-02-10", "status": "soon", "publisher": "Brightline"}
        ]},
        {"series": "Northbridge Wolves", "author": "Tessa Rhine", "next_books": [
            {"title": "Overtime Hearts (#3)", "release_date": "2026-12-05", "status": "soon", "publisher": "Frostline"}
        ]}
    ]
}, open(os.path.join(cfg, 'sequels.json'), 'w'), indent=2)

json.dump({
    "books": [
        {"title": "The First Year, Gently", "author": "Dr. Lena Moss", "date": "2026-03-03",
         "genre": "Baby development", "spice": 0, "mmc": 0}
    ]
}, open(os.path.join(cfg, 'added-books.json'), 'w'), indent=2)

pick = lambda i, t, a, p, g, da, s, m, r, tr, h, w: {
    "id": i, "title": t, "author": a, "publisher": p, "genre": g, "date": da,
    "spice": s, "mmc": m, "rating": r, "formats": ["Ebook", "Paperback"], "tropes": tr,
    "hook": h, "why": w}

json.dump({"mode": "adhoc", "books": [
    pick("o1", "Wildfire Season", "Ada Quill", "Brightline", "Contemporary romance", "2026-10-06", 3, 3, 4.1,
         ["small town", "forced proximity"], "A fire lookout, the pilot who grounds her, and one long smoke season.",
         "A quiet slow burn with a setting that works for it."),
    pick("o2", "Blueline Billionaire", "Sawyer Kent", "Frostline", "Hockey romance", "2026-10-13", 4, 4, 3.9,
         ["rich hero", "opposites attract"], "He bought the team. She coaches its worst power play.",
         "The trope stack is familiar but the power-play detail lands.")
]}, open(os.path.join(root, 'pipeline', 'data', 'month-2026-10.json'), 'w'), indent=2)

json.dump({"mode": "adhoc", "top_pick": "p1", "books": [
    pick("p1", "The Penalty Box", "Ruby Calder", "Frostline", "Hockey romance", "2026-11-03", 4, 4, 4.3,
         ["forced proximity", "grumpy sunshine"], "A captain with one rule and a physio who keeps breaking it.",
         "The rule and the injury arc give the tension a spine."),
    pick("p2", "Queen of Thorns and Dusk", "Selene Marr", "Red Winter House", "Romantasy", "2026-11-10", 3, 5, 4.5,
         ["enemies to lovers", "fae bargain"], "A thorn witch bargains with the fae prince who cursed her sister.",
         "The bargain structure earns the slow turn."),
    pick("p3", "Slipstream", "Nadia Kerr", "Brightline", "F1 romance", "2026-11-17", 3, 4, 4.0,
         ["second chance", "rivals"], "Her rival's new teammate broke her heart at sixteen.",
         "Pit wall politics plus an old wound, and neither is decorative."),
    pick("p4", "Last Call at Rosie's", "Hannah Bell", "Brightline", "Contemporary romance", "2026-11-24", 3, 3, 4.2,
         ["rivals", "one bed"], "The bar owner, the new chef, and one shared lease.",
         "A kitchen romance where the lease does the arguing."),
    pick("p5", "The Winter Guest", "Iris Vale", "Red Winter House", "Contemporary romance", "2026-11-25", 4, 3, 4.1,
         ["snowed in", "widower"], "She keeps the lodge. He is the guest who will not leave early.",
         "Snowed in, with a guest who actually earns the stay."),
    pick("p6", "Faceoff at Midnight", "Domenic Pace", "Frostline", "Hockey romance", "2026-11-27", 5, 4, 4.4,
         ["forbidden", "coach's daughter"], "The league's curfew rule was not written for them.",
         "Spice-forward but the midnight deadline keeps it honest.")
]}, open(os.path.join(root, 'pipeline', 'data', 'month-2026-11.json'), 'w'), indent=2)

if '--surveyed' in flags:
    os.environ['CFG_DIR'] = os.path.abspath(cfg)
    sys.path.insert(0, os.path.join(root, 'pipeline'))
    import interests  # the one definition of a blank install's file
    doc = interests.defaults()
    doc['surveyed'] = date.today().isoformat()
    doc['season_goal'] = interests.DEFAULT_SEASON_GOAL  # answered, so Home asks nothing
    json.dump(doc, open(os.path.join(cfg, 'interests.json'), 'w'), indent=1)
    print('seeded a surveyed interests.json (defaults, season goal %d) into' % doc['season_goal'], cfg)

print('seeded made-up shelf into', cfg)
print('seeded made-up months 2026-10 and 2026-11 (current-month files need "mode": "adhoc")')
