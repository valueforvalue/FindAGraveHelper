# Local Data Analysis — `dixiedata` CW Soldiers with FaG URLs

## Source

Database: `C:/Development/dixiedata/.dixiedata/dixiedata.db`
(separate project — see that repo for context).

Query that produced the working data:

```sql
SELECT s.id AS s_id, s.display_id, s.first_name, s.middle_name, s.last_name,
       IFNULL(s.prefix,''), IFNULL(s.suffix,''), IFNULL(s.birth_date,''),
       IFNULL(s.death_date,''), IFNULL(s.death_year,''), IFNULL(s.buried_in,''),
       IFNULL(s.unit,''), IFNULL(s.pension_state,''), r.record_type,
       IFNULL(r.app_id,''), IFNULL(r.details,'')
FROM soldiers s
JOIN records r ON r.person_record_id = s.id
WHERE r.record_type LIKE '%rave%' OR r.details LIKE '%findagrave%' OR r.app_id LIKE '%findagrave%';
```

Output: `local_soldiers_with_fag.csv` (1,147 rows = 575 unique soldiers × multiple FaG records each).

## Key findings

### Slug shape distribution (n=577)

The FaG memorial URL has a "slug" component that encodes the soldier's
name. The shape of the slug determines what search parameters will
match it.

| Shape | Example | Count | % |
|---|---|---|---|
| `first_last` (no middle in slug) | `william_looney` | 13 | 2.3% |
| `first_middle-last` (hyphen-joined middle) | `william_pickney-looney` | 471 | 81.6% |
| `first-last` (no underscore, only hyphen) | `greenberry-rozell` | 92 | 15.9% |
| `first_m_middle-last` (multi-part middle) | `jesse_carter_farrar-pruitt` | 14 | 2.4% |

**The slug embeds the middle name 84% of the time.** The current
helper only sends `firstname` + `lastname`. This is the single biggest
gap in hit-rate.

### First-name match rate

- 474/577 (82.1%) slug first matches local first exactly
- 92 records have no local first name (we found this is rare in our DB —
  but common in real-world genealogy data)
- 16 records where slug first differs from local first
  (`E.` ↔ `edward`, `Capt` ↔ `burton`, `Chief` ↔ `samuel` — titles as
  first name)

### Last-name match rate

- 558/577 (96.7%) slug last matches local last exactly
- 19 records differ (transcription drift): `Rozell`↔`Rozzell`,
  `Dooley`↔`Dooleyd`, `St. John`↔`john`, `Harris Sr.`↔`harris`

### Middle-name presence

- 522/577 (90.5%) local records have a populated middle name
- 145/577 (25.1%) have a single-letter middle (`H.`, `W.`, etc.)
- Top full middle names: Washington (14), Jackson (12), Henry (11),
  Monroe (6), Franklin (5), William (5)

### Date coverage

- 100% have `birth_date` (mostly `MM/DD/YYYY` format)
- 100% have `death_year`
- 95.7% have `buried_in` (location)
- 80.1% have `unit` (e.g. `Co. I, 4th TN Cav. Rgmnt., C.S.A.`)

### Death-year distribution

| Decade | Count |
|---|---|
| 1890s | 33 |
| 1900s | 100 |
| **1910s** | **170** ← peak |
| **1920s** | **173** ← peak |
| 1930s | 74 |
| 1940s | 12 |

CW-era vets who survived into old age. The peak death decade for our
sample is 1910s–1920s.

### Data quality issues surfaced

- **10 records** have `last_name='VETERAN'` (legacy placeholder; actual
  surname is in `middle_name`). Example:
  `Capt VETERAN James Jackson McAlester` → real last = `McAlester`.
- **3 records** have `birth_date='00/00/0000'` (unknown year).
- **2 records** have `prefix='Mrs.'` (widow records, not the soldier).
- **Suffixes in last-name field**: `Harris Sr.`, `VETERAN`.

### Validation: v5 strategy ladder vs local data

The proposed v5 strategy ladder (see `../v5-design/strategy-ladder.md`)
was replayed against all 577 (soldier, memorial) pairs as if we were
cold-starting (no prior FaG URL).

| After strategy | Cumulative hit-rate |
|---|---|
| Strategy 1 (exact sniper) | 92.9% (536/577) |
| + Strategy 2 (middlename-initial) | **97.1% (560/577)** |
| + Strategy 3 (first-initial exact) | 93.2% |
| + Strategy 4 (first-initial + fuzzy) | 98.8% |
| + Strategy 5 (fuzzy last only) | 99.5% |
| + Strategy 6 (CW context) | 100.0% |

The middlename strategy recovers 24 of 41 exact-sniper failures.
This validates it as the highest-impact addition.

## Files in this directory

- `local_soldiers_with_fag.csv` — raw export (1,147 rows)
- `local_fag_records.csv` — original `records` table query (records joined
  to soldiers, raw form)
- `local_soldiers_with_fag.csv` — cleaned/sanitized version with stable
  column ordering for analysis
- `analysis_output.txt` — full output of `scripts/analysis/analyze_local_db.py`
- `validation_results.md` — full strategy-ladder validation results

## Reproducing

```bash
# From project root (assuming dixiedata DB at C:/Development/dixiedata/.dixiedata/dixiedata.db):
cd C:/Development/dixiedata
sqlite3 -header -csv .dixiedata/dixiedata.db "<see query above>" > C:/tmp/fag_soldiers.csv

# Then run analysis (scripts moved to scripts/analysis/ subpackage):
python scripts/analysis/analyze_local_db.py
python scripts/analysis/analyze_slug_shapes.py
python scripts/analysis/validate_v5_ladder.py
```