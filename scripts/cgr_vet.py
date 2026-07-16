"""Parse CGR vetDetails pages into structured dicts.

CGR vetDetails.php returns a 2-column HTML table. Each row is
<td>label</td><td>value</td>. Labels repeat (e.g. 'City', 'State'
appear twice — once for birth, once for death).

We parse to a dict keyed by both the raw label AND a canonical
key when the label is recognizable. Birth vs death fields get
distinct keys.

We are CONSERVATIVE: we extract every label/value pair the page
shows. We don't infer fields that aren't present.

Field mapping (canonical → CGR label):
  first_name   → First Name
  middle_name  → Middle Name
  last_name    → Last Name
  aka          → AKA (nickname, appears twice if both name + unit have AKA)
  suffix       → Suffix
  enlisted     → Enlisted
  discharged   → Discharged
  source       → Source
  rank         → Rank
  unit         → Unit
  company      → Company
  born         → Born (date)
  birth_city   → City (1st occurrence)
  birth_state  → State (1st occurrence)
  died         → Died (date)
  death_city   → City (2nd occurrence)
  death_state  → State (2nd occurrence)  -- THIS is the key field for our project
  spouse       → Spouse
  mother_maiden → Mother Maiden
  notes        → Notes
  submitted_by → Submitted By
  phone        → Phone

The raw label→value dict is also preserved under the `_raw` key
for diagnostics.
"""
import re
from typing import Optional


# Label normalization: CGR's "First Name" / "First name" / "FIRST NAME"
# all collapse to "first_name".
_LABEL_MAP = {
    "first name": "first_name",
    "middle name": "middle_name",
    "last name": "last_name",
    "suffix": "suffix",
    "enlisted": "enlisted",
    "discharged": "discharged",
    "source": "source",
    "rank": "rank",
    "unit": "unit",
    "company": "company",
    "born": "born",
    "died": "died",
    "spouse": "spouse",
    "mother maiden": "mother_maiden",
    "notes": "notes",
    "submitted by": "submitted_by",
    "phone": "phone",
}

# These labels appear more than once on the page. We track them
# by occurrence index so birth vs death fields don't collide.
_INDEXED_LABELS = {"city", "state", "aka"}


def _clean(s: str) -> str:
    """Strip HTML entities and surrounding whitespace from a value cell."""
    s = s.replace("&nbsp;", "").replace("\xa0", "")
    return s.strip()


def parse_cgr_vet(html: str) -> dict:
    """Parse a CGR vetDetails page into a structured dict.

    Returns {} if the HTML doesn't look like a vet details page.
    """
    if not html:
        return {}

    # Match each <tr> with <td>label</td><td>value</td>.
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

        # Skip empty rows
        if not label or label == "&nbsp;":
            continue

        raw[label] = value

        if label in _INDEXED_LABELS:
            # Track occurrence (1st = birth, 2nd = death)
            indexed_counts[label] = indexed_counts.get(label, 0) + 1
            idx = indexed_counts[label]
            if label == "state":
                if idx == 1:
                    out["birth_state"] = value
                elif idx == 2:
                    out["died_state"] = value
            elif label == "city":
                if idx == 1:
                    out["birth_city"] = value
                elif idx == 2:
                    out["death_city"] = value
            elif label == "aka":
                # First AKA is the personal nickname, second is unit AKA
                if idx == 1:
                    out["aka"] = value
                else:
                    out["unit_aka"] = value
            # Keep a list of all states for diagnostics
            if label == "state":
                out.setdefault("states", []).append(value)
            if label == "city":
                out.setdefault("cities", []).append(value)
            continue

        canonical = _LABEL_MAP.get(label)
        if canonical:
            out[canonical] = value

    if raw:
        out["_raw"] = raw

    return out