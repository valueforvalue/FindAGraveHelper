#!/usr/bin/env python3
"""Analyze Find a Grave URLs from dixiedata to find search-pattern signals."""
import csv, re, json, sys
from collections import Counter, defaultdict
from pathlib import Path

csv_path = Path('C:/tmp/fag_soldiers.csv')
rows = list(csv.DictReader(csv_path.open(encoding='utf-8', errors='replace')))

print(f"Total rows: {len(rows)}")

# Pull every FaG URL/Memorial ID from app_id or details
url_re = re.compile(r"findagrave\.com/memorial/(\d+)/([^/\s\"'#]+)", re.I)
id_re  = re.compile(r"FaG ID:\s*(\d+)", re.I)

# de-dup by (soldier_id, memorial_id)
records = []
for r in rows:
    s_id = r['s_id']
    urls_found = []
    ids_found  = []
    for field in ('app_id', 'details'):
        text = r.get(field, '') or ''
        urls_found.extend(url_re.findall(text))
        m = id_re.search(text)
        if m:
            ids_found.append(m.group(1))
    for mem_id, slug in urls_found:
        records.append({
            'soldier_id': s_id,
            'display_id': r['display_id'],
            'first': r['first_name'] or '',
            'middle': r['middle_name'] or '',
            'last': r['last_name'] or '',
            'prefix': r['prefix'] or '',
            'suffix': r['suffix'] or '',
            'birth_date': r['birth_date'] or '',
            'death_year': r['death_year'] or '',
            'death_date': r['death_date'] or '',
            'buried_in': r['buried_in'] or '',
            'unit': r['unit'] or '',
            'pension_state': r['pension_state'] or '',
            'memorial_id': mem_id,
            'slug': slug,
            'record_type': r['record_type'],
        })

print(f"Total (soldier, memorial) pairs: {len(records)}")

unique_soldiers = {r['soldier_id'] for r in records}
print(f"Unique soldiers with FaG URL: {len(unique_soldiers)}")

unique_memorials = {r['memorial_id'] for r in records}
print(f"Unique FaG memorial IDs: {len(unique_memorials)}")

# ============================
# 1. SLUG analysis: did the
#    Find a Grave slug match the
#    surname as stored locally?
# ============================
def normalise(s):
    return re.sub(r"[^a-z]", "", (s or '').lower())

print("\n=== Slug-vs-local-name match rate ===")
match_kinds = Counter()
sample_mismatches = []
for r in records:
    slug = r['slug'].lower()
    parts = slug.split('_')
    # slug format: firstname_lastname  (sometimes first_middle_lastname)
    last_in_slug = parts[-1] if parts else ''
    # strip /photo, etc.
    last_in_slug = last_in_slug.split('/')[0]
    norm_local_last = normalise(r['last'])
    norm_slug_last = normalise(last_in_slug)
    if not norm_local_last:
        kind = 'no_local_last'
    elif norm_local_last == norm_slug_last:
        kind = 'last_match'
    elif norm_local_last.startswith(norm_slug_last) or norm_slug_last.startswith(norm_local_last):
        kind = 'last_partial'
    else:
        kind = 'last_mismatch'
    match_kinds[kind] += 1
    if kind == 'last_mismatch' and len(sample_mismatches) < 30:
        sample_mismatches.append((r['first'], r['last'], slug, r['memorial_id']))

for k, v in match_kinds.most_common():
    print(f"  {k}: {v}")
print("\n--- Last-name mismatch samples ---")
for s in sample_mismatches:
    print(f"  local=({s[0]!r},{s[1]!r})  slug={s[2]!r}  mem={s[3]}")

# ============================
# 2. first-name mismatch
# ============================
print("\n=== First-name slug-vs-local ===")
fn_kinds = Counter()
fn_samples = []
for r in records:
    slug = r['slug'].lower().split('/')[0]
    parts = slug.split('_')
    if len(parts) < 2:
        fn_kinds['no_first_in_slug'] += 1
        continue
    first_in_slug = parts[0]
    norm_local_first = normalise(r['first'])
    norm_slug_first = normalise(first_in_slug)
    if not norm_local_first:
        kind = 'no_local_first'
    elif norm_local_first == norm_slug_first:
        kind = 'exact_match'
    elif norm_local_first.startswith(norm_slug_first) or norm_slug_first.startswith(norm_local_first):
        kind = 'partial_match'
    elif norm_local_first[0] == norm_slug_first[0]:
        kind = 'initial_match'
    else:
        kind = 'mismatch'
    fn_kinds[kind] += 1
    if kind == 'mismatch' and len(fn_samples) < 30:
        fn_samples.append((r['first'], r['last'], slug, r['memorial_id']))

for k, v in fn_kinds.most_common():
    print(f"  {k}: {v}")
print("\n--- First-name mismatch samples ---")
for s in fn_samples:
    print(f"  local=({s[0]!r},{s[1]!r})  slug={s[2]!r}  mem={s[3]}")

# ============================
# 3. Slug shape patterns
#    - hyphenated last? middle? suffix? prefix?
# ============================
print("\n=== Slug shape distribution ===")
shape_counter = Counter()
for r in records:
    slug = r['slug'].lower().split('/')[0]
    parts = slug.split('_')
    shape = (len(parts), 'middle' if len(parts) >= 3 else 'simple')
    shape_counter[shape] += 1
for k, v in shape_counter.most_common(10):
    print(f"  parts={k[0]} kind={k[1]}: {v}")

# ============================
# 4. birth_year / death_year coverage
# ============================
print("\n=== Date coverage ===")
with_birth = sum(1 for r in records if r['birth_date'])
with_death = sum(1 for r in records if r['death_year'])
with_buried = sum(1 for r in records if r['buried_in'])
with_unit = sum(1 for r in records if r['unit'])
print(f"  birth_date present: {with_birth}/{len(records)} ({with_birth/len(records)*100:.1f}%)")
print(f"  death_year present: {with_death}/{len(records)} ({with_death/len(records)*100:.1f}%)")
print(f"  buried_in present:  {with_buried}/{len(records)} ({with_buried/len(records)*100:.1f}%)")
print(f"  unit present:       {with_unit}/{len(records)} ({with_unit/len(records)*100:.1f}%)")

# ============================
# 5. birth year distribution (from birth_date)
# ============================
print("\n=== Birth-year distribution (decade buckets) ===")
decade_counter = Counter()
for r in records:
    bd = r['birth_date']
    m = re.match(r"(\d{4})", bd or '')
    if m:
        decade = int(m.group(1)) // 10 * 10
        decade_counter[decade] += 1
for d in sorted(decade_counter):
    bar = '#' * min(80, decade_counter[d])
    print(f"  {d}s: {decade_counter[d]:4} {bar}")

# ============================
# 6. death_year distribution
# ============================
print("\n=== Death-year distribution (decade buckets) ===")
decade_counter = Counter()
for r in records:
    dy = r['death_year']
    if dy and str(dy).strip().isdigit():
        decade = int(dy) // 10 * 10
        decade_counter[decade] += 1
for d in sorted(decade_counter):
    bar = '#' * min(80, decade_counter[d])
    print(f"  {d}s: {decade_counter[d]:4} {bar}")

# ============================
# 7. How often would Strategy 4 (vowel trap) help?
#    i.e. last name in local has vowels that
#    the slug-spelling *actually* matches.
# ============================
print("\n=== Vowel-trap strategy heuristic signal ===")
print("(checking if local-last contains vowels that the slug's last name normalises differently)")
vowel_offenders = Counter()
for r in records:
    local = (r['last'] or '').lower()
    slug_parts = r['slug'].lower().split('/')[0].split('_')
    if not slug_parts:
        continue
    slug_last = slug_parts[-1]
    if not local:
        continue
    # count vowels
    local_v = sum(1 for c in local if c in 'aeiouy')
    slug_v = sum(1 for c in slug_last if c in 'aeiouy')
    if local != slug_last and local_v != slug_v:
        # likely vowel-trap candidate
        vowel_offenders[(local, slug_last)] += 1

print(f"  unique (local,slug) vowel-mismatch pairs: {len(vowel_offenders)}")
for (loc, sl), c in vowel_offenders.most_common(20):
    print(f"  {c:3}  local={loc!r:20}  slug={sl!r}")

# ============================
# 8. buried_in / state signals
#    for context=CivilWarBroad narrowing
# ============================
print("\n=== Burial location word-frequency (top tokens) ===")
token_counter = Counter()
for r in records:
    for tok in re.findall(r"[A-Za-z]+", (r['buried_in'] or '').lower()):
        if len(tok) >= 3:
            token_counter[tok] += 1
for tok, c in token_counter.most_common(25):
    print(f"  {c:4} {tok}")

# ============================
# 9. Slug-character breakdown: hyphens, apostrophes, suffixes
# ============================
print("\n=== Slug quirks ===")
hyphenated = 0
for r in records:
    if '-' in r['slug'].lower():
        hyphenated += 1
print(f"  slug contains '-': {hyphenated}/{len(records)} ({hyphenated/len(records)*100:.1f}%)")

# ============================
# 10. Disambiguate names: same (first,last) with multiple memorials
# ============================
print("\n=== Same (first,last) -> multiple distinct memorials ===")
mem_by_name = defaultdict(set)
for r in records:
    key = (normalise(r['first']), normalise(r['last']))
    mem_by_name[key].add(r['memorial_id'])
ambiguous = [(k, v) for k, v in mem_by_name.items() if len(v) > 1]
ambiguous.sort(key=lambda kv: -len(kv[1]))
print(f"  ambiguous (first,last) keys: {len(ambiguous)}")
for k, v in ambiguous[:15]:
    print(f"  local={k}  -> {len(v)} distinct memorials: {sorted(v)[:5]}")