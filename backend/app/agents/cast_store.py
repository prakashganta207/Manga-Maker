"""Per-project cast storage, so a later chapter can reuse the same characters.

    OUTPUT_DIR/projects/<project_id>/cast.json              approved bible entries
    OUTPUT_DIR/projects/<project_id>/characters/<slug>/...  their sheets and reference crops

A new job started with the same project_id copies these into its own folder, and the
Character Designer skips them (they keep their look, seeds and approval).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .state import CharacterEntry, MangaProject


class CastStore:
    def __init__(self, output_dir: Path):
        self.root = output_dir / "projects"

    def _dir(self, project_id: str) -> Path:
        return self.root / project_id

    def load(self, project_id: str) -> dict[str, CharacterEntry]:
        path = self._dir(project_id) / "cast.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {c["name"].lower(): CharacterEntry.model_validate(c) for c in data.get("characters", [])}

    def save(self, project: MangaProject, job_dir: Path) -> int:
        """Store the project's approved characters (merging with what's there). Returns count."""
        approved = [c for c in project.characters if c.approved]
        if not approved:
            return 0
        folder = self._dir(project.project_id)
        cast = self.load(project.project_id)
        for character in approved:
            source = job_dir / "characters" / character.slug
            target = folder / "characters" / character.slug
            if source.exists():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            stored = character.model_copy(deep=True)
            stored.reused_from = stored.reused_from or project.project_id
            cast[character.name.lower()] = stored
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "cast.json").write_text(json.dumps({
            "project_id": project.project_id,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "characters": [c.model_dump(mode="json") for c in cast.values()],
        }, indent=2), encoding="utf-8")
        return len(approved)

    def install(self, project_id: str, job_dir: Path) -> dict[str, CharacterEntry]:
        """Copy a stored cast's images into a job folder; return the entries for reuse."""
        cast = self.load(project_id)
        for character in cast.values():
            source = self._dir(project_id) / "characters" / character.slug
            target = job_dir / "characters" / character.slug
            if source.exists() and not target.exists():
                shutil.copytree(source, target)
        return cast

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        projects = []
        for path in sorted(self.root.glob("*/cast.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            projects.append({
                "project_id": data["project_id"],
                "updated_at": data.get("updated_at", ""),
                "characters": [{"name": c["name"], "approved": c.get("approved", False),
                                "image": c.get("sheets", {}).get("views", {}).get("front")}
                               for c in data.get("characters", [])],
            })
        return sorted(projects, key=lambda p: p["updated_at"], reverse=True)
