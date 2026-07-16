# Future Work

Things we identified but haven't built yet. Some are quick wins,
some require real engineering.

## 1. Spouse cross-reference (high impact, high effort)

**Idea:** Many pension records are for **widows** who applied on
behalf of a deceased soldier. The pension card lists both the
soldier's name and the widow's name. If both are in FaG, the
pair is a very strong signal.

**Confirmed feasible:** 49% of unified records (3,793) have a
`spouse_name` field. FaG's memorial page has a **Spouse** section
listing the spouse's name, dates, marriage year, and a **Children**
section listing each child with dates. This is rich cross-reference
data.

**Why it helps:**
- Doubles the verification: if `Soldier S` and `Widow W` are both
  in FaG with a spouse link between them, that's a near-perfect
  match
- Catches transcription errors: if FaG's "William Pickney Looney"
  doesn't match our local "William Looney" (no middle), but the
  widow "Mary Looney" does match, the pair confirms it
- Catches state-OK confusion: if a candidate for `Soldier S` is
  buried in TX but the widow is buried in OK, that's the right
  family (she may have moved back to OK after his death)

**Example from a real FaG page (William Pickney Looney, memorial 50923719):**
- Spouse: `Fayette J. "Fannie" Rogers Looney` (1844–1931, m. 1870)
- Children: `Walter W Looney` (1874–1953), `Laura Anne Looney Cryer` (1875–1960), `John Pleasant Looney` (1877–1964)

If our local pension record has a widow named "Fannie Looney" or
"Fayette Rogers", that's a near-perfect match.

**Design:**

### Step 1: Index FaG's "spouse" relationships

For each pensioner record, search FaG for the person. Visit their
memorial page. Parse out:
- `spouse_name`
- `parents` (father, mother names)
- `children` (children names)

Save to a sidecar index file:
```json
{
  "<memorial_id>": {
    "name": "...",
    "slug": "...",
    "spouse_name": "...",
    "parents": ["...", "..."],
    "children": ["...", "..."],
    "burial_cemetery": "...",
    "burial_state": "...",
    "birth_date": "...",
    "death_date": "...",
  }
}
```

Cost: 1 request per FaG candidate we'd want to know about. With
~5 candidates × 7,558 pensioners = 38K requests, ~16h at 1.5s
throttle. Could be done once, cached.

### Step 2: For each pensioner pair (soldier + widow), look up both

The OK pension index has both names. We:
1. Search for the soldier in FaG (current behavior)
2. For each top candidate, fetch the memorial page and extract
   spouse/parents
3. If any candidate's spouse name matches the widow name from the
   pension record, that's a very high-confidence match
4. **Same in reverse**: search for the widow; if her husband's
   name on FaG matches the soldier's name, also high-confidence

### Step 3: Cross-link records in the state file

Add to the state record:
```json
{
  "pensioner_id": 1234,
  "spouse_match": {
    "soldier_id": 1234,
    "widow_id": 1235,
    "soldier_candidate": "memorial/...",
    "widow_candidate": "memorial/...",
    "spouse_link_verified": true
  }
}
```

The HTML viewer can show a "Spouse cross-reference: VERIFIED" badge
when both halves match.

### Implementation effort

- **3-5 days** of development
- **2-4 hours** of full indexing run
- Requires the existing Playwright + stealth setup

### Estimated hit-rate boost

For widows: instead of "find widow name in FaG" alone, we can
also "find soldier name in FaG and verify widow-spouse link".
Expected boost: 84% → 90%+ on widow records.

### For soldier records (non-widow)

The Children field is also useful. If our local data has a child
name (it currently doesn't, but could be added), we can verify.
Without that, soldier records get less benefit from this feature.

### Side benefit: children-of-cross-generation matching

If we index **all** FaG records in OK, we can also do
**graph traversal**: for pensioner X, look at FaG candidate Y's
children list. If any child name appears in another pensioner
record (as a different CW pension), that's a family link.
Could surface pensions that are missing from our index.

### Quick start: prototype with the 575 known records

Even without building the full 38K-request index, we can validate
the **approach** on our 575 known records:

1. For each `local_soldiers_with_fag.csv` row, fetch the FaG
   memorial page and extract spouse/children
2. Check whether the spouse name on FaG matches the widow name in
   any other dixiedata record
3. Count how many "true" matches we can find

This takes ~5-10 minutes for 575 records. Confirms the data
quality and the approach before committing to the full index.

## 2. Birth year + birthplace

The OK pension records don't have birth year or birthplace. But
many CW records have a birth year derivable from:
- Enlistment age × enlistment year (if both known)
- Census records (1870, 1880) — cross-reference with FamilySearch
- Confederate pension index year

If we had birth year, we could add:
- `birth_year_score` (similar to death-year matching, weight 0.10)
- `birth_state_score` (if local has birthplace state, match it)

Boost: marginal, maybe 1-2%.

## 3. Cemetery name match

The local CSV has `buried_in` for ~95% of records. The FaG
candidate card has the cemetery name. Direct match would be a
near-perfect signal.

Implementation: parse `buried_in` into cemetery name, normalize
("Cemetery" / "Cem" / "Cem.") and compare.

Boost: significant for the 95% of records that have it.

## 4. Phonetic surname expansion

For names with known-variant phonetic neighbors (e.g. Rozell /
Rozzell / Roussel), generate variants and search each. The
"Peter Rozell" miss would have been caught if we searched
"Rozzell" too.

Implementation: use `talisman/phonetics` or a hand-rolled
Double Metaphone. Generate 3-5 variants per surname. Search each
in a separate query.

Cost: 3-5x more FaG requests per pensioner. Trade-off.

## 5. NPS Soldiers & Sailors index integration

The NPS has a complementary dataset of ~6.3M CW soldiers, organized
differently from NARA CMSR. Their cards have:
- Alternate names (explicit "Alternate Name" field)
- Officers (less represented in NARA CMSR)
- Union soldiers

Pulling NPS data would:
- Add 5-10x more soldiers to the broadened CW training set
- Validate the strategy ladder against a much bigger sample
- Find alternate name spellings we'd miss

But: NPS search is JS-rendered, harder to scrape. Would need
browser automation.

## 6. Run the full batch

We have all the pieces. The actual run is:
- ~3.2h for the full unified.json
- 84% rank-1 hit rate = 6,500 records that auto-pick
- 16% = 1,250 records that need human review (~30 min of clicking)
- 0% would be the "we didn't try" case (CAPTCHA at scale)

**This is the actual production step.** Just need to run it.

## 7. Bulk-export to dixiedata

Once we have a CSV of (soldier_id, fag_url) decisions, write back
to dixiedata.db. That's a separate one-time tool. Schema for the
existing records table is already in place (`record_type`,
`app_id`, `details`).

## 8. Multi-state expansion

The current tool is hardcoded for OK. To expand to other states
(TX, AR, MO, etc.):
- Make the `ok_burial_score` configurable to any state code
- Or remove it entirely for a generic "find any CW vet" search
- Or make it a list: `target_states = ["OK", "TX", ...]`
