#!/usr/bin/env python3
"""
build.py — turn a folder of original photographs into a deployable gallery.

Folder layout:

    my-site/
      build.py
      index.html
      originals/            <- your full-res exports (NEVER uploaded)
        Landscapes/
          swan-at-dusk.jpg
        Portraits/
          ...
      photos/               <- generated: resized web copies
      photos.json           <- generated: the manifest index.html reads

Each subfolder of originals/ becomes an optional collection tab. Loose files at
the top level belong to no collection: they appear in the main scroll only.

Run:  python3 build.py
Then deploy index.html, photos.json and photos/ — leave originals/ behind.
"""

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
LONG_EDGE = 2000          # max pixel dimension served to the web
JPEG_QUALITY = 82

SRC = "originals"
OUT = "photos"
MANIFEST = "photos.json"

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
CAMERA_DEFAULT = re.compile(r"^(dsc|img|dscf|dscn|mg|imgp|gopr|pxl|photo|p)\d+$", re.I)

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


def clean(v):
    if v is None:
        return None
    s = str(v).strip().strip("\x00")
    return s or None


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
    words = re.sub(r"[_-]+", " ", stem).strip().split()
    return " ".join(w[0].upper() + w[1:] for w in words if w)


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
            for name in sorted(os.listdir(path)):
                if os.path.splitext(name)[1].lower() in EXTS:
                    foldered.append((entry, os.path.join(path, name)))
        elif os.path.splitext(entry)[1].lower() in EXTS:
            loose.append((None, path))
    return loose + foldered


def build():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)

    items = gather()
    if not items:
        raise SystemExit(f"No images found under '{SRC}/'.")

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

        shutter = as_float(exif.get("ExposureTime"))
        record = {
            "src": f"{OUT}/{slug}.jpg",
            "title": title_from(stem),
            "collection": collection,
            "w": w,
            "h": h,
            "make": clean(exif.get("Make")),
            "model": clean(exif.get("Model")),
            "lens": clean(exif.get("LensModel")),
            "focal": as_float(exif.get("FocalLength")),
            "aperture": nice_aperture(as_float(exif.get("FNumber"))),
            "shutter": shutter,
            "iso": exif.get("ISOSpeedRatings") or exif.get("PhotographicSensitivity"),
            "date": parse_date(exif),
        }
        photos.append({k: v for k, v in record.items() if v not in (None, "")})
        photos[-1].setdefault("title", "")

        label = record["title"] or stem
        print(f"  {(collection or chr(8212)):22} {label[:38]:40} {w}x{h}")

    manifest = {"title": SITE_TITLE, "collections": collections, "photos": photos}
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print(f"\n{len(photos)} photographs across {len(collections)} collection(s).")
    print(f"Wrote {MANIFEST} and {OUT}/")
    print("Deploy: index.html, photos.json, photos/  — keep originals/ off the server.")


if __name__ == "__main__":
    build()
