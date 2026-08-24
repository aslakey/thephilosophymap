"""
Tests for migration 0003 and the coords/embeddings split it produces.

The point of the split is that the map downloads coordinates only, so the
things worth pinning down are that the vectors survive the move intact, that
coords come out with exactly three columns, and that neither the migration nor
a later regeneration can quietly put them back.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import validate
from lib.data_model import (
    COORDS_COLUMNS,
    coords_path,
    embeddings_path,
    load_coords,
    load_embeddings,
    load_philosophers,
    save_coords,
    save_embeddings,
)
from test_validate import all_errors

MIGRATION = Path(__file__).resolve().parents[1] / "scripts" / "migrations" / "0003_split_embeddings_from_coords.py"


def run_migration():
    spec = importlib.util.spec_from_file_location("migration_0003", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    sys.modules["migration_0003"] = module
    spec.loader.exec_module(module)
    module.main()


def inflate_coords(filename, vectors):
    """Put a coords file back into its pre-migration shape."""
    df = load_coords(filename)
    df["embedding"] = [vectors[pid] for pid in df["ID"]]
    df.to_csv(coords_path(filename), index=False)


VECTORS = {"P001": "[1.0, 2.0]", "P002": "[3.0, 4.0]", "P003": "[5.0, 6.0]"}


class TestMigration:
    def test_extracts_vectors_and_reduces_coords(self, data_root, capsys):
        embeddings_path("semantic_1536.csv").unlink()
        inflate_coords("coords_semantic_tsne.csv", VECTORS)
        assert "embedding" in load_coords("coords_semantic_tsne.csv").columns

        run_migration()

        assert list(load_coords("coords_semantic_tsne.csv").columns) == COORDS_COLUMNS
        extracted = load_embeddings("semantic_1536.csv")
        assert dict(zip(extracted["ID"], extracted["embedding"], strict=True)) == VECTORS

    def test_coordinates_are_unchanged_by_the_move(self, data_root):
        before = load_coords("coords_semantic_tsne.csv")
        embeddings_path("semantic_1536.csv").unlink()
        inflate_coords("coords_semantic_tsne.csv", VECTORS)

        run_migration()

        assert load_coords("coords_semantic_tsne.csv").equals(before)

    def test_shrinks_the_file_the_browser_downloads(self, data_root):
        embeddings_path("semantic_1536.csv").unlink()
        inflate_coords("coords_semantic_tsne.csv", VECTORS)
        before = coords_path("coords_semantic_tsne.csv").stat().st_size

        run_migration()

        assert coords_path("coords_semantic_tsne.csv").stat().st_size < before

    def test_is_idempotent(self, data_root):
        run_migration()
        first = load_coords("coords_semantic_tsne.csv")
        first_vectors = load_embeddings("semantic_1536.csv")

        run_migration()

        assert load_coords("coords_semantic_tsne.csv").equals(first)
        assert load_embeddings("semantic_1536.csv").equals(first_vectors)

    def test_does_not_shrink_an_existing_embeddings_table(self, data_root, capsys):
        # A coords file holding fewer rows than the embeddings table must not
        # truncate it -- that would silently discard vectors.
        inflate_coords("coords_semantic_tsne.csv", VECTORS)
        partial = load_coords("coords_semantic_tsne.csv")
        partial = partial[partial["ID"] != "P003"]
        partial.to_csv(coords_path("coords_semantic_tsne.csv"), index=False)

        run_migration()

        assert len(load_embeddings("semantic_1536.csv")) == 3
        assert "keeping existing file" in capsys.readouterr().out

    def test_leaves_a_clean_dataset_valid(self, data_root):
        run_migration()
        assert all_errors() == []


class TestCoordsSchemaValidation:
    def test_clean_fixture_passes(self, data_root):
        assert validate.check_coords(set(load_philosophers()["ID"])) == []

    def test_stray_vector_column_is_caught(self, data_root):
        inflate_coords("coords_semantic_tsne.csv", VECTORS)
        errors = validate.check_coords(set(load_philosophers()["ID"]))
        assert any("unexpected column" in e and "embedding" in e for e in errors)

    def test_error_points_at_the_migration(self, data_root):
        inflate_coords("coords_semantic_tsne.csv", VECTORS)
        errors = validate.check_coords(set(load_philosophers()["ID"]))
        assert any("0003_split_embeddings_from_coords" in e for e in errors)

    def test_save_coords_prevents_reintroducing_the_column(self, data_root):
        df = load_coords("coords_semantic_tsne.csv")
        df["embedding"] = "[0.1]"
        save_coords("coords_semantic_tsne.csv", df)
        assert validate.check_coords(set(load_philosophers()["ID"])) == []


class TestEmbeddingsValidation:
    def test_clean_fixture_passes(self, data_root):
        assert validate.check_embeddings(set(load_philosophers()["ID"])) == []

    def test_absent_embeddings_are_allowed(self, data_root):
        embeddings_path("semantic_1536.csv").unlink()
        assert validate.check_embeddings(set(load_philosophers()["ID"])) == []

    def test_partial_coverage_is_allowed(self, data_root):
        # A philosopher added through the CLI has no vector until the notebooks
        # are rerun, which is a legitimate intermediate state.
        df = load_embeddings("semantic_1536.csv")
        save_embeddings("semantic_1536.csv", df[df["ID"] != "P002"])
        assert validate.check_embeddings(set(load_philosophers()["ID"])) == []

    def test_dangling_reference_is_caught(self, data_root):
        df = load_embeddings("semantic_1536.csv")
        df.loc[len(df)] = {"ID": "P999", "embedding": "[0.0]"}
        save_embeddings("semantic_1536.csv", df)
        errors = validate.check_embeddings(set(load_philosophers()["ID"]))
        assert any("unknown philosopher ID" in e and "P999" in e for e in errors)

    def test_duplicate_ids_are_caught(self, data_root):
        df = load_embeddings("semantic_1536.csv")
        df.loc[len(df)] = dict(df.iloc[0])
        save_embeddings("semantic_1536.csv", df)
        assert any("duplicate IDs" in e for e in validate.check_embeddings(set(load_philosophers()["ID"])))

    def test_wrong_columns_are_caught(self, data_root):
        load_embeddings("semantic_1536.csv").rename(
            columns={"embedding": "vector"}
        ).to_csv(embeddings_path("semantic_1536.csv"), index=False)
        errors = validate.check_embeddings(set(load_philosophers()["ID"]))
        assert any("expected columns" in e for e in errors)


@pytest.mark.parametrize("filename", ["coords_semantic_tsne.csv", "coords_semantic_umap.csv", "coords_node2vec_tsne.csv"])
def test_real_coords_files_stay_lean(filename):
    """Guards the actual shipped data, not the fixture."""
    import pandas as pd
    repo_coords = Path(__file__).resolve().parents[1] / "docs" / "data" / filename
    assert list(pd.read_csv(repo_coords, nrows=1).columns) == COORDS_COLUMNS
    # 101 rows of "P001,12.34,-56.78" cannot legitimately reach a megabyte.
    assert repo_coords.stat().st_size < 100_000
