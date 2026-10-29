#!/usr/bin/env python3
"""
build.py — turn a folder of original photographs into a deployable gallery.

Folder layout:

    my-site/
      build.py
      index.html
      originals/            <- your full-res exports (NEVER uploaded)
        Wildlife/
          swan-at-dusk.jpg
        Landscape/
        Portrait/
          ...
      photos/               <- generated: resized web copies
      photos.json           <- generated: the manifest index.html reads

The site opens on 'All' — every photograph it holds, newest arrival first.
Each subfolder of originals/ becomes a collection tab beside it, hung in the
order ORDER names below. A file left loose at the top level belongs to no
collection: it appears in 'All' and nowhere else.

Run:  python3 build.py
Then deploy index.html, photos.json and photos/ — leave originals/ behind.
"""

import hashlib
import html
import json
import os
import re
import shutil
from datetime import datetime
from fractions import Fraction

from PIL import Image, ImageOps
from PIL.ExifTags import TAGS

# ---------------------------------------------------------------- settings

SITE_TITLE = "Keith Merkelt Photography"
# The contact page: a heading and an address, nothing else. The address here is
# the forwarding alias on the domain, not the mailbox behind it. Empty the
# address and the page leaves the site.
CONTACT_HEADING = "Inquiries"
CONTACT_EMAIL = "hello@pixelrocket.studio"
# A photograph under the address, if you want one: drop a file called
# contact.jpg (or .png, .tif ...) straight into originals/. It hangs on the
# contact page only, and never joins the roll.
CONTACT_IMAGE = "contact"
# The copy the viewer opens. A 27" retina screen draws a photograph about
# 3100px wide there, so 2000 was being enlarged by half on any large display —
# the photograph was softest exactly when someone had leaned in to look at it.
LONG_EDGE = 3200

# The roll's copies are cut to the width they are *displayed* at, not to a long
# edge. A column is never wider than 702px, so one copy dresses an ordinary
# screen and one dresses a retina one; the browser takes whichever it needs
# and ignores the other. Sizing by width rather than long edge also means an
# upright photograph is no longer served short — under the old long-edge rule a
# portrait got 1300px of *height* and only ~870px of width, and went soft in
# the column.
#
# 720 clears a 702px column exactly, so an ordinary screen takes the small copy
# rather than tipping into the large one over two pixels; 1440 clears the same
# column on a retina screen.
GRID_WIDTHS = (720, 1440)

# The viewer's copies. One file was not enough: the viewer draws a photograph
# anywhere from 350px on a phone to 2400 device pixels on a retina desktop, and
# a single 3200px copy answered all of it by sending 3200px every time. Against
# the originals, at the width an ordinary desktop actually draws (900px):
#
#     the roll's 1440, q54 4:2:0      75K   SSIM 0.9765   <- what it used to send
#     1440 at the viewer's grade     112K   SSIM 0.9903
#     2048                           216K   SSIM 0.9940
#     3200                           522K   SSIM 0.9959   <- one copy for everyone
#
# Most of the distance is bought by the first step and most of the weight by
# the last. Three widths let the viewer ask for the one that fits: an ordinary
# desktop takes the 1440 and pays 112K for a picture that is no longer soft,
# while the 3200 waits for the screens — and the pinches — that can see it.
FULL_WIDTHS = (1440, 2048, 3200)

# Newest format first: the browser stops at the first <source> it can read.
#
# The roll keeps a JPEG at the end of the chain because it is cheap there and
# guarantees every frame shows something. The viewer does not: a full-size JPEG
# is by far the heaviest file the site would hold, and nothing can reach it.
# This page needs CSS aspect-ratio (Safari 15, 2021) to lay out at all, which
# is a *later* arrival than WebP (Safari 14, 2020) — so any browser that can
# draw the page can read WebP. The viewer also only ever opens on top of a
# frame the roll already loaded, so the format is known good by then.
FORMATS = ("avif", "webp", "jpg")
FULL_FORMATS = ("avif", "webp")

# AVIF's scale is not JPEG's, and the three copies of a photograph do not want
# the same number on it. Measured with SSIM against the untouched original,
# over the eight photographs the page actually opens with, at the size
# each copy is really drawn:
#
#     old pipeline, JPEG q82 at 1300px    SSIM 0.9465   1157K the screenful
#     AVIF q54 at 1440px                  SSIM 0.9643   1112K
#     AVIF q58 at 1440px                  SSIM 0.9694   1269K
#
# The retina copy sits at q54: better than the site has ever looked *and*
# lighter than it has ever been, which q58 gives up for a difference nobody
# reports seeing. It can afford to be leaner than the small copy because it is
# carrying twice the pixels into the same square inch of screen.
#
# The ordinary copy is a third of the weight at the same quality setting, so
# there is nothing to buy by starving it — it sits higher, at q65.
#
# The viewer's copy is a different case again. It is fetched only when someone
# has clicked a photograph to look at it properly, one at a time, on top of a
# frame already on screen — so nobody waits on it, and it is the one place
# worth spending freely.
QUALITY = {
    "1x":   {"avif": 65, "webp": 82, "jpg": 86},   # ordinary screens, drawn 1:1
    "2x":   {"avif": 54, "webp": 74, "jpg": 78},   # retina screens
    "full": {"avif": 72, "webp": 86},              # the viewer
}

# Colour is stored at half width and half height unless you ask otherwise
# (4:2:0), which is why a saturated edge — the red flank of a car against sky —
# goes soft and drifts before anything else does. Asking for full colour costs
# about 7% more bytes and removes about a third of the colour error.
#
# It is worth that on the copy an ordinary screen draws 1:1, where half-
# resolution colour means one colour sample per two pixels of car.
#
# It is not worth anything on the retina copy, and this is not a compromise:
# 4:2:0 colour in a 1440px file is 720 colour samples across a 702px column —
# already one per CSS pixel, which is exactly what full colour gives an
# ordinary screen. Paying twice for it would buy nothing but weight, on the
# one copy that decides how fast the page arrives.
#
# The viewer's copy gets full colour because it is the one being looked at.
SUBSAMPLING = {"1x": "4:4:4", "2x": "4:2:0", "full": "4:4:4"}

SRC = "originals"
FULL = "full"             # inside photos/: the viewer's copies
# The order the collection tabs hang in, left to right — or top to bottom on a
# wide screen, where they stand in the sidebar. Name the folders you care about
# and leave the rest: anything unnamed follows, alphabetically. Nothing is
# renamed on disk, so reordering the site is a line here and a rebuild.
ORDER = ["Wildlife", "Landscape", "Portrait", "Cars", "Nightwork"]
OUT = "photos"
MANIFEST = "photos.json"
CAMERA_FILE = "camera.txt"   # folder-wide camera details, for a roll of film

# Where the site answers from. A share card is fetched by a machine that has no
# idea what site the link came from, so the URLs in one cannot be relative.
# Change this and the cards follow; it is the only place the address is written.
SITE_URL = "https://photography.pixelrocket.studio"
# One small page per photograph, each carrying that photograph's share card.
# A link into the gallery is '…/#swan-at-rest', and a '#' never reaches the
# server — so the machine building the preview sees only the gallery page and
# every photograph in the site shares one card. These pages are the fragment
# written as a path, which a scraper can actually fetch. See share_page().
PAGES = "p"

# Everything a run generates is written here and moved into place in one go,
# once the build has finished. Until that moment the live photos/ is not
# touched at all — see swap_dir() for what that buys.
STAGE = OUT
PAGE_STAGE = PAGES

# Fields you can type by hand. A note beside one photograph may set any of
# them; camera.txt sets the ones a whole roll shares.
NOTE_KEYS = ("title", "make", "model", "lens", "focal", "aperture", "shutter", "iso", "date")
ROLL_KEYS = ("make", "model", "lens", "focal", "iso")

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
CAMERA_DEFAULT = re.compile(r"^(dsc|img|dscf|dscn|mg|imgp|gopr|pxl|photo|p)\d+$", re.I)
# '01-swan.jpg' hangs the photograph in position 1 without captioning it "01 Swan".
# Four digits or more is a year, and stays.
ORDER_PREFIX = re.compile(r"^\d{1,3}[-_. ]+(?=\D)")

# ---------------------------------------------------------------- helpers


def read_exif(img):
    """Flatten EXIF, including the ExifIFD sub-block, into a tag-name dict."""
    out = {}
    raw = img.getexif()
    if not raw:
        return out
    for tag_id, value in raw.items():
        out[TAGS.get(tag_id, tag_id)] = value
    try:
        for tag_id, value in raw.get_ifd(0x8769).items():
            out[TAGS.get(tag_id, tag_id)] = value
    except Exception:
        pass
    return out


def as_float(v):
    if v is None:
        return None
    try:
        if isinstance(v, tuple) and len(v) == 2:
            return v[0] / v[1]
        return float(v)
    except Exception:
        return None


def as_int(v):
    """ISO arrives as an int, a rational or a tuple depending on the camera."""
    if isinstance(v, (tuple, list)):
        v = v[0] if v else None
    f = as_float(v)
    return int(round(f)) if f is not None else None


def clean(v):
    if v is None:
        return None
    s = str(v).strip().strip("\x00")
    return s or None


ARRIVED = datetime.now().isoformat(timespec="seconds")


def file_id(path):
    """Fingerprint of the original, so a rename does not look like a new photo."""
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def previous_arrivals():
    """When each photograph first appeared, carried over from the last build.

    The page is ordered by the day a photograph joined the site, not the day it
    was taken — so a negative scanned today goes to the top where you will see
    it, instead of sinking to wherever it was shot.
    """
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return {}, {}
    photos = old.get("photos", [])
    by_id = {p["id"]: p["added"] for p in photos if p.get("id") and p.get("added")}
    by_src = {p["src"]: p["added"] for p in photos if p.get("src") and p.get("added")}
    return by_id, by_src


def read_note(path, allowed):
    """Parse 'key: value' lines out of a hand-written .txt. Blank if there is none."""
    fields = {}
    if not os.path.isfile(path):
        return fields
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key in allowed and value:
                fields[key] = value
            elif value:
                print(f"  ! {os.path.basename(path)}: no such field '{key}' — ignored")
    return fields


_roll_cache = {}


def roll_note(folder):
    """camera.txt: what every frame in this folder was shot on."""
    if folder not in _roll_cache:
        _roll_cache[folder] = read_note(os.path.join(folder, CAMERA_FILE), ROLL_KEYS)
    return _roll_cache[folder]


def typed_number(text):
    """'2.8', 'f/2.8' and '50mm' all give a number."""
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def typed_shutter(text):
    """'1/125' or '1/125s' -> 0.008; '2' or '2s' -> 2.0"""
    text = text.strip().lower().rstrip("s").strip()
    if "/" in text:
        top, _, bottom = text.partition("/")
        try:
            return float(top) / float(bottom)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(text)
    except ValueError:
        return None


# A day on its own stays a day: the page then shows the date without a
# meaningless 00:00:00 hanging off it.
DATE_FORMATS = (("%Y-%m-%d %H:%M:%S", True), ("%Y-%m-%d %H:%M", True),
                ("%Y:%m:%d %H:%M:%S", True), ("%Y-%m-%d", False),
                ("%Y/%m/%d", False), ("%d %B %Y", False), ("%d %b %Y", False))


def typed_date(text):
    for fmt, has_time in DATE_FORMATS:
        try:
            when = datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
        return when.isoformat() if has_time else when.date().isoformat()
    return None


TYPED = {
    "focal": typed_number,
    "aperture": typed_number,
    "shutter": typed_shutter,
    "iso": as_int,
    "date": typed_date,
}


def typed(fields, key):
    """One hand-typed field, converted to the shape the manifest wants."""
    if key not in fields:
        return None
    return TYPED.get(key, clean)(fields[key])


def first(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def parse_date(exif):
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        raw = clean(exif.get(key))
        if not raw:
            continue
        for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).isoformat()
            except ValueError:
                continue
    return None


def nice_aperture(f):
    if f is None:
        return None
    return int(f) if abs(f - round(f)) < 0.05 else round(f, 1)


def title_from(stem):
    squashed = re.sub(r"[\s_-]+", "", stem.lstrip("_"))
    if CAMERA_DEFAULT.match(squashed) or re.fullmatch(r"[0-9a-fA-F]{8,}", squashed):
        return ""
    words = re.sub(r"[_-]+", " ", ORDER_PREFIX.sub("", stem)).strip().split()
    return " ".join(w[0].upper() + w[1:] for w in words if w)


def average_tone(img):
    """The photograph flattened to a single colour.

    The page paints this into the frame while the picture itself is still on the
    wire, so a photograph arrives out of its own colour rather than out of grey.
    """
    one = img.convert("RGB").resize((1, 1), Image.BOX)
    return "#%02x%02x%02x" % one.getpixel((0, 0))


ENCODER = {
    "jpg":  ("JPEG", {"optimize": True, "progressive": True}),
    "webp": ("WEBP", {"method": 6}),
    "avif": ("AVIF", {}),
}
# JPEG spells the same setting with its own numbers; WebP has no say in it.
JPEG_SUBSAMPLING = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}


def save_image(img, path, fmt, tier):
    """One copy, in one format, at the quality that tier is worth.

    Writes no EXIF: location and serial numbers never reach the web copies.
    """
    kind, opts = ENCODER[fmt]
    opts = dict(opts)
    sub = SUBSAMPLING[tier]
    if fmt == "avif":
        opts["subsampling"] = sub
    elif fmt == "jpg":
        opts["subsampling"] = JPEG_SUBSAMPLING[sub]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path, kind, quality=QUALITY[tier][fmt], **opts)


def to_width(img, width):
    """A copy no wider than `width`. Never enlarges: a small original stays small."""
    if img.width <= width:
        return img.copy()
    return img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)


def grid_copies(img, slug):
    """Every copy the roll might hang, and the note the page needs to choose one.

    One photograph leaves here as up to six files — two widths in three formats.
    The page offers the lot and the browser downloads exactly one.
    """
    widths = []
    largest = None
    for n, want in enumerate(sorted(GRID_WIDTHS)):
        copy = to_width(img, want)
        if widths and copy.width == widths[-1]:
            continue          # the original ran out before this size did
        tier = "1x" if n == 0 else "2x"
        for fmt in FORMATS:
            # Written to the staging folder, named for where it will live: the
            # manifest below says photos/, because that is where it ends up.
            save_image(copy, os.path.join(STAGE, f"{slug}-{copy.width}.{fmt}"), fmt, tier)
        widths.append(copy.width)
        largest = copy
    return {
        # Browsers too old for srcset take this one, and the viewer opens on it.
        "src": f"{OUT}/{slug}-{widths[0]}.jpg",
        "base": f"{OUT}/{slug}",
        "grid": widths,
        "w": largest.width,
        "h": largest.height,
        "tone": average_tone(largest),
    }


def full_copies(img, slug):
    """The copies the viewer opens, and the widths it may choose between.

    The largest is always kept, whatever it came out at — that is the one a
    pinch reaches for. Below it sit the widths that are meaningfully smaller;
    one within a few per cent of another buys nothing but a file, which is
    what an upright photograph would otherwise collect, its long edge being
    its height.
    """
    biggest = img.width
    wants = [w for w in sorted(FULL_WIDTHS) if w < biggest * 0.85] + [biggest]
    widths = []
    for want in wants:
        copy = to_width(img, want)
        for fmt in FULL_FORMATS:
            save_image(copy, os.path.join(STAGE, FULL, f"{slug}-{copy.width}.{fmt}"),
                       fmt, "full")
        widths.append(copy.width)
    return widths


def web_copy(path, slug):
    """Resize one file into photos/ and report what the page needs to hang it."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return grid_copies(img, slug)


def contact_image():
    """The picture for the contact page, if one has been left in originals/."""
    for entry in sorted(os.listdir(SRC)):
        stem, ext = os.path.splitext(entry)
        if stem.lower() == CONTACT_IMAGE and ext.lower() in EXTS:
            print(f"\n  contact page: {entry}")
            try:
                return web_copy(os.path.join(SRC, entry), "contact")
            except Exception as err:
                # The contact portrait is a nicety. It is not worth the roll.
                print(f"  ! {entry}: {err} — contact page goes without a picture")
                return None
    return None


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "photo"


# ------------------------------------------------------------------ the cache

# A rebuild used to re-encode all seventy photographs however little had
# changed — a hundred seconds to add one picture, and a hundred seconds of
# destructive work every time anything else was adjusted. Nothing about a
# photograph's web copies depends on anything but the original's own bytes and
# the settings at the top of this file, so a copy once made is good until one
# of those changes. Keeping them means a rebuild re-encodes only what is new.
CACHE = ".build-cache"


def settings_id():
    """A fingerprint of every setting that decides what a copy looks like.

    Change a quality number, a width, a format — anything in here — and every
    key changes with it, so the cache empties itself rather than quietly
    serving copies made under the old rules. This is the whole safety of it:
    there is no way to adjust the encoding and still be handed a stale file.
    """
    return hashlib.sha1(json.dumps({
        "long_edge": LONG_EDGE,
        "grid": list(GRID_WIDTHS), "full_widths": list(FULL_WIDTHS),
        "formats": list(FORMATS), "full_formats": list(FULL_FORMATS),
        "quality": QUALITY, "subsampling": SUBSAMPLING,
    }, sort_keys=True).encode()).hexdigest()[:12]


SETTINGS = settings_id()


def cache_key(photo_id):
    """This original, under these settings. Either part changing is a new key."""
    return f"{photo_id}-{SETTINGS}"


def place(src, dest):
    """Hardlink where the filesystem allows it, copy where it does not.

    The cache and the staging folder are side by side in the same place, so a
    copy reused across builds is stored once however many builds reuse it.
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def cache_files(meta, slug):
    """Every file this entry holds: its name in the cache, its name in the build."""
    pairs = []
    for w in meta["grid"]:
        for fmt in FORMATS:
            pairs.append((f"g-{w}.{fmt}", os.path.join(STAGE, f"{slug}-{w}.{fmt}")))
    for w in meta["fulls"]:
        for fmt in FULL_FORMATS:
            pairs.append((f"f-{w}.{fmt}", os.path.join(STAGE, FULL, f"{slug}-{w}.{fmt}")))
    return pairs


def cache_read(key, slug):
    """Copies already made for this original under these settings, or None.

    An entry missing so much as one of the files it promises is no entry at
    all: it is passed over and made again, rather than half-filling the build.
    """
    home = os.path.join(CACHE, key)
    try:
        with open(os.path.join(home, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        pairs = cache_files(meta, slug)
        if not all(os.path.isfile(os.path.join(home, name)) for name, _ in pairs):
            return None
        for name, dest in pairs:
            place(os.path.join(home, name), dest)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return meta


def cache_write(key, slug, meta):
    """Keep what this build just made, for the next one. Never fatal."""
    home = os.path.join(CACHE, key)
    try:
        shutil.rmtree(home, ignore_errors=True)
        os.makedirs(home, exist_ok=True)
        for name, made in cache_files(meta, slug):
            place(made, os.path.join(home, name))
        with open(os.path.join(home, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
    except OSError as err:
        print(f"  ! could not keep {slug} for next time: {err}")


def cache_prune(keep):
    """Entries for originals this build did not see, and for settings no longer
       in force. Only ever called once a build has succeeded, when `keep` is
       known to be the whole truth about what the site holds."""
    if not os.path.isdir(CACHE):
        return 0
    gone = 0
    for name in os.listdir(CACHE):
        if name not in keep:
            shutil.rmtree(os.path.join(CACHE, name), ignore_errors=True)
            gone += 1
    return gone


# ------------------------------------------------------- putting it in place


def swap_dir(stage, live):
    """Move a finished staging folder into place, and take the old one away.

    The build used to empty photos/ as its first act and fill it again as it
    went, which meant any run that did not reach the end left the site holding
    a fraction of its photographs — and a run that got nowhere at all, because
    originals/ was not there, left it holding none. originals/ is not in the
    repository, so that was every fresh clone.

    Nothing is removed now until a replacement exists. A build that falls over
    anywhere — a missing folder, a file Pillow cannot open, a full disk — tidies
    its staging folder away and leaves the deployed photographs untouched.
    """
    old = live + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(live):
        os.rename(live, old)
    os.rename(stage, live)
    shutil.rmtree(old, ignore_errors=True)


def recover():
    """Finish a swap that was interrupted between its two renames."""
    for live in (OUT, PAGES):
        old = live + ".old"
        if not os.path.isdir(live) and os.path.isdir(old):
            print(f"  ! a previous run stopped mid-swap — putting {live}/ back")
            os.rename(old, live)


def fresh(path):
    """An empty staging folder, whatever was left behind last time."""
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


# --------------------------------------------------------------- share cards

# Everything here is a machine's view of one photograph: the card that appears
# when the link is pasted into a message. People never read this page — the
# script sends them straight to the photograph in the gallery, and the link
# below is only there for the rare reader with no script at all.
SHARE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — {site}</title>
<link rel="canonical" href="{deep}">
<meta name="robots" content="noindex, follow">
<meta name="description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{site}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{deep}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="{w}">
<meta property="og:image:height" content="{h}">
<meta property="og:image:alt" content="{title}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{image}">
<!-- The card above has to be absolute: it is read by a machine somewhere else,
     which has no idea what site the link came from. Going back to the gallery
     is the opposite case — it is a step within whatever copy of the site this
     page was served from, so it is relative, and the page works the same
     opened locally, on a staging copy or on the live site. -->
<script>location.replace({here_js});</script>
</head>
<body>
<p><a href="{here}">{title} — {site}</a></p>
</body>
</html>
"""


def card_words(photo):
    """What the card says under the title: the camera, and what it was set to."""
    bits = []
    if photo.get("model"):
        bits.append(" ".join(x for x in (photo.get("make"), photo.get("model")) if x))
    elif photo.get("make"):
        bits.append(photo["make"])
    exposure = []
    if photo.get("iso") is not None:
        exposure.append(f"ISO{photo['iso']}")
    if photo.get("aperture") is not None:
        exposure.append(f"f/{photo['aperture']}")
    shutter = photo.get("shutter")
    if shutter:
        exposure.append(f"{round(shutter, 1)}s" if shutter >= 1 else f"1/{round(1 / shutter)}s")
    if exposure:
        bits.append(" · ".join(exposure))
    return " — ".join(bits) if bits else f"A photograph from {SITE_TITLE}."


def share_pages(photos):
    """One page per photograph, so a pasted link carries that photograph.

    The card points at the JPEG rather than the AVIF the site actually serves:
    the machines that build these previews are not browsers, and several of
    them still cannot read anything newer.
    """
    fresh(PAGE_STAGE)
    for photo in photos:
        slug = photo["full"].split("/")[-1]
        title = photo.get("title") or "Photograph"
        deep = f"{SITE_URL}/#{slug}"
        here = f"../#{slug}"          # the same photograph, from this page
        card = SHARE_PAGE.format(
            title=html.escape(title, quote=True),
            site=html.escape(SITE_TITLE, quote=True),
            desc=html.escape(card_words(photo), quote=True),
            deep=html.escape(deep, quote=True),
            here=html.escape(here, quote=True),
            here_js=json.dumps(here),
            image=html.escape(f"{SITE_URL}/{OUT}/{slug}-{photo['grid'][-1]}.jpg", quote=True),
            w=photo["w"], h=photo["h"],
        )
        with open(os.path.join(PAGE_STAGE, f"{slug}.html"), "w", encoding="utf-8") as fh:
            fh.write(card)
    print(f"  {len(photos)} share cards in {PAGES}/")


# ---------------------------------------------------------------- main


def in_order(names):
    """The collections hung in ORDER. A folder ORDER never mentions follows it,
    in alphabetical order, so a new one appears without having to be named."""
    named = {name.lower(): i for i, name in enumerate(ORDER)}
    return sorted(names, key=lambda c: (named.get(c.lower(), len(named)), c.lower()))


def gather():
    """Yield (collection_or_None, filepath) pairs, collections in folder order."""
    if not os.path.isdir(SRC):
        raise SystemExit(f"No '{SRC}/' folder found. Create it and put your photos inside.")

    loose, foldered = [], []
    for entry in sorted(os.listdir(SRC)):
        path = os.path.join(SRC, entry)
        if entry.startswith("."):
            continue
        if os.path.isdir(path):
            collection = entry
            bucket = foldered
            for name in sorted(os.listdir(path)):
                if os.path.splitext(name)[1].lower() in EXTS:
                    bucket.append((collection, os.path.join(path, name)))
        elif os.path.splitext(entry)[1].lower() in EXTS:
            if os.path.splitext(entry)[0].lower() == CONTACT_IMAGE:
                continue          # hangs on the contact page instead
            loose.append((None, path))
    return loose + foldered


def build():
    global STAGE, PAGE_STAGE

    # Ask every question that can refuse the build before anything is written,
    # and before anything already deployed is touched.
    recover()
    items = gather()
    if not items:
        raise SystemExit(f"No images found under '{SRC}/'.")

    STAGE, PAGE_STAGE = OUT + ".new", PAGES + ".new"
    fresh(STAGE)
    try:
        photos, collections, skipped, keys, reused = lay_out(items)
    except BaseException:
        # Including the interrupt from a Ctrl-C: a half-built folder is no use
        # to anyone, and leaving it would make the next run's job ambiguous.
        shutil.rmtree(STAGE, ignore_errors=True)
        raise
    if not photos:
        shutil.rmtree(STAGE, ignore_errors=True)
        raise SystemExit(f"Not one photograph could be read. '{OUT}/' left as it was.")
    publish(photos, collections, skipped, keys, reused)


def lay_out(items):
    """Every original turned into web copies, and the records to hang them by.

    A photograph that cannot be read is reported and left out. One truncated
    file used to end the run with a traceback, which — because the manifest is
    written last — left photos.json describing a set of files that no longer
    existed. The page drops a frame whose file is missing, so the site went on
    looking perfectly well while quietly holding fewer photographs.
    """
    known_by_id, known_by_src = previous_arrivals()
    collections, photos, used, skipped, keys = [], [], set(), [], set()
    reused = 0

    for collection, path in items:
        stem = os.path.splitext(os.path.basename(path))[0]
        # The name a photograph's files take depends on nothing but its own
        # name, so it can be settled before the file is opened — and the cache
        # needs it to know what to call what it hands back.
        base = slugify(f"{collection}-{stem}" if collection else stem)
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1

        try:
            photo_id = file_id(path)
            key = cache_key(photo_id)
            ready = cache_read(key, slug)
            if ready:
                # The copies are made and in place already. Only the EXIF still
                # has to come off the original, and that is read from its
                # header without decoding a single pixel.
                with Image.open(path) as img:
                    exif = read_exif(img)
                hung = {"src": f"{OUT}/{slug}-{ready['grid'][0]}.jpg",
                        "base": f"{OUT}/{slug}", "grid": ready["grid"],
                        "w": ready["w"], "h": ready["h"], "tone": ready["tone"]}
                fulls = ready["fulls"]
                reused += 1
            else:
                with Image.open(path) as img:
                    exif = read_exif(img)
                    img = ImageOps.exif_transpose(img)  # honour rotation, then drop it
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.thumbnail((LONG_EDGE, LONG_EDGE), Image.LANCZOS)

                    # Saving a fresh image writes no EXIF: location and serial
                    # numbers never reach the web copy.
                    fulls = full_copies(img, slug)

                    # The roll hangs smaller copies. A photograph 700px wide on
                    # screen has no use for 2000 pixels, and twenty of them
                    # have to arrive before the page is a page.
                    hung = grid_copies(img, slug)
                cache_write(key, slug, {"grid": hung["grid"], "fulls": fulls,
                                        "w": hung["w"], "h": hung["h"],
                                        "tone": hung["tone"]})
            full_base = f"{OUT}/{FULL}/{slug}"
            w, h = hung["w"], hung["h"]
        except Exception as err:
            print(f"  ! {os.path.relpath(path, SRC)}: {err} — left out")
            skipped.append(os.path.relpath(path, SRC))
            continue

        used.add(slug)
        keys.add(key)
        # Only a photograph that made it earns its folder a tab.
        if collection and collection not in collections:
            collections.append(collection)

        # What you typed beside the photograph wins, then whatever the file
        # itself knows, then what the roll declares. Film scans know nothing,
        # so for those it is simply what you typed.
        note = read_note(os.path.splitext(path)[0] + ".txt", NOTE_KEYS)
        roll = roll_note(os.path.dirname(path))
        for key in note:
            if typed(note, key) is None:
                print(f"  ! {stem}.txt: could not read '{key}: {note[key]}' — ignored")

        record = {
            "src": hung["src"],
            "base": hung["base"],
            "grid": hung["grid"],
            "full": full_base,
            "fulls": fulls,
            "title": first(typed(note, "title"), title_from(stem)),
            "collection": collection,
            "w": w,
            "h": h,
            "tone": hung["tone"],
            "make": first(typed(note, "make"), clean(exif.get("Make")), typed(roll, "make")),
            "model": first(typed(note, "model"), clean(exif.get("Model")), typed(roll, "model")),
            "lens": first(typed(note, "lens"), clean(exif.get("LensModel")), typed(roll, "lens")),
            "focal": first(typed(note, "focal"), as_float(exif.get("FocalLength")),
                           typed(roll, "focal")),
            "aperture": nice_aperture(first(typed(note, "aperture"),
                                            as_float(exif.get("FNumber")))),
            "shutter": first(typed(note, "shutter"), as_float(exif.get("ExposureTime"))),
            "iso": first(typed(note, "iso"),
                         as_int(exif.get("ISOSpeedRatings")
                                or exif.get("PhotographicSensitivity")),
                         typed(roll, "iso")),
            "date": first(typed(note, "date"), parse_date(exif)),
        }

        # Seen before under either its fingerprint or its filename? Keep the day
        # it arrived. Otherwise it is new today, and belongs at the top.
        record["id"] = photo_id
        record["added"] = first(known_by_id.get(photo_id),
                                known_by_src.get(record["src"]),
                                ARRIVED)
        photos.append({k: v for k, v in record.items() if v not in (None, "")})
        photos[-1].setdefault("title", "")

        if not record["make"] and not record["model"]:
            print(f"  ! {stem}: no camera details. The export kept no EXIF "
                  f"(Photoshop drops it) — add {stem}.txt to type them in.")

        label = record["title"] or stem
        print(f"  {(collection or chr(8212)):22} {label[:38]:40} {w}x{h}")

    # Newest arrivals at the top; within a batch, the newest photograph first.
    # Python's sort is stable, so anything undated keeps its filename order.
    photos.sort(key=lambda p: (p.get("added", ""), p.get("date") or ""), reverse=True)

    collections = in_order(collections)

    print("\nPage order — most recently added first:")
    for photo in photos:
        print(f"  added {photo['added'][:16].replace('T', ' ')}   {photo['title'] or '(untitled)'}")

    return photos, collections, skipped, keys, reused


def publish(photos, collections, skipped, keys, reused):
    """The finished build put in place, and nothing moved until it is finished."""
    manifest = {"title": SITE_TITLE,
                "formats": list(FORMATS), "fullFormats": list(FULL_FORMATS),
                # Where the share cards live, so the page only offers a link
                # it knows is there. An older photos.json leaves this out and
                # the page falls back to the plain '#' link.
                "pages": PAGES,
                "collections": collections, "photos": photos}
    if CONTACT_EMAIL:
        manifest["contact"] = {"heading": CONTACT_HEADING, "email": CONTACT_EMAIL}
        picture = contact_image()
        if picture:
            manifest["contact"]["image"] = picture

    share_pages(photos)

    # The manifest is written beside the live one and moved over it, so a
    # reader never catches it half-written.
    draft = MANIFEST + ".new"
    with open(draft, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    swap_dir(STAGE, OUT)
    swap_dir(PAGE_STAGE, PAGES)
    os.replace(draft, MANIFEST)

    # Only now that the build has succeeded is `keys` the whole truth about
    # what the site holds, and only then is it safe to throw anything away.
    stale = cache_prune(keys)

    print(f"\n{len(photos)} photographs across {len(collections)} collection(s).")
    print(f"{reused} reused from the cache, {len(photos) - reused} encoded"
          + (f", {stale} stale entries dropped" if stale else ""))
    if skipped:
        print(f"{len(skipped)} left out: {', '.join(skipped)}")
    print(f"Wrote {MANIFEST}, {OUT}/ and {PAGES}/")
    print(f"Deploy: index.html, photos.json, photos/, {PAGES}/"
          "  — keep originals/ off the server.")


if __name__ == "__main__":
    build()
