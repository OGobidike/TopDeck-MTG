"""What counts as a card, and the count.

Scryfall's Oracle Cards file holds far more than the cards a player would name: art
cards, tokens, joke cards, digital-only cards and cards from test printings are all in
it. One Goblin token would change every Goblin count, so the rule is written once,
here, and every number in the project follows it.

A card counts when all three of these hold:

1. It is a card and not something else: not an art card, a token, an emblem, a plane,
   a scheme or a vanguard.
2. At least one of its printings is on paper, in an ordinary set. The Oracle file shows
   only one printing of each card, and that one may be digital, so every printing in
   the Default Cards file is checked.
3. The Vintage format knows it: it is legal, restricted or banned there. Vintage is the
   format that allows the most cards, so this leaves out only cards that no format
   accepts, such as test cards and cards not yet released.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from topdeck.cards import Card, card_from_scryfall
from topdeck.snapshot import (
    DEFAULT_CARDS,
    ORACLE_CARDS,
    SNAPSHOT_DATE,
    BulkFile,
    read_entries,
)

# Layouts that are not cards, and what to call them.
NOT_A_CARD = {
    "art_series": "an art card",
    "token": "a token",
    "double_faced_token": "a token",
    "emblem": "an emblem",
    "planar": "a plane or phenomenon",
    "scheme": "a scheme",
    "vanguard": "a vanguard",
}
# Kinds of set that are not ordinary sets, and why a card found only there is left out.
NOT_AN_ORDINARY_SET = {
    "funny": "printed only in joke sets",
    "alchemy": "found only in digital Alchemy sets",
    "memorabilia": "printed only as a keepsake",
    "token": "printed only in token sets",
    "minigame": "printed only for a minigame",
    "vanguard": "printed only for Vanguard",
    "planechase": "printed only for Planechase",
    "archenemy": "printed only for Archenemy",
    "treasure_chest": "found only in Magic Online treasure chests",
}
NEVER_ON_PAPER = "never printed on paper"
NO_FORMAT = "accepted by no format (a test card, or not yet released)"
WIDEST_FORMAT = "vintage"


def is_a_real_printing(printing: dict) -> bool:
    """True when this printing is on paper, in an ordinary set, and is a card."""
    return (
        "paper" in printing.get("games", [])
        and not printing.get("digital", False)
        and printing["layout"] not in NOT_A_CARD
        and printing["set_type"] not in NOT_AN_ORDINARY_SET
    )


def oracle_id_of(entry: dict) -> str:
    """A card's identity. Reversible cards keep it on their faces."""
    return entry.get("oracle_id") or entry["card_faces"][0]["oracle_id"]


def why_left_out(entry: dict, has_a_real_printing: bool) -> str | None:
    """The reason an Oracle entry doesn't count as a card, or None when it counts."""
    if entry["layout"] in NOT_A_CARD:
        return NOT_A_CARD[entry["layout"]]
    if not has_a_real_printing:
        return NOT_AN_ORDINARY_SET.get(entry["set_type"], NEVER_ON_PAPER)
    if entry.get("legalities", {}).get(WIDEST_FORMAT, "not_legal") == "not_legal":
        return NO_FORMAT
    return None


def ids_with_a_real_printing(printings: Iterable[dict]) -> tuple[set[str], int]:
    """The cards that have at least one real printing, and how many printings were read."""
    real: set[str] = set()
    read = 0
    for printing in printings:
        read += 1
        if is_a_real_printing(printing):
            real.add(oracle_id_of(printing))
    return real, read


def sort_cards(entries: Iterable[dict], real: set[str]) -> tuple[list[Card], Counter[str], int]:
    """Apply the rule to every Oracle entry: the cards kept, why the rest were left out,
    and how many entries were read."""
    kept: list[Card] = []
    left_out: Counter[str] = Counter()
    read = 0
    for entry in entries:
        read += 1
        reason = why_left_out(entry, oracle_id_of(entry) in real)
        if reason is None:
            kept.append(card_from_scryfall(entry))
        else:
            left_out[reason] += 1
    kept.sort(key=lambda card: card.oracle_id)
    return kept, left_out, read


def ids_fingerprint(cards: Iterable[Card]) -> str:
    """One SHA-256 over the sorted ids of the cards kept: it changes if a single card
    joins or leaves."""
    joined = "\n".join(sorted(card.oracle_id for card in cards))
    return hashlib.sha256(joined.encode()).hexdigest()


def load_cards(
    folder: Path,
    oracle_file: BulkFile = ORACLE_CARDS,
    printings_file: BulkFile = DEFAULT_CARDS,
) -> tuple[list[Card], dict]:
    """Read the two pinned files and return the cards that count, with the census."""
    real, printings = ids_with_a_real_printing(read_entries(folder / printings_file.filename))
    kept, left_out, entries = sort_cards(read_entries(folder / oracle_file.filename), real)
    types: Counter[str] = Counter(t for card in kept for t in card.type_line.types)
    census = {
        "snapshot": SNAPSHOT_DATE,
        "entries": entries,
        "printings": printings,
        "cards": len(kept),
        "left_out": dict(sorted(left_out.items(), key=lambda item: (-item[1], item[0]))),
        "by_type": dict(sorted(types.items(), key=lambda item: (-item[1], item[0]))),
        "card_ids_sha256": ids_fingerprint(kept),
    }
    return kept, census
