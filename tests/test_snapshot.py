import io

import pytest

from topdeck.snapshot import DEFAULT_CARDS, ORACLE_CARDS, fetch, fingerprint, read_entries, verify


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
    for file in (ORACLE_CARDS, DEFAULT_CARDS):
        assert len(file.sha256) == 64
        assert file.url.endswith(file.filename)
        assert file.url.startswith("https://data.scryfall.io/")
