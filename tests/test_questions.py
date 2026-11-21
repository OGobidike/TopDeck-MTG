from topdeck.ground import (
    HAND_WRITTEN,
    HAND_WRITTEN_TARGET,
    Question,
    check_questions,
    read_questions,
)


def numbered(*texts: str) -> list[Question]:
    return [Question(n, text) for n, text in enumerate(texts, start=1)]


def test_only_numbered_lines_are_questions(tmp_path):
    page = tmp_path / "page.md"
    page.write_text(
        "# A heading\n\nSome rules.\n\n1. Which Goblins cost one mana?\n"
        "- not a question\n2.   What does this card do?  \n"
    )
    assert read_questions(page) == [
        Question(1, "Which Goblins cost one mana?"),
        Question(2, "What does this card do?"),
    ]


def test_good_questions_raise_no_problem():
    assert check_questions(numbered("Which Goblins cost one mana?", "Are most Elves green?")) == []


def test_a_question_without_a_question_mark_is_caught():
    problems = check_questions(numbered("List the red Goblins"))
    assert problems == ["question 1 doesn't end with a question mark"]


def test_a_repeat_is_caught_whatever_its_capitals_and_commas():
    problems = check_questions(numbered("Are most Elves green?", "are most elves, green?"))
    assert problems == ["question 2 repeats question 1"]


def test_a_gap_in_the_numbering_is_caught():
    questions = [Question(1, "Are most Elves green?"), Question(3, "Are most Goblins red?")]
    assert check_questions(questions) == ["question 2 is numbered 3"]


def test_a_fragment_is_caught():
    assert check_questions(numbered("Goblins?")) == ["question 1 is shorter than three words"]


def test_more_than_the_page_holds_is_caught():
    questions = numbered("Is card one legal?", "Is card two legal?", "Is card three legal?")
    assert check_questions(questions, target=2) == ["3 questions written, and the page holds 2"]


def test_the_page_in_the_repo_keeps_every_rule(root):
    questions = read_questions(root / HAND_WRITTEN)
    assert check_questions(questions) == []
    assert len(questions) <= HAND_WRITTEN_TARGET
