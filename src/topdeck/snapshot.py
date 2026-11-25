"""Scryfall's files: where they come from, how big they are, and their fingerprints.

Scryfall rebuilds its bulk files every 12 to 24 hours, so a count is only repeatable
against one pinned download. This module names each download and refuses any other.

Two snapshots are pinned. The card files are of 2026-11-21. The rulings and the two
community tag files were added a day later, so they are of 2026-11-22.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from topdeck import __version__

SNAPSHOT_DATE = "2026-11-21"
SOURCES_SNAPSHOT_DATE = "2026-11-22"
DATA_DIR = Path("data")
# Scryfall asks every program to name itself.
USER_AGENT = f"TopDeck-MTG/{__version__} (+https://github.com/OGobidike/TopDeck-MTG)"


@dataclass(frozen=True)
class BulkFile:
    """One of Scryfall's bulk files, as it stood on the snapshot date."""

    name: str
    filename: str
    url: str
    packed_bytes: int
    sha256: str
    snapshot: str = SNAPSHOT_DATE


ORACLE_CARDS = BulkFile(
    name="Oracle Cards",
    filename="oracle-cards-20261121100156.jsonl.gz",
    url="https://data.scryfall.io/oracle-cards/oracle-cards-20261121100156.jsonl.gz",
    packed_bytes=25_540_443,
    sha256="58696789d751b2e8090c280262179c4e79ec8aebafb81273998e5e0016c96407",
)
DEFAULT_CARDS = BulkFile(
    name="Default Cards",
    filename="default-cards-20261121100620.jsonl.gz",
    url="https://data.scryfall.io/default-cards/default-cards-20261121100620.jsonl.gz",
    packed_bytes=81_290_055,
    sha256="74d13e3d451914e3ce0e2765b1ee418918b65c36e78fd57bcc7239e1bc2eeb8c",
)
FILES = (ORACLE_CARDS, DEFAULT_CARDS)

# The official rulings: written by Wizards of the Coast, except a few that Scryfall's
# own staff wrote and marks as theirs.
RULINGS = BulkFile(
    name="Rulings",
    filename="rulings-20261122100032.jsonl.gz",
    url="https://data.scryfall.io/rulings/rulings-20261122100032.jsonl.gz",
    packed_bytes=5_508_481,
    sha256="a79e07a6aeee59b115e8ca3fc9f470f94fa08ccb3eca7749e3e8777100d092d1",
    snapshot=SOURCES_SNAPSHOT_DATE,
)
# Community labels from Tagger, Scryfall's tagging project: what a card does, and what
# its picture shows. Wizards does not check them, and I have not found how Scryfall
# reviews them. They are kept apart from the official facts, and no tag, checked or not,
# is ever an answer key.
ORACLE_TAGS = BulkFile(
    name="Oracle Tags",
    filename="oracle-tags-20261122100042.jsonl.gz",
    url="https://data.scryfall.io/oracle-tags/oracle-tags-20261122100042.jsonl.gz",
    packed_bytes=6_129_472,
    sha256="7eb9f7048a6b1703626bac4b8d4b5c0a7a0f2261d617066d305d23a9089a2208",
    snapshot=SOURCES_SNAPSHOT_DATE,
)
ART_TAGS = BulkFile(
    name="Art Tags",
    filename="art-tags-20261122100127.jsonl.gz",
    url="https://data.scryfall.io/art-tags/art-tags-20261122100127.jsonl.gz",
    packed_bytes=13_470_173,
    sha256="a65870959dc9368b99ff61540aa0e98965e4058681267b7072fb95ba1a1e2965",
    snapshot=SOURCES_SNAPSHOT_DATE,
)
SOURCE_FILES = (RULINGS, ORACLE_TAGS, ART_TAGS)
ALL_FILES = FILES + SOURCE_FILES


def fingerprint(path: Path) -> str:
    """The SHA-256 of a file, read in pieces so a large file never fills memory."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for piece in iter(lambda: file.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def verify(path: Path, expected: BulkFile) -> None:
    """Raise ValueError unless the file is byte for byte the pinned download."""
    found = fingerprint(path)
    if found != expected.sha256:
        raise ValueError(
            f"{path.name} is not the pinned {expected.name} file of {expected.snapshot}: "
            f"its SHA-256 is {found}, and the pin is {expected.sha256}"
        )


def read_entries(path: Path) -> Iterator[dict]:
    """Read a gzipped JSON Lines file one entry at a time, never unpacking it to disk."""
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            if line.strip():
                yield json.loads(line)


def fetch(
    expected: BulkFile,
    folder: Path = DATA_DIR,
    open_url: Callable = urllib.request.urlopen,
) -> Path:
    """Download one pinned file into the folder, unless a verified copy is already there."""
    target = folder / expected.filename
    if target.is_file():
        verify(target, expected)
        return target

    folder.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        expected.url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    part = target.with_name(target.name + ".part")
    with open_url(request) as response, part.open("wb") as file:
        shutil.copyfileobj(response, file)
    try:
        verify(part, expected)
    except ValueError:
        part.unlink()
        raise
    part.rename(target)
    return target
