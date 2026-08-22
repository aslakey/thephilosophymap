"""
Tests for scripts/validate.py.

The point of these is adversarial: each one corrupts the dataset in a specific
way and asserts validation actually fails. A validator that silently passes
broken data is worse than no validator, since CI would then wave it through.
"""
from __future__ import annotations

import pandas as pd
import pytest
import validate
from lib.data_model import (
    load_coords,
    load_dimension,
    load_links,
    load_philosophers,
    load_relations,
    save_coords,
    save_dimension,
    save_links,
    save_philosophers,
    save_relations,
)


def run_main(argv: list[str] | None = None) -> int:
    """Run validate.main() the way CI does; return the process exit code."""
    import sys
    from unittest.mock import patch

    with patch.object(sys, "argv", ["validate.py", *(argv or [])]):
        try:
            validate.main()
        except SystemExit as exc:
            return int(exc.code or 0)
    return 0


def all_errors() -> list[str]:
    philosopher_ids = set(load_philosophers()["ID"])
    errors = []
    for key in ("region", "primary_topic"):
        dim_df = load_dimension(key)
        links_df = load_links(key)
        errors.extend(validate.check_dimension_table(key, dim_df))
        errors.extend(validate.check_links_table(key, dim_df, links_df, philosopher_ids))
    errors.extend(validate.check_relations(philosopher_ids))
    errors.extend(validate.check_coords(philosopher_ids))
    return errors


class TestCleanDataset:
    def test_passes(self, data_root):
        assert all_errors() == []

    def test_main_exits_zero(self, data_root):
        assert run_main() == 0

    def test_report_mode_exits_zero(self, data_root, capsys):
        assert run_main(["--report"]) == 0
        assert "primary-value counts" in capsys.readouterr().out


class TestDimensionTableChecks:
    def test_duplicate_id_is_caught(self, data_root):
        df = load_dimension("region")
        df.loc[len(df)] = {"ID": "RG1", "Name": "Duplicate", "Description": "d"}
        save_dimension("region", df)
        assert any("duplicate dimension IDs" in e for e in all_errors())

    def test_duplicate_name_is_caught(self, data_root):
        df = load_dimension("region")
        df.loc[len(df)] = {"ID": "RG9", "Name": "Europe", "Description": "d"}
        save_dimension("region", df)
        assert any("duplicate dimension names" in e for e in all_errors())

    def test_empty_description_is_caught(self, data_root):
        df = load_dimension("region")
        df.loc[df["ID"] == "RG1", "Description"] = "   "
        save_dimension("region", df)
        assert any("empty Description" in e for e in all_errors())

    def test_empty_name_is_caught(self, data_root):
        df = load_dimension("region")
        df.loc[df["ID"] == "RG1", "Name"] = ""
        save_dimension("region", df)
        assert any("empty Name" in e for e in all_errors())


class TestLinkTableChecks:
    def test_dangling_dimension_id_is_caught(self, data_root):
        df = load_links("region")
        df.loc[df["PhilosopherID"] == "P001", "DimensionID"] = "RG404"
        save_links("region", df)
        assert any("unknown DimensionID" in e for e in all_errors())

    def test_dangling_philosopher_id_is_caught(self, data_root):
        df = load_links("region")
        df.loc[len(df)] = {"PhilosopherID": "P404", "DimensionID": "RG1", "Rank": 1}
        save_links("region", df)
        assert any("unknown PhilosopherID" in e for e in all_errors())

    def test_duplicate_pair_is_caught(self, data_root):
        df = load_links("region")
        df.loc[len(df)] = {"PhilosopherID": "P001", "DimensionID": "RG1", "Rank": 2}
        save_links("region", df)
        assert any("duplicate (PhilosopherID, DimensionID)" in e for e in all_errors())

    def test_non_contiguous_ranks_are_caught(self, data_root):
        df = load_links("primary_topic")
        df.loc[(df["PhilosopherID"] == "P001") & (df["DimensionID"] == "PT2"), "Rank"] = 5
        save_links("primary_topic", df)
        assert any("non-contiguous ranks" in e for e in all_errors())

    def test_missing_primary_rank_is_caught(self, data_root):
        # Drop P003's only region link, so they have no Rank=1 value and would
        # fall out of the map's colouring entirely.
        df = load_links("region")
        save_links("region", df[df["PhilosopherID"] != "P003"])
        assert any("missing a Rank=1" in e for e in all_errors())


class TestPhilosopherChecks:
    def test_duplicate_philosopher_id_is_caught(self, data_root):
        df = load_philosophers()
        df.loc[len(df)] = dict(df.iloc[0])
        save_philosophers(df)
        assert run_main() == 1


class TestRelationsChecks:
    def test_unknown_reference_is_caught(self, data_root):
        df = load_relations()
        df.loc[df["ID"] == "P001", "InfluencedIDs"] = "P404"
        save_relations(df)
        assert any("references unknown ID" in e for e in all_errors())

    def test_missing_row_is_caught(self, data_root):
        df = load_relations()
        save_relations(df[df["ID"] != "P003"])
        assert any("missing a relations.csv row" in e for e in all_errors())

    def test_extra_row_is_caught(self, data_root):
        df = load_relations()
        df.loc[len(df)] = {"ID": "P404", "InfluencedByIDs": "", "InfluencedIDs": ""}
        save_relations(df)
        assert any("unknown philosopher ID" in e for e in all_errors())

    def test_duplicate_row_is_caught(self, data_root):
        df = load_relations()
        df.loc[len(df)] = {"ID": "P001", "InfluencedByIDs": "", "InfluencedIDs": ""}
        save_relations(df)
        assert any("[relations] duplicate ID" in e for e in all_errors())


class TestCoordsChecks:
    @pytest.mark.parametrize(
        "filename",
        ["coords_semantic_tsne.csv", "coords_semantic_umap.csv", "coords_node2vec_tsne.csv"],
    )
    def test_missing_philosopher_is_caught_in_each_map(self, data_root, filename):
        df = load_coords(filename)
        save_coords(filename, df[df["ID"] != "P002"])
        errors = all_errors()
        assert any("missing a coordinate row" in e and filename in e for e in errors)

    def test_unknown_philosopher_is_caught(self, data_root):
        filename = "coords_node2vec_tsne.csv"
        df = load_coords(filename)
        df.loc[len(df)] = {"ID": "P404", "x": "1", "y": "1"}
        save_coords(filename, df)
        assert any("unknown philosopher ID" in e and filename in e for e in all_errors())

    def test_absent_coords_file_is_caught(self, data_root):
        (data_root / "coords_semantic_umap.csv").unlink()
        assert any("missing or has no ID column" in e for e in all_errors())


class TestExitCode:
    def test_main_exits_one_on_any_error(self, data_root):
        df = load_links("region")
        df.loc[df["PhilosopherID"] == "P001", "DimensionID"] = "RG404"
        save_links("region", df)
        assert run_main() == 1

    def test_failure_output_lists_the_problem(self, data_root, capsys):
        df = load_relations()
        df.loc[df["ID"] == "P001", "InfluencedIDs"] = "P404"
        save_relations(df)
        run_main()
        out = capsys.readouterr().out
        assert "problem(s) found" in out
        assert "P404" in out


class TestEmptyLinkTable:
    def test_empty_links_still_reports_missing_primaries(self, data_root):
        save_links("region", pd.DataFrame(columns=["PhilosopherID", "DimensionID", "Rank"]))
        assert any("missing a Rank=1" in e for e in all_errors())
