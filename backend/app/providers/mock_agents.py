"""Deterministic stand-ins for every agent, used when no LLM key is configured.

They follow the same rules as the real agents (so the rest of the pipeline gets
realistic input), using simple text heuristics over the story's sentences.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .mock_llm import (_HAIR, _OUTFIT, _PRONOUNS, _mood_for, _setting_for, _stable_index, _truncate,
                       find_names, split_quotes, split_sentences)

_INTENSITY = {"calm": 1, "cheerful": 2, "melancholy": 3, "mysterious": 3, "tense": 4, "dramatic": 4}

_SFX = [
    (("crash", "smash", "shatter"), "CRASH"), (("explode", "explosion", "blast"), "BOOM"),
    (("slam", "door"), "SLAM"), (("knock",), "KNOCK KNOCK"), (("run", "ran", "sprint", "dash"), "TAP TAP TAP"),
    (("wind", "gust"), "WHOOSH"), (("glow", "light", "shine"), "VMMMM"), (("punch", "hit", "strike"), "WHAM"),
    (("ring", "phone", "bell"), "RIIING"), (("rain",), "SHHHH"), (("laugh",), "HAHA"),
    (("thunder",), "RUMBLE"), (("sword", "blade", "clash"), "CLANG"), (("gasp",), "GASP"),
]


def _beat_kind(index: int, total: int, mood: str, intensity: int, climax_index: int) -> str:
    if index == climax_index:
        return "climax"
    if index > climax_index:
        return "resolution"
    if index == 0:
        return "setup"
    if intensity >= 4:
        return "action"
    if mood == "mysterious":
        return "reveal"
    if mood in ("calm", "melancholy"):
        return "quiet"
    return "rising"


def build_beat_sheet(story: str, max_beats: int = 12) -> dict[str, Any]:
    sentences = split_sentences(story)
    names = find_names(sentences, limit=4) or ["Hero"]
    count = min(12, max_beats, max(2, len(sentences)))
    if len(sentences) < 2:
        sentences = sentences * 2
    groups = [sentences[math.floor(i * len(sentences) / count): math.floor((i + 1) * len(sentences) / count)]
              for i in range(count)]
    texts = [" ".join(g) for g in groups]
    moods = [_mood_for(t) for t in texts]
    intensities = [min(5, _INTENSITY.get(m, 2) + (1 if "!" in t else 0)) for m, t in zip(moods, texts)]
    # Climax: the most intense beat, preferring later ones (stories build up to it).
    start = len(texts) // 2
    climax_index = max(range(start, len(texts)), key=lambda i: (intensities[i], i))
    intensities[climax_index] = 5
    beats = [{
        "id": i + 1,
        "summary": _truncate(text, 400),
        "emotion": moods[i],
        "intensity": intensities[i],
        "kind": _beat_kind(i, len(texts), moods[i], intensities[i], climax_index),
    } for i, text in enumerate(texts)]
    characters = [{
        "name": name,
        "role": "protagonist" if i == 0 else "supporting character",
        "importance": "main" if i < 2 else "supporting",
        "summary": f"Appears in the story as {name}.",
    } for i, name in enumerate(names)]
    title = f"{names[0]}'s Story" if names[0] != "Hero" else "A Short Story"
    return {
        "title": title,
        "logline": _truncate(re.sub(r'"', "", sentences[0]), 280),
        "emotional_arc": f"{moods[0]} -> {moods[climax_index]} -> {moods[-1]}",
        "beats": beats,
        "climax_beat": climax_index + 1,
        "characters": characters,
    }


def _sfx_for(text: str) -> list[str]:
    lower = text.lower()
    for keys, sound in _SFX:
        if any(re.search(rf"\b{k}", lower) for k in keys):
            return [sound]
    return []


def _panel_from_text(text: str, beat: dict, names: list[str], last_chars: list[str], last_setting: str,
                     size: str, purpose: str) -> dict[str, Any]:
    setting = _setting_for(text) or last_setting
    present = [n for n in names if re.search(rf"\b{re.escape(n)}\b", text)]
    if re.search(r"\b(they|them|their|together|both)\b", text, re.IGNORECASE):
        present = list(names[:3])
    elif not present and _PRONOUNS.search(text):
        present = list(last_chars)
    if not present:
        present = [names[0]]
    dialogue, actions, prose = [], [], []
    for sentence in split_sentences(text):
        quotes, rest = split_quotes(sentence)
        if rest:
            actions.append(rest)
        if rest and not quotes:
            prose.append(rest)
        if quotes:
            named = [n for n in names if re.search(rf"\b{re.escape(n)}\b", rest)]
            speaker = named[0] if named else present[0]
            for q in quotes:
                if len(dialogue) < 2:
                    dialogue.append({"speaker": speaker, "text": _truncate(re.sub(r"[,;:]$", ".", q.strip()), 120)})
    narration = _truncate(" ".join(prose), 110 if dialogue else 140) if prose and beat["kind"] in (
        "setup", "quiet", "resolution", "reveal") else None
    return {
        "panel_number": 1, "beat": beat["id"], "purpose": purpose, "size": size,
        "characters": present[:4], "action": _truncate(" ".join(actions), 300) if actions else f"{present[0]} speaks",
        "setting": setting, "emotion": beat["emotion"], "dialogue": dialogue, "narration": narration,
        "sfx": _sfx_for(text),
    }


def build_page_plan(story: str, beat_sheet: dict, max_pages: int = 2, max_panels: int = 6) -> dict[str, Any]:
    names = [c["name"] for c in beat_sheet["characters"]]
    beats = beat_sheet["beats"]
    climax_id = beat_sheet["climax_beat"]
    last_setting = _setting_for(story) or "a quiet street"
    last_chars = [names[0]]
    panels: list[dict] = []

    for beat in beats:
        sentences = split_sentences(beat["summary"])
        if beat["kind"] == "action" and len(sentences) >= 2:
            # Fast action: split into several small panels.
            half = math.ceil(len(sentences) / 2)
            parts = [(" ".join(sentences[:half]), "small"), (" ".join(sentences[half:]), "small")]
        elif beat["kind"] == "action":
            parts = [(beat["summary"], "small")]
        elif beat["id"] == climax_id:
            parts = [(beat["summary"], "large")]
        elif beat["kind"] == "setup":
            parts = [(beat["summary"], "large")]
        else:
            parts = [(beat["summary"], "medium")]
        for text, size in parts:
            purpose = {"setup": "Establish the scene", "climax": "Deliver the climax",
                       "action": "Keep the action moving", "quiet": "Let the emotion land",
                       "reveal": "Reveal something new", "resolution": "Resolve the story"}.get(
                beat["kind"], "Advance the story")
            panel = _panel_from_text(text, beat, names, last_chars, last_setting, size, purpose)
            last_chars, last_setting = panel["characters"], panel["setting"]
            panels.append(panel)

    # Too many panels for the page budget? Merge neighbouring non-climax panels.
    budget = max_pages * min(max_panels, 5)
    while len(panels) > budget:
        for i in range(len(panels) - 1):
            a, b = panels[i], panels[i + 1]
            if a["beat"] == b["beat"]:  # only merge panels of the same beat (keeps every beat covered)
                a["action"] = _truncate(f"{a['action']} {b['action']}", 300)
                a["dialogue"] = (a["dialogue"] + b["dialogue"])[:3]
                a["characters"] = list(dict.fromkeys(a["characters"] + b["characters"]))[:4]
                a["sfx"] = (a["sfx"] + b["sfx"])[:3]
                del panels[i + 1]
                break
        else:
            panels = panels[:budget]

    # Paginate: even split, but end each page on its most intense panel when possible.
    intensity = {b["id"]: b["intensity"] for b in beats}
    page_count = max(1, min(max_pages, math.ceil(len(panels) / min(5, max_panels))))
    pages, start = [], 0
    for p in range(page_count):
        remaining_pages = page_count - p
        if remaining_pages == 1:
            end = len(panels)
        else:
            target = start + math.ceil((len(panels) - start) / remaining_pages)
            per_page = min(5, max_panels)  # 5 or fewer panels keeps big slots available
            candidates = [e for e in (target - 1, target, target + 1)
                          if start < e < len(panels) and e - start <= per_page
                          and len(panels) - e <= (remaining_pages - 1) * per_page]
            end = max(candidates, key=lambda e: (intensity[panels[e - 1]["beat"]], e)) if candidates else target
        chunk = panels[start:end][:max_panels]
        start = end
        # The mock treats each page as one scene: one setting per page (the first one detected).
        page_setting = chunk[0]["setting"]
        for x in chunk:
            x["setting"] = page_setting
        # One large panel per page (the most intense), single-panel page = splash.
        larges = [x for x in chunk if x["size"] == "large"]
        if len(larges) > 1:
            keep = max(larges, key=lambda x: (intensity[x["beat"]], x["beat"] == climax_id))
            for x in larges:
                if x is not keep:
                    x["size"] = "medium"
        if len(chunk) == 1:
            chunk[0]["size"] = "splash"
        for n, panel in enumerate(chunk, start=1):
            panel["panel_number"] = n
        last = chunk[-1]
        pages.append({"page_number": p + 1, "panels": chunk,
                      "page_turn": _truncate(f"Ends on: {last['action']}", 200)})
    return {"pages": pages}


# --------------------------------------------------------------------------- character designer
_EYES = ["large round dark eyes", "narrow sharp eyes", "bright almond eyes", "sleepy half-closed eyes",
         "wide curious eyes", "calm downturned eyes"]
_ACCESSORIES = ["a red scarf", "round glasses", "a silver hairpin", "fingerless gloves", "a canvas backpack",
                "a wristwatch", "none", "a small pendant necklace"]
_MARKS = ["none", "a small scar on the left cheek", "a beauty mark under the right eye", "freckles",
          "a bandage on the nose", "none"]
_BODY = ["slim and tall", "short and wiry", "athletic build", "average build", "lanky", "stocky and broad"]
_AGES = ["mid teens", "late teens", "early twenties", "late twenties", "thirties"]
_PERSONALITY = ["determined but secretly anxious", "cheerful and impulsive", "quiet and observant",
                "sarcastic with a kind heart", "gentle and patient", "proud and competitive"]


def _distinct(options: list[str], name: str, salt: str, used: set[str]) -> str:
    """Deterministic pick that avoids options already given to another character."""
    start = _stable_index(name, len(options), salt)
    for k in range(len(options)):
        choice = options[(start + k) % len(options)]
        if choice not in used:
            used.add(choice)
            return choice
    return options[start]


def build_character_bible(beat_sheet: dict) -> dict[str, Any]:
    characters = []
    used_hair: set[str] = set()
    used_outfit: set[str] = set()
    for c in beat_sheet["characters"]:
        name = c["name"]
        tags = {
            "hair": _distinct(_HAIR, name, "hair", used_hair),
            "eyes": _EYES[_stable_index(name, len(_EYES), "eyes")],
            "outfit": _distinct(_OUTFIT, name, "outfit", used_outfit),
            "accessories": _ACCESSORIES[_stable_index(name, len(_ACCESSORIES), "acc")],
            "distinguishing_marks": _MARKS[_stable_index(name, len(_MARKS), "marks")],
        }
        body = _BODY[_stable_index(name, len(_BODY), "body")]
        age = _AGES[_stable_index(name, len(_AGES), "age")]
        characters.append({
            "name": name, "role": c["role"], "age_range": age, "body_type": body,
            "description": f"{name} is a {body} character in their {age}, with {tags['hair']}, "
                           f"{tags['eyes']} and {tags['outfit']}.",
            "visual_tags": tags,
            "personality": _PERSONALITY[_stable_index(name, len(_PERSONALITY), "pers")],
            "expression_range": ["neutral", "happy", "angry", "sad", "surprised"],
        })
    return {"characters": characters}


# --------------------------------------------------------------------------- director
def build_director_plan(context: dict) -> dict[str, Any]:
    from ..agents.director import is_peak, setting_key
    from ..agents.schemas import BeatSheet, PagePlan
    from ..pipeline.templates import best_template

    sheet = BeatSheet.model_validate(context["beat_sheet"])
    plan = PagePlan.model_validate(context["page_plan"])
    previous_setting = None
    pages = []
    for page in plan.pages:
        template = best_template([p.size for p in page.panels])
        panels = []
        for panel in page.panels:
            beat = sheet.beat(panel.beat)
            intensity = beat.intensity if beat else 2
            key = setting_key(panel.setting)
            if key != previous_setting:
                shot, angle = "establishing", "bird's eye" if intensity <= 2 else "high"
            elif is_peak(panel, sheet):
                shot, angle = ("extreme close-up" if panel.size == "small" else "close-up"), \
                    ("low" if intensity >= 4 else "eye level")
            elif panel.dialogue and len(panel.characters) >= 2:
                shot, angle = "over-the-shoulder", "eye level"
            elif beat and beat.kind == "action":
                shot, angle = "wide", "low"
            else:
                shot, angle = "medium", "high" if panel.emotion in ("melancholy", "sad") else "eye level"
            previous_setting = key
            who = " and ".join(panel.characters) or "the scene"
            focus = {"establishing": f"{who} small in the frame, the setting fills the panel",
                     "close-up": f"{who}'s face fills the frame, background dropped to screentone",
                     "extreme close-up": f"tight on {who}'s eyes",
                     "over-the-shoulder": f"over one shoulder toward {who}, speaker in the foreground",
                     "wide": f"{who} full body, motion lines across the panel",
                     "medium": f"{who} from the waist up, centred"}[shot]
            panels.append({"panel_number": panel.panel_number, "shot": shot, "angle": angle,
                           "composition": focus[:200]})
        pages.append({"page_number": page.page_number, "layout": template.id, "panels": panels})
    return {"pages": pages}


# ----------------------------------------------------------------------------- Editor (Phase 3)
# The mock Editor can't really "see", so it checks the few things plain code can measure
# (is the image greyscale? how similar is it to the references?) and uses a hash of the
# seed + prompt to simulate the occasional flawed drawing. Changing the seed or prompt (which
# is exactly what a redraw does) changes the outcome, so the redraw loop is exercised offline.
MOCK_FAIL_RATE = 35  # percent of drawings that get a "problem"

_MOCK_FAILURES = [
    ("anatomy", "The left hand looks malformed (fused fingers).",
     {"negative_add": ["bad hands", "fused fingers", "extra fingers"], "new_seed": True}),
    ("shot_angle", "The framing doesn't match the requested shot.", {"new_seed": False}),
    ("character_likeness", "The character's hair and outfit drift from the reference sheet.",
     {"ipadapter_weight": 0.85, "new_seed": True}),
    ("bubble_space", "The figures fill the whole frame; there is no calm area for the speech bubbles.",
     {"prompt_add": ["negative space", "simple background"], "new_seed": True}),
]


def _colourfulness(path: str) -> float:
    from PIL import Image, ImageStat
    try:
        with Image.open(path) as img:
            if img.mode in ("L", "1", "LA"):
                return 0.0
            r, g, b = (ImageStat.Stat(c).mean[0] for c in img.convert("RGB").resize((64, 64)).split())
            return max(abs(r - g), abs(g - b), abs(r - b))
    except OSError:
        return 0.0


def build_editor_review(context: dict[str, Any]) -> dict[str, Any]:
    key = f"{context.get('seed')}|{context.get('image_prompt_used', '')}|{context.get('page')}|{context.get('panel')}"
    roll = _stable_index(key, 100, "editor")
    scores = {name: 4 + (_stable_index(key, 2, name) if name not in ("anatomy",) else 0)
              for name in ("script_action", "characters", "people_count", "character_likeness", "shot_angle",
                           "emotion", "anatomy", "manga_style", "bubble_space")}
    problems, fix = [], {}
    clip = context.get("consistency") or {}
    if clip and min(clip.values()) < 0.62:
        scores["character_likeness"] = 3
    if _colourfulness(context.get("image_path", "")) > 12:
        scores["manga_style"] = 2
        problems.append("The panel is in colour; manga panels must be black and white.")
        fix = {"negative_add": ["color", "colorful"], "prompt_add": ["monochrome", "greyscale"]}
    if roll < MOCK_FAIL_RATE:
        criterion, problem, change = _MOCK_FAILURES[roll % len(_MOCK_FAILURES)]
        scores[criterion] = 2
        problems.append(problem)
        fix = {**fix, **change}
        if criterion == "shot_angle":
            fix["prompt_add"] = [context.get("shot", "medium") + " shot", context.get("angle", "eye level")]
    verdict = "fail" if problems else "pass"
    reasoning = (f"Mock review of page {context.get('page')} panel {context.get('panel')} "
                 f"(attempt {context.get('attempt')}). "
                 + ("; ".join(problems) if problems else "Composition, style and characters match the spec."))
    return {"scores": scores, "verdict": verdict, "problems": problems, "fix": fix, "reasoning": reasoning}


# ----------------------------------------------------------------------------- Panel Revision (Phase 4)
_REVISION_RULES = [
    # (keywords, changes) — a tiny "understanding" of common art-direction notes.
    (("angr", "furious", "mad", "rage"), {"emotion": "furious", "prompt_add": ["angry", "clenched teeth", "glaring"]}),
    (("sad", "cry", "tear"), {"emotion": "sad", "prompt_add": ["sad", "tears", "downcast eyes"]}),
    (("happ", "smil", "laugh", "joy"), {"emotion": "happy", "prompt_add": ["smile", "happy"]}),
    (("surpris", "shock", "scared", "afraid"), {"emotion": "shocked", "prompt_add": ["surprised", "wide eyes"]}),
    (("below", "low angle", "from under", "heroic"), {"angle": "low", "prompt_add": ["from below"], "keep_seed": False}),
    (("above", "high angle", "overhead"), {"angle": "high", "prompt_add": ["from above"], "keep_seed": False}),
    (("bird",), {"angle": "bird's eye", "prompt_add": ["bird's eye view"], "keep_seed": False}),
    (("close", "zoom in", "face"), {"shot": "close-up", "keep_seed": False}),
    (("wide", "zoom out", "far", "whole body", "full body"), {"shot": "wide", "keep_seed": False}),
    (("rain",), {"prompt_add": ["rain"]}),
    (("night", "dark"), {"prompt_add": ["night", "dark sky"]}),
]


def build_panel_revision(context: dict[str, Any]) -> dict[str, Any]:
    instruction = str(context.get("instruction", "")).lower()
    result = {"action": context.get("action", "a scene"), "emotion": context.get("emotion", "calm"),
              "shot": context.get("shot", "medium"), "angle": context.get("angle", "eye level"),
              "composition": context.get("composition", "centred subject"), "prompt_add": [],
              "prompt_remove": [], "negative_add": [], "keep_seed": True}
    matched = False
    for keywords, change in _REVISION_RULES:
        if any(k in instruction for k in keywords):
            matched = True
            for key, value in change.items():
                result[key] = result[key] + value if key == "prompt_add" else value
    if not matched:  # unknown note: pass its words through as tags
        words = re.sub(r"[^a-z0-9 ]", " ", instruction).split()
        result["prompt_add"] = [" ".join(words[:5])] if words else []
    result["composition"] = _truncate(f"{result['composition'].rstrip('.')}; {instruction.strip()}", 200)
    result["summary"] = _truncate(f"Revised for: {context.get('instruction', '').strip()}", 200)
    return result


# ----------------------------------------------------------------------------- Series memory (Phase 5)
def build_story_so_far(context: dict[str, Any]) -> dict[str, Any]:
    """Mock running summary: the earlier summary + this chapter's first, climax and last beats."""
    sheet = context["beat_sheet"]
    beats = sheet["beats"]
    climax = next((b for b in beats if b["id"] == sheet["climax_beat"]), beats[-1])
    picked = [beats[0], climax, beats[-1]] if len(beats) > 2 else beats
    chapter = " ".join(dict.fromkeys(b["summary"].rstrip(".") + "." for b in picked))
    chapter_summary = _truncate(f"Chapter {context.get('chapter', 1)}: {chapter}", 500)
    previous = (context.get("story_so_far") or "").strip()
    summary = _truncate(f"{previous} {chapter_summary}".strip(), 1500)
    threads = [_truncate(f"What happens after: {beats[-1]['summary']}", 200)]
    names = [c["name"] for c in sheet.get("characters", [])]
    notes = [f"{n} appeared in chapter {context.get('chapter', 1)}" for n in names[:4]]
    return {"summary": summary, "chapter_summary": chapter_summary, "open_threads": threads, "character_notes": notes}
