"""The three questions my 2024 notebook asked, answered from the graph.

1. Are Elves green and Goblins red?
2. Do some artists appear far more than others?
3. Which subtypes hide inside which colours?

Each count comes from one SQL query over the graph, kept below by name.

A share gets a Wilson 95% interval, which stays honest when the share is 100%. A lift is
a share inside a group divided by the share among everyone compared (all creatures, or
all cards), and its interval is the share's interval divided by that base share. The
base is measured over thousands of cards, so its own uncertainty is small and is left
out. Nothing here is random, so the same graph always gives the same numbers.
"""

from __future__ import annotations

import math

import psycopg
from psycopg import sql

from topdeck.graph import COLOURS, SCHEMA, _checked
from topdeck.snapshot import SNAPSHOT_DATE

TOP_SUBTYPES = 20
TOP_ARTISTS = 15
STRONGEST_PAIRS = 15
MOST_EVEN = 10
MIN_CARDS = 30
# Numbers are stored to this many decimal places, and rounded only once, on the page.
PLACES = 6
# Two answers match when every number agrees to within this.
TOLERANCE = 1e-9

INTERVALS = (
    "A share has a Wilson 95% interval. A lift's interval is the share's interval divided "
    "by the base share; the base's own uncertainty is small and left out."
)

# How many creatures there are, and how many have each colour.
CREATURES_BY_COLOUR = """
SELECT colours.code,
       count(card_colour.card_id) AS cards,
       (SELECT count(*) FROM card_type WHERE type = 'Creature') AS creatures
FROM colours
LEFT JOIN card_colour
       ON card_colour.colour = colours.code
      AND card_colour.card_id IN (SELECT card_id FROM card_type WHERE type = 'Creature')
GROUP BY colours.code
ORDER BY colours.code
"""

# For every creature subtype: how many creatures have it, and how many of those have
# each colour.
CREATURE_SUBTYPES_BY_COLOUR = """
SELECT card_subtype.subtype,
       colours.code,
       count(DISTINCT card_subtype.card_id) AS cards,
       count(DISTINCT card_colour.card_id) AS with_colour
FROM card_subtype
JOIN card_type ON card_type.card_id = card_subtype.card_id AND card_type.type = 'Creature'
CROSS JOIN colours
LEFT JOIN card_colour
       ON card_colour.card_id = card_subtype.card_id AND card_colour.colour = colours.code
GROUP BY card_subtype.subtype, colours.code
ORDER BY card_subtype.subtype, colours.code
"""

# The same two counts over every card, not only creatures.
CARDS_BY_COLOUR = """
SELECT colours.code,
       count(card_colour.card_id) AS cards,
       (SELECT count(*) FROM cards) AS all_cards
FROM colours
LEFT JOIN card_colour ON card_colour.colour = colours.code
GROUP BY colours.code
ORDER BY colours.code
"""

SUBTYPES_BY_COLOUR = """
SELECT card_subtype.subtype,
       colours.code,
       count(DISTINCT card_subtype.card_id) AS cards,
       count(DISTINCT card_colour.card_id) AS with_colour
FROM card_subtype
CROSS JOIN colours
LEFT JOIN card_colour
       ON card_colour.card_id = card_subtype.card_id AND card_colour.colour = colours.code
GROUP BY card_subtype.subtype, colours.code
ORDER BY card_subtype.subtype, colours.code
"""

# For every subtype: how many of its one-coloured cards are each colour. A card with
# two colours or none is left out, so each card counts once and the shares add to 100%.
MONO_COLOURED_SUBTYPES = """
WITH mono AS (
    SELECT card_id, min(colour) AS colour
    FROM card_colour
    GROUP BY card_id
    HAVING count(*) = 1
)
SELECT card_subtype.subtype, mono.colour, count(*) AS cards
FROM card_subtype
JOIN mono USING (card_id)
GROUP BY card_subtype.subtype, mono.colour
ORDER BY card_subtype.subtype, mono.colour
"""

# The printings that are of basic lands: Plains, Islands and the rest.
BASIC_LANDS = """
SELECT card_id FROM card_supertype WHERE supertype = 'Basic'
"""

# Every artist, counted once for each real printing they illustrated.
ARTISTS_BY_PRINTING = f"""
SELECT artists.name,
       count(*) AS printings,
       count(DISTINCT printings.card_id) AS cards,
       count(*) FILTER (WHERE printings.card_id IN ({BASIC_LANDS})) AS basic_lands
FROM printing_artist
JOIN artists USING (artist_id)
JOIN printings USING (printing_id)
GROUP BY artists.name
ORDER BY printings DESC, artists.name
"""

# The same, with basic lands left out.
ARTISTS_WITHOUT_BASIC_LANDS = f"""
SELECT artists.name,
       count(*) AS printings,
       count(DISTINCT printings.card_id) AS cards
FROM printing_artist
JOIN artists USING (artist_id)
JOIN printings USING (printing_id)
WHERE printings.card_id NOT IN ({BASIC_LANDS})
GROUP BY artists.name
ORDER BY printings DESC, artists.name
"""

# Every artist, counted the 2024 way: one printing per card. My notebook dropped
# duplicate names and kept the first row of each; this keeps each card's earliest real
# printing, with ties broken by set and collector number.
ARTISTS_THE_2024_WAY = """
SELECT artists.name, count(*) AS cards
FROM (
    SELECT DISTINCT ON (card_id) printing_id
    FROM printings
    ORDER BY card_id, released_at, set_code, collector_number, printing_id
) AS earliest
JOIN printing_artist USING (printing_id)
JOIN artists USING (artist_id)
GROUP BY artists.name
ORDER BY cards DESC, artists.name
"""


def kept(value: float) -> float:
    """A number as it is stored: to six decimal places."""
    return round(value, PLACES)


def wilson(successes: int, trials: int, z: float = 1.959964) -> tuple[float, float]:
    """The Wilson 95% interval for a share. It does not shrink to nothing when every
    card in the group has the colour."""
    if trials == 0:
        return (0.0, 1.0)
    share = successes / trials
    scale = 1 + z * z / trials
    centre = (share + z * z / (2 * trials)) / scale
    half = z * math.sqrt(share * (1 - share) / trials + z * z / (4 * trials * trials)) / scale
    return (max(0.0, centre - half), min(1.0, centre + half))


def lift_with_interval(both: int, group: int, colour: int, everyone: int) -> dict:
    """The share of a group that has a colour, and its lift, each with a 95% interval.

    Lift is the share inside the group divided by the share among everyone compared: a
    lift of 3 means the colour turns up three times as often in the group. Its interval
    is the share's Wilson interval divided by that base share.
    """
    share = both / group
    base = colour / everyone
    share_low, share_high = wilson(both, group)
    return {
        "with_colour": both,
        "share": kept(share),
        "share_low": kept(share_low),
        "share_high": kept(share_high),
        "lift": kept(share / base),
        "lift_low": kept(share_low / base),
        "lift_high": kept(share_high / base),
    }


def evenness(counts: list[int]) -> float:
    """How evenly a subtype is spread over the five colours: 1 is perfectly even, 0 is
    one colour only. It is the entropy of the colour shares, divided by its largest
    possible value."""
    total = sum(counts)
    if total == 0:
        return 0.0
    entropy = -sum((n / total) * math.log(n / total) for n in counts if n)
    return entropy / math.log(len(counts))


def _by_subtype(rows: list[tuple]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for subtype, colour, cards, with_colour in rows:
        entry = table.setdefault(subtype, {"cards": cards, "colours": {}})
        entry["colours"][colour] = with_colour
    return table


def _pairs(
    table: dict[str, dict], colour_totals: dict[str, int], everyone: int
) -> list[tuple[float, str, str]]:
    """Every subtype and colour pair, strongest lift first."""
    pairs = []
    for subtype, entry in table.items():
        for colour, both in entry["colours"].items():
            if both and colour_totals[colour]:
                lift = (both / entry["cards"]) / (colour_totals[colour] / everyone)
                pairs.append((lift, subtype, colour))
    return sorted(pairs, key=lambda pair: (-pair[0], -table[pair[1]]["cards"], pair[1]))


def _pair_answer(
    subtype: str, colour: str, table: dict[str, dict], colour_totals: dict[str, int], everyone: int
) -> dict:
    entry = table[subtype]
    return {
        "subtype": subtype,
        "cards": entry["cards"],
        "colour": COLOURS[colour],
        **lift_with_interval(
            entry["colours"][colour], entry["cards"], colour_totals[colour], everyone
        ),
    }


def elves_and_goblins(cursor: psycopg.Cursor) -> dict:
    by_colour = cursor.execute(CREATURES_BY_COLOUR).fetchall()
    creatures = by_colour[0][2]
    colour_totals = {code: cards for code, cards, _ in by_colour}
    table = _by_subtype(cursor.execute(CREATURE_SUBTYPES_BY_COLOUR).fetchall())
    pairs = _pairs(table, colour_totals, creatures)

    def pair(subtype: str, colour: str) -> dict | None:
        if subtype not in table:
            return None
        return _pair_answer(subtype, colour, table, colour_totals, creatures)

    def best(subtype: str) -> dict:
        colour = next(c for _, name, c in pairs if name == subtype)
        return pair(subtype, colour)

    commonest = sorted(table, key=lambda name: (-table[name]["cards"], name))[:TOP_SUBTYPES]
    return {
        "creatures": creatures,
        "colour_share": {
            COLOURS[code]: kept(cards / creatures) for code, cards in colour_totals.items()
        },
        "elves_green": pair("Elf", "G"),
        "goblins_red": pair("Goblin", "R"),
        "commonest_subtypes": [best(subtype) for subtype in commonest],
    }


def artists(cursor: psycopg.Cursor) -> dict:
    by_printing = cursor.execute(ARTISTS_BY_PRINTING).fetchall()
    without_basics = cursor.execute(ARTISTS_WITHOUT_BASIC_LANDS).fetchall()
    the_2024_way = cursor.execute(ARTISTS_THE_2024_WAY).fetchall()
    rank_by_printing = {row[0]: rank for rank, row in enumerate(by_printing, start=1)}
    rank_without = {row[0]: rank for rank, row in enumerate(without_basics, start=1)}
    rank_2024 = {row[0]: rank for rank, row in enumerate(the_2024_way, start=1)}

    printings = sum(row[1] for row in by_printing)
    basic = sum(row[3] for row in by_printing)
    top_few = max(1, math.ceil(len(by_printing) / 100))
    held = sum(row[1] for row in by_printing[:top_few])
    counts = sorted(row[1] for row in by_printing)

    return {
        "artists": len(by_printing),
        "printings": printings,
        "basic_land_printings": basic,
        "median_printings": counts[len(counts) // 2] if counts else 0,
        "top_one_percent": {
            "artists": top_few,
            "printings": held,
            "share": kept(held / printings) if printings else 0.0,
        },
        "by_printings": [
            {
                "artist": name,
                "printings": n,
                "basic_lands": basic_lands,
                "different_cards": cards,
                "rank_without_basic_lands": rank_without.get(name),
                "rank_2024": rank_2024.get(name),
            }
            for name, n, cards, basic_lands in by_printing[:TOP_ARTISTS]
        ],
        "without_basic_lands": {
            "printings": sum(row[1] for row in without_basics),
            "by_printings": [
                {
                    "artist": name,
                    "printings": n,
                    "different_cards": cards,
                    "rank_with_basic_lands": rank_by_printing.get(name),
                }
                for name, n, cards in without_basics[:TOP_ARTISTS]
            ],
        },
        "the_2024_way": [
            {"artist": name, "cards": cards, "rank_by_printings": rank_by_printing.get(name)}
            for name, cards in the_2024_way[:TOP_ARTISTS]
        ],
    }


def subtypes_in_colours(cursor: psycopg.Cursor) -> dict:
    by_colour = cursor.execute(CARDS_BY_COLOUR).fetchall()
    everyone = by_colour[0][2]
    colour_totals = {code: cards for code, cards, _ in by_colour}
    table = {
        subtype: entry
        for subtype, entry in _by_subtype(cursor.execute(SUBTYPES_BY_COLOUR).fetchall()).items()
        if entry["cards"] >= MIN_CARDS
    }
    strongest = _pairs(table, colour_totals, everyone)[:STRONGEST_PAIRS]

    mono: dict[str, dict[str, int]] = {}
    for subtype, colour, cards in cursor.execute(MONO_COLOURED_SUBTYPES).fetchall():
        mono.setdefault(subtype, {code: 0 for code in COLOURS})[colour] = cards
    spread = []
    for subtype, by_code in mono.items():
        counts = [by_code[code] for code in COLOURS]
        if sum(counts) >= MIN_CARDS:
            spread.append((evenness(counts), subtype, counts))
    spread.sort(key=lambda item: (-item[0], item[1]))

    return {
        "cards": everyone,
        "subtypes_considered": len(table),
        "colour_share": {
            COLOURS[code]: kept(cards / everyone) for code, cards in colour_totals.items()
        },
        "strongest": [
            _pair_answer(subtype, colour, table, colour_totals, everyone)
            for _, subtype, colour in strongest
        ],
        "one_coloured_subtypes_considered": len(spread),
        "most_even": [
            {
                "subtype": subtype,
                "one_coloured_cards": sum(counts),
                "evenness": kept(score),
                "share": {
                    COLOURS[code]: kept(n / sum(counts))
                    for code, n in zip(COLOURS, counts, strict=True)
                },
            }
            for score, subtype, counts in spread[:MOST_EVEN]
        ],
    }


def answer(connection: psycopg.Connection, schema: str = SCHEMA) -> dict:
    """Answer all three questions from the graph in the given schema."""
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(_checked(schema))))
        return {
            "snapshot": SNAPSHOT_DATE,
            "intervals": {"level": 0.95, "method": INTERVALS},
            "elves_and_goblins": elves_and_goblins(cursor),
            "artists": artists(cursor),
            "subtypes_in_colours": subtypes_in_colours(cursor),
        }


def differences(found, recorded, path: str = "") -> list[str]:
    """Where two sets of answers differ. Every count must match exactly, and every other
    number to within a billionth. A number that is not a number never matches."""
    if isinstance(found, dict) and isinstance(recorded, dict):
        problems = []
        for key in sorted(set(found) | set(recorded)):
            if key not in found or key not in recorded:
                problems.append(f"{path}{key}: only in one of the two")
                continue
            problems.extend(differences(found[key], recorded[key], f"{path}{key}."))
        return problems
    if isinstance(found, list) and isinstance(recorded, list):
        if len(found) != len(recorded):
            return [f"{path[:-1]}: found {len(found)} rows, recorded {len(recorded)}"]
        problems = []
        for index, (one, other) in enumerate(zip(found, recorded, strict=True)):
            problems.extend(differences(one, other, f"{path}{index}."))
        return problems
    numbers = (int, float)
    if (
        isinstance(found, numbers)
        and isinstance(recorded, numbers)
        and not isinstance(found, bool)
        and not isinstance(recorded, bool)
    ):
        if math.isnan(found) or math.isnan(recorded):
            return [f"{path[:-1]}: found {found!r}, recorded {recorded!r}, and NaN never matches"]
        if abs(found - recorded) > TOLERANCE:
            return [f"{path[:-1]}: found {found!r}, recorded {recorded!r}"]
        return []
    if found != recorded:
        return [f"{path[:-1]}: found {found!r}, recorded {recorded!r}"]
    return []
