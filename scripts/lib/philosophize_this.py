"""Match Philosophize This! episode titles to philosophers on the map.

Titles are the only signal we have, so matching is conservative: a philosopher
is linked when their distinctive name appears in the title, plus a short list
of curated aliases (Confucianism, Daoism, the Buddha) and a few theme episodes
that name a school rather than a person (the Early Stoa, the Frankfurt School
introduction). Short surnames like Mill, West, and James are never matched
alone -- they have to appear as the full form.

The resulting table is many-to-many: Kant has eight episodes, and one episode
can name several people.
"""

from __future__ import annotations

import re
import unicodedata

# Surnames that collide with English words or other people. Matched only via
# EXTRA_ALIASES (the full form) rather than as a last-token fallback.
GENERIC_SURNAMES = {
    "smith",
    "james",
    "mill",
    "moore",
    "austin",
    "west",
    "han",
    "paz",
    "king",
    "more",
    "taylor",
    "russell",
    "hooks",
    "hook",
    "yang",
    "xi",
    "wang",
}

# Extra title phrases, already folded, that should count as this philosopher.
EXTRA_ALIASES: dict[str, list[str]] = {
    "P001": ["socrates", "socratic"],
    "P010": ["augustine", "saint augustine"],
    "P013": ["aquinas", "saint thomas aquinas", "thomas aquinas"],
    "P017": ["avicenna", "ibn sina"],
    "P018": ["averroes", "ibn rushd"],
    "P021": ["descartes"],
    "P031": ["adam smith"],
    "P035": ["john stuart mill"],
    "P039": ["william james"],
    "P042": ["g.e. moore", "g. e. moore"],
    "P047": ["j.l. austin", "j. l. austin"],
    "P054": ["de beauvoir", "beauvoir"],
    "P064": ["confucius", "confucianism", "kongzi"],
    "P067": ["laozi", "lao tzu", "daoism", "taoism"],
    "P068": ["zhuangzi", "chuang tzu", "daoism", "taoism"],
    "P083": ["al ghazali", "ghazali"],
    "P092": ["macintyre"],
    "P095": ["charles taylor"],
    "P098": ["peter singer"],
    "P099": ["cornel west"],
    "P100": ["bell hooks"],
    "P101": ["the buddha", "buddha", "siddhartha", "gautama"],
}

# Episode number -> philosopher IDs for titles that name a school, not a person.
THEME_EPISODES: dict[int, list[str]] = {
    11: ["P005"],  # Early Stoa -> Zeno of Citium
    12: ["P006", "P007"],  # Stoic ethics -> Epictetus, Seneca
    108: ["P057", "P058", "P059"],  # Frankfurt School intro
}


def fold(text: str) -> str:
    """Case-fold and strip diacritics so 'Nāgārjuna' matches 'Nagarjuna'."""
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.casefold()


def _normalize_phrase(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(text)).strip()


def aliases_for(philosopher: dict) -> list[str]:
    """Distinctive phrases that identify this philosopher in an episode title."""
    names = [
        philosopher.get("Name", ""),
        philosopher.get("ShortName", ""),
        re.sub(r"\([^)]*\)", "", philosopher.get("Name", "")).strip(),
        *re.findall(r"\(([^)]+)\)", philosopher.get("Name", "")),
        *EXTRA_ALIASES.get(philosopher.get("ID", ""), []),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        phrase = _normalize_phrase(raw)
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        out.append(phrase)
        last = phrase.split()[-1]
        if last not in GENERIC_SURNAMES and len(last) >= 5 and last not in seen:
            seen.add(last)
            out.append(last)
    return out


def parse_episode_number(title: str) -> int | None:
    match = re.search(r"episode\s*#?\s*(\d+)", fold(title))
    return int(match.group(1)) if match else None


def title_matches(title: str, philosopher: dict) -> bool:
    haystack = f" {_normalize_phrase(title)} "
    for alias in aliases_for(philosopher):
        if len(alias) < 4:
            continue
        needle = f" {alias} "
        if needle in haystack:
            return True
    return False


def match_episode(title: str, philosophers: list[dict]) -> list[str]:
    """Return philosopher IDs this episode should link to, in map order."""
    hits: list[str] = []
    seen: set[str] = set()
    number = parse_episode_number(title)
    if number in THEME_EPISODES:
        for pid in THEME_EPISODES[number]:
            if pid not in seen:
                seen.add(pid)
                hits.append(pid)
    for philosopher in philosophers:
        pid = philosopher["ID"]
        if pid in seen:
            continue
        if title_matches(title, philosopher):
            seen.add(pid)
            hits.append(pid)
    return hits
