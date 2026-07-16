#!/usr/bin/env python3
"""Deeper analysis: slug structure reveals maiden names, double-barreled, etc."""
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
                'first': r['first_name'] or '',
                'middle': r['middle_name'] or '',
                'last': r['last_name'] or '',
                'prefix': r['prefix'] or '',
                'suffix': r['suffix'] or '',
                'birth_date': r['birth_date'] or '',
                'death_year': r['death_year'] or '',
                'unit': r['unit'] or '',
                'pension_state': r['pension_state'] or '',
                'memorial_id': mem_id,
                'slug': slug.lower(),
            })

# =========================================================
# 1. SLUG COMPONENT ANALYSIS
# =========================================================
print(f"Total (soldier, memorial) pairs: {len(records)}")

print("\n=== Slug part-count distribution ===")
parts_counter = Counter()
for r in records:
    slug = r['slug'].split('/')[0]
    n = len(slug.split('_'))
    parts_counter[n] += 1
for n, c in sorted(parts_counter.items()):
    print(f"  {n} parts: {c}")

print("\n=== Last slug-token vs local last-name ===")
# slug format examples:
#   william_pickney-looney     -> last="looney"  (pickney is middle)
#   james_hillard-newby        -> last="newby"
#   greenberry-rozell          -> 1-part slug!  -> just last?
#   andrew_jackson-ables       -> last="ables"
#   james_a-myers              -> "james" + "a" + "myers"  -> a=initial
# We need to extract: firstname, middle/initial, lastname
def parse_slug(slug):
    """Parse slug into (first, middles, last).  Returns list of tokens."""
    return slug.split('/')[0].split('_')

last_match = 0
last_partial = 0
last_missing = 0
last_mismatch = 0
for r in records:
    parts = parse_slug(r['slug'])
    if len(parts) < 2:
        last_missing += 1
        continue
    # last token is surname, possibly hyphenated
    slug_last = parts[-1]
    # split on hyphen
    slug_last_main = slug_last.split('-')[0]  # could be wrong for double-barrel
    local = re.sub(r"[^a-z]", "", (r['last'] or '').lower())
    sl = re.sub(r"[^a-z]", "", slug_last_main)
    if not local:
        last_missing += 1
    elif local == sl:
        last_match += 1
    elif local.startswith(sl) or sl.startswith(local):
        last_partial += 1
    else:
        last_mismatch += 1

print(f"  last_token exact matches local last: {last_match}")
print(f"  partial-prefix: {last_partial}")
print(f"  missing local last: {last_missing}")
print(f"  mismatch: {last_mismatch}")

print("\n=== Hyphenated slug-last tokens ===")
# slug = "james_hillard-newby"  -> parts = ["james", "hillard-newby"]
# the "hillard" is a middle name OR an alternate spelling of first
# Common pattern: middle_name is joined with hyphen to last
hyp_examples = []
for r in records:
    parts = parse_slug(r['slug'])
    if len(parts) == 2 and '-' in parts[1]:
        hyp_examples.append((r['first'], r['middle'], r['last'], r['slug'], r['memorial_id']))
print(f"  count of 2-part slugs with hyphenated last: {len(hyp_examples)}")
for ex in hyp_examples[:20]:
    print(f"  local=({ex[0]!r}, mid={ex[1]!r}, {ex[2]!r})  slug={ex[3]!r}  mem={ex[4]}")

print("\n=== 3-part slugs (first_middle_last OR first_maiden-married) ===")
three_part = [(r['first'], r['middle'], r['last'], r['slug'], r['memorial_id'])
              for r in records if len(parse_slug(r['slug'])) == 3]
print(f"  count: {len(three_part)}")
for ex in three_part:
    print(f"  local=({ex[0]!r}, mid={ex[1]!r}, {ex[2]!r})  slug={ex[3]!r}  mem={ex[4]}")

print("\n=== 1-part slugs (just surname) ===")
one_part = [(r['first'], r['middle'], r['last'], r['slug'], r['memorial_id'])
            for r in records if len(parse_slug(r['slug'])) == 1]
print(f"  count: {len(one_part)}")
for ex in one_part[:30]:
    print(f"  local=({ex[0]!r}, mid={ex[1]!r}, {ex[2]!r})  slug={ex[3]!r}  mem={ex[4]}")

# =========================================================
# 2. Local middle-name frequency in our 577 records
# =========================================================
print("\n=== Local middle-name presence ===")
has_middle = sum(1 for r in records if r['middle'].strip())
print(f"  records with local middle name: {has_middle}/{len(records)} ({has_middle/len(records)*100:.1f}%)")
mid_top = Counter(r['middle'].strip() for r in records if r['middle'].strip())
print("  top 20 middle names:")
for m, c in mid_top.most_common(20):
    print(f"    {c:3}  {m!r}")

# =========================================================
# 3. Prefix/suffix coverage
# =========================================================
print("\n=== Prefix/suffix coverage ===")
print(f"  has prefix: {sum(1 for r in records if r['prefix'].strip())}")
print(f"  has suffix: {sum(1 for r in records if r['suffix'].strip())}")
print(f"  prefix values: {Counter(r['prefix'].strip() for r in records if r['prefix'].strip()).most_common(10)}")
print(f"  suffix values: {Counter(r['suffix'].strip() for r in records if r['suffix'].strip()).most_common(10)}")

# =========================================================
# 4. pension_state distribution
# =========================================================
print("\n=== Pension state distribution ===")
ps_counter = Counter(r['pension_state'].strip() for r in records if r['pension_state'].strip())
for s, c in ps_counter.most_common(15):
    print(f"  {c:4} {s!r}")

# =========================================================
# 5. Unit-extracted state (first comma segment)
# =========================================================
print("\n=== Unit-derived state (first comma segment after C.S.A./U.S.A.) ===")
unit_states = Counter()
for r in records:
    u = r['unit']
    # look for ", XX Infantry" or "XX Cav" pattern
    m = re.search(r"\b([A-Z]{2})\b\s+(?:Infantry|Cavalry|Cav|Regiment|Rgmt|Battalion|Batn|Artillery|Arty)\b", u or '')
    if m:
        unit_states[m.group(1)] += 1
    else:
        unit_states['?'] += 1
for s, c in unit_states.most_common(20):
    print(f"  {c:4} {s}")

# =========================================================
# 6. birth_date format patterns
# =========================================================
print("\n=== birth_date format distribution ===")
fmt_counter = Counter()
for r in records:
    bd = r['birth_date']
    if not bd or bd == '00/00/0000':
        fmt_counter['empty/zero'] += 1
    elif re.match(r"\d{2}/\d{2}/\d{4}$", bd):
        fmt_counter['MM/DD/YYYY'] += 1
    elif re.match(r"\d{4}$", bd):
        fmt_counter['YYYY only'] += 1
    elif re.match(r"\d{4}-\d{2}-\d{2}$", bd):
        fmt_counter['ISO'] += 1
    else:
        fmt_counter['other:' + bd[:20]] += 1
for k, c in fmt_counter.most_common(15):
    print(f"  {c:4} {k}")

# =========================================================
# 7. Sample large slug variety
# =========================================================
print("\n=== Sample of 40 random slug forms ===")
import random
random.seed(0)
sample = random.sample(records, min(40, len(records)))
for r in sorted(sample, key=lambda r: r['slug']):
    print(f"  {r['first']:15} {r['last']:15} -> {r['slug']:45}  mem={r['memorial_id']}")

# =========================================================
# 8. What about surname-only slug records?
#    Sometimes a person was hard to find and
#    FaG only has a memorial slug with the surname
# =========================================================
print("\n=== Memorabilia of interest: soldiers with prefix/suffix in slug ===")
# "james_a-myers" : 2 parts, second contains hyphen with single-letter prefix
short_mid = [(r['first'], r['middle'], r['last'], r['slug'], r['memorial_id'])
             for r in records if len(parse_slug(r['slug'])) == 2 and
             '-' in parse_slug(r['slug'])[1] and
             len(parse_slug(r['slug'])[1].split('-')[0]) == 1]
print(f"  slugs with single-letter middle in hyphenated form: {len(short_mid)}")
for ex in short_mid[:15]:
    print(f"  local=({ex[0]!r}, mid={ex[1]!r}, {ex[2]!r})  slug={ex[3]!r}  mem={ex[4]}")