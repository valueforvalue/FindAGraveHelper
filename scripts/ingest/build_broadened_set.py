#!/usr/bin/env python3
"""
Build broadened CW training set from freecivilwarrecords.org rosters.

Confederate priority — 17 Confederate rosters across 11 states.
Plus 5 Union rosters for name-pattern diversity.
"""
import csv, re, sys
from pathlib import Path
from collections import Counter, defaultdict

# ALL rosters — auto-detect from filenames
ROSTERS = []
for path in sorted(Path('C:/tmp/rosters').glob('*.csv')):
    fn = path.name
    # 19AL_Infantry_Conf.csv or 1AL_Conf.csv
    m = re.match(r'(\d+)([A-Z]{2})_(?:Infantry_)?Conf\.csv', fn)
    if m:
        num, st = m.groups()
        side = 'Confederate'
    else:
        m = re.match(r'(\d+)([A-Z]{2})_Infantry\.csv', fn)
        if m:
            num, st = m.groups()
            side = 'Union'
        else:
            continue
    state_map = {'AL':'Alabama','AR':'Arkansas','FL':'Florida','GA':'Georgia',
                 'KY':'Kentucky','LA':'Louisiana','MD':'Maryland','MA':'Massachusetts',
                 'MS':'Mississippi','MO':'Missouri','NY':'New York','NC':'North Carolina',
                 'OH':'Ohio','PA':'Pennsylvania','SC':'South Carolina','TN':'Tennessee',
                 'TX':'Texas','VA':'Virginia'}
    state = state_map.get(st, st)
    unit_name = f"{num}{ {'AL':'st','AR':'th','FL':'st','GA':'th','KY':'st','LA':'th','MD':'st',
                          'MA':'th','MS':'th','MO':'th','NY':'th','NC':'th','OH':'th','PA':'th',
                          'SC':'th','TN':'th','TX':'th','VA':'th'}.get(st,'th')} {state} Infantry"
    ROSTERS.append((str(path), side, state, unit_name, num, st))

print(f"Rosters to process: {len(ROSTERS)}")
for path, side, state, unit, num, st in ROSTERS:
    print(f"  {side:12} {unit}")

# Each roster has ~7 lines of header before the data starts
SKIP_LINES = 7

all_soldiers = []

for path, side, state, unit_name, num, st in ROSTERS:
    with open(path, encoding='utf-8-sig') as f:
        # Skip 6 lines of preamble, leaving the header line for DictReader
        for _ in range(SKIP_LINES - 1):
            f.readline()
        reader = csv.DictReader(f)
        n_in = 0
        for row in reader:
            last = (row.get('Last name') or '').strip()
            first = (row.get('First name') or '').strip()
            if not last:
                continue
            rank = (row.get('Rank') or '').strip()
            company = (row.get('Company') or '').strip()
            regiment = (row.get('Regiment') or '').strip()
            side_actual = (row.get('Side') or '').strip() or side
            state_actual = (row.get('State') or '').strip() or state
            nara_id = (row.get('NARA ID') or '').strip()
            soldier_page = (row.get('Soldier page') or '').strip()
            record_type = (row.get('Record type') or '').strip()

            all_soldiers.append({
                'last_name': last,
                'first_name': first,
                'rank': rank,
                'company': company,
                'regiment': regiment,
                'side': side_actual,
                'state': state_actual,
                'unit_name': unit_name,
                'regiment_num': num,
                'regiment_state': st,
                'nara_id': nara_id,
                'soldier_page': soldier_page,
                'record_type': record_type,
                'source_roster': path,
            })
            n_in += 1
    print(f"  {unit_name:40} {side:12} parsed {n_in} soldiers")

print(f"\nTotal broadened soldiers: {len(all_soldiers)}")

# Save
out_path = Path('C:/tmp/broadened_cw_training.csv')
fieldnames = ['last_name', 'first_name', 'rank', 'company', 'regiment', 'side',
              'state', 'unit_name', 'regiment_num', 'regiment_state', 'nara_id',
              'soldier_page', 'record_type', 'source_roster']
with open(out_path, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(all_soldiers)
print(f"\nWrote {out_path} ({len(all_soldiers)} rows)")

# Side split
conf_only = [s for s in all_soldiers if s['side'] == 'Confederate']
union_only = [s for s in all_soldiers if s['side'] == 'Union']
print(f"\nConfederate: {len(conf_only)}")
print(f"Union:       {len(union_only)}")

# ============================================================
# NAME PARSING
# ============================================================
print("\n=== First-name parsing patterns ===")
first_patterns = Counter()
multi_part_first = []
for s in all_soldiers:
    fn = s['first_name']
    if not fn:
        first_patterns['(empty)'] += 1
        continue
    if re.fullmatch(r"[A-Z]\.?", fn):
        first_patterns['single initial (J.)'] += 1
    elif re.fullmatch(r"[A-Z][a-z]+", fn):
        first_patterns['single word (William)'] += 1
    elif re.fullmatch(r"[A-Z]\. ?[A-Z]\.?", fn):
        first_patterns['double initial (W. T.)'] += 1
    elif re.fullmatch(r"[A-Z][a-z]+ [A-Z]\.", fn):
        first_patterns['full + initial (William T.)'] += 1
    elif re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", fn):
        first_patterns['two words (Mary Jane)'] += 1
        multi_part_first.append(fn)
    elif re.fullmatch(r"[A-Z]\. ?[A-Z][a-z]+", fn):
        first_patterns['initial + full (J. William)'] += 1
    else:
        first_patterns[f'other: {fn[:15]}'] += 1

for k, v in first_patterns.most_common(15):
    print(f"  {v:5} {k}")

print(f"\n=== Two-word first names (Confederate, first 30) ===")
conf_multi = [fn for s in conf_only for fn in [s['first_name']] if re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", fn or '')]
for fn in conf_multi[:30]:
    print(f"  {fn}")

# Surname patterns
print("\n=== Surname patterns (all) ===")
surname_patterns = Counter()
hyphenated = []
apostrophe = []
space = []
for s in all_soldiers:
    ln = s['last_name']
    if not ln:
        continue
    if '-' in ln:
        surname_patterns['hyphenated'] += 1
        hyphenated.append(ln)
    elif "'" in ln:
        surname_patterns["apostrophe"] += 1
        apostrophe.append(ln)
    elif ' ' in ln:
        surname_patterns['space'] += 1
        space.append(ln)
    else:
        surname_patterns['plain'] += 1

for k, v in surname_patterns.most_common():
    print(f"  {v:5} {k}")

# Confederate-specific name quirks
print("\n=== Confederate-specific first-name patterns ===")
conf_first_patterns = Counter()
for s in conf_only:
    fn = s['first_name']
    if not fn:
        conf_first_patterns['(empty)'] += 1
        continue
    if re.fullmatch(r"[A-Z]\.?", fn):
        conf_first_patterns['single initial'] += 1
    elif re.fullmatch(r"[A-Z][a-z]+", fn):
        conf_first_patterns['single word'] += 1
    elif re.fullmatch(r"[A-Z][a-z]+ [A-Z]\.", fn):
        conf_first_patterns['full + initial'] += 1
    elif re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", fn):
        conf_first_patterns['two words'] += 1
    elif re.fullmatch(r"[A-Z]\. ?[A-Z][a-z]+", fn):
        conf_first_patterns['initial + full'] += 1
    else:
        conf_first_patterns[f'other: {fn[:15]}'] += 1

for k, v in conf_first_patterns.most_common(10):
    print(f"  {v:5} {k}")

# ============================================================
# PHONETIC clusters — which surnames likely match on FaG fuzzy
# ============================================================
def soundex(name):
    name = re.sub(r"[^A-Za-z]", "", name).upper()
    if not name:
        return ""
    code = name[0]
    mapping = {'BFPV': '1', 'CGJKQSXZ': '2', 'DT': '3', 'L': '4', 'MN': '5', 'R': '6'}
    for c in name[1:]:
        for k, v in mapping.items():
            if c in k:
                if code[-1] != v:
                    code += v
                break
    code = code[0] + ''.join(c for c in code[1:] if not c.isalpha())
    return code.ljust(4, '0')[:4]

print("\n=== Soundex clusters — Confederate only (top 15) ===")
conf_sx = defaultdict(set)
for s in conf_only:
    sx = soundex(s['last_name'])
    if sx:
        conf_sx[sx].add(s['last_name'])

top_conf_sx = sorted(conf_sx.items(), key=lambda kv: -len(kv[1]))[:15]
for sx, names in top_conf_sx:
    distinct = sorted(names)[:6]
    print(f"  SX {sx}: {len(names):3} names | {distinct}")

# ============================================================
# Top surnames by state
# ============================================================
print("\n=== Top 10 surnames by Confederate state ===")
states = sorted(set(s['state'] for s in conf_only))
for st in states:
    st_surnames = Counter(s['last_name'] for s in conf_only if s['state'] == st)
    top = st_surnames.most_common(10)
    print(f"\n  [{st}] ({sum(st_surnames.values())} soldiers)")
    for sn, c in top:
        print(f"    {c:4} {sn}")

# ============================================================
# FA-G SLUG PREDICTION — what slug would each soldier's
# CMSR name produce?
# ============================================================
print("\n=== Predicted FaG slug shape distribution ===")
slug_shapes = Counter()
for s in all_soldiers:
    fn = (s['first_name'] or '').strip()
    ln = (s['last_name'] or '').strip()
    if not fn or not ln:
        slug_shapes['(skip — empty first or last)'] += 1
        continue
    fn = re.sub(r'\.', '', fn)
    parts = fn.split()
    if len(parts) == 1:
        slug_shapes['first-last'] += 1
    elif len(parts) == 2:
        slug_shapes['first_m-last'] += 1
    else:
        slug_shapes[f'first_m_m_m...-last ({len(parts)} parts)'] += 1

for k, v in slug_shapes.most_common(10):
    print(f"  {v:5} {k}")

# Examples of multi-part first names — these become 3+ part slugs
print("\n=== Multi-part first names that produce complex slugs (Conf, first 20) ===")
conf_complex = [s for s in conf_only if len(re.sub(r'\.', '', s['first_name'] or '').split()) >= 3]
for s in conf_complex[:20]:
    print(f"  {s['first_name']:25} {s['last_name']:20} {s['state']}")