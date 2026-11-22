"""The graph: the cards that count, their real printings, and every given link, in PostgreSQL.

A fact is stored as a link between two things: this card is red, this card is a Goblin,
this printing is by that artist. Every link row says where it came from.

Building is safe to repeat. The graph is loaded into a fresh schema beside the live one
and swapped in only when the whole load has succeeded, all inside one transaction: if
any step fails, the old graph stands and the fresh schema is gone.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import psycopg
from psycopg import sql

from topdeck.cards import Card
from topdeck.census import is_a_real_printing, oracle_id_of
from topdeck.snapshot import DEFAULT_CARDS, BulkFile, read_entries

DATABASE_ENV = "TOPDECK_DATABASE_URL"
# The local development database that docker-compose.yml starts. It holds nothing
# private and listens on this machine only, so its password is no secret.
DEFAULT_DATABASE_URL = "postgresql://topdeck:topdeck@localhost:5544/topdeck"
SCHEMA = "topdeck"

COLOURS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
STORED_LEGALITIES = frozenset({"legal", "restricted", "banned"})
GIVEN = "given"
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
)
LINK_TABLES = (
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
)
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
        )


def read_printings(
    folder: Path, cards: Iterable[Card], printings_file: BulkFile = DEFAULT_CARDS
) -> list[Printing]:
    card_ids = {card.oracle_id for card in cards}
    return list(real_printings(read_entries(folder / printings_file.filename), card_ids))


def _colour_source(card: Card) -> str:
    """Scryfall keeps a two-sided card's colours on its faces, and the card is its front."""
    if card.faces and card.faces[0].colours is not None:
        return "oracle_cards.card_faces[0].colors"
    return "oracle_cards.colors"


def _rows(cards: list[Card], printings: list[Printing]) -> dict[str, list[tuple]]:
    """Every row of every table, worked out in memory before anything is written."""
    rows: dict[str, list[tuple]] = {table: [] for table in TABLES}
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
    for printing in printings:
        if printing.artist:
            rows["printing_artist"].append(
                (printing.printing_id, artist_ids[printing.artist], "default_cards.artist", GIVEN)
            )
    return rows


def build(
    connection: psycopg.Connection,
    cards: list[Card],
    printings: list[Printing],
    schema: str = SCHEMA,
) -> dict[str, int]:
    """Load the graph into a fresh schema and swap it in. Returns the row counts."""
    live = sql.Identifier(_checked(schema))
    fresh = sql.Identifier(_checked(schema) + "_build")
    rows = _rows(cards, printings)
    layout = resources.files("topdeck").joinpath("sql/schema.sql").read_text(encoding="utf-8")

    with connection.transaction(), connection.cursor() as cursor:
        # The fresh schema is this build's own scratch space: anything left in it by a
        # build that was cut off is thrown away.
        cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(fresh))
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(fresh))
        cursor.execute(sql.SQL("SET LOCAL search_path TO {}").format(fresh))
        cursor.execute(layout)
        for table in TABLES:
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
    tables = sql.SQL(", ").join(sql.SQL("{}.{}").format(live, sql.Identifier(t)) for t in TABLES)
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
    with connection.cursor() as cursor:
        found = cursor.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = 'cards'",
            (_checked(schema),),
        ).fetchone()
    return found is not None
