# 🃏 TopDeck

**Questions about Magic: The Gathering cards, answered five ways, with every answer scored by code.**

Most assistants today answer by search: they fetch the few passages that sound most like the question and answer from those. That works for "what does Counterspell do?". It fails for "how many red Goblins cost two mana or less?", because counting needs every matching card, not the five that sound closest.

A knowledge graph stores each fact as a link: this card is red, this card is a Goblin, this card was printed in that set. A query over those links can count, filter and walk from fact to fact.

TopDeck builds both, puts three simpler systems beside them, and measures what each step up buys and what it costs.

I'm building it for two kinds of people:

- **Anyone deciding whether their assistant needs a graph.** The results will show which kinds of question it helps, which it doesn't, and what plain filters already reach.
- **Anyone learning to test AI systems.** Every score here will be rerun by one command.

## 🗺️ Where it stands

Nothing here answers a question yet. The plan is written, the ground is laid, and the cards are counted.

| Phase | What it ships | Status |
| --- | --- | --- |
| 0. Ground | The [blueprint](docs/BLUEPRINT.md), tooling, CI, the 2024 code set aside untouched, and [108 questions I chose](questions/chosen.md) before the graph had a layout | 🔨 Under way: the 108 are chosen |
| 1. The cards | The pinned card files, the rule for what counts as a card, the cards in PostgreSQL with every given link, and my three 2024 questions answered | 🔨 Under way: the files, the rule and the parser are in |
| 2. The questions | About 540 questions, most with an answer a query can prove | Planned |
| 3. Search | The model alone, search, and search with filters | Planned |
| 4. The graph route | A model that writes read-only queries, inside a fence | Planned |
| 5. Extraction | What cards do, pulled from rules text and scored against my labels | Planned |
| 6. The router | A system that picks a route for each question; the final scores | Planned |
| 7. Serving | An API, a Docker image and a page to ask questions | Planned |
| 8. The telling | The results, written up | Planned |

The [blueprint](docs/BLUEPRINT.md) holds the full plan: the cards, the graph, the questions, the five contenders, how every answer is scored, the cost and the limits.

## 🃏 The cards

Scryfall's file of unique cards holds **39,356** entries, and **32,495** of them count as cards here. The rest are things a player wouldn't call a card, and one Goblin token would change every Goblin count, so the rule comes before any other number.

A card counts when all three of these hold:

1. **It is a card,** not an art card, a token, an emblem, a plane, a scheme or a vanguard.
2. **At least one of its printings is on paper, in an ordinary set.** Every printing is checked, all 120,211 of them.
3. **The Vintage format knows it:** it is legal, restricted or banned there. Vintage allows the most cards of any format, so this leaves out only cards that no format accepts.

| Left out | Why |
| --- | --- |
| 2,411 | An art card |
| 1,500 | Printed only in joke sets |
| 1,020 | A token |
| 742 | Found only in digital Alchemy sets |
| 350 | Printed only as a keepsake |
| 249 | Accepted by no format (a test card, or not yet released) |
| 207 | A plane or phenomenon |
| 107 | A vanguard |
| 102 | A scheme |
| 89 | An emblem |
| 68 | Never printed on paper |
| 13 | Printed only in token sets |
| 3 | Printed only for Planechase |

**The rule I wrote first was wrong, and the data showed it.** Scryfall's file shows one printing of each card, and I judged each card by that printing alone. Where the printing shown was a digital one, the card was dropped: 1,226 real cards, Tolarian Academy among them. The rule now checks every printing, and a test holds it there.

Two more rules cover the awkward shapes:

- **A card with two faces is its front face.** Its own colours, types and power are the front's, and each face keeps its own. A split card is the exception: both halves count.
- **Power is a number only when it is a whole one.** Some cards have a power of `*`, so a question about the highest power leaves those out and says so.

The card files are pinned to Scryfall's files of 2026-11-21 by their SHA-256 fingerprints. `uv run topdeck cards count` applies the rule and checks every number above against [`results/cards.json`](results/cards.json).

## 🥊 The contest

Five systems answer the same questions, each one step up from the last, so every gain is measured against something simpler.

| Contender | How it answers |
| --- | --- |
| A. Closed book | The model alone, from memory |
| B. Search | Finds the closest cards by meaning and by keywords, then answers from those |
| C. Search with filters | The model also sets filters on colour, type and cost, and every match comes back |
| D. Graph | The model writes a read-only query over the graph and words the rows that come back |
| E. Router | Plans the steps and picks a route for each |

**The questions I care about most are the ones a web search answers badly.** I rated 132 drafts, and the ones I rated highest need judgement or a story (rules, deck advice, "what happened to"), turn on art and artists with a twist, or ask whether anything odd exists at all. Many can't be answered from card data, so a system earns credit there by saying so, or by citing an official ruling. The [108 I chose](questions/chosen.md) are fixed in the repo before any system runs.

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

`topdeck ground` checks that the 2024 files are untouched, counts the chosen questions and checks each one is well formed.

To count the cards yourself, fetch the two pinned files. The first command only says what it would download (106.8 MB, kept packed); the second downloads.

```bash
uv run topdeck cards fetch
uv run topdeck cards fetch --yes
uv run topdeck cards count
```

Scryfall replaces its files daily, so the pinned ones may no longer be there. If so, the fetch says so and stops; the recorded counts are still in `results/cards.json`.

## ✅ Tested

- ✅ **53 tests**, run by CI on every push and pull request
- ✅ **The 2024 files are pinned by their SHA-256 fingerprints.** No formatter may touch them, and Git may not rewrite their line endings; a test covers each
- ✅ **Every rule for a chosen question is tested against the fault it exists to catch**: a missing question mark, a repeat, a gap in the numbering, a fragment
- ✅ **The rule for what counts as a card is tested reason by reason,** on cards I invented, so no real card text sits in the tests
- ✅ **The card count is checked against its record:** one changed number fails the command
- ✅ **A download that isn't the pinned file is refused,** and nothing of it is kept
- ✅ **No test can reach the network.** A fixture fails any test that tries, so later phases can't spend money by accident
- ✅ **This README is tested too**: its test count, its phase table and its card numbers must match the repo, the blueprint and the record
- ✅ `ruff check` and `ruff format --check` pass

## 🗂️ Repo map

| Path | What it holds |
| --- | --- |
| [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) | The plan the repo is built against |
| [`questions/chosen.md`](questions/chosen.md) | The 108 questions I chose before the graph had a layout, and why |
| [`src/topdeck/`](src/topdeck) | The package and the `topdeck` command |
| [`results/cards.json`](results/cards.json) | The recorded card count, which one command reproduces |
| [`tests/`](tests) | The tests, and the invented cards they run on |
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
