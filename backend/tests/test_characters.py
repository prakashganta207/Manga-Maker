"""Character Designer, reference sheets (turnaround + expressions), cast persistence."""

from PIL import Image, ImageDraw

from app.agents.cast_store import CastStore
from app.agents.character_designer import design_characters
from app.agents.pipeline import new_project, run_project
from app.agents.sheets import autocrop, generate_sheets, sheets_present, split_columns
from app.agents.state import EXPRESSIONS, VIEWS, MangaProject
from app.agents.writer import write_beat_sheet
from app.providers.base import ImageRequest
from app.providers.mock_image import MockImageProvider
from app.providers.mock_llm import MockLLMProvider


class RecordingImages(MockImageProvider):
    def __init__(self):
        self.requests: list[ImageRequest] = []

    def generate(self, request):
        self.requests.append(request)
        return super().generate(request)


def designed_project(story):
    project = MangaProject(job_id="job1", project_id="proj1", story=story)
    write_beat_sheet(project, MockLLMProvider())
    design_characters(project, MockLLMProvider())
    return project


def test_bible_entries_have_fixed_tags_and_seeds(story):
    project = designed_project(story)
    mira = project.character("Mira")
    assert mira.visual_tags.hair and mira.visual_tags.outfit and mira.expression_range
    assert mira.turnaround_seed != mira.expression_seed
    again = designed_project(story).character("Mira")
    assert again.turnaround_seed == mira.turnaround_seed           # seeds are stable per project
    assert again.tag_prompt() == mira.tag_prompt()                 # tags are stable too
    hairs = [c.visual_tags.hair for c in project.characters]
    assert len(set(hairs)) == len(hairs)                           # characters look different


def test_generate_sheets_crops_views_and_expressions(story, tmp_path):
    project = designed_project(story)
    mira = project.character("Mira")
    images = RecordingImages()
    generate_sheets(mira, images, tmp_path)
    assert set(mira.sheets.views) == set(VIEWS) and set(mira.sheets.expression_refs) == set(EXPRESSIONS)
    assert sheets_present(mira, tmp_path) and mira.status == "ready"
    turnaround, expressions = images.requests
    assert turnaround.kind == "turnaround" and turnaround.seed == mira.turnaround_seed
    assert expressions.kind == "expressions" and expressions.seed == mira.expression_seed
    assert mira.tag_prompt() in turnaround.prompt and mira.tag_prompt() in expressions.prompt
    front = Image.open(tmp_path / mira.sheets.views["front"])
    assert front.width < Image.open(tmp_path / mira.sheets.turnaround).width / 2  # a real crop


def test_autocrop_and_split():
    img = Image.new("L", (300, 100), 255)
    ImageDraw.Draw(img).rectangle((120, 30, 160, 70), fill=0)
    cropped = autocrop(img, pad=5)
    assert cropped.size == (51, 51)
    parts = split_columns(Image.new("L", (300, 100), 255), 3)
    assert len(parts) == 3


def test_only_main_characters_get_sheets(story, settings, tmp_path):
    settings.auto_approve = True
    images = RecordingImages()
    project = run_project(new_project(story, "job", settings), settings=settings, job_dir=tmp_path, image=images)
    main = {n.lower() for n in project.main_character_names()}
    for character in project.characters:
        assert sheets_present(character, tmp_path) == (character.name.lower() in main)
    sheet_requests = [r for r in images.requests if r.kind in ("turnaround", "expressions")]
    assert len(sheet_requests) == 2 * len(main)


def test_cast_store_round_trip(story, tmp_path):
    project = designed_project(story)
    job_dir = tmp_path / "job1"
    for character in project.characters:
        generate_sheets(character, MockImageProvider(), job_dir)
    project.characters[0].approved = True
    store = CastStore(tmp_path / "output")
    assert store.save(project, job_dir) == 1   # only approved characters are stored
    listing = store.list()
    assert listing[0]["project_id"] == "proj1" and listing[0]["characters"][0]["name"] == project.characters[0].name

    new_job = tmp_path / "job2"
    cast = store.install("proj1", new_job)
    entry = cast[project.characters[0].name.lower()]
    assert entry.approved and sheets_present(entry, new_job)  # images copied into the new job


def test_new_chapter_reuses_cast(story, settings, tmp_path):
    """Chapter 2 of a project keeps the approved characters (same look, no redesign)."""
    settings.auto_approve = True
    first = run_project(new_project(story, "chapter1", settings), settings=settings, job_dir=settings.output_dir / "chapter1")
    CastStore(settings.output_dir).save(first, settings.output_dir / "chapter1")

    class CountingLLM(MockLLMProvider):
        tasks: list = []

        def generate_json(self, **kwargs):
            self.tasks.append(kwargs["task"])
            return super().generate_json(**kwargs)

    llm = CountingLLM()
    second = run_project(new_project(story, "chapter2", settings, project_id="chapter1"), settings=settings,
                         job_dir=settings.output_dir / "chapter2", llm=llm)
    assert "character_bible" not in llm.tasks          # nobody needed designing
    step = next(s for s in second.trace if s.agent == "character_designer")
    assert step.status == "skipped"
    for old, new in zip(first.characters, second.characters):
        assert new.tag_prompt() == old.tag_prompt() and new.turnaround_seed == old.turnaround_seed


def test_expression_crops_follow_detected_faces(monkeypatch):
    """Real models draw sheets in any grid; crops must hold exactly one head each."""
    from PIL import Image
    from app.agents import sheets
    from app.vision.faces import Face
    sheet = Image.new("RGB", (1536, 640), "white")
    faces = [Face(100, 400, 150, 150), Face(40, 60, 160, 160), Face(400, 70, 150, 150)]  # two rows
    monkeypatch.setattr(sheets, "detect_faces", lambda img: faces)
    crops = sheets.expression_crops(sheet, 5)
    assert len(crops) == 5
    assert crops[0].size[0] == int(160 * 1.9) or crops[0].size[0] < 400   # first = top-left face, head-sized
    assert crops[3].size == sheets.split_columns(sheet, 5)[3].size        # missing faces -> column fallback
    monkeypatch.setattr(sheets, "detect_faces", lambda img: [])
    assert [c.size for c in sheets.expression_crops(sheet, 5)] == [c.size for c in sheets.split_columns(sheet, 5)]
