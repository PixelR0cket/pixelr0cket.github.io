# Keith Merkelt Photography

A static gallery. `index.html` looks for `photos.json` on load — if it finds one
it runs as the published site. If not, it falls back to a local drafting mode
where you can drag files in to try layouts.

## Folder layout

```
photography-portfolio/          <- this is the git repo root
  index.html
  build.py
  .gitignore
  originals/                    <- your full-res exports. NEVER deployed.
    swan-at-rest.jpg            <- loose file: goes in the main scroll
    Landscapes/                 <- subfolder: an optional collection tab
      ...
  photos/                       <- generated: resized web copies
  photos.json                   <- generated: the metadata manifest
```

Photographs do not have to belong to a collection. Loose files at the top level
of `originals/` appear in the main scroll and nothing else.

Each subfolder of `originals/` becomes an optional collection tab, in folder
order, shown alongside "All". With no subfolders there is no tab bar at all.

## Publishing a new photo

1. Export it into `originals/` — or into a subfolder, if it belongs to a
   collection.
2. Name the file how the caption should read — `swan-at-rest.jpg` becomes
   "Swan At Rest". Camera defaults like `DSC01234.jpg` are detected and left
   blank rather than shown as a serial number.
3. `python3 build.py`
4. Commit and push. The site updates in about a minute.

One-time setup: `pip3 install Pillow`

## Settings

Top of `build.py`:

- `SITE_TITLE` — the masthead
- `LONG_EDGE` — max served dimension, default 2000px
- `JPEG_QUALITY` — default 82

## What is and isn't published

Published: `index.html`, `photos.json`, `photos/`

Not published: `originals/` — kept out by `.gitignore`.

The generated JPEGs carry no embedded EXIF, so GPS coordinates, camera serial
numbers and owner fields never reach the web. The metadata shown on the page
comes from `photos.json`, which holds only the fields the design displays.

## Hosting

GitHub Pages, from the `PixelR0cket` account. Repo name `pixelr0cket.github.io`
serves at https://pixelr0cket.github.io. Any other repo name serves at
https://pixelr0cket.github.io/repo-name/.

Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)`.
