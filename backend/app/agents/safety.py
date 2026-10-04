"""Only original characters: rename well-known copyrighted characters if they appear."""

from __future__ import annotations

BLOCKED_CHARACTER_NAMES = {
    "naruto", "sasuke", "goku", "vegeta", "luffy", "zoro", "pikachu", "ash ketchum", "mario", "luigi",
    "link", "zelda", "sonic", "mickey", "mickey mouse", "minnie", "donald duck", "spider-man", "spiderman",
    "batman", "superman", "wonder woman", "iron man", "hulk", "elsa", "harry potter", "hermione",
    "totoro", "sailor moon", "doraemon", "astro boy", "gojo", "tanjiro", "nezuko", "eren", "levi",
    "light yagami", "ichigo", "edward elric", "shinji", "asuka", "deku", "all might", "saitama",
    "kirby", "darth vader", "yoda", "frodo", "gandalf", "sherlock holmes",
}

REPLACEMENT_NAMES = ["Aoi", "Ren", "Hana", "Sora", "Kei", "Mio", "Yuu", "Rin"]


def is_blocked(name: str) -> bool:
    return name.strip().lower() in BLOCKED_CHARACTER_NAMES


def rename_map(names: list[str]) -> dict[str, str]:
    """{blocked name (lowercase): new original name} for any blocked names in `names`."""
    taken = {n.lower() for n in names}
    replacements = (n for n in REPLACEMENT_NAMES if n.lower() not in taken)
    return {n.lower(): next(replacements, f"Original {i}") for i, n in enumerate(names) if is_blocked(n)}


def apply(name: str, renames: dict[str, str]) -> str:
    return renames.get(name.strip().lower(), name)
