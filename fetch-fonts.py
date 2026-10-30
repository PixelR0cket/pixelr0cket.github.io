#!/usr/bin/env python3
"""
fetch-fonts.py — put the site's typefaces in fonts/, so the page does not have
to fetch them from somebody else.

A stylesheet from fonts.googleapis.com blocks the first paint, and holds the
page behind a DNS lookup, a handshake and a TLS negotiation to that host before
a second set of all three to fonts.gstatic.com for the files themselves. Served
from the site they arrive on a connection that is already open.

Run this only when a face or a weight changes — the files it writes are
committed, and the site never calls out to Google at runtime.

    python3 fetch-fonts.py            # writes ./fonts/
    python3 fetch-fonts.py some/dir   # or wherever you want them

Then check the @font-face block at the head of index.html still names what
landed here. Nothing else reads this script; build.py does not run it.
"""

import re, os, sys, urllib.request, urllib.parse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
OUT = sys.argv[1] if len(sys.argv) > 1 else "fonts"
os.makedirs(OUT, exist_ok=True)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read()

WORDMARK = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
            "0123456789 &'-.,!?")

SHEETS = [
  # One variable file per style covers 400, 500 and 700 — three static cuts
  # of the same typeface, which is three downloads of mostly the same outlines.
  ("https://fonts.googleapis.com/css2?family=Karla:ital,wght@0,400..700;1,400..700&display=swap", "karla"),
  # Regular only. The sidebar is the one thing set in this, at one weight;
  # a bold was being downloaded that no rule in index.html ever asks for.
  ("https://fonts.googleapis.com/css2?family=Cousine:wght@400&display=swap", "cousine"),
  # The wordmark, and nothing else on the site, is set in this one. Google cuts
  # a font down to named characters, so what ships is the letters a title can
  # be written with rather than a whole typeface for one line.
  ("https://fonts.googleapis.com/css2?family=Reenie+Beanie&text="
   + urllib.parse.quote(WORDMARK), "reenie-beanie"),
]

BLOCK = re.compile(r"(?:/\*\s*([\w-]+)\s*\*/\s*)?(@font-face\s*\{.*?\})", re.S)
def field(name, css):
    m = re.search(name + r":\s*([^;]+);", css)
    return m.group(1).strip() if m else ""

faces = []
for url, slug_base in SHEETS:
    css = get(url).decode("utf-8")
    for subset, face in BLOCK.findall(css):
        # A &text= sheet carries one unlabelled face; everything else is
        # labelled by subset and only latin is wanted.
        if subset and subset != "latin":
            continue
        src = re.search(r"url\((https://[^)]+)\)", face)
        if not src:
            continue
        style = field("font-style", face) or "normal"
        weight = field("font-weight", face) or "400"
        # A variable face carries its whole range in one file and needs no
        # weight in the name; a static cut does, or the second overwrites it.
        variable = " " in weight
        slug = (slug_base
                + ("" if variable else "-" + weight)
                + ("-italic" if style == "italic" else "") + ".woff2")
        data = get(src.group(1))
        with open(os.path.join(OUT, slug), "wb") as fh:
            fh.write(data)
        faces.append((slug, style, weight, len(data)))
        print(f"  {slug:26} {len(data)//1024:3}K   weight {weight:9} {style}")

print(f"\n{len(faces)} files, {sum(f[3] for f in faces)//1024}K total")
