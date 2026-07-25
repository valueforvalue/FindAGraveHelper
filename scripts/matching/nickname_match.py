"""Nickname + maiden name matchers.

FaG supports including nicknames and maiden names in search
via optional URL params. We use these only when the pensioner
data has a known nickname OR when we have a spouse (whose
last name is often the maiden name).

Known CW-era nickname patterns (88 entries covering both male and
female diminutives common in 19th-century pension records):
  Fannie -> Fayette, Sallie -> Sarah, Lucy -> Lucinda/Lucille,
  Mattie -> Martha/Matilda, Joe -> Joseph, Sam -> Samuel,
  Charley -> Charles, Annie -> Ann/Anna, Kate -> Katherine,
  ... see KNOWN_NICKNAMES dict for full list.

The reverse map is generated automatically from KNOWN_NICKNAMES.
"""
from __future__ import annotations


# Forward nickname map (nickname -> [formal names])
KNOWN_NICKNAMES: dict[str, list[str]] = {
    "Abbie":   ["Abigail"],
    "Addie":   ["Adeline", "Adelaide", "Ada"],
    "Alex":    ["Alexander"],
    "Allie":   ["Alice", "Allison"],
    "Andy":    ["Andrew"],
    "Annie":   ["Ann", "Anna", "Anne"],
    "Arch":    ["Archibald"],
    "Artie":   ["Arthur"],
    "Becky":   ["Rebecca"],
    "Belle":   ["Isabella", "Arabella"],
    "Ben":     ["Benjamin"],
    "Bettie":  ["Elizabeth"],
    "Betty":   ["Elizabeth"],
    "Birdie":  ["Bertha", "Roberta"],
    "Callie":  ["Caroline", "Calista"],
    "Carrie":  ["Caroline", "Carolyn"],
    "Charley": ["Charles"],
    "Connie":  ["Constance"],
    "Daisy":   ["Margaret"],
    "Dave":    ["David"],
    "Dixie":   ["Edith", "Margaret"],
    "Dollie":  ["Dorothy"],
    "Dolly":   ["Dorothy"],
    "Dora":    ["Dorothy", "Theodora"],
    "Ed":      ["Edward", "Edwin", "Edmond"],
    "Effie":   ["Euphemia"],
    "Etta":    ["Henrietta", "Loretta"],
    "Fannie":  ["Fayette", "Frances", "Stephanie"],
    "Fanny":   ["Frances", "Fayette"],
    "Flora":   ["Florence"],
    "Gussie":  ["Augusta"],
    "Hallie":  ["Harriet"],
    "Harve":   ["Harvey"],
    "Hattie":  ["Harriet"],
    "Ike":     ["Isaac"],
    "Inez":    ["Agnes"],
    "Jack":    ["John"],
    "Janie":   ["Jane"],
    "Jeff":    ["Jefferson"],
    "Jennie":  ["Jane", "Jennifer", "Virginia"],
    "Jenny":   ["Jane", "Jennifer", "Virginia"],
    "Joe":     ["Joseph"],
    "Josie":   ["Josephine"],
    "Kate":    ["Katherine"],
    "Katie":   ["Katherine"],
    "Kitty":   ["Katherine"],
    "Libby":   ["Elizabeth"],
    "Lillie":  ["Lillian", "Elizabeth"],
    "Lizzie":  ["Elizabeth"],
    "Lizzy":   ["Elizabeth"],
    "Lottie":  ["Charlotte"],
    "Lou":     ["Louise", "Louisa", "Lucy"],
    "Lucy":    ["Lucinda", "Lucille", "Lucia", "Louise"],
    "Lue":     ["Lucinda", "Louise", "Lucy"],
    "Lula":    ["Louise", "Lucinda"],
    "Mack":    ["Malcolm", "Maxwell"],
    "Maggie":  ["Margaret"],
    "Mamie":   ["Mary"],
    "Mandy":   ["Amanda"],
    "Mattie":  ["Martha", "Matilda"],
    "May":     ["Mary"],
    "Millie":  ["Mildred", "Millicent"],
    "Minnie":  ["Mary", "Minerva", "Wilhelmina"],
    "Mollie":  ["Mary", "Molly"],
    "Nannie":  ["Nancy", "Ann"],
    "Nanny":   ["Nancy", "Ann"],
    "Nellie":  ["Eleanor", "Helen", "Ellen"],
    "Nick":    ["Nicholas"],
    "Nora":    ["Eleanor"],
    "Ollie":   ["Olive", "Oliver"],
    "Patsy":   ["Martha", "Patricia"],
    "Peggy":   ["Margaret"],
    "Polly":   ["Mary", "Pauline"],
    "Rosa":    ["Rosalind", "Rose"],
    "Roxie":   ["Roxanne", "Roxanna"],
    "Sadie":   ["Sarah"],
    "Sallie":  ["Sarah"],
    "Sally":   ["Sarah"],
    "Sam":     ["Samuel"],
    "Sue":     ["Susan", "Susanna"],
    "Susie":   ["Susan", "Susanna"],
    "Tillie":  ["Matilda"],
    "Tina":    ["Christina", "Albertina"],
    "Tom":     ["Thomas"],
    "Willa":   ["Wilhelmina"],
    "Willie":  ["William"],
    "Winnie":  ["Winifred", "Winona"],
    "Zack":    ["Zachariah"],
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