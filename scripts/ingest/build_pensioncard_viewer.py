"""Build a per-surname-letter HTML viewer for the pension cards.

Layout A — per-letter folder, index at bundle root:

    data/cards/viewer/
    ├── index.html               (top-level surname alphabet grid)
    ├── all.json                 (master record map for programmatic use)
    ├── lib/
    │   ├── alpine.min.js        (vendored locally; CDN-free for offline)
    │   ├── leaflet.min.js       (pan/zoom image viewer; replaced OSD 2026-07-29)
    │   ├── leaflet.css          (image-overlay CSS for Leaflet)
    │   └── leaflet-images/      (PNG sprites referenced by leaflet.css)
    └── letters/
        ├── A/
        │   ├── viewer/A.html    (surname-letter page, Alpine-driven)
        │   ├── A.json           (sidecar — same records the page embeds)
        │   └── img/             (jpegs whose pensioncard_id maps to letter A)
        ├── B/...
        └── _/                   (orphan bucket: pensioners with no initial)

Each letter page is fully self-contained — open
``letters/A/viewer/A.html`` from the HDD/USB and it can be reviewed
offline. Click any thumbnail to expand into a fullscreen Leaflet
viewer using CRS.Simple (mouse-wheel zoom, drag-pan, double-click
zoom, keyboard +/−/0/arrows). The Alpine.js layer wires the name
filter, the lightbox state, and keyboard navigation. Image paths use
``../img/`` relative to the page so per-letter extraction works
regardless of where the bundle lives on the reviewer's filesystem.

Image filenames in ``letters/{L}/img/`` are kept identical to the
flat ``data/cards/img/{pcid}__{page}.jpg`` names so the bundler
needs no filename rewriting.

History: 2026-07-29 swapped OpenSeadragon → Leaflet because OSD's
WebGL tile renderer failed in this environment (canvas stayed
transparent until the user clicked the lightbox center). Leaflet
with `CRS.Simple` draws the pension card via a single
`L.imageOverlay` + `setView(center, 0)` for fit-to-frame; no WebGL,
no tiles, no canvas drawing at all.

Usage:
    python scripts/ingest/build_pensioncard_viewer.py
    python scripts/ingest/build_pensioncard_viewer.py --letters A,B,C
    python scripts/ingest/build_pensioncard_viewer.py --out-dir path
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Source inputs (defaults match the digital-prairie run)
DEFAULT_INPUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners.json"
)
DEFAULT_REPORT = Path("data/cards/enrichment_report.json")
DEFAULT_IMG_DIR = Path("data/cards/img")
DEFAULT_APPLICATIONS_DIR = Path("data/cards/applications")
DEFAULT_APPLICATIONS_SUMMARY = Path(
    "data/cards/download_summary_applications.json"
)
DEFAULT_OUT_DIR = Path("data/cards/viewer")
# Vendored Alpine.js + Leaflet — copied into <out>/lib/ so the
# viewer is fully offline-capable.
# History: 2026-07-29 swapped from OpenSeadragon → Leaflet because
# OSD's WebGL tile renderer was failing ("Error creating texture in
# WebGL") in this environment, leaving the pension-card image
# invisible until the user clicked the lightbox center. Leaflet
# with `CRS.Simple` + a single `L.imageOverlay` provides the same
# pan/zoom UX on a plain <img> — no WebGL, no canvas, no
# tile-source plumbing. The `leaflet-images/` folder is still copied
# into the bundle because `leaflet.css` references
# `images/marker-icon.png` etc; we don't use markers in our viewer
# but the CSS may still try to load them, so ship them to avoid 404s.
VENDOR_DIR = _SCRIPTS_DIR / "vendor"
VENDORED_LIBS = ["alpine.min.js", "leaflet.min.js", "leaflet.css"]
VENDORED_LEAFLET_IMAGES_DIR = VENDOR_DIR / "leaflet-images"
# Legacy OSD sprite dir + prefix (kept so old bundles extracted by
# an earlier version still resolve correctly; new builds don't copy
# them).
VENDORED_OSD_SPRITE_DIR = VENDOR_DIR / "openseadragon-images"
VENDORED_OSD_PREFIX_REL = "lib/openseadragon-images/"

ALPHABET = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
ORPHAN_LETTER = "_"


def load_data(args, log):
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))

    enriched_by_pcid = {}
    for c in report.get("changed", []):
        pcid = c.get("pensioncard_id")
        if pcid is not None:
            enriched_by_pcid[int(pcid)] = c

    imgs_by_pcid = defaultdict(list)
    for img in args.img_dir.glob("*.jpg"):
        try:
            pcid = int(img.stem.split("__")[0])
            imgs_by_pcid[pcid].append(img.name)
        except Exception:
            continue

    # Application images: keyed by pensioner_id (the digitalprairie
    # `id` field, NOT pensioncard_id). The downloader writes
    # `data/cards/applications/<pensioner_id>.jpg`. Some pensioners
    # have no application record at digitalprairie (~158 of 7709
    # returned 404 in the L4 download run); those just won't have
    # an application_image field, and the viewer will show a
    # "no application" badge for them.
    app_by_pensioner_id: dict[int, str] = {}
    if args.applications_dir.exists():
        for img in args.applications_dir.glob("*.jpg"):
            try:
                pid = int(img.stem)
                app_by_pensioner_id[pid] = img.name
            except ValueError:
                continue
    log.info(
        "applications: %d jpgs on disk (%d missing-404 expected)",
        len(app_by_pensioner_id),
        max(0, len(rows) - len(app_by_pensioner_id)),
    )

    pcid_to_pensioner = {}
    for r in rows:
        pcid = r.get("pensioncard_id")
        if pcid is None:
            continue
        pcid_to_pensioner[int(pcid)] = r

    records = []
    for pcid, pensioner in pcid_to_pensioner.items():
        images = imgs_by_pcid.get(pcid, [])
        if not images and pcid not in enriched_by_pcid:
            continue
        enr = enriched_by_pcid.get(pcid)
        last_name = (pensioner.get("last_name") or "").strip()
        raw = (pensioner.get("name_raw") or "").strip()
        pid = pensioner.get("id")
        app_img_name = app_by_pensioner_id.get(pid) if pid is not None else None
        
        candidate = ""
        if last_name:
            candidate = last_name
        elif raw and "," in raw:
            candidate = raw.split(",", 1)[0].strip()
        elif raw:
            candidate = raw.split()[0].strip()
        
        title_only = {"Mrs", "Mr", "Miss", "Dr", "Sir", "Madam"}
        first_word = candidate.split()[0] if candidate else ""
        if not candidate or not candidate[0].isalpha() \
                or first_word.rstrip(".") in title_only:
            letter = ORPHAN_LETTER
        else:
            letter = candidate[0].upper()
            if letter not in ALPHABET:
                letter = ORPHAN_LETTER
        records.append({
            "pensioncard_id": pcid,
            "pensioner_id": pid,
            "letter": letter,
            "last_name": last_name,
            "first_name": pensioner.get("first_name", ""),
            "name_raw": raw,
            "spouse_name_raw": pensioner.get("spouse_name_raw", ""),
            "company": pensioner.get("company", ""),
            "regiment": pensioner.get("regiment", ""),
            "application_number": pensioner.get("application_number", ""),
            "pension_number": pensioner.get("pension_number", ""),
            "death_year": enr.get("death_year", "") if enr else "",
            "death_date_iso": enr.get("death_date_iso", "") if enr else "",
            "near_death_keyword": enr.get("near_death_keyword", False) if enr else False,
            "mentions_soldier_name": enr.get("mentions_soldier_name", False) if enr else False,
            "is_widow_card": enr.get("is_widow_card", False) if enr else bool(pensioner.get("spouse_name_raw", "").strip()),
            "images": sorted(images),
            
            "application_image": app_img_name,
            "application_available": app_img_name is not None,
        })

    log.info("loaded %d pensioner records with images or death data",
             len(records))
    return records


def group_by_letter(records):
    by_letter = defaultdict(list)
    for r in records:
        by_letter[r["letter"]].append(r)
    for letter in by_letter:
        by_letter[letter].sort(
            key=lambda r: (r["last_name"].lower(), r["first_name"].lower())
        )
    return by_letter


# ---------------------------------------------------------------------
# Shared HTML chrome (header nav, etc.)
# ---------------------------------------------------------------------

INDEX_CSS = """\
:root {
  --bg: #f5f5f0; --paper: #fff; --ink: #1e293b; --muted: #7f8c8d;
  --line: #ccc; --line-strong: #1e293b; --accent: #2c3e50;
  --accent-dark: #1a252f; --radius: 4px;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       margin: 0; padding: 0; background: var(--bg); color: var(--ink);
       line-height: 1.5; }
header { background: var(--accent); color: white; padding: 1em 1.5em;
         display: flex; justify-content: space-between; align-items: center;
         position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
header h1 { margin: 0; font-size: 1.25em; font-weight: 600; }
header .nav { display: flex; gap: 1em; align-items: center; }
header .nav a { color: white; text-decoration: none; font-size: 0.95em;
                padding: 0.25em 0.5em; border-radius: 3px; }
header .nav a:hover { background: rgba(255,255,255,0.15); }
main { padding: 1.5em; max-width: 1400px; margin: 0 auto; }
button { font: inherit; cursor: pointer; }
input { font: inherit; }
.letters-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.75em;
}
.letter-card {
  background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 1em; text-decoration: none; color: var(--ink);
  display: flex; flex-direction: column; align-items: center; gap: 0.25em;
  transition: transform 0.1s ease, border-color 0.1s ease;
}
.letter-card:hover { transform: translateY(-2px); border-color: var(--accent);
                     box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.letter-card .l { font-size: 2em; font-weight: 700; line-height: 1; color: var(--accent); }
.letter-card .meta { font-size: 0.8em; color: var(--muted); text-align: center; }
.letter-card.disabled { opacity: 0.35; cursor: not-allowed; }
.letter-card.disabled:hover { transform: none; border-color: var(--line); box-shadow: none; }
.summary-card { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
                padding: 1em 1.25em; margin-bottom: 1.5em; }
.summary-card h2 { margin: 0 0 0.25em; font-size: 1.1em; }
.summary-card .stat { font-size: 2em; font-weight: 700; color: var(--accent); }
"""

LETTER_CSS = INDEX_CSS + """\
.controls { margin: 1em 0; display: flex; gap: 1em; align-items: center; flex-wrap: wrap; }
.controls input[type='text'] {
  flex: 1; min-width: 18em; padding: 0.5em 0.75em;
  border: 1px solid var(--line); border-radius: var(--radius);
}
.controls .hint { font-size: 0.85em; color: var(--muted); }
.records { flex-direction: column; gap: 0.8em; }
.record {
  background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 1em; display: grid; grid-template-columns: 320px 1fr; gap: 1.25em;
}
.record .thumb-stack { display: flex; flex-direction: column; gap: 0.4em; }
.record .thumb {
  display: block; width: 100%; max-width: 320px; height: 220px;
  object-fit: contain; background: #fafafa;
  border: 1px solid var(--line); border-radius: 3px; cursor: zoom-in;
  transition: transform 0.1s ease, border-color 0.1s ease;
}
.record .thumb:hover { transform: scale(1.02); border-color: var(--accent); }
.record .name { font-size: 1.15em; font-weight: 600; margin: 0 0 0.25em; }
.record .widow-tag { display: inline-block; background: #e74c3c; color: white;
                     font-size: 0.7em; padding: 0.1em 0.5em; border-radius: 3px;
                     margin-left: 0.5em; vertical-align: middle; }
.record .info { font-size: 0.9em; color: #555; margin: 0.25em 0; }
.record .death-date { margin-top: 0.5em; padding: 0.4em 0.6em;
                      border-radius: 3px; display: inline-block; font-size: 0.95em; }
.record .death-date.has-date { background: #27ae60; color: white; font-weight: 600; }
.record .death-date.has-date.kw { background: #229954; }
.record .death-date.has-date.soldier { background: #1e8449; }
.record .death-date.no-date { background: #ecf0f1; color: var(--muted); font-style: italic; }
.record .markers { font-size: 0.8em; color: var(--muted); margin-top: 0.3em; }
.record .marker { display: inline-block; margin-right: 0.5em;
                  padding: 0.1em 0.4em; border-radius: 3px; background: #ecf0f1; }
.record .marker.soldier { background: #d5f5e3; color: #196f3d; }
.record .marker.kw { background: #d6eaf8; color: #1f618d; }
.record .marker.fallback { background: #fdebd0; color: #935116; }
.empty-state { padding: 3em; text-align: center; color: var(--muted); }

/* OpenSeadragon lightbox overlay */
.lightbox-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0, 0, 0, 0.92);
  display: flex; align-items: stretch; justify-content: stretch;
  /* let the absolutely-positioned canvas child participate in
     flex sizing — without this OSD can mount with 0x0 dimensions
     if it runs before layout settles, leaving the image invisible
     until the first user click triggers a re-measure. */
}
.lightbox-overlay[hidden] { display: none; }
.lightbox-toolbar {
  position: absolute; top: 0; left: 0; right: 0;
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.75em 1em; background: rgba(0, 0, 0, 0.6);
  color: white; font-size: 0.9em; z-index: 10;
}
.lightbox-toolbar .title { font-weight: 600; }
.lightbox-toolbar button {
  background: rgba(255, 255, 255, 0.1); color: white; border: 1px solid rgba(255, 255, 255, 0.25);
  padding: 0.35em 0.7em; border-radius: 3px; margin-left: 0.5em;
}
.lightbox-toolbar button:hover { background: rgba(255, 255, 255, 0.2); }
.lightbox-canvas {
  /* Leaflet measures the container at init; the absolute + vw/vh
     sizing gives it a definite box the moment the overlay opens.
     Parent (.lightbox-overlay) is position:fixed inset:0, so vh/vw
     tracks the visible viewport even when the toolbar/counter
     shrink the visible area. */
  position: absolute; inset: 0; width: 100vw; height: 100vh;
}
.lightbox-counter {
  position: absolute; bottom: 0; left: 0; right: 0; padding: 0.6em;
  background: rgba(0, 0, 0, 0.5); color: white;
  text-align: center; font-size: 0.85em; z-index: 10;
}
.lightbox-counter kbd {
  background: rgba(255,255,255,0.15); padding: 0.1em 0.4em; border-radius: 3px;
  margin: 0 0.1em; font-family: monospace;
}
.lightbox-toolbar .view-toggle {
  display: inline-flex; gap: 0.4em; align-items: center;
  margin: 0 1em;
}
.lightbox-toolbar .view-toggle button {
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.2);
  color: white; padding: 0.3em 0.7em; border-radius: 3px;
  font-size: 0.85em; margin-left: 0;
}
.lightbox-toolbar .view-toggle button.active {
  background: rgba(255,255,255,0.25); border-color: rgba(255,255,255,0.6);
  font-weight: 600;
}
.lightbox-toolbar .view-toggle button:disabled {
  opacity: 0.35; cursor: not-allowed;
}
.lightbox-toolbar .view-toggle button kbd {
  background: rgba(255,255,255,0.15); padding: 0.05em 0.3em; border-radius: 2px;
  margin-left: 0.3em; font-family: monospace; font-size: 0.85em;
}

.record .app-badge {
  display: inline-block; font-size: 0.7em; padding: 0.1em 0.5em;
  border-radius: 3px; margin-left: 0.5em; vertical-align: middle;
}
.record .app-badge.has {
  background: #3498db; color: white;
}
.record .app-badge.missing {
  background: #ecf0f1; color: var(--muted); font-style: italic;
}
"""

INDEX_HEADER_HTML = """\
<header>
  <h1>Pension Card Viewer</h1>
  <nav class="nav">
    <a href="all.json" target="_blank">all.json</a>
  </nav>
</header>
"""

LETTER_HEADER_HTML = """\
<header>
  <h1>Surnames: {LETTER}</h1>
  <nav class="nav">
    <a href="{HREF_INDEX}">\u2190 Index</a>
    <a href="{SAFE_LETTER}.json" target="_blank">JSON</a>
    {PREV_LETTER_LINK}{NEXT_LETTER_LINK}
  </nav>
</header>
"""


# ---------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------

INDEX_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pension Cards \u2014 Index ({TOTAL} cards, {LETTERS} letters)</title>
<style>{INDEX_CSS}</style>
</head>
<body x-data="letterApp()" x-init="init()" x-cloak>
{INDEX_HEADER}
<main>
  <div class="summary-card">
    <h2>Browse by surname letter</h2>
    <div class="stat" x-text="totalCards"></div>
    <div>records across <span x-text="presentLetters"></span> letters
          (&times; front/back images &mdash; click any letter to open its
          offline viewer).</div>
  </div>
  <div class="letters-grid">
    <template x-for="card in cards" :key="card.letter">
      <a class="letter-card"
         x-bind:class="card.disabled ? 'letter-card disabled' : 'letter-card'"
         x-bind:href="card.disabled ? '#' : card.href"
         x-bind:aria-disabled="card.disabled">
        <div class="l" x-text="card.letter"></div>
        <div class="meta" x-text="card.meta"></div>
      </a>
    </template>
  </div>
</main>
<script src="lib/alpine.min.js" defer></script>
<script>
function letterApp() {{
  return {{
    // Letter cards are filled in from a <script type="application/json"> block
    cards: window.__LETTERS__,
    init() {{
      this.totalCards = this.cards.reduce((s, c) => s + c.count, 0);
      this.presentLetters = this.cards.filter(c => !c.disabled).length;
    }},
    totalCards: 0,
    presentLetters: 0,
  }};
}}
</script>
</body>
</html>
"""

LETTER_PAGE_TEMPLATE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pension Cards \u2014 Letter {LETTER} ({COUNT} cards)</title>
<style>{CSS}</style>
<script>
  // Records are injected into this JSON block at build time (see
  // build_pensioncard_viewer.py:render_letter). The Alpine app
  // factory below reads from window.__PCIDS__ once Alpine evaluates
  // x-data. Keeping the JSON in a <script type=application/json>
  // block avoids HTML-attribute quoting hell (the records list
  // is a JSON array with "double quotes" inside it, which would
  // terminate an x-data="…" attribute mid-string).
  window.__PCIDS__ = __RECORDS__;
</script>
</head>
<body x-data="letterApp()" x-init="init()" x-cloak
      @keydown.window="handleKey($event)">
{HEADER}
<main>
  <div class="controls">
    <input type="text" x-model="filter"
           placeholder="Filter by name, company, regiment..."
           aria-label="Filter records">
    <span class="hint"
          x-text="visible.length + ' / ' + records.length + ' shown'"></span>
    <button @click="filter = ''" x-show="filter">Clear</button>
    <button @click="prevCard()" :disabled="visible.length === 0">\u2191 Prev</button>
    <button @click="nextCard()" :disabled="visible.length === 0">\u2193 Next</button>
  </div>
  <div class="records" x-show.important="visible.length > 0">
    <template x-for="rec in visible" :key="rec.pensioncard_id">
      <div class="record" :data-pcid="rec.pensioncard_id">
        <div class="thumb-stack">
          <template x-for="(img, idx) in rec.images" :key="img">
            <img class="thumb"
                 :src="'../img/' + img"
                 :alt="rec.name_raw + ' (image ' + (idx + 1) + ')'"
                 loading="lazy"
                 @click="openLightbox(rec, idx)">
          </template>
        </div>
        <div>
          <div class="name">
            <span x-text="rec.name_raw"></span>
            <template x-if="rec.application_available">
              <span class="app-badge has" title="Original pension application on file">App</span>
            </template>
            <template x-if="!rec.application_available && rec.pensioner_id !== undefined">
              <span class="app-badge missing" title="No application found at digitalprairie">no app</span>
            </template>
          </div>
          <div class="info">
            <template x-for="line in infoLines(rec)" :key="line"><div x-text="line"></div></template>
          </div>
          <div :class="'death-date ' + deathClass(rec)"
               x-text="deathLabel(rec)"></div>
          <div class="markers">
            <template x-if="rec.mentions_soldier_name">
              <span class="marker soldier">mentions soldier name</span>
            </template>
            <template x-if="rec.near_death_keyword">
              <span class="marker kw">death keyword</span>
            </template>
            <template x-if="rec.is_widow_card">
              <span class="marker" style="background:#f5d7d7;color:#922b21;">widow card</span>
            </template>
          </div>
        </div>
      </div>
    </template>
  </div>
  <div class="empty-state" x-show.important="visible.length === 0">
    No records match <strong x-text="filter"></strong>.
  </div>
</main>

<!-- Lightbox overlay -->
<div class="lightbox-overlay" x-show.important="lightbox.open"
     @click.self="closeLightbox()"
     x-cloak>
  <div class="lightbox-toolbar" @click.stop>
    <span class="title" x-text="lightboxTitle()"></span>
    <span class="view-toggle">
      <button @click="switchView('card')"
              :class="lightbox.view === 'card' ? 'active' : ''"
              :disabled="!lightbox.open || !lightbox.rec || !lightbox.rec.images.length"
              title="Card front/back (c)">
        Card <kbd>c</kbd>
      </button>
      <button @click="switchView('application')"
              :class="lightbox.view === 'application' ? 'active' : ''"
              :disabled="!hasApplication(lightbox.rec)"
              title="Application form (a)">
        Application <kbd>a</kbd>
      </button>
    </span>
    <span>
      <button @click="zoomOut()" title="Zoom out (-)">\u2212</button>
      <button @click="zoomIn()" title="Zoom in (+)">+</button>
      <button @click="zoomReset()" title="Reset zoom (0)">Reset</button>
      <button @click="rotate()" title="Rotate (r)">\u21BB</button>
      <button @click="screenshot()" title="Download PNG (s)">\u2193 PNG</button>
      <button @click="fullscreen()" title="Fullscreen (f)">\u26F6</button>
      <button @click="closeLightbox()" title="Close (esc)">\u2715</button>
    </span>
  </div>
  <div id="leaflet-viewer" class="lightbox-canvas" @click.stop></div>
  <div class="lightbox-counter" @click.stop>
    <span x-show="lightbox.view === 'card'">
      Image <span x-text="(lightbox.idx ?? 0) + 1"></span>
      of <span x-text="lightbox.total"></span> &mdash;
    </span>
    <span x-show="lightbox.view === 'application'">
      Original application form &mdash;
    </span>
    <kbd>+</kbd>/<kbd>\u2212</kbd>/<kbd>0</kbd> zoom,
    <kbd>f</kbd> fullscreen, <kbd>r</kbd> rotate,
    <kbd>\u2190</kbd>/<kbd>\u2192</kbd> step,
    <kbd>s</kbd> save PNG,
    <kbd>c</kbd> card,
    <kbd>a</kbd> application,
    <kbd>esc</kbd> close
  </div>
</div>

<script src="app.js"></script>
<script src="../../../lib/alpine.min.js" defer></script>
<script src="../../../lib/leaflet.min.js"></script>
<link rel="stylesheet" href="../../../lib/leaflet.css">
</body>
</html>
"""

LETTER_APP_JS = """\
// Alpine + Leaflet viewer app for one letter page.
// Reads the per-letter record list from window.__PCIDS__, which the
// build script sets inside a <script> block in <head>. Keeping
// records out of the x-data attribute sidesteps the
// unescaped-quotes bug that broke the previous viewer build.
//
// History: 2026-07-29 swapped OpenSeadragon → Leaflet (see
// build_pensioncard_viewer.py header for why). Leaflet with
// CRS.Simple draws the pension card via a single L.imageOverlay
// + map.setView(center, zoom) for fit-to-frame. No WebGL, no
// tile-source plumbing, no canvas. Pan/zoom is built into Leaflet's
// map controls.
function letterApp() {
  return {
    records: (window.__PCIDS__ || []),
    filter: '',
    visible: [],
    lightbox: {open: false, idx: null, total: 0, rec: null,
                view: 'card'},
    map: null,
    overlay: null,
    init() {
      this.recomputeVisible();
      this.$watch('filter', () => this.recomputeVisible());
    },
    recomputeVisible() {
      const q = (this.filter || '').toLowerCase().trim();
      if (!q) {
        this.visible = this.records;
        return;
      }
      this.visible = this.records.filter((r) => {
        return (r.name_raw || '').toLowerCase().includes(q)
          || (r.spouse_name_raw || '').toLowerCase().includes(q)
          || (r.company || '').toLowerCase().includes(q)
          || (r.regiment || '').toLowerCase().includes(q);
      });
    },
    infoLines(rec) {
      const out = [];
      if (rec.company) out.push('Company ' + rec.company);
      if (rec.regiment) out.push('Regiment ' + rec.regiment);
      if (rec.application_number) out.push('App # ' + rec.application_number);
      if (rec.pension_number) out.push('Pension # ' + rec.pension_number);
      if (rec.spouse_name_raw) out.push('Spouse: ' + rec.spouse_name_raw);
      return out;
    },
    deathClass(rec) {
      if (!rec.death_year && !rec.death_date_iso) return 'no-date';
      let cls = 'has-date';
      if (rec.mentions_soldier_name) cls += ' soldier';
      else if (rec.near_death_keyword) cls += ' kw';
      return cls;
    },
    deathLabel(rec) {
      if (rec.death_date_iso || rec.death_year) {
        return 'Death: ' + (rec.death_date_iso || rec.death_year);
      }
      return 'No death date extracted';
    },
    openLightbox(rec, idx) {
      this.lightbox = {open: true, idx: idx, total: rec.images.length,
                       rec: rec};
      // Wait for Alpine's reactive update + a paint frame so the
      // overlay has laid out with non-zero dimensions, then mount
      // Leaflet into the container. (Leaflet needs the container to
      // have a size before it computes its initial center; unlike
      // OSD, Leaflet handles resize events gracefully, so a single
      // rAF is sufficient.)
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          this.mountLeaflet();
        });
      });
    },
    lightboxTitle() {
      const r = this.lightbox.rec;
      if (!r) return '';
      const viewLabel = this.lightbox.view === 'application'
        ? ' \u2014 APPLICATION'
        : ' \u2014 pensioncard #' + r.pensioncard_id;
      return r.name_raw + viewLabel;
    },
    hasApplication(rec) {
      return !!(rec && rec.application_available && rec.application_image);
    },
    switchView(target) {
      // Toggle between 'card' (front/back of the pension card) and
      // 'application' (the original pension request form). Issue
      // #140 wires both into the lightbox so a reviewer can verify
      // that the application name matches the card name, that the
      // filing dates line up, etc. - all without leaving the
      // lightbox.
      const r = this.lightbox.rec;
      if (!r) return;
      if (target === 'application' && !this.hasApplication(r)) return;
      if (target === this.lightbox.view) return;
      this.lightbox.view = target;
      // Reset zoom + re-mount Leaflet on the new image.
      this.mountLeaflet();
    },
    mountLeaflet() {
      const r = this.lightbox.rec;
      const idx = this.lightbox.idx;
      if (!r) return;
      
      let imgPath;
      if (this.lightbox.view === 'application' && this.hasApplication(r)) {
        imgPath = '../applications/' + r.application_image;
      } else {
        imgPath = '../img/' + r.images[idx];
      }

      // Tear down any previous map (e.g. user re-opened while one
      // was still alive) before building a new one. Leaflet maps
      // own their DOM container, so reuse requires explicit remove.
      if (this.map) {
        this.map.remove();
        this.map = null;
        this.overlay = null;
      }
      // CRS.Simple treats pixel coordinates as map units. The
      // bounds object below is sized to the actual image dimensions
      // (load via a hidden <img> so Leaflet can fit-to-frame with
      // the correct aspect ratio).
      const imgEl = new Image();
      imgEl.onload = () => {
        const w = imgEl.naturalWidth;
        const h = imgEl.naturalHeight;
        const bounds = [[0, 0], [h, w]];
        this.map = L.map('leaflet-viewer', {
          crs: L.CRS.Simple,
          minZoom: -3,
          maxZoom: 4,
          zoomSnap: 0.25,
          zoomDelta: 0.5,
          wheelDebounceTime: 20,
          wheelPxPerZoomLevel: 80,
          attributionControl: false,
          zoomControl: false,
        });
        this.overlay = L.imageOverlay(imgPath, bounds).addTo(this.map);
        this.map.fitBounds(bounds);
        this.map.setMaxBounds([
          [-h * 0.5, -w * 0.5],
          [h * 1.5, w * 1.5],
        ]);
      };
      imgEl.onerror = () => {
        console.error('[lightbox] failed to load image:', imgPath);
      };
      imgEl.src = imgPath;
    },
    closeLightbox() {
      if (this.map) {
        this.map.remove();
        this.map = null;
        this.overlay = null;
      }
      this.lightbox = {open: false, idx: null, total: 0, rec: null,
                       view: 'card'};
    },
    step(delta) {
      const r = this.lightbox.rec;
      if (!r) return;
      let idx = (this.lightbox.idx + delta + r.images.length) % r.images.length;
      this.openLightbox(r, idx);
    },
    zoomIn() {
      if (this.map) this.map.zoomIn(0.5);
    },
    zoomOut() {
      if (this.map) this.map.zoomOut(0.5);
    },
    zoomReset() {
      // Re-fit to image bounds (Leaflet has no goHome equivalent)
      if (!this.map || !this.overlay) return;
      const b = this.overlay.getBounds();
      this.map.fitBounds(b);
    },
    rotate() {
      // Leaflet's CSS transform-based rotation isn't built-in;
      // apply via inline style on the overlay's <img>.
      if (!this.overlay) return;
      const img = this.overlay.getElement();
      const cur = (parseFloat(img.dataset.rotation) || 0) % 360;
      const next = cur + 90;
      img.dataset.rotation = next;
      img.style.transform = `rotate(${next}deg)`;
    },
    fullscreen() {
      const el = document.querySelector('.lightbox-overlay');
      if (document.fullscreenElement) { document.exitFullscreen(); }
      else if (el.requestFullscreen) { el.requestFullscreen(); }
    },
    screenshot() {
      // Leaflet renders via <img>, so we can fetch the JPEG directly
      // (no canvas conversion needed). Just download the image URL.
      if (!this.overlay) return;
      const url = this.overlay.getElement().src;
      const r = this.lightbox.rec;
      const safe = (r.name_raw || 'pension-' + r.pensioncard_id)
        .replace(/[^a-z0-9]+/gi, '_').toLowerCase();
      const a = document.createElement('a');
      a.href = url;
      a.download = safe + '_' + (this.lightbox.idx + 1) + '.jpg';
      document.body.appendChild(a); a.click();
      setTimeout(() => document.body.removeChild(a), 0);
    },
    handleKey(ev) {
      if (!this.lightbox.open) return;
      // Ignore typing in the filter input
      if (ev.target && (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA')) {
        return;
      }
      switch (ev.key) {
        case '+': case '=': this.zoomIn(); break;
        case '-': case '_': this.zoomOut(); break;
        case '0': this.zoomReset(); break;
        case 'r': case 'R': this.rotate(); break;
        case 'ArrowLeft':  this.step(-1); break;
        case 'ArrowRight': this.step(1); break;
        case 'f': case 'F': this.fullscreen(); break;
        case 's': case 'S': this.screenshot(); break;
        case 'c': case 'C': this.switchView('card'); break;
        case 'a': case 'A': this.switchView('application'); break;
        case 'Escape': this.closeLightbox(); break;
      }
    },
    nextCard() {
      // Scroll to next matching card (used by the on-page prev/next
      // buttons for navigating without the lightbox).
      const cards = document.querySelectorAll('.record');
      for (let i = 0; i < cards.length; i++) {
        if (cards[i].getBoundingClientRect().bottom > window.innerHeight) {
          cards[i].scrollIntoView({behavior: 'smooth', block: 'start'});
          return;
        }
      }
    },
    prevCard() {
      const cards = document.querySelectorAll('.record');
      for (let i = cards.length - 1; i >= 0; i--) {
        if (cards[i].getBoundingClientRect().top < 0) {
          cards[i].scrollIntoView({behavior: 'smooth', block: 'start'});
          return;
        }
      }
    },
  };
}
"""

def safe_letter_filename(letter: str) -> str:
    return letter if letter.isalnum() else "_"


def render_index(by_letter, total, rendered, bundle_root: Path):
    cards = []
    for letter in ALPHABET + [ORPHAN_LETTER]:
        recs = by_letter.get(letter, [])
        with_date = sum(1 for r in recs if r.get("death_year"))
        href = f"letters/{safe_letter_filename(letter)}/viewer/{safe_letter_filename(letter)}.html"
        cards.append({
            "letter": letter,
            "href": href,
            "count": len(recs),
            "with_date": with_date,
            "disabled": letter not in rendered,
            "meta": f"{len(recs)} cards\n{with_date} dated" if recs else "no records",
        })
    page = INDEX_PAGE_TEMPLATE.format(
        INDEX_CSS=INDEX_CSS,
        INDEX_HEADER=INDEX_HEADER_HTML,
        TOTAL=total,
        LETTERS=len(rendered),
        CARDS_JSON=json.dumps(cards, ensure_ascii=False),
    )
    # Inline the card array as window.__LETTERS__ so Alpine sees it.
    page = page.replace("window.__LETTERS__",
                        "JSON.parse(" + json.dumps(json.dumps(cards)) + ")")
    out = bundle_root / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


def render_letter(letter, recs, by_letter):
    sorted_letters = sorted(by_letter.keys())
    idx = sorted_letters.index(letter) if letter in sorted_letters else -1
    prev_html = ""
    next_html = ""
    if idx > 0:
        prev = sorted_letters[idx - 1]
        prev_html = f'<a href="../../../{safe_letter_filename(prev)}/viewer/{safe_letter_filename(prev)}.html">\u2190 {prev}</a>'
    if idx >= 0 and idx < len(sorted_letters) - 1:
        nxt = sorted_letters[idx + 1]
        next_html = f'<a href="../../../{safe_letter_filename(nxt)}/viewer/{safe_letter_filename(nxt)}.html">{nxt} \u2192</a>'

    # Format the header chrome first (it has its own {PLACEHOLDERS}
    # that aren't related to the page template).
    header_html = LETTER_HEADER_HTML.format(
        LETTER=letter,
        HREF_INDEX="../../../index.html",
        SAFE_LETTER=safe_letter_filename(letter),
        PREV_LETTER_LINK=prev_html,
        NEXT_LETTER_LINK=next_html,
    )
    # Render with .format using only its own {PLACEHOLDERS}; the
    # Alpine {records: __RECORDS__} expression is filled in via
    # .replace() afterward because it contains curly braces that
    # conflict with str.format.
    replacements = {
        "LETTER": letter,
        "COUNT": len(recs),
        "CSS": LETTER_CSS,
        "HEADER": header_html,
    }
    head = LETTER_PAGE_TEMPLATE_HEAD.format(**replacements)
    head = head.replace("__RECORDS__", json.dumps(recs, ensure_ascii=False))
    return head


def place_letter_files(
    out_root: Path,
    letter: str,
    html: str,
    records: list[dict],
    img_dir: Path,
    applications_dir: Path = DEFAULT_APPLICATIONS_DIR,
):
    """Write letters/{L}/viewer/{L}.html + sidecar JSON. Returns
    dict of (pcid, page) basenames that should be copied into
    letters/{L}/img/."""
    safe = safe_letter_filename(letter)
    letter_dir = out_root / "letters" / safe
    (letter_dir / "viewer").mkdir(parents=True, exist_ok=True)
    (letter_dir / "img").mkdir(parents=True, exist_ok=True)
    (letter_dir / "applications").mkdir(parents=True, exist_ok=True)
    (letter_dir / "viewer" / f"{safe}.html").write_text(html, encoding="utf-8")
    (letter_dir / "viewer" / "app.js").write_text(LETTER_APP_JS, encoding="utf-8")
    (letter_dir / f"{safe}.json").write_text(
        json.dumps({
            "letter": letter,
            "count": len(records),
            "with_death_date": sum(1 for r in records if r.get("death_year")),
            "with_application": sum(
                1 for r in records if r.get("application_available")
            ),
            "records": records,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # Copy images
    copied = []
    seen = set()
    for rec in records:
        pcid = rec["pensioncard_id"]
        for name in rec["images"]:
            if name in seen:
                continue
            seen.add(name)
            src = img_dir / name
            dst = letter_dir / "img" / name
            if src.exists():
                shutil.copy2(src, dst)
                copied.append(name)

    
    apps_copied = []
    apps_seen = set()
    for rec in records:
        app_name = rec.get("application_image")
        if not app_name or app_name in apps_seen:
            continue
        apps_seen.add(app_name)
        src = applications_dir / app_name
        dst = letter_dir / "applications" / app_name
        if src.exists():
            shutil.copy2(src, dst)
            apps_copied.append(app_name)
    return copied, apps_copied


def vendor_libs(out_root: Path, log: logging.Logger):
    """Copy vendored Alpine + Leaflet (+ leaflet-images/) into
    <out>/lib/."""
    lib_dir = out_root / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    for name in VENDORED_LIBS:
        src = VENDOR_DIR / name
        dst = lib_dir / name
        if not src.exists():
            log.warning("missing vendor lib: %s (viewer will load CDN)", src)
            continue
        shutil.copy2(src, dst)
        log.info("vendored %s -> %s (%s)", src.name, dst,
                 human_bytes(dst.stat().st_size))

    # Leaflet CSS references marker-icon.png / layers.png via
    # `url(images/...)`. We don't actually use markers in our
    # viewer (CRS.Simple + imageOverlay only), but the CSS may
    # still try to fetch them at parse time, so ship them to avoid
    # console 404s in offline review.
    if VENDORED_LEAFLET_IMAGES_DIR.exists():
        img_dst = lib_dir / "leaflet-images"
        img_dst.mkdir(parents=True, exist_ok=True)
        n_copied = 0
        for src in VENDORED_LEAFLET_IMAGES_DIR.glob("*.png"):
            shutil.copy2(src, img_dst / src.name)
            n_copied += 1
        log.info("vendored leaflet-images -> %s (%d PNGs)",
                 img_dst, n_copied)
    else:
        log.warning("missing leaflet-images folder: %s "
                    "(CSS may 404 on marker sprites)", VENDORED_LEAFLET_IMAGES_DIR)
    return lib_dir


def write_all_json(out_root: Path, by_letter, total, rendered):
    payload = {
        "total_pensioners": total,
        "rendered_letters": sorted(rendered),
        "by_letter": {
            letter: [
                {"pensioncard_id": r["pensioncard_id"],
                 "name_raw": r["name_raw"],
                 "death_date_iso": r["death_date_iso"]}
                for r in recs
            ]
            for letter, recs in by_letter.items()
        },
    }
    (out_root / "all.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_letter_index_jsons(out_root: Path, by_letter, total, rendered_letters):
    """Per-letter sidecar JSONs at the bundle root for consumers who
    only want JSON (no HTML). Each is the same payload as the
    letters/{L}/{L}.json file."""
    for letter, recs in by_letter.items():
        safe = safe_letter_filename(letter)
        path = out_root / "letters" / safe / f"{safe}.json"
        if path.exists():
            continue
        path.write_text(
            json.dumps({
                "letter": letter, "count": len(recs),
                "with_death_date": sum(1 for r in recs if r.get("death_year")),
                "records": recs,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT_JSON)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--img-dir", type=Path, default=DEFAULT_IMG_DIR)
    ap.add_argument(
        "--applications-dir", type=Path,
        default=DEFAULT_APPLICATIONS_DIR,
        help="directory of application jpegs (one per pensioner, "
             "named <pensioner_id>.jpg); issue #140 wires these into "
             "the viewer so reviewers can flip between card and "
             "application inside the same lightbox.",
    )
    ap.add_argument(
        "--applications-summary", type=Path,
        default=DEFAULT_APPLICATIONS_SUMMARY,
        help="JSON summary written by download_application_images.py; "
             "ships inside the bundle so reviewers can see which "
             "pensioners are missing applications without re-querying "
             "digitalprairie.",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--letters", type=str, default="",
                    help="comma-separated subset of letters to render (default: all)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("viewer")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    # Clear stale artifacts from previous runs:
    # - letters/ subdir (regenerated)
    # - any *.html / *.json at the bundle root matching old
    #   flat-shape letter files (A.html, A.json, ... _.html)
    # - leave index.html, all.json, lib/ alone (regenerated below)
    if (args.out_dir / "letters").exists():
        shutil.rmtree(args.out_dir / "letters")
    (args.out_dir / "letters").mkdir(parents=True, exist_ok=True)
    flat_stale_glob = re.compile(r"^[A-Z_]\.(html|json)$")
    for p in list(args.out_dir.iterdir()):
        if p.is_file() and flat_stale_glob.match(p.name):
            log.info("removing stale flat-shape artifact: %s", p.name)
            p.unlink()

    records = load_data(args, log)
    by_letter = group_by_letter(records)

    if args.letters:
        wanted = {L.strip().upper() for L in args.letters.split(",") if L.strip()}
        wanted.add(ORPHAN_LETTER)  # always include the orphan bucket
        for L in list(by_letter):
            if L not in wanted:
                del by_letter[L]
        log.info("rendering only letters: %s", sorted(by_letter))

    log.info("letters present: %s", sorted(by_letter))
    log.info("writing letter pages...")
    for letter, recs in by_letter.items():
        if not recs:
            continue
        html_doc = render_letter(letter, recs, by_letter)
        copied, apps_copied = place_letter_files(
            args.out_dir, letter, html_doc, recs,
            args.img_dir, args.applications_dir,
        )
        log.info(
            "  %s: %d records, %d card images, %d application images",
            letter, len(recs), len(copied), len(apps_copied),
        )

    write_all_json(args.out_dir, by_letter, len(records), set(by_letter.keys()))

    # Top-level index pointing into letters/*/viewer/*.html
    index_path = render_index(by_letter, len(records),
                              set(by_letter.keys()), args.out_dir)
    log.info("wrote index -> %s (%d cards)",
             index_path.relative_to(args.out_dir.parent),
             len(records))

    # Vendor Alpine + OpenSeadragon
    vendor_libs(args.out_dir, log)

    # Summarize
    html_count = sum(1 for _ in args.out_dir.rglob("*.html"))
    json_count = sum(1 for _ in args.out_dir.rglob("*.json"))
    total_bytes = sum(p.stat().st_size for p in args.out_dir.rglob("*")
                      if p.is_file())
    log.info("totals: %d HTML + %d JSON = %s in %s",
             html_count, json_count,
             human_bytes(total_bytes), args.out_dir)


if __name__ == "__main__":
    main()
