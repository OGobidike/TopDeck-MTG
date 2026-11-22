"""Cards as TopDeck reads them: Scryfall's raw entries turned into one plain shape.

Three things in Scryfall's data are awkward, and each gets a rule here:

- A card's types arrive as one line of text ("Legendary Creature — Elf Druid") that has
  to be split into supertypes, types and subtypes.
- A card with more than one face keeps some facts on the card and some on each face.
- Power is text, not a number: some cards have a power of "*".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The five supertypes the game's rules name (rule 205.4a).
SUPERTYPES = frozenset({"Basic", "Legendary", "Ongoing", "Snow", "World"})

# Subtypes that are two words long. Every other subtype is one word.
TWO_WORD_SUBTYPES = ("Time Lord",)

# A type line puts this dash between a card's types and its subtypes.
_DASH = " — "
# A card with two parts joins their names, and their type lines, with this.
_FACE_BREAK = " // "
# Layouts whose two parts are both on the card's one printed side, and both count
# towards the card's types. A split card is an Instant and a Sorcery at once.
_BOTH_HALVES = frozenset({"split"})

_WHOLE_NUMBER = re.compile(r"-?\d+")


@dataclass(frozen=True)
class TypeLine:
    supertypes: tuple[str, ...]
    types: tuple[str, ...]
    subtypes: tuple[str, ...]


def parse_type_line(line: str) -> TypeLine:
    """Split one face's type line into supertypes, types and subtypes.

    >>> parse_type_line("Legendary Creature — Time Lord Doctor")
    TypeLine(supertypes=('Legendary',), types=('Creature',), subtypes=('Time Lord', 'Doctor'))
    """
    if _FACE_BREAK in line:
        raise ValueError(f"{line!r} holds more than one face; split it with face_type_lines")
    left, _, right = line.partition(_DASH)
    words = left.split()
    supertypes = tuple(word for word in words if word in SUPERTYPES)
    types = tuple(word for word in words if word not in SUPERTYPES)

    for subtype in TWO_WORD_SUBTYPES:
        right = right.replace(subtype, subtype.replace(" ", "\x00"))
    subtypes = tuple(word.replace("\x00", " ") for word in right.split())
    return TypeLine(supertypes, types, subtypes)


def face_type_lines(line: str) -> list[str]:
    """The type line of each face, front face first."""
    return line.split(_FACE_BREAK)


def power_number(power: str | None) -> int | None:
    """A card's power as a whole number, or None when it isn't one.

    Powers such as "*", "1+*" and "2.5" can't be ranked, so a question about the
    highest power leaves those cards out. That is this project's rule, and it is
    stated wherever such a question is asked.
    """
    if power is None or not _WHOLE_NUMBER.fullmatch(power):
        return None
    return int(power)


@dataclass(frozen=True)
class Face:
    name: str
    mana_cost: str
    type_line: TypeLine
    colours: frozenset[str] | None  # None when Scryfall keeps the colours on the card
    rules_text: str
    power: str | None
    toughness: str | None


@dataclass(frozen=True)
class Card:
    """One unique card. Its own colours, types and power are those of its front face,
    except on a split card, whose two halves both count. Every face keeps its own."""

    oracle_id: str
    name: str
    layout: str
    mana_cost: str
    mana_value: float
    colours: frozenset[str]
    colour_identity: frozenset[str]
    type_line: TypeLine
    keywords: tuple[str, ...]
    rules_text: str
    power: str | None
    toughness: str | None
    legalities: dict[str, str]
    faces: tuple[Face, ...]

    @property
    def power_number(self) -> int | None:
        return power_number(self.power)

    def is_a(self, card_type: str) -> bool:
        return card_type in self.type_line.types

    def has_subtype(self, subtype: str) -> bool:
        return subtype in self.type_line.subtypes


def _merge(lines: list[TypeLine]) -> TypeLine:
    def joined(parts: list[tuple[str, ...]]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(word for part in parts for word in part))

    return TypeLine(
        joined([line.supertypes for line in lines]),
        joined([line.types for line in lines]),
        joined([line.subtypes for line in lines]),
    )


def card_from_scryfall(raw: dict) -> Card:
    """Turn one entry of Scryfall's Oracle Cards file into a Card."""
    lines = [parse_type_line(line) for line in face_type_lines(raw["type_line"])]
    raw_faces = raw.get("card_faces") or []

    faces = tuple(
        Face(
            name=face["name"],
            mana_cost=face.get("mana_cost", ""),
            type_line=parse_type_line(face["type_line"]) if "type_line" in face else lines[0],
            colours=frozenset(face["colors"]) if face.get("colors") is not None else None,
            rules_text=face.get("oracle_text", ""),
            power=face.get("power"),
            toughness=face.get("toughness"),
        )
        for face in raw_faces
    )
    front = faces[0] if faces else None

    if raw.get("colors") is not None:
        colours = frozenset(raw["colors"])
    elif front is not None and front.colours is not None:
        colours = front.colours
    else:
        colours = frozenset()

    if "oracle_text" in raw:
        rules_text = raw["oracle_text"]
    else:
        rules_text = "\n//\n".join(face.rules_text for face in faces)

    return Card(
        oracle_id=raw.get("oracle_id") or raw_faces[0]["oracle_id"],
        name=raw["name"],
        layout=raw["layout"],
        mana_cost=raw["mana_cost"] if "mana_cost" in raw else (front.mana_cost if front else ""),
        mana_value=float(raw.get("cmc", 0)),
        colours=colours,
        colour_identity=frozenset(raw.get("color_identity", [])),
        type_line=_merge(lines) if raw["layout"] in _BOTH_HALVES else lines[0],
        keywords=tuple(raw.get("keywords", [])),
        rules_text=rules_text,
        power=raw["power"] if "power" in raw else (front.power if front else None),
        toughness=raw["toughness"] if "toughness" in raw else (front.toughness if front else None),
        legalities=dict(raw.get("legalities", {})),
        faces=faces,
    )
