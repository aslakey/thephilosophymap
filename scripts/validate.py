"""
Validate referential integrity of the dimensional data model.

Checks, across every dimension declared in docs/data/dimensions/manifest.json:
  - dimension tables have unique, non-empty IDs and Names, and every row has
    a non-empty Description
  - every link row's DimensionID exists in its dimension table
  - every link row's PhilosopherID exists in philosophers.csv
  - no duplicate (PhilosopherID, DimensionID) pairs within one link table
  - per philosopher, Ranks for a given dimension are unique and start at 1
    with no gaps (1, 2, 3, ... not 1, 3, 4)
  - every philosopher has exactly one Rank=1 (primary) row per dimension

Also checks relations.csv: every ID referenced in InfluencedByIDs/InfluencedIDs
exists in philosophers.csv, and relations.csv has exactly one row per
philosopher (no more, no less).

Also checks that every philosopher has a row in every coords_*.csv map file
(coords_semantic_tsne.csv, coords_semantic_umap.csv, coords_node2vec_tsne.csv)
-- a philosopher missing from a coords file is invisible on that map view.

Usage:
    python scripts/validate.py             # run all checks, exit 1 on any failure
    python scripts/validate.py --report    # also print category counts per dimension
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.data_model import (  # noqa: E402
    COORDS_FILENAMES,
    load_coords,
    load_dimension,
    load_links,
    load_manifest,
    load_philosophers,
    load_relations,
    relations_path,
)


def check_dimension_table(key: str, dim_df: pd.DataFrame) -> list[str]:
    errors = []
    if dim_df["ID"].duplicated().any():
        dupes = dim_df.loc[dim_df["ID"].duplicated(), "ID"].tolist()
        errors.append(f"[{key}] duplicate dimension IDs: {dupes}")
    if dim_df["Name"].duplicated().any():
        dupes = dim_df.loc[dim_df["Name"].duplicated(), "Name"].tolist()
        errors.append(f"[{key}] duplicate dimension names: {dupes}")
    empty_names = dim_df[dim_df["Name"].str.strip() == ""]
    if not empty_names.empty:
        errors.append(f"[{key}] {len(empty_names)} row(s) with an empty Name")
    empty_desc = dim_df[dim_df["Description"].str.strip() == ""]
    if not empty_desc.empty:
        errors.append(f"[{key}] {len(empty_desc)} row(s) with an empty Description: {empty_desc['Name'].tolist()}")
    return errors


def check_links_table(key: str, dim_df: pd.DataFrame, links_df: pd.DataFrame, philosopher_ids: set[str]) -> list[str]:
    errors = []
    valid_dimension_ids = set(dim_df["ID"])

    bad_dim_refs = links_df.loc[~links_df["DimensionID"].isin(valid_dimension_ids)]
    if not bad_dim_refs.empty:
        errors.append(f"[{key}] {len(bad_dim_refs)} link(s) reference unknown DimensionID: {bad_dim_refs['DimensionID'].unique().tolist()}")

    bad_phil_refs = links_df.loc[~links_df["PhilosopherID"].isin(philosopher_ids)]
    if not bad_phil_refs.empty:
        errors.append(f"[{key}] {len(bad_phil_refs)} link(s) reference unknown PhilosopherID: {bad_phil_refs['PhilosopherID'].unique().tolist()}")

    dupes = links_df[links_df.duplicated(subset=["PhilosopherID", "DimensionID"], keep=False)]
    if not dupes.empty:
        errors.append(f"[{key}] duplicate (PhilosopherID, DimensionID) pairs: {dupes[['PhilosopherID', 'DimensionID']].drop_duplicates().values.tolist()}")

    for philosopher_id, group in links_df.groupby("PhilosopherID"):
        ranks = sorted(group["Rank"].tolist())
        expected = list(range(1, len(ranks) + 1))
        if ranks != expected:
            errors.append(f"[{key}] {philosopher_id} has non-contiguous ranks {ranks} (expected {expected})")

    missing_primary = philosopher_ids - set(links_df.loc[links_df["Rank"] == 1, "PhilosopherID"])
    if missing_primary:
        errors.append(f"[{key}] {len(missing_primary)} philosopher(s) missing a Rank=1 (primary) value: {sorted(missing_primary)}")

    return errors


def check_relations(philosopher_ids: set[str]) -> list[str]:
    errors = []
    if not relations_path().exists():
        return errors
    relations = load_relations()

    dupes = relations.loc[relations["ID"].duplicated(), "ID"].tolist()
    if dupes:
        errors.append(f"[relations] duplicate ID(s): {dupes}")

    missing_rows = philosopher_ids - set(relations["ID"])
    if missing_rows:
        errors.append(f"[relations] {len(missing_rows)} philosopher(s) missing a relations.csv row: {sorted(missing_rows)}")

    extra_rows = set(relations["ID"]) - philosopher_ids
    if extra_rows:
        errors.append(f"[relations] {len(extra_rows)} row(s) reference unknown philosopher ID: {sorted(extra_rows)}")

    for _, row in relations.iterrows():
        for col in ("InfluencedByIDs", "InfluencedIDs"):
            for ref_id in str(row.get(col, "")).split(";"):
                ref_id = ref_id.strip()
                if ref_id and ref_id not in philosopher_ids:
                    errors.append(f"[relations] {row['ID']} {col} references unknown ID {ref_id!r}")
    return errors


def check_coords(philosopher_ids: set[str]) -> list[str]:
    errors = []
    for filename in COORDS_FILENAMES:
        coords_df = load_coords(filename)
        if coords_df.empty or "ID" not in coords_df.columns:
            errors.append(f"[{filename}] file is missing or has no ID column")
            continue
        missing = philosopher_ids - set(coords_df["ID"])
        if missing:
            errors.append(f"[{filename}] {len(missing)} philosopher(s) missing a coordinate row (invisible on this map view): {sorted(missing)}")
        extra = set(coords_df["ID"]) - philosopher_ids
        if extra:
            errors.append(f"[{filename}] {len(extra)} coordinate row(s) reference unknown philosopher ID: {sorted(extra)}")
    return errors


def print_report(key: str, dim_df: pd.DataFrame, links_df: pd.DataFrame) -> None:
    counts = links_df[links_df["Rank"] == 1]["DimensionID"].value_counts()
    id_to_name = dict(zip(dim_df["ID"], dim_df["Name"], strict=True))
    print(f"\n=== {key} ({len(dim_df)} categories) -- primary-value counts ===")
    for dim_id, count in counts.sort_values(ascending=False).items():
        print(f"  {count:4d}  {id_to_name.get(dim_id, dim_id)}")
    unused = set(dim_df["ID"]) - set(links_df["DimensionID"])
    if unused:
        unused_names = [id_to_name[i] for i in unused]
        print(f"  (unused categories: {unused_names})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="also print per-dimension category counts")
    args = parser.parse_args()

    philosophers = load_philosophers()
    philosopher_ids = set(philosophers["ID"])

    duplicate_ids = philosophers.loc[philosophers["ID"].duplicated(), "ID"].tolist()

    all_errors: list[str] = []
    if duplicate_ids:
        all_errors.append(f"[philosophers] duplicate IDs: {duplicate_ids}")

    manifest = load_manifest()
    for entry in manifest:
        key = entry["key"]
        dim_df = load_dimension(key)
        links_df = load_links(key)

        all_errors.extend(check_dimension_table(key, dim_df))
        all_errors.extend(check_links_table(key, dim_df, links_df, philosopher_ids))

        if args.report:
            print_report(key, dim_df, links_df)

    all_errors.extend(check_relations(philosopher_ids))
    all_errors.extend(check_coords(philosopher_ids))

    print(f"\n{len(manifest)} dimensions checked across {len(philosophers)} philosophers.")

    if all_errors:
        print(f"\n{len(all_errors)} problem(s) found:")
        for err in all_errors:
            print(f"  - {err}")
        sys.exit(1)

    print("All checks passed.")


if __name__ == "__main__":
    main()
