import pytest

from topdeck.cards import (
    TypeLine,
    card_from_scryfall,
    face_type_lines,
    parse_type_line,
    power_number,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Instant", TypeLine((), ("Instant",), ())),
        ("Creature — Elf Druid", TypeLine((), ("Creature",), ("Elf", "Druid"))),
        (
            "Legendary Snow Creature — Elf Wizard",
            TypeLine(("Legendary", "Snow"), ("Creature",), ("Elf", "Wizard")),
        ),
        ("Artifact Creature — Golem", TypeLine((), ("Artifact", "Creature"), ("Golem",))),
        ("Basic Land — Forest", TypeLine(("Basic",), ("Land",), ("Forest",))),
        (
            "Legendary Creature — Time Lord Doctor",
            TypeLine(("Legendary",), ("Creature",), ("Time Lord", "Doctor")),
        ),
    ],
)
def test_a_type_line_splits_into_its_three_parts(line, expected):
    assert parse_type_line(line) == expected


def test_a_two_faced_type_line_must_be_split_first():
    line = "Creature — Human Scout // Creature — Horror"
    with pytest.raises(ValueError, match="more than one face"):
        parse_type_line(line)
    assert face_type_lines(line) == ["Creature — Human Scout", "Creature — Horror"]


@pytest.mark.parametrize(
    ("power", "number"),
    [("3", 3), ("0", 0), ("-1", -1), ("*", None), ("1+*", None), ("2.5", None), (None, None)],
)
def test_power_is_a_number_only_when_it_is_a_whole_one(power, number):
    assert power_number(power) == number


def test_a_plain_card(invented):
    card = card_from_scryfall(invented["Cinderpot Raider"])
    assert card.colours == {"R"}
    assert card.is_a("Creature") and card.has_subtype("Goblin")
    assert card.keywords == ("Haste",)
    assert card.power_number == 2
    assert card.faces == ()


def test_a_power_that_is_not_a_number_is_kept_as_text(invented):
    card = card_from_scryfall(invented["Lady of the Frozen Vault"])
    assert card.power == "*"
    assert card.power_number is None
    assert card.type_line.supertypes == ("Legendary", "Snow")


def test_a_split_card_is_both_of_its_halves(invented):
    card = card_from_scryfall(invented["Kindle // Quench"])
    assert card.type_line.types == ("Instant", "Sorcery")
    assert card.colours == {"R", "U"}
    assert [face.name for face in card.faces] == ["Kindle", "Quench"]
    assert "Draw two cards." in card.rules_text


def test_a_two_sided_card_is_its_front_face(invented):
    """Scryfall keeps a two-sided card's colours and power on its faces, not on the card."""
    card = card_from_scryfall(invented["Village Lamplighter // Lamplit Horror"])
    assert card.colours == {"W"}
    assert card.type_line.subtypes == ("Human", "Scout")
    assert card.power == "1"
    back = card.faces[1]
    assert back.colours == {"B"} and back.power == "4"
    assert back.type_line.subtypes == ("Horror",)
    assert "Menace" in card.rules_text


def test_an_adventure_card_is_its_creature(invented):
    card = card_from_scryfall(invented["Hedge Tinker // Tinker's Errand"])
    assert card.type_line.types == ("Creature",)
    assert not card.is_a("Sorcery")
    assert card.faces[1].type_line == TypeLine((), ("Sorcery",), ("Adventure",))
    assert card.faces[1].colours is None
