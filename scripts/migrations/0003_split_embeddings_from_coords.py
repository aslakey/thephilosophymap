"""
Move the source embedding vectors out of the coords files.

Each coords_*.csv carried an `embedding` column holding the high-dimensional
vector the 2D position was reduced from. The map only ever reads x and y, so
every visitor downloaded and parsed 3.1MB of float text to draw 101 points --
and the same 1536-dimension matrix was stored three times over
(coords_semantic_tsne.csv, coords_semantic_umap.csv, and a third copy in
notebooks/openai_text_emb_small.csv).

After this, coords files are ID,x,y and the vectors live once in
docs/data/embeddings/, where a future similarity feature can fetch them
deliberately rather than every visitor paying for them by default.

Safe to re-run: coords files that are already ID,x,y are left alone, and an
existing embeddings file is never overwritten with less data than it has.

Usage:
    python scripts/migrations/0003_split_embeddings_from_coords.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.data_model import (  # noqa: E402
    COORDS_COLUMNS,
    coords_path,
    embeddings_path,
    load_coords,
    load_embeddings,
    save_coords,
    save_embeddings,
)

# Which coords file each embedding table is extracted from. Both semantic coords
# files hold identical vectors (same model, different 2D reduction), so t-SNE is
# the arbitrary but stable choice and UMAP's copy is simply dropped.
SOURCES = {
    "semantic_1536.csv": "coords_semantic_tsne.csv",
    "influence_16.csv": "coords_node2vec_tsne.csv",
}


def extract(embeddings_filename: str, coords_filename: str) -> None:
    coords = load_coords(coords_filename)
    if coords.empty:
        print(f"  {coords_filename}: missing or empty, skipped")
        return

    if "embedding" not in coords.columns:
        print(f"  {coords_filename}: already ID,x,y")
        return

    vectors = coords[["ID", "embedding"]]
    existing = load_embeddings(embeddings_filename)
    if len(existing) > len(vectors):
        print(
            f"  {embeddings_filename}: keeping existing file "
            f"({len(existing)} rows) rather than overwriting with {len(vectors)}"
        )
    else:
        save_embeddings(embeddings_filename, vectors)
        dims = len(vectors["embedding"].iloc[0].strip("[]").split(",")) if len(vectors) else 0
        print(f"  {embeddings_filename}: wrote {len(vectors)} vectors of {dims} dimensions")

    before = coords_path(coords_filename).stat().st_size
    save_coords(coords_filename, coords)
    after = coords_path(coords_filename).stat().st_size
    print(f"  {coords_filename}: {before / 1e6:.2f}MB -> {after / 1e3:.1f}KB")


def main():
    print("Extracting embeddings:")
    for embeddings_filename, coords_filename in SOURCES.items():
        extract(embeddings_filename, coords_filename)

    # The UMAP coords are a second reduction of the same semantic vectors, so
    # its embedding column is a duplicate with no unique data to preserve.
    duplicate = load_coords("coords_semantic_umap.csv")
    if not duplicate.empty and "embedding" in duplicate.columns:
        before = coords_path("coords_semantic_umap.csv").stat().st_size
        save_coords("coords_semantic_umap.csv", duplicate)
        after = coords_path("coords_semantic_umap.csv").stat().st_size
        print(f"  coords_semantic_umap.csv: {before / 1e6:.2f}MB -> {after / 1e3:.1f}KB (duplicate vectors dropped)")
    elif not duplicate.empty:
        print("  coords_semantic_umap.csv: already ID,x,y")

    print("\nEmbeddings now live in:")
    for name in SOURCES:
        path = embeddings_path(name)
        if path.exists():
            print(f"  {path.parent.name}/{name} ({path.stat().st_size / 1e6:.2f}MB)")

    if COORDS_COLUMNS != ["ID", "x", "y"]:
        raise SystemExit(f"unexpected coords schema: {COORDS_COLUMNS}")


if __name__ == "__main__":
    main()
