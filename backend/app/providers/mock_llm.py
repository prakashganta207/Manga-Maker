"""Mock LLM: builds a deterministic manga script from the story's sentences.

No AI here — just simple text rules — so the whole app works offline, for free,
and gives the same output for the same story every time (great for tests).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

from .base import LLMProvider, LLMResponse, ProviderError

# Capitalised words that are usually NOT names.
_STOPWORDS = set("""
A About Above After Again Ah All Also Although An And Another Any Are As At Back Be Because
Before Behind Below Beside Between Both But By Can Could Day Did Do Does Down During Each
Even Ever Every Everyone Everything Far Few Finally First For From Good Had Has Have He Hello
Her Here Hers Him His How However I If In Inside Instead Into Is It Its Just Last Later Let
Like Long Many Maybe Me Meanwhile More Morning Most Much Must My Never Next Night No None Nor
Not Nothing Now Of Off Oh Ok Okay On Once One Only Or Other Our Out Outside Over Perhaps Please
Quickly Quietly Rain Right Said Same Seconds She Should Silence Since So Some Someone Something
Somewhere Soon Still Such Suddenly Than Thank Thanks That The Their Them Then There These They
This Those Though Through Thus To Today Together Tomorrow Tonight Too Two Under Until Up Us
Very Wait Was We Well Were What When Where Whether Which While Who Why Will With Without Would
Yes Yesterday Yet You Your Monday Tuesday Wednesday Thursday Friday Saturday Sunday January
February March April May June July August September October November December God Hey Hi
Run Stop Look Come Go No Don Help Sorry Three Four Five Years Hours Minutes Everybody Nobody
""".split())

_SETTINGS = [
    ("rooftop", "a school rooftop"), ("classroom", "a classroom"), ("school", "a school"),
    ("forest", "a dense forest"), ("woods", "the woods"), ("mountain", "a mountain path"),
    ("beach", "a beach"), ("sea", "the seaside"), ("ocean", "the ocean shore"),
    ("river", "a riverbank"), ("lake", "a lakeside"), ("station", "a train station"),
    ("train", "a train carriage"), ("street", "a city street"), ("alley", "a narrow alley"),
    ("city", "a city"), ("town", "a small town"), ("village", "a village"),
    ("kitchen", "a kitchen"), ("bedroom", "a bedroom"), ("room", "a room"),
    ("house", "a house"), ("shop", "a small shop"), ("cafe", "a cafe"), ("café", "a cafe"),
    ("garden", "a garden"), ("park", "a park"), ("temple", "an old temple"),
    ("shrine", "a shrine"), ("library", "a library"), ("castle", "a castle"),
    ("ship", "a ship deck"), ("space", "a spaceship"), ("lab", "a laboratory"),
    ("hospital", "a hospital"), ("bridge", "a bridge"), ("field", "an open field"),
]

_MOODS = [
    (("afraid", "fear", "scared", "dark", "shadow", "tremble", "danger", "storm"), "tense"),
    (("cry", "tears", "sad", "alone", "lost", "goodbye", "miss"), "melancholy"),
    (("laugh", "smile", "happy", "joy", "grin", "cheer"), "cheerful"),
    (("run", "shout", "scream", "fight", "crash", "explode", "rush", "!"), "dramatic"),
    (("quiet", "calm", "soft", "gentle", "peace", "still"), "calm"),
    (("wonder", "strange", "mystery", "glow", "secret", "magic"), "mysterious"),
]

_HAIR = ["short spiky black hair", "long straight silver hair", "messy brown hair with a cowlick",
         "twin-tail black hair with ribbons", "short wavy white hair", "shoulder-length hair with blunt bangs",
         "a tight bun of dark hair", "shaved sides and a long top braid"]
_OUTFIT = ["a dark school uniform with a striped tie", "a long hooded traveling cloak",
           "a work apron over a plain shirt", "a sailor-collar uniform and knee socks",
           "a patched jacket with rolled sleeves", "a high-collared coat with brass buttons",
           "a light kimono-style top with a sash", "a baggy hoodie and cargo pants"]
_FEATURES = ["sharp determined eyes, slim build", "round glasses, freckles, small build",
             "a scar across the left cheek, tall", "large expressive eyes, cheerful face",
             "tired eyes with dark circles, lanky", "a small mole under one eye, calm expression",
             "thick eyebrows, broad shoulders", "an old wristwatch, gentle smile"]

_PRONOUNS = re.compile(r"\b(he|she|they|him|her|them|his|their)\b", re.IGNORECASE)


def _stable_index(text: str, size: int, salt: str = "") -> int:
    # hashlib (not hash()) so results don't change between Python runs.
    digest = hashlib.sha256((salt + text).encode("utf-8")).hexdigest()
    return int(digest, 16) % size


def normalise_text(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    text = normalise_text(text)
    if not text:
        return []
    raw = re.findall(r'[^.!?]*[.!?]+"?(?=\s|$)|[^.!?]+$', text)
    sentences: list[str] = []
    for part in (p.strip() for p in raw):
        if not part:
            continue
        # '"Run!" shouted Ken.' splits after "Run!" — glue the lowercase tail back on.
        # Same for a short speech tag after a quote: '"What?" Mira whispered.'
        short_tag = sentences and sentences[-1].endswith('"') and '"' not in part and len(part.split()) <= 4
        if sentences and (part[0].islower() or part[0] in ",;" or short_tag):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def find_names(sentences: list[str], limit: int = 3) -> list[str]:
    counts: Counter[str] = Counter()
    mid_sentence: set[str] = set()
    for sentence in sentences:
        for match in re.finditer(r"\b[A-Z][a-z]{1,}\b", sentence):
            word = match.group(0)
            if word in _STOPWORDS:
                continue
            before = sentence[: match.start()].rstrip()
            at_start = before == "" or before.endswith(('"', ".", "!", "?"))
            # Possessive / contraction like "Don't" -> skip ("Don" + "'t").
            if sentence[match.end(): match.end() + 1] == "'" and sentence[match.end() + 1: match.end() + 2] == "t":
                continue
            counts[word] += 1
            if not at_start:
                mid_sentence.add(word)
    names = [w for w, c in counts.most_common() if c >= 2 or w in mid_sentence]
    return names[:limit]


def split_quotes(sentence: str) -> tuple[list[str], str]:
    """Return (quoted parts, the rest of the sentence)."""
    quotes = [q.strip() for q in re.findall(r'"([^"]+)"', sentence) if q.strip()]
    rest = re.sub(r'"[^"]*"', " ", sentence)
    rest = re.sub(r"\s+", " ", rest).strip(" ,;")
    return quotes, rest


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;: ") + "…"


def _setting_for(text: str) -> str | None:
    lower = text.lower()
    for keyword, setting in _SETTINGS:
        if re.search(rf"\b{re.escape(keyword)}\b", lower):
            return setting
    return None


def _mood_for(text: str) -> str:
    lower = text.lower()
    for keywords, mood in _MOODS:
        if any(k in lower for k in keywords):
            return mood
    return "calm"


class MockLLMProvider(LLMProvider):
    name = "mock"

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any],
                      task: str, context: dict[str, Any]) -> LLMResponse:
        # Agent tasks are built by mock_agents (imported here to avoid a circular import).
        from . import mock_agents

        if task == "beat_sheet":
            return LLMResponse(mock_agents.build_beat_sheet(context["story"], int(context.get("max_beats", 12))),
                               model="mock")
        if task == "page_plan":
            return LLMResponse(mock_agents.build_page_plan(
                context["story"], context["beat_sheet"], int(context.get("max_pages", 2)),
                int(context.get("max_panels", 6))), model="mock")
        if task == "character_bible":
            return LLMResponse(mock_agents.build_character_bible(context["beat_sheet"]), model="mock")
        if task == "director":
            return LLMResponse(mock_agents.build_director_plan(context), model="mock")
        if task != "manga_script":
            raise ProviderError(f"Mock LLM does not know task '{task}'")
        return LLMResponse(self.build_script(
            context["story"],
            panels_per_page=int(context.get("panels_per_page", 4)),
            max_pages=int(context.get("max_pages", 2)),
        ), model="mock")

    # ------------------------------------------------------------------ #
    def build_script(self, story: str, *, panels_per_page: int = 4, max_pages: int = 2) -> dict[str, Any]:
        sentences = split_sentences(story)
        if not sentences:
            raise ProviderError("Story is empty")

        # Need at least one sentence per panel: split long sentences at commas if short.
        if len(sentences) < panels_per_page:
            expanded: list[str] = []
            for s in sentences:
                # Don't split sentences with dialogue: the quote would lose its speaker.
                pieces = [p.strip() for p in re.split(r",\s+", s) if p.strip()] if '"' not in s else [s]
                expanded.extend(pieces if len(pieces) > 1 else [s])
            sentences = expanded

        names = find_names(sentences) or ["Hero"]
        characters = [
            {
                "name": name,
                "role": "protagonist" if i == 0 else "supporting character",
                "hair": _HAIR[_stable_index(name, len(_HAIR), "hair")],
                "outfit": _OUTFIT[_stable_index(name, len(_OUTFIT), "outfit")],
                "features": _FEATURES[_stable_index(name, len(_FEATURES), "features")],
            }
            for i, name in enumerate(names)
        ]

        # Up to three sentences per panel before starting a new page, capped by max_pages.
        pages_needed = math.ceil(len(sentences) / (panels_per_page * 3))
        page_count = max(1, min(max_pages, pages_needed))
        total_panels = min(page_count * panels_per_page, len(sentences))
        page_count = math.ceil(total_panels / panels_per_page)

        chunks = [
            sentences[math.floor(i * len(sentences) / total_panels): math.floor((i + 1) * len(sentences) / total_panels)]
            for i in range(total_panels)
        ]

        shot_cycle = ["wide", "medium", "close-up", "medium", "wide", "close-up"]
        last_setting = _setting_for(story) or "a quiet street"
        last_chars: list[str] = [names[0]]
        panels: list[dict[str, Any]] = []

        for index, chunk in enumerate(chunks):
            text = " ".join(chunk)
            setting = _setting_for(text) or last_setting
            last_setting = setting

            present = [n for n in names if re.search(rf"\b{re.escape(n)}\b", text)]
            if re.search(r"\b(they|them|their|together|both)\b", text, re.IGNORECASE):
                present = list(names)  # plural pronoun -> everyone in the scene
            elif not present and _PRONOUNS.search(text):
                present = list(last_chars)
            if not present:
                present = [names[0]]
            last_chars = present

            dialogue: list[dict[str, str]] = []
            actions: list[str] = []
            prose: list[str] = []  # sentences without dialogue -> usable as narration
            for sentence in chunk:
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
                            # '"You came," she said' -> "You came."
                            line = re.sub(r"[,;:]$", ".", q.strip())
                            dialogue.append({"speaker": speaker, "text": _truncate(line, 120)})

            action = _truncate(" ".join(actions), 300) if actions else f"{present[0]} speaks"
            shot = shot_cycle[index % len(shot_cycle)]
            narration = _truncate(" ".join(prose), 110 if dialogue else 140) if prose else None

            panels.append({
                "panel_number": index % panels_per_page + 1,
                "characters": present,
                "action": action,
                "setting": setting,
                "shot": shot,
                "mood": _mood_for(text),
                "dialogue": dialogue,
                "narration": narration,
            })

        pages = [
            {"page_number": p + 1, "panels": panels[p * panels_per_page:(p + 1) * panels_per_page]}
            for p in range(page_count)
        ]
        title = f"{names[0]}'s Story" if names[0] != "Hero" else "A Short Story"
        return {"title": title, "characters": characters, "pages": pages}
