"""The page that answers the 2024 questions, written from the recorded answers.

The page is never typed by hand: every number in it is read from
results/answers_2024.json, so the two cannot drift apart. A test checks that the page
in the repo is exactly what this module writes. Numbers are stored unrounded and
rounded once, here.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

ANSWERS_PAGE = Path("docs/2024-QUESTIONS.md")
COLOUR_ORDER = ("white", "blue", "black", "red", "green")


def percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def span(low: float, high: float, as_percent: bool = False) -> str:
    if as_percent:
        return f"{percent(low)} to {percent(high)}"
    return f"{low:.2f} to {high:.2f}"


def rank(value: int | None) -> str:
    """A rank, or plain words when there is none."""
    return str(value) if value is not None else "not ranked"


def _tie(row: dict, noun: str, all_noun: str, base: float) -> str:
    return (
        f"**{row['with_colour']:,} of {row['cards']:,}** {noun} are {row['colour']}: "
        f"{percent(row['share'])} ({span(row['share_low'], row['share_high'], True)}). "
        f"Of all {all_noun}, {percent(base)} are {row['colour']}, so the lift is "
        f"**{row['lift']:.2f}** ({span(row['lift_low'], row['lift_high'])})."
    )


def artist_headline(two: dict) -> str:
    """The artist finding in one sentence, the same on the page and in the README."""
    leader = two["by_printings"][0]
    plain = two["without_basic_lands"]["by_printings"][0]
    sentence = (
        f"{leader['artist']} has the most printings, {leader['printings']:,}, and "
        f"{leader['basic_lands']:,} of them are basic lands."
    )
    if plain["artist"] != leader["artist"]:
        without = leader["rank_without_basic_lands"]
        sentence += (
            f" Leave basic lands out and {plain['artist']} leads with {plain['printings']:,}, "
            + (
                f"while {leader['artist']} ranks {without}."
                if without is not None
                else f"while {leader['artist']} has no printings left."
            )
        )
    old = leader["rank_2024"]
    sentence += f" Counted the 2024 way, one printing per card, {leader['artist']} " + (
        f"ranks {old}." if old is not None else "has no card at all."
    )
    return sentence


def picture(name: str, alt: str, folder: str = "images") -> list[str]:
    """A chart that follows the reader's theme: the dark drawing on GitHub's dark page,
    the light one everywhere else. Both are drawn by `topdeck figures`."""
    return [
        "<picture>",
        f'  <source media="(prefers-color-scheme: dark)" srcset="{folder}/{name}-dark.png">',
        f'  <img alt="{escape(alt, quote=True)}" src="{folder}/{name}-light.png">',
        "</picture>",
    ]


def _subtypes_alt(three: dict) -> str:
    """The subtypes chart's finding in words, for a reader who can't see it."""
    rows = three["strongest"]
    if not rows:
        return "No subtype has enough cards to show a tie to one colour."
    whole = sorted((r for r in rows if r["share"] >= 1), key=lambda r: -r["cards"])
    low = min(r["share"] for r in rows)
    lead = ""
    if len(whole) >= 2:
        a, b = whole[0], whole[1]
        lead = (
            f"All {a['cards']} {a['subtype']} cards are {a['colour']} and all {b['cards']} "
            f"{b['subtype']} cards {b['colour']}; "
        )
    shares = sorted(three["colour_share"].values())
    return (
        f"{lead}these {len(rows)} subtypes are {low * 100:.0f}% to 100% one colour, "
        f"against {shares[0] * 100:.0f}% to {shares[-1] * 100:.0f}% of all cards."
    )


def render_answers(answers: dict) -> str:
    one = answers["elves_and_goblins"]
    two = answers["artists"]
    three = answers["subtypes_in_colours"]
    elf, goblin = one["elves_green"], one["goblins_red"]
    tightest = max(one["commonest_subtypes"], key=lambda row: row["lift"])
    loosest = min(one["commonest_subtypes"], key=lambda row: row["lift"])
    old_leader = two["the_2024_way"][0]
    top = two["top_one_percent"]

    lines = [
        "# 🧝 The 2024 questions, answered",
        "",
        "In 2024 I started TopDeck as a notebook with three questions about Magic: The "
        "Gathering cards. It printed four counts and stopped before answering any of them. "
        f"This page answers all three from TopDeck's graph, built from Scryfall's card files "
        f"of {answers['snapshot']}.",
        "",
        "`uv run topdeck answers` works every number on this page out again and checks it "
        "against [`results/answers_2024.json`](../results/answers_2024.json). "
        "`uv run topdeck figures` draws the charts from the same record.",
        "",
        "## 📏 How to read the numbers",
        "",
        f"- **What counts as a card.** {three['cards']:,} cards count here; the "
        "[README](../README.md#-the-cards) gives the rule and what it leaves out.",
        "- **A card is its front face.** A card with two faces is counted by the colours "
        "and types of its front. A split card is both halves.",
        '- **"Green" means green is among the card\'s colours.** A green and white Elf '
        "counts as green, and as white.",
        "",
        "### Words used here",
        "",
        "| Word | What it means |",
        "| --- | --- |",
        "| Printing | One real printing of a card: on paper, in an ordinary set. Promos, "
        "Secret Lair-style box sets, masterpieces and basic lands all count. A card printed "
        "in five sets has five printings |",
        "| Subtype | The words after the dash on a card's type line, such as Elf or Goblin. "
        "Not every subtype is a creature kind: Aura, Saga and Equipment are subtypes too |",
        "| Share | Of the cards in a group, the part that has a colour |",
        "| Lift | A group's share divided by the share among all the cards compared. A lift "
        "of 3 means the colour turns up three times as often in the group |",
        "| 95% interval | The range in brackets. A share's is a Wilson interval. A lift's is "
        "the share's interval divided by the share among all the cards compared; that base "
        "is measured over thousands of cards, so its own uncertainty is small and left out |",
        "",
        "## 1. Are Elves green and Goblins red?",
        "",
        "**Yes, both, and strongly.**",
        "",
        "- "
        + _tie(
            elf, "Elf creatures", f"{one['creatures']:,} creatures", one["colour_share"]["green"]
        ),
        "- " + _tie(goblin, "Goblin creatures", "creatures", one["colour_share"]["red"]),
        "",
        f"Here are the {len(one['commonest_subtypes'])} commonest creature subtypes, each "
        "with the colour it is most tied to, ordered by lift as in the chart. The lift "
        "compares each with all the creatures.",
        "",
        *picture(
            "lift-by-subtype",
            f"Elves are green {elf['lift']:.1f} times as often as creatures in general, and "
            f"Goblins red {goblin['lift']:.1f} times as often. A dot for each of the "
            f"{len(one['commonest_subtypes'])} commonest creature subtypes.",
        ),
        "",
        "| Subtype | Creatures | Colour | Share | Lift |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in sorted(one["commonest_subtypes"], key=lambda row: -row["lift"]):
        lines.append(
            f"| {row['subtype']} | {row['cards']:,} | {row['colour'].capitalize()} | "
            f"{percent(row['share'])} | {row['lift']:.2f} "
            f"({span(row['lift_low'], row['lift_high'])}) |"
        )
    lines += [
        "",
        f"The tightest tie in the table is {tightest['subtype']} to {tightest['colour']} "
        f"(lift {tightest['lift']:.2f}). The loosest is {loosest['subtype']} to "
        f"{loosest['colour']} (lift {loosest['lift']:.2f}).",
        "",
        "## 2. Do some artists appear far more than others?",
        "",
        f"**Yes.** {two['artists']:,} artists are credited on {two['printings']:,} printings. "
        f"Half of them have {two['median_printings']} printings or fewer, while the top 1% "
        f"({top['artists']} artists) hold **{percent(top['share'])}** of all printings.",
        "",
        f"**Basic lands shape the top of this list.** {artist_headline(two)} Of all "
        f"{two['printings']:,} printings, {two['basic_land_printings']:,} are basic lands, "
        "reprinted in nearly every set, so an artist who painted many of them climbs the "
        "count quickly.",
        "",
        *picture(
            "artists-basic-lands",
            f"The top artists ranked with basic lands and without them: "
            f"{two['without_basic_lands']['by_printings'][0]['artist']} rises to first and "
            f"{two['by_printings'][0]['artist']} falls to "
            f"{rank(two['by_printings'][0]['rank_without_basic_lands'])}.",
        ),
        "",
        "| Artist | Printings | Of them basic lands | Different cards | "
        "Rank without basic lands | Rank the 2024 way |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in two["by_printings"][: two["top"]]:
        lines.append(
            f"| {row['artist']} | {row['printings']:,} | {row['basic_lands']:,} | "
            f"{row['different_cards']:,} | {rank(row['rank_without_basic_lands'])} | "
            f"{rank(row['rank_2024'])} |"
        )
    lines += [
        "",
        f"With basic lands left out, {two['without_basic_lands']['printings']:,} printings "
        "remain, and the list starts like this:",
        "",
        "| Artist | Printings, no basic lands | Different cards | Rank with basic lands |",
        "| --- | --- | --- | --- |",
    ]
    for row in two["without_basic_lands"]["by_printings"][: two["top"]]:
        lines.append(
            f"| {row['artist']} | {row['printings']:,} | {row['different_cards']:,} | "
            f"{rank(row['rank_with_basic_lands'])} |"
        )
    lines += [
        "",
        "**The 2024 way.** My notebook dropped duplicate card names before it counted "
        "artists, which keeps one printing of each card. I replay that here by keeping each "
        "card's earliest real printing. Counted that way, "
        f"{old_leader['artist']} leads with {old_leader['cards']:,} cards. An artist whose "
        "work is reprinted often, basic lands most of all, falls down this list, because "
        "every reprint after the first is dropped.",
        "",
        "| Artist, the 2024 way | Cards, one printing each | Rank by printings |",
        "| --- | --- | --- |",
    ]
    for row in two["the_2024_way"]:
        lines.append(f"| {row['artist']} | {row['cards']:,} | {rank(row['rank_by_printings'])} |")
    lines += [
        "",
        "An artist is counted as credited on the card, so two artists who share a credit "
        "are counted as one name.",
        "",
        "## 3. Which subtypes hide inside which colours?",
        "",
        f"Of the {three['subtypes_considered']} subtypes with at least 30 cards, these "
        f"{len(three['strongest'])} are tied most strongly to one colour. This chart and "
        f"table compare against all {three['cards']:,} cards, not only creatures, so their "
        "subtypes include kinds that aren't creatures, such as Auras and Sagas.",
        "",
        *picture("subtypes-by-colour", _subtypes_alt(three)),
        "",
        "| Subtype | Cards | Colour | Share | Lift |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in three["strongest"]:
        lines.append(
            f"| {row['subtype']} | {row['cards']:,} | {row['colour'].capitalize()} | "
            f"{percent(row['share'])} ({span(row['share_low'], row['share_high'], True)}) | "
            f"{row['lift']:.2f} ({span(row['lift_low'], row['lift_high'])}) |"
        )
    lines += [
        "",
        "These rows were picked for being the strongest, so their lifts lean a little high: "
        "the luckiest of many pairs always looks better than it is.",
        "",
        "At the other end, these subtypes are spread most evenly over the five colours. "
        "This table counts one-coloured cards only, so each card counts once and a row's "
        f"shares add up to 100%. Of the subtypes with at least 30 one-coloured cards "
        f"({three['one_coloured_subtypes_considered']}), these are the most even. An "
        "evenness of 1 is a perfectly even spread.",
        "",
        "| Subtype | One-coloured cards | Evenness | White | Blue | Black | Red | Green |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in three["most_even"]:
        shares = " | ".join(percent(row["share"][colour]) for colour in COLOUR_ORDER)
        lines.append(
            f"| {row['subtype']} | {row['one_coloured_cards']:,} | {row['evenness']:.3f} | "
            f"{shares} |"
        )
    lines += [
        "",
        "## ⚖️ Limits",
        "",
        "- These are counts of cards printed, not of cards played. A colour's share says "
        "nothing about how strong its cards are.",
        "- The cards are those of one day. A new set changes every number a little.",
        "- The 2024 way is a replay, not the old notebook run again: I don't know which row "
        "the old data file kept for each card, so the earliest real printing stands in.",
        "",
    ]
    return "\n".join(lines)
