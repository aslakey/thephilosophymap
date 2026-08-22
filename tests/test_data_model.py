"""Unit tests for the shared CSV I/O layer."""
from __future__ import annotations

import pandas as pd
import pytest
from lib import data_model
from lib.data_model import (
    DataModelError,
    dimension_keys,
    find_dimension_id_by_name,
    load_coords,
    load_dimension,
    load_links,
    load_manifest,
    load_philosophers,
    load_relations,
    manifest_entry,
    next_dimension_id,
    next_philosopher_id,
    resolve_philosopher_id,
    save_coords,
    save_dimension,
    save_links,
    save_philosophers,
    save_relations,
    suggest_similar_names,
)


class TestDataDirOverride:
    def test_set_data_dir_redirects_reads(self, data_root):
        assert data_model.data_dir() == data_root
        assert data_model.philosophers_path() == data_root / "philosophers.csv"
        assert data_model.manifest_path() == data_root / "dimensions" / "manifest.json"

    def test_reset_restores_default(self, data_root, monkeypatch):
        monkeypatch.delenv(data_model.DATA_DIR_ENV_VAR, raising=False)
        data_model.set_data_dir(None)
        try:
            assert data_model.data_dir() == data_model.DEFAULT_DATA_DIR
        finally:
            data_model.set_data_dir(data_root)

    def test_override_takes_precedence_over_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv(data_model.DATA_DIR_ENV_VAR, str(tmp_path / "from_env"))
        data_model.set_data_dir(tmp_path / "from_call")
        try:
            assert data_model.data_dir() == (tmp_path / "from_call").resolve()
        finally:
            data_model.set_data_dir(None)

    def test_env_var_is_honoured_when_no_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv(data_model.DATA_DIR_ENV_VAR, str(tmp_path))
        data_model.set_data_dir(None)
        assert data_model.data_dir() == tmp_path.resolve()


class TestManifest:
    def test_lists_fixture_keys(self, data_root):
        assert dimension_keys() == ["region", "primary_topic"]

    def test_entry_exposes_file_paths(self, data_root):
        entry = manifest_entry("region")
        assert entry["file"] == "dimensions/region.csv"
        assert entry["linksFile"] == "links/region_links.csv"

    def test_unknown_key_raises(self, data_root):
        with pytest.raises(DataModelError, match="Unknown dimension key"):
            manifest_entry("not_a_dimension")

    def test_missing_manifest_raises(self, data_root):
        data_model.manifest_path().unlink()
        with pytest.raises(DataModelError, match="not found"):
            load_manifest()


class TestNextDimensionId:
    def test_increments_past_highest(self, data_root):
        assert next_dimension_id(load_dimension("primary_topic"), "PT") == "PT4"

    def test_starts_at_one_when_empty(self):
        empty = pd.DataFrame(columns=["ID", "Name", "Description"])
        assert next_dimension_id(empty, "RG") == "RG1"

    def test_fills_past_gaps_rather_than_into_them(self):
        # IDs are permanent handles, so a deleted RG2 must not be reissued.
        df = pd.DataFrame({"ID": ["RG1", "RG3"], "Name": ["a", "b"], "Description": ["x", "y"]})
        assert next_dimension_id(df, "RG") == "RG4"

    def test_ignores_other_prefixes(self):
        df = pd.DataFrame({"ID": ["RG1", "PT9"], "Name": ["a", "b"], "Description": ["x", "y"]})
        assert next_dimension_id(df, "RG") == "RG2"


class TestNextPhilosopherId:
    def test_increments_and_zero_pads(self, data_root):
        assert next_philosopher_id(load_philosophers()) == "P004"

    def test_starts_at_one_when_empty(self):
        assert next_philosopher_id(pd.DataFrame({"ID": []})) == "P001"

    def test_pads_to_three_digits_past_ninety_nine(self):
        assert next_philosopher_id(pd.DataFrame({"ID": ["P099"]})) == "P100"


class TestNameLookup:
    def test_exact_match(self, data_root):
        assert find_dimension_id_by_name(load_dimension("region"), "Europe") == "RG1"

    def test_is_case_and_whitespace_insensitive(self, data_root):
        assert find_dimension_id_by_name(load_dimension("region"), "  eUrOpE  ") == "RG1"

    def test_returns_none_when_absent(self, data_root):
        assert find_dimension_id_by_name(load_dimension("region"), "Atlantis") is None

    def test_suggests_close_names(self, data_root):
        assert "Europe" in suggest_similar_names(load_dimension("region"), "Euorpe")


class TestResolvePhilosopherId:
    def test_accepts_an_id(self, data_root):
        assert resolve_philosopher_id(load_philosophers(), "P002") == "P002"

    def test_accepts_a_name_case_insensitively(self, data_root):
        assert resolve_philosopher_id(load_philosophers(), "beta") == "P002"

    def test_returns_none_for_unknown(self, data_root):
        assert resolve_philosopher_id(load_philosophers(), "Nobody") is None


class TestRoundTrips:
    def test_dimension_round_trip(self, data_root):
        df = load_dimension("region")
        df.loc[len(df)] = {"ID": "RG3", "Name": "Africa", "Description": "A description."}
        save_dimension("region", df)
        assert find_dimension_id_by_name(load_dimension("region"), "Africa") == "RG3"

    def test_links_rank_is_read_back_as_int(self, data_root):
        assert load_links("primary_topic")["Rank"].tolist() == [1, 2, 1, 1]

    def test_links_round_trip(self, data_root):
        df = load_links("region")
        save_links("region", df)
        pd.testing.assert_frame_equal(load_links("region"), df)

    def test_philosophers_round_trip_preserves_columns(self, data_root):
        df = load_philosophers()
        save_philosophers(df)
        assert list(load_philosophers().columns) == data_model.PHILOSOPHER_COLUMNS
        assert len(load_philosophers()) == 3

    def test_relations_round_trip(self, data_root):
        df = load_relations()
        save_relations(df)
        reloaded = load_relations()
        assert reloaded.loc[reloaded["ID"] == "P002", "InfluencedByIDs"].iloc[0] == "P001"

    def test_coords_round_trip_preserves_extra_columns(self, data_root):
        filename = "coords_semantic_tsne.csv"
        df = load_coords(filename)
        assert "embedding" in df.columns
        save_coords(filename, df)
        assert "embedding" in load_coords(filename).columns

    def test_missing_files_read_as_empty(self, data_root):
        data_model.relations_path().unlink()
        assert load_relations().empty
        assert load_coords("does_not_exist.csv").empty

    def test_empty_values_are_not_coerced_to_nan(self, data_root):
        # keep_default_na=False matters: a NaN here would be written back to the
        # CSV as the literal string "nan".
        relations = load_relations()
        assert relations.loc[relations["ID"] == "P001", "InfluencedByIDs"].iloc[0] == ""
