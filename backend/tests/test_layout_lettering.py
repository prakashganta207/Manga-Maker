import itertools

import pytest
from PIL import Image, ImageDraw

from app.agents.schemas import DialogueLine, PlannedPage, PlannedPanel
from app.fonts import load_font, safe_text
from app.geometry import Rect
from app.pipeline import templates
from app.pipeline.layout import LayoutConfig, compose_page, fit_image, panel_aspects, plan_page
from app.pipeline.lettering import keep_out_zone, plan_balloons, wrap_text

CFG = LayoutConfig()


def make_panel(n=1, dialogue=(), narration=None, characters=("Aya", "Ben"), emotion="calm", sfx=()):
    return PlannedPanel(panel_number=n, beat=1, purpose="test", size="medium", characters=list(characters),
                        action="something", setting="a park", emotion=emotion, narration=narration,
                        dialogue=[DialogueLine(speaker=s, text=t) for s, t in dialogue], sfx=list(sfx))


# --------------------------------------------------------------------------- template library
def test_library_has_required_templates():
    assert 8 <= len(templates.TEMPLATES) <= 10
    assert any(t.sizes == ["splash"] for t in templates.TEMPLATES)                      # splash page
    three_tier = templates.get("three_tier")                                             # 3 full-width rows
    assert three_tier.panel_count == 3 and all(s.w == 1 and s.x == 0 for s in three_tier.slots)
    assert any(s.shape == "tall" and s.h == 1 for t in templates.TEMPLATES for s in t.slots)  # tall vertical
    assert {t.panel_count for t in templates.TEMPLATES} == {1, 2, 3, 4, 5, 6}


@pytest.mark.parametrize("template", templates.TEMPLATES, ids=lambda t: t.id)
def test_template_geometry(template):
    # Slots tile the whole inner page exactly (no holes, no overlaps).
    assert sum(s.area for s in template.slots) == pytest.approx(1.0, abs=1e-6)
    rects = plan_page(template.id, CFG)
    page = Rect(CFG.margin, CFG.margin, CFG.width - 2 * CFG.margin, CFG.height - 2 * CFG.margin)
    for r in rects:
        assert page.contains(r)
    for a, b in itertools.combinations(rects, 2):
        assert not a.intersects(b)
        assert not a.inset(-CFG.gutter // 2 + 1).intersects(b.inset(-CFG.gutter // 2 + 1))  # gutter kept


def test_rtl_mirrors_reading_order():
    ltr = plan_page("classic_4", CFG)
    rtl = plan_page("classic_4", CFG, rtl=True)
    assert ltr[1].x < ltr[2].x and rtl[1].x > rtl[2].x   # panel 2 is on the right in manga order
    assert [r.w for r in ltr] == [r.w for r in rtl]
    tall_rtl = plan_page("tall_left", CFG, rtl=True)
    assert tall_rtl[0].x > tall_rtl[1].x                  # the tall panel moves to the right side


def test_best_template_matches_sizes():
    assert templates.best_template(["splash"]).id == "splash"
    assert templates.best_template(["large", "medium", "medium"]).id == "splash_top"
    assert templates.best_template(["small", "small", "large", "medium", "medium"]).id == "action_5"
    assert templates.best_template(["large", "medium", "medium", "medium"]).id == "tall_left"
    with pytest.raises(ValueError):
        templates.best_template(["medium"] * 7)


def test_panel_aspects_follow_slots():
    aspects = panel_aspects(["tall_left"], [4], CFG)
    assert aspects[(1, 1)] < 0.75 < aspects[(1, 2)]  # tall slot vs wide slots


def test_fit_image_exact_size():
    out = fit_image(Image.new("RGB", (300, 100), "red"), 120, 200)
    assert out.size == (120, 200) and out.mode == "L"


# --------------------------------------------------------------------------- lettering
def test_wrap_text_respects_width():
    draw = ImageDraw.Draw(Image.new("L", (10, 10)))
    font = load_font(24)
    lines = wrap_text("the quick brown fox jumps over the lazy dog " * 3 + "supercalifragilistic" * 3, font, 200, draw)
    assert len(lines) > 3 and all(draw.textlength(line, font=font) <= 200 for line in lines)


def assert_good_placement(balloons, rect):
    keep_out = keep_out_zone(rect)
    for b in balloons:
        assert rect.contains(b.box), f"{b.box} outside {rect}"
        assert not b.box.intersects(keep_out), "text covers the centre of the panel"
    for a, b in itertools.combinations(balloons, 2):
        assert not a.box.intersects(b.box)


def test_balloons_and_sfx_avoid_centre_and_each_other():
    rect = Rect(0, 0, 700, 500)
    panel = make_panel(dialogue=[("Aya", "Where are we going tonight?"), ("Ben", "To the river. Something glows.")],
                       narration="Later that evening, by the old bridge.", sfx=["CRASH"])
    balloons = plan_balloons(panel, rect)
    assert [b.kind for b in balloons] == ["narration", "speech", "speech", "sfx"]
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
    panel = make_panel(dialogue=[("Aya", "Left side."), ("Ben", "Right side."), ("Narrator", "Off panel.")])
    aya, ben, narrator = plan_balloons(panel, Rect(0, 0, 800, 600))
    assert aya.tail_target[0] < ben.tail_target[0]
    assert narrator.tail_target is None


def test_long_text_in_small_panel_shrinks_font():
    rect = Rect(0, 0, 360, 320)
    long = "This is a very long line of dialogue that will never fit at full size in a tiny panel."
    panel = make_panel(dialogue=[("Aya", long), ("Ben", long)], narration="A long caption that also needs space.")
    balloons = plan_balloons(panel, rect, font_size=26)
    assert any(b.font_size < 26 for b in balloons)
    for b in balloons:
        assert b.overflow or not b.box.intersects(keep_out_zone(rect))


def test_shout_balloon_for_intense_exclamation():
    assert plan_balloons(make_panel(dialogue=[("Aya", "Run!")], emotion="fear"), Rect(0, 0, 600, 400))[0].kind == "shout"
    assert plan_balloons(make_panel(dialogue=[("Aya", "Yay!")], emotion="calm"), Rect(0, 0, 600, 400))[0].kind == "speech"


def test_safe_text_for_bundled_font():
    assert safe_text("Café — naïve") == "Cafe - naive"
    assert safe_text("Café", font_path="custom.ttf") == "Café"


def test_compose_page_with_template():
    panels = [make_panel(n, dialogue=[("Aya", f"Line {n}.")]) for n in range(1, 6)]
    page = PlannedPage(page_number=1, panels=panels)
    images = {n: Image.new("L", (400, 400), 200) for n in range(1, 6)}
    img, info = compose_page(page, "action_5", images, CFG, title="Test")
    assert img.size == (CFG.width, CFG.height) and info["layout"] == "action_5"
    for p in info["panels"]:
        rect = Rect(**p["rect"])
        assert img.getpixel((rect.x + 1, rect.y + rect.h // 2)) == 0       # ink border
        assert img.getpixel((rect.x + rect.w // 2, rect.y + rect.h // 2)) == 200  # art pasted, centre clear
    with pytest.raises(ValueError):
        compose_page(page, "classic_4", images, CFG)
