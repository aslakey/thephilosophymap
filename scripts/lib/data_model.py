"""
Shared CSV I/O helpers for the philosophy map's dimensional data model.

Data model
----------
docs/data/philosophers.csv            fact table: ID, Name, BirthYear, DeathYear,
                                       CoreTeachings, HistoricalContext, KeyWorks, Tags
docs/data/relations.csv               unchanged: ID, InfluencedByIDs, InfluencedIDs
docs/data/coords_*.csv                unchanged: ID, x, y

docs/data/dimensions/manifest.json    THE CONTRACT: list of
                                       {key, label, file, linksFile}
docs/data/dimensions/<key>.csv        dimension table: ID, Name, Description
docs/data/links/<key>_links.csv       link table: PhilosopherID, DimensionID, Rank
                                       (Rank=1 is the philosopher's primary value
                                       for that dimension, used for map coloring)

Every script that reads or writes this data should go through this module
instead of hand-rolling CSV paths, so the on-disk layout only needs to be
known in one place.

The data root defaults to docs/data/ but can be redirected with the
PHILOSOPHY_MAP_DATA_DIR environment variable or set_data_dir(); the test suite
uses this to run against a throwaway copy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "docs" / "data"

# Tests (and any other caller that must not touch the real data) point the whole
# model at a different directory, either by setting this environment variable
# before the process starts or by calling set_data_dir() in-process. Paths are
# therefore resolved through the functions below rather than fixed at import
# time -- importing a stale path constant is what makes a test suite silently
# rewrite docs/data/.
DATA_DIR_ENV_VAR = "PHILOSOPHY_MAP_DATA_DIR"

_data_dir_override: Path | None = None


def set_data_dir(path: str | Path | None) -> None:
    """Point every read/write in this module at `path` (None restores default)."""
    global _data_dir_override
    _data_dir_override = Path(path).expanduser().resolve() if path is not None else None


def data_dir() -> Path:
    if _data_dir_override is not None:
        return _data_dir_override
    env_value = os.environ.get(DATA_DIR_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_DATA_DIR


def dimensions_dir() -> Path:
    return data_dir() / "dimensions"


def links_dir() -> Path:
    return data_dir() / "links"


def manifest_path() -> Path:
    return dimensions_dir() / "manifest.json"


def philosophers_path() -> Path:
    return data_dir() / "philosophers.csv"


def relations_path() -> Path:
    return data_dir() / "relations.csv"


def coords_path(filename: str) -> Path:
    return data_dir() / filename

# 2D map coordinate files. Each has an ID column plus x, y, and (for the
# semantic ones) a raw embedding column -- see load_coords()/save_coords().
COORDS_FILENAMES = [
    "coords_semantic_tsne.csv",
    "coords_semantic_umap.csv",
    "coords_node2vec_tsne.csv",
]

PHILOSOPHER_COLUMNS = [
    "ID", "Name", "BirthYear", "DeathYear",
    "CoreTeachings", "HistoricalContext", "KeyWorks", "Tags",
]
DIMENSION_COLUMNS = ["ID", "Name", "Description"]
LINK_COLUMNS = ["PhilosopherID", "DimensionID", "Rank"]
RELATIONS_COLUMNS = ["ID", "InfluencedByIDs", "InfluencedIDs"]


class DataModelError(Exception):
    """Raised for data-model contract violations (unknown dimension key, etc.)."""


# ---------------------------------------------------------------------------
# Manifest (the contract)
# ---------------------------------------------------------------------------

def load_manifest() -> list[dict]:
    path = manifest_path()
    if not path.exists():
        raise DataModelError(
            f"{path} not found. Run scripts/migrations/0001_split_into_dimension_tables.py first."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_manifest(entries: list[dict]) -> None:
    dimensions_dir().mkdir(parents=True, exist_ok=True)
    with open(manifest_path(), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.write("\n")


def manifest_entry(key: str) -> dict:
    for entry in load_manifest():
        if entry["key"] == key:
            return entry
    known = [e["key"] for e in load_manifest()]
    raise DataModelError(f"Unknown dimension key {key!r}. Known keys: {known}")


def dimension_keys() -> list[str]:
    return [e["key"] for e in load_manifest()]


# ---------------------------------------------------------------------------
# Dimension tables
# ---------------------------------------------------------------------------

def dimension_path(key: str) -> Path:
    return data_dir() / manifest_entry(key)["file"]


def links_path(key: str) -> Path:
    return data_dir() / manifest_entry(key)["linksFile"]


def load_dimension(key: str) -> pd.DataFrame:
    path = dimension_path(key)
    if not path.exists():
        return pd.DataFrame(columns=DIMENSION_COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def save_dimension(key: str, df: pd.DataFrame) -> None:
    path = dimension_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    df[DIMENSION_COLUMNS].to_csv(path, index=False)


def load_links(key: str) -> pd.DataFrame:
    path = links_path(key)
    if not path.exists():
        return pd.DataFrame(columns=LINK_COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df["Rank"] = df["Rank"].astype(int)
    return df


def save_links(key: str, df: pd.DataFrame) -> None:
    path = links_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    df[LINK_COLUMNS].to_csv(path, index=False)


def next_dimension_id(dim_df: pd.DataFrame, prefix: str) -> str:
    """Return the next unused ID for a dimension table, e.g. prefix='SM' -> 'SM18'."""
    max_n = 0
    for existing_id in dim_df["ID"]:
        if str(existing_id).startswith(prefix):
            suffix = str(existing_id)[len(prefix):]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1}"


def find_dimension_id_by_name(dim_df: pd.DataFrame, name: str) -> str | None:
    """Case-insensitive exact match on Name -> ID, or None if not found."""
    matches = dim_df[dim_df["Name"].str.lower() == name.strip().lower()]
    if matches.empty:
        return None
    return matches.iloc[0]["ID"]


def suggest_similar_names(dim_df: pd.DataFrame, name: str, limit: int = 3) -> list[str]:
    import difflib
    return difflib.get_close_matches(name, dim_df["Name"].tolist(), n=limit, cutoff=0.4)


# ---------------------------------------------------------------------------
# Philosophers fact table
# ---------------------------------------------------------------------------

def load_philosophers() -> pd.DataFrame:
    path = philosophers_path()
    if not path.exists():
        return pd.DataFrame(columns=PHILOSOPHER_COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def save_philosophers(df: pd.DataFrame) -> None:
    path = philosophers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df[PHILOSOPHER_COLUMNS].to_csv(path, index=False)


def next_philosopher_id(philosophers_df: pd.DataFrame) -> str:
    max_n = 0
    for existing_id in philosophers_df["ID"]:
        digits = "".join(ch for ch in str(existing_id) if ch.isdigit())
        if digits:
            max_n = max(max_n, int(digits))
    return f"P{max_n + 1:03d}"


def resolve_philosopher_id(philosophers_df: pd.DataFrame, identifier: str) -> str | None:
    """Resolve a philosopher ID or exact (case-insensitive) Name to an ID."""
    identifier = identifier.strip()
    if identifier in set(philosophers_df["ID"]):
        return identifier
    matches = philosophers_df[philosophers_df["Name"].str.lower() == identifier.lower()]
    if matches.empty:
        return None
    return matches.iloc[0]["ID"]


# ---------------------------------------------------------------------------
# Relations (influence graph)
# ---------------------------------------------------------------------------

def load_relations() -> pd.DataFrame:
    path = relations_path()
    if not path.exists():
        return pd.DataFrame(columns=RELATIONS_COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def save_relations(df: pd.DataFrame) -> None:
    path = relations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df[RELATIONS_COLUMNS].to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Map coordinate files (docs/data/coords_*.csv)
# ---------------------------------------------------------------------------

def load_coords(filename: str) -> pd.DataFrame:
    path = coords_path(filename)
    if not path.exists():
        return pd.DataFrame(columns=["ID", "x", "y"])
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def save_coords(filename: str, df: pd.DataFrame) -> None:
    path = coords_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
