import io
from dataclasses import replace

import pytest

from topdeck.snapshot import (
    ALL_FILES,
    DEFAULT_CARDS,
    ORACLE_CARDS,
    SOURCE_FILES,
    fetch,
    fingerprint,
    read_entries,
    verify,
)


def test_the_packed_file_is_read_one_entry_at_a_time(card_files):
    folder, oracle, _ = card_files
    entries = read_entries(folder / oracle.filename)
    assert next(entries)["name"] == "Mossback Elder"
    assert sum(1 for _ in entries) == 13


def test_a_file_with_the_wrong_fingerprint_is_refused(card_files):
    folder, oracle, printings = card_files
    verify(folder / oracle.filename, oracle)
    with pytest.raises(ValueError, match="is not the pinned"):
        verify(folder / printings.filename, oracle)


def test_fetch_downloads_names_itself_and_verifies(card_files, tmp_path):
    folder, oracle, _ = card_files
    asked = []

    def fake_open(request):
        asked.append(request)
        return io.BytesIO((folder / oracle.filename).read_bytes())

    target = fetch(oracle, tmp_path / "data", open_url=fake_open)
    assert fingerprint(target) == oracle.sha256
    assert asked[0].full_url == oracle.url
    assert asked[0].get_header("User-agent").startswith("TopDeck-MTG/")
    assert not list((tmp_path / "data").glob("*.part"))


def test_fetch_keeps_nothing_when_the_download_is_not_the_pinned_file(card_files, tmp_path):
    _, oracle, _ = card_files
    with pytest.raises(ValueError, match="is not the pinned"):
        fetch(oracle, tmp_path / "data", open_url=lambda request: io.BytesIO(b"something else"))
    assert list((tmp_path / "data").iterdir()) == []


def test_fetch_does_not_download_a_file_it_already_holds(card_files):
    folder, oracle, _ = card_files

    def never(request):
        raise AssertionError("fetch downloaded a file it already had")

    assert fetch(oracle, folder, open_url=never) == folder / oracle.filename


def test_the_real_pins_are_whole():
    for file in ALL_FILES:
        assert len(file.sha256) == 64
        assert file.url.endswith(file.filename)
        assert file.url.startswith("https://data.scryfall.io/")
        assert file.packed_bytes > 0


def test_the_card_pins_are_unchanged_and_the_new_files_are_a_day_later():
    assert (ORACLE_CARDS.snapshot, ORACLE_CARDS.sha256) == (
        "2026-11-21",
        "58696789d751b2e8090c280262179c4e79ec8aebafb81273998e5e0016c96407",
    )
    assert (DEFAULT_CARDS.snapshot, DEFAULT_CARDS.sha256) == (
        "2026-11-21",
        "74d13e3d451914e3ce0e2765b1ee418918b65c36e78fd57bcc7239e1bc2eeb8c",
    )
    assert [file.name for file in SOURCE_FILES] == ["Rulings", "Oracle Tags", "Art Tags"]
    for file in SOURCE_FILES:
        assert file.snapshot == "2026-11-22"
        assert "-20261122" in file.filename


def test_a_refused_file_names_the_snapshot_it_was_pinned_to(card_files, source_files):
    folder, oracle, _ = card_files
    rulings = source_files[0]
    wrong = replace(rulings, name="Rulings", snapshot="2026-11-22")
    with pytest.raises(ValueError, match="not the pinned Rulings file of 2026-11-22"):
        verify(folder / oracle.filename, wrong)
