# Civil War Genealogy Search Tactics

A practical playbook distilled from CW genealogy guides, NPS/Fold3
documentation, and FamilySearch wiki articles.

## 1. Name traps to build into the search loop

### Historical abbreviations are real names

Treat these as separate searchable names, not as transcription errors:

| Abbreviation | Full name |
|---|---|
| `Wm`, `Wms`, `Will` | William |
| `Jas` | James |
| `Thos` | Thomas |
| `Jno` | John |
| `Chas` | Charles |
| `Geo` | George |
| `Robt`, `Rob` | Robert |
| `Saml` | Samuel |
| `Benj` | Benjamin |
| `Danl` | Daniel |

Source: [FamilySearch Abbreviations](https://www.familysearch.org/en/wiki/Abbreviations_Found_in_Genealogy_Records)

### Generate variants for initials

A soldier may appear as any of:
- `J Smith`, `J. Smith`, `John Smith`, `John S Smith`
- A middle name used as the first name (enlistment alias)
- NPS preserves alternate names and misspellings as originally
  documented; explicit "Alternate Name" fields exist on cards.

### Apostrophes and hyphens

Search both forms of every name:
- `O'Brien`, `Obrien`, `OBrien`, `O Brien`
- `O'Neal`, `Oneal`, `ONeal`
- `St. John`, `St John`, `Stjohn`, `Saint John`
- `Van Buren`, `Vanburen`, `VanBuren`
- `De La Cruz`, `Delacruz`

FaG disallows most special characters but supports `?` (one char) and
`*` (zero or more) wildcards. So for `O'Brien`, try `OBrien`,
`O?Brien`, `O*Brien`.

### Maiden-name hyphenated

A woman may appear under any of:
- `Nancy Powers` (married name)
- `Nancy Blue` (maiden name)
- `Nancy Blue-Powers` (maiden-married hyphenated)
- `Nancy B. Powers` (maiden initial)

FaG has an **Include maiden name** option (`maidenname=true`).

### Mother's maiden name as middle

A middle name may be the mother's maiden surname. Test:
- `William Carter Smith`, `William C. Smith`, `William Smith`, `Carter Smith`

Treat the naming pattern as a lead, not proof.

### Formerly enslaved people

Pre-1865 records may show only a given name, an enslaver-associated
identifier, or no surname. After emancipation, the person might adopt
a new surname—and might change it again. Search postwar surnames, given
name + county/enslaver, and USCT pension/service records.

### Aliases

Preserve "known as," nickname, and enlistment aliases. A soldier could
enlist under a middle name, nickname, or alias. Search both names and
look for NPS/Fold3 alternate-name references.

## 2. Records and tactical use

### NPS Civil War Soldiers & Sailors System

It is an **index**, not a service file. Gives name, side, unit,
company, rank-in, rank-out, alternate name, source information. Search
by state/side/unit when known, then test name variants.

- [NPS search](https://www.nps.gov/civilwar/search-soldiers.htm)
- 6.3 million index cards for ~3.5 million soldiers.
- FamilySearch Civil War Soldiers Index is complementary:
  [collection 1910717](https://www.familysearch.org/search/collection/1910717)

### Fold3 CMSR

Compiled Military Service Records organized **state → unit →
company/name**. Browse the publication rather than relying only on
global keyword search. A CMSR is normally one jacket per soldier per
regiment and may contain muster-roll abstracts, enlistment/discharge,
hospital, prison, parole, casualty, or personal papers.

- **Rank-in** = rank at enlistment or beginning of that regiment's
  service.
- **Rank-out** = final rank when leaving that regiment. NOT necessarily
  the soldier's highest rank. Transfers/re-enlistments create separate
  records.

### Confederate pensions

NARA does not hold the state Confederate pension files. The veteran
or widow generally applied in the state where they lived **when
applying**, not necessarily the state of service. Search every
plausible postwar residence. Files often provide wife/widow, children,
residence, service, age, death date, sometimes burial location.

- [NARA state-by-state guide](https://www.archives.gov/research/military/civil-war/confederate-pension-records)

### Confederate soldiers' homes

Many CW vets ended up in state-run homes. Search late-life residences:

| Home | Years | Approx residents |
|---|---|---|
| Beauvoir, Biloxi MS | 1903–1957 | 1,845 men and women |
| R.E. Lee Camp, Richmond VA | 1885–1941 | ~300 peak |
| Missouri Confederate Home, Higginsville | 1891–1950 | ~380 peak annual |
| Confederate Woman's Home, Austin TX | 1908–1963 | 80–110 in 1920s–30s |
| Oklahoma Confederate Home, Ardmore | 1911–1942 | ~85 |
| Pewee Valley KY | 1902–1934 | 700+ |
| Tennessee Soldiers' Home, Hermitage | 1892–1933 | ~125 capacity |
| Jacksonville FL | 1893–1938 | ~16 in 1930 |
| Atlanta GA | 1902–~1941 | — |

Source: [FamilySearch Confederate Soldiers Home Records](https://www.familysearch.org/en/wiki/Confederate_Soldiers_Home_Records)

### Headstone records

The correct acronym is **OQMG** (Office of the Quartermaster General),
not HQGM. Federal M1847 cards (Union, 1879–1903). OQMG applications
M1916 (1925–1941), M2113 (1941–1949) include some Confederate veterans.
Confederate markers authorized in national cemeteries 1906, private
cemeteries 1929.

[Headstone records PDF](https://www.archives.gov/files/research/military/veterans/headstones-nonfederal-cemeteries.pdf)

### 1890 Union Veterans Census

The 1890 census was destroyed but surviving special Union-veteran
schedules cover many states. They show rank, company, regiment/vessel,
enlistment/discharge dates, length of service, address, disability.
Primarily for Union vets/widows. [NARA surviving-state list](https://www.archives.gov/research/census/1890)

## 3. Recommended search order (from working genealogists)

1. Establish 1860 residence, postwar residence, spouse, realistic
   birth estimate.
2. Search obituary, county history, cemetery transcription, GAR/UCV
   marker, relatives' memorials for a unit.
3. If unit known, search **state + unit + name** in NPS/Fold3. If
   unknown, search NPS by name variants plus side/state.
4. Search FaG with birth year **±5 first**, then ±1/±2 for
   disambiguation—not ±25 unless the date is genuinely uncertain.
5. Verify the candidate in CMSR, pension, soldier-home, headstone,
   census records.
6. For a known mother's maiden surname, repeat searches with it as
   middle name, middle initial, and surname.

## 4. Disambiguation (when multiple results match)

Require more than name and dates. Prioritize:

1. **Same unit/company and side.** Strongest signal.
2. **Middle name or initial.** Strong.
3. **Birth year within ±2.** Moderate.
4. **Spouse/widow and postwar residence.** Strong.
5. **Burial state/county and death date.** Moderate.

FaG is user-contributed discovery evidence, not final proof.

## 5. Find a Grave URL tricks

- `/memorial/<id>/<slug>` — main memorial URL
- `/memorial/<id>/<slug>/photo` — photo tab
- `#add-to-vc` — anchor for Virtual Cemetery
- Bio searches support Boolean + wildcards (see findagrave-params/)

## 6. Useful walkthroughs

- [Brian Rhinehart, Genealogy TV](https://www.youtube.com/watch?v=V_b1nSe4aUc) —
  case study of "William Smith" using NPS, cemetery evidence,
  Ancestry/Fold3 pension indexes, census records.
- [Finding the Soldiers](https://wagsnetn.org/wp-content/uploads/2018/11/Finding-the-Soldiers.pdf) —
  real Confederate workflow: TN pensions → FamilySearch → Fold3 CMSR →
  FaG → Ancestry.
- [A Connecticut Confederate at Gettysburg](https://bportlibrary.org/hc/veterans-and-wars/a-connecticut-confederate-at-gettysburg/) —
  Theophilus Judd case combining Fold3 CMSR, Ancestry research,
  newspapers, cemetery records, FaG.

## Implications for the helper script

The script should:

1. **Generate abbreviation variants** of first names (Wm, Jas, Thos, etc.)
   and search each.
2. **Generate apostrophe variants** of last names (O'Brien, OBrien, Obrien).
3. **Generate maiden-name variants** for women (last only, last-maiden
   hyphenated, maiden only with `maidenname=true`).
4. **Try unit+state first** when local data has it (10x narrower than
   name-only).
5. **Anchor on birth ±5 first**, not ±25.
6. **Disambiguate** by middle initial, then by unit/state, then by year.

## Sources

- [NPS Civil War Soldiers search](https://www.nps.gov/civilwar/search-soldiers.htm)
- [FamilySearch CW Soldiers Index](https://www.familysearch.org/search/collection/1910717)
- [Fold3 CMSR overview](https://www.fold3.com/blog/compiled-military-service-records-of-the-civil-war/)
- [NARA Confederate Pensions](https://www.archives.gov/research/military/civil-war/confederate-pension-records)
- [FamilySearch Confederate Soldiers Home Records](https://www.familysearch.org/en/wiki/Confederate_Soldiers_Home_Records)
- [Beauvoir Veteran Project](https://beauvoirveteranproject.org/data/data/)
- [Library of Virginia — R.E. Lee Camp](https://lva-virginia.libguides.com/lee-home)
- [Missouri Confederate Memorial](https://mostateparks.com/parks/confederate-memorial-hs/general-information-confederate-memorial)
- [TSHA Confederate Woman's Home Austin](https://www.tshaonline.org/handbook/entries/confederate-womans-home)