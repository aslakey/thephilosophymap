"""
Tests for map short names (the ShortName column and its seeding heuristic).

The heuristic only has to handle the two mechanical patterns; anything
requiring knowledge of a name is expected to be authored in the data, and these
tests pin down which is which.
"""
from __future__ import annotations

import manage_philosophers
import pytest
import validate
from lib.data_model import derive_short_name, load_philosophers, save_philosophers
from test_manage_philosophers import VALID_SPEC, run, write_spec
from test_validate import all_errors


class TestDeriveShortName:
    @pytest.mark.parametrize(
        "full,expected",
        [
            ("Immanuel Kant", "Kant"),
            ("Jean-Paul Sartre", "Sartre"),
            ("Simone de Beauvoir", "Beauvoir"),
            ("G.W.F. Hegel", "Hegel"),
            ("Maurice Merleau-Ponty", "Merleau-Ponty"),
        ],
    )
    def test_western_names_use_the_last_token(self, full, expected):
        assert derive_short_name(full) == expected

    @pytest.mark.parametrize("full", ["Socrates", "Plato", "Maimonides", "Dōgen", "Nāgārjuna"])
    def test_single_token_names_pass_through(self, full):
        assert derive_short_name(full) == full

    @pytest.mark.parametrize(
        "full,expected",
        [
            ("Siddhārtha Gautama (the Buddha)", "Gautama"),
            ("Avicenna (Ibn Sina)", "Avicenna"),
            ("Confucius (Kongzi)", "Confucius"),
            ("bell hooks (Gloria Jean Watkins)", "hooks"),
        ],
    )
    def test_parentheticals_are_stripped_never_truncated(self, full, expected):
        # The bug being fixed produced "Buddha)" / "(Kongzi)"; whatever the
        # heuristic returns, it must never contain bracket debris.
        result = derive_short_name(full)
        assert result == expected
        assert not any(ch in result for ch in "()[]")

    @pytest.mark.parametrize(
        "full,expected",
        [
            ("Augustine of Hippo", "Augustine"),
            ("Zeno of Citium", "Zeno"),
            ("Anselm of Canterbury", "Anselm"),
            ("Erasmus of Rotterdam", "Erasmus"),
        ],
    )
    def test_of_place_keeps_the_name_not_the_place(self, full, expected):
        assert derive_short_name(full) == expected

    def test_surname_particles_are_not_treated_as_places(self):
        # "de"/"van" belong to the surname, unlike English "of".
        assert derive_short_name("Simone de Beauvoir") == "Beauvoir"
        assert derive_short_name("Vincent van Gogh") == "Gogh"

    @pytest.mark.parametrize("full", ["Zhu Xi", "Han Feizi", "Ibn Khaldun", "William of Ockham"])
    def test_knowledge_cases_are_not_expected_from_the_heuristic(self, full):
        # Documents the boundary: these need an authored ShortName, which is
        # exactly why the column exists. The heuristic must still return
        # something non-empty and bracket-free rather than failing.
        result = derive_short_name(full)
        assert result
        assert not any(ch in result for ch in "()[]")

    def test_empty_input(self):
        assert derive_short_name("") == ""
        assert derive_short_name(None) == ""


class TestValidation:
    def test_clean_fixture_passes(self, data_root):
        assert all_errors() == []
        assert validate.check_philosophers(load_philosophers()) == []

    def test_empty_short_name_is_caught(self, data_root):
        df = load_philosophers()
        df.loc[df["ID"] == "P002", "ShortName"] = "  "
        save_philosophers(df)
        assert any("empty ShortName" in e for e in validate.check_philosophers(load_philosophers()))

    def test_bracket_debris_is_caught(self, data_root):
        # Guards against a regression to the old last-token behaviour.
        df = load_philosophers()
        df.loc[df["ID"] == "P002", "ShortName"] = "Buddha)"
        save_philosophers(df)
        errors = validate.check_philosophers(load_philosophers())
        assert any("bracket characters" in e for e in errors)

    def test_missing_column_is_caught(self, data_root):
        df = load_philosophers().drop(columns=["ShortName"])
        df.to_csv(data_root / "philosophers.csv", index=False)
        assert any("missing ShortName column" in e for e in validate.check_philosophers(load_philosophers()))

    def test_duplicate_ids_still_caught(self, data_root):
        df = load_philosophers()
        df.loc[len(df)] = dict(df.iloc[0])
        save_philosophers(df)
        assert any("duplicate IDs" in e for e in validate.check_philosophers(load_philosophers()))


class TestCli:
    def test_short_name_from_spec_is_used(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "short_name": "D."}
        run(["add", "--spec", write_spec(tmp_path, spec)])
        df = load_philosophers()
        assert df.loc[df["ID"] == "P004", "ShortName"].iloc[0] == "D."

    def test_short_name_is_derived_when_omitted(self, data_root, tmp_path):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        df = load_philosophers()
        assert df.loc[df["ID"] == "P004", "ShortName"].iloc[0] == "Delta"

    def test_derivation_is_announced(self, data_root, tmp_path, capsys):
        run(["add", "--spec", write_spec(tmp_path, VALID_SPEC)])
        assert "derived short name" in capsys.readouterr().out

    def test_added_philosopher_passes_validation(self, data_root, tmp_path):
        spec = {**VALID_SPEC, "name": "Xyz of Somewhere"}
        run(["add", "--spec", write_spec(tmp_path, spec)])
        assert all_errors() == []

    def test_short_name_can_be_edited(self, data_root, tmp_path):
        run(["edit", "--id", "P001", "--spec", write_spec(tmp_path, {"short_name": "A."})])
        df = load_philosophers()
        assert df.loc[df["ID"] == "P001", "ShortName"].iloc[0] == "A."
        assert df.loc[df["ID"] == "P001", "Name"].iloc[0] == "Alpha"

    def test_scalar_field_map_exposes_short_name(self):
        assert manage_philosophers.SCALAR_FIELD_MAP["short_name"] == "ShortName"
