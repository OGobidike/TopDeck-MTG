import shutil

from topdeck.cli import count_cards, fetch_cards, main
from topdeck.ground import HAND_WRITTEN, ORIGINALS


def copy_of_the_ground(root, tmp_path):
    for path in (*ORIGINALS, HAND_WRITTEN):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / path, target)
    return tmp_path


def test_ground_passes_on_the_repo_as_it_stands(root, capsys):
    assert main(["ground", "--root", str(root)]) == 0
    printed = capsys.readouterr().out
    assert "The 2024 files: 2 of 2 untouched" in printed
    assert "of 100" in printed
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
    with (copy / HAND_WRITTEN).open("a") as file:
        file.write("\n1. List the red Goblins\n")
    assert main(["ground", "--root", str(copy)]) == 1
    assert "question mark" in capsys.readouterr().out


def test_ground_explains_a_missing_questions_page(root, tmp_path, capsys):
    copy = copy_of_the_ground(root, tmp_path)
    (copy / HAND_WRITTEN).unlink()
    assert main(["ground", "--root", str(copy)]) == 1
    assert "Could not read the hand-written questions" in capsys.readouterr().out


def test_fetch_says_what_it_costs_and_waits_for_a_yes(tmp_path, capsys):
    assert main(["cards", "fetch", "--data", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "106.8 MB" in printed
    assert "Nothing was downloaded." in printed
    assert list(tmp_path.iterdir()) == []


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


def test_count_asks_for_the_files_when_they_are_missing(tmp_path, capsys):
    assert main(["cards", "count", "--data", str(tmp_path)]) == 1
    assert "topdeck cards fetch --yes" in capsys.readouterr().out
