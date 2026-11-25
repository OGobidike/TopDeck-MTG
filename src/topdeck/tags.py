"""The art-tag check: 50 of the community's picture labels, drawn so I can check them by eye.

Tagger's labels are written by Scryfall's community. Wizards does not check them, and I
have not found how Scryfall reviews them. No tag, checked or not, is ever the answer key
for any score. The check measures how often Tagger is right and reports that number; it
does not promote any tag.

The draw is fixed: each label's place in line comes from a hash of the seed, the picture
and the tag, so the same graph always gives the same 50. Most labels are of middling
weight, so a plain random draw would be nearly all of those. The draw is spread across
Tagger's weights instead (QUOTAS below). Tagger's weight is its own grading of each label;
the notes on the labels suggest it says how prominent the thing is in the picture. With
10 or 20 labels a weight, each weight's share right is only a hint, so it carries a Wilson
interval. The overall share right is weighted by how many labels of each weight the graph
holds. Nearly all of them are median, so the overall rests almost wholly on the 20 median
labels: it is worth about 21 labels, and carries its own interval at that size.

The record of the draw holds no annotation: those are notes volunteers wrote, and their
words stay out of the repo, as rulings' do. The table to mark by hand shows them, so it is
kept in marking/, which Git ignores. The verdicts read back from it hold no notes.
"""

from __future__ import annotations

import re
from urllib.parse import quote

import psycopg
from psycopg import sql

from topdeck.answers import wilson
from topdeck.graph import SCHEMA, WEIGHTS, _checked
from topdeck.snapshot import SOURCES_SNAPSHOT_DATE

SEED = "topdeck-art-tag-check-2026-11-22"
QUOTAS = {"weak": 10, "median": 20, "strong": 10, "very_strong": 10}
# The bar, set before any label is marked: the share right, weighted by the labels of
# each weight in the graph, must reach it. It is the bar the blueprint sets for links
# extracted from rules text.
BAR = 0.9


def words(weight: str) -> str:
    return weight.replace("_", " ")


def how(quotas: dict[str, int]) -> str:
    """How the draw is made, in words, from the quotas it is made with."""
    counts = [f"{quotas[weight]} {words(weight)}" for weight in WEIGHTS]
    return (
        "Drawn by a fixed hash of the seed, the picture and the tag: "
        f"{', '.join(counts[:-1])} and {counts[-1]}, by Tagger's own weights. Each picture "
        "is shown on its earliest real printing."
    )


# Every label of each weight, in the fixed order its hash gives; the first few of each
# weight are drawn. Each picture is shown on its earliest real printing, with ties broken
# by set and number in plain byte order, so no database's collation can change the pick.
DRAW = """
WITH drawn AS (
    SELECT illustration_id, tag_id, weight, annotation,
           row_number() OVER (
               PARTITION BY weight
               ORDER BY md5(%(seed)s || illustration_id::text || tag_id::text)
           ) AS place
    FROM illustration_art_tag
),
shown_on AS (
    SELECT DISTINCT ON (printing_illustration.illustration_id)
           printing_illustration.illustration_id, printing_illustration.position,
           cards.name, printings.set_code, printings.collector_number
    FROM printing_illustration
    JOIN printings USING (printing_id)
    JOIN cards USING (card_id)
    ORDER BY printing_illustration.illustration_id, printings.released_at,
             printings.set_code COLLATE "C", printings.collector_number COLLATE "C",
             printings.printing_id, printing_illustration.position
)
SELECT drawn.weight, drawn.place, shown_on.name, shown_on.set_code,
       shown_on.collector_number, art_tags.label, drawn.annotation,
       drawn.illustration_id::text, drawn.tag_id::text, shown_on.position
FROM drawn
JOIN shown_on USING (illustration_id)
JOIN art_tags USING (tag_id)
WHERE drawn.place <= CASE drawn.weight
    WHEN 'weak' THEN %(weak)s WHEN 'median' THEN %(median)s
    WHEN 'strong' THEN %(strong)s WHEN 'very_strong' THEN %(very_strong)s END
"""

COUNT_BY_WEIGHT = "SELECT weight, count(*) FROM illustration_art_tag GROUP BY weight"


def link(set_code: str, collector_number: str) -> str:
    """The printing's page on Scryfall, where its picture can be seen."""
    return f"https://scryfall.com/card/{quote(set_code)}/{quote(collector_number)}"


def sample(connection: psycopg.Connection, schema: str = SCHEMA) -> dict:
    """Draw the 50 labels to check, the same 50 every time. Each row keeps the
    volunteer's annotation for the table; `public` takes it out for the record."""
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(_checked(schema))))
        rows = cursor.execute(DRAW, {"seed": SEED, **QUOTAS}).fetchall()
        by_weight = dict(cursor.execute(COUNT_BY_WEIGHT).fetchall())
    order = {weight: position for position, weight in enumerate(WEIGHTS)}
    rows.sort(key=lambda row: (order[row[0]], row[1]))
    return {
        "snapshot": SOURCES_SNAPSHOT_DATE,
        "seed": SEED,
        "how": how(QUOTAS),
        "quotas": dict(QUOTAS),
        "labels_in_the_graph": {weight: by_weight.get(weight, 0) for weight in WEIGHTS},
        "sample": [
            {
                "number": number,
                "card": name,
                "set": set_code,
                "collector_number": collector_number,
                "face": "back" if position else "front",
                "tag": label,
                "weight": weight,
                "illustration_id": illustration_id,
                "tag_id": tag_id,
                "link": link(set_code, collector_number),
                "annotation": annotation,
            }
            for number, (
                weight,
                _,
                name,
                set_code,
                collector_number,
                label,
                annotation,
                illustration_id,
                tag_id,
                position,
            ) in enumerate(rows, start=1)
        ],
    }


def public(record: dict) -> dict:
    """The draw as the repo keeps it: every row without the volunteer's annotation."""
    return {
        **record,
        "sample": [
            {key: value for key, value in row.items() if key != "annotation"}
            for row in record["sample"]
        ],
    }


# The verdicts I may give, and how each is decided, written before any label is marked:
#   right       what the tag names can be seen in the picture. How prominent it is does
#               not matter: the weight is Tagger's, and I do not judge it.
#   wrong       it can't be seen, or what is there is something else.
#   can't tell  the picture alone can't show it: a plane or a place, how the art was
#               made, what the card does, or words; or the picture is too small or dark
#               to say. These are counted and reported, and left out of the share right.
# I judge the picture only, on the printing's Scryfall page and the face the table names:
# not the card's name, type line, rules text, set or frame.
VERDICTS = ("right", "wrong", "can't tell")
VERDICT_HEADING = "My verdict"
COLUMNS = ("#", "Card", "Tag", "Weight", "Link", VERDICT_HEADING)


def cell(text: str) -> str:
    """Text made safe for a table cell: a bar inside it would start a new cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def card_cell(row: dict) -> str:
    where = ", back face" if row["face"] == "back" else ""
    return cell(f"{row['card']} ({row['set']} #{row['collector_number']}{where})")


def table(record: dict) -> str:
    """The sample as a plain table to mark by hand, with an empty column for my verdict.

    The table shows the notes volunteers wrote on some labels, so it is kept out of the
    repo (marking/ is ignored by Git). `topdeck tags score --table` reads it back."""
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    for row in record["sample"]:
        tag = row["tag"] + (f" ({row['annotation']})" if row.get("annotation") else "")
        lines.append(
            f"| {row['number']} | {card_cell(row)} | {cell(tag)} | {words(row['weight'])} "
            f"| {row['link']} |  |"
        )
    return "\n".join(lines) + "\n"


def said(verdict: str) -> str:
    """A verdict as written in the table, in the words VERDICTS uses."""
    plain = " ".join(verdict.replace("\u2019", "'").strip().lower().split())
    return {"cant tell": "can't tell"}.get(plain, plain)


def read_table(draw: dict, text: str) -> dict:
    """Turn the table I marked into verdicts keyed by picture and tag, never by row.

    Each row is matched to the drawn label with its number, and its card, tag and weight
    must still be that label's, so a table from another draw, or one whose rows were
    moved or edited, is refused rather than scored. A row with no verdict yet is left
    out. Raises ValueError, naming the row, when anything does not match."""
    drawn = {row["number"]: row for row in draw["sample"]}
    verdicts, seen, header = [], set(), None
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [part.strip() for part in re.split(r"(?<!\\)\|", line.strip("|"))]
        if header is None:
            header = cells
            if tuple(cells) != COLUMNS:
                raise ValueError(f"line {line_number} is not the heading this table is made with")
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if len(cells) != len(COLUMNS):
            raise ValueError(f"line {line_number} has {len(cells)} cells, not {len(COLUMNS)}")
        number, card, tag, weight, _, verdict = cells
        row = drawn.get(int(number)) if number.isdigit() else None
        if row is None:
            raise ValueError(f"line {line_number} is not a drawn label: #{number}")
        if (
            card != card_cell(row)
            or not tag.startswith(cell(row["tag"]))
            or weight != words(row["weight"])
        ):
            raise ValueError(f"row #{number} is not the label drawn as #{number}")
        if row["number"] in seen:
            raise ValueError(f"row #{number} is in the table twice")
        seen.add(row["number"])
        if not verdict:
            continue
        if said(verdict) not in VERDICTS:
            raise ValueError(f"row #{number} is marked {verdict!r}, not right, wrong or can't tell")
        verdicts.append(
            {
                "number": row["number"],
                "illustration_id": row["illustration_id"],
                "tag_id": row["tag_id"],
                "verdict": said(verdict),
            }
        )
    if header is None:
        raise ValueError("there is no table in it")
    verdicts.sort(key=lambda entry: entry["number"])
    return {"seed": draw.get("seed"), "verdicts": verdicts}


def weighted(in_graph: dict, rows: dict) -> tuple[float, float]:
    """The share right across the weights, each weighted by its labels in the graph, and
    how many labels it is worth: with nearly every label of one weight, the overall rests
    on that weight's few drawn labels, and is worth little more than they are.

    `rows` maps a weight to (right, judged). The worth is Kish's effective number of a
    weighted sample: 1 / sum(w * w / n), with w each weight's share of the graph."""
    counted = [w for w in WEIGHTS if rows.get(w, (0, 0))[1]]
    total = sum(in_graph[w] for w in counted)
    if not total:
        return 0.0, 0.0
    share = sum(in_graph[w] * rows[w][0] / rows[w][1] for w in counted) / total
    worth = 1 / sum((in_graph[w] / total) ** 2 / rows[w][1] for w in counted)
    return share, worth


def score(draw: dict, marked: dict) -> dict:
    """Score my verdicts against the draw they were made on.

    `marked` holds {"verdicts": [{"illustration_id", "tag_id", "verdict"}]}, keyed by the
    picture and the tag, never by a row number alone; `read_table` makes it from the
    table I mark. Raises ValueError when a verdict is not for a drawn label, is given
    twice, or is not one of VERDICTS.

    The overall share right is weighted by the labels of each weight in the graph, and
    carries a Wilson interval at the number of labels it is worth. "Can't tell" labels
    are left out of every share, and counted."""
    drawn = {(row["illustration_id"], row["tag_id"]): row for row in draw["sample"]}
    verdicts = marked.get("verdicts") if isinstance(marked, dict) else None
    if not isinstance(verdicts, list):
        raise ValueError("the verdicts record has no list of verdicts")
    seen: dict[tuple[str, str], str] = {}
    for entry in verdicts:
        if not isinstance(entry, dict):
            raise ValueError("a verdict is not a picture, a tag and a verdict")
        key = (entry.get("illustration_id"), entry.get("tag_id"))
        if key not in drawn:
            raise ValueError(f"a verdict is for a label that was not drawn: {key}")
        if key in seen:
            raise ValueError(f"label #{drawn[key]['number']} is marked twice")
        if entry.get("verdict") not in VERDICTS:
            raise ValueError(
                f"label #{drawn[key]['number']} is marked neither right, wrong nor can't tell"
            )
        seen[key] = entry["verdict"]

    by_weight = {}
    for weight in WEIGHTS:
        keys = [key for key, row in drawn.items() if row["weight"] == weight]
        done = [seen[key] for key in keys if key in seen]
        right, wrong = done.count("right"), done.count("wrong")
        low, high = wilson(right, right + wrong)
        by_weight[weight] = {
            "drawn": len(keys),
            "marked": len(done),
            "right": right,
            "wrong": wrong,
            "cant_tell": done.count("can't tell"),
            "share_low": round(low, 6),
            "share_high": round(high, 6),
        }
    complete = len(seen) == len(drawn)
    in_graph = draw["labels_in_the_graph"]
    rows = {
        w: (by_weight[w]["right"], by_weight[w]["right"] + by_weight[w]["wrong"]) for w in WEIGHTS
    }
    share, worth = weighted(in_graph, rows)
    overall = None
    if complete and worth:
        low, high = wilson(share * worth, worth)
        overall = {
            "share_right": round(share, 6),
            "share_low": round(low, 6),
            "share_high": round(high, 6),
            "worth_labels": round(worth, 1),
        }
    return {
        "drawn": len(drawn),
        "marked": len(seen),
        "cant_tell": sum(row["cant_tell"] for row in by_weight.values()),
        "by_weight": by_weight,
        "overall": overall,
        "weighted_share_right": None if overall is None else overall["share_right"],
        "bar": BAR,
        "clears_the_bar": None if overall is None else overall["share_right"] >= BAR,
    }
