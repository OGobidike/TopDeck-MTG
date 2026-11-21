import socket
import tomllib

import pytest

from topdeck.ground import ORIGINAL_DIR, ORIGINALS, changed_originals, fingerprint


def test_the_2024_files_are_byte_for_byte_what_they_were(root):
    """The rebuild audits where I began, so where I began must not move."""
    for path, expected in ORIGINALS.items():
        assert fingerprint(root / path) == expected, path
    assert changed_originals(root) == []


def test_every_file_in_the_2024_folder_is_pinned(root):
    on_disk = {p.relative_to(root) for p in (root / ORIGINAL_DIR).rglob("*") if p.is_file()}
    assert on_disk == set(ORIGINALS)


def test_one_changed_byte_is_noticed(root, tmp_path):
    for path in ORIGINALS:
        copy = tmp_path / path
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes((root / path).read_bytes())
    code = tmp_path / next(iter(ORIGINALS))
    code.write_bytes(code.read_bytes() + b"\n")
    assert changed_originals(tmp_path) == [next(iter(ORIGINALS))]


def test_a_missing_2024_file_is_noticed(tmp_path):
    assert changed_originals(tmp_path) == list(ORIGINALS)


def test_no_formatter_or_linter_may_touch_the_2024_files(root):
    settings = tomllib.loads((root / "pyproject.toml").read_text())
    assert "notebooks" in settings["tool"]["ruff"]["extend-exclude"]


def test_git_may_not_rewrite_their_line_endings(root):
    rules = (root / ".gitattributes").read_text()
    assert "notebooks/2024-original/** -text" in rules


def test_a_test_that_reaches_for_the_network_fails():
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("192.0.2.1", 80), timeout=1)


def test_the_card_files_and_the_key_can_never_be_committed(root):
    ignored = (root / ".gitignore").read_text().split()
    assert ".env" in ignored
    assert "data/" in ignored
