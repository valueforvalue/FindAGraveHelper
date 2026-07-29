"""Build a per-surname-letter HTML viewer for the pension cards.

Generates one HTML file per last-name first letter (A, B, C, ...)
under ``data/cards/viewer/{letter}.html`` plus an ``index.html``.

Each row in a letter page shows:
- Pensioner name + spouse name (if widow card)
- Service info (company, regiment) when present
- Image(s) of the pension card, lazy-loaded (``loading="lazy"``)
- OCR-extracted death date (if available) with confidence markers
  (death keyword proximity, soldier-name mention)
- "No date extracted" row for cards where OCR found nothing

The embedded JSON is inlined as a ``<script type="application/json">``
block at the top of each page so the page is fully self-contained
and works offline.

Usage:
    python scripts/ingest/build_pensioncard_viewer.py
    python scripts/ingest/build_pensioncard_viewer.py --letters A,B,C
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_ROOT = _SCRIPTS_DIR.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_INPUT_JSON = Path(
    "docs/research/digitalprairie/ok_pensioners.json"
)
DEFAULT_REPORT = Path("data/cards/enrichment_report.json")
DEFAULT_IMG_DIR = Path("data/cards/img")
DEFAULT_OUT_DIR = Path("data/cards/viewer")


def load_data(args, log):
    rows = json.loads(args.input.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    # Index enrichment by pensioncard_id
    enriched_by_pcid = {}
    for c in report.get("changed", []):
        pcid = c.get("pensioncard_id")
        if pcid is not None:
            enriched_by_pcid[int(pcid)] = c

    # Index images by pensioncard_id
    imgs_by_pcid = defaultdict(list)
    for img in args.img_dir.glob("*.jpg"):
        try:
            pcid = int(img.stem.split("__")[0])
            imgs_by_pcid[pcid].append(img.name)
        except Exception:
            continue

    # Build one record per pensioncard_id that has at least one image
    # (or for which OCR produced a result). Skip pensioners with no
    # card image AND no OCR result — they have nothing to show.
    pcid_to_pensioner = {}
    for r in rows:
        pcid = r.get("pensioncard_id")
        if pcid is None:
            continue
        pcid_to_pensioner[int(pcid)] = r

    records = []
    seen_pcids = set()
    # Walk all pensioners with images (so widow cards without enrichment
    # still appear).
    for pcid, pensioner in pcid_to_pensioner.items():
        images = imgs_by_pcid.get(pcid, [])
        if not images and pcid not in enriched_by_pcid:
            continue
        enr = enriched_by_pcid.get(pcid)
        last_name = (pensioner.get("last_name") or "").strip()
        letter = (last_name[0].upper() if last_name else "?")
        records.append({
            "pensioncard_id": pcid,
            "pensioner_id": pensioner.get("id"),
            "letter": letter,
            "last_name": last_name,
            "first_name": pensioner.get("first_name", ""),
            "name_raw": pensioner.get("name_raw", ""),
            "spouse_name_raw": pensioner.get("spouse_name_raw", ""),
            "company": pensioner.get("company", ""),
            "regiment": pensioner.get("regiment", ""),
            "application_number": pensioner.get("application_number", ""),
            "pension_number": pensioner.get("pension_number", ""),
            "death_year": enr.get("death_year", "") if enr else "",
            "death_date_iso": enr.get("death_date_iso", "") if enr else "",
            "near_death_keyword": enr.get("near_death_keyword", False) if enr else False,
            "mentions_soldier_name": enr.get("mentions_soldier_name", False) if enr else False,
            "is_widow_card": enr.get("is_widow_card", False) if enr else bool(pensioner.get("spouse_name_raw","").strip()),
            "images": sorted(images),
        })
        seen_pcids.add(pcid)

    log.info("loaded %d pensioner records with images or death data",
             len(records))
    return records


def group_by_letter(records):
    by_letter = defaultdict(list)
    for r in records:
        by_letter[r["letter"]].append(r)
    # Sort each group by last name, then first name
    for letter in by_letter:
        by_letter[letter].sort(
            key=lambda r: (r["last_name"].lower(), r["first_name"].lower())
        )
    return by_letter


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pension Cards — Surnames starting with {LETTER} ({COUNT} cards)</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 1em; background: #f5f5f0; color: #222;
  }}
  header {{
    background: #2c3e50; color: white; padding: 1em 1.5em;
    margin: -1em -1em 1em -1em; display: flex;
    justify-content: space-between; align-items: center;
  }}
  header h1 {{ margin: 0; font-size: 1.4em; }}
  header .nav a {{ color: white; margin-left: 1em; text-decoration: none; }}
  header .nav a:hover {{ text-decoration: underline; }}
  .controls {{ margin: 1em 0; }}
  .controls input {{
    padding: 0.4em; font-size: 1em; width: 18em;
    border: 1px solid #ccc; border-radius: 3px;
  }}
  .record {{
    background: white; border: 1px solid #ccc; border-radius: 4px;
    margin: 0.8em 0; padding: 0.8em;
    display: grid; grid-template-columns: 220px 1fr; gap: 1em;
  }}
  .record .name {{ font-size: 1.15em; font-weight: 600; }}
  .record .widow-tag {{
    display: inline-block; background: #e74c3c; color: white;
    font-size: 0.75em; padding: 0.1em 0.5em; border-radius: 3px;
    margin-left: 0.5em; vertical-align: middle;
  }}
  .record .info {{ font-size: 0.9em; color: #555; margin: 0.3em 0; }}
  .record .death-date {{
    margin-top: 0.5em; padding: 0.4em 0.6em; border-radius: 3px;
    display: inline-block; font-size: 0.95em;
  }}
  .death-date.has-date {{
    background: #27ae60; color: white; font-weight: 600;
  }}
  .death-date.has-date.kw {{ background: #229954; }}
  .death-date.has-date.soldier {{ background: #1e8449; }}
  .death-date.no-date {{
    background: #ecf0f1; color: #7f8c8d; font-style: italic;
  }}
  .images {{ display: flex; flex-direction: column; gap: 0.3em; }}
  .images img {{
    max-width: 220px; max-height: 280px; object-fit: contain;
    border: 1px solid #ddd; background: #fafafa;
  }}
  .markers {{ font-size: 0.8em; color: #7f8c8d; margin-top: 0.3em; }}
  .markers .marker {{
    display: inline-block; margin-right: 0.5em;
    padding: 0.1em 0.4em; border-radius: 3px;
    background: #ecf0f1;
  }}
  .markers .marker.soldier {{ background: #d5f5e3; color: #196f3d; }}
  .markers .marker.kw {{ background: #d6eaf8; color: #1f618d; }}
  .markers .marker.fallback {{ background: #fdebd0; color: #935116; }}
  .summary {{ font-size: 0.85em; color: #666; }}
</style>
</head>
<body>
<header>
  <h1>Surnames: {LETTER} <span class="summary">({COUNT} cards, {WITH_DATE} with death date)</span></h1>
  <nav class="nav">
    <a href="index.html">Index</a>
    <a href="{SAFE_LETTER}.json">JSON</a>
    {PREV_NEXT}
  </nav>
</header>
<div class="controls">
  <input type="text" id="filter" placeholder="Filter by name (case-insensitive)..." autofocus>
</div>
<div id="records">
{RECORDS}
</div>
<script type="application/json" id="records-data">
{JSON_DATA}
</script>
<script>
  // Filter rows by name fragment
  const filter = document.getElementById('filter');
  filter.addEventListener('input', () => {{
    const q = filter.value.toLowerCase();
    document.querySelectorAll('.record').forEach(el => {{
      const name = el.dataset.searchText || '';
      el.style.display = (!q || name.includes(q)) ? '' : 'none';
    }});
  }});
</script>
</body>
</html>
"""


def render_record(rec):
    """Render one record's HTML + build its searchable text."""
    name = html.escape(rec["name_raw"] or "?")
    spouse = rec.get("spouse_name_raw", "").strip()
    is_widow = rec.get("is_widow_card", False)
    widow_tag = '<span class="widow-tag">widow card</span>' if is_widow else ""

    info_lines = []
    if rec.get("company"):
        info_lines.append(f"Company {html.escape(rec['company'])}")
    if rec.get("regiment"):
        info_lines.append(f"Regiment {html.escape(rec['regiment'])}")
    if rec.get("application_number"):
        info_lines.append(f"App #{html.escape(rec['application_number'])}")
    if rec.get("pension_number"):
        info_lines.append(f"Pension #{html.escape(rec['pension_number'])}")
    if spouse:
        info_lines.append(f"Spouse: {html.escape(spouse)}")
    info_html = "<br>".join(info_lines) if info_lines else ""

    death_year = rec.get("death_year", "")
    death_iso = rec.get("death_date_iso", "")
    kw = rec.get("near_death_keyword", False)
    soldier = rec.get("mentions_soldier_name", False)
    source_pass = rec.get("source_pass")  # may not be in rec — not critical

    if death_year:
        cls = "has-date"
        if soldier:
            cls += " soldier"
        elif kw:
            cls += " kw"
        death_html = (
            f'<div class="death-date {cls}">'
            f'Death date: {html.escape(death_iso or death_year)}'
            f'</div>'
        )
        markers = []
        if soldier:
            markers.append('<span class="marker soldier">mentions soldier name</span>')
        if kw:
            markers.append('<span class="marker kw">death keyword</span>')
        # source_pass is not in our enriched record, skip if missing
        marker_html = ('<div class="markers">' + " ".join(markers) + '</div>'
                       if markers else "")
    else:
        death_html = '<div class="death-date no-date">No date extracted</div>'
        marker_html = ""

    images_html = ""
    if rec["images"]:
        imgs = "".join(
            f'<img src="../img/{html.escape(fn)}" loading="lazy" '
            f'alt="Pension card for {html.escape(rec["name_raw"])}">'
            for fn in rec["images"]
        )
        images_html = f'<div class="images">{imgs}</div>'
    else:
        images_html = '<div class="images"><em>No image on disk</em></div>'

    search_text = f"{rec['name_raw']} {spouse}".lower()

    return (
        f'<div class="record" data-search-text="{html.escape(search_text)}">'
        f'{images_html}'
        f'<div>'
        f'<div class="name">{name}{widow_tag}</div>'
        f'<div class="info">{info_html}</div>'
        f'{death_html}'
        f'{marker_html}'
        f'</div>'
        f'</div>'
    )


def render_letter_page(letter, records, all_letters):
    def _safe(L):
        return L if L.isalnum() else "_"
    prev_next = ""
    sorted_letters = sorted(all_letters)
    idx = sorted_letters.index(letter)
    if idx > 0:
        prev_next += f'<a href="{_safe(sorted_letters[idx-1])}.html">&larr; {sorted_letters[idx-1]}</a>'
    if idx < len(sorted_letters) - 1:
        prev_next += f'<a href="{_safe(sorted_letters[idx+1])}.html">{sorted_letters[idx+1]} &rarr;</a>'

    records_html = "\n".join(render_record(r) for r in records)
    with_date = sum(1 for r in records if r.get("death_year"))
    json_data = json.dumps(records, ensure_ascii=False)

    return PAGE_TEMPLATE.format(
        LETTER=letter,
        SAFE_LETTER=letter if letter.isalnum() else "_",
        COUNT=len(records),
        WITH_DATE=with_date,
        PREV_NEXT=prev_next,
        RECORDS=records_html,
        JSON_DATA=json_data,
    )


INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pension Card Viewer — Index</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 2em; background: #f5f5f0;
  }}
  h1 {{ margin-top: 0; }}
  .summary {{ color: #666; margin-bottom: 1.5em; }}
  .letters {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
             gap: 0.8em; }}
  .letter-card {{
    background: white; border: 1px solid #ccc; border-radius: 4px;
    padding: 1em; text-decoration: none; color: #2c3e50;
    display: block; transition: transform 0.1s;
  }}
  .letter-card:hover {{ transform: translateY(-2px);
                       border-color: #2c3e50; }}
  .letter-card .l {{ font-size: 2.5em; font-weight: 700;
                     line-height: 1; color: #2c3e50; }}
  .letter-card .meta {{ font-size: 0.85em; color: #666; margin-top: 0.3em; }}
</style>
</head>
<body>
<h1>Pension Card Viewer</h1>
<div class="summary">
  Total: {TOTAL} pensioners with images or death data, across {LETTERS} letters.
  Click a letter to browse surname-grouped cards.
</div>
<div class="letters">
{LETTER_CARDS}
</div>
</body>
</html>
"""


def render_index(full_by_letter, full_total, rendered_letters):
    """Render the index page.

    All letters appear; ones that were rendered (per --letters) are
    clickable, others show as a disabled card.
    """
    def _safe(L):
        return L if L.isalnum() else "_"
    cards = []
    for letter in sorted(full_by_letter):
        recs = full_by_letter[letter]
        with_date = sum(1 for r in recs if r.get("death_year"))
        if letter in rendered_letters:
            cards.append(
                f'<a class="letter-card" href="{_safe(letter)}.html">'
                f'<div class="l">{letter}</div>'
                f'<div class="meta">{len(recs)} cards<br>{with_date} with death date</div>'
                f'</a>'
            )
        else:
            cards.append(
                f'<div class="letter-card" style="opacity:0.4; cursor:not-allowed;">'
                f'<div class="l">{letter}</div>'
                f'<div class="meta">{len(recs)} cards<br>(not rendered — re-run without --letters)</div>'
                f'</div>'
            )
    return INDEX_TEMPLATE.format(
        TOTAL=full_total,
        LETTERS=len(full_by_letter),
        LETTER_CARDS="\n".join(cards),
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT_JSON)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--img-dir", type=Path, default=DEFAULT_IMG_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--letters", type=str, default="",
                    help="comma-separated subset of letters to render (default: all)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("viewer")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    records = load_data(args, log)
    by_letter = group_by_letter(records)

    selected = None
    if args.letters:
        selected = set(l.strip().upper() for l in args.letters.split(","))
        log.info("rendering only letters: %s", sorted(selected))
        for L in list(by_letter):
            if L not in selected:
                del by_letter[L]

    # Render each letter page + sidecar JSON
    total = sum(len(v) for v in by_letter.values())
    for letter, recs in by_letter.items():
        page = render_letter_page(letter, recs, by_letter)
        # Sanitize letter for filename — '?' is invalid on Windows
        safe = letter if letter.isalnum() else "_"
        out_html = args.out_dir / f"{safe}.html"
        out_html.write_text(page, encoding="utf-8")
        # Sidecar JSON for the letter — same record list the page
        # embeds, written separately so consumers can parse it
        # without scraping HTML.
        out_json = args.out_dir / f"{safe}.json"
        out_json.write_text(
            json.dumps({
                "letter": letter,
                "count": len(recs),
                "with_death_date": sum(1 for r in recs if r.get("death_year")),
                "records": recs,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("wrote %s + %s (%d records)",
                 out_html.name, out_json.name, len(recs))

    # Master JSON: every record across every letter, keyed by
    # pensioncard_id for direct lookup. Larger but single source
    # of truth — useful for piping into other tools. Always
    # written with the FULL set, regardless of --letters filter
    # (the filter only narrows which HTML pages get rendered).
    full_records = records  # unfiltered list
    full_by_letter = group_by_letter(full_records)
    full_total = len(full_records)
    master = {
        "total_pensioners": full_total,
        "letters": sorted(full_by_letter.keys()),
        "by_pensioncard_id": {
            str(r["pensioncard_id"]): r
            for letter_recs in full_by_letter.values()
            for r in letter_recs
        },
        "by_letter": {
            letter: [
                {"pensioncard_id": r["pensioncard_id"],
                 "name_raw": r["name_raw"],
                 "death_date_iso": r["death_date_iso"]}
                for r in recs
            ]
            for letter, recs in full_by_letter.items()
        },
    }
    master_path = args.out_dir / "all.json"
    master_path.write_text(
        json.dumps(master, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("wrote %s (%d records)", master_path.name, full_total)

    # Render index (always shows all letters so navigation works
    # even after a --letters filter)
    rendered_letters = set(by_letter.keys())
    index_html = render_index(full_by_letter, full_total, rendered_letters)
    (args.out_dir / "index.html").write_text(index_html, encoding="utf-8")
    log.info("wrote %s/index.html (%d letters, %d records total)",
             args.out_dir, len(full_by_letter), full_total)

    # Print a summary of sizes
    htmls = list(args.out_dir.glob("*.html"))
    jsons = list(args.out_dir.glob("*.json"))
    html_size = sum(p.stat().st_size for p in htmls)
    json_size = sum(p.stat().st_size for p in jsons)
    log.info(
        "totals: %d HTML files (%.1f MB), %d JSON files (%.1f MB)",
        len(htmls), html_size / 1e6, len(jsons), json_size / 1e6,
    )


if __name__ == "__main__":
    raise SystemExit(main())