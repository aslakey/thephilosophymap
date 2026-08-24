"""
CLI for adding, editing, and removing philosophers via a JSON spec file. This
is the main enforcement point for the controlled vocabulary: dimension values
in a spec are given **by name**, resolved against the existing dimension
tables, and rejected by default if the name doesn't already exist -- so new
philosophers can't silently reintroduce free-text drift into the dimensions.

Spec file format (JSON), all keys optional except "name" for `add`:
{
  "name": "Jane Doe",
  "short_name": "Doe",
  "birth_year": 1900,
  "death_year": 1980,
  "core_teachings": "...",
  "historical_context": "...",
  "key_works": "Work One;Work Two",
  "tags": "tag one;tag two",

  "region": ["Europe"],
  "civilization": ["Modern European"],
  "era": ["20th Century"],
  "school_movement": ["Analytic Philosophy"],
  "primary_topic": ["Ethics", "Political Philosophy"],
  "metaphysical_stance": ["Materialism / Naturalism / Physicalism"],
  "epistemological_stance": ["Empiricism"],
  "ethical_orientation": ["Consequentialism / Utilitarianism"],
  "political_orientation": ["Liberal"],
  "religious_orientation": ["Secular / Atheist / Agnostic"],

  "influenced_by": ["Aristotle", "P010"],
  "influenced": ["Some Later Philosopher"]
}

Dimension values are lists; order matters -- the first entry becomes Rank=1
(the "primary" value used for map coloring).

"short_name" is the label drawn on the map. If omitted it's derived from
"name", which handles parentheticals and "X of Place" but can't know about
non-Western name order or epithets -- so set it explicitly for anyone whose
common short form isn't simply their last name.

"influenced_by" / "influenced" list philosophers **by Name or ID** (mixing is
fine). Setting either fully replaces that direction's edges for this
philosopher in relations.csv, and the reverse edge is kept in sync on the
referenced philosophers' own rows automatically (e.g. adding "influenced_by":
["Aristotle"] also adds this philosopher to Aristotle's InfluencedIDs).

Subcommands:
    add --spec philosopher.json [--allow-new-categories]
        Create a new philosopher (auto-assigned ID), its dimension links, and
        any influence relations given in the spec. Also picks a placeholder
        map position: the existing philosopher with the most overlapping
        dimension categories (by Jaccard similarity across all 10
        dimensions) is used as a "nearest neighbor", and the new philosopher
        is placed at that neighbor's coordinates (plus a small random jitter)
        in all three coords_*.csv files. This is a rough placeholder, not a
        real semantic/network embedding -- for a precise position, re-run
        notebooks/semantics2vec.ipynb and notebooks/node2vec.ipynb to
        regenerate the coords files from scratch.

    edit --id P042 --spec patch.json [--allow-new-categories]
        Patch narrative/scalar fields present in the spec, fully replace the
        links for any dimension key present in the spec (dimension keys
        omitted from the patch are left untouched), and/or fully replace
        influence relations if "influenced_by"/"influenced" are present.
        Does NOT touch map coordinates -- the placeholder-positioning logic
        only runs at `add` time.

    remove --id P042 [--force]
        Remove a philosopher, all of their dimension links, and their row
        from every coords_*.csv and embeddings file. Their own relations.csv row is always
        removed; if other philosophers still reference them there, this
        refuses to proceed unless --force is given, in which case those
        references are stripped too.

Examples:
    python scripts/manage_philosophers.py add --spec new_philosopher.json
    python scripts/manage_philosophers.py edit --id P042 --spec patch.json
    python scripts/manage_philosophers.py remove --id P042
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.data_model import (  # noqa: E402
    COORDS_FILENAMES,
    EMBEDDING_FILENAMES,
    PHILOSOPHER_COLUMNS,
    DataModelError,
    derive_short_name,
    dimension_keys,
    embeddings_path,
    find_dimension_id_by_name,
    load_coords,
    load_dimension,
    load_embeddings,
    load_links,
    load_philosophers,
    load_relations,
    next_dimension_id,
    next_philosopher_id,
    resolve_philosopher_id,
    save_coords,
    save_dimension,
    save_embeddings,
    save_links,
    save_philosophers,
    save_relations,
    suggest_similar_names,
)

SCALAR_FIELD_MAP = {
    "name": "Name",
    "short_name": "ShortName",
    "birth_year": "BirthYear",
    "death_year": "DeathYear",
    "core_teachings": "CoreTeachings",
    "historical_context": "HistoricalContext",
    "key_works": "KeyWorks",
    "tags": "Tags",
}

# spec key -> (this philosopher's own relations.csv column, the column to
# mirror the edge into on each *referenced* philosopher's row)
RELATION_FIELD_MAP = {
    "influenced_by": ("InfluencedByIDs", "InfluencedIDs"),
    "influenced": ("InfluencedIDs", "InfluencedByIDs"),
}

COORD_JITTER_FRACTION = 0.01  # +/- 1% of the axis range, so the placeholder doesn't sit exactly on its neighbor


def resolve_names_to_ids(key: str, names: list[str], allow_new: bool) -> list[str]:
    dim_df = load_dimension(key)
    ids = []
    dirty = False
    for name in names:
        existing_id = find_dimension_id_by_name(dim_df, name)
        if existing_id:
            ids.append(existing_id)
            continue
        if not allow_new:
            suggestions = suggest_similar_names(dim_df, name)
            hint = f" Did you mean: {suggestions}?" if suggestions else ""
            raise SystemExit(
                f"Unknown {key!r} category {name!r}.{hint} "
                f"Use `manage_dimensions.py add {key} --name ... --description ...` first, "
                f"or pass --allow-new-categories to create it inline (with a placeholder description you should edit)."
            )
        prefix = str(dim_df.iloc[0]["ID"]).rstrip("0123456789") if not dim_df.empty else key[:2].upper()
        new_id = next_dimension_id(dim_df, prefix)
        new_row = pd.DataFrame([{
            "ID": new_id,
            "Name": name,
            "Description": f"TODO: write a description for {name!r} (auto-created by manage_philosophers.py).",
        }])
        dim_df = pd.concat([dim_df, new_row], ignore_index=True)
        ids.append(new_id)
        dirty = True
        print(f"  (created new {key} category [{new_id}] {name!r} -- please edit its description)")
    if dirty:
        save_dimension(key, dim_df)
    return ids


def apply_scalar_fields(row: dict, spec: dict) -> None:
    for spec_key, column in SCALAR_FIELD_MAP.items():
        if spec_key in spec:
            row[column] = spec[spec_key]


def resolve_all_dimension_specs(spec: dict, allow_new: bool) -> dict[str, list[str]]:
    """Resolve every dimension key present in spec to IDs up front, so a spec
    with one bad category name fails before anything is written to disk."""
    return {
        key: resolve_names_to_ids(key, spec[key], allow_new)
        for key in dimension_keys()
        if key in spec
    }


def write_links_for_philosopher(key: str, philosopher_id: str, ids: list[str]) -> None:
    links_df = load_links(key)
    links_df = links_df[links_df["PhilosopherID"] != philosopher_id]
    new_rows = pd.DataFrame([
        {"PhilosopherID": philosopher_id, "DimensionID": dim_id, "Rank": rank}
        for rank, dim_id in enumerate(ids, start=1)
    ])
    links_df = pd.concat([links_df, new_rows], ignore_index=True)
    save_links(key, links_df)


# ---------------------------------------------------------------------------
# Influence relations (relations.csv)
# ---------------------------------------------------------------------------

def resolve_philosopher_ids(philosophers_df: pd.DataFrame, identifiers: list[str]) -> list[str]:
    ids = []
    for identifier in identifiers:
        resolved = resolve_philosopher_id(philosophers_df, identifier)
        if not resolved:
            raise SystemExit(f"Unknown philosopher {identifier!r} in an influence relation (expected a Name or ID).")
        ids.append(resolved)
    return ids


def resolve_all_relation_specs(spec: dict, philosophers_df: pd.DataFrame) -> dict[str, list[str]]:
    """Resolve influence-relation identifiers (by Name or ID) up front, same
    reasoning as resolve_all_dimension_specs: fail before writing anything."""
    return {
        spec_key: resolve_philosopher_ids(philosophers_df, spec[spec_key])
        for spec_key in RELATION_FIELD_MAP
        if spec_key in spec
    }


def _semicolon_list(value) -> list[str]:
    return [p.strip() for p in str(value).split(";") if p.strip()]


def apply_relation_direction(relations_df: pd.DataFrame, philosopher_id: str, own_column: str, mirror_column: str, new_ids: list[str]) -> pd.DataFrame:
    """Fully replace philosopher_id's own_column with new_ids, and keep the
    reverse edge in sync on each referenced philosopher's mirror_column
    (adding it where newly present, removing it where no longer present)."""
    relations_df = relations_df.set_index("ID")
    if philosopher_id not in relations_df.index:
        relations_df.loc[philosopher_id] = {"InfluencedByIDs": "", "InfluencedIDs": ""}

    old_ids = set(_semicolon_list(relations_df.loc[philosopher_id, own_column]))
    new_ids_set = set(new_ids)
    relations_df.loc[philosopher_id, own_column] = ";".join(new_ids)

    for other_id in old_ids - new_ids_set:
        if other_id in relations_df.index:
            items = [i for i in _semicolon_list(relations_df.loc[other_id, mirror_column]) if i != philosopher_id]
            relations_df.loc[other_id, mirror_column] = ";".join(items)

    for other_id in new_ids_set - old_ids:
        if other_id not in relations_df.index:
            relations_df.loc[other_id] = {"InfluencedByIDs": "", "InfluencedIDs": ""}
        items = _semicolon_list(relations_df.loc[other_id, mirror_column])
        if philosopher_id not in items:
            items.append(philosopher_id)
        relations_df.loc[other_id, mirror_column] = ";".join(items)

    return relations_df.reset_index()


def ensure_relations_row(relations_df: pd.DataFrame, philosopher_id: str) -> pd.DataFrame:
    if philosopher_id in set(relations_df["ID"]):
        return relations_df
    new_row = pd.DataFrame([{"ID": philosopher_id, "InfluencedByIDs": "", "InfluencedIDs": ""}])
    return pd.concat([relations_df, new_row], ignore_index=True)


def write_relations_for_philosopher(philosopher_id: str, resolved_relations: dict[str, list[str]]) -> None:
    relations_df = load_relations()
    relations_df = ensure_relations_row(relations_df, philosopher_id)
    for spec_key, ids in resolved_relations.items():
        own_column, mirror_column = RELATION_FIELD_MAP[spec_key]
        relations_df = apply_relation_direction(relations_df, philosopher_id, own_column, mirror_column, ids)
    save_relations(relations_df)


# ---------------------------------------------------------------------------
# Placeholder map coordinates (docs/data/coords_*.csv)
# ---------------------------------------------------------------------------

def dimension_id_sets_by_philosopher() -> dict[str, set[str]]:
    """Every existing philosopher's set of linked DimensionIDs, pooled across
    all 10 dimensions (used only to find a 'nearest neighbor' by shared
    categories -- Rank is ignored, a linked value counts regardless of rank)."""
    sets: dict[str, set[str]] = {}
    for key in dimension_keys():
        for _, row in load_links(key).iterrows():
            sets.setdefault(row["PhilosopherID"], set()).add(row["DimensionID"])
    return sets


def nearest_neighbor_by_dimensions(new_dimension_ids: set[str], existing_sets: dict[str, set[str]]) -> str | None:
    """Existing philosopher with the highest Jaccard overlap of dimension
    categories with new_dimension_ids, or None if there's nothing to compare
    against (e.g. the new philosopher has no dimension values at all)."""
    if not new_dimension_ids:
        return None
    best_id, best_score = None, -1.0
    for philosopher_id, ids in existing_sets.items():
        union = ids | new_dimension_ids
        if not union:
            continue
        score = len(ids & new_dimension_ids) / len(union)
        if score > best_score:
            best_score, best_id = score, philosopher_id
    return best_id


def assign_placeholder_coordinates(new_id: str, neighbor_id: str) -> None:
    """Naive placeholder positioning: copy the neighbor's coordinates into a new
    row for new_id in every coords_*.csv file, with a small random jitter so the
    two points don't exactly overlap. This is not a real semantic/network
    embedding -- rerun the notebooks under notebooks/ for a precise position.

    No entry is written to docs/data/embeddings/. Copying the neighbour's vector
    would make the two philosophers identical to anything that measures
    similarity, which is a worse failure than simply having no vector yet."""
    rng = np.random.default_rng()
    for filename in COORDS_FILENAMES:
        df = load_coords(filename)
        if df.empty or "ID" not in df.columns:
            continue
        neighbor_rows = df[df["ID"] == neighbor_id]
        if neighbor_rows.empty:
            print(f"  (warning: neighbor [{neighbor_id}] not found in {filename}; skipping placeholder position there)")
            continue

        neighbor_row = neighbor_rows.iloc[0]
        xs = df["x"].astype(float)
        ys = df["y"].astype(float)
        x_range = xs.max() - xs.min() or 1.0
        y_range = ys.max() - ys.min() or 1.0
        new_x = float(neighbor_row["x"]) + rng.uniform(-1, 1) * COORD_JITTER_FRACTION * x_range
        new_y = float(neighbor_row["y"]) + rng.uniform(-1, 1) * COORD_JITTER_FRACTION * y_range

        new_row = {col: neighbor_row[col] for col in df.columns}
        new_row["ID"] = new_id
        new_row["x"] = new_x
        new_row["y"] = new_y
        df = pd.concat([df, pd.DataFrame([new_row])[df.columns]], ignore_index=True)
        save_coords(filename, df)
        print(f"  placed in {filename} near [{neighbor_id}] (jittered placeholder)")


def cmd_add(args):
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if "name" not in spec:
        raise SystemExit("Spec must include \"name\".")

    # Resolve (and validate) every dimension + relation reference before
    # writing anything, so a bad category or philosopher name never leaves a
    # half-created philosopher behind. Relations are resolved first because
    # --allow-new-categories makes dimension resolution write to disk, and an
    # unknown influence name afterwards would strand a category nobody uses.
    philosophers = load_philosophers()
    resolved_relations = resolve_all_relation_specs(spec, philosophers)
    resolved_dimensions = resolve_all_dimension_specs(spec, args.allow_new_categories)

    # Snapshot existing philosophers' dimension sets *before* writing the new
    # philosopher's own links, so they can never end up as their own "nearest
    # neighbor" for placeholder positioning below.
    existing_dimension_sets = dimension_id_sets_by_philosopher()

    new_id = next_philosopher_id(philosophers)

    row = {col: "" for col in PHILOSOPHER_COLUMNS}
    row["ID"] = new_id
    apply_scalar_fields(row, spec)

    # ShortName is the map label. Derive one when the spec omits it, but say so:
    # the heuristic can't know about non-Western name order or epithets, so the
    # result is worth a glance.
    if not str(row.get("ShortName", "")).strip():
        row["ShortName"] = derive_short_name(row["Name"])
        print(f"  (derived short name {row['ShortName']!r} for the map label; "
              f"set \"short_name\" in the spec to override)")

    philosophers = pd.concat([philosophers, pd.DataFrame([row])], ignore_index=True)
    save_philosophers(philosophers)

    for key, ids in resolved_dimensions.items():
        write_links_for_philosopher(key, new_id, ids)

    # relations.csv has exactly one row per philosopher; keep that invariant
    # even if no influence relations were given in the spec.
    write_relations_for_philosopher(new_id, resolved_relations)

    print(f"Added [{new_id}] {spec['name']}.")

    new_dimension_ids = {dim_id for ids in resolved_dimensions.values() for dim_id in ids}
    neighbor_id = nearest_neighbor_by_dimensions(new_dimension_ids, existing_dimension_sets)
    if neighbor_id:
        neighbor_name = philosophers.loc[philosophers["ID"] == neighbor_id, "Name"].iloc[0]
        print(f"Nearest neighbor by shared categories: [{neighbor_id}] {neighbor_name} -- using as a placeholder map position.")
        assign_placeholder_coordinates(new_id, neighbor_id)
        print("  (this is a rough placeholder, not a real embedding -- rerun notebooks/semantics2vec.ipynb "
              "and notebooks/node2vec.ipynb for a precise position once convenient)")
        print("  (no vector was written to docs/data/embeddings/; the notebooks generate those)")
    else:
        print("No dimension categories given, so no placeholder map position was assigned. "
              "Add coordinates to coords_*.csv manually, or rerun the embedding notebooks.")


def cmd_edit(args):
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    philosophers = load_philosophers()
    if args.id not in set(philosophers["ID"]):
        raise SystemExit(f"No philosopher with ID {args.id!r}.")

    resolved_relations = resolve_all_relation_specs(spec, philosophers)
    resolved_dimensions = resolve_all_dimension_specs(spec, args.allow_new_categories)

    row = philosophers.loc[philosophers["ID"] == args.id].iloc[0].to_dict()
    apply_scalar_fields(row, spec)
    philosophers.loc[philosophers["ID"] == args.id, list(row.keys())] = list(row.values())
    save_philosophers(philosophers)

    for key, ids in resolved_dimensions.items():
        write_links_for_philosopher(key, args.id, ids)

    if resolved_relations:
        write_relations_for_philosopher(args.id, resolved_relations)

    print(f"Updated [{args.id}].")


def cmd_remove(args):
    philosophers = load_philosophers()
    if args.id not in set(philosophers["ID"]):
        raise SystemExit(f"No philosopher with ID {args.id!r}.")

    relations = load_relations()
    if not relations.empty:
        referenced_elsewhere = [
            r["ID"] for _, r in relations.iterrows()
            if r["ID"] != args.id
            and (args.id in _semicolon_list(r.get("InfluencedByIDs", "")) or args.id in _semicolon_list(r.get("InfluencedIDs", "")))
        ]
        if referenced_elsewhere and not args.force:
            raise SystemExit(
                f"[{args.id}] is still referenced in relations.csv by {sorted(set(referenced_elsewhere))}. "
                f"Use --force to strip those references too."
            )
        if referenced_elsewhere:
            for col in ("InfluencedByIDs", "InfluencedIDs"):
                relations[col] = relations[col].apply(lambda v: ";".join(i for i in _semicolon_list(v) if i != args.id))
        # The removed philosopher's own row is always dropped, regardless of --force.
        relations = relations[relations["ID"] != args.id]
        save_relations(relations)

    name = philosophers.loc[philosophers["ID"] == args.id, "Name"].iloc[0]
    philosophers = philosophers[philosophers["ID"] != args.id]
    save_philosophers(philosophers)

    for key in dimension_keys():
        links_df = load_links(key)
        remaining = links_df[links_df["PhilosopherID"] != args.id]
        if len(remaining) != len(links_df):
            save_links(key, remaining)

    for filename in COORDS_FILENAMES:
        coords_df = load_coords(filename)
        if coords_df.empty or "ID" not in coords_df.columns:
            continue
        remaining = coords_df[coords_df["ID"] != args.id]
        if len(remaining) != len(coords_df):
            save_coords(filename, remaining)

    # A leftover vector would outlive the philosopher it describes, which
    # validate.py reports as a dangling reference.
    for filename in EMBEDDING_FILENAMES:
        if not embeddings_path(filename).exists():
            continue
        emb_df = load_embeddings(filename)
        remaining = emb_df[emb_df["ID"] != args.id]
        if len(remaining) != len(emb_df):
            save_embeddings(filename, remaining)

    print(f"Removed [{args.id}] {name!r}, their dimension links, relations, map coordinates, and embeddings.")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sp = subparsers.add_parser("add", help="add a new philosopher from a JSON spec")
    sp.add_argument("--spec", required=True, help="path to a JSON spec file")
    sp.add_argument("--allow-new-categories", action="store_true", help="create unknown dimension categories inline instead of erroring")
    sp.set_defaults(func=cmd_add)

    sp = subparsers.add_parser("edit", help="patch an existing philosopher from a JSON spec")
    sp.add_argument("--id", required=True)
    sp.add_argument("--spec", required=True, help="path to a JSON patch file")
    sp.add_argument("--allow-new-categories", action="store_true", help="create unknown dimension categories inline instead of erroring")
    sp.set_defaults(func=cmd_edit)

    sp = subparsers.add_parser("remove", help="remove a philosopher and their links")
    sp.add_argument("--id", required=True)
    sp.add_argument("--force", action="store_true", help="also strip references from relations.csv")
    sp.set_defaults(func=cmd_remove)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except DataModelError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
