"""Tests for scripts/manage_dimensions.py."""
from __future__ import annotations

import manage_dimensions
import pytest
from lib.data_model import find_dimension_id_by_name, load_dimension, load_links
from test_validate import all_errors


def run(argv: list[str]) -> None:
    args = manage_dimensions.build_parser().parse_args(argv)
    args.func(args)


class TestList:
    def test_prints_categories_with_usage_counts(self, data_root, capsys):
        run(["list", "primary_topic"])
        out = capsys.readouterr().out
        assert "primary_topic -- 3 categories" in out
        assert "[PT1] Ethics" in out
        assert "1 philosopher(s)" in out


class TestAdd:
    def test_appends_with_next_id(self, data_root):
        run(["add", "primary_topic", "--name", "Aesthetics", "--description", "The study of beauty."])
        assert find_dimension_id_by_name(load_dimension("primary_topic"), "Aesthetics") == "PT4"

    def test_rejects_duplicate_name(self, data_root):
        with pytest.raises(SystemExit, match="already exists"):
            run(["add", "primary_topic", "--name", "Ethics", "--description", "d"])

    def test_rejects_duplicate_name_case_insensitively(self, data_root):
        with pytest.raises(SystemExit, match="already exists"):
            run(["add", "primary_topic", "--name", "ethics", "--description", "d"])

    def test_warns_about_similar_names_but_proceeds(self, data_root, capsys):
        run(["add", "primary_topic", "--name", "Ethic Theory", "--description", "d"])
        assert "similar existing categories" in capsys.readouterr().out
        assert find_dimension_id_by_name(load_dimension("primary_topic"), "Ethic Theory")

    def test_rejects_unknown_dimension_key(self, data_root):
        with pytest.raises(SystemExit):
            run(["add", "nonexistent_dim", "--name", "X", "--description", "d"])

    def test_result_still_validates(self, data_root):
        run(["add", "region", "--name", "Africa", "--description", "The African continent."])
        assert all_errors() == []


class TestEdit:
    def test_updates_description(self, data_root):
        run(["edit", "region", "--id", "RG1", "--description", "A new description."])
        df = load_dimension("region")
        assert df.loc[df["ID"] == "RG1", "Description"].iloc[0] == "A new description."

    def test_rejects_unknown_id(self, data_root):
        with pytest.raises(SystemExit, match="No category with ID"):
            run(["edit", "region", "--id", "RG404", "--description", "d"])

    def test_leaves_other_rows_untouched(self, data_root):
        before = load_dimension("region")
        run(["edit", "region", "--id", "RG1", "--description", "changed"])
        after = load_dimension("region")
        assert after.loc[after["ID"] == "RG2", "Description"].iloc[0] == \
            before.loc[before["ID"] == "RG2", "Description"].iloc[0]


class TestRename:
    def test_renames(self, data_root):
        run(["rename", "region", "--id", "RG1", "--name", "Western Europe"])
        assert find_dimension_id_by_name(load_dimension("region"), "Western Europe") == "RG1"

    def test_rejects_name_taken_by_another_category(self, data_root):
        with pytest.raises(SystemExit, match="already uses the name"):
            run(["rename", "region", "--id", "RG1", "--name", "Asia"])

    def test_allows_renaming_to_its_own_name(self, data_root):
        run(["rename", "region", "--id", "RG1", "--name", "Europe"])
        assert find_dimension_id_by_name(load_dimension("region"), "Europe") == "RG1"

    def test_rejects_unknown_id(self, data_root):
        with pytest.raises(SystemExit, match="No category with ID"):
            run(["rename", "region", "--id", "RG404", "--name", "X"])

    def test_does_not_touch_links(self, data_root):
        before = load_links("region")
        run(["rename", "region", "--id", "RG1", "--name", "Western Europe"])
        assert load_links("region").equals(before)


class TestMerge:
    def test_repoints_links_to_target(self, data_root):
        run(["merge", "primary_topic", "--from", "PT2", "--into", "PT1"])
        links = load_links("primary_topic")
        assert "PT2" not in set(links["DimensionID"])
        assert links.loc[links["PhilosopherID"] == "P002", "DimensionID"].tolist() == ["PT1"]

    def test_drops_source_category(self, data_root):
        run(["merge", "primary_topic", "--from", "PT2", "--into", "PT1"])
        assert "PT2" not in set(load_dimension("primary_topic")["ID"])

    def test_deduplicates_when_philosopher_had_both(self, data_root):
        # P001 holds PT1 (rank 1) and PT2 (rank 2); merging must not leave them
        # linked to PT1 twice.
        run(["merge", "primary_topic", "--from", "PT2", "--into", "PT1"])
        links = load_links("primary_topic")
        p001 = links[links["PhilosopherID"] == "P001"]
        assert p001["DimensionID"].tolist() == ["PT1"]
        assert p001["Rank"].tolist() == [1]

    def test_reranks_contiguously(self, data_root):
        run(["merge", "primary_topic", "--from", "PT2", "--into", "PT1"])
        links = load_links("primary_topic")
        for _, group in links.groupby("PhilosopherID"):
            assert sorted(group["Rank"]) == list(range(1, len(group) + 1))

    def test_result_still_validates(self, data_root):
        run(["merge", "primary_topic", "--from", "PT2", "--into", "PT1"])
        assert all_errors() == []

    def test_rejects_unknown_source(self, data_root):
        with pytest.raises(SystemExit, match="No category with ID"):
            run(["merge", "primary_topic", "--from", "PT404", "--into", "PT1"])

    def test_rejects_unknown_target(self, data_root):
        with pytest.raises(SystemExit, match="No category with ID"):
            run(["merge", "primary_topic", "--from", "PT1", "--into", "PT404"])

    def test_rejects_merging_into_itself(self, data_root):
        with pytest.raises(SystemExit, match="must be different"):
            run(["merge", "primary_topic", "--from", "PT1", "--into", "PT1"])


class TestRemove:
    def test_refuses_when_still_referenced(self, data_root):
        with pytest.raises(SystemExit, match="still referenced"):
            run(["remove", "primary_topic", "--id", "PT1"])

    def test_referenced_category_survives_a_refusal(self, data_root):
        with pytest.raises(SystemExit):
            run(["remove", "primary_topic", "--id", "PT1"])
        assert "PT1" in set(load_dimension("primary_topic")["ID"])

    def test_removes_unreferenced_category(self, data_root):
        run(["add", "region", "--name", "Africa", "--description", "d"])
        run(["remove", "region", "--id", "RG3"])
        assert "RG3" not in set(load_dimension("region")["ID"])

    def test_force_removes_links_too(self, data_root):
        run(["remove", "primary_topic", "--id", "PT2", "--force"])
        links = load_links("primary_topic")
        assert "PT2" not in set(links["DimensionID"])
        assert "PT2" not in set(load_dimension("primary_topic")["ID"])

    def test_force_reranks_remaining_links(self, data_root):
        # P001 had PT1 (rank 1) and PT2 (rank 2); dropping PT2 must leave a
        # contiguous 1..N, not a gap.
        run(["remove", "primary_topic", "--id", "PT2", "--force"])
        links = load_links("primary_topic")
        assert links[links["PhilosopherID"] == "P001"]["Rank"].tolist() == [1]

    def test_force_removal_can_strand_a_philosopher_and_validation_says_so(self, data_root):
        # P002's only topic is PT2, so force-removing it leaves them with no
        # primary value. That's a real consequence, and validate must flag it
        # rather than let it slip into the site.
        run(["remove", "primary_topic", "--id", "PT2", "--force"])
        assert any("missing a Rank=1" in e and "P002" in e for e in all_errors())

    def test_rejects_unknown_id(self, data_root):
        with pytest.raises(SystemExit, match="No category with ID"):
            run(["remove", "region", "--id", "RG404"])
