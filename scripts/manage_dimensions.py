"""
CLI for managing dimension categories (school_movement, primary_topic, etc.)
without hand-editing CSVs. Always leaves the data in a state that passes
scripts/validate.py.

Subcommands:
    list <dim>
        List all categories in a dimension with usage counts.

    add <dim> --name "New Category" --description "..."
        Add a new category. Fails if a category with that name already exists.

    edit <dim> --id SM18 --description "..."
        Update a category's description.

    rename <dim> --id SM18 --name "New Name"
        Rename a category. Fails if another category already has that name.

    merge <dim> --from SM18 --into SM2
        Repoint every link from the source category to the target category,
        re-rank each affected philosopher's links (dropping the duplicate if
        a philosopher was already linked to both), then remove the source
        category from the dimension table.

    remove <dim> --id SM18 [--force]
        Remove a category. Fails if it's still referenced by any link unless
        --force is given, in which case those links are deleted too (and
        affected philosophers' ranks are recomputed).

Examples:
    python scripts/manage_dimensions.py list primary_topic
    python scripts/manage_dimensions.py add primary_topic --name "Philosophy of Language" --description "..."
    python scripts/manage_dimensions.py merge primary_topic --from PT16 --into PT7
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.data_model import (  # noqa: E402
    DataModelError,
    dimension_keys,
    find_dimension_id_by_name,
    load_dimension,
    load_links,
    next_dimension_id,
    save_dimension,
    save_links,
    suggest_similar_names,
)


def _dim_prefix(dim_df: pd.DataFrame, key: str) -> str:
    if dim_df.empty:
        raise DataModelError(f"Dimension {key!r} has no existing rows to infer an ID prefix from.")
    sample_id = str(dim_df.iloc[0]["ID"])
    prefix = sample_id.rstrip("0123456789")
    return prefix


def _reassign_ranks(links_df: pd.DataFrame) -> pd.DataFrame:
    """Recompute contiguous 1..N ranks per philosopher, preserving relative order."""
    links_df = links_df.sort_values(["PhilosopherID", "Rank"]).copy()
    links_df["Rank"] = links_df.groupby("PhilosopherID").cumcount() + 1
    return links_df.reset_index(drop=True)


def cmd_list(args):
    dim_df = load_dimension(args.dim)
    links_df = load_links(args.dim)
    counts = links_df["DimensionID"].value_counts()
    print(f"{args.dim} -- {len(dim_df)} categories")
    for _, row in dim_df.iterrows():
        count = counts.get(row["ID"], 0)
        print(f"\n[{row['ID']}] {row['Name']}  ({count} philosopher(s))")
        print(f"    {row['Description']}")


def cmd_add(args):
    dim_df = load_dimension(args.dim)
    if find_dimension_id_by_name(dim_df, args.name):
        raise SystemExit(f"A category named {args.name!r} already exists in {args.dim!r}.")
    similar = suggest_similar_names(dim_df, args.name)
    if similar:
        print(f"Note: similar existing categories in {args.dim!r}: {similar}. Continuing to add {args.name!r} as a new, distinct category.")
    prefix = _dim_prefix(dim_df, args.dim)
    new_id = next_dimension_id(dim_df, prefix)
    new_row = pd.DataFrame([{"ID": new_id, "Name": args.name, "Description": args.description}])
    dim_df = pd.concat([dim_df, new_row], ignore_index=True)
    save_dimension(args.dim, dim_df)
    print(f"Added [{new_id}] {args.name} to {args.dim}.")


def cmd_edit(args):
    dim_df = load_dimension(args.dim)
    if args.id not in set(dim_df["ID"]):
        raise SystemExit(f"No category with ID {args.id!r} in {args.dim!r}.")
    dim_df.loc[dim_df["ID"] == args.id, "Description"] = args.description
    save_dimension(args.dim, dim_df)
    print(f"Updated description for [{args.id}] in {args.dim}.")


def cmd_rename(args):
    dim_df = load_dimension(args.dim)
    if args.id not in set(dim_df["ID"]):
        raise SystemExit(f"No category with ID {args.id!r} in {args.dim!r}.")
    existing = find_dimension_id_by_name(dim_df, args.name)
    if existing and existing != args.id:
        raise SystemExit(f"Another category ([{existing}]) already uses the name {args.name!r}.")
    old_name = dim_df.loc[dim_df["ID"] == args.id, "Name"].iloc[0]
    dim_df.loc[dim_df["ID"] == args.id, "Name"] = args.name
    save_dimension(args.dim, dim_df)
    print(f"Renamed [{args.id}] {old_name!r} -> {args.name!r} in {args.dim}.")


def cmd_merge(args):
    dim_df = load_dimension(args.dim)
    ids = set(dim_df["ID"])
    if args.from_id not in ids:
        raise SystemExit(f"No category with ID {args.from_id!r} in {args.dim!r}.")
    if args.into_id not in ids:
        raise SystemExit(f"No category with ID {args.into_id!r} in {args.dim!r}.")
    if args.from_id == args.into_id:
        raise SystemExit("--from and --into must be different categories.")

    links_df = load_links(args.dim)
    links_df["DimensionID"] = links_df["DimensionID"].replace(args.from_id, args.into_id)
    links_df = links_df.drop_duplicates(subset=["PhilosopherID", "DimensionID"], keep="first")
    links_df = _reassign_ranks(links_df)
    save_links(args.dim, links_df)

    from_name = dim_df.loc[dim_df["ID"] == args.from_id, "Name"].iloc[0]
    into_name = dim_df.loc[dim_df["ID"] == args.into_id, "Name"].iloc[0]
    dim_df = dim_df[dim_df["ID"] != args.from_id]
    save_dimension(args.dim, dim_df)
    print(f"Merged [{args.from_id}] {from_name!r} into [{args.into_id}] {into_name!r} in {args.dim}.")


def cmd_remove(args):
    dim_df = load_dimension(args.dim)
    if args.id not in set(dim_df["ID"]):
        raise SystemExit(f"No category with ID {args.id!r} in {args.dim!r}.")

    links_df = load_links(args.dim)
    referenced = links_df[links_df["DimensionID"] == args.id]
    if not referenced.empty and not args.force:
        raise SystemExit(
            f"[{args.id}] is still referenced by {len(referenced)} philosopher(s): "
            f"{sorted(referenced['PhilosopherID'].unique())}. Use --force to remove those links too "
            f"(or use 'merge' to reassign them to another category instead)."
        )

    if not referenced.empty:
        affected = set(referenced["PhilosopherID"])
        links_df = links_df[links_df["DimensionID"] != args.id]
        links_df = _reassign_ranks(links_df)
        save_links(args.dim, links_df)
        print(f"Removed {len(referenced)} link(s) for {sorted(affected)}.")

    name = dim_df.loc[dim_df["ID"] == args.id, "Name"].iloc[0]
    dim_df = dim_df[dim_df["ID"] != args.id]
    save_dimension(args.dim, dim_df)
    print(f"Removed [{args.id}] {name!r} from {args.dim}.")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_dim_arg(sp):
        sp.add_argument("dim", choices=dimension_keys(), help="dimension key, e.g. primary_topic")

    sp = subparsers.add_parser("list", help="list categories in a dimension")
    add_dim_arg(sp)
    sp.set_defaults(func=cmd_list)

    sp = subparsers.add_parser("add", help="add a new category")
    add_dim_arg(sp)
    sp.add_argument("--name", required=True)
    sp.add_argument("--description", required=True)
    sp.set_defaults(func=cmd_add)

    sp = subparsers.add_parser("edit", help="update a category's description")
    add_dim_arg(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--description", required=True)
    sp.set_defaults(func=cmd_edit)

    sp = subparsers.add_parser("rename", help="rename a category")
    add_dim_arg(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--name", required=True)
    sp.set_defaults(func=cmd_rename)

    sp = subparsers.add_parser("merge", help="merge one category into another")
    add_dim_arg(sp)
    sp.add_argument("--from", dest="from_id", required=True)
    sp.add_argument("--into", dest="into_id", required=True)
    sp.set_defaults(func=cmd_merge)

    sp = subparsers.add_parser("remove", help="remove a category")
    add_dim_arg(sp)
    sp.add_argument("--id", required=True)
    sp.add_argument("--force", action="store_true", help="also delete any links that still reference this category")
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
