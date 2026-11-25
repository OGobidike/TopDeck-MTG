"""The graph: the cards that count, their real printings, and every link, in PostgreSQL.

A fact is stored as a link between two things: this card is red, this card is a Goblin,
this printing is by that artist. Every link row says where it came from and how.

Two kinds of source go in, and they are kept apart. Official facts come from Wizards'
cards and rulings as Scryfall publishes them (method "given"; a few rulings Scryfall
wrote itself are "scryfall"). Community labels come from Tagger, Scryfall's tagging
project, and say what a card does or what its picture shows (method "community").
No tag, checked or not, is ever the answer key for any score.

Building is safe to repeat. The graph is loaded into a fresh schema beside the live one
and swapped in only when the whole load has succeeded, all inside one transaction: if
any step fails, the old graph stands and the fresh schema is gone.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import psycopg
from psycopg import sql

from topdeck.cards import Card
from topdeck.census import is_a_real_printing, oracle_id_of
from topdeck.snapshot import ART_TAGS, DEFAULT_CARDS, ORACLE_TAGS, RULINGS, BulkFile, read_entries

DATABASE_ENV = "TOPDECK_DATABASE_URL"
# The local development database that docker-compose.yml starts. It holds nothing
# private and listens on this machine only, so its password is no secret.
DEFAULT_DATABASE_URL = "postgresql://topdeck:topdeck@localhost:5544/topdeck"
SCHEMA = "topdeck"

COLOURS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
STORED_LEGALITIES = frozenset({"legal", "restricted", "banned"})
GIVEN = "given"
SCRYFALL = "scryfall"
COMMUNITY = "community"
WEIGHTS = ("weak", "median", "strong", "very_strong")
# Scryfall lists keywords for the whole card, not for each face, so a keyword only the
# back face has is still linked to the card. This is the one exception to "a card is its
# front face", and the source says so.
KEYWORD_SOURCE = "oracle_cards.keywords (all faces)"

# Things first, then the links between them: the order the tables are loaded in.
THING_TABLES = (
    "colours",
    "types",
    "subtypes",
    "supertypes",
    "keywords",
    "formats",
    "cards",
    "faces",
    "sets",
    "artists",
    "printings",
    "rulings",
    "illustrations",
    "art_tags",
    "oracle_tags",
)
# Links read from official fields.
GIVEN_LINK_TABLES = (
    "card_colour",
    "card_colour_identity",
    "card_type",
    "card_subtype",
    "card_supertype",
    "card_keyword",
    "card_legality",
    "face_colour",
    "face_type",
    "face_subtype",
    "face_supertype",
    "printing_artist",
    "printing_illustration",
)
# Links from Tagger's community labels.
COMMUNITY_LINK_TABLES = (
    "card_oracle_tag",
    "illustration_art_tag",
    "art_tag_parent",
    "oracle_tag_parent",
)
LINK_TABLES = GIVEN_LINK_TABLES + COMMUNITY_LINK_TABLES
# The build's own report: how much it read from each file, and what it read but did not
# load, and why. Neither is a thing or a link.
REPORT_TABLES = ("files_read", "skipped")
TABLES = THING_TABLES + LINK_TABLES

_SCHEMA_NAME = re.compile(r"[a-z_][a-z0-9_]*")
# Schemas PostgreSQL itself keeps, which a build must never drop or replace.
_RESERVED = frozenset({"public", "information_schema"})


class DatabaseUnreachable(Exception):
    """The database did not answer. The message says where it was looked for."""


def database_url() -> str:
    return os.environ.get(DATABASE_ENV, DEFAULT_DATABASE_URL)


def where(url: str) -> str:
    """The host and port of a database address, with no password in it."""
    try:
        info = psycopg.conninfo.conninfo_to_dict(url)
    except psycopg.Error:
        return "the address given"
    return f"{info.get('host', 'localhost')}:{info.get('port', 5432)}"


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection, or raise DatabaseUnreachable with a plain message."""
    url = url or database_url()
    try:
        return psycopg.connect(url, connect_timeout=5)
    except psycopg.OperationalError as error:
        raise DatabaseUnreachable(
            f"Could not reach the database at {where(url)}. "
            "Start it with: docker compose up -d --wait"
        ) from error


def _checked(schema: str) -> str:
    if not _SCHEMA_NAME.fullmatch(schema):
        raise ValueError(f"{schema!r} is not a plain schema name")
    if schema in _RESERVED or schema.startswith("pg_"):
        raise ValueError(f"{schema!r} is a schema PostgreSQL keeps for itself")
    return schema


@dataclass(frozen=True)
class Printing:
    """One real printing of a card that counts."""

    printing_id: str
    card_id: str
    card_source: str
    set_code: str
    set_name: str
    set_type: str
    collector_number: str
    rarity: str
    released_at: str
    artist: str | None
    # (position, illustration id, source) for each picture: one, or one per face.
    illustrations: tuple[tuple[int, str, str], ...] = ()


def illustrations_of(entry: dict) -> tuple[tuple[int, str, str], ...]:
    """A printing's pictures. A card with one picture keeps its id on the printing; a
    card with a picture on each face keeps one on each face."""
    if entry.get("illustration_id"):
        return ((0, entry["illustration_id"], "default_cards.illustration_id"),)
    return tuple(
        (position, face["illustration_id"], f"default_cards.card_faces[{position}].illustration_id")
        for position, face in enumerate(entry.get("card_faces") or ())
        if face.get("illustration_id")
    )


def real_printings(entries: Iterable[dict], card_ids: set[str]) -> Iterator[Printing]:
    """The real printings, out of every printing, of the cards that count."""
    for entry in entries:
        if not is_a_real_printing(entry):
            continue
        card_id = oracle_id_of(entry)
        if card_id not in card_ids:
            continue
        yield Printing(
            printing_id=entry["id"],
            card_id=card_id,
            # A reversible card keeps its card id on its faces, not on the printing.
            card_source=(
                "default_cards.oracle_id"
                if "oracle_id" in entry
                else "default_cards.card_faces[0].oracle_id"
            ),
            set_code=entry["set"],
            set_name=entry["set_name"],
            set_type=entry["set_type"],
            collector_number=entry.get("collector_number", ""),
            rarity=entry.get("rarity", ""),
            released_at=entry["released_at"],
            artist=entry.get("artist") or None,
            illustrations=illustrations_of(entry),
        )


def read_printings(
    folder: Path, cards: Iterable[Card], printings_file: BulkFile = DEFAULT_CARDS
) -> list[Printing]:
    card_ids = {card.oracle_id for card in cards}
    return list(real_printings(read_entries(folder / printings_file.filename), card_ids))


@dataclass
class Sources:
    """The rulings and the community tags. Rulings and tag links are cut down to what
    touches the cards that count, and everything left out is counted with its reason.
    Every tag is kept, linked or not, so the tag tree stays whole."""

    rulings: list[tuple] = field(default_factory=list)
    art_tags: list[tuple] = field(default_factory=list)
    art_tag_parents: list[tuple] = field(default_factory=list)
    illustration_tags: list[tuple] = field(default_factory=list)
    oracle_tags: list[tuple] = field(default_factory=list)
    oracle_tag_parents: list[tuple] = field(default_factory=list)
    card_tags: list[tuple] = field(default_factory=list)
    read: dict[str, int] = field(default_factory=dict)
    skipped: dict[tuple[str, str], int] = field(default_factory=dict)

    def skip(self, what: str, reason: str) -> None:
        self.skipped[(what, reason)] = self.skipped.get((what, reason), 0) + 1


# Why a tag link was read but not loaded.
SKIP_REASONS = {
    "oracle": "on a card that doesn't count",
    "art": "on a picture that no real printing of a counted card has",
}


def _tags(entries: Iterable[dict], kind: str, keep, sources: Sources) -> tuple[list, list, list]:
    """Read one of Tagger's files: every tag and its parents, so the tree stays whole,
    and the taggings that touch something kept. `keep` says whether a tagged id is a card,
    or picture, that counts."""
    tags, parents, taggings = [], [], []
    target = "illustration_id" if kind == "art" else "oracle_id"
    source = f"{kind}_tags.taggings.{target}"
    read = 0
    for tag in entries:
        tags.append((tag["id"], tag["label"], tag["slug"], tag.get("description")))
        for parent in tag.get("parent_ids") or ():
            parents.append((tag["id"], parent, f"{kind}_tags.parent_ids", COMMUNITY))
        for tagging in tag.get("taggings") or ():
            read += 1
            if not keep(tagging[target]):
                sources.skip(f"{kind} tag links", SKIP_REASONS[kind])
                continue
            taggings.append(
                (
                    tagging[target],
                    tag["id"],
                    tagging["weight"],
                    tagging.get("annotation"),
                    source,
                    COMMUNITY,
                )
            )
    sources.read[f"{kind} tags"] = len(tags)
    sources.read[f"{kind} tag links"] = read
    return tags, parents, taggings


def read_sources(
    folder: Path,
    cards: Iterable[Card],
    printings: Iterable[Printing],
    files: tuple[BulkFile, BulkFile, BulkFile] = (RULINGS, ORACLE_TAGS, ART_TAGS),
) -> Sources:
    """Read the rulings, Oracle Tags and Art Tags, keeping what touches the cards that
    count and counting the rest."""
    rulings_file, oracle_tags_file, art_tags_file = files
    card_ids = {card.oracle_id for card in cards}
    pictures = {picture for p in printings for _, picture, _ in p.illustrations}
    sources = Sources()

    seen: set[tuple] = set()
    read = by_scryfall = 0
    for ruling in read_entries(folder / rulings_file.filename):
        read += 1
        by_scryfall += ruling["source"] == SCRYFALL
        if ruling["oracle_id"] not in card_ids:
            sources.skip("rulings", "for a card that doesn't count")
            continue
        key = (ruling["oracle_id"], ruling["source"], ruling["published_at"], ruling["comment"])
        if key in seen:
            sources.skip("rulings", "an exact repeat of another ruling")
            continue
        seen.add(key)
        sources.rulings.append(
            (
                len(sources.rulings) + 1,
                ruling["oracle_id"],
                "rulings.oracle_id",
                ruling["source"],
                ruling["published_at"],
                ruling["comment"],
                GIVEN if ruling["source"] == "wotc" else SCRYFALL,
            )
        )
    sources.read["rulings"] = read
    sources.read["rulings written by Scryfall"] = by_scryfall

    tags, parents, taggings = _tags(
        read_entries(folder / oracle_tags_file.filename), "oracle", card_ids.__contains__, sources
    )
    sources.oracle_tags, sources.oracle_tag_parents, sources.card_tags = tags, parents, taggings
    tags, parents, taggings = _tags(
        read_entries(folder / art_tags_file.filename), "art", pictures.__contains__, sources
    )
    sources.art_tags, sources.art_tag_parents, sources.illustration_tags = tags, parents, taggings
    return sources


def _colour_source(card: Card) -> str:
    """Scryfall keeps a two-sided card's colours on its faces, and the card is its front."""
    if card.faces and card.faces[0].colours is not None:
        return "oracle_cards.card_faces[0].colors"
    return "oracle_cards.colors"


def _rows(
    cards: list[Card], printings: list[Printing], sources: Sources | None = None
) -> dict[str, list[tuple]]:
    """Every row of every table, worked out in memory before anything is written."""
    sources = sources or Sources()
    rows: dict[str, list[tuple]] = {table: [] for table in (*TABLES, *REPORT_TABLES)}
    types, subtypes, supertypes, keywords, formats = set(), set(), set(), set(), set()

    rows["colours"] = sorted(COLOURS.items())

    for card in cards:
        key = card.oracle_id
        rows["cards"].append(
            (
                key,
                card.name,
                card.layout,
                card.mana_cost,
                card.mana_value,
                card.rules_text,
                card.power,
                card.power_number,
                card.toughness,
                None,
            )
        )
        colour_source = _colour_source(card)
        for colour in sorted(card.colours):
            rows["card_colour"].append((key, colour, colour_source, GIVEN))
        for colour in sorted(card.colour_identity):
            rows["card_colour_identity"].append((key, colour, "oracle_cards.color_identity", GIVEN))
        for name in card.type_line.types:
            types.add(name)
            rows["card_type"].append((key, name, "oracle_cards.type_line", GIVEN))
        for name in card.type_line.subtypes:
            subtypes.add(name)
            rows["card_subtype"].append((key, name, "oracle_cards.type_line", GIVEN))
        for name in card.type_line.supertypes:
            supertypes.add(name)
            rows["card_supertype"].append((key, name, "oracle_cards.type_line", GIVEN))
        for name in dict.fromkeys(card.keywords):
            keywords.add(name)
            rows["card_keyword"].append((key, name, KEYWORD_SOURCE, GIVEN))
        for name, status in sorted(card.legalities.items()):
            formats.add(name)
            if status in STORED_LEGALITIES:
                rows["card_legality"].append((key, name, status, "oracle_cards.legalities", GIVEN))

        for position, face in enumerate(card.faces):
            field = f"oracle_cards.card_faces[{position}]"
            rows["faces"].append(
                (
                    key,
                    position,
                    face.name,
                    face.mana_cost,
                    face.rules_text,
                    face.power,
                    face.toughness,
                )
            )
            for colour in sorted(face.colours or ()):
                rows["face_colour"].append((key, position, colour, f"{field}.colors", GIVEN))
            for name in dict.fromkeys(face.type_line.types):
                types.add(name)
                rows["face_type"].append((key, position, name, f"{field}.type_line", GIVEN))
            for name in dict.fromkeys(face.type_line.subtypes):
                subtypes.add(name)
                rows["face_subtype"].append((key, position, name, f"{field}.type_line", GIVEN))
            for name in dict.fromkeys(face.type_line.supertypes):
                supertypes.add(name)
                rows["face_supertype"].append((key, position, name, f"{field}.type_line", GIVEN))

    for table, names in (
        ("types", types),
        ("subtypes", subtypes),
        ("supertypes", supertypes),
        ("keywords", keywords),
        ("formats", formats),
    ):
        rows[table] = [(name,) for name in sorted(names)]

    sets: dict[str, tuple[str, str, str]] = {}
    artist_ids: dict[str, int] = {}
    for printing in sorted(printings, key=lambda p: p.printing_id):
        name, set_type, first = sets.get(
            printing.set_code, (printing.set_name, printing.set_type, printing.released_at)
        )
        sets[printing.set_code] = (name, set_type, min(first, printing.released_at))
        rows["printings"].append(
            (
                printing.printing_id,
                printing.card_id,
                printing.card_source,
                printing.set_code,
                "default_cards.set",
                printing.collector_number,
                printing.rarity,
                printing.released_at,
                GIVEN,
            )
        )
    for name in sorted({p.artist for p in printings if p.artist}):
        artist_ids[name] = len(artist_ids) + 1
    rows["artists"] = [(artist_id, name) for name, artist_id in artist_ids.items()]
    rows["sets"] = [(code, *facts) for code, facts in sorted(sets.items())]
    pictures: set[str] = set()
    for printing in printings:
        if printing.artist:
            rows["printing_artist"].append(
                (printing.printing_id, artist_ids[printing.artist], "default_cards.artist", GIVEN)
            )
        for position, picture, source in printing.illustrations:
            pictures.add(picture)
            rows["printing_illustration"].append(
                (printing.printing_id, position, picture, source, GIVEN)
            )
    rows["illustrations"] = [(picture,) for picture in sorted(pictures)]

    rows["rulings"] = sources.rulings
    rows["art_tags"] = sources.art_tags
    rows["art_tag_parent"] = sources.art_tag_parents
    rows["illustration_art_tag"] = sources.illustration_tags
    rows["oracle_tags"] = sources.oracle_tags
    rows["oracle_tag_parent"] = sources.oracle_tag_parents
    rows["card_oracle_tag"] = sources.card_tags
    rows["files_read"] = sorted(sources.read.items())
    rows["skipped"] = [(what, reason, n) for (what, reason), n in sorted(sources.skipped.items())]
    return rows


def build(
    connection: psycopg.Connection,
    cards: list[Card],
    printings: list[Printing],
    schema: str = SCHEMA,
    sources: Sources | None = None,
) -> dict[str, int]:
    """Load the graph into a fresh schema and swap it in. Returns the row counts."""
    live = sql.Identifier(_checked(schema))
    fresh = sql.Identifier(_checked(schema) + "_build")
    rows = _rows(cards, printings, sources)
    layout = resources.files("topdeck").joinpath("sql/schema.sql").read_text(encoding="utf-8")

    with connection.transaction(), connection.cursor() as cursor:
        # The fresh schema is this build's own scratch space: anything left in it by a
        # build that was cut off is thrown away.
        cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(fresh))
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(fresh))
        cursor.execute(sql.SQL("SET LOCAL search_path TO {}").format(fresh))
        cursor.execute(layout)
        for table in (*TABLES, *REPORT_TABLES):
            copy = sql.SQL("COPY {} FROM STDIN").format(sql.Identifier(table))
            with cursor.copy(copy) as stream:
                for row in rows[table]:
                    stream.write_row(row)
        cursor.execute(
            "UPDATE cards SET first_printed = firsts.first_printed "
            "FROM (SELECT card_id, min(released_at) AS first_printed "
            "      FROM printings GROUP BY card_id) AS firsts "
            "WHERE cards.card_id = firsts.card_id"
        )
        _drop_live(cursor, live)
        _rename(cursor, fresh, live)
    return {table: len(rows[table]) for table in TABLES}


def _drop_live(cursor: psycopg.Cursor, live: sql.Identifier) -> None:
    """Drop the old graph's tables, then its schema, both with RESTRICT.

    RESTRICT, not CASCADE: if anything else depends on the graph (such as the read-only
    views a later phase adds for the model's queries), the drop fails and the whole build
    is undone. Such things must be rebuilt on purpose, never destroyed in silence.
    """
    tables = sql.SQL(", ").join(
        sql.SQL("{}.{}").format(live, sql.Identifier(t)) for t in (*TABLES, *REPORT_TABLES)
    )
    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} RESTRICT").format(tables))
    cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} RESTRICT").format(live))


def _rename(cursor: psycopg.Cursor, fresh: sql.Identifier, live: sql.Identifier) -> None:
    cursor.execute(sql.SQL("ALTER SCHEMA {} RENAME TO {}").format(fresh, live))


def count(connection: psycopg.Connection, schema: str = SCHEMA) -> dict[str, int]:
    """Count the rows of every table, as the database holds them now."""
    counts = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            query = sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(_checked(schema)), sql.Identifier(table)
            )
            counts[table] = cursor.execute(query).fetchone()[0]
    return counts


def is_built(connection: psycopg.Connection, schema: str = SCHEMA) -> bool:
    """Whether any graph is there: a graph has its cards table."""
    return "cards" in _tables_present(connection, schema)


def is_current(connection: psycopg.Connection, schema: str = SCHEMA) -> bool:
    """Whether the graph there has every table this version of TopDeck builds. A graph
    built by an older version lacks some, and must be built again."""
    return set(TABLES + REPORT_TABLES) <= _tables_present(connection, schema)


def _tables_present(connection: psycopg.Connection, schema: str) -> set[str]:
    with connection.cursor() as cursor:
        rows = cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = ANY(%s)",
            (_checked(schema), list(TABLES + REPORT_TABLES)),
        ).fetchall()
    return {name for (name,) in rows}


# Said by every command that needs the graph, when it is missing or out of date.
NOT_BUILT = "The graph isn't built yet. Build it with: topdeck graph build"
OUT_OF_DATE = "The graph was built by an older TopDeck. Rebuild it with: topdeck graph build"


def not_ready(connection: psycopg.Connection, schema: str = SCHEMA) -> str | None:
    """Why the graph can't be used yet, or None when it can."""
    if not is_built(connection, schema):
        return NOT_BUILT
    if not is_current(connection, schema):
        return OUT_OF_DATE
    return None


# How much of the graph each source reaches: the cards that count with at least one link
# of each kind.
COVERAGE = {
    "given links": "SELECT count(DISTINCT card_id) FROM card_type",
    "rulings": "SELECT count(DISTINCT card_id) FROM rulings",
    "oracle tags": "SELECT count(DISTINCT card_id) FROM card_oracle_tag",
    "art tags": (
        "SELECT count(DISTINCT printings.card_id) FROM printings "
        "JOIN printing_illustration USING (printing_id) "
        "WHERE illustration_id IN (SELECT illustration_id FROM illustration_art_tag)"
    ),
}


def coverage(connection: psycopg.Connection, schema: str = SCHEMA) -> dict[str, int]:
    """How many cards that count each source reaches."""
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(_checked(schema))))
        return {name: cursor.execute(query).fetchone()[0] for name, query in COVERAGE.items()}


# Tags the build keeps although no loaded link uses them: every tag is kept so the tag
# tree stays whole, and these are counted so no one mistakes them for linked ones.
UNLINKED_TAGS = {
    "oracle tags": (
        "SELECT count(*) FROM oracle_tags WHERE NOT EXISTS "
        "(SELECT 1 FROM card_oracle_tag WHERE card_oracle_tag.tag_id = oracle_tags.tag_id)"
    ),
    "art tags": (
        "SELECT count(*) FROM art_tags WHERE NOT EXISTS "
        "(SELECT 1 FROM illustration_art_tag "
        "WHERE illustration_art_tag.tag_id = art_tags.tag_id)"
    ),
}


def unlinked_tags(connection: psycopg.Connection, schema: str = SCHEMA) -> dict[str, int]:
    """How many tags of each kind link to no card or picture that counts."""
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(_checked(schema))))
        return {name: cursor.execute(query).fetchone()[0] for name, query in UNLINKED_TAGS.items()}


def files_read(connection: psycopg.Connection, schema: str = SCHEMA) -> dict[str, int]:
    """How many entries the last build read from the rulings and tag files."""
    with connection.cursor() as cursor:
        query = sql.SQL("SELECT what, rows FROM {}.files_read ORDER BY what").format(
            sql.Identifier(_checked(schema))
        )
        return dict(cursor.execute(query).fetchall())


def skipped(connection: psycopg.Connection, schema: str = SCHEMA) -> dict[str, dict[str, int]]:
    """What the last build read but did not load, and why."""
    with connection.cursor() as cursor:
        query = sql.SQL("SELECT what, reason, rows FROM {}.skipped ORDER BY what, reason").format(
            sql.Identifier(_checked(schema))
        )
        report: dict[str, dict[str, int]] = {}
        for what, reason, rows in cursor.execute(query).fetchall():
            report.setdefault(what, {})[reason] = rows
        return report


def methods(connection: psycopg.Connection, schema: str = SCHEMA) -> dict[str, dict[str, int]]:
    """How many rulings are official and how many Scryfall's own."""
    with connection.cursor() as cursor:
        query = sql.SQL(
            "SELECT method, count(*) FROM {}.rulings GROUP BY method ORDER BY 1"
        ).format(sql.Identifier(_checked(schema)))
        return {"rulings": dict(cursor.execute(query).fetchall())}
