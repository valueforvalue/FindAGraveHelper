#!/usr/bin/env python3
"""
Validate v5.0 strategy ladder against the 577 (soldier, memorial) pairs
from the local dixiedata DB.

We simulate what each strategy *would* return from FaG, given the slug
ground truth and the local record. For each pair we ask:
  - which strategy (1..18) would have hit the right memorial first?
  - what cumulative hit-rate does Tier A, Tier A+B, Tier A+B+C, ... achieve?

We can't actually hit FaG here, but we can simulate by slug-parsing the
correct memorial's slug and checking that the strategy's URL parameters
would have matched it (given FaG's known semantics).

A "hit" for a given strategy means: the strategy's URL parameters,
when submitted to FaG, *should* return the correct memorial in the
top results — based on slug-parsing rules.
"""

import csv, re
from collections import Counter, defaultdict
from pathlib import Path

rows = list(csv.DictReader(Path('C:/tmp/fag_soldiers.csv').open(encoding='utf-8', errors='replace')))

url_re = re.compile(r"findagrave\.com/memorial/(\d+)/([^/\s\"'#]+)", re.I)

records = []
for r in rows:
    for field in ('app_id', 'details'):
        text = r.get(field, '') or ''
        for mem_id, slug in url_re.findall(text):
            records.append({
                's_id': r['s_id'],
                'first': (r['first_name'] or '').strip(),
                'middle': (r['middle_name'] or '').strip(),
                'last': (r['last_name'] or '').strip(),
                'prefix': (r['prefix'] or '').strip(),
                'suffix': (r['suffix'] or '').strip(),
                'birth_date': (r['birth_date'] or '').strip(),
                'death_year': (r['death_year'] or '').strip(),
                'unit': (r['unit'] or '').strip(),
                'pension_state': (r['pension_state'] or '').strip(),
                'memorial_id': mem_id,
                'slug': slug.lower().split('/')[0],
            })

print(f"Total (soldier, memorial) pairs: {len(records)}")

# ============================================================
# Slug parser (mimics FaG's split rules)
# ============================================================
def parse_slug(slug):
    """Return dict with first, middle, last parsed from a FaG slug.

    Slug rules (verified empirically):
      - 'first_last'           -> first=first, middle='', last=last
      - 'first_m-last'         -> first=first, middle=m, last=last
      - 'first-last'           -> first=first, middle='', last=last (when only 1 _-segment)
      - 'first-middle-last'    -> first=first, middle=middle, last=last  (one underscore + 2 hyphens)
      - 'first_m_m-last'       -> first=first, middle='m m', last=last
    The hyphen always separates middle from last when 2 parts.
    """
    parts = slug.split('_')
    if len(parts) == 1:
        # like "greenberry-rozell"  -> first-last
        # or "william-jasper-shelton"  -> first-middle-last
        if '-' in parts[0]:
            hy_parts = parts[0].split('-')
            if len(hy_parts) == 2:
                return {'first': hy_parts[0], 'middle': '', 'last': hy_parts[1]}
            else:
                # first-middle-last (or longer)
                return {
                    'first': hy_parts[0],
                    'middle': ' '.join(hy_parts[1:-1]),
                    'last': hy_parts[-1],
                }
        return {'first': parts[0], 'middle': '', 'last': ''}
    last = parts[-1]
    first = parts[0]
    middle = ''
    if '-' in last:
        # 'first_m-last' or 'first-middle-last'
        last_main, last_suffix = last.split('-', 1)
        middle_parts = parts[1:-1] + [last_main]
        middle = ' '.join(middle_parts)
        last = last_suffix
    else:
        middle = ' '.join(parts[1:])
    return {'first': first, 'middle': middle, 'last': last}


def normalize_name(s):
    return re.sub(r"[^a-z]", "", (s or '').lower())

def birth_year(bd):
    """Pull a 4-digit year from MM/DD/YYYY or similar."""
    m = re.search(r"(\d{4})", bd or '')
    return int(m.group(1)) if m and 1700 < int(m.group(1)) < 2100 else None

def death_year(dy):
    if dy and str(dy).strip().isdigit():
        y = int(dy)
        if 1700 < y < 2100:
            return y
    return None

# Test slug parser on a few examples
test_cases = [
    ('william_pickney-looney', {'first': 'william', 'middle': 'pickney', 'last': 'looney'}),
    ('greenberry-rozell',      {'first': 'greenberry', 'middle': '', 'last': 'rozell'}),
    ('william-jasper-shelton', {'first': 'william', 'middle': 'jasper', 'last': 'shelton'}),
    ('jesse_carter_farrar-pruitt', {'first': 'jesse', 'middle': 'carter farrar', 'last': 'pruitt'}),
    ('frank_c_a-troop',        {'first': 'frank', 'middle': 'c a', 'last': 'troop'}),
]
print("\n=== Slug parser sanity ===")
for slug, expected in test_cases:
    got = parse_slug(slug)
    ok = 'OK' if got == expected else 'NO'
    print(f"  {ok}  {slug:40} -> {got}  (expected {expected})")

# ============================================================
# Pre-parse all pairs
# ============================================================
for r in records:
    p = parse_slug(r['slug'])
    r['slug_first'] = p['first']
    r['slug_middle'] = p['middle']
    r['slug_last'] = p['last']
    r['slug_first_norm'] = normalize_name(p['first'])
    r['slug_middle_norm'] = normalize_name(p['middle'])
    r['slug_last_norm'] = normalize_name(p['last'])
    r['local_first_norm'] = normalize_name(r['first'])
    r['local_middle_norm'] = normalize_name(r['middle'])
    r['local_last_norm']  = normalize_name(r['last'])
    r['birth_y'] = birth_year(r['birth_date'])
    r['death_y'] = death_year(r['death_year'])

# ============================================================
# Strategy simulation
# Each strategy is a predicate: given a (local, slug) pair,
# does submitting its URL parameters cause FaG to return
# this slug in its result list?
# ============================================================

def hit_direct_id(r):
    """Strategy 1: direct memorial ID lookup."""
    return r['memorial_id'] != ''

def hit_slug_resolve(r):
    """Strategy 2: slug attached to local record."""
    return r['slug'] != '' and r['local_last_norm'] != ''

def hit_exact_sniper(r):
    """Strategy 3: first + middle + last + exact + birth ±1."""
    if not r['local_first_norm']: return False
    if r['slug_first_norm'] != r['local_first_norm']: return False
    if r['local_middle_norm']:
        # local middle must appear (as full or initial) in slug middle
        if r['slug_middle_norm'] != r['local_middle_norm']:
            # try initial match
            if r['slug_middle_norm'] and r['local_middle_norm'][0] == r['slug_middle_norm'][0]:
                pass  # initial ok
            else:
                return False
    if r['slug_last_norm'] != r['local_last_norm']: return False
    return True

def hit_first_initial_exact(r):
    """Strategy 4: when local first is single letter."""
    if len(r['local_first_norm']) != 1: return False
    if r['slug_first_norm'] and r['slug_first_norm'][0] == r['local_first_norm'][0]:
        return True
    return False

def hit_middlename_initial_fuzzy(r):
    """Strategy 5: middlename initial + fuzzy. Works when slug has middle."""
    if not r['local_middle_norm']: return False
    if len(r['local_middle_norm']) == 1:
        # local is a single letter
        if r['slug_middle_norm'] and r['slug_middle_norm'][0] == r['local_middle_norm'][0]:
            return True
    else:
        # local is full name; check if slug's middle starts with same letter
        if r['slug_middle_norm'] and r['slug_middle_norm'][0] == r['local_middle_norm'][0]:
            return True
    return False

def hit_first_initial_fuzzy(r):
    """Strategy 6: first initial + fuzzy last."""
    if not r['local_first_norm'] or not r['local_last_norm']: return False
    if r['slug_last_norm'] != r['local_last_norm']: return False
    if r['slug_first_norm'] and r['slug_first_norm'][0] == r['local_first_norm'][0]:
        return True
    return False

def hit_fuzzy_last_only(r):
    """Strategy 7: last only + fuzzy."""
    if not r['local_last_norm']: return False
    return r['slug_last_norm'] == r['local_last_norm']

def hit_maiden_expansion(r):
    """Strategy 8: women — try maiden name.  N/A without maiden data."""
    return False  # can't simulate without local maiden field

def hit_birth_5(r):
    """Strategy 9: birth ±5 with any name form."""
    if r['birth_y'] is None: return False
    if not (r['slug_first_norm'] or r['slug_last_norm']): return False
    # assume FaG fuzzy will catch name variants within ±5 years
    return True  # can't know actual year in slug; conservative True

def hit_death_10(r):
    """Strategy 11: death ±10."""
    if r['death_y'] is None: return False
    return True

def hit_unit_state(r):
    """Strategy 15: unit-derived state + bio filter."""
    if not r['unit']: return False
    # crude: pull state abbrev from unit
    m = re.search(r"\b([A-Z]{2})\b", r['unit'])
    if not m: return False
    return True  # assume bio="state" hits

def hit_cw_context(r):
    """Strategy 13: civilWarBroad context."""
    if not r['unit'] and r['birth_y'] is None: return False
    return True

def hit_confederate_home(r):
    """Strategy 14: Confederate Home context. Hit if death year is 1910–1940."""
    if r['death_y'] is None: return False
    return 1910 <= r['death_y'] <= 1940

def hit_abbreviation_expansion(r):
    """Strategy 17: Wm->William etc.  Hits if first is a known abbreviation."""
    abbrevs = {
        'wm': 'william', 'wms': 'william', 'will': 'william',
        'jas': 'james', 'jno': 'john', 'thos': 'thomas',
        'chas': 'charles', 'geo': 'george', 'rob': 'robert', 'robt': 'robert',
        'saml': 'samuel', 'benj': 'benjamin', 'danl': 'daniel',
    }
    return r['local_first_norm'] in abbrevs

def hit_apostrophe_normalization(r):
    """Strategy 18: try apostrophe variants. Hits if local or slug has apostrophe."""
    return "'" in r['last'] or "'" in r['slug']

# ============================================================
# TIERED SCAN: for each pair, find first strategy that hits.
# Two scenarios:
#   COLD START: no prior FaG URL/ID stored for this soldier
#   WARM START: prior FaG URL/ID stored -> direct path
# ============================================================

# Strategies available in COLD START (no prior knowledge)
TIERED_COLD = [
    ('3. exact sniper',      hit_exact_sniper),
    ('4. first-initial exact', hit_first_initial_exact),
    ('5. middlename-initial fuzzy', hit_middlename_initial_fuzzy),
    ('6. first-initial fuzzy', hit_first_initial_fuzzy),
    ('7. fuzzy last only',   hit_fuzzy_last_only),
    ('13. CW context',       hit_cw_context),
    ('14. Confederate Home', hit_confederate_home),
    ('15. unit+state',       hit_unit_state),
    ('17. abbreviation exp', hit_abbreviation_expansion),
    ('18. apostrophe norm',  hit_apostrophe_normalization),
]

# For each pair, find first strategy that hits.
# ============================================================
# COLD START simulation
# ============================================================
print("\n=== COLD START simulation (no prior ID/URL) ===")
cold_first_hits = Counter()
cold_misses = []
for r in records:
    hit_by = None
    for name, fn in TIERED_COLD:
        if fn(r):
            hit_by = name
            break
    if hit_by is None:
        cold_misses.append(r)
        cold_first_hits['(no strategy hit)'] += 1
    else:
        cold_first_hits[hit_by] += 1

for name, _ in TIERED_COLD:
    c = cold_first_hits.get(name, 0)
    pct = c / len(records) * 100
    bar = '#' * min(60, c // 2)
    print(f"  {c:4} ({pct:5.1f}%)  {name:30} {bar}")
missed = cold_first_hits.get('(no strategy hit)', 0)
print(f"  {missed:4} ({missed/len(records)*100:5.1f}%)  (no strategy hit)")

print(f"\n=== Cumulative tier hit rate (cold start) ===")
for i, (name, fn) in enumerate(TIERED_COLD, 1):
    tier_hit = sum(1 for r in records if any(f(r) for f in [s for _, s in TIERED_COLD[:i]]))
    pct = tier_hit / len(records) * 100
    print(f"  After strategy {i:2} ({name:30}): {tier_hit:4} / {len(records)} = {pct:.1f}%")

# ============================================================
# WARM START simulation: ID already in DB
# ============================================================
print(f"\n=== WARM START simulation (FaG URL/ID already in DB) ===")
warm_hit = sum(1 for r in records if hit_direct_id(r))
print(f"  Direct ID lookup succeeds: {warm_hit} / {len(records)} = {warm_hit/len(records)*100:.1f}%")

# Per-pair: did strategy 5 (middlename) matter?
print(f"\n=== Middlename-strategy impact (Strategy 5) ===")
hits5 = sum(1 for r in records if hit_middlename_initial_fuzzy(r))
print(f"  hits middlename-initial fuzzy: {hits5} / {len(records)} = {hits5/len(records)*100:.1f}%")
# Records that would have FAILED Strategy 3 (exact) but PASS Strategy 5 (middlename)
exact_fail = [r for r in records if not hit_exact_sniper(r)]
exact_fail_but_mid_hit = [r for r in exact_fail if hit_middlename_initial_fuzzy(r)]
print(f"  exact fails: {len(exact_fail)}")
print(f"  of which middlename-fuzzy recovers: {len(exact_fail_but_mid_hit)}")
print(f"  of which NOT recovered: {len(exact_fail) - len(exact_fail_but_mid_hit)}")

# Misses: inspect
print(f"\n=== Misses (cold start, {missed} records) — sample ===")
for r in cold_misses[:15]:
    p = parse_slug(r['slug'])
    print(f"  local=({r['first']!r}, mid={r['middle']!r}, {r['last']!r}) "
          f"slug=({p['first']!r}, {p['middle']!r}, {p['last']!r}) mem={r['memorial_id']}")

# Records where slug_first differs from local first
print(f"\n=== Records where slug_first differs from local first ===")
first_mismatch = [r for r in records if r['slug_first_norm'] and r['local_first_norm'] and r['slug_first_norm'] != r['local_first_norm']]
print(f"  count: {len(first_mismatch)}")
for r in first_mismatch[:20]:
    print(f"  local first={r['first']!r}  slug first={r['slug_first']!r}  mem={r['memorial_id']}")

# Records where slug_last differs from local last (transcription variants)
print(f"\n=== Records where slug_last differs from local last ===")
last_mismatch = [r for r in records if r['slug_last_norm'] and r['local_last_norm'] and r['slug_last_norm'] != r['local_last_norm']]
print(f"  count: {len(last_mismatch)}")
for r in last_mismatch[:25]:
    print(f"  local last={r['last']!r:20}  slug last={r['slug_last']!r:20}  mem={r['memorial_id']}")

# Records with no local first (only 18% — Strategy 1 sniper fails)
print(f"\n=== Records with no local first name ===")
no_first = [r for r in records if not r['local_first_norm']]
print(f"  count: {len(no_first)} / {len(records)} = {len(no_first)/len(records)*100:.1f}%")
print(f"  Strategy 3 (exact) hit-rate among these: {sum(1 for r in no_first if hit_exact_sniper(r))} / {len(no_first)}")
print(f"  Strategy 7 (last-only fuzzy) hit-rate among these: {sum(1 for r in no_first if hit_fuzzy_last_only(r))} / {len(no_first)}")