"""Every chart in the README and the 2024 page, drawn twice: for GitHub's light page and
for its dark one.

The pages pick the version that matches the reader's theme with a <picture> element, and
each background is GitHub's own page colour in that theme. Every chart is drawn from the
records in results/ alone, never from the database, so anyone can redraw them without
building the graph: `topdeck figures`.

The look is one system across the set:

- The title states the finding, a standfirst under it says how to read the chart, and a
  short credit ends it: "Chart: TopDeck".
- Blue marks official facts. Orange marks community labels, and nothing else: no other
  mark in any chart is orange. Community marks are hatched as well, so the split never
  rests on colour alone.
- Magic's white and black are drawn as a fill with a grey ring, the same in both themes;
  every coloured dot is also named in words.
- No text is smaller than 12 points at the full 1,600 pixels: about 17 pixels in GitHub's
  column, about 880 pixels wide. On a phone the charts shrink further, and a tap opens
  them full size.

Every chart is laid out on a pixel canvas: one axes over the whole figure, x from 0 to
1600 and y from 0 downwards, so text and marks sit exactly where they are placed. A lint
pass then checks that no text leaves the frame or runs into other text.

The drawing is the same on every machine: the font is DejaVu Sans, read from the file
matplotlib carries with it, the PNG files carry no version stamp, and nothing is random.
Redrawn from the same records, every image comes out byte for byte the same. The images
are drawn into a scratch folder first and moved into place only when every one of them
has passed the layout check, so a broken layout never overwrites a good chart.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch, Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402

from topdeck.answers import MIN_CARDS  # noqa: E402
from topdeck.graph import COMMUNITY_LINK_TABLES, GIVEN_LINK_TABLES  # noqa: E402

OUT = Path("docs/images")
RESULTS = Path("results")
DPI = 200
WIDTH = 1600  # px; the README column is about 880 px wide, so this stays sharp
PX_PER_PT = DPI / 72
MIN_PT = 12  # no text smaller than 12 pt at 1600 px, about 17 px in GitHub's column
MARGIN = 64
CREDIT = "Chart: TopDeck."

_FONTS = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
REGULAR = _FONTS / "DejaVuSans.ttf"
BOLD = _FONTS / "DejaVuSans-Bold.ttf"

# Magic's white and black: a fill with a grey ring, identical on both pages, so a dot
# never changes its look with the theme and never reads as "missing".
RING = "#8b8a84"
WHITE_AND_BLACK = {"white": ("#f4f1e4", RING), "black": ("#3b4048", RING)}

THEMES = {
    "light": {
        "surface": "#ffffff",  # GitHub's light page
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#6e6d68",
        "grid": "#e8e7e1",
        "tint": "#f6f8fa",
        "highlight": "#e3e9f0",  # the rows a chart calls out: at least 1.15:1 on the page
        "track": "#eeeeea",
        "context": "#b9b8ae",
        "context_strong": "#8d8c84",
        "official": "#2a78d6",
        "official_tint": "#eaf2fc",
        "community": "#eb6834",
        "community_tint": "#fdf0ea",
        "community_deep": "#b8461b",
        "segment": ["#8d8c84", "#a8a79f", "#c3c2b7", "#dcdbd4"],
        "mana": {"blue": "#2a78d6", "red": "#e34948", "green": "#008300", **WHITE_AND_BLACK},
    },
    "dark": {
        "surface": "#0d1117",  # GitHub's dark page
        "ink": "#f0efec",
        "ink2": "#c3c2b7",
        "muted": "#9c9b94",
        "grid": "#21262d",
        "tint": "#161b22",
        "highlight": "#222a35",
        "track": "#21262d",
        "context": "#4b525c",
        "context_strong": "#7d848e",
        "official": "#3987e5",
        "official_tint": "#13233a",
        "community": "#d95926",
        "community_tint": "#2a1a12",
        "community_deep": "#f0a07e",
        "segment": ["#7d848e", "#5f6670", "#4b525c", "#363c45"],
        "mana": {"blue": "#3987e5", "red": "#e66767", "green": "#0ca30c", **WHITE_AND_BLACK},
    },
}
COLOURS = ("white", "blue", "black", "red", "green")

# The charts, by the name of their files: NAME-light.png and NAME-dark.png.
NAMES = (
    "what-topdeck-knows",
    "coverage",
    "lift-by-subtype",
    "artists-basic-lands",
    "subtypes-by-colour",
)

# One definition of an official link, shared by the hero and the coverage chart.
OFFICIAL_LINK = (
    "An official link is a fact the official data states outright: a card's colour, "
    "colour identity, type, subtype, supertype, keyword or format, a face's own, or a "
    "printing's artist and picture. A picture's id is Scryfall's own grouping of the "
    "printings that share one piece of art."
)
# How the charts speak of the tags, the same in every chart, the README and the code.
UNCHECKED = (
    "Wizards does not check them, and TopDeck has not found how Scryfall reviews them. "
    "No tag, checked or not, is ever an answer key."
)


# --------------------------------------------------------------------------- words


def n(value: float) -> str:
    """12345 -> '12,345'."""
    return f"{round(value):,}"


def pct(share: float, places: int = 1) -> str:
    """0.6022 -> '60.2%'; a whole share drops its decimals: '100%'."""
    if share in (0.0, 1.0):
        return f"{share:.0%}"
    return f"{share * 100:.{places}f}%"


def long_date(iso: str) -> str:
    """'2026-11-21' -> '21 November 2026', with no-break spaces so it never splits."""
    day = date.fromisoformat(iso)
    return f"{day.day} {day.strftime('%B')} {day.year}"


# --------------------------------------------------------------------------- the canvas


class Canvas:
    """A WIDTH x height pixel canvas, origin top-left, y growing downwards."""

    def __init__(self, t: dict, height: int = 2000, width: int = WIDTH):
        self.t = t
        self.w, self.h = width, height
        self.fig = plt.figure(figsize=(width / DPI, height / DPI), dpi=DPI)
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(0, width)
        self.ax.set_ylim(height, 0)
        self.ax.axis("off")

    # ----------------------------------------------------------------- text
    def font(self, size: float, weight: str = "normal", italic: bool = False):
        if size < MIN_PT:
            raise ValueError(f"text of {size} pt is below the {MIN_PT} pt floor")
        properties = FontProperties(fname=BOLD if weight == "bold" else REGULAR, size=size)
        if italic:
            properties = FontProperties(fname=_FONTS / "DejaVuSans-Oblique.ttf", size=size)
        return properties

    def text(
        self,
        x,
        y,
        s,
        size=12,
        color=None,
        weight="normal",
        ha="left",
        va="baseline",
        italic=False,
        **kw,
    ):
        return self.ax.text(
            x,
            y,
            s,
            fontproperties=self.font(size, weight, italic),
            color=color or self.t["ink"],
            ha=ha,
            va=va,
            **kw,
        )

    def extent(self, artist) -> tuple[float, float, float, float]:
        """The box a drawn artist covers, in canvas pixels (y downwards)."""
        box = artist.get_window_extent(self.fig.canvas.get_renderer())
        return box.x0, self.h - box.y1, box.x1, self.h - box.y0

    def width_of(self, s: str, size: float = 12, weight: str = "normal") -> float:
        probe = self.text(0, 0, s, size=size, weight=weight)
        x0, _, x1, _ = self.extent(probe)
        probe.remove()
        return x1 - x0

    def wrap(self, s: str, max_px: float, size: float = 12, weight: str = "normal") -> list:
        """Greedy word wrap to a measured width; an explicit newline forces a break."""
        lines = []
        for chunk in s.split("\n"):
            line = ""
            for word in chunk.split(" "):
                trial = f"{line} {word}".strip()
                if line and self.width_of(trial, size, weight) > max_px:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
        return lines

    def para(
        self, x, y, s, max_px, size=12, color=None, weight="normal", leading=1.38, ha="left"
    ) -> float:
        """A wrapped paragraph; y is the first baseline. Returns the last baseline."""
        lines = self.wrap(s, max_px, size, weight)
        step = size * PX_PER_PT * leading
        for i, line in enumerate(lines):
            self.text(x, y + i * step, line, size=size, color=color, weight=weight, ha=ha)
        return y + (len(lines) - 1) * step

    # ----------------------------------------------------------------- marks
    def line(self, xs, ys, color, lw_px=2.0, zorder=1, **kw):
        return self.ax.plot(
            xs,
            ys,
            color=color,
            lw=lw_px / PX_PER_PT,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=zorder,
            **kw,
        )[0]

    def hbar(self, x0, y_mid, length, height, color, hatch=None, hatch_color=None, zorder=2):
        """A horizontal bar, square at its start and rounded (4 px) at the data end."""
        if length <= 0:
            return None
        r = min(4, length / 2, height / 2)
        y0, y1 = y_mid - height / 2, y_mid + height / 2
        x1 = x0 + length
        verts = [
            (x0, y0),
            (x1 - r, y0),
            (x1, y0),
            (x1, y0 + r),
            (x1, y1 - r),
            (x1, y1),
            (x1 - r, y1),
            (x0, y1),
            (x0, y0),
        ]
        codes = [
            MPath.MOVETO,
            MPath.LINETO,
            MPath.CURVE3,
            MPath.CURVE3,
            MPath.LINETO,
            MPath.CURVE3,
            MPath.CURVE3,
            MPath.LINETO,
            MPath.CLOSEPOLY,
        ]
        patch = PathPatch(MPath(verts, codes), facecolor=color, lw=0, zorder=zorder)
        if hatch:
            patch.set_hatch(hatch)
            patch.set_edgecolor(hatch_color or color)
        self.ax.add_patch(patch)
        return patch

    def box(self, x, y, w, h, face, edge=None, lw_px=0.0, radius=8, zorder=1, hatch=None):
        patch = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=face,
            edgecolor=edge or "none",
            lw=lw_px / PX_PER_PT,
            zorder=zorder,
            hatch=hatch,
        )
        self.ax.add_patch(patch)
        return patch

    def rect(self, x, y, w, h, face, zorder=1):
        patch = Rectangle((x, y), w, h, facecolor=face, lw=0, zorder=zorder)
        self.ax.add_patch(patch)
        return patch

    def dot(self, x, y, r, face, ring=None, ring_px=2.5, gap_px=2.5, zorder=4):
        """A dot with a gap of page colour around it; `ring` draws a visible outline."""
        if gap_px:
            self.ax.add_patch(
                Circle(
                    (x, y),
                    r + gap_px + (ring_px if ring else 0),
                    facecolor=self.t["surface"],
                    lw=0,
                    zorder=zorder,
                )
            )
        if ring:
            self.ax.add_patch(
                Circle((x, y), r + ring_px, facecolor=ring, lw=0, zorder=zorder + 0.1)
            )
        self.ax.add_patch(Circle((x, y), r, facecolor=face, lw=0, zorder=zorder + 0.2))

    def mana_dot(self, x, y, colour, r=9.5, zorder=4):
        face = self.t["mana"][colour]
        if isinstance(face, tuple):
            self.dot(x, y, r - 1.5, face[0], ring=face[1], ring_px=3, zorder=zorder)
        else:
            self.dot(x, y, r, face, zorder=zorder)

    def hatched_dot(self, x, y, r, zorder=5):
        """A community node: hatched orange in a solid orange ring."""
        t = self.t
        self.ax.add_patch(Circle((x, y), r + 3, facecolor=t["surface"], lw=0, zorder=zorder))
        circle = Circle(
            (x, y),
            r,
            facecolor=t["community_tint"],
            edgecolor=t["community"],
            lw=2.4 / PX_PER_PT,
            hatch="////",
            zorder=zorder + 0.1,
        )
        self.ax.add_patch(circle)

    def curve(self, x0, y0, x1, y1, color, lw_px=2.0, bend=0.45, zorder=1):
        """A smooth horizontal S-curve from (x0, y0) to (x1, y1)."""
        dx = (x1 - x0) * bend
        path = MPath(
            [(x0, y0), (x0 + dx, y0), (x1 - dx, y1), (x1, y1)],
            [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4],
        )
        patch = PathPatch(
            path,
            facecolor="none",
            edgecolor=color,
            lw=lw_px / PX_PER_PT,
            capstyle="round",
            zorder=zorder,
        )
        self.ax.add_patch(patch)

    def arrow(self, x, y_from, y_to, color, zorder=0.5):
        """A straight vertical arrow, pointing down or up, its tip at y_to."""
        s = 10 if y_to > y_from else -10
        self.line([x, x], [y_from, y_to - s * 0.8], color, lw_px=2.5, zorder=zorder)
        tip = MPath(
            [(x, y_to), (x - abs(s) * 0.6, y_to - s), (x + abs(s) * 0.6, y_to - s), (x, y_to)],
            [MPath.MOVETO, MPath.LINETO, MPath.LINETO, MPath.CLOSEPOLY],
        )
        self.ax.add_patch(PathPatch(tip, facecolor=color, lw=0, zorder=zorder + 0.1))

    def key_square(self, x, y_mid, kind, size=20):
        """The legend mark: solid blue for official, hatched orange for community."""
        t = self.t
        if kind == "official":
            self.box(x, y_mid - size / 2, size, size, t["official"], radius=3, zorder=3)
        else:
            self.box(
                x,
                y_mid - size / 2,
                size,
                size,
                t["community_tint"],
                edge=t["community"],
                lw_px=2,
                radius=3,
                zorder=3,
                hatch="////",
            )

    def meter(self, x, y_mid, length, height, share, kind):
        """A share of a whole: a track, and a bar solid for official, hatched for community."""
        t = self.t
        self.hbar(x, y_mid, length, height, t["track"], zorder=1)
        if kind == "official":
            self.hbar(x, y_mid, length * share, height, t["official"])
        else:
            self.hbar(
                x,
                y_mid,
                length * share,
                height,
                t["community"],
                hatch="////",
                hatch_color=t["community_deep"],
            )

    # ----------------------------------------------------------------- frame
    def header(self, title, standfirst, top=58) -> float:
        """The title (the finding) and a standfirst. Returns the y below the block."""
        max_px = self.w - 2 * MARGIN
        y = top + 19 * PX_PER_PT * 0.78
        y = self.para(MARGIN, y, title, max_px, size=19, weight="bold", leading=1.25)
        y += 13 * PX_PER_PT * 1.8
        y = self.para(MARGIN, y, standfirst, max_px, size=13, color=self.t["ink2"], leading=1.42)
        return y + 13 * PX_PER_PT * 0.6

    def finish(self, bottom, notes, gap=64):
        """Fit the canvas to its content and write the notes and the credit under it."""
        # The credit is wrapped as one word, and never sits alone on the last line. The
        # sentence before it comes down to keep it company, so no line ends on half a
        # sentence such as "Card files of"; if that sentence started on an earlier line,
        # only the word before the credit comes down.
        credit = CREDIT.replace(" ", "\u00a0")
        max_px = self.w - 2 * MARGIN
        lines = self.wrap(f"{notes} {credit}".strip(), max_px, 12)
        if len(lines) > 1 and lines[-1] == credit:
            head, dot, tail = lines[-2].rpartition(". ")
            if dot and self.width_of(f"{tail} {credit}", 12) <= max_px:
                lines[-2:] = [head + ".", f"{tail} {credit}"]
            else:
                *rest, last_word = lines[-2].split(" ")
                lines[-2:] = [" ".join(rest), f"{last_word} {credit}"]
        step = 12 * PX_PER_PT * 1.38
        first = bottom + gap
        height = int(round(first + (len(lines) - 1) * step + 48))
        self.h = height
        self.fig.set_size_inches(self.w / DPI, height / DPI)
        self.ax.set_ylim(height, 0)
        for i, line in enumerate(lines):
            self.text(MARGIN, first + i * step, line, size=12, color=self.t["muted"])

    def lint(self) -> list[str]:
        """Text that leaves the frame or runs into other text. Layout, not art."""
        renderer = self.fig.canvas.get_renderer()
        boxes = []
        for artist in self.ax.texts:
            if not artist.get_text().strip():
                continue
            box = artist.get_window_extent(renderer)
            # A font's box includes its line leading; trim it so stacked lines pass.
            trim = 0.16 * box.height / (artist.get_text().count("\n") + 1)
            boxes.append((artist.get_text()[:40], box.x0, box.y0 + trim, box.x1, box.y1 - trim))
        problems = []
        for s, x0, y0, x1, y1 in boxes:
            if x0 < 32 or x1 > self.w - 32 or y0 < 4 or y1 > self.h - 4:
                problems.append(f"out of the frame: {s!r}")
        for i, (s1, ax0, ay0, ax1, ay1) in enumerate(boxes):
            for s2, bx0, by0, bx1, by1 in boxes[i + 1 :]:
                if ax0 < bx1 - 2 and bx0 < ax1 - 2 and ay0 < by1 - 2 and by0 < ay1 - 2:
                    problems.append(f"text on text: {s1!r} and {s2!r}")
        return problems


def stack(cv: Canvas, x, y_first, items, max_px) -> float:
    """Centred lines, each wrapped to the column: (text, size, weight, colour, space
    before). Returns the last baseline."""
    y = y_first
    for i, (s, size, weight, color, before) in enumerate(items):
        y += before if i else 0
        y = cv.para(
            x, y, s, max_px, size=size, weight=weight, color=color, ha="center", leading=1.25
        )
    return y


# --------------------------------------------------------------------------- the records


# What each chart reads from each record. A record without one of these is refused with
# its name, before anything is drawn.
NEEDED = {
    "cards": ("snapshot", "entries", "cards", "printings", "left_out"),
    "graph": (
        "sources_snapshot",
        "tables",
        "coverage",
        "files_read",
        "skipped",
        "methods",
        "unlinked_tags",
    ),
    "answers_2024": ("snapshot", "elves_and_goblins", "artists", "subtypes_in_colours"),
}


def read_records(root: Path = Path(".")) -> dict:
    """The three records the charts are drawn from, checked against one another."""
    folder = root / RESULTS
    records = {}
    for name, keys in NEEDED.items():
        path = RESULTS / f"{name}.json"
        try:
            record = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        except ValueError as error:
            raise ValueError(f"{path} is not valid JSON: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"{path} is not the shape its command writes")
        for key in keys:
            if key not in record:
                raise ValueError(f"{path} has no '{key}': record it again with its command")
        records[name] = record
    try:
        problems = cross_check(records)
    except (KeyError, TypeError, AttributeError, ZeroDivisionError) as error:
        raise ValueError(f"the records are not the shape the charts read: {error!r}") from error
    if problems:
        raise ValueError("the records disagree: " + "; ".join(problems))
    return records


def official_links(tables: dict) -> int:
    return sum(tables[table] for table in GIVEN_LINK_TABLES)


def cross_check(records: dict) -> list[str]:
    """Every sum the charts rely on, checked before anything is drawn."""
    cards, graph, answers = records["cards"], records["graph"], records["answers_2024"]
    tables, read, skipped = graph["tables"], graph["files_read"], graph["skipped"]
    problems = []

    def same(what, a, b):
        if a != b:
            problems.append(f"{what}: {a!r} against {b!r}")

    same("cards left out", cards["entries"] - sum(cards["left_out"].values()), cards["cards"])
    same("cards in the graph", tables["cards"], cards["cards"])
    same("rulings read", read["rulings"], tables["rulings"] + sum(skipped["rulings"].values()))
    same("rulings by method", sum(graph["methods"]["rulings"].values()), tables["rulings"])
    same(
        "Oracle Tag links read",
        read["oracle tag links"],
        tables["card_oracle_tag"] + sum(skipped["oracle tag links"].values()),
    )
    same(
        "Art Tag links read",
        read["art tag links"],
        tables["illustration_art_tag"] + sum(skipped["art tag links"].values()),
    )
    for source, reached in graph["coverage"].items():
        if not 0 <= reached <= cards["cards"]:
            problems.append(f"coverage of {source}: {reached} of {cards['cards']}")
    if not cards["cards"] or not tables["rulings"]:
        problems.append("a record counts no cards or no rulings")
    artists = answers["artists"]
    same("printings with an artist", artists["printings"], tables["printing_artist"])
    without = {row["artist"]: row for row in artists["without_basic_lands"]["by_printings"]}
    for row in artists["by_printings"]:
        if row["artist"] in without:
            same(
                f"{row['artist']} without basic lands",
                row["printings"] - row["basic_lands"],
                without[row["artist"]]["printings"],
            )
            same(
                f"{row['artist']} with basic lands",
                row["printings"],
                without[row["artist"]]["printings_with_basic_lands"],
            )
    return problems


# --------------------------------------------------------------------------- A. the hero

SHORT_REASONS = {
    "an art card": "art cards",
    "printed only in joke sets": "joke-set cards",
    "a token": "tokens",
}


def what_topdeck_knows(records: dict) -> Callable[[dict], Canvas]:
    """Five files, one rule, one graph, with official and community kept apart."""
    cards, graph = records["cards"], records["graph"]
    tables, read, reach = graph["tables"], graph["files_read"], graph["coverage"]
    total = cards["cards"]
    order = ["Oracle Cards", "Default Cards", "Rulings", "Oracle Tags", "Art Tags"]
    kind = dict.fromkeys(order[:3], "official") | dict.fromkeys(order[3:], "community")
    # Each file in plain words, with Scryfall's name for it under that when they differ.
    plain = {
        "Oracle Cards": ("Every card", "Oracle Cards"),
        "Default Cards": ("Every printing", "Default Cards"),
        "Rulings": ("Every ruling", "Rulings"),
        "Oracle Tags": ("Card labels", "Oracle Tags"),
        "Art Tags": ("Picture labels", "Art Tags"),
    }
    tiles = {
        "Oracle Cards": (cards["entries"], "entries", "tokens included"),
        "Default Cards": (cards["printings"], "printings", "every printing"),
        "Rulings": (
            read["rulings"],
            "rulings",
            f"{n(read['rulings written by Scryfall'])} written by Scryfall's staff",
        ),
        "Oracle Tags": (read["oracle tag links"], "tag links", f"{n(read['oracle tags'])} tags"),
        "Art Tags": (read["art tag links"], "tag links", f"{n(read['art tags'])} tags"),
    }
    unlinked = graph["unlinked_tags"]
    community = sum(tables[table] for table in COMMUNITY_LINK_TABLES)
    tag_links = tables["card_oracle_tag"] + tables["illustration_art_tag"]
    between_tags = community - tag_links
    kept = {
        "Oracle Cards": (total, cards["entries"], "count as cards"),
        "Default Cards": (tables["printings"], cards["printings"], "printings kept"),
        "Rulings": (tables["rulings"], read["rulings"], "rulings kept"),
        "Oracle Tags": (tables["card_oracle_tag"], read["oracle tag links"], "tag links kept"),
        "Art Tags": (tables["illustration_art_tag"], read["art tag links"], "tag links kept"),
    }
    reasons = sorted(cards["left_out"].items(), key=lambda item: -item[1])
    named = [(SHORT_REASONS[r], v) for r, v in reasons if r in SHORT_REASONS]
    others = [v for r, v in reasons if r not in SHORT_REASONS]
    left_out = cards["entries"] - total
    links = official_links(tables)

    def draw(t: dict) -> Canvas:
        cv = Canvas(t, height=2600)
        y = cv.header(
            f"Everything TopDeck knows hangs on the {n(total)} cards that count",
            f"Of Scryfall's {n(cards['entries'])} entries, one rule keeps {n(total)} as cards. "
            "Three files are Wizards' card data, as Scryfall serves it; two are labels that "
            "volunteers add on Scryfall Tagger. Every printing and ruling in the graph, and every "
            "tag on a card or a picture, leads back to one of those cards.",
        )
        left, right = MARGIN, cv.w - MARGIN
        g_in, g_mid = 14, 40
        col_w = (right - left - 3 * g_in - g_mid) / 5
        x0, x = {}, left
        for i, name in enumerate(order):
            x0[name] = x
            nxt = order[i + 1] if i < 4 else None
            x += col_w + (g_mid if nxt and kind[nxt] != kind[name] else g_in)
        cx = {name: x0[name] + col_w / 2 for name in order}
        hue = {name: t[kind[name]] for name in order}
        inner = col_w - 24

        # Group headings.
        y_group = y + 70
        for k, label, who in (
            ("official", "OFFICIAL", "Wizards, as Scryfall serves it"),
            ("community", "COMMUNITY", "Scryfall Tagger"),
        ):
            members = [name for name in order if kind[name] == k]
            gx0, gx1 = x0[members[0]], x0[members[-1]] + col_w
            cv.key_square(gx0, y_group - 9, k)
            head = cv.text(gx0 + 30, y_group, label, size=12.5, weight="bold")
            cv.text(cv.extent(head)[2] + 12, y_group, who, size=12.5, color=t["ink2"])
            cv.line([gx0, gx1], [y_group + 20, y_group + 20], t[k], lw_px=2)

        # 1. The files.
        tile_top = y_group + 48
        tile_h = 352
        for name in order:
            xa, c = x0[name], cx[name]
            if kind[name] == "official":
                cv.box(xa, tile_top, col_w, tile_h, t["official_tint"], radius=12)
                cv.box(xa, tile_top, col_w, 8, t["official"], radius=4, zorder=1.2)
            else:
                cv.box(
                    xa, tile_top, col_w, tile_h, t["surface"], edge=hue[name], lw_px=2, radius=12
                )
                cv.box(
                    xa + 1,
                    tile_top + 1,
                    col_w - 2,
                    14,
                    t["community_tint"],
                    radius=4,
                    zorder=1.2,
                    edge=t["community"],
                    hatch="////",
                )
            big, unit, detail = tiles[name]
            title, subtitle = plain[name]
            stack(
                cv,
                c,
                tile_top + 62,
                [
                    (title, 12, "bold", t["ink"], 0),
                    (subtitle, 12, "normal", t["ink2"], 40),
                    (n(big), 19, "bold", t["ink"], 70),
                    (unit, 13, "normal", t["ink"], 42),
                    (detail, 12, "normal", t["ink2"], 44),
                ],
                col_w - 10,
            )

        # 2. The rule. The band grows to hold its caption.
        rule_w = cv.width_of("THE RULE", 12, "bold")
        rule_text = (
            "A card counts when it is a card, has a printing on paper in an ordinary set, and "
            "the Vintage format knows it. Only links that touch a card that counts are loaded. "
            "Every tag is kept so the tag tree stays whole, though "
            f"{n(unlinked['oracle tags'])} Oracle Tags and {n(unlinked['art tags'])} Art Tags "
            "link to nothing that counts."
        )
        rule_px = right - left - rule_w - 36
        rule_lines = len(cv.wrap(rule_text, rule_px, 12))
        band_top = tile_top + tile_h + 72
        band_h = 306 + (rule_lines - 1) * 12 * PX_PER_PT * 1.38 + 40
        cv.box(left - 12, band_top, right - left + 24, band_h, t["tint"], radius=16, zorder=0.2)
        for name in order:
            have, of, label = kept[name]
            c = cx[name]
            cv.text(c, band_top + 66, n(have), size=18, weight="bold", ha="center")
            cv.text(c, band_top + 108, label, size=12.5, color=t["ink"], ha="center")
            cv.meter(c - inner / 2, band_top + 146, inner, 16, have / of, kind[name])
            cv.text(
                c, band_top + 196, f"keeps {have / of:.0%}", size=12, color=t["ink2"], ha="center"
            )
            cv.text(
                c, band_top + 236, f"{n(of - have)} left out", size=12, color=t["ink2"], ha="center"
            )
        caption_y = band_top + 306
        cv.text(left + 12, caption_y, "THE RULE", size=12, weight="bold", color=t["ink2"])
        cv.para(left + rule_w + 26, caption_y, rule_text, rule_px, size=12, color=t["ink2"])

        # 3. The graph: a hub, with everything else hanging off it.
        spine_y = band_top + band_h + 92
        for name in order:
            cv.arrow(cx[name], tile_top + tile_h + 8, band_top - 6, hue[name])
            cv.arrow(
                cx[name],
                band_top + band_h + 8,
                spine_y - (28 if name == order[0] else 20),
                hue[name],
            )
        hub = order[0]
        cv.dot(cx[hub], spine_y, 20, t["official"], gap_px=3)
        for name in order[1:]:
            if kind[name] == "official":
                cv.dot(cx[name], spine_y, 12, t["official"], gap_px=3)
            else:
                cv.hatched_dot(cx[name], spine_y, 12)
        outputs = {
            "Oracle Cards": [
                (n(total), 22, "bold", t["ink"], 0),
                ("cards", 13, "normal", t["ink"], 42),
            ],
            "Default Cards": [
                (n(tables["printings"]), 19, "bold", t["ink"], 0),
                ("printings", 13, "normal", t["ink"], 42),
                (f"{n(tables['artists'])} artists", 12, "normal", t["ink2"], 40),
            ],
            "Rulings": [
                (n(reach["rulings"]), 19, "bold", t["ink"], 0),
                ("have a ruling", 13, "normal", t["ink"], 42),
                (f"{pct(reach['rulings'] / total)} of cards", 12, "normal", t["ink2"], 40),
            ],
            "Oracle Tags": [
                (n(reach["oracle tags"]), 19, "bold", t["ink"], 0),
                ("have an\nOracle Tag", 13, "normal", t["ink"], 42),
                (f"{pct(reach['oracle tags'] / total)} of cards", 12, "normal", t["ink2"], 40),
            ],
            "Art Tags": [
                (n(reach["art tags"]), 19, "bold", t["ink"], 0),
                ("have an\nArt Tag", 13, "normal", t["ink"], 42),
                (f"{pct(reach['art tags'] / total)} of cards", 12, "normal", t["ink2"], 40),
            ],
        }
        bottoms = {
            name: stack(
                cv, cx[name], spine_y + (80 if name == hub else 70), outputs[name], col_w - 10
            )
            for name in order
        }
        # The bracket: every other node is tied to the hub, not to its neighbour.
        bracket = max(bottoms.values()) + 44
        for name in order[1:]:
            cv.line([cx[name], cx[name]], [bottoms[name] + 18, bracket], t["ink2"], lw_px=2)
        cv.line([cx[hub], cx[order[-1]]], [bracket, bracket], t["ink2"], lw_px=2)
        cv.arrow(cx[hub], bracket, bottoms[hub] + 18, t["ink2"])
        label_y = bracket + 46
        middle = (cx[order[0]] + cx[order[-1]]) / 2
        cv.text(
            middle,
            label_y,
            "printings, rulings, tagged cards and tagged pictures all lead back to a card",
            size=13,
            color=t["ink2"],
            ha="center",
        )
        # Every link in the graph, under the source it comes from. Rulings and printings
        # are rows of their own, so neither total counts them.
        totals_y = label_y + 110
        cv.text(
            left, totals_y, f"The {n(links + community)} links in the graph", size=13, weight="bold"
        )
        totals_y += 58
        official = [name for name in order if kind[name] == "official"]
        spans = {
            "official": (x0[official[0]], x0[official[-1]] + col_w),
            "community": (x0[order[len(official)]], x0[order[-1]] + col_w),
        }
        totals = {
            "official": (
                f"{n(links)} official links",
                "a card's, a face's or a printing's own facts, read from the card files; "
                f"the {n(tables['rulings'])} rulings are rows of their own",
            ),
            "community": (
                f"{n(community)} community links",
                f"{n(tag_links)} tags on cards and pictures, and {n(between_tags)} from a "
                "tag to its parent tag",
            ),
        }
        ends = []
        for k, (head_text, detail_text) in totals.items():
            xa, xb = spans[k]
            cv.key_square(xa, totals_y - 9, k)
            cv.text(xa + 30, totals_y, head_text, size=13, weight="bold")
            ends.append(cv.para(xa, totals_y + 44, detail_text, xb - xa, size=12, color=t["ink2"]))

        # What the rule leaves out.
        out_top = max(ends) + 96
        cv.text(
            left,
            out_top,
            f"The {n(left_out)} entries the rule leaves out",
            size=13,
            weight="bold",
        )
        parts = named + [(f"of {len(others)} other kinds", sum(others))]
        bar_y, bar_h = out_top + 30, 24
        x = left
        for i, (label, value) in enumerate(parts):
            width = (right - left) * value / left_out
            cv.rect(x, bar_y, width - 4, bar_h, t["segment"][i])
            cv.text(x, bar_y + bar_h + 42, n(value), size=13, weight="bold")
            cv.text(x, bar_y + bar_h + 80, label, size=12, color=t["ink2"])
            x += width
        bottom = bar_y + bar_h + 80

        cv.finish(
            bottom,
            f"Card files of {long_date(cards['snapshot'])}; rulings and tags of "
            f"{long_date(graph['sources_snapshot'])}. No tag is ever an answer key.",
        )
        return cv

    return draw


# --------------------------------------------------------------------------- B. coverage


def coverage(records: dict) -> Callable[[dict], Canvas]:
    """How much of the cards that count each source reaches."""
    cards, graph = records["cards"], records["graph"]
    tables, read, reach = graph["tables"], graph["files_read"], graph["coverage"]
    total = cards["cards"]
    rulings_tenths = round(reach["rulings"] / total * 10)
    groups = [
        (
            "official",
            "OFFICIAL",
            "Wizards of the Coast's card data, as Scryfall serves it",
            [
                (
                    "Official links",
                    "an official link",
                    "colours, types, keywords, formats, artists",
                    reach["given links"],
                    f"{n(official_links(tables))} links in the graph",
                ),
                (
                    "Rulings",
                    "a ruling",
                    "how a card works: from Wizards, and a few from Scryfall's staff",
                    reach["rulings"],
                    f"{n(read['rulings'])} rulings in the file, {n(tables['rulings'])} kept",
                ),
            ],
        ),
        (
            "community",
            "COMMUNITY",
            "labels volunteers add on Scryfall Tagger",
            [
                (
                    "Oracle Tags",
                    "an Oracle Tag",
                    "what a card does",
                    reach["oracle tags"],
                    f"{n(read['oracle tags'])} tags, used {n(read['oracle tag links'])} times; "
                    f"{n(tables['card_oracle_tag'])} kept",
                ),
                (
                    "Art Tags",
                    "an Art Tag",
                    "what a card's picture shows",
                    reach["art tags"],
                    f"{n(read['art tags'])} tags, used {n(read['art tag links'])} times; "
                    f"{n(tables['illustration_art_tag'])} kept",
                ),
            ],
        ),
    ]

    def draw(t: dict) -> Canvas:
        cv = Canvas(t, height=1800)
        y = cv.header(
            "Nearly every card carries community tags, but only "
            f"{rulings_tenths} in 10 have a ruling",
            f"How many of TopDeck's {n(total)} cards each source reaches with at least one "
            "link. Tags reach further than rulings. They are kept apart from the official "
            "data, and no tag, checked or not, is ever an answer key.",
        )
        left, right = MARGIN, cv.w - MARGIN
        bar_h = 24
        y += 76
        bottom = y
        for k, label, who, rows in groups:
            cv.key_square(left, y - 9, k)
            head = cv.text(left + 32, y, label, size=12.5, weight="bold")
            cv.text(cv.extent(head)[2] + 12, y, who, size=12.5, color=t["ink2"])
            cv.line([left, right], [y + 22, y + 22], t["grid"], lw_px=1.5)
            y += 84
            for name, noun, what, reached, volume in rows:
                share = reached / total
                figure = cv.text(right, y + 4, pct(share), size=21, weight="bold", ha="right")
                cv.text(left, y, name, size=14, weight="bold")
                cv.text(left, y + 40, what, size=12.5, color=t["ink2"])
                cv.text(
                    cv.extent(figure)[0] - 20,
                    y,
                    f"{n(reached)} cards",
                    size=12.5,
                    color=t["ink2"],
                    ha="right",
                )
                bar_y = y + 78
                length = right - left
                cv.meter(left, bar_y, length, bar_h, share, k)
                y = bar_y + bar_h / 2
                missing = total - reached
                if missing and share < 0.9:
                    # A bracket under the empty end of the track.
                    xa, xb = left + length * share + 6, right
                    yb = y + 14
                    cv.line([xa, xa, xb, xb], [yb - 6, yb, yb, yb - 6], t["ink2"], lw_px=1.6)
                    cv.text(
                        (xa + xb) / 2,
                        yb + 38,
                        f"{n(missing)} cards without {noun}",
                        size=12.5,
                        color=t["ink"],
                        ha="center",
                    )
                    y = yb + 38
                elif missing:
                    # Too small a gap for a bracket: the words sit under the track's end.
                    cv.text(
                        right,
                        y + 46,
                        f"{n(missing)} cards without {noun}",
                        size=12.5,
                        color=t["ink"],
                        ha="right",
                    )
                    y += 46
                cv.text(left, y + 42, volume, size=12, color=t["muted"])
                bottom = y + 42
                y += 128
            y += 20
        cv.finish(
            bottom,
            "A card is reached when at least one link of that kind touches it; an Art Tag "
            "reaches a card through the picture on any of its printings. "
            + OFFICIAL_LINK
            + f" Card files of {long_date(cards['snapshot'])}; rulings and tags of "
            f"{long_date(graph['sources_snapshot'])}.",
        )
        return cv

    return draw


# --------------------------------------------------------------------------- C. lift


def lift_by_subtype(records: dict) -> Callable[[dict], Canvas]:
    """2024 question 1: the colour each common creature subtype leans to, and how hard."""
    answers = records["answers_2024"]
    one = answers["elves_and_goblins"]
    rows = sorted(one["commonest_subtypes"], key=lambda row: -row["lift"])
    elf, goblin = one["elves_green"], one["goblins_red"]
    called = {elf["subtype"], goblin["subtype"]}
    plural = {"Elf": "Elves", "Goblin": "Goblins"}
    lo, hi = 1.0, 4.5  # the axis starts at 1x, no lean at all: dots need no zero
    if min(r["lift_low"] for r in rows) < lo or max(r["lift_high"] for r in rows) > hi:
        raise ValueError("a lift falls outside the chart's axis")

    def draw(t: dict) -> Canvas:
        cv = Canvas(t, height=2200)
        y = cv.header(
            f"Elves are green {elf['lift']:.1f} times as often as creatures in general, and "
            f"Goblins red {goblin['lift']:.1f} times as often",
            f"{elf['share']:.0%} of Elves are green, against "
            f"{one['colour_share'][elf['colour']]:.0%} of all {n(one['creatures'])} "
            f"creatures: a lift of {elf['lift']:.1f}. Each row is one of the {len(rows)} "
            "commonest creature subtypes, with the colour it leans to most, ordered by lift. "
            "Dot: the lift. Line: its 95% interval.",
        )
        name_r = MARGIN + max(cv.width_of(r["subtype"], 13, "bold") for r in rows)
        x0, x1 = name_r + 40, 880
        share_r, count_r = 1348, 1536

        def X(v):
            return x0 + (x1 - x0) * (v - lo) / (hi - lo)

        # Each colour's share of all creatures: the base every lift divides by.
        bases = ", ".join(f"{colour} {one['colour_share'][colour]:.1%}" for colour in COLOURS)
        y = cv.para(
            MARGIN,
            y + 40,
            f"The base each lift divides by, each colour's share of all creatures: {bases}.",
            cv.w - 2 * MARGIN,
            size=12,
            color=t["ink2"],
        )
        head_y = y + 76
        top = head_y + 70
        pitch = 54
        end = top + pitch * (len(rows) - 1)
        cv.text(share_r, head_y - 20, "Share in", size=12, color=t["muted"], ha="right")
        cv.text(share_r, head_y + 14, "that colour", size=12, color=t["muted"], ha="right")
        cv.text(count_r, head_y + 14, "Creatures", size=12, color=t["muted"], ha="right")
        for v in (1, 2, 3, 4):
            cv.line(
                [X(v)] * 2,
                [top - 30, end + 28],
                t["ink2"] if v == 1 else t["grid"],
                lw_px=1.6 if v == 1 else 1,
                zorder=0,
            )
            cv.text(X(v), head_y + 14, f"{v}×", size=12, color=t["muted"], ha="center")
        cv.text(
            X(1) + 12,
            end + 70,
            "1× is no lean: as often as all creatures",
            size=12,
            color=t["ink2"],
        )

        for i, row in enumerate(rows):
            y = top + i * pitch
            hot = row["subtype"] in called
            weight = "bold" if hot else "normal"
            if hot:
                cv.rect(40, y - pitch / 2 + 4, cv.w - 80, pitch - 8, t["highlight"], zorder=-2)
            cv.text(
                name_r, y, row["subtype"], size=13, weight=weight, ha="right", va="center_baseline"
            )
            cv.line(
                [X(row["lift_low"]), X(row["lift_high"])], [y, y], t["muted"], lw_px=3, zorder=2
            )
            cv.mana_dot(X(row["lift"]), y, row["colour"])
            label = row["colour"]
            if hot:
                label += f" {row['lift']:.1f}×, {row['with_colour']} of {row['cards']}"
            cv.text(
                X(row["lift_high"]) + 16,
                y,
                label,
                size=12.5,
                weight=weight,
                color=t["ink"] if hot else t["ink2"],
                va="center_baseline",
            )
            cv.text(
                share_r,
                y,
                f"{row['share']:.0%}",
                size=12.5,
                weight=weight,
                ha="right",
                va="center_baseline",
            )
            cv.text(
                count_r,
                y,
                n(row["cards"]),
                size=12.5,
                color=t["ink2"],
                ha="right",
                va="center_baseline",
            )

        cv.finish(
            end + 70,
            f"{plural[elf['subtype']]} and {plural[goblin['subtype']]} are shaded. A creature "
            "counts in every colour it has: a green and white Elf counts as green and as "
            "white. The line is the Wilson 95% interval on the share, divided by the share "
            f"among all creatures. Card files of {long_date(answers['snapshot'])}.",
        )
        return cv

    return draw


# --------------------------------------------------------------------------- D. artists


def artist_ranks(two: dict) -> dict:
    """Where each artist sits on each side of the artists chart.

    The record keeps both lists down to the same rank, so every rank down to it is drawn
    on both sides, to scale. An artist from the left-hand list who falls below that rank
    without basic lands is drawn further down on the right, past a break. An artist who
    enters the right-hand list from below the left-hand one has no partner on the left.
    """
    with_ = {row["artist"]: row for row in two["by_printings"]}
    without = {row["artist"]: row for row in two["without_basic_lands"]["by_printings"]}
    deepest = two["ranks_kept"]
    left = {a: i + 1 for i, a in enumerate(with_)}
    right = {a: i + 1 for i, a in enumerate(without)}
    right.update({a: r["rank_without_basic_lands"] for a, r in with_.items() if a not in right})
    left_count = {a: r["printings"] for a, r in with_.items()}
    right_count = {a: r["printings"] for a, r in without.items()}
    right_count.update({a: r["printings"] - r["basic_lands"] for a, r in with_.items()})
    return {
        "deepest": deepest,
        "left": left,
        "right": right,
        "left_count": left_count,
        "right_count": right_count,
        # Below the drawn ranks on the right, past the break.
        "far": sorted(r for a, r in right.items() if r > deepest),
        # In the right-hand list, but below every rank drawn on the left.
        "right_only": [a for a in without if a not in left],
    }


def skipped_ranks(deepest: int, far: list[int]) -> str:
    """The ranks a break leaves out, in words: 'ranks 19 to 22 and 24 to 38'."""
    spans, before = [], deepest
    for rank in far:
        if rank - before > 1:
            first, last = before + 1, rank - 1
            spans.append(str(first) if first == last else f"{first} to {last}")
        before = rank
    if not spans:
        return ""
    joined = spans[0] if len(spans) == 1 else ", ".join(spans[:-1]) + " and " + spans[-1]
    return ("rank " if len(spans) == 1 and "to" not in spans[0] else "ranks ") + joined


def artists_basic_lands(records: dict) -> Callable[[dict], Canvas]:
    """2024 question 2: how leaving out basic lands reorders the most-printed artists."""
    answers = records["answers_2024"]
    two = answers["artists"]
    with_ = {row["artist"]: row for row in two["by_printings"]}
    without = {row["artist"]: row for row in two["without_basic_lands"]["by_printings"]}
    leader_before = two["by_printings"][0]["artist"]
    leader_now = two["without_basic_lands"]["by_printings"][0]["artist"]
    top_n = two["top"]
    ranks = artist_ranks(two)
    left, right = ranks["left"], ranks["right"]
    left_count, right_count = ranks["left_count"], ranks["right_count"]
    deepest, far, right_only = ranks["deepest"], ranks["far"], ranks["right_only"]
    big_falls = sorted(a for a in with_ if right[a] in far)

    def slot(rank):
        return rank if rank <= deepest else deepest + 3.2 + far.index(rank)

    def draw(t: dict) -> Canvas:
        ja, kw = with_[leader_before], with_[leader_now]
        # Walker in blue, Avon in ink: orange is kept for community data alone.
        hues = {leader_now: t["official"], leader_before: t["ink"]}
        cv = Canvas(t, height=2400)
        y = cv.header(
            f"Without basic lands, {leader_now}, not {leader_before}, is the most-printed artist",
            f"{leader_before} has the most printings, {n(ja['printings'])}, but "
            f"{n(ja['basic_lands'])} of them are basic lands, reprinted in nearly every set. "
            f"{leader_now} has {n(kw['printings'])}, and only {n(kw['basic_lands'])} are basic "
            "lands. The top artists, ranked both ways, with their printings beside them.",
        )
        size, hot_size = 12.5, 13

        def name_w(a):
            hot = a in hues
            return cv.width_of(a, hot_size if hot else size, "bold" if hot else "normal")

        count_w = cv.width_of("1,216", size, "bold")
        rank_w = cv.width_of("40", 12)
        left_w = count_w + 22 + max(name_w(a) for a in left)
        right_w = max(name_w(a) for a in right) + 22 + count_w
        rank_gap, name_gap = 16, 30 + rank_w
        xl = MARGIN + left_w + name_gap
        xr = cv.w - MARGIN - right_w - name_gap
        row_h = 48
        head = y + 70
        y0 = head + 70

        def Y(rank):
            return y0 + (slot(rank) - 1) * row_h

        cv.text(xl + 10, head, "Counting every printing", size=13, weight="bold", ha="right")
        cv.text(xr - 10, head, "Leaving out basic lands", size=13, weight="bold")
        cv.line([MARGIN, xl + 10], [head + 20, head + 20], t["grid"], lw_px=1.5)
        cv.line([xr - 10, cv.w - MARGIN], [head + 20, head + 20], t["grid"], lw_px=1.5)
        cut = Y(top_n) + row_h / 2
        for xa, xb in ((MARGIN, xl + 10), (xr - 10, cv.w - MARGIN)):
            cv.line([xa, xb], [cut, cut], t["grid"], lw_px=1.5, zorder=0.2)

        def right_label(a, hot):
            ink = t["ink"] if hot else t["ink2"]
            weight = "bold" if hot else "normal"
            yr = Y(right[a])
            cv.text(
                xr + rank_gap + rank_w,
                yr,
                str(right[a]),
                size=12,
                color=t["muted"],
                ha="right",
                va="center_baseline",
            )
            cv.text(
                xr + name_gap,
                yr,
                a,
                size=hot_size if hot else size,
                color=ink,
                weight=weight,
                va="center_baseline",
            )
            cv.text(
                cv.w - MARGIN,
                yr,
                n(right_count[a]),
                size=size,
                color=ink,
                weight=weight,
                ha="right",
                va="center_baseline",
            )

        for a in sorted(left, key=lambda a: (a in hues, a in big_falls, a)):
            hot = a in hues
            strong = a in big_falls
            col = hues.get(a, t["context_strong"] if strong else t["context"])
            yl, yr = Y(left[a]), Y(right[a])
            cv.curve(
                xl,
                yl,
                xr,
                yr,
                col,
                lw_px=4 if hot else (2.8 if strong else 2),
                zorder=3 if hot else (2 if strong else 1),
            )
            for xx, yy in ((xl, yl), (xr, yr)):
                cv.dot(xx, yy, 7 if hot else 5.5, col, gap_px=2.5, zorder=4 if hot else 2)
            ink = t["ink"] if hot else t["ink2"]
            weight = "bold" if hot else "normal"
            cv.text(
                xl - rank_gap,
                yl,
                str(left[a]),
                size=12,
                color=t["muted"],
                ha="right",
                va="center_baseline",
            )
            cv.text(
                xl - name_gap,
                yl,
                a,
                size=hot_size if hot else size,
                color=ink,
                weight=weight,
                ha="right",
                va="center_baseline",
            )
            cv.text(
                MARGIN + count_w,
                yl,
                n(left_count[a]),
                size=size,
                color=ink,
                weight=weight,
                ha="right",
                va="center_baseline",
            )
            right_label(a, hot)

        # Artists who enter the right-hand list from below the left-hand one: a short
        # stub leads in from the left, from no rank drawn there.
        for a in right_only:
            yr = Y(right[a])
            cv.line(
                [xr - 70, xr],
                [yr + 26, yr],
                t["context_strong"],
                lw_px=2,
                zorder=1,
                linestyle=(0, (2, 3)),
            )
            cv.dot(xr, yr, 5.5, t["context"], gap_px=2.5, zorder=2)
            cv.text(
                xr - 78,
                yr + 26,
                f"from {without[a]['rank_with_basic_lands']}",
                size=12,
                color=t["muted"],
                ha="right",
                va="center_baseline",
                italic=True,
                # On a patch of page colour, so the lines that cross here pass behind it.
                bbox={"boxstyle": "round,pad=0.2", "facecolor": t["surface"], "edgecolor": "none"},
                zorder=6,
            )
            right_label(a, False)

        # A clear break across the right-hand rank scale, with the ranks it leaves out.
        if far:
            yb = (Y(deepest) + Y(far[0])) / 2
            for dy in (-6, 6):
                cv.line(
                    [xr - 22, xr + 22], [yb + dy + 7, yb + dy - 7], t["ink2"], lw_px=2.2, zorder=5
                )
            label = f"{skipped_ranks(deepest, far)} not shown"
            room = cv.w - MARGIN - (xr + name_gap)
            lines = cv.wrap(label, room, 12)
            step = 12 * PX_PER_PT * 1.3
            first = yb - (len(lines) - 1) * step / 2
            for i, line in enumerate(lines):
                cv.text(
                    xr + name_gap,
                    first + i * step,
                    line,
                    size=12,
                    color=t["muted"],
                    va="center_baseline",
                    italic=True,
                )

        bottom = Y(far[-1] if far else deepest) + row_h / 2
        cv.finish(
            bottom,
            f"The line under each list marks the top {top_n}; a dashed stub comes in from a "
            "rank below the list on the left. A printing is one real printing of a card, on "
            f"paper, in an ordinary set: {n(two['basic_land_printings'])} of the "
            f"{n(two['printings'])} with an artist credit are basic lands. Card files of "
            f"{long_date(answers['snapshot'])}.",
        )
        return cv

    return draw


# --------------------------------------------------------------------------- E. subtypes


def subtypes_by_colour(records: dict) -> Callable[[dict], Canvas]:
    """2024 question 3: the subtypes most tied to one colour, block by colour."""
    answers = records["answers_2024"]
    three = answers["subtypes_in_colours"]
    rows = three["strongest"]
    if min(r["cards"] for r in rows) < MIN_CARDS:
        raise ValueError("a listed subtype has fewer cards than the floor")
    base = three["colour_share"]
    groups = [
        (c, sorted([r for r in rows if r["colour"] == c], key=lambda r: (-r["share"], -r["cards"])))
        for c in COLOURS
    ]
    groups = [(c, g) for c, g in groups if g]
    full = sorted([r for r in rows if r["share"] >= 1.0], key=lambda r: -r["cards"])
    plural = {"Vedalken": "Vedalken", "Kor": "Kor", "Cyclops": "Cyclopes", "Octopus": "Octopuses"}
    # The floor's example: the smallest listed group that just missed 100%.
    near = min((r for r in rows if r["share"] < 1), key=lambda r: (r["cards"], -r["share"]))

    def many(name):
        return plural.get(name, name + "s")

    def draw(t: dict) -> Canvas:
        cv = Canvas(t, height=2600)
        if len(full) >= 2:
            a, b = full[0], full[1]
            title = (
                f"All {a['cards']} {many(a['subtype'])} are {a['colour']} and all "
                f"{b['cards']} {many(b['subtype'])} {b['colour']}: some kinds of card "
                "keep to one colour"
            )
        else:
            title = "Some kinds of card keep to one colour"
        y = cv.header(
            title,
            f"The {len(rows)} subtypes most tied to one colour, of the "
            f"{three['subtypes_considered']} with at least {MIN_CARDS} cards. Dot: the share of "
            "the subtype's cards that have the colour. Line: its 95% interval. The upright "
            f"line in each block is that colour's share among all {n(three['cards'])} cards, "
            "about one in five.",
        )
        name_r = MARGIN + max(cv.width_of(r["subtype"], 13) for r in rows)
        x0, x1 = name_r + 36, 1090
        with_r, lift_r = 1352, 1536

        def X(v):
            return x0 + (x1 - x0) * v

        head_y = y + 66
        for v in (0, 0.5, 1.0):
            cv.text(X(v), head_y + 14, f"{v:.0%}", size=12, color=t["muted"], ha="center")
        cv.text(with_r, head_y - 20, "Cards with", size=12, color=t["muted"], ha="right")
        cv.text(with_r, head_y + 14, "the colour", size=12, color=t["muted"], ha="right")
        cv.text(lift_r, head_y - 20, "Times as", size=12, color=t["muted"], ha="right")
        cv.text(lift_r, head_y + 14, "often", size=12, color=t["muted"], ha="right")

        pitch = 52
        y = head_y + 52
        grid_top = y
        first_row = True
        for colour, group in groups:
            band_h = 50
            cv.rect(40, y, cv.w - 80, band_h, t["tint"], zorder=-1)
            cv.mana_dot(MARGIN + 12, y + band_h / 2, colour, r=10)
            cv.text(
                MARGIN + 36,
                y + band_h / 2,
                colour.capitalize(),
                size=13,
                weight="bold",
                va="center_baseline",
            )
            cv.text(
                X(base[colour]) + 12,
                y + band_h / 2,
                f"{base[colour]:.1%} of all cards",
                size=12,
                color=t["ink2"],
                va="center_baseline",
            )
            block_top = y + band_h
            y = block_top + pitch * 0.75
            for row in group:
                cv.text(name_r, y, row["subtype"], size=13, ha="right", va="center_baseline")
                cv.line(
                    [X(row["share_low"]), X(row["share_high"])],
                    [y, y],
                    t["muted"],
                    lw_px=3,
                    zorder=2,
                )
                cv.mana_dot(X(row["share"]), y, colour)
                whole = row["share"] >= 1
                cv.text(
                    with_r,
                    y,
                    f"{row['with_colour']} of {row['cards']}",
                    size=12.5,
                    weight="bold" if whole else "normal",
                    ha="right",
                    va="center_baseline",
                )
                cv.text(
                    lift_r,
                    y,
                    f"{row['lift']:.1f}×",
                    size=12.5,
                    color=t["ink2"],
                    ha="right",
                    va="center_baseline",
                )
                if whole:
                    cv.text(
                        X(row["share_low"]) - 16,
                        y,
                        f"all {row['cards']}; interval down to {row['share_low']:.0%}",
                        size=12,
                        color=t["ink2"],
                        ha="right",
                        va="center_baseline",
                    )
                elif first_row:
                    cv.text(
                        X(row["share_low"]) - 16,
                        y,
                        "line: 95% interval",
                        size=12,
                        color=t["ink2"],
                        ha="right",
                        va="center_baseline",
                    )
                first_row = False
                y += pitch
            block_bottom = y - pitch / 2
            cv.line(
                [X(base[colour])] * 2, [block_top + 6, block_bottom], t["ink2"], lw_px=1.6, zorder=1
            )
            if colour == near["colour"]:
                # The floor, explained inside the chart where it is read.
                note_x = X(base[colour]) + 28
                note_w = X(min(r["share_low"] for r in group)) - 40 - note_x
                cv.para(
                    note_x,
                    block_top + 34,
                    f"Why {MIN_CARDS} cards or more? A small group hits 100% by luck too "
                    f"easily: {near['with_colour']} of {near['cards']} "
                    f"{many(near['subtype'])} fits a true share from "
                    f"{near['share_low']:.0%} to {near['share_high']:.0%}.",
                    note_w,
                    size=12,
                    color=t["ink2"],
                    leading=1.3,
                )
            y += 18
        grid_bottom = y - 18
        for v in (0, 0.5, 1.0):
            cv.line([X(v)] * 2, [grid_top, grid_bottom], t["grid"], lw_px=1, zorder=-0.5)

        cv.finish(
            grid_bottom,
            f"These were picked as the strongest of {three['subtypes_considered']} subtypes, "
            "so their shares lean a little high. Counted over all cards, not only creatures; "
            "a card counts in every colour it has. The interval is a Wilson 95% interval. "
            f"Card files of {long_date(answers['snapshot'])}.",
            gap=56,
        )
        return cv

    return draw


# --------------------------------------------------------------------------- drawing

CHARTS = {
    "what-topdeck-knows": what_topdeck_knows,
    "coverage": coverage,
    "lift-by-subtype": lift_by_subtype,
    "artists-basic-lands": artists_basic_lands,
    "subtypes-by-colour": subtypes_by_colour,
}


def _style(t: dict) -> None:
    plt.rcdefaults()
    plt.rcParams.update(
        {
            "text.parse_math": False,  # "$" and "^" are text, never formulas
            "text.color": t["ink"],
            "figure.facecolor": t["surface"],
            "axes.facecolor": t["surface"],
            "savefig.facecolor": t["surface"],
            "hatch.linewidth": 1.6,
        }
    )


def draw_all(root: Path = Path("."), out: Path | None = None) -> list[Path]:
    """Draw every chart from the records in results/ into docs/images/, light and dark.

    Every image is drawn into a scratch folder beside the output and checked; only when
    all of them pass are they moved into place, so a broken layout changes nothing."""
    records = read_records(root)
    out = out if out is not None else root / OUT
    if tuple(CHARTS) != NAMES:
        raise ValueError("every chart must have a name")
    out.mkdir(parents=True, exist_ok=True)
    drawn, problems = [], []
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".figures-") as scratch:
        for name, chart in CHARTS.items():
            draw = chart(records)
            for mode, t in THEMES.items():
                _style(t)
                cv = draw(t)
                try:
                    cv.fig.canvas.draw()
                    problems += [f"{name}-{mode}: {p}" for p in cv.lint()]
                    path = Path(scratch) / f"{name}-{mode}.png"
                    # No version stamp in the file, so the same records give the same bytes.
                    cv.fig.savefig(path, dpi=DPI, metadata={"Software": None})
                finally:
                    plt.close(cv.fig)
                drawn.append(path)
        if problems:
            raise ValueError("the layout is broken: " + "; ".join(problems))
        written = []
        for path in drawn:
            os.replace(path, out / path.name)
            written.append(out / path.name)
    return written
