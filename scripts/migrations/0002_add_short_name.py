"""
Add a ShortName column to philosophers.csv.

The map labels each point with a short form of the philosopher's name. That was
previously derived in the frontend by taking the last whitespace-separated
token, which broke in three systematic ways:

  parentheticals     "Siddhārtha Gautama (the Buddha)" -> "Buddha)"
  "X of Place"       "Augustine of Hippo"              -> "Hippo"
  non-Western order  "Zhu Xi"                          -> "Xi"

The last two are the dangerous ones: "Hippo" and "Xi" look like plausible
names, so unlike "Buddha)" nobody notices they are wrong.

The first two patterns are mechanical and handled by derive_short_name(). The
rest is knowledge, not pattern -- no rule can know that Augustine of Hippo is
"Augustine" while William of Ockham is "Ockham" -- so those are curated below
and stored in the data, where validation can enforce them.

Safe to re-run: if ShortName already exists, only blank values are filled.

Usage:
    python scripts/migrations/0002_add_short_name.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.data_model import (  # noqa: E402
    PHILOSOPHER_COLUMNS,
    derive_short_name,
    load_philosophers,
    save_philosophers,
)

# Full Name -> ShortName, for cases the heuristic cannot get right on its own.
CURATED_SHORT_NAMES = {
    # Conventionally referred to by both names.
    "Marcus Aurelius": "Marcus Aurelius",
    "John Duns Scotus": "Duns Scotus",
    # "X of Place" where the place, not the given name, is the common short form.
    "William of Ockham": "Ockham",
    # Chinese names put the family name first, inverting the last-token rule.
    "Han Feizi": "Han Feizi",
    "Zhu Xi": "Zhu Xi",
    "Wang Yangming (Wang Shouren)": "Wang Yangming",
    # "Ibn X" is kept whole.
    "Ibn Khaldun": "Ibn Khaldun",
    # Stylised lowercase is deliberate and part of the name.
    "bell hooks (Gloria Jean Watkins)": "bell hooks",
    # Known by the epithet rather than the given name.
    "Siddhārtha Gautama (the Buddha)": "Buddha",
    # A school rather than a person; shortened to fit as a map label.
    "Nyāya/Vaiśeṣika (Gautama and later figures)": "Nyāya",
}


def main():
    philosophers = load_philosophers()

    if "ShortName" not in philosophers.columns:
        philosophers["ShortName"] = ""

    filled, curated, skipped = 0, 0, 0
    for index, row in philosophers.iterrows():
        if str(row.get("ShortName", "")).strip():
            skipped += 1
            continue

        name = row["Name"]
        if name in CURATED_SHORT_NAMES:
            philosophers.at[index, "ShortName"] = CURATED_SHORT_NAMES[name]
            curated += 1
        else:
            philosophers.at[index, "ShortName"] = derive_short_name(name)
            filled += 1

    unknown = set(CURATED_SHORT_NAMES) - set(philosophers["Name"])
    if unknown:
        print(f"Warning: curated entries match no philosopher: {sorted(unknown)}")

    save_philosophers(philosophers[PHILOSOPHER_COLUMNS])
    print(f"ShortName populated: {filled} derived, {curated} curated, {skipped} already set.")
    print("\nCurated values:")
    for name, short in CURATED_SHORT_NAMES.items():
        print(f"  {name!r} -> {short!r}")


if __name__ == "__main__":
    main()
