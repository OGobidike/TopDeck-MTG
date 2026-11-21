import shutil

from topdeck.cli import main
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
