# 🃏 TopDeck

**Questions about Magic: The Gathering cards, answered five ways, with every answer scored by code.**

Most assistants today answer by search: they fetch the few passages that sound most like the question and answer from those. That works for "what does Counterspell do?". It fails for "how many red Goblins cost two mana or less?", because counting needs every matching card, not the five that sound closest.

A knowledge graph stores each fact as a link: this card is red, this card is a Goblin, this card was printed in that set. A query over those links can count, filter and walk from fact to fact.

TopDeck builds both, puts three simpler systems beside them, and measures what each step up buys and what it costs.

I'm building it for two kinds of people:

- **Anyone deciding whether their assistant needs a graph.** The results will show which kinds of question it helps, which it doesn't, and what plain filters already reach.
- **Anyone learning to test AI systems.** Every score here will be rerun by one command.

## 🗺️ Where it stands

Nothing here answers a question yet. The plan is written and the ground is laid.

| Phase | What it ships | Status |
| --- | --- | --- |
| 0. Ground | The [blueprint](docs/BLUEPRINT.md), tooling, CI, the 2024 code set aside untouched, and [100 questions I write by hand](questions/hand_written.md) | 🔨 Under way |
| 1. The cards | The pinned card file, the cards in PostgreSQL with every given link, and my three 2024 questions answered | Planned |
| 2. The questions | About 530 questions, most with an answer a query can prove | Planned |
| 3. Search | The model alone, search, and search with filters | Planned |
| 4. The graph route | A model that writes read-only queries, inside a fence | Planned |
| 5. Extraction | What cards do, pulled from rules text and scored against my labels | Planned |
| 6. The router | A system that picks a route for each question; the final scores | Planned |
| 7. Serving | An API, a Docker image and a page to ask questions | Planned |
| 8. The telling | The results, written up | Planned |

The [blueprint](docs/BLUEPRINT.md) holds the full plan: the cards, the graph, the questions, the five contenders, how every answer is scored, the cost and the limits.

## 🥊 The contest

Five systems answer the same questions, each one step up from the last, so every gain is measured against something simpler.

| Contender | How it answers |
| --- | --- |
| A. Closed book | The model alone, from memory |
| B. Search | Finds the closest cards by meaning and by keywords, then answers from those |
| C. Search with filters | The model also sets filters on colour, type and cost, and every match comes back |
| D. Graph | The model writes a read-only query over the graph and words the rows that come back |
| E. Router | Plans the steps and picks a route for each |

That a database can count and a top-five search can't is known before the first run, so it is not the finding. These are the open questions:

- How often does a model write the right query, and how often is it wrong while sounding sure?
- How much does the wording of a question move the answer?
- How much of the graph's gain can plain filters already reach?
- Does knowledge pulled out of rules text help, or mislead?
- What does each answer cost?

My prediction for each kind of question is [written in the blueprint](docs/BLUEPRINT.md#the-questions) before any run. A wrong one stays in this README.

## 🕰️ 2024 and 2026

I started TopDeck in 2024 as a notebook with three questions. Are Elves green and Goblins red? Do some artists appear far more than others? Which subtypes hide inside which colours? It printed four counts and stopped before answering any of them.

That code and its README are still here, byte for byte, in [`notebooks/2024-original/`](notebooks/2024-original). A test fails if either ever changes. Reading the code again, I found three things this rebuild corrects:

| 2024 | Why it matters | 2026 |
| --- | --- | --- |
| The data file's source isn't recorded | Nobody else can rerun it, me included | A named source, a date and a fingerprint |
| Duplicate names are dropped before artists are counted | If the file holds one row per printing, a card printed five times by five artists keeps one, and the artist counts are wrong | Artists are counted per printing |
| Counts only | A count can't say whether Elves are green more often than chance would make them | Counts with lift (how many times more often than chance) and its interval |

Phase 1 answers the three questions first. Where I began is part of the story.

## 🚀 Try it

You need [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/OGobidike/TopDeck-MTG.git
cd TopDeck-MTG
uv sync
uv run pytest
uv run topdeck ground
```

`topdeck ground` checks that the 2024 files are untouched, counts the hand-written questions and checks each one against its rules.

## ✅ Tested

- ✅ **27 tests**, run by CI on every push and pull request
- ✅ **The 2024 files are pinned by their SHA-256 fingerprints.** No formatter may touch them, and Git may not rewrite their line endings; a test covers each
- ✅ **Every rule for a hand-written question is tested against the fault it exists to catch**: a missing question mark, a repeat, a gap in the numbering, a fragment
- ✅ **No test can reach the network.** A fixture fails any test that tries, so later phases can't spend money by accident
- ✅ **This README is tested too**: its test count and its phase table must match the repo and the blueprint
- ✅ `ruff check` and `ruff format --check` pass

## 🗂️ Repo map

| Path | What it holds |
| --- | --- |
| [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) | The plan the repo is built against |
| [`questions/hand_written.md`](questions/hand_written.md) | The questions I write by hand, before the graph's layout exists |
| [`src/topdeck/`](src/topdeck) | The package and the `topdeck` command |
| [`tests/`](tests) | The tests |
| [`notebooks/2024-original/`](notebooks/2024-original) | Where I began, unchanged |

## ⚖️ Limits

- **TopDeck measures a clean, shallow graph of game cards.** It won't prove the same gains on messy company documents.
- **Part of the result is known in advance.** Search with filters is in the contest so the graph gets no credit for what filters already do.
- **Models have read about Magic.** The plan tests for that memory with newer cards and with invented ones; it can't remove it.
- **Every hand label is mine.** I measure how often I agree with myself; nobody else checks me.

The blueprint lists the rest, and what was still unchecked when the plan was written.

## 🙏 Credits

- **The cards** will come from [Scryfall](https://scryfall.com)'s free bulk files. TopDeck uses card text and facts only, and no card images.
- **The idea** is inspired by Knowledge Augmented Generation ([arXiv 2409.13731](https://arxiv.org/abs/2409.13731)). TopDeck is not a copy of that paper's method.
- **My other projects** it builds on: [The Disease Division](https://github.com/OGobidike/disease-division) for the scoring, and [Morning Manna](https://github.com/OGobidike/Morning-Manna) for the stack.
- I build with an AI pair-programmer, and I review, test and run every change myself.

TopDeck is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

The code is under the [MIT License](LICENSE).
