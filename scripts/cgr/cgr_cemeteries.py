"""Parse the CGR cemetery-list endpoint into structured dicts.

The ajax_cemeteryDrop.php endpoint returns:

    cemeteryDiv|<select name="cemetery_id">
    <option value=></option>
    <option value="13211">Adair Co.: Baptist Mission Cemetery</option>
    <option value="14481">Adair Co.: Chalk Bluff Cemetery</option>
    ...
    </select>

The leading "cemeteryDiv|" prefix and trailing "</select>" are
junk — we ignore them.

Each option's text is "County: Name" (sometimes with "AKA:" too).
We split on "Co.:" to extract county + name.

Same cemetery name can appear with multiple ids (duplicate
entries in CGR). We preserve them all — the matcher will deal
with duplicates.

We are CONSERVATIVE: we don't filter, dedupe, or assume
relationships. We extract every option.
"""
import re


def parse_cemeteries_html(html: str) -> list[dict]:
    """Parse a CGR cemetery-list HTML response.

    Returns a list of dicts:
      - id: int
      - name: str (just the cemetery name, no county)
      - county: str (just the county name, no "Co.:")
      - raw_label: str (the original "County: Name" text)

    Empty options (no value attribute) are skipped. Options with
    malformed values are skipped (no crash).
    """
    if not html:
        return []

    out = []
    # Match each <option value="N">LABEL</option>
    # Allow optional quotes around value (the real fixture uses them).
    option_re = re.compile(
        r'<option\s+value="?(\d+)"?[^>]*>([^<]*)</option>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in option_re.finditer(html):
        raw_id = m.group(1)
        raw_label = m.group(2).strip()
        if not raw_label or raw_label == "&nbsp;":
            continue
        try:
            cid = int(raw_id)
        except ValueError:
            continue

        county, name = _split_county_name(raw_label)
        out.append({
            "id": cid,
            "name": name,
            "county": county,
            "raw_label": raw_label,
        })

    return out


def _split_county_name(raw: str) -> tuple[str, str]:
    """Split 'Adair Co.: Baptist Mission Cemetery' into ('Adair', 'Baptist Mission Cemetery').

    If no 'Co.:' separator is found, returns ('', raw).
    """
    # Common pattern: "XYZ Co.: Name"
    m = re.match(r"^(.*?)\s*Co\.\s*:\s*(.*)$", raw)
    if m:
        county = m.group(1).strip()
        name = m.group(2).strip()
        return county, name
    return "", raw