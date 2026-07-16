# Find a Grave `/memorial/search` Parameter Reference

All parameters below were **verified live** against
`findagrave.com/memorial/search` by constructing URLs and reading the
result counts and refinement chips. The form is JS-rendered, so the
canonical input names come from the JS bundle; static `<form>` scraping
was unrevealing — these are the names actually accepted by the endpoint.

## Verified Parameters

### Person name

| Param | Example value | Effect | Notes |
|---|---|---|---|
| `firstname` | `John` | matches given name (incl. middle) | **Required to be ≥2 chars** (server-enforced... actually: server-side enforcement was relaxed in 2026; 1-char inputs are accepted) |
| `middlename` | `Jacob` | adds middle-name refinement | 1,788 results for `John Jacob Smith` |
| `lastname` | `Smith` | matches ALL surnames (maiden, married, alternate) | search help: "will search all names in the last name field" |
| `exactspelling` | `true` | disable fuzzy | |
| `fuzzyNames` | `true` | enable "Similar name spellings" | 8,700 results with vs. 97,283 without |
| `maidenname` | `true` | include maiden-name matches | for women |
| `nickname` | `true` | include nicknames | |
| `titles` | `true` | include titles (Dr., Rev., etc.) | |

### Dates (year-only precision)

- `birthyear`, `birthyearfilter` — filter values: `exact`, `before`, `after`, `1`, `3`, `5`, `10`, `25`, `unknown`
- `deathyear`, `deathyearfilter` — same buckets
- `datefilter` = `24h | 7d | 30d | 90d | 90dplus` — **added in last N** (NOT death date)

### Direct lookup (gold paths)

- `memorialid` — exact ID; bypasses name search
- `cemeteryid` / `cemeteryId` — narrow to one cemetery (both casings work)
- `cemeteryName` — free-text camelCase cemetery filter
- `contributorid` — contributor's memorials

### Other flags

- `bio` — full-text bio search with Boolean ops: `(a) AND (b)`, `(a) OR (b)`, `(a) NOT (b)`, quoted phrases, `?` and `*` wildcards
- `plot` + `plotinfo=true` — plot text + "with plot info"
- `isVeteran=true` — veteran only
- `famous`, `sponsored`, `cenotaph`, `monument`, `noncemetery` — memorial-type flags
- `nophoto`, `hasphoto`, `gps`, `nogps`, `hasflowers` — content flags

### Pagination & sort

- `page` — 1-indexed, 20/page, **hard cap at 500 pages (~10K results)**
- `sort` — `relevance`, `birthDate`, `deathDate`, `firstName`, `cemeteryName`, `created`, `updated`, `plot`
- `order` — `asc|desc`
- `condensed` — list view without thumbs

### NOT in URL (JS-only state)

- `stateId` / `countyId` — does not filter when set directly. Location
  widget uses internal API IDs that are not URL-persistent.
- `location` — display-only label, doesn't filter

### Bot friction

- PerimeterX bot detection.
- 1–2 req/sec with realistic UA/Referer is OK for hundreds of pages.
- Sustained scraping will trigger CAPTCHA.

## Confirmed working URL example

```
https://www.findagrave.com/memorial/search?
  firstname=William&
  middlename=Pickney&
  lastname=Looney&
  exactspelling=true&
  birthyear=1825&
  birthyearfilter=5&
  isVeteran=true&
  bio="Civil War" OR "CSA"
```

## What this means for the helper script

The current `FindaGraveIterativeHelper.user.js` uses only:
- `firstname`
- `lastname`
- `fuzzyNames` (always)
- `isVeteran` (sometimes)
- `bio` (sometimes)
- `birthyear` + `birthyearfilter` (sometimes)

**It does NOT use:**
- `middlename` ← biggest gap
- `exactspelling` ← would prevent false matches
- `maidenname` / `nickname` / `titles`
- `memorialid` (gold path when known)

The v5.0 ladder should add `middlename` as a primary parameter and
`exactspelling` selectively (only when the local name is high-quality).

## Sources

- Live verification against `findagrave.com/memorial/search`
- [Official Memorial Search help](https://support.findagrave.com/s/article/Memorial-Search)
- [Searching the bio field using keywords](https://support.findagrave.com/s/article/Searching-the-bio-field-using-keywords)
- [Naming Memorials](https://support.findagrave.com/s/article/Naming-Memorials)
- Third-party: [Apify Cemetery Scraper](https://apify.com/parseforge/cemetery-records-scraper),
  [FindAGrave Extras userscript (drench gist)](https://gist.github.com/drench/1bdb13461b383a004951c4b94246cbcb)