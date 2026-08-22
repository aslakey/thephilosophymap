"""
Shared fixtures.

Every test runs against a small synthetic dataset written into a tmp_path, with
the data model pointed at it via set_data_dir(). Nothing here ever reads or
writes the real docs/data/ -- see test_isolation.py, which asserts that.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# The scripts are standalone entry points rather than an installed package, so
# they're imported the same way they run: with scripts/ on sys.path.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib import data_model  # noqa: E402

# key -> (label, id prefix, [(name, description), ...])
DIMENSION_FIXTURE = {
    "region": (
        "Region",
        "RG",
        [
            ("Europe", "The European landmass and its philosophical traditions."),
            ("Asia", "The Asian landmass and its philosophical traditions."),
        ],
    ),
    "primary_topic": (
        "Primary Topics",
        "PT",
        [
            ("Ethics", "The study of right action and the good life."),
            ("Metaphysics", "The study of the fundamental nature of reality."),
            ("Logic", "The study of valid inference."),
        ],
    ),
}

PHILOSOPHER_FIXTURE = [
    {
        "ID": "P001",
        "Name": "Alpha",
        "BirthYear": "-400",
        "DeathYear": "-330",
        "CoreTeachings": "Teachings of Alpha.",
        "HistoricalContext": "Context of Alpha.",
        "KeyWorks": "Alpha's Book",
        "Tags": "ancient",
    },
    {
        "ID": "P002",
        "Name": "Beta",
        "BirthYear": "1600",
        "DeathYear": "1670",
        "CoreTeachings": "Teachings of Beta.",
        "HistoricalContext": "Context of Beta.",
        "KeyWorks": "Beta's Book",
        "Tags": "modern",
    },
    {
        "ID": "P003",
        "Name": "Gamma",
        "BirthYear": "1900",
        "DeathYear": "1980",
        "CoreTeachings": "Teachings of Gamma.",
        "HistoricalContext": "Context of Gamma.",
        "KeyWorks": "Gamma's Book",
        "Tags": "contemporary",
    },
]

# (PhilosopherID, DimensionID, Rank) per dimension key
LINK_FIXTURE = {
    "region": [
        ("P001", "RG1", 1),
        ("P002", "RG1", 1),
        ("P003", "RG2", 1),
    ],
    "primary_topic": [
        ("P001", "PT1", 1),
        ("P001", "PT2", 2),
        ("P002", "PT2", 1),
        ("P003", "PT3", 1),
    ],
}

RELATIONS_FIXTURE = [
    {"ID": "P001", "InfluencedByIDs": "", "InfluencedIDs": "P002"},
    {"ID": "P002", "InfluencedByIDs": "P001", "InfluencedIDs": ""},
    {"ID": "P003", "InfluencedByIDs": "", "InfluencedIDs": ""},
]

COORDS_FIXTURE = {
    "P001": (0.0, 0.0),
    "P002": (10.0, 10.0),
    "P003": (20.0, 20.0),
}


def write_csv(path: Path, columns: list[str], rows: list[tuple | list]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)


def build_dataset(root: Path) -> Path:
    """Write a complete, valid dataset under `root` and return it."""
    root.mkdir(parents=True, exist_ok=True)

    manifest = []
    for key, (label, prefix, categories) in DIMENSION_FIXTURE.items():
        rows = [
            (f"{prefix}{i}", name, description)
            for i, (name, description) in enumerate(categories, start=1)
        ]
        write_csv(root / "dimensions" / f"{key}.csv", ["ID", "Name", "Description"], rows)
        write_csv(
            root / "links" / f"{key}_links.csv",
            ["PhilosopherID", "DimensionID", "Rank"],
            LINK_FIXTURE[key],
        )
        manifest.append({
            "key": key,
            "label": label,
            "file": f"dimensions/{key}.csv",
            "linksFile": f"links/{key}_links.csv",
        })

    manifest_file = root / "dimensions" / "manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    write_csv(
        root / "philosophers.csv",
        data_model.PHILOSOPHER_COLUMNS,
        [[p[col] for col in data_model.PHILOSOPHER_COLUMNS] for p in PHILOSOPHER_FIXTURE],
    )
    write_csv(
        root / "relations.csv",
        data_model.RELATIONS_COLUMNS,
        [[r[col] for col in data_model.RELATIONS_COLUMNS] for r in RELATIONS_FIXTURE],
    )

    for filename in data_model.COORDS_FILENAMES:
        # The semantic files carry an extra embedding column in the real data;
        # keep one here so placeholder positioning is exercised against both
        # shapes (with and without the extra column).
        if "semantic" in filename:
            columns = ["ID", "x", "y", "embedding"]
            rows = [[pid, x, y, "0.1|0.2"] for pid, (x, y) in COORDS_FIXTURE.items()]
        else:
            columns = ["ID", "x", "y"]
            rows = [[pid, x, y] for pid, (x, y) in COORDS_FIXTURE.items()]
        write_csv(root / filename, columns, rows)

    return root


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """A throwaway dataset that the data model is pointed at for one test."""
    root = build_dataset(tmp_path / "data")
    data_model.set_data_dir(root)
    monkeypatch.setenv(data_model.DATA_DIR_ENV_VAR, str(root))
    yield root
    data_model.set_data_dir(None)


def _hash_tree(root: Path) -> dict[str, str]:
    import hashlib

    digests = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digests[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


@pytest.fixture(scope="session", autouse=True)
def guard_real_data():
    """Fail the run if any test mutated the committed dataset.

    A test suite that writes to docs/data/ would corrupt the site's real data
    and produce spurious git diffs, so the whole tree is content-hashed before
    and after the session.
    """
    real_data_dir = REPO_ROOT / "docs" / "data"
    before = _hash_tree(real_data_dir)
    yield
    after = _hash_tree(real_data_dir)
    if before != after:
        changed = sorted(
            set(before) ^ set(after)
            | {name for name in set(before) & set(after) if before[name] != after[name]}
        )
        raise AssertionError(
            "tests mutated the real docs/data/ -- these files changed: " + ", ".join(changed)
        )
