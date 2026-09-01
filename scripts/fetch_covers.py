#!/usr/bin/env python3
"""Fetch 8 mock book covers from Pollinations for THE SHELF design variants.
Portrait 512x768, no text (CSS overlays titles), one seed each, jpg output."""
import urllib.parse, urllib.request, os, sys

OUT = os.path.expanduser("~/Documents/HermesApps/the-shelf/.lavish/assets")
os.makedirs(OUT, exist_ok=True)

COVERS = {
    "cover-01-iron-crown.jpg": ("epic romantasy book cover art, a crowned woman in ash-grey armor stands before a smoldering castle, a huge black dragon silhouette coils in ember-lit smoke above, dramatic warm embers and gold crown glowing, painterly digital art, vertical book cover composition, no text, no typography, no letters", 11),
    "cover-02-throttle-hearts.jpg": ("romance book cover art, a Formula 1 driver in a red racing suit and a woman in a paddock embrace at golden hour sunset, a race car teardrop of heart shaped exhaust smoke, glossy cinematic romance cover, vertical composition, no text, no typography, no letters", 22),
    "cover-03-ice-gameweek.jpg": ("romance book cover art, a hockey player in a blue jersey and a woman sharing a moment on a rink, ice spray backlit by warm arena lights, romantic cinematic, vertical composition, no text, no typography, no letters", 33),
    "cover-04-starless-court.jpg": ("romantasy book cover art, a pale winged male figure stands in a gothic night court under a star-filled deep blue sky, silver moonlight on marble, majestic and romantic fantasy, vertical composition, no text, no typography, no letters", 44),
    "cover-05-grid-girls.jpg": ("romance book cover art, two rival Formula 1 drivers, one man one woman in racing suits, facing off in a neon-lit pit lane at night, tension and sparks, bold glossy romance cover, vertical composition, no text, no typography, no letters", 55),
    "cover-06-demon-third-line.jpg": ("romance book cover art, a handsome hockey player with an intense stare on an ice rink, dramatic dark arena lighting, moody romantic sports cover, vertical composition, no text, no typography, no letters", 66),
    "cover-07-ember-ash.jpg": ("romantasy book cover art, a fae woman with embers rising from her hands walks through an ash-covered gothic court, deep crimson and charcoal palette, romantic dark fantasy, vertical composition, no text, no typography, no letters", 77),
    "cover-08-touchdown-rosewood.jpg": ("romance book cover art, a college football player in a vineyard-red jersey and a young woman at a stadium at golden hour, warm rose petals in the air, nostalgic romantic sports cover, vertical composition, no text, no typography, no letters", 88),
}

for name, (prompt, seed) in COVERS.items():
    path = os.path.join(OUT, name)
    if os.path.exists(path) and os.path.getsize(path) > 20000:
        print("exists", name); continue
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
           + f"?width=512&height=768&seed={seed}&nologo=true")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        open(path, "wb").write(data)
        print("ok", name, len(data))
    except Exception as e:
        print("FAIL", name, e)
