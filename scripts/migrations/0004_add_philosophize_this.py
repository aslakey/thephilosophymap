"""Build docs/data/philosophize_this.csv from the Philosophize This! catalog.

Fetches the public RSS feed and Apple Podcasts lookup, matches episode titles
to philosophers on the map, and writes the sidecar table the site reads.
Re-run when new episodes land; matching is conservative (see
scripts/lib/philosophize_this.py) so a title has to name the person.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.data_model import (  # noqa: E402
    load_philosophers,
    save_philosophize_this,
)
from lib.philosophize_this import match_episode, parse_episode_number  # noqa: E402

RSS_URL = "https://feeds.megaphone.fm/QCD6036500916"
ITUNES_URL = "https://itunes.apple.com/lookup?id=659155419&entity=podcastEpisode&limit=300"
APPLE_SHOW_URL = "https://podcasts.apple.com/us/podcast/philosophize-this/id659155419"


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "thephilosophymap/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def load_apple_urls() -> dict[int, str]:
    payload = json.loads(_get(ITUNES_URL))
    out: dict[int, str] = {}
    for row in payload.get("results", []):
        if row.get("wrapperType") != "podcastEpisode":
            continue
        number = parse_episode_number(row.get("trackName", ""))
        if number is None:
            continue
        url = (row.get("trackViewUrl") or "").split("&uo=")[0]
        if url:
            out[number] = url
    return out


def load_rss_episodes() -> list[dict]:
    root = ET.fromstring(_get(RSS_URL))
    episodes = []
    for item in root.find("channel").findall("item"):
        title = unescape(item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        number = parse_episode_number(title)
        if number is None or not title:
            continue
        episodes.append({"number": number, "title": title, "rss_link": link})
    episodes.sort(key=lambda e: e["number"])
    return episodes


def pick_url(episode: dict, apple_urls: dict[int, str]) -> str:
    if episode["number"] in apple_urls:
        return apple_urls[episode["number"]]
    if episode["rss_link"].startswith("http"):
        return episode["rss_link"]
    return APPLE_SHOW_URL


def build_rows(philosophers: list[dict], episodes: list[dict], apple_urls: dict[int, str]) -> list[dict]:
    rows = []
    seen: set[tuple[str, int]] = set()
    for episode in episodes:
        url = pick_url(episode, apple_urls)
        for pid in match_episode(episode["title"], philosophers):
            key = (pid, episode["number"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "PhilosopherID": pid,
                "Episode": str(episode["number"]),
                "Title": episode["title"],
                "URL": url,
            })
    return rows


def main() -> None:
    philosophers = load_philosophers().to_dict("records")
    episodes = load_rss_episodes()
    apple_urls = load_apple_urls()
    rows = build_rows(philosophers, episodes, apple_urls)
    save_philosophize_this(pd.DataFrame(rows))
    n_people = len({r["PhilosopherID"] for r in rows})
    print(
        f"Wrote {len(rows)} episode link(s) across {n_people} philosopher(s) "
        f"from {len(episodes)} catalogued episodes."
    )


if __name__ == "__main__":
    main()
