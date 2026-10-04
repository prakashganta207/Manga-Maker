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
            candidates = [e for e in (target - 1, target) if start < e < len(panels) and e - start <= max_panels]
            end = max(candidates, key=lambda e: (intensity[panels[e - 1]["beat"]], e)) if candidates else target
        chunk = panels[start:end][:max_panels]
        start = end
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


def build_character_bible(beat_sheet: dict) -> dict[str, Any]:
    characters = []
    for c in beat_sheet["characters"]:
        name = c["name"]
        tags = {
            "hair": _HAIR[_stable_index(name, len(_HAIR), "hair")],
            "eyes": _EYES[_stable_index(name, len(_EYES), "eyes")],
            "outfit": _OUTFIT[_stable_index(name, len(_OUTFIT), "outfit")],
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
