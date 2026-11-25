"""The rulings, the Oracle Tags and the Art Tags, on invented ones.

Every ruling and tag in tests/fixtures is made up, on the invented cards and their
invented pictures, so these tests hold no real ruling text. The counts below are worked
out by hand from those files.
"""

import hashlib
import json

import psycopg
import pytest
from psycopg import sql

from topdeck import graph, tags
from topdeck.census import load_cards
from topdeck.cli import answer_2024, count_graph, sample_tags, score_tags

# Read from the invented files, and what of it was left out and why.
READ = {
    "rulings": 7,
    "rulings written by Scryfall": 2,
    "oracle tags": 3,
    "oracle tag links": 7,
    "art tags": 3,
    "art tag links": 7,
}
SKIPPED = {
    "rulings": {
        "for a card that doesn't count": 2,
        "an exact repeat of another ruling": 1,
    },
    "oracle tag links": {"on a card that doesn't count": 3},
    "art tag links": {"on a picture that no real printing of a counted card has": 2},
}


def ask(connection, schema, query, *arguments):
    with connection.cursor() as cursor:
        cursor.execute(f"SET search_path TO {schema}")
        return cursor.execute(query, arguments).fetchall()


def test_reading_the_sources_keeps_what_touches_a_card_and_counts_the_rest(
    card_files, source_files
):
    folder, oracle, printings_file = card_files
    cards, _ = load_cards(folder, oracle, printings_file)
    printings = graph.read_printings(folder, cards, printings_file)
    sources = graph.read_sources(folder, cards, printings, source_files)
    assert sources.read == READ
    found: dict = {}
    for (what, reason), rows in sources.skipped.items():
        found.setdefault(what, {})[reason] = rows
    assert found == SKIPPED
    assert len(sources.rulings) == 4
    assert len(sources.card_tags) == 4
    assert len(sources.illustration_tags) == 5


@pytest.mark.db
def test_a_ruling_keeps_its_card_its_author_and_its_method(invented_graph):
    connection, schema, _ = invented_graph
    rows = ask(
        connection,
        schema,
        "SELECT c.name, r.author, r.method, r.card_source, r.published_at::text "
        "FROM rulings r JOIN cards c USING (card_id) ORDER BY r.ruling_id",
    )
    assert rows == [
        ("Mossback Elder", "wotc", "given", "rulings.oracle_id", "2020-01-01"),
        ("Mossback Elder", "wotc", "given", "rulings.oracle_id", "2021-02-02"),
        ("Kindle // Quench", "scryfall", "scryfall", "rulings.oracle_id", "2022-03-03"),
        (
            "Village Lamplighter // Lamplit Horror",
            "wotc",
            "given",
            "rulings.oracle_id",
            "2023-04-04",
        ),
    ]


@pytest.mark.db
def test_a_two_faced_printing_keeps_a_picture_for_each_face(invented_graph):
    connection, schema, _ = invented_graph
    rows = ask(
        connection,
        schema,
        "SELECT position, source FROM printing_illustration "
        "JOIN printings USING (printing_id) JOIN cards USING (card_id) "
        "WHERE name = %s ORDER BY position",
        "Village Lamplighter // Lamplit Horror",
    )
    assert rows == [
        (0, "default_cards.card_faces[0].illustration_id"),
        (1, "default_cards.card_faces[1].illustration_id"),
    ]
    shared = ask(
        connection,
        schema,
        "SELECT count(DISTINCT printing_id), count(DISTINCT illustration_id) "
        "FROM printing_illustration JOIN printings USING (printing_id) "
        "JOIN cards USING (card_id) WHERE name = %s",
        "Mossback Elder",
    )
    assert shared == [(2, 1)], "two printings of one picture share it"


@pytest.mark.db
def test_tags_keep_their_label_slug_description_parents_and_weights(invented_graph):
    connection, schema, _ = invented_graph
    assert ask(
        connection,
        schema,
        "SELECT t.label, p.label FROM art_tag_parent JOIN art_tags t USING (tag_id) "
        "JOIN art_tags p ON p.tag_id = parent_id",
    ) == [("invented beast", "invented creature")]
    assert ask(
        connection,
        schema,
        "SELECT slug, description FROM oracle_tags ORDER BY slug",
    ) == [
        ("invented-draw", None),
        ("invented-ramp", None),
        ("invented-removal", "A made-up tag for the tests."),
    ]
    weights = ask(
        connection,
        schema,
        "SELECT weight, count(*) FROM illustration_art_tag GROUP BY 1 ORDER BY 1",
    )
    assert weights == [("median", 2), ("strong", 1), ("very_strong", 1), ("weak", 1)]
    annotated = ask(
        connection, schema, "SELECT annotation FROM illustration_art_tag WHERE annotation <> ''"
    )
    assert annotated == [("On the left, invented",)]


@pytest.mark.db
def test_everything_left_out_is_counted_with_its_reason(invented_graph):
    connection, schema, _ = invented_graph
    assert graph.files_read(connection, schema) == dict(sorted(READ.items()))
    assert graph.skipped(connection, schema) == SKIPPED
    assert graph.methods(connection, schema) == {"rulings": {"given": 3, "scryfall": 1}}


@pytest.mark.db
def test_every_tag_is_kept_and_the_ones_no_link_uses_are_counted(invented_graph):
    """'invented draw' is used only on a card that doesn't count, and 'invented sky' on
    nothing at all: both stay, so the tag tree is whole, and both are counted."""
    connection, schema, _ = invented_graph
    assert graph.unlinked_tags(connection, schema) == {"oracle tags": 1, "art tags": 1}
    assert ask(connection, schema, "SELECT label FROM oracle_tags ORDER BY label") == [
        ("invented draw",),
        ("invented ramp",),
        ("invented removal",),
    ]


@pytest.mark.db
def test_coverage_counts_the_cards_each_source_reaches(invented_graph):
    connection, schema, _ = invented_graph
    assert graph.coverage(connection, schema) == {
        "given links": 8,
        "rulings": 3,
        "oracle tags": 3,
        "art tags": 4,
    }


@pytest.mark.db
def test_the_count_command_checks_coverage_and_what_was_left_out(
    invented_graph, database_url, tmp_path, capsys
):
    _, schema, _ = invented_graph
    record = tmp_path / "graph.json"
    assert count_graph(record, True, database_url, schema) == 0
    written = json.loads(record.read_text())
    assert written["skipped"] == SKIPPED
    assert written["sources_snapshot"] == "2026-11-22"
    assert written["unlinked_tags"] == {"oracle tags": 1, "art tags": 1}
    assert count_graph(record, False, database_url, schema) == 0
    assert capsys.readouterr().out.strip().endswith(f"Every number matches {record}.")

    written["skipped"]["rulings"]["an exact repeat of another ruling"] = 2
    record.write_text(json.dumps(written))
    assert count_graph(record, False, database_url, schema) == 1
    printed = capsys.readouterr().out
    assert "skipped: counted" in printed
    assert printed.strip().endswith(f"The graph does not match {record}.")


@pytest.mark.db
def test_the_art_tag_draw_is_the_same_every_time(invented_graph):
    connection, schema, _ = invented_graph
    first = tags.sample(connection, schema)
    assert first == tags.sample(connection, schema)
    # Fewer labels than the quotas: every one of them is drawn, ordered by weight.
    assert [row["weight"] for row in first["sample"]] == [
        "weak",
        "median",
        "median",
        "strong",
        "very_strong",
    ]
    assert [row["number"] for row in first["sample"]] == [1, 2, 3, 4, 5]
    assert first["labels_in_the_graph"] == {"weak": 1, "median": 2, "strong": 1, "very_strong": 1}
    assert first["how"] == tags.how(tags.QUOTAS)


def place(seed: str, row: dict) -> str:
    """A label's place in line, worked out here as the database works it out."""
    return hashlib.md5((seed + row["illustration_id"] + row["tag_id"]).encode()).hexdigest()


@pytest.mark.db
def test_the_draw_takes_each_weight_in_the_order_its_seeded_hash_gives(invented_graph, monkeypatch):
    """Two median labels, one to draw: the one whose hash of seed, picture and tag comes
    first. Another seed that reverses their order draws the other."""
    connection, schema, _ = invented_graph
    rows = tags.sample(connection, schema)["sample"]
    medians = [row for row in rows if row["weight"] == "median"]
    assert len(medians) == 2
    monkeypatch.setattr(tags, "QUOTAS", {"weak": 0, "median": 1, "strong": 0, "very_strong": 0})

    def drawn():
        (row,) = tags.sample(connection, schema)["sample"]
        return row["card"], row["tag"]

    first = min(medians, key=lambda row: place(tags.SEED, row))
    assert drawn() == (first["card"], first["tag"])
    other = next(
        seed
        for seed in (f"another seed {n}" for n in range(100))
        if min(medians, key=lambda row: place(seed, row)) is not first
    )
    monkeypatch.setattr(tags, "SEED", other)
    second = next(row for row in medians if row is not first)
    assert drawn() == (second["card"], second["tag"])


@pytest.mark.db
def test_the_art_tag_draw_keeps_to_its_quota_for_each_weight(invented_graph, monkeypatch):
    connection, schema, _ = invented_graph
    monkeypatch.setattr(tags, "QUOTAS", {"weak": 1, "median": 1, "strong": 0, "very_strong": 1})
    drawn = tags.sample(connection, schema)
    assert [row["weight"] for row in drawn["sample"]] == ["weak", "median", "very_strong"]
    assert drawn == tags.sample(connection, schema)


@pytest.mark.db
def test_each_drawn_picture_is_shown_on_its_earliest_real_printing(invented_graph):
    connection, schema, _ = invented_graph
    shown = {
        (row["card"], row["set"], row["collector_number"], row["link"])
        for row in tags.sample(connection, schema)["sample"]
        if row["card"] == "Mossback Elder"
    }
    assert shown == {("Mossback Elder", "inv", "1", "https://scryfall.com/card/inv/1")}


@pytest.mark.db
def test_each_drawn_label_names_its_picture_its_tag_and_its_face(invented_graph):
    connection, schema, _ = invented_graph
    rows = tags.sample(connection, schema)["sample"]
    back = [row for row in rows if row["face"] == "back"]
    assert [(row["card"], row["tag"]) for row in back] == [
        ("Village Lamplighter // Lamplit Horror", "invented creature")
    ]
    assert back[0]["illustration_id"] == "20000000-0000-4000-8000-0000000000e6"
    assert back[0]["tag_id"] == "30000000-0000-4000-8000-0000000000a1"
    assert {row["face"] for row in rows} == {"front", "back"}
    assert "(inv #7, back face)" in tags.table({"sample": back})


@pytest.mark.db
def test_the_sample_command_records_then_matches_and_writes_a_table_to_mark(
    invented_graph, database_url, tmp_path, capsys
):
    _, schema, _ = invented_graph
    record, table = tmp_path / "sample.json", tmp_path / "sample.md"
    assert sample_tags(record, True, database_url, schema, table=table) == 0
    assert sample_tags(record, False, database_url, schema) == 0
    assert capsys.readouterr().out.strip().endswith(f"The draw matches {record}.")
    lines = table.read_text().splitlines()
    assert lines[0] == "| # | Card | Tag | Weight | Link | My verdict |"
    assert len(lines) == 2 + 5
    assert all(line.endswith("|  |") for line in lines[2:])
    # The volunteer's note is in the table to mark by hand, never in the record.
    assert "On the left, invented" in table.read_text()
    assert "annotation" not in record.read_text()
    assert "On the left, invented" not in record.read_text()

    changed = json.loads(record.read_text())
    changed["sample"][0]["tag"] = "something else"
    record.write_text(json.dumps(changed))
    assert sample_tags(record, False, database_url, schema) == 1
    assert capsys.readouterr().out.strip().endswith(f"The draw does not match {record}.")


def test_a_link_leads_to_the_printing_on_scryfall():
    assert tags.link("sld", "2504") == "https://scryfall.com/card/sld/2504"
    assert tags.link("pwar", "18s") == "https://scryfall.com/card/pwar/18s"
    assert tags.link("plst", "DDO-20") == "https://scryfall.com/card/plst/DDO-20"
    assert tags.link("sld", "1★") == "https://scryfall.com/card/sld/1%E2%98%85"


def drawn_record() -> dict:
    """An invented draw of four labels, one of each weight, on invented cards."""
    rows = [
        {
            "number": n,
            "card": f"Invented Card {n}",
            "set": "inv",
            "collector_number": str(n),
            "face": "back" if n == 4 else "front",
            "tag": f"invented tag {n}",
            "weight": weight,
            "illustration_id": f"pic-{n}",
            "tag_id": f"tag-{n}",
            "link": tags.link("inv", str(n)),
        }
        for n, weight in enumerate(("weak", "median", "median", "very_strong"), start=1)
    ]
    return {
        "seed": "an invented seed",
        "labels_in_the_graph": {"weak": 10, "median": 80, "strong": 0, "very_strong": 10},
        "sample": rows,
    }


def verdicts(*marks: str) -> dict:
    return {
        "verdicts": [
            {"illustration_id": f"pic-{n}", "tag_id": f"tag-{n}", "verdict": mark}
            for n, mark in enumerate(marks, start=1)
        ]
    }


def marked_table(*marks: str, draw: dict | None = None) -> str:
    """The table `tags sample --table` writes, with my verdicts typed into its last column."""
    lines = tags.table(draw or drawn_record()).splitlines()
    for i, mark in enumerate(marks):
        lines[2 + i] = lines[2 + i][: -len("|  |")] + f"| {mark} |"
    return "\n".join(lines) + "\n"


def test_the_score_is_weighted_by_the_labels_of_each_weight_in_the_graph():
    found = tags.score(drawn_record(), verdicts("wrong", "right", "right", "right"))
    assert found["marked"] == found["drawn"] == 4
    assert found["by_weight"]["median"]["right"] == 2
    assert found["by_weight"]["weak"]["right"] == 0
    # 10 weak at 0%, 80 median at 100% and 10 very strong at 100%: 90% right.
    assert found["weighted_share_right"] == 0.9
    assert found["clears_the_bar"] is True
    median = found["by_weight"]["median"]
    low, high = median["share_low"], median["share_high"]
    assert 0 < low < 1 == high


def test_the_overall_share_carries_an_interval_at_the_labels_it_is_worth():
    found = tags.score(drawn_record(), verdicts("wrong", "right", "right", "right"))
    overall = found["overall"]
    # Weights of 0.1, 0.8 and 0.1 over 1, 2 and 1 labels: 1 / (0.01 + 0.32 + 0.01).
    assert overall["worth_labels"] == round(1 / 0.34, 1)
    low, high = tags.wilson(0.9 / 0.34, 1 / 0.34)
    assert (overall["share_low"], overall["share_high"]) == (round(low, 6), round(high, 6))
    assert overall["share_low"] < 0.9 < overall["share_high"]


def test_a_label_i_cant_tell_is_counted_and_left_out_of_every_share():
    found = tags.score(drawn_record(), verdicts("can't tell", "right", "wrong", "right"))
    assert found["cant_tell"] == 1 and found["marked"] == 4
    assert found["by_weight"]["weak"] == {
        "drawn": 1,
        "marked": 1,
        "right": 0,
        "wrong": 0,
        "cant_tell": 1,
        "share_low": 0.0,
        "share_high": 1.0,
    }
    # Weak is left out: 80 median at 50% and 10 very strong at 100%, over 90.
    assert found["weighted_share_right"] == round((80 * 0.5 + 10) / 90, 6)


def test_a_score_waits_for_every_verdict_and_refuses_stray_ones():
    part = tags.score(drawn_record(), verdicts("right", "right"))
    assert part["marked"] == 2 and part["weighted_share_right"] is None
    assert part["overall"] is None
    with pytest.raises(ValueError, match="not drawn"):
        tags.score(drawn_record(), {"verdicts": [{"illustration_id": "x", "tag_id": "y"}]})
    with pytest.raises(ValueError, match="neither right, wrong nor can't tell"):
        tags.score(drawn_record(), verdicts("maybe"))
    twice = verdicts("right")
    twice["verdicts"] *= 2
    with pytest.raises(ValueError, match="marked twice"):
        tags.score(drawn_record(), twice)


def test_the_marked_table_turns_into_verdicts_keyed_by_picture_and_tag():
    text = marked_table("Wrong", "right", "can\u2019t tell")
    marked = tags.read_table(drawn_record(), text)
    assert marked == {
        "seed": "an invented seed",
        "verdicts": [
            {"number": 1, "illustration_id": "pic-1", "tag_id": "tag-1", "verdict": "wrong"},
            {"number": 2, "illustration_id": "pic-2", "tag_id": "tag-2", "verdict": "right"},
            {"number": 3, "illustration_id": "pic-3", "tag_id": "tag-3", "verdict": "can't tell"},
        ],
    }
    assert tags.score(drawn_record(), marked)["marked"] == 3


def test_a_table_whose_rows_were_edited_is_refused():
    lines = marked_table("right", "wrong").splitlines()
    # A whole row moved keeps its verdict with its label.
    swapped = lines[:2] + [lines[3], lines[2]] + lines[4:]
    assert tags.read_table(drawn_record(), "\n".join(swapped)) == tags.read_table(
        drawn_record(), "\n".join(lines)
    )
    # A number edited would hand the verdict to another label.
    edited = lines[:3] + [lines[3].replace("| 2 |", "| 3 |", 1)]
    with pytest.raises(ValueError, match="row #3 is not the label drawn as #3"):
        tags.read_table(drawn_record(), "\n".join(edited))
    renumbered = [lines[0], lines[1], lines[2].replace("| 1 |", "| 9 |", 1)]
    with pytest.raises(ValueError, match="not a drawn label: #9"):
        tags.read_table(drawn_record(), "\n".join(renumbered))
    with pytest.raises(ValueError, match="marked 'maybe'"):
        tags.read_table(drawn_record(), marked_table("maybe"))
    with pytest.raises(ValueError, match="not the heading"):
        tags.read_table(drawn_record(), lines[0].replace("My verdict", "Verdict"))
    with pytest.raises(ValueError, match="no table"):
        tags.read_table(drawn_record(), "nothing to see")


def test_a_bar_in_a_volunteers_note_does_not_break_the_table():
    draw = drawn_record()
    draw["sample"][0]["annotation"] = "left | right, invented"
    text = marked_table("right", draw=draw)
    assert "left \\| right, invented" in text
    assert tags.read_table(tags.public(draw), text)["verdicts"][0]["verdict"] == "right"


def test_the_score_command_waits_for_verdicts_then_scores_them(tmp_path, capsys):
    draw, marked = tmp_path / "sample.json", tmp_path / "verdicts.json"
    draw.write_text(json.dumps(drawn_record()))
    assert score_tags(draw, marked) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        f"Nothing was scored: no verdicts are recorded yet in {marked}."
    )
    marked.write_text(json.dumps(verdicts("wrong", "right", "right", "right")))
    assert score_tags(draw, marked) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith("90.0% are right (95% interval ")
    assert last.endswith("), which clears the bar of 90%.")
    marked.write_text(json.dumps(verdicts("maybe")))
    assert score_tags(draw, marked) == 1
    assert capsys.readouterr().out.strip().startswith("The verdicts could not be scored:")


def test_the_score_command_reads_the_marked_table_and_records_its_verdicts(tmp_path, capsys):
    draw, marked, table = (tmp_path / name for name in ("s.json", "v.json", "t.md"))
    draw.write_text(json.dumps(drawn_record()))
    assert score_tags(draw, marked, table) == 1
    assert capsys.readouterr().out.strip() == (
        f"Nothing was scored: there is no marked table at {table}."
    )
    table.write_text(marked_table("wrong", "right", "right", "right"))
    assert score_tags(draw, marked, table) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == f"Read 4 verdicts from {table}, recorded in {marked}."
    assert out[-1].endswith("which clears the bar of 90%.")
    recorded = json.loads(marked.read_text())
    assert [row["verdict"] for row in recorded["verdicts"]] == ["wrong", "right", "right", "right"]
    # The recorded verdicts score the same without the table.
    assert score_tags(draw, marked) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == out[-1]
    table.write_text(marked_table("maybe"))
    assert score_tags(draw, marked, table) == 1
    assert capsys.readouterr().out.strip().startswith(f"The table at {table} could not be read:")


@pytest.mark.db
def test_a_graph_built_by_an_older_topdeck_is_named_as_such(
    invented_graph, database_url, tmp_path, capsys
):
    """A graph without the new tables: each command says to rebuild it, in plain words."""
    connection, schema, _ = invented_graph
    with psycopg.connect(database_url, autocommit=True) as other:
        other.execute(sql.SQL("DROP TABLE {}.illustration_art_tag").format(sql.Identifier(schema)))
    assert graph.is_built(connection, schema) and not graph.is_current(connection, schema)
    for run in (
        lambda: count_graph(tmp_path / "graph.json", False, database_url, schema),
        lambda: answer_2024(tmp_path / "a.json", tmp_path / "a.md", False, database_url, schema),
        lambda: sample_tags(tmp_path / "s.json", False, database_url, schema),
    ):
        assert run() == 1
        assert capsys.readouterr().out.strip() == graph.OUT_OF_DATE
