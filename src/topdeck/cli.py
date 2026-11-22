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
from topdeck.snapshot import DATA_DIR, FILES, SNAPSHOT_DATE, BulkFile, fetch, verify

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
        return 1
    print("\nThe ground holds.")
    return 0


def megabytes(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


def fetch_cards(
    folder: Path,
    agreed: bool,
    files: tuple[BulkFile, ...] = FILES,
    open_url: Callable = urllib.request.urlopen,
) -> int:
    """Download the pinned card files. Says what it will cost first, and waits for --yes."""
    total = sum(file.packed_bytes for file in files)
    print(f"The card files of {SNAPSHOT_DATE}, from Scryfall:")
    for file in files:
        print(f"  {file.name:14} {megabytes(file.packed_bytes):>9}  {file.filename}")
    print(f"  {'In all':14} {megabytes(total):>9}  kept packed in {folder}/, never unpacked")
    if not agreed:
        print("\nNothing was downloaded. Run it again with --yes to fetch them.")
        return 0
    for file in files:
        try:
            fetch(file, folder, open_url)
        except (OSError, ValueError) as error:
            print(f"\nCould not fetch {file.name}: {error}")
            print("Scryfall replaces its files daily, so this pinned one may be gone.")
            return 1
        print(f"  fetched and verified: {file.filename}")
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

    try:
        recorded = json.loads(results.read_text(encoding="utf-8"))
    except OSError:
        print(f"\nThere is no record at {results} to check against.")
        return 1
    differences = [
        f"{key}: counted {census.get(key)!r}, recorded {recorded.get(key)!r}"
        for key in sorted(set(census) | set(recorded))
        if census.get(key) != recorded.get(key)
    ]
    if differences:
        print(f"\nThe count does not match {results}:")
        for difference in differences:
            print(f"  - {difference}")
        return 1
    print(f"\nEvery number matches {results}.")
    return 0


def files_are_in_place(folder: Path, files: tuple[BulkFile, ...]) -> bool:
    """Check the pinned card files are there and whole, and say so plainly if not."""
    try:
        for file in files:
            verify(folder / file.filename, file)
    except OSError:
        print(f"The card files aren't in {folder}/. Fetch them with: topdeck cards fetch --yes")
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
) -> int:
    """Load the cards that count, their real printings and every given link."""
    if not files_are_in_place(folder, files):
        return 1
    try:
        connection = graph.connect(url)
    except graph.DatabaseUnreachable as error:
        print(error)
        return 1
    try:
        cards, _ = load_cards(folder, *files)
        printings = graph.read_printings(folder, cards, files[1])
        with connection:
            counts = graph.build(connection, cards, printings, schema)
    except (psycopg.Error, ValueError, KeyError) as error:
        print(
            f"The graph was not built, and any graph already there is unchanged: "
            f"{first_line(error)}"
        )
        return 1
    links = sum(counts[table] for table in graph.LINK_TABLES)
    print(
        f"The graph is built: {counts['cards']:,} cards, {counts['printings']:,} printings "
        f"and {links:,} links."
    )
    return 0


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
            if not graph.is_built(connection, schema):
                print("The graph isn't built yet. Build it with: topdeck graph build")
                return 1
            counts = graph.count(connection, schema)
    except (psycopg.Error, ValueError) as error:
        print(f"The graph could not be counted: {first_line(error)}")
        return 1

    print("The graph holds:")
    for table in graph.THING_TABLES:
        print(f"  {counts[table]:>9,}  {table}")
    print("\nIts links:")
    for table in graph.LINK_TABLES:
        print(f"  {counts[table]:>9,}  {table}")

    found = {"snapshot": SNAPSHOT_DATE, "tables": counts}
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
    if recorded.get("snapshot") != SNAPSHOT_DATE:
        differences.append(f"snapshot: {SNAPSHOT_DATE}, recorded {recorded.get('snapshot')!r}")
    if differences:
        print(f"\nThe graph does not match {results}:")
        for difference in differences:
            print(f"  - {difference}")
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
            if not graph.is_built(connection, schema):
                print("The graph isn't built yet. Build it with: topdeck graph build")
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
        print(f"\nThe answers do not match {results}:")
        for problem in problems[:20]:
            print(f"  - {problem}")
        return 1
    print(f"\nEvery answer matches {results}.")
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

    cards = commands.add_parser("cards", help="fetch the pinned card files, or count the cards")
    actions = cards.add_subparsers(dest="action", required=True)
    fetch_parser = actions.add_parser("fetch", help="download the pinned card files")
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
        "build", help="load the cards, their printings and every given link"
    )
    graph_count_parser = graph_actions.add_parser(
        "count", help="count every table and check the recorded counts"
    )
    answers_parser = commands.add_parser(
        "answers", help="answer the three 2024 questions and check the recorded answers"
    )
    for sub in (graph_count_parser, answers_parser):
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
    if arguments.command == "graph":
        if arguments.action == "build":
            return build_graph(arguments.data)
        return count_graph(GRAPH_RESULTS, arguments.write)
    if arguments.action == "fetch":
        return fetch_cards(arguments.data, arguments.yes)
    return count_cards(arguments.data, RESULTS, arguments.write)


if __name__ == "__main__":
    sys.exit(main())
