import json

from PIL import Image

from app.pipeline.export import export_pdf, export_pngs
from app.pipeline.run import STAGES, run_pipeline


def test_export_png_and_pdf(tmp_path):
    pages = [Image.new("L", (300, 400), 255), Image.new("L", (300, 400), 0)]
    pngs = export_pngs(pages, tmp_path / "pages")
    assert [p.name for p in pngs] == ["page_01.png", "page_02.png"]
    pdf = export_pdf(pages, tmp_path / "out.pdf")
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Count 2" in data  # two PDF pages


def test_end_to_end_mock_run(story, settings, tmp_path):
    events = []
    out = tmp_path / "job"
    manifest = run_pipeline(story, settings=settings, out_dir=out,
                            progress=lambda s, f, m: events.append((s, f)))
    # Every stage reported, in order, and finished
    seen = []
    for stage, _ in events:
        if stage not in seen:
            seen.append(stage)
    assert seen == STAGES
    assert events[-1] == ("export", 1.0)

    assert manifest["providers"] == {"llm": "mock", "image": "mock"}
    assert manifest["panel_count"] >= 4
    for direction in ("rtl", "ltr"):
        output = manifest["outputs"][direction]
        assert len(output["pages"]) == manifest["page_count"]
        page = Image.open(out / output["pages"][0])
        assert page.size == (1240, 1754)
        assert (out / output["pdf"]).read_bytes().startswith(b"%PDF")
    for character in manifest["characters"]:
        assert (out / character["reference_image"]).exists()
    saved = json.loads((out / "result.json").read_text())
    assert saved["title"] == manifest["title"]
    assert (out / "script.json").exists() and (out / "panels" / "prompts.json").exists()


def test_end_to_end_is_deterministic(story, settings, tmp_path):
    a = run_pipeline(story, settings=settings, out_dir=tmp_path / "a")
    b = run_pipeline(story, settings=settings, out_dir=tmp_path / "b")
    page_a = (tmp_path / "a" / a["outputs"]["rtl"]["pages"][0]).read_bytes()
    page_b = (tmp_path / "b" / b["outputs"]["rtl"]["pages"][0]).read_bytes()
    assert page_a == page_b
