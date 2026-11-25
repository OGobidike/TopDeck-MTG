"""The `topdeck` command."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

import psycopg

from topdeck import answers as answers_module
from topdeck import graph
from topdeck import tags as tags_module
from topdeck.census import load_cards
from topdeck.ground import (
    CHOSEN,
    CHOSEN_TARGET,
    ORIGINALS,
    changed_originals,
    check_questions,
    read_questions,
)
from topdeck.pages import ANSWERS_PAGE, render_answers
from topdeck.snapshot import (
    ALL_FILES,
    DATA_DIR,
    FILES,
    SNAPSHOT_DATE,
    SOURCE_FILES,
    SOURCES_SNAPSHOT_DATE,
    BulkFile,
    fetch,
    verify,
)

RESULTS = Path("results/cards.json")


def first_line(error: BaseException) -> str:
    """An error's message, cut to its first line so a verdict stays one plain line."""
    text = str(error).strip().splitlines()
    return text[0] if text else type(error).__name__


def read_record(results: Path) -> tuple[dict | None, str | None]:
    """A recorded result, or the plain reason it can't be read."""
    try:
        recorded = json.loads(results.read_text(encoding="utf-8"))
    except OSError:
        return None, f"There is no record at {results} to check against."
    except ValueError as error:
        return None, f"The record at {results} is not valid JSON: {first_line(error)}."
    if not isinstance(recorded, dict):
        return None, f"The record at {results} is not the shape this command writes."
    return recorded, None


GRAPH_RESULTS = Path("results/graph.json")
ANSWERS_RESULTS = Path("results/answers_2024.json")
SAMPLE_RESULTS = Path("results/art_tag_sample.json")
VERDICTS_RESULTS = Path("results/art_tag_verdicts.json")


def ground(root: Path) -> int:
    """Run the Phase 0 checks from the repo's root. Returns the exit code."""
    problems = []

    changed = changed_originals(root)
    print(f"The 2024 files: {len(ORIGINALS) - len(changed)} of {len(ORIGINALS)} untouched")
    for path in changed:
        problems.append(f"{path} is missing or changed; it must stay byte for byte as it was")

    try:
        questions = read_questions(root / CHOSEN)
    except OSError as error:
        print(f"Could not read the chosen questions: {error}")
        return 1
    print(f"Chosen questions: {len(questions)} of {CHOSEN_TARGET}")
    problems.extend(check_questions(questions))

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        print("\nThe ground does not hold.")
        return 1
    print("\nThe ground holds.")
    return 0


NUMBERS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def megabytes(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


def fetch_cards(
    folder: Path,
    agreed: bool,
    files: tuple[BulkFile, ...] = ALL_FILES,
    open_url: Callable = urllib.request.urlopen,
) -> int:
    """Download the pinned files. Says what they will cost first, and waits for --yes."""
    total = sum(file.packed_bytes for file in files)
    print("Scryfall's pinned files:")
    for file in files:
        held = " (already here)" if (folder / file.filename).is_file() else ""
        print(
            f"  {file.name:14} {megabytes(file.packed_bytes):>9}  {file.snapshot}  "
            f"{file.filename}{held}"
        )
    print(f"  {'In all':14} {megabytes(total):>9}  kept packed in {folder}/, never unpacked")
    if not agreed:
        if all((folder / file.filename).is_file() for file in files):
            print(
                f"\nAll {NUMBERS.get(len(files), len(files))} pinned files are already here; "
                "nothing to download. Run it again with --yes to check their fingerprints."
            )
            return 0
        print("\nNothing was downloaded. Run it again with --yes to fetch them.")
        return 0
    print()
    for file in files:
        held = (folder / file.filename).is_file()
        try:
            fetch(file, folder, open_url)
        except (OSError, ValueError) as error:
            print(f"\nCould not fetch {file.name}: {error}")
            print("Scryfall replaces its files daily, so this pinned one may be gone.")
            return 1
        print(f"  {'already here, verified' if held else 'fetched and verified'}: {file.filename}")
    print(f"\nEvery pinned file is in {folder}/ and matches its fingerprint.")
    return 0


def show(census: dict) -> None:
    print(f"Scryfall's files of {census['snapshot']}:")
    print(f"  {census['entries']:>7,} entries in Oracle Cards")
    print(f"  {census['printings']:>7,} printings in Default Cards")
    print(f"  {census['cards']:>7,} count as cards\n")
    print("Left out, and why:")
    for reason, number in census["left_out"].items():
        print(f"  {number:>7,}  {reason}")


def count_cards(
    folder: Path,
    results: Path,
    write: bool,
    files: tuple[BulkFile, BulkFile] = FILES,
) -> int:
    """Apply the rule for what counts as a card, and check the count against the record."""
    if not files_are_in_place(folder, files):
        return 1

    _, census = load_cards(folder, *files)
    show(census)

    if write:
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps(census, indent=2) + "\n", encoding="utf-8")
        print(f"\nRecorded in {results}.")
        return 0

    recorded, problem = read_record(results)
    if problem:
        print(f"\n{problem}")
        return 1
    differences = [
        f"{key}: counted {census.get(key)!r}, recorded {recorded.get(key)!r}"
        for key in sorted(set(census) | set(recorded))
        if census.get(key) != recorded.get(key)
    ]
    if differences:
        print("\nWhere it differs:")
        for difference in differences:
            print(f"  - {difference}")
        print(f"\nThe count does not match {results}.")
        return 1
    print(f"\nEvery number matches {results}.")
    return 0


def files_are_in_place(folder: Path, files: tuple[BulkFile, ...]) -> bool:
    """Check the pinned files are there and whole, and say so plainly if not."""
    try:
        for file in files:
            verify(folder / file.filename, file)
    except OSError:
        print(
            f"Scryfall's files aren't all in {folder}/. Fetch them with: topdeck cards fetch --yes"
        )
        return False
    except ValueError as error:
        print(error)
        return False
    return True


def build_graph(
    folder: Path,
    url: str | None = None,
    schema: str = graph.SCHEMA,
    files: tuple[BulkFile, BulkFile] = FILES,
    sources: tuple[BulkFile, BulkFile, BulkFile] = SOURCE_FILES,
) -> int:
    """Load the cards that count, their real printings, their rulings and every link."""
    if not files_are_in_place(folder, (*files, *sources)):
        return 1
    try:
        connection = graph.connect(url)
    except graph.DatabaseUnreachable as error:
        print(error)
        return 1
    try:
        cards, _ = load_cards(folder, *files)
        printings = graph.read_printings(folder, cards, files[1])
        extra = graph.read_sources(folder, cards, printings, sources)
        with connection:
            counts = graph.build(connection, cards, printings, schema, extra)
    except (psycopg.Error, ValueError, KeyError) as error:
        print(
            f"The graph was not built, and any graph already there is unchanged: "
            f"{first_line(error)}"
        )
        return 1
    given = sum(counts[table] for table in graph.GIVEN_LINK_TABLES)
    community = sum(counts[table] for table in graph.COMMUNITY_LINK_TABLES)
    print(
        f"The graph is built: {counts['cards']:,} cards, {counts['printings']:,} printings, "
        f"{counts['rulings']:,} rulings, {given:,} official links and "
        f"{community:,} community ones."
    )
    return 0


# How the record's keys are said on screen.
SAID = {
    "given links": "official links",
    "rulings": "rulings",
    "oracle tags": "Oracle Tags",
    "art tags": "Art Tags",
}


def count_graph(
    results: Path, write: bool, url: str | None = None, schema: str = graph.SCHEMA
) -> int:
    """Count every table of the graph, and check the counts against the record."""
    try:
        connection = graph.connect(url)
    except graph.DatabaseUnreachable as error:
        print(error)
        return 1
    try:
        with connection:
            waiting = graph.not_ready(connection, schema)
            if waiting:
                print(waiting)
                return 1
            counts = graph.count(connection, schema)
            reach = graph.coverage(connection, schema)
            read = graph.files_read(connection, schema)
            left_out = graph.skipped(connection, schema)
            by_method = graph.methods(connection, schema)
            unlinked = graph.unlinked_tags(connection, schema)
    except (psycopg.Error, ValueError) as error:
        print(f"The graph could not be counted: {first_line(error)}")
        return 1

    print("The graph holds:")
    for table in graph.THING_TABLES:
        print(f"  {counts[table]:>9,}  {table}")
    print("\nIts official links:")
    for table in graph.GIVEN_LINK_TABLES:
        print(f"  {counts[table]:>9,}  {table}")
    print("\nIts community links:")
    for table in graph.COMMUNITY_LINK_TABLES:
        print(f"  {counts[table]:>9,}  {table}")
    print(f"\nOf the {counts['cards']:,} cards, how many each source reaches:")
    for name, cards in reach.items():
        share = f" ({cards / counts['cards']:.1%})" if counts["cards"] else ""
        print(f"  {cards:>9,}  {SAID.get(name, name)}{share}")
    if left_out:
        print("\nRead from the files but not loaded, and why:")
        for what, reasons in left_out.items():
            for reason, rows in reasons.items():
                print(f"  {rows:>9,}  {what}: {reason}")
    print("\nTags kept so the tag tree stays whole, though no loaded link uses them:")
    for name, tags in unlinked.items():
        print(f"  {tags:>9,}  {SAID.get(name, name)}")

    found = {
        "snapshot": SNAPSHOT_DATE,
        "sources_snapshot": SOURCES_SNAPSHOT_DATE,
        "tables": counts,
        "coverage": reach,
        "files_read": read,
        "skipped": left_out,
        "methods": by_method,
        "unlinked_tags": unlinked,
    }
    if write:
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
        print(f"\nRecorded in {results}.")
        return 0
    recorded, problem = read_record(results)
    if problem:
        print(f"\n{problem}")
        return 1
    tables_recorded = recorded.get("tables")
    if not isinstance(tables_recorded, dict):
        print(f"\nThe record at {results} has no table counts to check against.")
        return 1
    differences = [
        f"{table}: counted {counts.get(table)!r}, recorded {tables_recorded.get(table)!r}"
        for table in sorted(set(counts) | set(tables_recorded))
        if counts.get(table) != tables_recorded.get(table)
    ]
    for key in sorted(set(found) - {"tables"}):
        if found[key] != recorded.get(key):
            differences.append(f"{key}: counted {found[key]!r}, recorded {recorded.get(key)!r}")
    if differences:
        print("\nWhere it differs:")
        for difference in differences:
            print(f"  - {difference}")
        print(f"\nThe graph does not match {results}.")
        return 1
    print(f"\nEvery number matches {results}.")
    return 0


def answer_2024(
    results: Path,
    page: Path,
    write: bool,
    url: str | None = None,
    schema: str = graph.SCHEMA,
) -> int:
    """Answer the three 2024 questions from the graph, and check them against the record."""
    try:
        connection = graph.connect(url)
    except graph.DatabaseUnreachable as error:
        print(error)
        return 1
    try:
        with connection:
            waiting = graph.not_ready(connection, schema)
            if waiting:
                print(waiting)
                return 1
            found = answers_module.answer(connection, schema)
    except (psycopg.Error, ValueError, KeyError) as error:
        print(f"The questions could not be answered: {first_line(error)}")
        return 1

    one, two = found["elves_and_goblins"], found["artists"]
    elf, goblin = one["elves_green"], one["goblins_red"]
    if elf and goblin:
        print(
            f"Elves: {elf['with_colour']:,} of {elf['cards']:,} are green, "
            f"{elf['lift']:.2f} times the share among all creatures."
        )
        print(
            f"Goblins: {goblin['with_colour']:,} of {goblin['cards']:,} are red, "
            f"{goblin['lift']:.2f} times the share among all creatures."
        )
    if two["by_printings"]:
        leader = two["by_printings"][0]
        rank = leader["rank_2024"] if leader["rank_2024"] is not None else "not ranked"
        print(
            f"Artists: {leader['artist']} leads with {leader['printings']:,} printings, "
            f"{leader['basic_lands']:,} of them basic lands; the 2024 way ranks them {rank}."
        )

    if write:
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps(found, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(render_answers(found), encoding="utf-8")
        print(f"\nRecorded in {results} and written up in {page}.")
        return 0
    recorded, problem = read_record(results)
    if problem:
        print(f"\n{problem}")
        return 1
    problems = answers_module.differences(found, recorded)
    if problems:
        print("\nWhere it differs:")
        for problem in problems[:20]:
            print(f"  - {problem}")
        print(f"\nThe answers do not match {results}.")
        return 1
    print(f"\nEvery answer matches {results}.")
    return 0


def sample_tags(
    results: Path,
    write: bool,
    url: str | None = None,
    schema: str = graph.SCHEMA,
    table: Path | None = None,
) -> int:
    """Draw the 50 art tags to check by eye, and check the draw against the record."""
    try:
        connection = graph.connect(url)
    except graph.DatabaseUnreachable as error:
        print(error)
        return 1
    try:
        with connection:
            waiting = graph.not_ready(connection, schema)
            if waiting:
                print(waiting)
                return 1
            found = tags_module.sample(connection, schema)
    except (psycopg.Error, ValueError, KeyError) as error:
        print(f"The art tags could not be drawn: {first_line(error)}")
        return 1

    weights = ", ".join(
        f"{sum(row['weight'] == weight for row in found['sample'])} {weight.replace('_', ' ')}"
        for weight in graph.WEIGHTS
    )
    print(f"Drew {len(found['sample'])} art tags to check by eye: {weights}.")
    if table is not None:
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text(tags_module.table(found), encoding="utf-8")
        print(f"The table to mark by hand is in {table}.")
    kept = tags_module.public(found)
    if write:
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nRecorded in {results}.")
        return 0
    recorded, problem = read_record(results)
    if problem:
        print(f"\n{problem}")
        return 1
    if kept != recorded:
        print(f"\nThe draw does not match {results}.")
        return 1
    print(f"\nThe draw matches {results}.")
    return 0


def score_tags(draw_record: Path, verdicts: Path, table: Path | None = None) -> int:
    """Score my verdicts on the 50 drawn art tags, by weight and weighted overall.

    With `table`, the verdicts are first read from the table I marked, and recorded in
    `verdicts`, keyed by picture and tag. Without it, the recorded verdicts are scored."""
    draw, problem = read_record(draw_record)
    if problem:
        print(problem)
        return 1
    if table is not None:
        try:
            marked = tags_module.read_table(draw, table.read_text(encoding="utf-8"))
        except OSError:
            print(f"Nothing was scored: there is no marked table at {table}.")
            return 1
        except (ValueError, KeyError, TypeError) as error:
            print(f"The table at {table} could not be read: {first_line(error)}.")
            return 1
    elif not verdicts.is_file():
        print("To score, mark the table and run: topdeck tags score --table <the table>")
        print(f"Nothing was scored: no verdicts are recorded yet in {verdicts}.")
        return 0
    else:
        marked, problem = read_record(verdicts)
        if problem:
            print(problem)
            return 1
    try:
        found = tags_module.score(draw, marked)
    except (ValueError, KeyError, TypeError) as error:
        print(f"The verdicts could not be scored: {first_line(error)}.")
        return 1
    if table is not None:
        verdicts.parent.mkdir(parents=True, exist_ok=True)
        verdicts.write_text(json.dumps(marked, indent=2) + "\n", encoding="utf-8")
        print(f"Read {len(marked['verdicts'])} verdicts from {table}, recorded in {verdicts}.\n")
    print(f"Marked {found['marked']} of the {found['drawn']} drawn art tags:")
    for weight, row in found["by_weight"].items():
        judged = row["right"] + row["wrong"]
        interval = (
            f" (95% interval {row['share_low']:.0%} to {row['share_high']:.0%})" if judged else ""
        )
        unsure = f", {row['cant_tell']} can't tell" if row["cant_tell"] else ""
        print(
            f"  {tags_module.words(weight):12} {row['right']:>3} of {judged:>3} "
            f"right{interval}{unsure}"
        )
    if found["overall"] is None:
        print(f"\nThe score is not final: {found['drawn'] - found['marked']} are still unmarked.")
        return 0
    overall = found["overall"]
    verdict = "clears" if found["clears_the_bar"] else "misses"
    print(
        f"\nWeighted by the art tags of each weight in the graph, the verdicts are worth "
        f"about {overall['worth_labels']:.0f} labels. Marked can't tell, and left out: "
        f"{found['cant_tell']}."
    )
    print(
        f"{overall['share_right']:.1%} are right (95% interval {overall['share_low']:.0%} to "
        f"{overall['share_high']:.0%}), which {verdict} the bar of {found['bar']:.0%}."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="topdeck",
        description="Questions about Magic: The Gathering cards, answered five ways.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ground_parser = commands.add_parser(
        "ground", help="check the 2024 files are untouched and count the chosen questions"
    )
    ground_parser.add_argument(
        "--root", type=Path, default=Path("."), help="the repo's root (default: here)"
    )

    cards = commands.add_parser("cards", help="fetch Scryfall's pinned files, or count the cards")
    actions = cards.add_subparsers(dest="action", required=True)
    fetch_parser = actions.add_parser(
        "fetch", help="download the pinned card, rulings and tag files"
    )
    fetch_parser.add_argument("--yes", action="store_true", help="agree to the download")
    count_parser = actions.add_parser(
        "count", help="apply the rule for what counts as a card and check the recorded count"
    )
    count_parser.add_argument(
        "--write", action="store_true", help="record the count instead of checking it"
    )
    graph_parser = commands.add_parser("graph", help="build the graph in PostgreSQL, or count it")
    graph_actions = graph_parser.add_subparsers(dest="action", required=True)
    build_parser = graph_actions.add_parser(
        "build",
        help="load the cards, their printings, every given link, the rulings and the tags",
    )
    graph_count_parser = graph_actions.add_parser(
        "count", help="count every table and check the recorded counts"
    )
    answers_parser = commands.add_parser(
        "answers", help="answer the three 2024 questions and check the recorded answers"
    )
    tags_parser = commands.add_parser("tags", help="the art-tag check")
    tags_actions = tags_parser.add_subparsers(dest="action", required=True)
    sample_parser = tags_actions.add_parser(
        "sample", help="draw the 50 art tags to check by eye, and check the recorded draw"
    )
    sample_parser.add_argument(
        "--table", type=Path, help="also write the draw as a table to mark by hand, here"
    )
    score_parser = tags_actions.add_parser(
        "score", help="score my verdicts on the drawn art tags, by weight and overall"
    )
    score_parser.add_argument(
        "--table", type=Path, help="read the verdicts from this marked table, and record them"
    )
    commands.add_parser(
        "figures", help="draw every chart from the recorded results, light and dark"
    )
    for sub in (graph_count_parser, answers_parser, sample_parser):
        sub.add_argument(
            "--write", action="store_true", help="record the result instead of checking it"
        )

    for sub in (fetch_parser, count_parser, build_parser):
        sub.add_argument("--data", type=Path, default=DATA_DIR, help="where the card files live")

    arguments = parser.parse_args(argv)
    if arguments.command == "ground":
        return ground(arguments.root)
    if arguments.command == "answers":
        return answer_2024(ANSWERS_RESULTS, ANSWERS_PAGE, arguments.write)
    if arguments.command == "tags":
        if arguments.action == "score":
            return score_tags(SAMPLE_RESULTS, VERDICTS_RESULTS, arguments.table)
        return sample_tags(SAMPLE_RESULTS, arguments.write, table=arguments.table)
    if arguments.command == "figures":
        return draw_figures()
    if arguments.command == "graph":
        if arguments.action == "build":
            return build_graph(arguments.data)
        return count_graph(GRAPH_RESULTS, arguments.write)
    if arguments.action == "fetch":
        return fetch_cards(arguments.data, arguments.yes)
    return count_cards(arguments.data, RESULTS, arguments.write)


def draw_figures(root: Path = Path(".")) -> int:
    """Draw every chart from the recorded results. Needs the figures extra."""
    try:
        from topdeck import figures
    except ModuleNotFoundError as error:
        if error.name != "matplotlib" and not (error.name or "").startswith("matplotlib."):
            raise
        print("Drawing needs matplotlib. Install it with: uv sync --extra figures")
        return 1
    try:
        written = figures.draw_all(root)
    except (OSError, ValueError) as error:
        print(f"The charts were not drawn: {first_line(error)}")
        return 1
    print(f"Drew {len(written)} images into {figures.OUT}/ from the records in results/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
