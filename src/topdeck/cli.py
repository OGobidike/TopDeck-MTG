"""The `topdeck` command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from topdeck.ground import (
    HAND_WRITTEN,
    HAND_WRITTEN_TARGET,
    ORIGINALS,
    changed_originals,
    check_questions,
    read_questions,
)


def ground(root: Path) -> int:
    """Run the Phase 0 checks from the repo's root. Returns the exit code."""
    problems = []

    changed = changed_originals(root)
    print(f"The 2024 files: {len(ORIGINALS) - len(changed)} of {len(ORIGINALS)} untouched")
    for path in changed:
        problems.append(f"{path} is missing or changed; it must stay byte for byte as it was")

    try:
        questions = read_questions(root / HAND_WRITTEN)
    except OSError as error:
        print(f"Could not read the hand-written questions: {error}")
        return 1
    print(f"Hand-written questions: {len(questions)} of {HAND_WRITTEN_TARGET}")
    problems.extend(check_questions(questions))

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nThe ground holds.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="topdeck",
        description="Questions about Magic: The Gathering cards, answered five ways.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ground_parser = commands.add_parser(
        "ground", help="check the 2024 files are untouched and count the hand-written questions"
    )
    ground_parser.add_argument(
        "--root", type=Path, default=Path("."), help="the repo's root (default: here)"
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "ground":
        return ground(arguments.root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
