"""Export + the whole agent graph end to end in mock mode."""

from PIL import Image

from app.agents.director import shot_runs_ok
from app.agents.pipeline import new_project, run_project
from app.agents.state import MangaProject
from app.pipeline.export import export_pdf, export_pngs
from app.providers.mock_llm import MockLLMProvider


def test_export_png_and_pdf(tmp_path):
    pages = [Image.new("L", (300, 400), 255), Image.new("L", (300, 400), 0)]
    pngs = export_pngs(pages, tmp_path / "pages")
    assert [p.name for p in pngs] == ["page_01.png", "page_02.png"]
    data = export_pdf(pages, tmp_path / "out.pdf").read_bytes()
    assert data.startswith(b"%PDF") and b"/Count 2" in data


def run(story, settings, out, **kw):
    settings.auto_approve = True
    events = []
    project = run_project(new_project(story, "job", settings, **kw), settings=settings, job_dir=out,
                          progress=lambda s, f, m: events.append((s, f)))
    return project, events


def test_end_to_end_mock_run(story, settings, tmp_path):
    out = tmp_path / "job"
    project, events = run(story, settings, out)
    assert project.status == "done"
    assert project.providers["llm"] == "mock" and project.providers["image"] == "mock"
    # Every agent step is in the trace, with timings recorded per node.
    assert [s.label for s in project.trace][:3] == ["Beat sheet", "Page plan", "Director plan"]
    assert {"writer_beats", "director", "panels", "export"} <= set(project.timings)
    assert shot_runs_ok(project.director)
    assert len(project.panels) == len(project.prompts) == len(project.page_plan.all_panels())
    for direction in ("rtl", "ltr"):
        output = project.outputs[direction]
        assert Image.open(out / output["pages"][0]).size == (1240, 1754)
        assert (out / output["pdf"]).read_bytes().startswith(b"%PDF")
    # Character tags appear verbatim in prompts of panels where the character is present.
    tags = {c.name: c.tag_prompt() for c in project.characters}
    for spec in project.prompts:
        for name in spec.characters:
            assert tags[name] in spec.prompt
    assert MangaProject.load(out).status == "done"


def test_resume_after_crash(story, settings, tmp_path):
    out = tmp_path / "job"
    project, _ = run(story, settings, out)
    # Simulate a crash after panel generation: drop the layout/export results.
    project.outputs, project.status = {}, "running"
    project.save(out)

    class NoLLM(MockLLMProvider):
        def generate_json(self, **kwargs):
            raise AssertionError("agents must not run again on resume")

    resumed = run_project(MangaProject.load(out), settings=settings, job_dir=out, llm=NoLLM())
    assert resumed.status == "done" and resumed.outputs["rtl"]["pdf"]


def test_end_to_end_is_deterministic(story, settings, tmp_path):
    a, _ = run(story, settings, tmp_path / "a")
    b, _ = run(story, settings, tmp_path / "b")
    page_a = (tmp_path / "a" / a.outputs["rtl"]["pages"][0]).read_bytes()
    page_b = (tmp_path / "b" / b.outputs["rtl"]["pages"][0]).read_bytes()
    assert page_a == page_b
