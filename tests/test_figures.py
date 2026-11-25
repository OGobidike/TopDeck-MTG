"""The charts: every one drawn from the records in results/ alone, the same every time.

These need matplotlib, from the optional `figures` extra. Without it they skip, except
where a database is required (in CI, or with TOPDECK_REQUIRE_DB set): there a missing
extra fails the run, as a missing database does, so a skip can never leave CI green.
"""

import json
import shutil

import pytest
from conftest import database_required

from topdeck import graph
from topdeck.cli import draw_figures

try:
    import matplotlib  # noqa: F401
except ModuleNotFoundError:
    if database_required():
        pytest.fail(
            "Drawing needs the figures extra, and it is required here: uv sync --extra figures",
            pytrace=False,
        )
    pytest.skip("drawing needs the figures extra", allow_module_level=True)

from PIL import Image  # noqa: E402

from topdeck import figures  # noqa: E402

pytestmark = pytest.mark.figures

RECORDS = ("cards.json", "graph.json", "answers_2024.json")


@pytest.fixture
def records_only(root, tmp_path, monkeypatch):
    """A folder holding the records and nothing else, with no way to reach a database."""
    (tmp_path / "results").mkdir()
    for name in RECORDS:
        shutil.copyfile(root / "results" / name, tmp_path / "results" / name)

    def no_database(*args, **kwargs):
        raise AssertionError("a chart tried to reach the database")

    monkeypatch.setattr(graph, "connect", no_database)
    return tmp_path


def test_every_chart_is_drawn_light_and_dark_from_the_records_alone(records_only):
    written = figures.draw_all(records_only)
    expected = {
        records_only / figures.OUT / f"{name}-{mode}.png"
        for name in figures.NAMES
        for mode in ("light", "dark")
    }
    assert set(written) == expected
    for path in written:
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_same_records_always_give_the_same_bytes(records_only, tmp_path):
    first = figures.draw_all(records_only, out=tmp_path / "first")
    second = figures.draw_all(records_only, out=tmp_path / "second")
    for a, b in zip(first, second, strict=True):
        assert a.read_bytes() == b.read_bytes(), a.name


def pixels(path):
    with Image.open(path) as image:
        return image.size, image.mode, image.tobytes()


def test_the_committed_charts_are_the_ones_the_records_draw(root, records_only):
    """The images in docs/images match, pixel for pixel, what the records draw now, so a
    chart can't fall behind its record. Pixels, not bytes: a PNG packer elsewhere may
    pack the same picture differently. The rehearsal compares the bytes as well."""
    for path in figures.draw_all(records_only):
        committed = root / figures.OUT / path.name
        assert committed.is_file(), f"{path.name} is drawn but not in docs/images"
        assert pixels(committed) == pixels(path), f"{path.name} is out of date: topdeck figures"


def test_a_changed_record_changes_the_charts(root, records_only):
    record = records_only / "results" / "graph.json"
    changed = json.loads(record.read_text())
    changed["coverage"]["rulings"] = 12000
    record.write_text(json.dumps(changed))
    drawn = {path.name: path for path in figures.draw_all(records_only)}
    for name in ("coverage-light.png", "what-topdeck-knows-dark.png"):
        assert pixels(drawn[name]) != pixels(root / figures.OUT / name), name


def test_the_figures_command_ends_on_a_plain_line(records_only, capsys):
    assert draw_figures(records_only) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        "Drew 10 images into docs/images/ from the records in results/."
    )


def test_records_that_disagree_are_refused_before_anything_is_drawn(records_only, capsys):
    record = records_only / "results" / "graph.json"
    record.write_text(record.read_text().replace('"rulings": 77164', '"rulings": 77000'))
    assert draw_figures(records_only) == 1
    printed = capsys.readouterr().out.strip()
    assert printed.startswith("The charts were not drawn: the records disagree: rulings read")
    assert not (records_only / figures.OUT).exists()


@pytest.mark.parametrize(
    "broken, said",
    [
        ("[]", "results/graph.json is not the shape its command writes"),
        ('{"broken', "results/graph.json is not valid JSON"),
        ("{}", "results/graph.json has no 'sources_snapshot'"),
    ],
)
def test_a_broken_record_ends_on_a_plain_sentence(records_only, capsys, broken, said):
    (records_only / "results" / "graph.json").write_text(broken)
    assert draw_figures(records_only) == 1
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith(f"The charts were not drawn: {said}")


def test_a_broken_layout_leaves_the_charts_already_there_untouched(records_only, monkeypatch):
    out = records_only / figures.OUT
    figures.draw_all(records_only)
    before = {path.name: path.read_bytes() for path in out.glob("*.png")}
    finish = figures.Canvas.finish

    def spill(canvas, bottom, notes, gap=64):
        finish(canvas, bottom, notes, gap)
        canvas.text(canvas.w - 10, 100, "past the edge")

    monkeypatch.setattr(figures.Canvas, "finish", spill)
    with pytest.raises(ValueError, match="the layout is broken"):
        figures.draw_all(records_only)
    assert {path.name: path.read_bytes() for path in out.glob("*.png")} == before
    assert [path.name for path in out.parent.iterdir()] == [out.name], "no scratch left"


def test_every_rank_above_the_break_is_drawn_on_both_sides(root):
    """No rank is missing down to the deepest one drawn to scale, on either side."""
    answers = json.loads((root / "results/answers_2024.json").read_text())
    ranks = figures.artist_ranks(answers["artists"])
    deepest = ranks["deepest"]
    for side in ("left", "right"):
        drawn = sorted(rank for rank in ranks[side].values() if rank <= deepest)
        assert drawn == list(range(1, deepest + 1)), side
    assert all(ranks["right"][a] <= deepest for a in ranks["right_only"])
    for artist in ranks["left"]:
        assert artist in ranks["left_count"] and artist in ranks["right_count"]


def test_the_break_names_the_ranks_it_leaves_out():
    assert figures.skipped_ranks(18, [23, 40]) == "ranks 19 to 22 and 24 to 39"
    assert figures.skipped_ranks(18, [20]) == "rank 19"
    assert figures.skipped_ranks(18, [19]) == ""


def test_text_below_twelve_points_is_refused():
    figures._style(figures.THEMES["light"])
    canvas = figures.Canvas(figures.THEMES["light"], height=200)
    with pytest.raises(ValueError, match="below the 12 pt floor"):
        canvas.text(100, 100, "too small", size=11)


def test_the_layout_check_catches_text_on_text_and_out_of_the_frame():
    figures._style(figures.THEMES["dark"])
    canvas = figures.Canvas(figures.THEMES["dark"], height=300)
    canvas.text(200, 100, "one line")
    canvas.text(210, 104, "another line")
    canvas.text(1590, 200, "past the edge")
    canvas.fig.canvas.draw()
    problems = canvas.lint()
    assert any(p.startswith("text on text: 'one line'") for p in problems)
    assert any(p.startswith("out of the frame: 'past the edge'") for p in problems)


def test_orange_is_kept_for_community_data_alone():
    for theme in figures.THEMES.values():
        others = {key: value for key, value in theme.items() if not key.startswith("community")}
        assert theme["community"] not in str(others)


def test_white_and_black_dots_look_the_same_in_both_themes():
    light, dark = (figures.THEMES[mode]["mana"] for mode in ("light", "dark"))
    for colour in ("white", "black"):
        fill, ring = light[colour]
        assert (fill, ring) == dark[colour]
        assert ring  # a fill with a ring, never a bare ring
