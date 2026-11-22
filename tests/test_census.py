import pytest

from topdeck.cards import card_from_scryfall
from topdeck.census import (
    NEVER_ON_PAPER,
    NO_FORMAT,
    ids_fingerprint,
    ids_with_a_real_printing,
    is_a_real_printing,
    load_cards,
    oracle_id_of,
    why_left_out,
)


def printing(**changes) -> dict:
    return {"games": ["paper"], "digital": False, "layout": "normal", "set_type": "core"} | changes


@pytest.mark.parametrize(
    ("changes", "real"),
    [
        ({}, True),
        ({"games": ["mtgo"]}, False),
        ({"digital": True}, False),
        ({"layout": "token"}, False),
        ({"layout": "art_series"}, False),
        ({"set_type": "funny"}, False),
        ({"set_type": "alchemy"}, False),
        ({"set_type": "masters"}, True),
    ],
)
def test_what_makes_a_printing_real(changes, real):
    assert is_a_real_printing(printing(**changes)) is real


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("Mossback Elder", None),
        ("Goblin", "a token"),
        ("Mossback Elder // Mossback Elder", "an art card"),
        ("Clown of Many Hats", "printed only in joke sets"),
        ("Rebalanced Spark", "found only in digital Alchemy sets"),
        ("Prototype of Things to Come", NO_FORMAT),
        ("Screen-Only Sprite", NEVER_ON_PAPER),
    ],
)
def test_every_reason_a_card_is_left_out(invented, invented_printings, name, reason):
    real, _ = ids_with_a_real_printing(invented_printings)
    entry = invented[name]
    assert why_left_out(entry, oracle_id_of(entry) in real) == reason


def test_a_card_counts_if_any_printing_is_real(invented, invented_printings):
    """The Oracle file shows one printing per card, and it may be a digital one. My first
    rule judged a card by that printing alone and dropped 1,226 real cards."""
    entry = invented["Old Road Sentinel"]
    assert entry["digital"] and entry["games"] == ["mtgo"]
    real, _ = ids_with_a_real_printing(invented_printings)
    assert why_left_out(entry, oracle_id_of(entry) in real) is None


def test_the_census_of_the_invented_cards(card_files):
    folder, oracle, printings = card_files
    cards, census = load_cards(folder, oracle, printings)
    assert census["entries"] == 14
    assert census["printings"] == 16
    assert census["cards"] == 8
    assert census["cards"] + sum(census["left_out"].values()) == census["entries"]
    assert census["by_type"]["Creature"] == 7
    assert "Old Road Sentinel" in {card.name for card in cards}
    assert [card.oracle_id for card in cards] == sorted(card.oracle_id for card in cards)


def test_the_fingerprint_of_the_ids_changes_when_one_card_leaves(invented):
    cards = [card_from_scryfall(invented[name]) for name in ("Mossback Elder", "Kindle // Quench")]
    assert ids_fingerprint(cards) == ids_fingerprint(reversed(cards))
    assert ids_fingerprint(cards) != ids_fingerprint(cards[:1])
