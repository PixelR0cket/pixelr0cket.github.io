#!/usr/bin/env python3
"""
build.py — turn a folder of original photographs into a deployable gallery.

Folder layout:

    my-site/
      build.py
      index.html
      originals/            <- your full-res exports (NEVER uploaded)
        Featured Work/          <- the front page, not a tab
          swan-at-dusk.jpg
        Landscapes/
        Portraits/
          ...
      photos/               <- generated: resized web copies
      photos.json           <- generated: the manifest index.html reads

Each subfolder of originals/ becomes an optional collection tab, except the
one named by FRONT below: that folder is the front page. Loose files at the top
level belong to no collection either, and join the front page beside it.

Run:  python3 build.py
Then deploy index.html, photos.json and photos/ — leave originals/ behind.
"""

import hashlib
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
LONG_EDGE = 2000          # max pixel dimension served to the web
JPEG_QUALITY = 82

SRC = "originals"
# The front page. A folder by this name is not a collection: its photographs
# are the ones the site opens on, the same as files left loose in originals/.
FRONT = "Featured Work"
OUT = "photos"
MANIFEST = "photos.json"
CAMERA_FILE = "camera.txt"   # folder-wide camera details, for a roll of film

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


def web_copy(path, slug):
    """Resize one file into photos/ and report what the page needs to hang it."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((LONG_EDGE, LONG_EDGE), Image.LANCZOS)
        img.save(os.path.join(OUT, slug + ".jpg"), "JPEG", quality=JPEG_QUALITY,
                 optimize=True, progressive=True)
        w, h = img.size
        return {"src": f"{OUT}/{slug}.jpg", "w": w, "h": h, "tone": average_tone(img)}


def contact_image():
    """The picture for the contact page, if one has been left in originals/."""
    for entry in sorted(os.listdir(SRC)):
        stem, ext = os.path.splitext(entry)
        if stem.lower() == CONTACT_IMAGE and ext.lower() in EXTS:
            print(f"\n  contact page: {entry}")
            return web_copy(os.path.join(SRC, entry), "contact")
    return None


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "photo"


# ---------------------------------------------------------------- main


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
            # The front-page folder keeps originals/ tidy without earning a tab:
            # its photographs are filed exactly as loose ones are.
            collection = None if entry == FRONT else entry
            bucket = loose if collection is None else foldered
            for name in sorted(os.listdir(path)):
                if os.path.splitext(name)[1].lower() in EXTS:
                    bucket.append((collection, os.path.join(path, name)))
        elif os.path.splitext(entry)[1].lower() in EXTS:
            if os.path.splitext(entry)[0].lower() == CONTACT_IMAGE:
                continue          # hangs on the contact page instead
            loose.append((None, path))
    return loose + foldered


def build():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    items = gather()
    if not items:
        raise SystemExit(f"No images found under '{SRC}/'.")

    known_by_id, known_by_src = previous_arrivals()
    collections, photos, used = [], [], set()

    for collection, path in items:
        if collection and collection not in collections:
            collections.append(collection)

        stem = os.path.splitext(os.path.basename(path))[0]

        with Image.open(path) as img:
            exif = read_exif(img)
            img = ImageOps.exif_transpose(img)          # honour rotation, then drop it
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((LONG_EDGE, LONG_EDGE), Image.LANCZOS)

            base = slugify(f"{collection}-{stem}" if collection else stem)
            slug, n = base, 2
            while slug in used:
                slug, n = f"{base}-{n}", n + 1
            used.add(slug)

            outfile = os.path.join(OUT, slug + ".jpg")
            # Saving a fresh image writes no EXIF: location and serial numbers
            # never reach the web copy.
            img.save(outfile, "JPEG", quality=JPEG_QUALITY,
                     optimize=True, progressive=True)
            w, h = img.size
            tone = average_tone(img)

        # What you typed beside the photograph wins, then whatever the file
        # itself knows, then what the roll declares. Film scans know nothing,
        # so for those it is simply what you typed.
        note = read_note(os.path.splitext(path)[0] + ".txt", NOTE_KEYS)
        roll = roll_note(os.path.dirname(path))
        for key in note:
            if typed(note, key) is None:
                print(f"  ! {stem}.txt: could not read '{key}: {note[key]}' — ignored")

        record = {
            "src": f"{OUT}/{slug}.jpg",
            "title": first(typed(note, "title"), title_from(stem)),
            "collection": collection,
            "w": w,
            "h": h,
            "tone": tone,
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
        photo_id = file_id(path)
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

    print("\nPage order — most recently added first:")
    for photo in photos:
        print(f"  added {photo['added'][:16].replace('T', ' ')}   {photo['title'] or '(untitled)'}")

    manifest = {"title": SITE_TITLE, "front": FRONT,
                "collections": collections, "photos": photos}
    if CONTACT_EMAIL:
        manifest["contact"] = {"heading": CONTACT_HEADING, "email": CONTACT_EMAIL}
        picture = contact_image()
        if picture:
            manifest["contact"]["image"] = picture
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print(f"\n{len(photos)} photographs across {len(collections)} collection(s).")
    print(f"Wrote {MANIFEST} and {OUT}/")
    print("Deploy: index.html, photos.json, photos/  — keep originals/ off the server.")


if __name__ == "__main__":
    build()
