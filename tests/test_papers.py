"""The README and the blueprint make claims. These tests fail when a claim drifts."""

import json
import re

from topdeck import tags
from topdeck.graph import COMMUNITY_LINK_TABLES, GIVEN_LINK_TABLES, LINK_TABLES
from topdeck.pages import ANSWERS_PAGE, artist_headline, render_answers
from topdeck.snapshot import ALL_FILES, ART_TAGS, ORACLE_TAGS, RULINGS

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


def test_every_task_from_t0_to_t11_is_in_the_blueprint_once(root):
    table = "\n".join(
        line
        for line in (root / "docs/BLUEPRINT.md").read_text().splitlines()
        if PHASE_ROW.match(line)
    )
    assert sorted(re.findall(r"\bT(\d+)\b", table), key=int) == [str(n) for n in range(12)]
    blueprint = (root / "docs/BLUEPRINT.md").read_text()
    assert "Nine phases, twelve tasks" in blueprint


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


PICTURE = re.compile(
    r'<picture>\s*<source media="\(prefers-color-scheme: dark\)" srcset="([^"]+)-dark\.png">'
    r'\s*<img alt="([^"]+)" src="([^"]+)-light\.png">\s*</picture>'
)
PAGES = ("README.md", "docs/2024-QUESTIONS.md")


def charts_on(root, page: str) -> list[str]:
    """The charts a page shows, as paths from the repo's root, each checked to come as a
    light and dark pair with words for a reader who can't see it."""
    found = []
    for dark, alt, light in PICTURE.findall((root / page).read_text()):
        assert dark == light, f"{page} pairs {dark} with {light}"
        assert len(alt) > 20, f"{page} gives {dark} too little alt text"
        found.append(str((root / page).parent.joinpath(dark).relative_to(root)))
    return found


def test_every_chart_a_page_shows_is_drawn_light_and_dark(root):
    shown = {page: charts_on(root, page) for page in PAGES}
    for page, charts in shown.items():
        assert charts, f"{page} shows no chart"
        for chart in charts:
            for mode in ("light", "dark"):
                assert (root / f"{chart}-{mode}.png").is_file(), f"{page}: {chart}-{mode}"
    drawn = {
        str(path.relative_to(root)).rsplit("-", 1)[0]
        for path in (root / "docs/images").glob("*.png")
    }
    assert drawn == {chart for charts in shown.values() for chart in charts}


def test_the_hero_is_near_the_top_and_each_question_has_its_chart(root):
    readme = (root / "README.md").read_text()
    assert readme.index("what-topdeck-knows-dark.png") < readme.index("## 🗺️ Where it stands")
    page = (root / "docs/2024-QUESTIONS.md").read_text()
    sections = re.split(r"^## \d\. ", page, flags=re.MULTILINE)[1:]
    charts = ["lift-by-subtype", "artists-basic-lands", "subtypes-by-colour"]
    for section, chart in zip(sections, charts, strict=True):
        assert f"images/{chart}-dark.png" in section


def test_the_sources_numbers_in_the_readme_are_the_recorded_ones(root):
    readme = (root / "README.md").read_text()
    record = json.loads((root / "results/graph.json").read_text())
    cards = record["tables"]["cards"]
    reach, read, skipped = record["coverage"], record["files_read"], record["skipped"]
    official = sum(record["tables"][table] for table in GIVEN_LINK_TABLES)
    community = sum(record["tables"][table] for table in COMMUNITY_LINK_TABLES)
    for claim in (
        f"{official:,} official and {community:,} from the community",
        f"pinned on {record['sources_snapshot']}",
        f"Scryfall's file holds {read['rulings']:,}, and "
        f"{read['rulings written by Scryfall']:,} of them were written by Scryfall's own staff",
        f"except the {record['methods']['rulings']['scryfall']:,} Scryfall's own staff wrote",
        f"the {record['methods']['rulings']['scryfall']:,} of those on cards that count are "
        "marked as Scryfall's",
        f"{reach['rulings']:,} of the {cards:,} cards ({reach['rulings'] / cards:.1%}) have at "
        "least one ruling",
        f"only {round(reach['rulings'] / cards * 10)} in 10 have a ruling",
        f"{record['unlinked_tags']['oracle tags']:,} Oracle Tags and "
        f"{record['unlinked_tags']['art tags']:,} Art Tags link to nothing that counts",
        f"{reach['oracle tags']:,} ({reach['oracle tags'] / cards:.1%}) have an Oracle Tag",
        f"{reach['art tags']:,} ({reach['art tags'] / cards:.0%}) have a picture with an Art Tag",
        f"{skipped['rulings']['for a card that doesn' + chr(39) + 't count']:,} rulings for "
        f"cards that don't count and {skipped['rulings']['an exact repeat of another ruling']:,} "
        "exact repeats",
        f"{sum(skipped['oracle tag links'].values()):,} Oracle Tag links on cards that don't count",
        f"{sum(skipped['art tag links'].values()):,} Art Tag links on pictures that no real "
        "printing of a counted card has",
    ):
        assert claim in readme, f"README is missing: {claim}"


def test_the_art_tag_draw_in_the_readme_is_the_recorded_one(root):
    readme = (root / "README.md").read_text()
    record = json.loads((root / "results/art_tag_sample.json").read_text())
    quotas = record["quotas"]
    drawn = sum(quotas.values())
    assert len(record["sample"]) == drawn
    assert f"draws {drawn} tagged pictures" in readme
    words = ", ".join(f"{quotas[w]} {w.replace('_', ' ')}" for w in list(quotas)[:-1])
    last = list(quotas)[-1]
    assert f"{words} and {quotas[last]} {last.replace('_', ' ')}" in readme
    assert f"my check of {drawn} art tags" in readme


def test_the_art_tag_draw_is_whole(root):
    record = json.loads((root / "results/art_tag_sample.json").read_text())
    rows = record["sample"]
    assert record["seed"] == tags.SEED
    assert record["quotas"] == tags.QUOTAS
    assert record["how"] == tags.how(tags.QUOTAS)
    assert [row["number"] for row in rows] == list(range(1, len(rows) + 1))
    for weight, quota in record["quotas"].items():
        assert sum(row["weight"] == weight for row in rows) == quota
        assert quota <= record["labels_in_the_graph"][weight]
    tables = json.loads((root / "results/graph.json").read_text())["tables"]
    assert sum(record["labels_in_the_graph"].values()) == tables["illustration_art_tag"]
    for row in rows:
        assert row["link"] == tags.link(row["set"], row["collector_number"])
        assert row["card"] and row["tag"] and row["illustration_id"] and row["tag_id"]
        assert row["face"] in ("front", "back")
        assert "annotation" not in row, "volunteers' notes stay out of the repo"
    assert len({(row["illustration_id"], row["tag_id"]) for row in rows}) == len(rows)


NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def test_the_pinned_files_in_the_readme_are_the_pinned_ones(root):
    readme = (root / "README.md").read_text()
    assert f"{sum(file.packed_bytes for file in ALL_FILES) / 1e6:.1f} MB" in readme
    assert f"fetch the {NUMBER_WORDS[len(ALL_FILES)]} pinned files" in readme
    assert f"{NUMBER_WORDS[len(ALL_FILES)]} pinned files, one rule" in readme


def test_the_blueprint_table_of_rulings_and_tags_is_the_recorded_one(root):
    blueprint = (root / "docs/BLUEPRINT.md").read_text()
    read = json.loads((root / "results/graph.json").read_text())["files_read"]
    for row in (
        f"| {read['rulings']:,} rulings, {read['rulings written by Scryfall']:,} of them written "
        f"by Scryfall's staff; {RULINGS.packed_bytes / 1e6:.1f} MB packed |",
        f"| {read['oracle tags']:,} tags used {read['oracle tag links']:,} times; "
        f"{ORACLE_TAGS.packed_bytes / 1e6:.1f} MB packed |",
        f"| {read['art tags']:,} tags used {read['art tag links']:,} times; "
        f"{ART_TAGS.packed_bytes / 1e6:.1f} MB packed |",
    ):
        assert row in blueprint, f"the blueprint is missing: {row}"
    assert f"All {NUMBER_WORDS[len(ALL_FILES)]} are gzipped JSON Lines files" in blueprint


def test_the_community_links_in_the_readme_split_as_recorded(root):
    readme = (root / "README.md").read_text()
    tables = json.loads((root / "results/graph.json").read_text())["tables"]
    on_cards = tables["card_oracle_tag"] + tables["illustration_art_tag"]
    between = tables["art_tag_parent"] + tables["oracle_tag_parent"]
    assert on_cards + between == sum(tables[table] for table in COMMUNITY_LINK_TABLES)
    assert (
        f"Of the community ones, {on_cards:,} tag a card or a picture, and {between:,} tie a "
        "tag to its parent tag" in readme
    )


def test_what_the_papers_say_the_art_tag_bar_takes_is_what_the_score_does(root):
    """The share of median links, what the overall is worth, and how many of the
    median labels may be wrong with the bar still cleared, worked out from the record."""
    readme = (root / "README.md").read_text()
    blueprint = (root / "docs/BLUEPRINT.md").read_text()
    record = json.loads((root / "results/art_tag_sample.json").read_text())
    in_graph, quotas = record["labels_in_the_graph"], record["quotas"]
    median = quotas["median"]
    assert f"{in_graph['median'] / sum(in_graph.values()):.1%} of the art-tag links are median" in (
        readme
    )
    _, worth = tags.weighted(in_graph, {w: (quotas[w], quotas[w]) for w in quotas})
    for paper in (readme, blueprint):
        assert f"worth about {worth:.0f} labels" in paper

    def clears(wrong_median: int) -> bool:
        marks = []
        for row in record["sample"]:
            wrong = row["weight"] == "median" and wrong_median > 0
            wrong_median -= wrong
            marks.append(
                {
                    "illustration_id": row["illustration_id"],
                    "tag_id": row["tag_id"],
                    "verdict": "wrong" if wrong else "right",
                }
            )
        return tags.score(record, {"verdicts": marks})["clears_the_bar"]

    most = max(k for k in range(median + 1) if clears(k))
    assert not clears(most + 1)
    for paper in (readme, blueprint):
        assert f"only if at most {most} of those {median} are wrong" in paper
