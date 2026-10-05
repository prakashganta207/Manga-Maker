"""Version history with undo / redo for the interactive editor.

Targets:  "panel:<page>:<panel>"  (which drawing a panel shows)
          "lettering:<page>"       (the bubble layers of a page)

Every change (a bubble edit, a redraw from an instruction, an inpaint, a restore...) records a
*version* of its target: a snapshot small enough to keep forever (for panels: which attempt
image; for lettering: the list of bubbles). Undo/redo move a target between versions:

    change  = (target, from_version, to_version)
    undo    = pop the last change, show `from_version`, push the change on the redo stack
    redo    = pop from the redo stack, show `to_version` again
    restore = a new change from the current version to any older one (so it can be undone too)

A new change clears the redo stack (like every text editor). Versions are never deleted.
"""

from __future__ import annotations

from typing import Any

from .state import Bubble, Change, History, MangaProject, PageLettering, Version


def panel_target(page: int, panel: int) -> str:
    return f"panel:{page}:{panel}"


def lettering_target(page: int) -> str:
    return f"lettering:{page}"


def _history(project: MangaProject) -> History:
    if project.history is None:
        project.history = History()
    return project.history


def record(project: MangaProject, target: str, kind: str, label: str, data: dict[str, Any],
           undoable: bool = True) -> Version:
    """Store a new version of `target` and make it current. `undoable=False` for the very first
    version (the original drawing / automatic lettering), which has nothing to go back to."""
    history = _history(project)
    version = Version(id=len(history.versions) + 1, target=target, kind=kind, label=label, data=data)
    history.versions.append(version)
    previous = history.current.get(target)
    history.current[target] = version.id
    if undoable and previous is not None:
        history.undo_stack.append(Change(target=target, from_id=previous, to_id=version.id, label=label))
        history.redo_stack.clear()
    return version


def record_panel(project: MangaProject, page: int, panel: int, kind: str, label: str) -> Version | None:
    result = project.panel_result(page, panel)
    if result is None or not result.chosen_attempt:
        return None
    target = panel_target(page, panel)
    first = target not in _history(project).current
    return record(project, target, kind, label, {"attempt": result.chosen_attempt, "image": result.image},
                  undoable=not first)


def record_lettering(project: MangaProject, page: int, kind: str, label: str) -> Version | None:
    lettering = project.page_lettering(page)
    if lettering is None:
        return None
    target = lettering_target(page)
    first = target not in _history(project).current
    data = {"bubbles": [b.model_dump(mode="json") for b in lettering.bubbles], "source": lettering.source}
    return record(project, target, kind, label, data, undoable=not first)


def apply_version(project: MangaProject, version: Version) -> int:
    """Make the project show `version`. Returns the page number that needs re-rendering."""
    kind, *rest = version.target.split(":")
    if kind == "panel":
        page, panel = int(rest[0]), int(rest[1])
        result = project.panel_result(page, panel)
        attempt = result.attempt(version.data["attempt"]) if result else None
        if attempt is None:
            raise KeyError(f"Attempt {version.data['attempt']} of panel {page}-{panel} is gone")
        result.use_attempt(attempt)
        result.status = {"accepted": "accepted", "needs_review": "needs_review"}.get(attempt.status, "unreviewed")
    elif kind == "lettering":
        page = int(rest[0])
        bubbles = [Bubble.model_validate(b) for b in version.data["bubbles"]]
        current = project.page_lettering(page)
        if current is None:
            project.lettering.append(PageLettering(page=page, bubbles=bubbles, source=version.data.get("source", "edited")))
        else:
            current.bubbles, current.source = bubbles, version.data.get("source", "edited")
    else:
        raise KeyError(f"Unknown target {version.target}")
    _history(project).current[version.target] = version.id
    return page


def undo(project: MangaProject) -> tuple[Change, int] | None:
    history = _history(project)
    if not history.undo_stack:
        return None
    change = history.undo_stack.pop()
    page = apply_version(project, history.version(change.from_id))  # from_id is never None for undoable changes
    history.redo_stack.append(change)
    return change, page


def redo(project: MangaProject) -> tuple[Change, int] | None:
    history = _history(project)
    if not history.redo_stack:
        return None
    change = history.redo_stack.pop()
    page = apply_version(project, history.version(change.to_id))
    history.undo_stack.append(change)
    return change, page


def restore(project: MangaProject, version_id: int) -> tuple[Change, int] | None:
    """Show an older version again (as a new, undoable change). None if it's already current."""
    history = _history(project)
    version = history.version(version_id)
    current = history.current.get(version.target)
    if current == version_id:
        return None
    page = apply_version(project, version)
    change = Change(target=version.target, from_id=current, to_id=version_id, label=f"Restore: {version.label}")
    if current is not None:
        history.undo_stack.append(change)
        history.redo_stack.clear()
    return change, page


def summary(project: MangaProject) -> dict[str, Any]:
    history = _history(project)
    return {
        "versions": [v.model_dump(mode="json") for v in history.versions],
        "current": history.current,
        "can_undo": bool(history.undo_stack), "can_redo": bool(history.redo_stack),
        "undo_label": history.undo_stack[-1].label if history.undo_stack else None,
        "redo_label": history.redo_stack[-1].label if history.redo_stack else None,
    }
