import math

import pytest

from topdeck import answers
from topdeck.cli import answer_2024, count_graph
from topdeck.graph import DatabaseUnreachable, connect, where


def test_a_wilson_interval_brackets_the_share():
    low, high = answers.wilson(569, 669)
    assert low < 569 / 669 < high
    assert round(low, 3) == 0.822 and round(high, 3) == 0.876


def test_a_wilson_interval_does_not_shrink_to_nothing_at_every_card():
    low, high = answers.wilson(57, 57)
    assert high == 1.0
    assert 0.93 < low < 0.95


def test_lift_is_the_share_in_the_group_over_the_share_among_everyone():
    result = answers.lift_with_interval(both=80, group=100, colour=250, everyone=1000)
    assert result["share"] == 0.8
    assert result["lift"] == 3.2  # 0.8 / 0.25
    assert result["lift_low"] < 3.2 < result["lift_high"]
    assert result["share_low"] < 0.8 < result["share_high"]


def test_a_lifts_interval_is_the_shares_interval_over_the_base():
    result = answers.lift_with_interval(569, 669, 4327, 18080)
    low, high = answers.wilson(569, 669)
    base = 4327 / 18080
    assert result["lift_low"] == round(low / base, 6)
    assert result["lift_high"] == round(high / base, 6)


def test_a_full_share_still_has_room_below_its_lift():
    """When every card in the group has the colour, a resampled interval collapses onto
    the base's noise. The Wilson share interval doesn't, so neither does the lift's."""
    result = answers.lift_with_interval(57, 57, 6600, 32495)
    assert result["share"] == 1.0 and result["share_high"] == 1.0
    assert result["lift_low"] < 0.95 * result["lift"]
    assert result["lift_high"] == result["lift"]


def test_the_same_counts_always_give_the_same_answer():
    assert answers.lift_with_interval(80, 100, 250, 1000) == answers.lift_with_interval(
        80, 100, 250, 1000
    )


def test_a_bigger_group_gives_a_narrower_interval():
    small = answers.lift_with_interval(8, 10, 250, 1000)
    large = answers.lift_with_interval(320, 400, 250, 1000)
    assert (large["lift_high"] - large["lift_low"]) < (small["lift_high"] - small["lift_low"])


def test_evenness_is_one_when_even_and_nought_when_one_colour():
    assert answers.evenness([10, 10, 10, 10, 10]) == pytest.approx(1.0)
    assert answers.evenness([50, 0, 0, 0, 0]) == 0.0
    assert 0 < answers.evenness([40, 5, 5, 0, 0]) < 0.6


def test_differences_are_exact():
    recorded = {"rows": [{"cards": 10, "lift": 3.0, "lift_low": 2.5, "lift_high": 3.5}]}
    same = {"rows": [{"cards": 10, "lift": 3.0, "lift_low": 2.5 + 1e-12, "lift_high": 3.5}]}
    close = {"rows": [{"cards": 10, "lift": 3.0, "lift_low": 2.501, "lift_high": 3.5}]}
    miscount = {"rows": [{"cards": 11, "lift": 3.0, "lift_low": 2.5, "lift_high": 3.5}]}
    assert answers.differences(same, recorded) == []
    assert answers.differences(close, recorded) == ["rows.0.lift_low: found 2.501, recorded 2.5"]
    assert answers.differences(miscount, recorded) == ["rows.0.cards: found 11, recorded 10"]
    assert answers.differences({"rows": []}, recorded) == ["rows: found 0 rows, recorded 1"]


def test_a_number_that_is_not_a_number_never_matches():
    problems = answers.differences({"lift_low": math.nan}, {"lift_low": math.nan})
    assert problems == ["lift_low: found nan, recorded nan, and NaN never matches"]


def test_an_unreachable_database_is_explained_in_plain_words(tmp_path, capsys):
    nowhere = "postgresql://topdeck:topdeck@127.0.0.1:1/topdeck"
    with pytest.raises(DatabaseUnreachable, match="Could not reach the database at 127.0.0.1:1"):
        connect(nowhere)
    assert count_graph(tmp_path / "graph.json", False, nowhere) == 1
    printed = capsys.readouterr().out
    assert "docker compose up -d --wait" in printed
    assert "topdeck:topdeck" not in printed  # the address is shown without its password


def test_the_place_of_a_database_never_shows_its_password():
    assert where("postgresql://someone:secret@db.example:6543/cards") == "db.example:6543"


@pytest.mark.db
def test_the_invented_elves_are_green_by_hand(invented_graph):
    """Seven invented creatures. Two are Elves, and both are green. Two of the seven are
    green, so the lift is 1.0 / (2 / 7) = 3.5. The one Goblin is the one red creature:
    1.0 / (1 / 7) = 7."""
    connection, schema, _ = invented_graph
    found = answers.answer(connection, schema)
    one = found["elves_and_goblins"]
    assert one["creatures"] == 7
    assert one["elves_green"]["cards"] == 2
    assert one["elves_green"]["with_colour"] == 2
    assert one["elves_green"]["share"] == 1.0
    assert one["elves_green"]["lift"] == 3.5
    assert one["goblins_red"]["lift"] == 7.0
    low, high = one["elves_green"]["share_low"], one["elves_green"]["share_high"]
    assert low < 1.0 == high
    exact_low, _ = answers.wilson(2, 2)
    assert one["elves_green"]["lift_low"] == round(exact_low / (2 / 7), 6)


@pytest.mark.db
def test_the_invented_artists_are_counted_per_printing(invented_graph):
    """Nine real printings: eight by one artist, one by another. Counted the 2024 way,
    each card's earliest real printing only, the second artist's later reprint is dropped.
    One invented card's only other printing is digital, and that never counts."""
    connection, schema, _ = invented_graph
    two = answers.answer(connection, schema)["artists"]
    assert two["artists"] == 2 and two["printings"] == 9
    assert two["basic_land_printings"] == 0
    assert two["by_printings"] == [
        {
            "artist": "Invented Artist",
            "printings": 8,
            "basic_lands": 0,
            "different_cards": 8,
            "rank_without_basic_lands": 1,
            "rank_2024": 1,
        },
        {
            "artist": "Second Artist",
            "printings": 1,
            "basic_lands": 0,
            "different_cards": 1,
            "rank_without_basic_lands": 2,
            "rank_2024": None,
        },
    ]
    assert two["the_2024_way"] == [
        {"artist": "Invented Artist", "cards": 8, "rank_by_printings": 1}
    ]


def test_an_artist_with_no_rank_is_written_in_words_not_none():
    from topdeck.pages import artist_headline, rank

    assert rank(None) == "not ranked"
    two = {
        "by_printings": [
            {
                "artist": "A",
                "printings": 10,
                "basic_lands": 6,
                "rank_without_basic_lands": 2,
                "rank_2024": None,
            }
        ],
        "without_basic_lands": {"by_printings": [{"artist": "B", "printings": 5}]},
    }
    headline = artist_headline(two)
    assert "None" not in headline
    assert headline == (
        "A has the most printings, 10, and 6 of them are basic lands. Leave basic lands out "
        "and B leads with 5, while A ranks 2. Counted the 2024 way, one printing per card, "
        "A has no card at all."
    )


@pytest.mark.db
def test_the_answers_command_records_then_matches(invented_graph, database_url, tmp_path, capsys):
    _, schema, _ = invented_graph
    record, page = tmp_path / "answers.json", tmp_path / "page.md"
    assert answer_2024(record, page, True, database_url, schema) == 0
    assert page.read_text().startswith("# 🧝 The 2024 questions, answered")
    assert answer_2024(record, page, False, database_url, schema) == 0
    assert capsys.readouterr().out.strip().endswith(f"Every answer matches {record}.")

    record.write_text(record.read_text().replace('"creatures": 7', '"creatures": 8'))
    assert answer_2024(record, page, False, database_url, schema) == 1
    assert "creatures: found 7, recorded 8" in capsys.readouterr().out

    record.write_text("[1, 2")
    assert answer_2024(record, page, False, database_url, schema) == 1
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith(f"The record at {record} is not valid JSON")
