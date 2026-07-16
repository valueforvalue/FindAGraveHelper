#!/usr/bin/env python3
"""
Match broadened CW set against local dixiedata records.
Measures: how many of our 575 FaG-found soldiers can be matched to a
broadened roster soldier? If match is high, the broadened set is a
good proxy for the population we want to find.

Also: for non-matching local records, do their name patterns fall
outside the broadened set's distribution?
"""
import csv, re
from collections import Counter, defaultdict
from pathlib import Path

# Local records
local = list(csv.DictReader(Path('C:/tmp/fag_soldiers.csv').open(encoding='utf-8')))
print(f"Local records (soldiers with FaG URL): {len(local)}")

# Broadened
broad = list(csv.DictReader(Path('C:/tmp/broadened_cw_training.csv').open(encoding='utf-8')))
print(f"Broadened CW records: {len(broad)}")

def normalise(s):
    return re.sub(r"[^a-z]", "", (s or '').lower())

# Group broadened by (last, first initial)
broad_index = defaultdict(list)
for s in broad:
    last_norm = normalise(s['last_name'])
    fn = (s['first_name'] or '').strip()
    fn_clean = re.sub(r'\.', '', fn)
    fn_first = fn_clean.split()[0] if fn_clean else ''
    fn_first_norm = normalise(fn_first)
    if last_norm and fn_first_norm:
        key = (last_norm, fn_first_norm[0])  # (last, first-letter)
        broad_index[key].append(s)

print(f"Broadened index size (last, first-letter): {len(broad_index)}")

# For each local record, extract last + unit state abbreviation
unit_state_re = re.compile(r'\b([A-Z]{2})\b\s+(?:Infantry|Cavalry|Cav|Regiment|Rgmt|Battalion|Batn|Artillery|Arty)\b', re.I)
def extract_state(unit):
    if not unit: return ''
    m = unit_state_re.search(unit)
    return m.group(1) if m else ''

# Try matching each local record
match_count = 0
no_match = []
for r in local:
    ln = normalise(r['last_name'])
    fn = (r['first_name'] or '').strip()
    fn_clean = re.sub(r'\.', '', fn)
    fn_first_norm = normalise(fn_clean)
    if not ln or not fn_first_norm:
        no_match.append((r, 'no name'))
        continue
    state_abbr = extract_state(r['unit'])
    candidates = broad_index.get((ln, fn_first_norm[0]), [])
    if not candidates:
        no_match.append((r, 'no broad match (last+initial)'))
        continue
    # Filter by state if known
    state_matches = [c for c in candidates if c['regiment_state'] == state_abbr] if state_abbr else candidates
    if state_matches:
        match_count += 1
    else:
        no_match.append((r, f'state mismatch (local={state_abbr}, broad candidates from {set(c["regiment_state"] for c in candidates)})'))

print(f"\nMatched (last+initial+state): {match_count}/{len(local)} = {match_count/len(local)*100:.1f}%")
print(f"No match: {len(no_match)}")
print("\n=== Reasons for no-match (top 10) ===")
reason_counter = Counter(n[1].split(' (')[0] for n in no_match)
for r, c in reason_counter.most_common(10):
    print(f"  {c:4} {r}")

# Look at 20 no-match samples
print("\n=== 20 sample no-match records ===")
for r, reason in no_match[:20]:
    print(f"  local=({r['first_name']:15}, {r['last_name']:15}) unit={r['unit']:30} reason={reason[:60]}")

# For matched records, what state distribution do they pull from?
print("\n=== For matches: which state does the broad match come from? ===")
match_state_counter = Counter()
for r in local:
    ln = normalise(r['last_name'])
    fn = (r['first_name'] or '').strip()
    fn_clean = re.sub(r'\.', '', fn)
    fn_first_norm = normalise(fn_clean)
    state_abbr = extract_state(r['unit'])
    if not ln or not fn_first_norm: continue
    candidates = broad_index.get((ln, fn_first_norm[0]), [])
    state_matches = [c for c in candidates if c['regiment_state'] == state_abbr] if state_abbr else candidates
    if state_matches:
        for c in state_matches:
            match_state_counter[c['state']] += 1

for st, c in match_state_counter.most_common(20):
    print(f"  {c:5} {st}")

# How many distinct broadened soldiers match each local soldier?
# (1 match = best; multiple matches = needs disambiguation)
print("\n=== Matches-per-local distribution ===")
match_per_local = []
for r in local:
    ln = normalise(r['last_name'])
    fn = (r['first_name'] or '').strip()
    fn_clean = re.sub(r'\.', '', fn)
    fn_first_norm = normalise(fn_clean)
    state_abbr = extract_state(r['unit'])
    if not ln or not fn_first_norm: continue
    candidates = broad_index.get((ln, fn_first_norm[0]), [])
    state_matches = [c for c in candidates if c['regiment_state'] == state_abbr] if state_abbr else candidates
    if state_matches:
        match_per_local.append(len(state_matches))

match_per_local_counter = Counter(match_per_local)
for n, c in sorted(match_per_local_counter.items())[:10]:
    print(f"  {c:4} local records matched {n} broad soldiers")