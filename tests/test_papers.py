"""The README and the blueprint make claims. These tests fail when a claim drifts."""

import json
import re

from topdeck.graph import LINK_TABLES
from topdeck.pages import ANSWERS_PAGE, artist_headline, render_answers

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
    assert sources == [288, 40, 108, 80, 20]
    assert sum(sources) == 536  # "about 540"
    assert "about 540 questions" in blueprint


def test_no_placeholder_is_left_in_any_paper(root):
    for name in (
        "README.md",
        "docs/BLUEPRINT.md",
        "docs/2024-QUESTIONS.md",
        "questions/chosen.md",
    ):
        found = PLACEHOLDER.findall((root / name).read_text())
        assert not found, f"{name} still holds {found}"


def test_every_link_inside_the_repo_leads_somewhere(root):
    readme = (root / "README.md").read_text()
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", readme):
        if not target.startswith("http"):
            assert (root / target).exists(), f"README links to {target}, which isn't there"


def test_the_blueprint_heading_the_readme_points_at_exists(root):
    assert "\n## The questions\n" in (root / "docs/BLUEPRINT.md").read_text()


def test_the_card_numbers_in_the_readme_are_the_recorded_ones(root):
    readme = (root / "README.md").read_text()
    record = json.loads((root / "results/cards.json").read_text())
    for key in ("entries", "cards", "printings"):
        assert f"{record[key]:,}" in readme, f"README is missing {key} = {record[key]:,}"
    for reason, number in record["left_out"].items():
        row = f"| {number:,} | {reason[0].upper()}{reason[1:]} |"
        assert row in readme, f"README is missing the row {row}"
    assert record["snapshot"] in readme


def test_the_recorded_count_adds_up(root):
    record = json.loads((root / "results/cards.json").read_text())
    assert record["cards"] + sum(record["left_out"].values()) == record["entries"]
    assert len(record["card_ids_sha256"]) == 64


def test_the_graph_numbers_in_the_readme_are_the_recorded_ones(root):
    readme = (root / "README.md").read_text()
    tables = json.loads((root / "results/graph.json").read_text())["tables"]
    for table, rows in tables.items():
        assert f"| `{table}` | {rows:,} |" in readme, f"README is missing {table} = {rows:,}"
    assert set(LINK_TABLES) <= set(tables)
    links = sum(tables[table] for table in LINK_TABLES)
    assert f"**{links:,} links**" in readme


def test_the_graph_and_the_card_count_agree(root):
    tables = json.loads((root / "results/graph.json").read_text())["tables"]
    cards = json.loads((root / "results/cards.json").read_text())
    assert tables["cards"] == cards["cards"]
    assert tables["printings"] <= cards["printings"]
    assert tables["printing_artist"] <= tables["printings"]


def test_the_answers_page_is_exactly_what_the_record_writes(root):
    recorded = json.loads((root / "results/answers_2024.json").read_text())
    assert (root / ANSWERS_PAGE).read_text() == render_answers(recorded)


def test_the_headline_answers_in_the_readme_are_the_recorded_ones(root):
    readme = (root / "README.md").read_text()
    recorded = json.loads((root / "results/answers_2024.json").read_text())
    elf = recorded["elves_and_goblins"]["elves_green"]
    goblin = recorded["elves_and_goblins"]["goblins_red"]
    for claim in (
        f"{elf['with_colour']:,} of {elf['cards']:,} Elf creatures are green, "
        f"**{elf['lift']:.2f} times**",
        f"{goblin['with_colour']:,} of {goblin['cards']:,} are red, **{goblin['lift']:.2f} times**",
        artist_headline(recorded["artists"]),
    ):
        assert claim in readme, f"README is missing: {claim}"


def test_the_recorded_answers_add_up(root):
    recorded = json.loads((root / "results/answers_2024.json").read_text())
    tables = json.loads((root / "results/graph.json").read_text())["tables"]
    assert recorded["artists"]["printings"] == tables["printing_artist"]
    assert recorded["artists"]["artists"] == tables["artists"]
    assert recorded["subtypes_in_colours"]["cards"] == tables["cards"]
    three = recorded["subtypes_in_colours"]
    for row in recorded["elves_and_goblins"]["commonest_subtypes"] + three["strongest"]:
        assert row["share_low"] <= row["share"] <= row["share_high"]
        assert row["lift_low"] <= row["lift"] <= row["lift_high"]
        assert row["with_colour"] <= row["cards"]
    for row in three["most_even"]:
        assert abs(sum(row["share"].values()) - 1) < 1e-5, row["subtype"]
        assert row["one_coloured_cards"] >= 30
    leader = recorded["artists"]["by_printings"][0]
    assert leader["basic_lands"] <= leader["printings"]
