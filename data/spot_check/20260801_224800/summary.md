# Spot-check pack — 20260801_224800

- Total records: **25**
- Seed: `99`
- EasyOCR fresh pass: no

| bucket | pid | pcid | name | claimed (year/iso) | src_pass | parser-on-fresh | image |
|---|---|---|---|---|---|---|---|
| red | 3135 | 12892 | Graham, Jones P. | 1920/1920 | red | — |  |
| red | 3843 | 12921 | Bass, Amanda J. | 1929/1929-02-08 | red | — | cards/12921_3843.jpg |
| red | 7065 | 2973 | Tabor, Susie | 1931/1931-06-04 | red | — | cards/2973_7065.jpg |
| red | 4977 | 4287 | Lane, Sampson T. | 1933/1933-02-28 | red | — | cards/4287_4977.jpg |
| red | 6055 | 4722 | Wilkerson, Richard L. | 1932/1932-06-27 | red | — | cards/4722_6055.jpg |
| full-fallback | 7410 | 6516 | Walker, Allen H. | 1928/1928-08-14 | full-fallback | — | cards/6516_7410.jpg |
| full-fallback | 7160 | 11576 | Whisenhunt, George A | 1919/1919-01-27 | full-fallback | — |  |
| full-fallback | 5304 | 9028 | McDaniel, Winnie M. | 1922/1922 | full-fallback | — |  |
| full-fallback | 5858 | 5259 | Thompson, John W. | 1920/1920-10-17 | full-fallback | — | cards/5259_5858.jpg |
| full-fallback | 2573 | 6021 | Rider, Jane | 1915/1915-02-05 | full-fallback | — | cards/6021_2573.jpg |
| easyocr | 362 | 3028 | Hall, Thomas G. | 1916/1916 | easyocr | — | cards/3028_362.jpg |
| easyocr | 3136 | 6476 | Gravely, Ellen L. | 1929/1929 | easyocr | — | cards/6476_3136.jpg |
| easyocr | 4168 | 5274 | Curtis, Mary J. | 1924/1924-07-01 | easyocr | — | cards/5274_4168.jpg |
| easyocr | 2678 | 2039 | Corntassell, Jennie | 1936/1936-04-26 | easyocr | — | cards/2039_2678.jpg |
| easyocr | 8635 | 3742 | Harrison, Nancy M. | 1921/1921-03-14 | easyocr | — |  |
| no_date_with_ocr | 6205 | 7819 | Boyd, Roland N | / |  | — |  |
| no_date_with_ocr | 1903 | 444 | Pendleton, Hiram | / |  | — | cards/444_1903.jpg |
| no_date_with_ocr | 1282 | 6175 | Davis, Nancy K. | / |  | — | cards/6175_1282.jpg |
| no_date_with_ocr | 675 | 3374 | Oxley, Presley | / |  | — | cards/3374_675.jpg |
| no_date_with_ocr | 1455 | 508 | Golden, Tom | / |  | — | cards/508_1455.jpg |
| no_date_with_ocr | 8251 | 2112 | Conant, Thomas C | / |  | — | cards/2112_8251.jpg |
| no_date_with_ocr | 6398 | 3564 | Hagler, Nancy | / |  | — | cards/3564_6398.jpg |
| no_date_with_ocr | 552 | 9774 | Manes, James E. | / |  | — |  |
| no_date_with_ocr | 8377 | 10708 | Barrow, James R | / |  | — |  |
| no_date_with_ocr | 59 | 2439 | Bauldwyn, Elisha B. | / |  | — |  |

## Manual review protocol

1. Open the image (`cards/<pcid>_<pid>.jpg`).
2. Read the top-right DECEASED stamp. Note year (and month/day if shown).
3. Compare to `claimed (year/iso)`.
4. Mark each row in `manifest.json` with `review_verdict`:
   - `pass` — claimed year matches the stamp
   - `fail_year` — different year (record the correct one in `corrected_year`)
   - `fail_parser` — date is on the card but the regex missed it (record in `corrected_iso`)
   - `no_date_on_card` — card genuinely has no death date (confirms skip is correct)
   - `uncertain` — can't tell from this scan quality

Aggregate verdicts feed a follow-up issue. Do NOT auto-merge — the parser's
precision is load-bearing for FaG matching.
