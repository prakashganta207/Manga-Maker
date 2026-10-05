"""Phase 5 M8: the Letterer — face-aware placement, reading order, tails, vertical text, fonts."""

import math

import pytest
from PIL import Image, ImageDraw

from app.agents import letterer
from app.agents.letterer import BusyMap, letter_page, panel_faces, reading_score
from app.agents.pipeline import new_project, run_project
from app.agents.schemas import DialogueLine, PlannedPage, PlannedPanel
from app.fonts import DIALOGUE_FONT, SFX_FONT, dialogue_font, has_cjk
from app.geometry import Rect
from app.pipeline.bubbles import render_lettering, to_pixels
from app.vision.faces import Face

SLOT = Rect(64, 64, 1112, 600)
INNER = SLOT.inset(5)


def page_with(panel: PlannedPanel) -> PlannedPage:
    return PlannedPage(page_number=1, panels=[panel])


def panel(**kw) -> PlannedPanel:
    base = dict(panel_number=1, beat=1, purpose="p", size="large", characters=["Aya", "Ken"], action="a",
                setting="s", emotion="calm",
                dialogue=[DialogueLine(speaker="Aya", text="Where are you going?"),
                          DialogueLine(speaker="Ken", text="Somewhere far away.")],
                narration="That night the city was silent.", sfx=["WHOOSH"])
    return PlannedPanel(**{**base, **kw})


@pytest.fixture
def two_faces(monkeypatch):
    """A 1112x600 'drawing' with two faces (in image coordinates = slot coordinates here)."""
    faces = [Face(150, 180, 160, 160), Face(780, 200, 150, 150)]
    monkeypatch.setattr(letterer, "detect_faces", lambda img: faces)
    image = Image.new("RGB", (SLOT.w, SLOT.h), "white")
    draw = ImageDraw.Draw(image)
    for f in faces:
        draw.ellipse((f.x, f.y, f.x + f.w, f.y + f.h), outline="black", width=6)
    return image, faces


def test_fonts_are_bundled_with_licences():
    assert DIALOGUE_FONT.exists() and SFX_FONT.exists()
    assert (DIALOGUE_FONT.parent / "ComicNeue-OFL.txt").exists() and (SFX_FONT.parent / "Bangers-OFL.txt").exists()
    assert dialogue_font("") == str(DIALOGUE_FONT) and dialogue_font("x.ttf") == "x.ttf"
    assert has_cjk("どこへ行くの") and not has_cjk("Hello!")


def test_busy_map_prefers_empty_areas():
    image = Image.new("L", (400, 200), 255)
    draw = ImageDraw.Draw(image)
    for x in range(200, 400, 6):
        draw.line((x, 0, x, 200), fill=0, width=2)          # right half: dense linework
    busy = BusyMap(image, Rect(0, 0, 400, 200))
    assert busy.mean(Rect(10, 10, 150, 150)) < 0.2 < busy.mean(Rect(220, 10, 150, 150))


def test_faces_are_mapped_through_the_cover_fit(monkeypatch):
    # 832x1216 portrait art cover-fitted into a wide slot: only a band in the middle is visible.
    monkeypatch.setattr(letterer, "detect_faces", lambda img: [Face(300, 600, 200, 200), Face(300, 50, 100, 100)])
    faces = panel_faces(Image.new("RGB", (832, 1216)), SLOT, INNER, 1, "medium")
    assert len(faces) == 1                                   # the face near the top is cropped away
    f = faces[0]
    assert SLOT.x < f.center[0] < SLOT.right and SLOT.y < f.center[1] < SLOT.bottom
    assert f.w > 200                                          # scaled up with the art


def test_estimated_faces_without_art():
    faces = panel_faces(None, SLOT, INNER, 2, "medium")
    assert len(faces) == 2 and not faces[0].detected and faces[0].x < faces[1].x


def test_bubbles_avoid_faces_follow_rtl_order_and_aim_tails(two_faces):
    image, faces = two_faces
    lettering, notes = letter_page(page_with(panel()), [SLOT], [INNER], {1: image}, {1: "medium"}, rtl=True)
    bubbles = lettering.bubbles
    assert [b.kind for b in bubbles][:3] == ["narration", "speech", "speech"] and bubbles[-1].kind == "sfx"
    boxes = [to_pixels(b, INNER) for b in bubbles]
    page_faces = [f.scaled(1, 1, SLOT.x, SLOT.y) for f in faces]
    for box in boxes:
        assert not any(box.intersects(f.rect) for f in page_faces)       # no text on a face
        assert INNER.contains(box)
    # Right-to-left reading order: each bubble starts at or after the previous one.
    scores = [reading_score(b, INNER, rtl=True) for b in boxes[:3]]
    assert scores == sorted(scores)
    assert boxes[0].y < INNER.y + INNER.h * 0.4                        # narration near the top
    # Tails point at the right speaker: Aya = left face, Ken = right face.
    aya, ken = bubbles[1], bubbles[2]
    for bubble, face in ((aya, page_faces[0]), (ken, page_faces[1])):
        tip = (INNER.x + bubble.tail[0] * INNER.w, INNER.y + bubble.tail[1] * INNER.h)
        box = to_pixels(bubble, INNER)
        centre = (box.x + box.w / 2, box.y + box.h / 2)
        assert math.dist(tip, face.center) < math.dist(centre, face.center)
    assert "2 face(s) detected" in notes[0]
    assert lettering.faces[1][0][4] == 1.0


def test_ltr_reading_order_starts_top_left(two_faces):
    image, _ = two_faces
    lettering, _ = letter_page(page_with(panel(narration=None, sfx=[])), [SLOT], [INNER], {1: image}, {1: "medium"}, rtl=False)
    first = to_pixels(lettering.bubbles[0], INNER)
    assert first.x + first.w / 2 < INNER.x + INNER.w / 2 or first.y < INNER.y + INNER.h * 0.3


def test_vertical_text_auto_for_japanese_and_toggle(two_faces):
    image, _ = two_faces
    jp = panel(dialogue=[DialogueLine(speaker="Aya", text="どこへ行くの？")], narration=None, sfx=[])
    auto, _ = letter_page(page_with(jp), [SLOT], [INNER], {1: image}, {}, vertical="auto")
    assert auto.bubbles[0].vertical and auto.bubbles[0].h > auto.bubbles[0].w * 0.6
    english, _ = letter_page(page_with(panel(sfx=[])), [SLOT], [INNER], {1: image}, {}, vertical="auto")
    assert not any(b.vertical for b in english.bubbles)
    forced, _ = letter_page(page_with(panel(sfx=[])), [SLOT], [INNER], {1: image}, {}, vertical="on")
    assert all(b.vertical for b in forced.bubbles if b.kind != "narration")


def test_render_vertical_and_styled_sfx():
    page = Image.new("L", (1240, 1754), 255)
    from app.agents.state import Bubble, PageLettering
    lettering = PageLettering(page=1, bubbles=[
        Bubble(id="a", panel=1, kind="speech", text="WAIT FOR ME", x=0.1, y=0.1, w=0.2, h=0.5, vertical=True, tail=(0.5, 0.9)),
        Bubble(id="b", panel=1, kind="sfx", text="BOOM", x=0.5, y=0.6, w=0.4, h=0.3, font_size=70),
        Bubble(id="c", panel=1, kind="thought", text="Hmm...", x=0.5, y=0.1, w=0.3, h=0.25, tail=(0.6, 0.6)),
    ])
    drawn = render_lettering(page, lettering, {1: INNER}, dialogue_font(""))
    assert [b.kind for b in drawn] == ["speech", "sfx", "thought"]
    assert page.crop(to_pixels(lettering.bubbles[1], INNER).box).getextrema()[0] == 0   # ink drawn for the SFX


def test_pipeline_records_letterer_step(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "lt", settings), settings=settings, job_dir=tmp_path)
    step = next(s for s in project.trace if s.agent == "letterer")
    assert step.output["layers"] == sum(len(pl.bubbles) for pl in project.lettering)
    assert step.inputs["reading_order"] == "right-to-left" and step.inputs["font"] == "ComicNeue-Bold.ttf"
    assert all(pl.faces for pl in project.lettering)
