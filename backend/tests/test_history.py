"""Phase 4 M7: version history (undo / redo / restore) and locks."""

import time

import pytest
from fastapi.testclient import TestClient

from app.agents import history
from app.agents.pipeline import new_project, run_project
from app.agents.state import Bubble, MangaProject, PageLettering, PanelAttempt, PanelResult
from app.main import create_app
from tests.test_redraw_loop import ScriptedEditor, answer


# --------------------------------------------------------------------------- pure history logic
def make_project() -> MangaProject:
    p = MangaProject(job_id="j", project_id="j", story="s")
    result = PanelResult(page=1, panel=1, image="a1.png",
                         attempts=[PanelAttempt(attempt=i, image=f"a{i}.png", status="accepted") for i in (1, 2, 3)])
    result.chosen_attempt = 1
    p.panels.append(result)
    p.lettering.append(PageLettering(page=1, bubbles=[Bubble(id="b1", panel=1, text="HI")]))
    return p


def choose(p, n):
    p.panel_result(1, 1).use_attempt(p.panel_result(1, 1).attempt(n))


def test_first_version_is_not_undoable():
    p = make_project()
    history.record_panel(p, 1, 1, "generate", "First drawing")
    history.record_lettering(p, 1, "auto_place", "Automatic lettering")
    assert history.undo(p) is None
    assert history.summary(p)["can_undo"] is False and len(p.history.versions) == 2


def test_undo_redo_and_new_change_clears_redo():
    p = make_project()
    history.record_panel(p, 1, 1, "generate", "First")
    choose(p, 2)
    history.record_panel(p, 1, 1, "revision", "Angrier")
    choose(p, 3)
    history.record_panel(p, 1, 1, "inpaint", "Lamp")
    assert p.panel_result(1, 1).image == "a3.png"

    change, page = history.undo(p)
    assert change.label == "Lamp" and page == 1 and p.panel_result(1, 1).image == "a2.png"
    history.undo(p)
    assert p.panel_result(1, 1).image == "a1.png" and history.undo(p) is None
    history.redo(p)
    assert p.panel_result(1, 1).image == "a2.png" and history.summary(p)["can_redo"]
    p.lettering[0].bubbles[0].text = "NEW"            # a new change ...
    history.record_lettering(p, 1, "auto_place", "base")   # (first lettering version: not undoable)
    p.lettering[0].bubbles[0].text = "NEWER"
    history.record_lettering(p, 1, "bubbles", "Edited")
    assert not history.summary(p)["can_redo"]           # ... clears the redo stack
    history.undo(p)
    assert p.lettering[0].bubbles[0].text == "NEW"


def test_restore_any_version_is_undoable():
    p = make_project()
    v1 = history.record_panel(p, 1, 1, "generate", "First")
    choose(p, 3)
    history.record_panel(p, 1, 1, "revision", "Third")
    change, _ = history.restore(p, v1.id)
    assert p.panel_result(1, 1).image == "a1.png" and change.label == "Restore: First"
    assert history.restore(p, v1.id) is None            # already current
    history.undo(p)
    assert p.panel_result(1, 1).image == "a3.png"
    with pytest.raises(KeyError):
        history.restore(p, 99)


def test_versions_survive_save_and_load(tmp_path):
    p = make_project()
    history.record_panel(p, 1, 1, "generate", "First")
    choose(p, 2)
    history.record_panel(p, 1, 1, "revision", "Second")
    p.save(tmp_path)
    loaded = MangaProject.load(tmp_path)
    history.undo(loaded)
    assert loaded.panel_result(1, 1).image == "a1.png"


# --------------------------------------------------------------------------- pipeline + API
@pytest.fixture
def client(settings, story):
    settings.auto_approve = True
    run_project(new_project(story, "hx", settings), settings=settings, job_dir=settings.output_dir / "hx")
    with TestClient(create_app(settings)) as c:
        yield c


def wait(client, job="hx"):
    for _ in range(150):
        state = client.get(f"/api/jobs/{job}").json()
        if not state["busy"]:
            return state
        time.sleep(0.1)
    raise AssertionError("job still busy")


def test_pipeline_records_initial_versions(client):
    h = client.get("/api/jobs/hx/history").json()
    kinds = {v["kind"] for v in h["versions"]}
    assert {"generate", "auto_place"} <= kinds and not h["can_undo"]


def test_bubble_edit_undo_redo_restore_via_api(client):
    page = client.get("/api/jobs/hx/pages/1/editor").json()
    original = page["lettering"]["bubbles"]
    edited = [dict(b, text="CHANGED") if i == 0 else b for i, b in enumerate(original)]
    client.put("/api/jobs/hx/pages/1/lettering", json={"bubbles": edited, "label": "Changed first bubble"})
    h = client.get("/api/jobs/hx/history").json()
    assert h["can_undo"] and h["undo_label"] == "Changed first bubble"
    undone = client.post("/api/jobs/hx/history/undo").json()
    assert undone["page"] == 1 and undone["can_redo"]
    assert client.get("/api/jobs/hx/pages/1/editor").json()["lettering"]["bubbles"][0]["text"] == original[0]["text"]
    client.post("/api/jobs/hx/history/redo")
    assert client.get("/api/jobs/hx/pages/1/editor").json()["lettering"]["bubbles"][0]["text"] == "CHANGED"
    first = next(v for v in client.get("/api/jobs/hx/history").json()["versions"] if v["target"] == "lettering:1")
    client.post("/api/jobs/hx/history/restore", json={"version_id": first["id"]})
    assert client.get("/api/jobs/hx/pages/1/editor").json()["lettering"]["bubbles"][0]["text"] == original[0]["text"]
    assert client.post("/api/jobs/hx/history/restore", json={"version_id": first["id"]}).status_code == 409
    assert client.post("/api/jobs/hx/history/restore", json={"version_id": 9999}).status_code == 404


def test_revision_creates_panel_version_and_undo_brings_back_the_old_drawing(client):
    before = client.get("/api/jobs/hx/project").json()
    target = next(r for r in before["panels"] if r["page"] == 1)
    page, panel = target["page"], target["panel"]
    client.post(f"/api/jobs/hx/panels/{page}/{panel}/revise", json={"instruction": "make it sadder"})
    wait(client)
    h = client.get("/api/jobs/hx/history").json()
    assert h["undo_label"].lower().startswith("instruction")
    changed = next(r for r in client.get("/api/jobs/hx/project").json()["panels"] if (r["page"], r["panel"]) == (page, panel))
    assert changed["image"] != target["image"]
    client.post("/api/jobs/hx/history/undo")
    back = next(r for r in client.get("/api/jobs/hx/project").json()["panels"] if (r["page"], r["panel"]) == (page, panel))
    assert back["image"] == target["image"]
    versions = [v for v in h["versions"] if v["target"] == f"panel:{page}:{panel}"]
    assert [v["kind"] for v in versions] == ["generate", "revision"]


def test_panel_lock_blocks_automatic_redraws(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "lk", settings), settings=settings, job_dir=tmp_path,
                          llm=ScriptedEditor(lambda ctx: answer()))
    result = project.panels[0]
    result.locked = True
    project.save(tmp_path)
    from app.agents.graph import Ctx
    from app.agents.redraw import run_quality_loop
    from app.agents.revision import find_panel
    from app.providers.mock_image import MockImageProvider
    ctx = Ctx(settings=settings, llm=ScriptedEditor(lambda c: answer("fail", low="anatomy")),
              image=MockImageProvider(), job_dir=tmp_path)
    planned, directed, spec = find_panel(project, result.page, result.panel)
    run_quality_loop(project, ctx, spec, planned, directed, source="revision")
    assert len([a for a in result.attempts if a.round == 2]) == 1        # no automatic redraw
    # and a re-run of the pipeline never redraws it
    result.status = "drawing"
    assert project.panels[0].locked


def test_character_lock_protects_look_in_automatic_fixes(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "cl", settings), settings=settings, job_dir=tmp_path,
                          llm=ScriptedEditor(lambda ctx: answer()))
    spec = next(s for s in project.prompts if s.references)
    name = spec.characters[0]
    project.character(name).look_locked = True
    from app.agents.graph import Ctx
    from app.agents.redraw import run_quality_loop
    from app.agents.revision import find_panel
    from app.providers.mock_image import MockImageProvider
    bad_fix = {"ipadapter_weight": 0.3, "prompt_remove": [project.character(name).visual_tags.hair], "new_seed": True}
    calls = []
    llm = ScriptedEditor(lambda c: calls.append(1) or (answer("fail", low="character_likeness", fix=bad_fix)
                                                     if len(calls) == 1 else answer()))
    planned, directed, spec = find_panel(project, spec.page, spec.panel)
    result = run_quality_loop(project, Ctx(settings=settings, llm=llm, image=MockImageProvider(), job_dir=tmp_path),
                              spec, planned, directed, source="revision")
    redraw = [a for a in result.attempts if a.source == "redraw"][-1]
    first = [a for a in result.attempts if a.source == "revision"][-1]
    assert redraw.ipadapter_weight == first.ipadapter_weight            # weight change ignored
    assert redraw.fix_applied.prompt_remove == []                       # tag removal ignored


def test_lock_endpoints(client):
    assert client.post("/api/jobs/hx/panels/1/1/lock", json={"locked": True}).json()["locked"] is True
    assert client.get("/api/jobs/hx/project").json()["panels"][0]["locked"] is True
    name = client.get("/api/jobs/hx/project").json()["characters"][0]["name"]
    assert client.post(f"/api/jobs/hx/characters/{name}/lock", json={"locked": True}).json()["look_locked"] is True
    assert client.post("/api/jobs/hx/characters/Nobody/lock", json={"locked": True}).status_code == 404


def test_old_project_gets_a_baseline_before_the_first_edit(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "old", settings), settings=settings, job_dir=tmp_path,
                          llm=ScriptedEditor(lambda ctx: answer()))
    project.history = None                         # as if made before version history existed
    original = project.panels[0].image
    from app.agents.graph import Ctx
    from app.agents.redraw import run_quality_loop
    from app.agents.revision import find_panel
    from app.providers.mock_image import MockImageProvider
    r = project.panels[0]
    planned, directed, spec = find_panel(project, r.page, r.panel)
    run_quality_loop(project, Ctx(settings=settings, llm=ScriptedEditor(lambda c: answer()), image=MockImageProvider(),
                                  job_dir=tmp_path), spec, planned, directed, source="revision")
    assert history.undo(project) is not None and project.panels[0].image == original
