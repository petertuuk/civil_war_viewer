"""The names and two-letter codes of the states, in one place, and the one function that builds the lookup tables the
scripts used to spell out each on their own (full name -> code, code -> full name, upper-case, lower-case, ...).

NAME holds the 48 states of the lower United States, DC, and two period regions the sources use as if they were states (Dakota, Indian Territory).
table(key, value, *entries) builds a dict in exactly the order given, so a script that matches the first of several
names (a regex alternation, a startswith loop, a first-hit scan) still sees them in the order it always did:
  - an entry that is a code ("AL") gives the pair for that state in the two spellings asked for;
  - an entry that is a pair ("Indian Territory", "OK") is a spelling that is not a plain state name and is kept as written.
Spellings (key / value kind): "Name" Alabama, "NAME" ALABAMA, "name" alabama, "snake" new_york, "CODE" AL, "code" al.

Where the sources disagree on what a name means, the disagreement stays in the table that has it and is listed here, because
it is a decision about the source and not a typo:
  - "Dakota" is DT (Dyer's, the event index, places_inventory, build_db, score_dyers_vs_cwss) but SD in resolve_mentions.HOME;
  - "Indian Territory" is OK in extract_nps_histories and or_stations, IT in places_inventory and the event index;
  - "Washington" is WA in gnis_index and resolve_mentions, but DC in or_stations.STATE_WORDS (the city);
  - "Washington Territory" is WA everywhere it appears.
The abbreviation tables ("ala", "n. c", "tenn", ...) are not here yet: they differ by source on purpose and by key spelling.
"""

NAME = {
    "AL": "Alabama",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DT": "Dakota",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "ID": "Idaho",
    "IL": "Illinois",
    "IT": "Indian Territory",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

_FORMAT = {
    "Name": lambda code: NAME[code],
    "NAME": lambda code: NAME[code].upper(),
    "name": lambda code: NAME[code].lower(),
    "snake": lambda code: NAME[code].lower().replace(" ", "_"),
    "CODE": lambda code: code,
    "code": lambda code: code.lower(),
}


def table(key, value, *entries):
    """Dict of key spelling -> value spelling, in the order of `entries` (state codes, or literal (key, value) pairs)."""
    out = {}
    for e in entries:
        if isinstance(e, str):
            out[_FORMAT[key](e)] = _FORMAT[value](e)
        else:
            k, v = e
            out[k] = v
    return out
