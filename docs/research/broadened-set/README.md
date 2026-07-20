# Broadened Civil War Training Set

## Why this exists

The original training set (575 soldiers with FaG URLs in the local
dixiedata DB) is **biased**:

- Heavily Oklahoma-CW-veteran
- Mostly men
- Mostly 1920s deaths
- Mostly hand-transcribed 19th-century records
- Skews toward common CW units

Patterns derived from this set may not generalize to other CW
populations. To build a more robust helper, we pulled a broader CW
dataset from `freecivilwarrecords.org`.

## Source

`freecivilwarrecords.org` ("Reveille") — free, public-domain CW
service records from NARA + soldier index from NPS CWSS.

- 5,040,436 soldier records
- 25.6M document images
- 47.26 TB of archives
- 6,550 regiments

Per-regiment CSVs available at:
`https://freecivilwarrecords.org/regiment/<code>/roster.csv`

## Scope

**22 regimental rosters pulled**, covering **~43,834 soldiers**:

| Side | State | Regiments |
|---|---|---|
| Confederate | Alabama | 1st, 5th, 10th, 15th, 19th, 25th |
| Confederate | Arkansas | 5th |
| Confederate | Florida | 1st |
| Confederate | Georgia | 10th |
| Confederate | Kentucky | 1st |
| Confederate | Louisiana | 5th |
| Confederate | Maryland | 1st |
| Confederate | Mississippi | 20th |
| Confederate | South Carolina | 5th |
| Confederate | Tennessee | 5th, 10th |
| Confederate | Texas | 10th |
| Union | Massachusetts | 54th (Colored) |
| Union | New York | 5th |
| Union | Ohio | 23rd |
| Union | Pennsylvania | 7th |
| Union | Tennessee | 10th |

**Confederate: 34,227 soldiers** | **Union: 9,607 soldiers**

## File layout

```
docs/research/broadened-set/
├── README.md                    ← this file
├── broadened_cw_training.csv    ← normalized 43,834-row training set
├── parse_output.txt             ← full output of build_broadened_set.py
├── match_output.txt             ← full output of match_broadened_to_local.py
└── rosters/                     ← 21 raw CSV rosters from freecivilwarrecords.org
```

## Key findings (Confederate only, n=34,227)

### First-name pattern distribution

| Pattern | Count | % | FaG slug impact |
|---|---|---|---|
| `full + initial` (William T.) | 11,277 | 33% | `first_m-last` |
| `single word` (William) | 8,623 | 25% | `first-last` |
| `double initial` (W. T.) | 11,095 | 32% | `first_m-last` (single-letter middle) |
| `single initial` (J.) | 1,975 | 5.8% | `first-last` |
| `two words` (Mary Jane) | 279 | 0.8% | `first_m_m-last` |
| `initial + full` (J. William) | 168 | 0.5% | tricky |

**49.3% of Confederate soldiers have a middle initial or middle name.**

This is **higher than our local OK-CW sample's 25% single-letter
middle rate.** The middlename strategy is more important than local
validation suggested.

### Surname apostrophe variants

185 distinct surnames contain apostrophes. Top:

| Surname | Count |
|---|---|
| O'Brien | 19 |
| O'Connor | 11 |
| O'Neal | 10 |
| O'Donnell | 8 |
| O'Hara | 6 |
| O'Neil | 6 |
| O'Neill | 5 |
| O'Sullivan | 5 |
| L'Hommedieu | 3 |
| O'Connell | 3 |
| O'Rourke | 3 |
| O'Conner | 3 |

Apostrophe handling is real — the helper should generate
`O'Brien`/`OBrien`/`Obrien` variants.

### Soundex clusters reveal confusable surnames

The top Soundex clusters in Confederate data:

| Soundex | # distinct names | Example names |
|---|---|---|
| M250 | 82 | Machen, Mackin, Macon, Maquoine, Mason |
| M200 | 66 | Macay, Macey, Mack, Mackey, Mackie |
| M245 | 60 | McCallen, McCallum, McCalmon (all `McCall-*`) |
| H200 | 55 | Haegis, Hago, Hague, Hagy |
| M252 | 54 | Mackingham, Maginnis, Magness |
| B650 | 41 | Barnum, Barron, Bernan, Berney |
| L500 | 42 | Lain, Lamei, Lamon, Lanahan, Lane |
| B620 | 40 | Barrise, Barrs, Beers, Bergess |

These clusters mean a single Confederate soldier with last name
`Machen` could be on FaG as `Machen`, `Mackin`, `Macon`, etc. Helper
must use phonetic expansion.

### Predicted FaG slug shape (Confederate, n=34,227)

| Shape | Count | % |
|---|---|---|
| `first-last` | 17,337 | 50.7% |
| `first_m-last` (single middle) | 16,573 | 48.4% |
| `first_m_m-last` (multi-part middle) | 306 | 0.9% |
| 4+ parts | 8 | <0.1% |

So the helper should expect **roughly half of CW soldiers have a
middle component in their slug**.

### Top surnames by state

See `parse_output.txt` for the full list. Highlights:

- **Smith** is the #1 surname in AL, AR, FL, MS, TX (Confederate)
- **Jones** is #1 in KY, TN
- **Moore** is #1 in SC
- **Brown** is #1 in LA
- **Maryland** has fewer very-common names (Smith is #1 at 11, then
  small counts) — likely reflects different naming origins (Irish,
  German).

## Match against local data

`scripts/analysis/match_broadened_to_local.py` joins our 1,147 local records
against the broadened set on `(last_name, first_initial,
state_from_unit)`.

**Match rate: 584/1147 = 50.9%** by (last + initial + state)

**Reasons for non-match:**

| Reason | Count |
|---|---|
| No broad match (last + initial) | 499 |
| State mismatch | 64 |

### What the state mismatches tell us

When the broadened set has the name in a *different* state than our
local unit says, we get a mismatch. This is actually useful signal —
it's the **state-drift phenomenon** where the same soldier name appears
across multiple states.

Examples:

- `William Looney` — local says 4th TN Cav, broadened has him in AL
- `John Newby` — local says 2nd TX Cav, broadened has him in MA
- `James Goad` — local says 1st TX Inf, broadened has no match
- `Rozell` family — local all in TX (10th/15th TX Cav), broadened
  doesn't have any

This implies the helper should:
1. Search the claimed state first (narrow)
2. If 0 results, broaden to other Confederate states
3. Use phonetic expansion to find variants

### Match cardinality distribution

| Matches per local record | Local records |
|---|---|
| 1 (high confidence) | 169 |
| 2 | 92 |
| 3 | 61 |
| 4 | 53 |
| 5+ | 25 |

When the broadened set has multiple matches, the helper should
disambiguate using middle name, then unit/company, then year.

## Limitations of this broadened set

- **No NPS CWSS data** — only NARA CMSR index. Officers and alternate
  names may be under-represented. **Path B (NPS pull) addresses this.**
- **Texas coverage thin** — only 10th TX (Nelson's) downloaded. Other
  TX regiments (1st, 5th, Hood's, etc.) not pulled.
- **No Virginia regiments** — VA was the largest CW state. Adding
  VA regiments should be a priority.
- **Enlisted-focused** — officers less represented in CMSR.
- **Surviving-regiment bias** — units that surrendered and were
  paroled (e.g., the entire Army of Northern Virginia) have
  disproportionately complete records.

## Reproducing

```bash
# 1. Re-download rosters (from project root):
mkdir -p C:/tmp/rosters
for code in CAL0001RI CAL0005RI CAL0010RI CAL0015RI CAL0019RI CAL0025RI \
            CMS0020RI CTN0005RI CTN0010RI CTX0010RI CGA0010RI CAR0005RI \
            CFL0001RI CSC0005RI CKY0001RI CLA0005RI CMD0001RI; do
  curl -sL -o "C:/tmp/rosters/${code}.csv" "https://freecivilwarrecords.org/regiment/${code}/roster.csv"
done
# Plus Union:
for code in UNY0005RI UTN0010RI UOH0023RI UMA0054RI00C UPA0007RI; do
  curl -sL -o "C:/tmp/rosters/${code}.csv" "https://freecivilwarrecords.org/regiment/${code}/roster.csv"
done

# 2. Build the normalized training set:
python scripts/ingest/build_broadened_set.py

# 3. Match against local records (requires local_soldiers_with_fag.csv):
python scripts/analysis/match_broadened_to_local.py
```

## Sources

- [freecivilwarrecords.org](https://freecivilwarrecords.org/) — Reveille project
- NARA Compiled Military Service Records (M-publication numbers per state)
- NPS Civil War Soldiers & Sailors System (surname index embedded in the rosters)