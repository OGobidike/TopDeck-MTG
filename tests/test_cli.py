import shutil
import sys

import pytest

import topdeck
from topdeck.cli import count_cards, draw_figures, fetch_cards, main
from topdeck.ground import CHOSEN, ORIGINALS
from topdeck.snapshot import ALL_FILES


def copy_of_the_ground(root, tmp_path):
    for path in (*ORIGINALS, CHOSEN):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / path, target)
    return tmp_path


def test_ground_passes_on_the_repo_as_it_stands(root, capsys):
    assert main(["ground", "--root", str(root)]) == 0
    printed = capsys.readouterr().out
    assert "The 2024 files: 2 of 2 untouched" in printed
    assert "Chosen questions: 108 of 108" in printed
    assert "The ground holds." in printed


def test_ground_fails_when_a_2024_file_changes(root, tmp_path, capsys):
    copy = copy_of_the_ground(root, tmp_path)
    with (copy / next(iter(ORIGINALS))).open("a") as file:
        file.write("# tidied\n")
    assert main(["ground", "--root", str(copy)]) == 1
    printed = capsys.readouterr().out
    assert "1 of 2 untouched" in printed
    assert "is missing or changed" in printed


def test_ground_fails_on_a_badly_formed_question(root, tmp_path, capsys):
    copy = copy_of_the_ground(root, tmp_path)
    with (copy / CHOSEN).open("a") as file:
        file.write("\n1. List the red Goblins\n")
    assert main(["ground", "--root", str(copy)]) == 1
    assert "question mark" in capsys.readouterr().out


def test_ground_explains_a_missing_questions_page(root, tmp_path, capsys):
    copy = copy_of_the_ground(root, tmp_path)
    (copy / CHOSEN).unlink()
    assert main(["ground", "--root", str(copy)]) == 1
    assert "Could not read the chosen questions" in capsys.readouterr().out


def test_fetch_says_what_it_costs_and_waits_for_a_yes(tmp_path, capsys):
    assert main(["cards", "fetch", "--data", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    for file in ALL_FILES:
        assert f"{file.packed_bytes / 1e6:.1f} MB  {file.snapshot}  {file.filename}" in printed
    assert "131.9 MB" in printed  # all five, in all
    assert printed.strip().splitlines()[-1] == (
        "Nothing was downloaded. Run it again with --yes to fetch them."
    )
    assert list(tmp_path.iterdir()) == []


def test_fetch_with_a_yes_verifies_files_it_already_holds(card_files, source_files, capsys):
    folder, oracle, printings = card_files

    def never(request):
        raise AssertionError("fetch downloaded a file it already had")

    files = (oracle, printings, *source_files)
    assert fetch_cards(folder, agreed=True, files=files, open_url=never) == 0
    printed = capsys.readouterr().out
    assert printed.count("already here, verified") == 5
    assert printed.strip().splitlines()[-1] == (
        f"Every pinned file is in {folder}/ and matches its fingerprint."
    )


def test_fetch_explains_a_file_it_cannot_get(card_files, tmp_path, capsys):
    _, oracle, _ = card_files

    def gone(request):
        raise OSError("404: Not Found")

    assert fetch_cards(tmp_path / "data", agreed=True, files=(oracle,), open_url=gone) == 1
    printed = capsys.readouterr().out
    assert "Could not fetch" in printed and "may be gone" in printed


def test_count_records_then_matches_its_own_record(card_files, tmp_path, capsys):
    folder, oracle, printings = card_files
    record = tmp_path / "results" / "cards.json"
    assert count_cards(folder, record, write=True, files=(oracle, printings)) == 0
    assert count_cards(folder, record, write=False, files=(oracle, printings)) == 0
    printed = capsys.readouterr().out
    assert "8 count as cards" in printed
    assert "Every number matches" in printed


def test_count_fails_when_the_record_says_otherwise(card_files, tmp_path, capsys):
    folder, oracle, printings = card_files
    record = tmp_path / "cards.json"
    count_cards(folder, record, write=True, files=(oracle, printings))
    record.write_text(record.read_text().replace('"cards": 8', '"cards": 9'))
    assert count_cards(folder, record, write=False, files=(oracle, printings)) == 1
    assert "cards: counted 8, recorded 9" in capsys.readouterr().out


@pytest.mark.parametrize(
    "broken, said",
    [
        ('{"broken', "is not valid JSON"),
        ("[]", "is not the shape this command writes"),
    ],
)
def test_count_ends_on_a_plain_sentence_when_its_record_is_broken(
    card_files, tmp_path, capsys, broken, said
):
    folder, oracle, printings = card_files
    record = tmp_path / "cards.json"
    record.write_text(broken)
    assert count_cards(folder, record, write=False, files=(oracle, printings)) == 1
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith(f"The record at {record} {said}")


def test_fetch_says_when_every_file_is_already_here(card_files, source_files, capsys):
    folder, oracle, printings = card_files
    assert fetch_cards(folder, agreed=False, files=(oracle, printings, *source_files)) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        "All five pinned files are already here; nothing to download. Run it again with "
        "--yes to check their fingerprints."
    )


def test_count_asks_for_the_files_when_they_are_missing(tmp_path, capsys):
    assert main(["cards", "count", "--data", str(tmp_path)]) == 1
    assert "topdeck cards fetch --yes" in capsys.readouterr().out


def test_without_matplotlib_the_figures_command_says_how_to_get_it(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.delitem(sys.modules, "topdeck.figures", raising=False)
    monkeypatch.delattr(topdeck, "figures", raising=False)
    assert draw_figures() == 1
    assert capsys.readouterr().out.strip() == (
        "Drawing needs matplotlib. Install it with: uv sync --extra figures"
    )
