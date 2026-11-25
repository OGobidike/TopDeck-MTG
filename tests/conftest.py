"""Rules every test runs under: no key, no internet and no money."""

import gzip
import json
import os
import socket
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from topdeck import graph
from topdeck.census import load_cards
from topdeck.snapshot import BulkFile, fingerprint

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection from Python.

    This closes the door every later phase could spend money through: urllib, an HTTP
    client, a model's SDK. The database tests are not stopped by it, because the
    PostgreSQL driver connects through its own C library and never touches Python's
    socket. They are kept local by the `database_url` fixture below, which refuses any
    host that isn't this machine.
    """

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


@pytest.fixture
def source_files(card_files) -> tuple[BulkFile, BulkFile, BulkFile]:
    """The invented rulings, Oracle Tags and Art Tags, packed and pinned beside the cards."""
    folder = card_files[0]
    return tuple(
        pack(FIXTURES / f"{name}.jsonl", folder / f"{name}.jsonl.gz")
        for name in ("rulings", "oracle_tags", "art_tags")
    )


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# Set in CI, and by anyone who wants a missing database to fail the run, not skip.
REQUIRE_DATABASE = "TOPDECK_REQUIRE_DB"


def database_required() -> bool:
    return bool(os.environ.get("CI") or os.environ.get(REQUIRE_DATABASE))


def without_database(reason: str):
    """Skip a database test, or fail it when a database is required.

    A skipped test still leaves pytest's exit code at 0, so in CI a skip could hide a
    broken database. There, and wherever TOPDECK_REQUIRE_DB is set, it fails instead.
    """
    if database_required():
        pytest.fail(f"{reason} A database is required here, so this is a failure.", False)
    pytest.skip(f"{reason} The database tests did not run.")


@pytest.fixture(scope="session")
def database_url() -> str:
    """The address of a local PostgreSQL to test against: TOPDECK_DATABASE_URL, or the
    same default the commands use, the database docker-compose.yml starts."""
    url = graph.database_url()
    host = psycopg.conninfo.conninfo_to_dict(url).get("host", "localhost")
    if host not in LOCAL_HOSTS and not host.startswith("/"):
        without_database(f"The database tests only run against this machine, not {host}.")
    try:
        graph.connect(url).close()
    except graph.DatabaseUnreachable as error:
        without_database(str(error))
    return url


@pytest.fixture
def schema(database_url) -> str:
    """A schema of this test's own, dropped when the test ends."""
    name = f"test_{uuid.uuid4().hex[:16]}"
    yield name
    with psycopg.connect(database_url, autocommit=True) as connection:
        for doomed in (name, name + "_build"):
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(doomed))
            )


@pytest.fixture
def invented_graph(database_url, schema, card_files, source_files):
    """The invented cards, their rulings and tags, loaded as a graph. Yields an open
    connection, the schema and the row counts."""
    folder, oracle, printings_file = card_files
    cards, _ = load_cards(folder, oracle, printings_file)
    printings = graph.read_printings(folder, cards, printings_file)
    sources = graph.read_sources(folder, cards, printings, source_files)
    with psycopg.connect(database_url) as connection:
        counts = graph.build(connection, cards, printings, schema, sources)
        connection.commit()
        yield connection, schema, counts
