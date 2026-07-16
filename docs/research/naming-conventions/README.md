# Civil War Era Naming Conventions

## Southern naming culture, 1800–1860

Middle names became customary among Americans during the 19th century
and were nearly universal by 1900. Our local sample's 90% middle-name
rate is consistent with this broader trend.

### Honorific middle names (very common)

| Name | Frequency in local sample | Likely origin |
|---|---|---|
| Washington | 14 | George Washington, Revolution, national identity |
| Jackson | 12 | Andrew Jackson (general + president) |
| Henry | 11 | Patrick Henry (Virginia orator); also established given name |
| Monroe | 6 | President Monroe |
| Franklin | 5 | Benjamin Franklin; also established given name |
| Jefferson, Madison, Lee, Harrison | — | Presidents, generals, national figures |

A Chesapeake study found nearly 40% of families gave a son some form
of "Washington" name. Treat Washington, Jackson, Franklin as
honorific **clues**, not proof of kinship.

### Functions of middle names

- **Maternal or grandmother's maiden surname.** Increasingly common in
  the 19th century; preserves a maternal line. Example: *John Mauldin
  Reeves* preserved his grandmother's Mauldin surname.
- **Father's or grandfather's given name.** Patronymic-like practice;
  no uniform system but consistent regionally.
- **Hero, president, minister, or local notable.** Honorific.
- **Jr./Sr./III/IV.** Historically often distinguished two same-named
  men in one community. Did **not** necessarily mean father and son.
  Roman numerals generally indicate a continuing namesake line.

Sources:
- [Family Tree Magazine](https://familytreemagazine.com/names/researching-ancestors-middle-names/)
- [Genfiles — middle names](https://genfiles.com/articles/middle-names/)
- [Genfiles — Jr/Sr suffixes](https://genfiles.com/articles/senior-junior/)
- [Family Locket — Southern naming patterns](https://familylocket.com/analyzing-naming-patterns-a-southern-united-states-example/)

## Confederate and Union Homes

Many CW vets ended up in state-run homes. Search late-life residence
and home registers.

| Home | Years | Approx total served |
|---|---|---|
| Beauvoir, Biloxi MS | 1903–1957 | 1,845 men + women |
| R.E. Lee Camp, Richmond VA | 1885–1941 | ~300 peak; 2,800+ applications |
| Missouri Confederate Home, Higginsville | 1891–1950 | 1,600+ veterans/widows/children |
| Confederate Woman's Home, Austin TX | 1908–1963 | 3,400+ women served |
| Oklahoma Confederate Home, Ardmore | 1911–1942 | ~85 opening complement |
| Atlanta GA | 1902–~1941 | veteran registers 1901–1941 |
| Pewee Valley KY | 1902–1934 | 700+ veterans; 313 buried in home cemetery |
| Tennessee Soldiers' Home, Hermitage | 1892–1933 | ~700 served; 125 capacity; 487 buried in cemetery |
| Jacksonville FL | 1893–1938 | ~16 in 1930 |

Applications can include birth data, enlistment, rank/unit,
relatives, death date, burial.

Source: [FamilySearch Confederate Soldiers' Home Records](https://www.familysearch.org/en/wiki/Confederate_Soldiers_Home_Records)

## Service-record naming quirks

### CMSR master index (Confederate)

Alphabetical by surname. Cards show name, rank, unit.
**Cross-reference cards identify alternate spellings.** NPS preserves
alternate names and misspellings as originally documented; may
display "Alternate Name" such as `D.A./Bishop` or `David/Bishop`.

Source: [NARA CMSR](https://www.archives.gov/research/military/army/compiled-military-service-records)

### Search `Wms`, `Wm`, `William`, initials separately

CMSRs were transcribed from period documents, not standardized modern
biographies.

### Union widow pension files

Commonly include the widow's maiden name.

### Confederate pensions

State-held, not NARA. Apply in the state of **postwar residence**, not
necessarily the state of service. NARA directs researchers to state
repositories.

### Headstone applications

Record the requested name, rank, company/regiment, cemetery, dates.
Compare against the inscription and service record rather than treating
one as definitive.

## Units and sides

Normalize all forms to structured fields:
`Company K | 19th | Alabama | Infantry`

So `Co. K, 19th Alabama Infantry Regiment`, `19th AL Inf.`, and
`19th Alabama` should match. FaG's state selector uses full names
(e.g. **Alabama**); local transcriptions and URLs may use `AL`. NPS
records use full state and unit names.

A single person may produce multiple Union/Confederate entries
because of transfers, two names, spelling variants, or post-capture
Federal service ("Galvanized Yankees"). NPS notes 6.3M index cards
for ~3.5M actual soldiers.

## Name normalization and married names

Generate variants by removing or restoring punctuation and spaces:

| Local | FaG-friendly variants |
|---|---|
| `O'Brien` | `OBrien`, `Obrien`, `O Brien`, `O?Brien` |
| `St. John` | `St John`, `StJohn`, `Stjohn`, `Saint John` |
| `Van Buren` | `Vanburen`, `Van Buren`, `VanBuren` |
| `De La Cruz` | `Delacruz`, `De La Cruz`, `DeLaCruz` |

FaG recommends preserving known apostrophes/hyphens, but also
supports similar-spelling searches.

Search women under **married and maiden names**. Widows are often
indexed under the husband's surname; pension, obituary, probate, and
home records may supply the maiden name.

Treat forms such as `Carter-Powers` as an additional searchable
variant, not automatically as the person's original legal format.

## Implications for the helper script

1. **Honorific middles** are real name data. The script should send
   them, not strip them.
2. **Confederate Home records** are searchable. Add a context filter
   that uses `bio="Confederate Home" OR "Beauvoir" OR "Higginsville"`.
3. **Service-record alternate names** mean the helper should expand
   the local name into a variant list, not just one query.
4. **Maiden/married name variants** should be tried for women (with
   `maidenname=true`).
5. **Normalize unit parsing** to extract `(Company, Number, State,
   Type)` so a `bio` filter can target the unit.