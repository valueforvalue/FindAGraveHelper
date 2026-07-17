"""Headless smoke test for the spouse badges.

Outputs a self-contained HTML fixture that imports only the
two badge renderers from scripts/view.html and asserts the
DOM behaviour. Run with playwright (manual invocation).
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).parent.parent
VIEW = (ROOT / "scripts" / "view.html").read_text(encoding="utf-8")

# Extract: escapeHtml + 4 renderers, just the function bodies
extract = ""
m = re.search(r"function escapeHtml\([\s\S]*?^\}\s*$", VIEW, re.MULTILINE)
extract = m.group(0) if m else ""
for name in ("renderCgrDedupBadge", "renderDdBadge",
            "renderSpouseKnownBadge", "renderSpouseMatchBadge"):
    m = re.search(
        rf"function\s+{name}\s*\(\s*p\s*\)[\s\S]*?^\}}\s*$",
        VIEW, re.MULTILINE,
    )
    if m:
        extract += "\n" + m.group(0)

test_data = [
    {  # P1: known + match (Garnett Adams / Sarah E. Adams)
        "pensioner_id": 1,
        "pensioner_name": "Sarah E. Adams",
        "pensioner_first": "Sarah",
        "pensioner_last": "Adams",
        "status": "ambiguous",
        "pensioner_spouse_first": "Garnett",
        "pensioner_spouse_middle": "A.",
        "pensioner_spouse_last": "Adams",
        "spouse_match": {
            "captured_spouse_first": "Garnett",
            "captured_spouse_last": "Adams",
            "dd_memorial_id": 83891522,
            "matched_via": "family_section",
            "match_strength": "strong",
        },
    },
    {  # P2: known only
        "pensioner_id": 2,
        "pensioner_name": "John Smith",
        "pensioner_first": "John",
        "pensioner_last": "Smith",
        "status": "ambiguous",
        "pensioner_spouse_first": "Jane",
        "pensioner_spouse_last": "Smith",
    },
    {  # P3: neither
        "pensioner_id": 3,
        "pensioner_name": "No Spouse Recorded",
        "pensioner_first": "Alice",
        "pensioner_last": "Doe",
        "status": "ambiguous",
    },
]

html = """<!DOCTYPE html><html><body>
<div id="results"></div>
<script>
const pensioners = """ + json.dumps(test_data) + """;
""" + extract + """

const results = document.getElementById('results');
let out = '';
for (const p of pensioners) {
  out += '<div class="pensioner"><h2>' +
    (p.pensioner_name || '?') + ' id=' + p.pensioner_id +
    renderCgrDedupBadge(p) +
    renderDdBadge(p) +
    renderSpouseKnownBadge(p) +
    renderSpouseMatchBadge(p) +
    '</h2></div>';
}
results.innerHTML = out;
</script>
</body></html>
"""

fixture = ROOT / "tests" / "_smoke_view.html"
fixture.write_text(html, encoding="utf-8")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright not installed; open", fixture, "manually")
    sys.exit(1)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.goto("file:///" + str(fixture).replace("\\", "/"))
    page.wait_for_selector(".pensioner", timeout=5000)
    divs = page.locator(".pensioner")
    assert divs.count() == 3, f"expected 3 pensioners, got {divs.count()}"
    p1_html = divs.nth(0).inner_html()
    p2_html = divs.nth(1).inner_html()
    p3_html = divs.nth(2).inner_html()
    browser.close()

checks = [
    ("P1: spouse-known-badge present",  "spouse-known-badge"  in p1_html),
    ("P1: spouse-match-badge present",   "spouse-match-badge"  in p1_html),
    ("P1: shows memorial #83891522",     "83891522"             in p1_html),
    ("P1: includes heart",                "\u2665"             in p1_html),
    ("P2: spouse-known-badge present",  "spouse-known-badge"  in p2_html),
    ("P2: NO spouse-match-badge",        "spouse-match-badge" not in p2_html),
    ("P3: no spouse-known-badge",        "spouse-known-badge" not in p3_html),
    ("P3: no spouse-match-badge",        "spouse-match-badge" not in p3_html),
]

all_ok = True
for label, ok in checks:
    safe_label = label.encode("ascii", "replace").decode("ascii")
    print(("PASS" if ok else "FAIL"), "-", safe_label)
    if not ok:
        all_ok = False

fixture.unlink(missing_ok=True)
sys.exit(0 if all_ok else 1)
