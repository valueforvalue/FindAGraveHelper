"""Parse CGR cemetery details pages into structured dicts.

cemDetails.php returns a 2-column HTML table with cemetery
metadata. The same parsing pattern as vetDetails but with
different field labels (cemetery-specific).

Field mapping (canonical → CGR label):
  name           → Name
  aka            → AKA
  city           → City
  county         → County
  state          → State
  country        → Country
  marker_type    → Marker Type
  marker_condition → Condition (1st)
  unit_on_marker  → Unit On Marker
  last_seen      → Last Seen
  section        → Section/Row/Plot
  nearest_road   → Nearest Road
  owner          → Owner
  directions     → Directions
  latitude       → Latitude
  longitude      → Longitude
  signage        → Signage
  signage_condition → Condition (2nd)  -- if "Condition" repeats
  size           → Size
  in_use         → In Use

We preserve all raw label→value pairs under `_raw` for diagnostics.
We do NOT assume relationships between fields (e.g. we don't infer
"this cemetery is for veterans" — we just record what the page says).
"""
import re


_LABEL_MAP = {
    "name": "name",
    "aka": "aka",
    "city": "city",
    "county": "county",
    "state": "state",
    "country": "country",
    "marker type": "marker_type",
    "unit on marker": "unit_on_marker",
    "last seen": "last_seen",
    "section/row/plot": "section",
    "nearest road": "nearest_road",
    "owner": "owner",
    "directions": "directions",
    "latitude": "latitude",
    "longitude": "longitude",
    "signage": "signage",
    "size": "size",
    "in use": "in_use",
}

# These labels appear more than once on the page — track by index.
_INDEXED_LABELS = {"condition"}


def _clean(s: str) -> str:
    s = s.replace("&nbsp;", "").replace("\xa0", "")
    return s.strip()


def parse_cgr_cem(html: str) -> dict:
    """Parse a CGR cemetery details page into a structured dict.

    Returns {} if the HTML doesn't look like a cemetery page.
    """
    if not html:
        return {}

    row_re = re.compile(
        r"<tr[^>]*>\s*"
        r"<td[^>]*>([^<]+)</td>\s*"
        r"<td[^>]*>([^<]*)</td>\s*"
        r"</tr>",
        re.IGNORECASE | re.DOTALL,
    )

    out: dict = {}
    raw: dict = {}
    indexed_counts: dict[str, int] = {}

    for m in row_re.finditer(html):
        raw_label, raw_value = m.groups()
        label = _clean(raw_label).lower()
        value = _clean(raw_value)
        if not label or label == "&nbsp;":
            continue
        raw[label] = value

        if label in _INDEXED_LABELS:
            indexed_counts[label] = indexed_counts.get(label, 0) + 1
            idx = indexed_counts[label]
            if label == "condition":
                if idx == 1:
                    out["marker_condition"] = value
                elif idx == 2:
                    out["signage_condition"] = value
                else:
                    out.setdefault("conditions", []).append(value)
            continue

        canonical = _LABEL_MAP.get(label)
        if canonical:
            out[canonical] = value

    if raw:
        out["_raw"] = raw
    return out