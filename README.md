# Keith Merkelt Photography

A static photography site: plain HTML, no framework, no server, no database.
Published from this repo to https://pixelr0cket.github.io.

## The short version

1. Put photographs in `originals/`
2. `python3 build.py`
3. Commit and push. The site updates in about a minute.

Everything in `originals/` scrolls down one page, newest addition at the top.
That is the whole site — nothing below this line is required.

One-time setup: `pip3 install Pillow`

## Ordering the scroll

The page runs newest-first by **the day a photograph joined the site** — not
the day it was taken. Scan a negative from 1987 this afternoon and it goes to
the top, where you will actually see it, instead of sinking thirty years down
the page.

Everything added in one `build.py` run counts as one batch and stays together.
Within a batch the newest photograph comes first, so a morning's shooting reads
in a sensible order.

Once a photograph has a place it keeps it. Rebuilding changes nothing, and
renaming a file to fix its caption does not send it back to the top — arrivals
are matched on the picture itself, not its name.

To move one by hand, edit its `added` stamp in `photos.json` and rebuild:

```json
"added": "2026-08-21T10:31:24"
```

A leading number in a filename — `01-swan.jpg` — is left out of the caption, so
old numbered files read cleanly. It does not affect the order. Four digits or
more is a year and stays: `1984-summer.jpg` is captioned "1984 Summer".

## Captions

Name the file how the caption should read: `swan-at-rest.jpg` becomes "Swan At
Rest". Camera defaults like `DSC01234.jpg` are recognised and left blank rather
than shown as a serial number. To write a caption that a filename cannot hold,
type it in a note — see below.

## Typing in your own details

Film scans carry no EXIF, so there is nothing to read off them. Put a `.txt`
beside the photograph, named the same, and type what you know. For
`harbour-wall.jpg`, a `harbour-wall.txt`:

```
title: Harbour Wall, Low Tide
make: Canon
model: L3
lens: 50mm f/1.8 Serenar
aperture: f/2.8
shutter: 1/125
iso: 400
date: 2026-04-11
```

Every line is optional. Fields: `title`, `make`, `model`, `lens`, `focal`,
`aperture`, `shutter`, `iso`, `date`.

Aperture takes `2.8` or `f/2.8`; shutter takes `1/125` or `2s`; date takes
`2026-04-11`, with a time if you have one. A date with no time shows as a day.

### A whole roll at once

When every frame came off the same body, put those lines in a `camera.txt` in
the same folder instead of repeating them. It covers every photograph beside
it:

```
# Canon L3, Ilford HP5
make: Canon
model: L3
lens: 50mm f/1.8 Serenar
iso: 400
```

`camera.txt` takes `make`, `model`, `lens`, `focal` and `iso` — the things a
roll shares. Per-frame details still go in the photograph's own note.

What you typed beside a photograph wins, then the file's own EXIF, then
`camera.txt`. A field you leave out stays blank rather than being invented: a
scan with no date shows no date. `build.py` says so when a line doesn't land:

```
! harbour-wall.txt: no such field 'grain' — ignored
```

## Collections — only if you want them

You do not need these. A subfolder of `originals/` becomes a tab at the top of
the page, in folder order, alongside "All". With no subfolders there is no tab
bar at all, just the scroll.

```
originals/
  swan-at-rest.jpg      <- loose: the main scroll, and nothing else
  Nightwork/            <- a tab at the top of the page
    ...
```

A collection's photographs still appear in the main scroll — the tab filters
the same page, it is not a separate site.

## Camera marks

Each frame is signed with the camera that took it. If the make has a logo in
`logos/` the logo is used; anything else falls back to the make in plain type,
so an unrecognised camera still identifies itself.

Logos are matched by make, lowercased: an EXIF `Make` of `SONY` — or a
`make: Canon` you typed — looks for `logos/sony.png`, `logos/canon.png`. To add
a brand, drop in a transparent PNG about 40px tall named for the make.

## Folder layout

```
photography-portfolio/          <- this is the git repo root
  index.html
  build.py
  originals/                    <- your full-res exports. NEVER deployed.
    swan-at-rest.jpg
    swan-at-rest.txt            <- optional: details you type yourself
    camera.txt                  <- optional: details a whole roll shares
  photos/                       <- generated: resized web copies
    swan-at-rest-720.avif       <- the roll's copy, one per width per format
    swan-at-rest-1440.avif         (.webp and .jpg sit beside each one)
    full/
      swan-at-rest.avif         <- the copy the viewer opens
  photos.json                   <- generated: the manifest index.html reads
  logos/                        <- camera brand marks, deployed
    sony.png
    source/                     <- full-size logo artwork. NEVER deployed.
```

## Settings

Top of `build.py`:

- `SITE_TITLE` — the masthead
- `LONG_EDGE` — max served dimension, default 2000px
- `GRID_WIDTHS` — the widths the roll is cut to, default 720 and 1440
- `FORMATS` — default `avif`, `webp`, `jpg`
- `JPEG_QUALITY` / `WEBP_QUALITY` / `AVIF_QUALITY` — defaults 82 / 78 / 58

### About the roll's copies

Each photograph is cut to the width it is actually *drawn* at, in three
formats. The page offers the lot and every browser downloads exactly one: AVIF
if it can, WebP if not, JPEG otherwise — and the small copy unless the screen
is retina. So a photograph that used to arrive as one 1300px JPEG for everybody
now arrives as roughly a third of that on an ordinary screen, and sharper than
before on a retina one.

That is why `photos/` holds several hundred files for a few dozen photographs.
It is all generated: delete the folder and `build.py` writes it again.

`GRID_WIDTHS` is tied to the stylesheet. A column is never drawn wider than
702px, so 720 covers an ordinary screen and 1440 a retina one. If you change
the layout's widths in `index.html`, change these to match — and the `SIZES`
string in `index.html`, which tells the browser how wide a photograph will be
before it has seen the page.

Nothing is ever enlarged: an original smaller than 1440px simply keeps its own
width, and the page is told which widths actually exist.

## What is and isn't published

Published: `index.html`, `photos.json`, `photos/`, `logos/`

Not published: `originals/` and `logos/source/` — kept out by `.gitignore`.

The generated copies carry no embedded EXIF, so GPS coordinates, camera serial
numbers and owner fields never reach the web. The metadata shown on the page
comes from `photos.json`, which holds only the fields the design displays.

## Hosting

GitHub Pages, from the `PixelR0cket` account. The repo is named
`pixelr0cket.github.io`, which is what serves it at the bare
https://pixelr0cket.github.io — any other repo name would serve at
`https://pixelr0cket.github.io/repo-name/` instead.

Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)`.

## Working on the page itself

`index.html` looks for `photos.json` on load. Finding one, it runs as the
published site. Finding none, it falls back to a local drafting mode where you
can drag files onto the page to try layouts and captions before committing to
them.
