"""Matching Philosophize This! titles to philosophers, plus validation of the table."""

from __future__ import annotations

import pandas as pd
from lib.data_model import (
    PHILOSOPHIZE_THIS_COLUMNS,
    load_philosophize_this,
    save_philosophize_this,
)
from lib.philosophize_this import match_episode, parse_episode_number, title_matches
from test_validate import all_errors, run_main

PLATO = {"ID": "P002", "Name": "Plato", "ShortName": "Plato"}
MILL = {"ID": "P035", "Name": "John Stuart Mill", "ShortName": "Mill"}
JAMES = {"ID": "P039", "Name": "William James", "ShortName": "James"}
BEAUVOIR = {"ID": "P054", "Name": "Simone de Beauvoir", "ShortName": "Beauvoir"}
CONFUCIUS = {"ID": "P064", "Name": "Confucius (Kongzi)", "ShortName": "Confucius"}
LAOZI = {"ID": "P067", "Name": "Laozi (Lao Tzu)", "ShortName": "Laozi"}
BUDDHA = {"ID": "P101", "Name": "Siddhārtha Gautama (the Buddha)", "ShortName": "Buddha"}
NAGARJUNA = {"ID": "P074", "Name": "Nāgārjuna", "ShortName": "Nāgārjuna"}
ZENO = {"ID": "P005", "Name": "Zeno of Citium", "ShortName": "Zeno"}


def test_parse_episode_number_variants():
    assert parse_episode_number("Episode #004 - Plato") == 4
    assert parse_episode_number("Episode 118 - A Basic Look At Post-Modernism") == 118
    assert parse_episode_number("Episode #80 ... Feuerbach on Religion") == 80
    assert parse_episode_number("No number here") is None


def test_plato_matches_his_episode_not_aristotle():
    assert title_matches("Episode #004 - Plato", PLATO)
    assert not title_matches("Episode #005 - Aristotle Part 1", PLATO)


def test_generic_surnames_do_not_fire_alone():
    assert not title_matches("Episode #084 - William James on Truth", MILL)
    assert title_matches("Episode #084 - William James on Truth", JAMES)
    assert title_matches("How much freedom would you trade? (Foucault, Hobbes, John Stuart Mill)", MILL)


def test_curated_aliases():
    assert title_matches("Episode #008 - Confucianism", CONFUCIUS)
    assert title_matches("Episode #007 - Daoism", LAOZI)
    assert title_matches("Episode #009 - The Buddha", BUDDHA)
    assert title_matches("Episode #089 - Simone De Beauvoir", BEAUVOIR)


def test_diacritics_fold():
    assert title_matches("Episode about Nagarjuna", NAGARJUNA)


def test_theme_episode_early_stoa():
    people = [ZENO, PLATO]
    assert match_episode("Episode #011 - The Hellenistic Age Pt. 2 - The Early Stoa and the Cynics", people) == ["P005"]
    assert match_episode("Episode #004 - Plato", people) == ["P002"]


def test_round_trip_and_sort(data_root):
    rows = pd.DataFrame([
        {"PhilosopherID": "P002", "Episode": "4", "Title": "Episode #004 - Plato", "URL": "https://example.com/4"},
        {"PhilosopherID": "P002", "Episode": "2", "Title": "Earlier", "URL": "https://example.com/2"},
    ])
    save_philosophize_this(rows)
    loaded = load_philosophize_this()
    assert list(loaded.columns) == PHILOSOPHIZE_THIS_COLUMNS
    assert list(loaded["Episode"]) == ["2", "4"]


def test_validate_rejects_unknown_philosopher(data_root):
    save_philosophize_this(pd.DataFrame([{
        "PhilosopherID": "P999",
        "Episode": "1",
        "Title": "Nope",
        "URL": "https://example.com/1",
    }]))
    errors = " ".join(all_errors())
    assert "P999" in errors
    assert run_main() == 1


def test_validate_rejects_bad_url_and_episode(data_root):
    save_philosophize_this(pd.DataFrame([{
        "PhilosopherID": "P001",
        "Episode": "abc",
        "Title": "X",
        "URL": "not-a-url",
    }]))
    errors = " ".join(all_errors())
    assert "positive integer" in errors
    assert "non-http URL" in errors


def test_missing_file_is_not_an_error(data_root):
    assert run_main() == 0
