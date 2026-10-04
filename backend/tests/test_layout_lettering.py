import itertools

import pytest
from PIL import Image, ImageDraw

from app.geometry import Rect
from app.models import DialogueLine, Page, Panel
from app.pipeline.layout import LayoutConfig, compose_page, fit_image, plan_page
from app.pipeline.lettering import keep_out_zone, plan_balloons, wrap_text
from app.fonts import load_font

CFG = LayoutConfig()


def make_panel(n=1, dialogue=(), narration=None, characters=("Aya", "Ben"), mood="calm"):
    return Panel(panel_number=n, characters=list(characters), action="something", setting="a park",
                 shot="medium", mood=mood, narration=narration,
                 dialogue=[DialogueLine(speaker=s, text=t) for s, t in dialogue])


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
def test_plan_page_fits_inside_margins_without_overlap(count):
    rects = plan_page(count, CFG)
    assert len(rects) == count
    page = Rect(CFG.margin, CFG.margin, CFG.width - 2 * CFG.margin, CFG.height - 2 * CFG.margin)
    for r in rects:
        assert page.contains(r)
    for a, b in itertools.combinations(rects, 2):
        assert not a.intersects(b)
        # gutters: panels are separated by at least the gutter
        assert not a.inset(-CFG.gutter // 2 + 1).intersects(b.inset(-CFG.gutter // 2 + 1))


def test_rtl_mirrors_reading_order():
    ltr = plan_page(4, CFG)
    rtl = plan_page(4, CFG, rtl=True)
    # Row 2 has two panels: in LTR panel 2 is on the left, in RTL on the right.
    assert ltr[1].x < ltr[2].x
    assert rtl[1].x > rtl[2].x
    assert [r.w for r in ltr] == [r.w for r in rtl]


def test_plan_page_rejects_bad_counts():
    with pytest.raises(ValueError):
        plan_page(7, CFG)


def test_fit_image_exact_size():
    img = Image.new("RGB", (300, 100), "red")
    out = fit_image(img, 120, 200)
    assert out.size == (120, 200) and out.mode == "L"


def test_wrap_text_respects_width():
    draw = ImageDraw.Draw(Image.new("L", (10, 10)))
    font = load_font(24)
    lines = wrap_text("the quick brown fox jumps over the lazy dog " * 3 + "supercalifragilistic" * 3, font, 200, draw)
    assert len(lines) > 3
    assert all(draw.textlength(line, font=font) <= 200 for line in lines)


def assert_good_placement(balloons, rect):
    keep_out = keep_out_zone(rect)
    for b in balloons:
        assert rect.contains(b.box), f"{b.box} outside {rect}"
        assert not b.box.intersects(keep_out), "balloon covers the centre of the panel"
    for a, b in itertools.combinations(balloons, 2):
        assert not a.box.intersects(b.box)


def test_balloons_avoid_centre_and_each_other():
    rect = Rect(0, 0, 700, 500)
    panel = make_panel(dialogue=[("Aya", "Where are we going tonight?"), ("Ben", "To the river. Something is glowing there.")],
                       narration="Later that evening, by the old bridge.")
    balloons = plan_balloons(panel, rect)
    assert [b.kind for b in balloons] == ["narration", "speech", "speech"]
    assert_good_placement(balloons, rect)
    assert not any(b.overflow for b in balloons)


def test_reading_order_start_corner():
    rect = Rect(0, 0, 800, 600)
    panel = make_panel(dialogue=[("Aya", "Hello there.")])
    ltr = plan_balloons(panel, rect)[0].box
    rtl = plan_balloons(panel, rect, rtl=True)[0].box
    assert ltr.x < rect.w / 2 < rtl.right
    assert ltr.y < rect.h * 0.3 and rtl.y < rect.h * 0.3


def test_tails_point_at_speaker():
    rect = Rect(0, 0, 800, 600)
    panel = make_panel(dialogue=[("Aya", "Left side."), ("Ben", "Right side."), ("Narrator", "Off panel.")])
    aya, ben, narrator = plan_balloons(panel, rect)
    assert aya.tail_target[0] < ben.tail_target[0]
    assert narrator.tail_target is None


def test_long_text_in_small_panel_shrinks_font():
    rect = Rect(0, 0, 360, 320)
    long = "This is a very long line of dialogue that will never fit at full size in a tiny panel."
    panel = make_panel(dialogue=[("Aya", long), ("Ben", long)], narration="A long caption that also needs space.")
    balloons = plan_balloons(panel, rect, font_size=26)
    assert any(b.font_size < 26 for b in balloons)
    # Whatever happens, text never goes into the keep-out zone unless forced (overflow flag).
    keep_out = keep_out_zone(rect)
    for b in balloons:
        assert b.overflow or not b.box.intersects(keep_out)


def test_shout_balloon_for_dramatic_exclamation():
    panel = make_panel(dialogue=[("Aya", "Run!")], mood="dramatic")
    assert plan_balloons(panel, Rect(0, 0, 600, 400))[0].kind == "shout"


def test_compose_page_draws_panels_and_returns_boxes():
    panels = [make_panel(n, dialogue=[("Aya", f"Line {n}.")]) for n in range(1, 5)]
    page = Page(page_number=1, panels=panels)
    images = {n: Image.new("L", (400, 400), 200) for n in range(1, 5)}
    img, info = compose_page(page, images, CFG, title="Test")
    assert img.size == (CFG.width, CFG.height)
    assert len(info["panels"]) == 4
    for p in info["panels"]:
        rect = Rect(**p["rect"])
        # border pixel is ink
        assert img.getpixel((rect.x + 1, rect.y + rect.h // 2)) == 0
        # panel art was pasted (grey 200 somewhere in the middle)
        assert img.getpixel((rect.x + rect.w // 2, rect.y + rect.h // 2)) == 200
        assert len(p["balloons"]) == 1
