"""Tests for scripts/manage_philosophers.py."""
from __future__ import annotations

import json

import manage_philosophers
import pytest
from lib.data_model import (
    COORDS_FILENAMES,
    load_coords,
    load_dimension,
    load_embeddings,
    load_links,
    load_philosophers,
    load_relations,
)
from test_validate import all_errors


def run(argv: list[str]) -> None:
    args = manage_philosophers.build_parser().parse_args(argv)
    args.func(args)


def write_spec(tmp_path, spec: dict) -> str:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def relations_for(philosopher_id: str) -> dict[str, str]:
    relations = load_relations()
    row = relations[relations["ID"] == philosopher_id]
    if row.empty:
        return {}
    return {
        "InfluencedByIDs": row.iloc[0]["InfluencedByIDs"],
        "InfluencedIDs": row.iloc[0]["InfluencedIDs"],
    }


VALID_SPEC = {
    "name": "Delta",
    "birth_year": 1750,
    "death_year": 1820,
    "core_teachings": "Teachings of Delta.",
    "historical_context": "Context of Delta.",
    "key_works": "Delta's Book",
    "tags": "enlightenment",
    "region": ["Europe"],
    "primary_topic": ["Ethics", "Logic"],
}


class TestAdd:
    def test_creates_philosopher_with_next_id(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        philosophers = load_philosophers()
        assert "P004" in set(philosophers["ID"])
        row = philosophers[philosophers["ID"] == "P004"].iloc[0]
        assert row["Name"] == "Delta"
        assert row["BirthYear"] == "1750"
        assert row["CoreTeachings"] == "Teachings of Delta."

    def test_creates_links_in_spec_order(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        links = load_links("primary_topic")
        new = links[links["PhilosopherID"] == "P004"].sort_values("Rank")
        # "Ethics" first in the spec means Rank=1, which is what colours the map.
        assert new["DimensionID"].tolist() == ["PT1", "PT3"]
        assert new["Rank"].tolist() == [1, 2]

    def test_creates_relations_row_even_without_relations(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        assert relations_for("P004") == {"InfluencedByIDs": "", "InfluencedIDs": ""}

    def test_assigns_coordinates_in_every_map(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        for filename in COORDS_FILENAMES:
            assert "P004" in set(load_coords(filename)["ID"]), filename

    def test_places_new_philosopher_near_its_closest_match(self, data_root, tmp_path):
        # Delta shares Europe + Ethics with Alpha (P001) at (0, 0), so the
        # placeholder should land next to Alpha rather than anywhere else.
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        coords = load_coords("coords_node2vec_tsne.csv")
        row = coords[coords["ID"] == "P004"].iloc[0]
        assert abs(float(row["x"])) < 1.0
        assert abs(float(row["y"])) < 1.0

    def test_does_not_pick_itself_as_neighbour(self, data_root, tmp_path, capsys):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        out = capsys.readouterr().out
        assert "P004" not in out.split("Nearest neighbor by shared categories:")[1].split("\n")[0]

    def test_does_not_fabricate_an_embedding(self, data_root, tmp_path):
        # The placeholder position is copied from a neighbour, but the vector is
        # not: sharing one would make the two philosophers indistinguishable to
        # anything measuring similarity, which is worse than having none.
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        assert "embedding" not in load_coords("coords_semantic_tsne.csv").columns
        assert "P004" not in set(load_embeddings("semantic_1536.csv")["ID"])

    def test_missing_embedding_is_not_a_validation_error(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        assert all_errors() == []

    def test_result_validates_clean(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        assert all_errors() == []

    def test_requires_a_name(self, data_root, tmp_path):
        with pytest.raises(SystemExit, match="must include"):
            run(["add", "--spec", write_spec(tmp_path, {"region": ["Europe"]})])

    def test_spec_without_dimensions_skips_placement(self, data_root, tmp_path, capsys):
        run(["add", "--spec", write_spec(tmp_path, {"name": "Nameless"})])
        assert "no placeholder map position" in capsys.readouterr().out


class TestControlledVocabulary:
    def test_rejects_unknown_category(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "primary_topic": ["Phrenology"]}
        with pytest.raises(SystemExit, match="Unknown 'primary_topic' category"):
            run(["add", "--spec", write_spec(tmp_path, spec)])

    def test_suggests_a_near_miss(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "primary_topic": ["Ethic"]}
        with pytest.raises(SystemExit, match="Did you mean"):
            run(["add", "--spec", write_spec(tmp_path, spec)])

    def test_allow_new_categories_creates_it_with_a_todo(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "primary_topic": ["Phrenology"]}
        run(["add", "--spec", write_spec(tmp_path, spec), "--allow-new-categories"])
        topics = load_dimension("primary_topic")
        new = topics[topics["Name"] == "Phrenology"]
        assert not new.empty
        assert new.iloc[0]["Description"].startswith("TODO")

    def test_created_category_is_flagged_by_validation_until_described(self, data_root, tmp_path):
        # A TODO description is deliberately not a real description, but it is
        # non-empty, so validation passes -- the guard is the visible TODO.
        spec = {**VALID_SPEC, "primary_topic": ["Phrenology"]}
        run(["add", "--spec", write_spec(tmp_path, spec), "--allow-new-categories"])
        assert all_errors() == []
        topics = load_dimension("primary_topic")
        assert "TODO" in topics[topics["Name"] == "Phrenology"].iloc[0]["Description"]


class TestAddAtomicity:
    def test_unknown_category_leaves_no_partial_philosopher(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "primary_topic": ["Phrenology"]}
        with pytest.raises(SystemExit):
            run(["add", "--spec", write_spec(tmp_path, spec)])
        assert set(load_philosophers()["ID"]) == {"P001", "P002", "P003"}
        assert "P004" not in set(load_links("region")["PhilosopherID"])
        assert "P004" not in set(load_relations()["ID"])
        for filename in COORDS_FILENAMES:
            assert "P004" not in set(load_coords(filename)["ID"])

    def test_unknown_influence_leaves_no_partial_philosopher(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "influenced_by": ["Nobody At All"]}
        with pytest.raises(SystemExit, match="Unknown philosopher"):
            run(["add", "--spec", write_spec(tmp_path, spec)])
        assert set(load_philosophers()["ID"]) == {"P001", "P002", "P003"}
        assert "P004" not in set(load_links("region")["PhilosopherID"])

    def test_unknown_influence_creates_no_categories(self, data_root, tmp_path):
        # With --allow-new-categories the dimension tables are written during
        # resolution, so a later failure must not leave an orphan category
        # behind for a philosopher that was never created.
        spec = {**VALID_SPEC, "primary_topic": ["Phrenology"], "influenced_by": ["Nobody At All"]}
        with pytest.raises(SystemExit, match="Unknown philosopher"):
            run(["add", "--spec", write_spec(tmp_path, spec), "--allow-new-categories"])
        assert "Phrenology" not in set(load_dimension("primary_topic")["Name"])

    def test_dataset_still_validates_after_a_rejected_add(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "primary_topic": ["Phrenology"]}
        with pytest.raises(SystemExit):
            run(["add", "--spec", write_spec(tmp_path, spec)])
        assert all_errors() == []


class TestInfluenceRelations:
    def test_influenced_by_is_mirrored_onto_the_other_philosopher(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "influenced_by": ["Alpha"]}
        run(["add", "--spec", write_spec(tmp_path, spec)])
        assert relations_for("P004")["InfluencedByIDs"] == "P001"
        assert "P004" in relations_for("P001")["InfluencedIDs"]

    def test_influenced_is_mirrored_in_reverse(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "influenced": ["Gamma"]}
        run(["add", "--spec", write_spec(tmp_path, spec)])
        assert relations_for("P004")["InfluencedIDs"] == "P003"
        assert "P004" in relations_for("P003")["InfluencedByIDs"]

    def test_accepts_ids_and_names_together(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "influenced_by": ["Alpha", "P002"]}
        run(["add", "--spec", write_spec(tmp_path, spec)])
        assert set(relations_for("P004")["InfluencedByIDs"].split(";")) == {"P001", "P002"}

    def test_editing_relations_removes_the_stale_reverse_edge(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, {**VALID_SPEC, "influenced_by": ["Alpha"]})])
        assert "P004" in relations_for("P001")["InfluencedIDs"]
        run(["edit", "--id", "P004", "--spec", write_spec(tmp_path, {"influenced_by": ["Beta"]})])
        assert "P004" not in relations_for("P001")["InfluencedIDs"]
        assert "P004" in relations_for("P002")["InfluencedIDs"]

    def test_relations_stay_valid(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "influenced_by": ["Alpha"], "influenced": ["Gamma"]}
        run(["add", "--spec", write_spec(tmp_path, spec)])
        assert all_errors() == []


class TestEdit:
    def test_patches_only_the_given_scalar_fields(self, data_root, tmp_path):
        run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"tags": "updated"})])
        row = load_philosophers().set_index("ID").loc["P001"]
        assert row["Tags"] == "updated"
        assert row["Name"] == "Alpha"
        assert row["CoreTeachings"] == "Teachings of Alpha."

    def test_replaces_links_for_the_given_dimension(self, data_root, tmp_path):
        run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"primary_topic": ["Logic"]})])
        links = load_links("primary_topic")
        p001 = links[links["PhilosopherID"] == "P001"]
        assert p001["DimensionID"].tolist() == ["PT3"]
        assert p001["Rank"].tolist() == [1]

    def test_leaves_dimensions_absent_from_the_patch_untouched(self, data_root, tmp_path):
        before = load_links("region")
        run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"primary_topic": ["Logic"]})])
        assert load_links("region").equals(before)

    def test_does_not_touch_coordinates(self, data_root, tmp_path):
        before = load_coords("coords_node2vec_tsne.csv")
        run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"tags": "updated"})])
        assert load_coords("coords_node2vec_tsne.csv").equals(before)

    def test_rejects_unknown_philosopher(self, data_root, tmp_path):
        with pytest.raises(SystemExit, match="No philosopher with ID"):
            run(["edit", "--id", "P404", "--spec", write_spec(tmp_path, {"tags": "x"})])

    def test_rejects_unknown_category(self, data_root, tmp_path):
        with pytest.raises(SystemExit, match="Unknown 'primary_topic' category"):
            run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"primary_topic": ["Phrenology"]})])

    def test_result_validates_clean(self, data_root, tmp_path):
        run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"primary_topic": ["Logic", "Ethics"]})])
        assert all_errors() == []


class TestRemove:
    def test_removes_philosopher_links_relations_and_coords(self, data_root, tmp_path):
        run(["remove", "--id", "P003"])
        assert "P003" not in set(load_philosophers()["ID"])
        assert "P003" not in set(load_links("region")["PhilosopherID"])
        assert "P003" not in set(load_links("primary_topic")["PhilosopherID"])
        assert "P003" not in set(load_relations()["ID"])
        for filename in COORDS_FILENAMES:
            assert "P003" not in set(load_coords(filename)["ID"]), filename

    def test_refuses_while_referenced_by_others(self, data_root):
        # P001 influenced P002, so removing P001 would dangle that reference.
        with pytest.raises(SystemExit, match="still referenced"):
            run(["remove", "--id", "P001"])

    def test_refusal_changes_nothing(self, data_root):
        with pytest.raises(SystemExit):
            run(["remove", "--id", "P001"])
        assert "P001" in set(load_philosophers()["ID"])
        assert all_errors() == []

    def test_force_strips_references(self, data_root):
        run(["remove", "--id", "P001", "--force"])
        assert "P001" not in set(load_philosophers()["ID"])
        assert "P001" not in relations_for("P002")["InfluencedByIDs"]

    def test_result_validates_clean(self, data_root):
        run(["remove", "--id", "P003"])
        assert all_errors() == []

    def test_force_result_validates_clean(self, data_root):
        run(["remove", "--id", "P001", "--force"])
        assert all_errors() == []

    def test_rejects_unknown_philosopher(self, data_root):
        with pytest.raises(SystemExit, match="No philosopher with ID"):
            run(["remove", "--id", "P404"])


class TestRoundTrip:
    def test_add_then_remove_restores_the_original_dataset(self, data_root, tmp_path):
        before = {
            "philosophers": load_philosophers().to_csv(index=False),
            "region": load_links("region").to_csv(index=False),
            "primary_topic": load_links("primary_topic").to_csv(index=False),
            "relations": load_relations().to_csv(index=False),
        }
        run(["add", "--spec", write_spec(tmp_path, {**VALID_SPEC, "influenced_by": ["Alpha"]})])
        # --force is required because the mirrored edge on Alpha's row counts as
        # an outside reference; see test_removing_a_philosopher_with_any_edge_needs_force.
        run(["remove", "--id", "P004", "--force"])
        after = {
            "philosophers": load_philosophers().to_csv(index=False),
            "region": load_links("region").to_csv(index=False),
            "primary_topic": load_links("primary_topic").to_csv(index=False),
            "relations": load_relations().to_csv(index=False),
        }
        assert after == before
        assert all_errors() == []

    def test_removing_a_philosopher_with_any_edge_needs_force(self, data_root, tmp_path):
        # Documents a sharp edge in the current design: because every influence
        # edge is mirrored onto the other philosopher's row, a philosopher with
        # any relations is by definition "referenced elsewhere", so plain
        # `remove` refuses even though the only references are their own
        # mirrored edges. Removing is safe with --force.
        run(["add", "--spec", write_spec(tmp_path, {**VALID_SPEC, "influenced_by": ["Alpha"]})])
        with pytest.raises(SystemExit, match="still referenced"):
            run(["remove", "--id", "P004"])
        run(["remove", "--id", "P004", "--force"])
        assert all_errors() == []
