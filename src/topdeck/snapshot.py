"""The card files: where they come from, how big they are, and their fingerprints.

Scryfall rebuilds its bulk files every 12 to 24 hours, so a count is only repeatable
against one pinned download. This module names that download and refuses any other.
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
            f"{path.name} is not the pinned {expected.name} file of {SNAPSHOT_DATE}: "
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
