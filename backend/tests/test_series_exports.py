"""Phase 5 M11: series memory across chapters + PNG / PDF / CBZ / webtoon exports."""

import time
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from app.agents.pipeline import new_project, run_project
from app.agents.series import SeriesStore
from app.main import create_app
from app.pipeline.export import comic_info, export_webtoon
from app.providers.mock_llm import MockLLMProvider

CHAPTER_2 = ('The next morning Mira returned to the school rooftop. Kaito was waiting by the fence. '
             '"Did you see the river last night?" Kaito asked. Mira nodded slowly. '
             '"The glow came back," Mira said. They ran down the stairs together.')


class SpyLLM(MockLLMProvider):
    def __init__(self):
        self.prompts = {}

    def generate_json(self, *, task, user, **kw):
        self.prompts.setdefault(task, []).append(user)
        return super().generate_json(task=task, user=user, **kw)


def wait(client, job_id):
    for _ in range(300):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "awaiting_approval"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_two_chapters_share_cast_style_and_memory(settings, story):
    settings.auto_approve = True
    spy = SpyLLM()
    with TestClient(create_app(settings, llm=spy)) as client:
        first = client.post("/api/jobs", json={"story": story}).json()
        assert wait(client, first["id"])["status"] == "done"
        pid = first["id"]                                           # chapter 1 starts the series
        series = client.get(f"/api/series/{pid}").json()
        assert series["chapters"][0]["number"] == 1 and series["story_so_far"]
        assert series["chapters"][0]["summary"] and series["cast"]
        client.patch(f"/api/series/{pid}", json={"style_tags": "heavy shadows, thick lines", "title": "Rooftop Glow"})

        second = client.post(f"/api/series/{pid}/chapters", json={"story": CHAPTER_2}).json()
        assert wait(client, second["id"])["status"] == "done"
        p2 = client.get(f"/api/jobs/{second['id']}/project").json()
        assert p2["chapter"] == 2 and p2["project_id"] == pid and p2["series_title"] == "Rooftop Glow"
        assert p2["story_so_far"] == series["story_so_far"]
        # The Writer saw the memory, the Character Designer reused the cast, prompts carry the style.
        assert "<story_so_far>" in spy.prompts["beat_sheet"][-1] and "chapter 2" in spy.prompts["beat_sheet"][-1]
        reused = [c for c in p2["characters"] if c["reused_from"] == pid]
        assert reused and all(c["approved"] for c in reused)
        assert all("heavy shadows, thick lines" in x["prompt"] for x in p2["prompts"])
        after = client.get(f"/api/series/{pid}").json()
        assert [c["number"] for c in after["chapters"]] == [1, 2]
        assert after["story_so_far"].startswith(series["story_so_far"][:40])   # memory grows
        assert client.get("/api/series").json()[0]["project_id"] == pid
        assert client.post("/api/series/nope/chapters", json={"story": CHAPTER_2}).status_code == 404


def test_chapter_inherits_lora_and_locks(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "s1", settings), settings=settings, job_dir=settings.output_dir / "s1")
    character = project.characters[0]
    character.look_locked = True
    character.lora.status, character.lora.trainer, character.lora.file = "ready", "imported", "x.safetensors"
    from app.agents.cast_store import CastStore
    CastStore(settings.output_dir).save(project, settings.output_dir / "s1")
    chapter = run_project(new_project(CHAPTER_2, "s2", settings, project_id="s1"), settings=settings,
                          job_dir=settings.output_dir / "s2")
    again = chapter.character(character.name)
    assert again.look_locked and again.has_lora() and chapter.chapter == 2
    assert any(f"{again.lora.trigger}, " in x.prompt for x in chapter.prompts if character.name in x.characters)


def test_exports_cbz_webtoon_pdf(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "ex", settings), settings=settings, job_dir=tmp_path)
    for direction in ("rtl", "ltr"):
        out = project.outputs[direction]
        assert (tmp_path / out["pdf"]).exists()
        with zipfile.ZipFile(tmp_path / out["cbz"]) as zf:
            names = zf.namelist()
            assert names[: len(out["pages"])] == [f"{i:03d}.png" for i in range(1, len(out["pages"]) + 1)]
            info = zf.read("ComicInfo.xml").decode()
            assert ("YesAndRightToLeft" in info) == (direction == "rtl")
    strips = project.outputs["rtl"]["webtoon"]
    assert strips and all(Image.open(tmp_path / s).width == 800 for s in strips)
    assert all(Image.open(tmp_path / s).height <= 4000 for s in strips)


def test_webtoon_keeps_reading_order_and_slices(tmp_path):
    page = Image.new("L", (1240, 1754), 255)
    for i, shade in enumerate((0, 80, 160)):
        page.paste(shade, (100, 100 + i * 500, 1100, 500 + i * 500))
    page.save(tmp_path / "p.png")
    layout = {"panels": [{"rect": {"x": 100, "y": 100 + i * 500, "w": 1000, "h": 400}} for i in range(3)]}
    strips = export_webtoon([tmp_path / "p.png"] * 4, [layout] * 4, tmp_path / "w", max_height=1500)
    assert len(strips) > 1 and all(Image.open(s).height <= 1500 for s in strips)
    first = Image.open(strips[0])
    assert first.getpixel((400, 40 + 50)) == 0                 # the first panel (black) comes first
    assert "<Manga>No</Manga>" in comic_info("t", 3, rtl=False)


def test_series_store_registers_chapters(settings, story):
    settings.auto_approve = True
    project = run_project(new_project(story, "st", settings), settings=settings, job_dir=settings.output_dir / "st")
    series = SeriesStore(settings.output_dir).load("st")
    assert series.title == project.title and series.chapters[0].status == "done"
    assert series.chapters[0].cover.startswith("pages/rtl/")
