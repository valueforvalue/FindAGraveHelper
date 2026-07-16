"""Nickname + maiden name matchers.

FaG supports including nicknames and maiden names in search
via optional URL params. We use these only when the pensioner
data has a known nickname OR when we have a spouse (whose
last name is often the maiden name).

Known CW-era nickname patterns:
  Fannie  -> Fayette
  Mollie  -> Mary
  Polly   -> Mary
  Sally   -> Sarah
  Bettie  -> Elizabeth
  Nannie  -> Nancy
  Maggie  -> Margaret
  Nellie  -> Eleanor/Helen
  Mamie   -> Mary
  Patsy   -> Martha
  Dolly   -> Dorothy
  Lou     -> Louise
  Jennie  -> Jane/Jennifer
  Mandy   -> Amanda

The reverse map is generated automatically from KNOWN_NICKNAMES.
"""
from __future__ import annotations


# Forward nickname map (nickname -> [formal names])
KNOWN_NICKNAMES: dict[str, list[str]] = {
    "Fannie":  ["Fayette", "Frances", "Stephanie"],
    "Fanny":   ["Frances", "Fayette"],
    "Mollie":  ["Mary", "Molly"],
    "Polly":   ["Mary", "Pauline"],
    "Sally":   ["Sarah"],
    "Bettie":  ["Elizabeth"],
    "Betty":   ["Elizabeth"],
    "Lizzy":   ["Elizabeth"],
    "Nannie":  ["Nancy", "Ann"],
    "Nanny":   ["Nancy", "Ann"],
    "Maggie":  ["Margaret"],
    "Nellie":  ["Eleanor", "Helen", "Ellen"],
    "Mamie":   ["Mary"],
    "Patsy":   ["Martha", "Patricia"],
    "Dolly":   ["Dorothy"],
    "Lou":     ["Louise", "Louisa", "Lucy"],
    "Jennie":  ["Jane", "Jennifer", "Virginia"],
    "Jenny":   ["Jane", "Jennifer", "Virginia"],
    "Mandy":   ["Amanda"],
    "Dollie":  ["Dorothy"],
    "Lizzie":  ["Elizabeth"],
    "Libby":   ["Elizabeth"],
    "Tina":    ["Christina", "Albertina"],
    "Lula":    ["Louise", "Lucinda"],
    "May":     ["Mary"],
    "Kitty":   ["Katherine"],
    "Katie":   ["Katherine"],
    "Becky":   ["Rebecca"],
    "Peggy":   ["Margaret"],
    "Connie":  ["Constance"],
    "Daisy":   ["Margaret"],
    "Flora":   ["Florence"],
    "Gussie":  ["Augusta"],
    "Inez":    ["Agnes"],
    "Josie":   ["Josephine"],
    "Lottie":  ["Charlotte"],
    "Minnie":  ["Mary", "Minerva", "Wilhelmina"],
    "Nora":    ["Eleanor"],
    "Ollie":   ["Olive", "Oliver"],
    "Rosa":    ["Rosalind", "Rose"],
    "Tillie":  ["Matilda"],
    "Willa":   ["Wilhelmina"],
    "Birdie":  ["Bertha", "Roberta"],
    "Dixie":   ["Edith", "Margaret"],
    "Hallie":  ["Harriet"],
}


def reverse_nickname(formal: str) -> list[str]:
    """Given a formal name, return the list of nicknames.
    Empty list if no nickname known."""
    formal_lower = (formal or "").lower()
    rev = []
    # Iterate over a case-folded view of the nickname map
    for nick, formals in KNOWN_NICKNAMES.items():
        for f in formals:
            if f.lower() == formal_lower:
                rev.append(nick)
                break
    return rev


def nickname_candidates(first_name: str) -> list[str]:
    """Given a first name, return the nicknames that map to it
    (plus the formal names themselves if the input looks like a
    nickname)."""
    fn = (first_name or "").strip()
    if not fn:
        return []
    candidates = set()
    fn_lower = fn.lower()

    # Build a lowercase lookup map once
    lower_map = {k.lower(): v for k, v in KNOWN_NICKNAMES.items()}

    # Is this name a known nickname? Then list all formals it maps to.
    if fn_lower in lower_map:
        for f in lower_map[fn_lower]:
            candidates.add(f)
        # Also include other nicknames that map to the same formal
        for formal in lower_map[fn_lower]:
            for other_nick in reverse_nickname(formal):
                candidates.add(other_nick)

    # Is this name a formal name? Then add the reverse-nicknames.
    for nick in reverse_nickname(fn):
        candidates.add(nick)

    # Drop the input name itself (case-insensitive)
    for c in list(candidates):
        if c.lower() == fn_lower:
            candidates.discard(c)

    return sorted(candidates)


def strategy_with_nickname(first, middle, last, birth_year, death_year, pensioner=None):
    """F3: Search with nickname + maiden name expansion.

    Two flavors:
    1. If first_name has a known nickname, use all variants
    2. If pensioner has spouse_last_name, search by maiden name
       (some pensions were filed under wife's maiden name in error)
    """
    if not first or not last:
        return None
    candidates = nickname_candidates(first)
    maiden = ""
    if pensioner is None:
        pensioner = {} if isinstance(pensioner, dict) else {}
    if isinstance(pensioner, dict):
        maiden = (pensioner.get("spouse_last_name") or "").strip()

    has_nickname = bool(candidates)
    has_maiden = bool(maiden)
    if not has_nickname and not has_maiden:
        return None

    # Strategy variants: try first name with all known nickname variants
    if has_nickname:
        # Pick the most distinctive variant (longest? original?)
        variant = candidates[0]
        params = {
            "firstname": variant,
            "lastname": last,
            "includeNickname": "true",
            "exactspelling": "true",
        }
        if middle:
            params["middlename"] = middle
        return params

    # Maiden name variant: search by maiden as last name
    if has_maiden:
        return {
            "firstname": first,
            "lastname": maiden,
            "includeMaidenName": "true",
            "exactspelling": "true",
        }
    return None