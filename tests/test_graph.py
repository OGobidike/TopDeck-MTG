import json

import psycopg
import pytest

from topdeck import graph
from topdeck.census import load_cards
from topdeck.cli import build_graph, count_graph

pytestmark = pytest.mark.db

# Worked out by hand from the invented cards in tests/fixtures.
EXPECTED = {
    "colours": 5,
    "types": 3,
    "subtypes": 14,
    "supertypes": 2,
    "keywords": 2,
    "formats": 2,
    "cards": 8,
    "faces": 6,
    "sets": 3,
    "artists": 2,
    "printings": 9,
    "card_colour": 10,
    "card_colour_identity": 11,
    "card_type": 9,
    "card_subtype": 14,
    "card_supertype": 3,
    "card_keyword": 2,
    "card_legality": 8,
    "face_colour": 2,
    "face_type": 6,
    "face_subtype": 6,
    "face_supertype": 0,
    "printing_artist": 9,
}


def ask(connection, schema, query, *arguments):
    with connection.cursor() as cursor:
        cursor.execute(f"SET search_path TO {schema}")
        return cursor.execute(query, arguments).fetchall()


def test_every_table_holds_what_the_invented_cards_say(invented_graph):
    connection, schema, counts = invented_graph
    assert counts == EXPECTED
    assert graph.count(connection, schema) == EXPECTED


# Exactly where each kind of link is read from, for the invented cards.
SOURCES = {
    "card_colour": {"oracle_cards.colors", "oracle_cards.card_faces[0].colors"},
    "card_colour_identity": {"oracle_cards.color_identity"},
    "card_type": {"oracle_cards.type_line"},
    "card_subtype": {"oracle_cards.type_line"},
    "card_supertype": {"oracle_cards.type_line"},
    "card_keyword": {"oracle_cards.keywords (all faces)"},
    "card_legality": {"oracle_cards.legalities"},
    "face_colour": {"oracle_cards.card_faces[0].colors", "oracle_cards.card_faces[1].colors"},
    "face_type": {"oracle_cards.card_faces[0].type_line", "oracle_cards.card_faces[1].type_line"},
    "face_subtype": {
        "oracle_cards.card_faces[0].type_line",
        "oracle_cards.card_faces[1].type_line",
    },
    "face_supertype": set(),
    "printing_artist": {"default_cards.artist"},
}


def test_every_link_says_exactly_where_it_came_from(invented_graph):
    connection, schema, _ = invented_graph
    assert set(SOURCES) == set(graph.LINK_TABLES)
    for table, expected in SOURCES.items():
        rows = ask(connection, schema, f"SELECT DISTINCT source, method FROM {table}")
        assert {source for source, _ in rows} == expected, table
        assert {method for _, method in rows} <= {"given"}, table
    printing_links = ask(
        connection, schema, "SELECT DISTINCT card_source, set_source, method FROM printings"
    )
    assert printing_links == [("default_cards.oracle_id", "default_cards.set", "given")]


def test_building_twice_leaves_one_graph_not_two(invented_graph, card_files):
    connection, schema, counts = invented_graph
    folder, oracle, printings_file = card_files
    cards, _ = load_cards(folder, oracle, printings_file)
    again = graph.build(
        connection, cards, graph.read_printings(folder, cards, printings_file), schema
    )
    connection.commit()
    assert again == counts == graph.count(connection, schema)
    leftovers = ask(
        connection,
        "public",
        "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s",
        schema + "_build",
    )
    assert leftovers == [(0,)]


def test_a_two_sided_card_is_its_front_face_and_keeps_its_back(invented_graph):
    connection, schema, _ = invented_graph
    name = "Village Lamplighter // Lamplit Horror"
    colours = ask(
        connection,
        schema,
        "SELECT colour, source FROM card_colour JOIN cards USING (card_id) WHERE name = %s",
        name,
    )
    assert colours == [("W", "oracle_cards.card_faces[0].colors")]
    subtypes = ask(
        connection,
        schema,
        "SELECT subtype FROM card_subtype JOIN cards USING (card_id) WHERE name = %s ORDER BY 1",
        name,
    )
    assert subtypes == [("Human",), ("Scout",)]
    back = ask(
        connection,
        schema,
        "SELECT f.name, fc.colour, fs.subtype FROM faces f "
        "JOIN cards c USING (card_id) "
        "JOIN face_colour fc USING (card_id, position) "
        "JOIN face_subtype fs USING (card_id, position) "
        "WHERE c.name = %s AND f.position = 1",
        name,
    )
    assert back == [("Lamplit Horror", "B", "Horror")]


def test_a_split_card_is_both_of_its_halves(invented_graph):
    connection, schema, _ = invented_graph
    types = ask(
        connection,
        schema,
        "SELECT type FROM card_type JOIN cards USING (card_id) WHERE name = %s ORDER BY 1",
        "Kindle // Quench",
    )
    assert types == [("Instant",), ("Sorcery",)]


def test_a_keyword_only_the_back_face_has_is_linked_to_the_card_and_says_so(invented_graph):
    """Scryfall gives keywords for the whole card. The invented card's back face has
    Menace and its front doesn't, yet the card carries Menace, labelled as all faces."""
    connection, schema, _ = invented_graph
    rows = ask(
        connection,
        schema,
        "SELECT keyword, source FROM card_keyword JOIN cards USING (card_id) WHERE name = %s",
        "Village Lamplighter // Lamplit Horror",
    )
    assert rows == [("Menace", graph.KEYWORD_SOURCE)]
    assert graph.KEYWORD_SOURCE == "oracle_cards.keywords (all faces)"


def test_an_adventure_card_is_only_its_creature(invented_graph):
    connection, schema, _ = invented_graph
    name = "Hedge Tinker // Tinker's Errand"
    types = ask(
        connection,
        schema,
        "SELECT type FROM card_type JOIN cards USING (card_id) WHERE name = %s",
        name,
    )
    assert types == [("Creature",)]
    faces = ask(
        connection,
        schema,
        "SELECT position, type FROM face_type JOIN cards USING (card_id) "
        "WHERE name = %s ORDER BY 1, 2",
        name,
    )
    assert faces == [(0, "Creature"), (1, "Sorcery")]


def test_only_cards_that_count_and_only_their_real_printings_are_loaded(invented_graph):
    connection, schema, _ = invented_graph
    names = {name for (name,) in ask(connection, schema, "SELECT name FROM cards")}
    assert "Old Road Sentinel" in names
    assert not names & {"Goblin", "Clown of Many Hats", "Rebalanced Spark", "Screen-Only Sprite"}
    sets = ask(
        connection,
        schema,
        "SELECT set_code FROM printings JOIN cards USING (card_id) WHERE name = %s",
        "Old Road Sentinel",
    )
    assert sets == [("old",)]


def test_a_card_knows_its_first_printing(invented_graph):
    connection, schema, _ = invented_graph
    rows = ask(
        connection,
        schema,
        "SELECT name, first_printed::text FROM cards WHERE name IN (%s, %s) ORDER BY 1",
        "Mossback Elder",
        "Old Road Sentinel",
    )
    assert rows == [("Mossback Elder", "2020-01-01"), ("Old Road Sentinel", "1995-06-01")]
    assert ask(connection, schema, "SELECT count(*) FROM cards WHERE first_printed IS NULL") == [
        (0,)
    ]


def test_power_is_kept_as_text_and_as_a_number_when_it_is_one(invented_graph):
    connection, schema, _ = invented_graph
    rows = ask(
        connection,
        schema,
        "SELECT name, power, power_number FROM cards WHERE name IN (%s, %s) ORDER BY 1",
        "Cinderpot Raider",
        "Lady of the Frozen Vault",
    )
    assert rows == [("Cinderpot Raider", "2", 2), ("Lady of the Frozen Vault", "*", None)]


def test_a_failed_build_leaves_the_old_graph_standing(invented_graph, card_files):
    connection, schema, counts = invented_graph
    folder, oracle, printings_file = card_files
    cards, _ = load_cards(folder, oracle, printings_file)
    orphan = graph.Printing(
        "10000000-0000-4000-8000-000000000099",
        "00000000-0000-4000-8000-000000000404",  # no such card
        "default_cards.oracle_id",
        "inv",
        "Invented Lands",
        "expansion",
        "99",
        "common",
        "2020-01-01",
        "Invented Artist",
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        graph.build(connection, cards, [orphan], schema)
    connection.rollback()
    assert graph.count(connection, schema) == counts
    assert not leftover_build_schema(connection, schema)


def leftover_build_schema(connection, schema) -> bool:
    found = ask(
        connection,
        "public",
        "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s",
        schema + "_build",
    )
    return found != [(0,)]


def test_a_build_that_fails_after_the_old_graph_is_dropped_still_leaves_it_standing(
    invented_graph, card_files, monkeypatch
):
    """The hardest moment: the old graph has been dropped and the new one not yet put in
    its place. A failure there must undo the drop too, which only one transaction can."""
    connection, schema, counts = invented_graph
    folder, oracle, printings_file = card_files
    cards, _ = load_cards(folder, oracle, printings_file)
    printings = graph.read_printings(folder, cards, printings_file)

    def fail_after_the_drop(cursor, fresh, live):
        live_left = ask(
            cursor.connection,
            "public",
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s",
            schema,
        )
        assert live_left == [(0,)], "by now the old graph should have been dropped"
        raise RuntimeError("the rename failed")

    monkeypatch.setattr(graph, "_rename", fail_after_the_drop)
    with pytest.raises(RuntimeError, match="the rename failed"):
        graph.build(connection, cards, printings, schema)
    connection.rollback()
    assert graph.count(connection, schema) == counts
    assert not leftover_build_schema(connection, schema)


def test_a_view_built_on_the_graph_stops_a_rebuild_rather_than_vanishing(
    invented_graph, card_files, database_url
):
    """The old graph is dropped with RESTRICT: anything that depends on it, such as the
    read-only views a later phase adds, makes the build fail instead of being destroyed."""
    connection, schema, counts = invented_graph
    folder, oracle, printings_file = card_files
    cards, _ = load_cards(folder, oracle, printings_file)
    printings = graph.read_printings(folder, cards, printings_file)
    outside = schema + "_views"
    with psycopg.connect(database_url, autocommit=True) as other:
        other.execute(f"CREATE SCHEMA {outside}")
        other.execute(f"CREATE VIEW {outside}.names AS SELECT name FROM {schema}.cards")
    try:
        with pytest.raises(psycopg.errors.DependentObjectsStillExist):
            graph.build(connection, cards, printings, schema)
        connection.rollback()
        assert graph.count(connection, schema) == counts
        assert ask(connection, outside, "SELECT count(*) FROM names") == [(counts["cards"],)]
    finally:
        # Let go of the view before another connection drops it, or the drop would wait.
        connection.rollback()
        with psycopg.connect(database_url, autocommit=True) as other:
            other.execute(f"DROP SCHEMA IF EXISTS {outside} CASCADE")


def test_a_schema_name_must_be_plain(database_url):
    with psycopg.connect(database_url) as connection:
        with pytest.raises(ValueError, match="not a plain schema name"):
            graph.count(connection, 'x"; DROP SCHEMA public CASCADE; --')


@pytest.mark.parametrize("name", ["public", "information_schema", "pg_catalog", "pg_toast"])
def test_a_build_refuses_the_schemas_postgresql_keeps(database_url, name):
    with psycopg.connect(database_url) as connection:
        with pytest.raises(ValueError, match="PostgreSQL keeps for itself"):
            graph.build(connection, [], [], name)


def test_the_build_command_ends_on_a_plain_verdict(card_files, database_url, schema, capsys):
    folder, oracle, printings_file = card_files
    assert build_graph(folder, database_url, schema, (oracle, printings_file)) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last == "The graph is built: 8 cards, 9 printings and 80 links."


def test_a_failed_build_ends_on_one_plain_line(
    card_files, database_url, schema, monkeypatch, capsys
):
    folder, oracle, printings_file = card_files

    def broken(*args, **kwargs):
        raise psycopg.errors.ForeignKeyViolation("insert violates a foreign key\nDETAIL: more")

    monkeypatch.setattr(graph, "build", broken)
    assert build_graph(folder, database_url, schema, (oracle, printings_file)) == 1
    printed = capsys.readouterr().out.strip().splitlines()
    assert printed == [
        "The graph was not built, and any graph already there is unchanged: "
        "insert violates a foreign key"
    ]


def test_the_count_command_matches_then_catches_a_changed_record(
    invented_graph, database_url, tmp_path, capsys
):
    _, schema, _ = invented_graph
    record = tmp_path / "graph.json"
    assert count_graph(record, True, database_url, schema) == 0
    assert count_graph(record, False, database_url, schema) == 0
    assert capsys.readouterr().out.strip().endswith(f"Every number matches {record}.")

    changed = json.loads(record.read_text())
    changed["tables"]["cards"] = 9
    record.write_text(json.dumps(changed))
    assert count_graph(record, False, database_url, schema) == 1
    assert "cards: counted 8, recorded 9" in capsys.readouterr().out


def test_the_count_command_explains_a_record_it_cannot_read(
    invented_graph, database_url, tmp_path, capsys
):
    _, schema, _ = invented_graph
    record = tmp_path / "graph.json"
    record.write_text("{ not json")
    assert count_graph(record, False, database_url, schema) == 1
    assert (
        capsys.readouterr()
        .out.strip()
        .splitlines()[-1]
        .startswith(f"The record at {record} is not valid JSON")
    )
    record.write_text('{"snapshot": "2026-11-21"}')
    assert count_graph(record, False, database_url, schema) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        f"The record at {record} has no table counts to check against."
    )


def test_the_count_command_says_when_the_graph_is_not_built(database_url, schema, tmp_path, capsys):
    assert count_graph(tmp_path / "graph.json", False, database_url, schema) == 1
    assert "The graph isn't built yet." in capsys.readouterr().out
