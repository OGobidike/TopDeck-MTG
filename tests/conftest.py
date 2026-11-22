"""Rules every test runs under: no key, no network and no money."""

import gzip
import json
import socket
from pathlib import Path

import pytest

from topdeck.snapshot import BulkFile, fingerprint

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def root() -> Path:
    return ROOT


def read_fixture(name: str) -> list[dict]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@pytest.fixture
def invented() -> dict[str, dict]:
    """The invented Oracle entries, by name."""
    return {entry["name"]: entry for entry in read_fixture("oracle.jsonl")}


@pytest.fixture
def invented_printings() -> list[dict]:
    return read_fixture("printings.jsonl")


def pack(source: Path, target: Path) -> BulkFile:
    """Gzip a fixture the way Scryfall packs its files, and pin the result."""
    with target.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as packed:
        packed.write(source.read_bytes())
    return BulkFile(
        name=target.stem,
        filename=target.name,
        url=f"https://example.invalid/{target.name}",
        packed_bytes=target.stat().st_size,
        sha256=fingerprint(target),
    )


@pytest.fixture
def card_files(tmp_path) -> tuple[Path, BulkFile, BulkFile]:
    """A folder holding the invented cards, packed and pinned like the real files."""
    oracle = pack(FIXTURES / "oracle.jsonl", tmp_path / "oracle.jsonl.gz")
    printings = pack(FIXTURES / "printings.jsonl", tmp_path / "printings.jsonl.gz")
    return tmp_path, oracle, printings
