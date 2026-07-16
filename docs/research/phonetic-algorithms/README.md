# Phonetic Matching Algorithms for Genealogy

When the local name and the FaG slug differ by one or two letters,
phonetic matching recovers the hit.

## Algorithm comparison (Civil War-era American names)

| Algorithm | Best for | Weakness | Looney/Luney/Loney | Anderson/Andersen/Andison | Rozell/Rozzell/Roussel | O'Brien variants |
|---|---|---|---|---|---|---|
| **Soundex** | English surnames, fast | Truncates at 4 chars; collapses `oo/ey/y` | All → `L500` ✓ | `A536/A536/A532` | `R240/R240/R240` | All `O165` ✓ |
| **Daitch-Mokotoff** | Slavic/Yiddish/German | Multiple encodings (must intersect) | `L500` for all | `A536/A536/A536` ✓ | `R740/R744/R844` ✓ | `O796/O796/O796` ✓ |
| **Double Metaphone** | English phonetic | English-biased | `LN/LN/LN` | `ANTRSN/ANTRSN/ANTSN` | `RSL/RSL/RSL` | `APRN/APRN/APRN` ✓ |
| **Beider-Morse BMPM** | Ashkenazi Jewish | 16 language tables, heavy | Excellent | Excellent | Excellent | Excellent |
| **NYSIIS** | Names (NY state) | Less common | `LANY/LANY/LANY` | `ANDAR/ANDAR/ANDAS` | `RACAL/RACAL/RASAL` | `OBRAN/OBRAN/OBRAN` |
| **Cologne** | German only | Wrong choice for English | `865/865/865` | `0627/0627/0627` | `857/857/857` | `0176` |
| **Damerau-Levenshtein** | Typos + transpositions | No phonetic awareness | 1 edit / 2 / 1 | 2 / 1 / 2 | 1 / 1 / 2 | 1 / 1 / 1 |

**Recommendation for CW-era US names:** run **Double Metaphone** as
primary filter, **Soundex** as a recall backstop, then
**Damerau-Levenshtein** on the candidate set for ranking. Add
**Daitch-Mokotoff** if the name looks German/Polish/Scandinavian
(common in 1860s PA/OH/NY regiments: detect with
`/[äöüß]|icz|ski|berg|mann$/i`).

## JS implementations — drop-in snippets

### A. Talisman from CDN (recommended)

```js
// @require works in Tampermonkey/Greasemonkey/Violentmonkey
// Tree-shakable per-module
const dm   = require('talisman/phonetics/double-metaphone');
const soun = require('talisman/phonetics/soundex');
const nys  = require('talisman/phonetics/nysiis');
```

Source: [Talisman phonetics docs](https://yomguithereal.github.io/talisman/phonetics/)

### B. Damerau-Levenshtein (handles "Morrisson"↔"Morrison" in 1 op)

```js
function damerauLevenshtein(a, b) {
  const m = a.length, n = b.length;
  if (!m) return n; if (!n) return m;
  const d = Array.from({length: m+1}, () => new Int32Array(n+1));
  for (let i = 0; i <= m; i++) d[i][0] = i;
  for (let j = 0; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i-1].toLowerCase() === b[j-1].toLowerCase() ? 0 : 1;
      d[i][j] = Math.min(
        d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + cost
      );
      if (i > 1 && j > 1 &&
          a[i-1].toLowerCase() === b[j-2].toLowerCase() &&
          a[i-2].toLowerCase() === b[j-1].toLowerCase())
        d[i][j] = Math.min(d[i][j], d[i-2][j-2] + cost);
    }
  }
  return d[m][n];
}
const sim = (a, b) => 1 - damerauLevenshtein(a, b) / Math.max(a.length, b.length);
```

### C. Jaro-Winkler (best for short strings, initials)

```js
function jaroWinkler(s1, s2) {
  if (s1 === s2) return 1;
  const m = (a, b) => {
    if (!a.length) return b.length ? 0 : 1;
    const matchWindow = Math.max(0, Math.floor(Math.max(a.length, b.length)/2)-1);
    const aMatches = new Array(a.length).fill(false);
    const bMatches = new Array(b.length).fill(false);
    let matches = 0;
    for (let i = 0; i < a.length; i++) {
      const lo = Math.max(0, i-matchWindow), hi = Math.min(i+matchWindow+1, b.length);
      for (let j = lo; j < hi; j++) if (!bMatches[j] && a[i]===b[j]) { aMatches[i]=bMatches[j]=true; matches++; break; }
    }
    if (!matches) return 0;
    let t = 0, k = 0;
    for (let i = 0; i < a.length; i++) if (aMatches[i]) { while (!bMatches[k]) k++; if (a[i]!==b[k]) t++; k++; }
    return (matches/a.length + matches/b.length + (matches - t/2)/matches) / 3;
  };
  const j = m(s1, s2);
  let p = 0; while (p < 4 && s1[p] === s2[p]) p++;
  return j + p * 0.1 * (1 - j);
}
```

### D. Combined scorer

```js
function nameScore(query, candidate) {
  const q = query.toLowerCase().replace(/[^a-z]/g, '');
  const c = candidate.toLowerCase().replace(/[^a-z]/g, '');
  const [q1, q2] = dm(q);
  const [c1, c2] = dm(c);
  const phoneticHit = (q1 && (q1===c1 || q1===c2 || q2===c1 || q2===c2)) ? 1 : 0;
  const sounHit    = soun(q) === soun(c) ? 1 : 0;
  const jw         = jaroWinkler(q, c);
  const dlSim      = sim(q, c);
  return Math.max(
    phoneticHit * 0.95 + jw * 0.05,
    sounHit      * 0.85 + jw * 0.15,
    jw * 0.7 + dlSim * 0.3
  );
}
```

## Threshold tuning (AML-screening convention)

| Score | Interpretation |
|---|---|
| **≥ 0.92** | Almost certainly same person; auto-flag |
| **0.85 – 0.91** | Likely same; review (use birth/death year tie-break) |
| **0.75 – 0.84** | Possibly same; show as "review candidates" |
| **< 0.75** | Discard |

Sources: Flagright uses 0.85 standard; Splink uses 0.80 lower bound.

Use **Jaro-Winkler first/last** as separate features and AND them —
only auto-match when both pass 0.88.

## Find a Grave's built-in fuzzy

The official help only says the checkbox "searches for similar name
spellings." No algorithm disclosed. Empirical behavior:

- Matches **all surnames** entered in the last-name field (married +
  maiden stacked).
- Does **not phonetically collapse** "Wm" ↔ "William" or "Wms" — manual
  expansion needed.
- Handles truncated/dropped vowels reasonably (e.g., "Eliz" matches
  "Elizabeth").
- Middle-name search is a separate field; fuzzy applies per-field
  independently.
- Does **not** handle apostrophes specially — "Obrien" and "O'Brien"
  both return results, but the strictest match wins ordering.

**Practical implication:** don't rely on FaG's fuzzy alone. Run a
local candidate generator with `double-metaphone` +
`damerauLevenshtein`, then submit well-formed query strings.

## Implications for the helper script

The helper should:

1. Pre-process the local name to normalize (strip periods, lower-case)
2. Compute Double Metaphone code(s) for the surname
3. Query FaG with `fuzzyNames=true` for the standard match
4. If 0 results, generate abbreviation variants of first name and retry
5. If 0 results, generate apostrophe variants of last name and retry
6. If 0 results, drop the first name and search last-only
7. If 0 results, try phonetic neighbors of last name (locally
   generated list)

Don't run phonetic on FaG itself — FaG doesn't expose that.

## Sources

- [Talisman phonetics](https://yomguithereal.github.io/talisman/phonetics/)
- [Beider & Morse BMPM (APGQ 2010)](https://stevemorse.org/phonetics/bmpm2.htm)
- [Find a Grave Naming Memorials help](https://support.findagrave.com/s/article/Naming-Memorials)
- [Splink threshold guide](https://moj-analytical-services.github.io/splink/)