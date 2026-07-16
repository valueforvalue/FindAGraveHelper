"""Parse CGR search results pages into structured dicts.

CGR's results.php returns a plain HTML table with one row per
veteran. Each data row has 4 cells:

    <tr bgcolor=...>
        <th><input type=radio name=choose value=V_88159 onClick=...></th>
        <td>88159</td>
        <td>William G (Guy) Looney</td>
        <td>34 TX</td>
        <td>May 24 1840</td>
    </tr>

The id is parsed from the radio's value attribute (V_<id>) since
that's the canonical source. Other fields come from <td> cells in
order: ID, Name, Unit, Born.

We are DELIBERATELY conservative here: we extract exactly what the
page shows, without judgment about whether a record matches a
local pensioner. The matcher (test_cgr_matcher.py / cgr_matcher.py)
makes those decisions.

This module only handles HTML parsing. The HTTP client is in
cgr_client.py.
"""
import re
from typing import Optional


def parse_cgr_results(html: str) -> list[dict]:
    """Parse CGR results.html into a list of dicts.

    Returns [] if there are no results. Each dict has:
      - id: int (the CGR veteran id) or None if unparseable
      - name: str (full name as displayed)
      - unit: str (e.g. "34 TX")
      - born: str (e.g. "May 24 1840")

    The parser does NOT filter rows or merge duplicates. Every
    row the page shows comes back.
    """
    if not html:
        return []

    results = []
    # Match each <tr> block that contains the radio + ID/Name/Unit/Born tds.
    # We anchor on the radio button (value="V_<id>") to find veteran rows
    # and skip the header rows.
    # The radio's value attribute is the canonical id source.
    row_re = re.compile(
        r"<tr[^>]*>\s*"
        r"<th[^>]*>\s*<input[^>]*value=V_(\d+)[^>]*>\s*</th>"
        r".*?"
        r"<td[^>]*>([^<]*)</td>\s*"
        r"<td[^>]*>([^<]*)</td>\s*"
        r"<td[^>]*>([^<]*)</td>\s*"
        r"</tr>",
        re.IGNORECASE | re.DOTALL,
    )
    for m in row_re.finditer(html):
        raw_id, raw_name, raw_unit, raw_born = m.groups()
        # Clean HTML entities and whitespace
        def clean(s: str) -> str:
            return s.replace("&nbsp;", "").replace("\xa0", "").strip()
        try:
            vid = int(raw_id)
        except ValueError:
            vid = None
        results.append({
            "id": vid,
            "name": clean(raw_name),
            "unit": clean(raw_unit),
            "born": clean(raw_born),
        })
    return results


def extract_record_count(html: str) -> Optional[int]:
    """Pull the "N records returned" line out of the results page.

    Returns None if the count line isn't found. Used for diagnostics
    and pagination decisions.
    """
    m = re.search(r"(\d+)\s+records?\s+returned", html, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None