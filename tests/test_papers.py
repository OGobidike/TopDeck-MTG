"""The README and the blueprint make claims. These tests fail when a claim drifts."""

import re

PHASE_ROW = re.compile(r"^\| (\d\. [^|]+?) \|", flags=re.MULTILINE)
# What an unfinished write-up leaves behind: $TOTAL_REVENUE, COUNTRY_1, TODO, TBD.
PLACEHOLDER = re.compile(r"\$[A-Z_]{4,}|\b[A-Z]{4,}_\d\b|\bTODO\b|\bTBD\b|⟦")


def test_the_test_count_in_the_readme_is_current(root):
    written = sum(
        len(re.findall(r"^def test_", path.read_text(), flags=re.MULTILINE))
        for path in (root / "tests").glob("test_*.py")
    )
    quoted = re.findall(r"\*\*(\d+) tests\*\*", (root / "README.md").read_text())
    assert quoted == [str(written)], f"README says {quoted}, tests/ holds {written}"


def test_the_readme_and_the_blueprint_name_the_same_phases(root):
    readme = PHASE_ROW.findall((root / "README.md").read_text())
    blueprint = PHASE_ROW.findall((root / "docs/BLUEPRINT.md").read_text())
    assert len(blueprint) == 9
    assert readme == blueprint


def test_every_task_from_t0_to_t10_is_in_the_blueprint_once(root):
    table = "\n".join(
        line
        for line in (root / "docs/BLUEPRINT.md").read_text().splitlines()
        if PHASE_ROW.match(line)
    )
    assert sorted(re.findall(r"\bT(\d+)\b", table), key=int) == [str(n) for n in range(11)]


def test_the_question_counts_in_the_blueprint_add_up(root):
    blueprint = (root / "docs/BLUEPRINT.md").read_text()
    sources = [int(n) for n in re.findall(r"^- \*\*(\d+) ", blueprint, flags=re.MULTILINE)]
    assert sources == [288, 40, 100, 80, 20]
    assert sum(sources) == 528  # "about 530"
    assert "about 530 questions" in blueprint


def test_no_placeholder_is_left_in_any_paper(root):
    for name in ("README.md", "docs/BLUEPRINT.md", "questions/hand_written.md"):
        found = PLACEHOLDER.findall((root / name).read_text())
        assert not found, f"{name} still holds {found}"


def test_every_link_inside_the_repo_leads_somewhere(root):
    readme = (root / "README.md").read_text()
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", readme):
        if not target.startswith("http"):
            assert (root / target).exists(), f"README links to {target}, which isn't there"


def test_the_blueprint_heading_the_readme_points_at_exists(root):
    assert "\n## The questions\n" in (root / "docs/BLUEPRINT.md").read_text()
