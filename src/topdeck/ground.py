"""Phase 0, the ground: the checks that must hold before any card is loaded.

Two things are guarded here. The 2024 files this project grew from stay exactly as they
were, and the questions I write by hand are well formed and counted.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

ORIGINAL_DIR = Path("notebooks/2024-original")
# Every 2024 file and its SHA-256 fingerprint.
ORIGINALS = {
    ORIGINAL_DIR / "topdeck_magic_the_gathering_portfolio_project.py": (
        "0420b1b087c74a0d9c1f0e99bc6ef56cdb3e80c5f066c3d401d8acbafa05e429"
    ),
    ORIGINAL_DIR / "README.md": (
        "d000f3613522ee907f88c47f67ca95801bad2492be5cf7a0addd5f23d912fbe7"
    ),
}

HAND_WRITTEN = Path("questions/hand_written.md")
HAND_WRITTEN_TARGET = 100

# A question is a numbered line: "12. Which cards ...?"
_NUMBERED = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Question:
    number: int
    text: str


def fingerprint(path: Path) -> str:
    """The SHA-256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changed_originals(root: Path) -> list[Path]:
    """The 2024 files that are no longer byte for byte what they were, or are missing."""
    changed = []
    for path, expected in ORIGINALS.items():
        file = root / path
        if not file.is_file() or fingerprint(file) != expected:
            changed.append(path)
    return changed


def read_questions(path: Path) -> list[Question]:
    """Read the numbered questions from the hand-written page, in the order written."""
    questions = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _NUMBERED.match(line)
        if match:
            questions.append(Question(int(match.group(1)), match.group(2)))
    return questions


def _key(text: str) -> str:
    """How two questions are compared: letters and digits only, in lower case."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def check_questions(questions: list[Question], target: int = HAND_WRITTEN_TARGET) -> list[str]:
    """Every rule a hand-written question must keep. Returns the problems found."""
    problems = []
    seen: dict[str, int] = {}
    for position, question in enumerate(questions, start=1):
        if question.number != position:
            problems.append(f"question {position} is numbered {question.number}")
        if not question.text.endswith("?"):
            problems.append(f"question {question.number} doesn't end with a question mark")
        if len(question.text.split()) < 3:
            problems.append(f"question {question.number} is shorter than three words")
        key = _key(question.text)
        if key in seen:
            problems.append(f"question {question.number} repeats question {seen[key]}")
        seen.setdefault(key, question.number)
    if len(questions) > target:
        problems.append(f"{len(questions)} questions written, and the page holds {target}")
    return problems
