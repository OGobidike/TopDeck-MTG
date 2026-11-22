"""The `topdeck` command."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

from topdeck.census import load_cards
from topdeck.ground import (
    CHOSEN,
    CHOSEN_TARGET,
    ORIGINALS,
    changed_originals,
    check_questions,
    read_questions,
)
from topdeck.snapshot import DATA_DIR, FILES, SNAPSHOT_DATE, BulkFile, fetch, verify

RESULTS = Path("results/cards.json")


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
    try:
        for file in files:
            verify(folder / file.filename, file)
    except OSError:
        print(f"The card files aren't in {folder}/. Fetch them with: topdeck cards fetch --yes")
        return 1
    except ValueError as error:
        print(error)
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
    for sub in (fetch_parser, count_parser):
        sub.add_argument("--data", type=Path, default=DATA_DIR, help="where the card files live")

    arguments = parser.parse_args(argv)
    if arguments.command == "ground":
        return ground(arguments.root)
    if arguments.action == "fetch":
        return fetch_cards(arguments.data, arguments.yes)
    return count_cards(arguments.data, RESULTS, arguments.write)


if __name__ == "__main__":
    sys.exit(main())
