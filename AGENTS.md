# Working in this repo

Guidance for AI agents and new contributors. The short version: never hand-edit
`docs/data/`, and run `make check` before opening a PR.

## Before you open a PR

Three gates must pass. CI runs exactly these on every pull request
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), so running them
locally first is the fastest way to avoid a red check:

```bash
make check
```

That is equivalent to:

```bash
ruff check .            # lint
pytest                  # tests
python scripts/validate.py   # referential integrity of docs/data/
```

First-time setup: `pip install -r requirements-dev.txt` (or `make install-dev`).
That file is deliberately minimal -- the heavy notebook stack in
`requirements.txt` is only needed to regenerate map embeddings, not to run the
gates.

Validation is the gate that matters most here. The site is a static read of
`docs/data/`, so a dangling ID doesn't fail loudly at build time -- it silently
renders a broken or invisible philosopher in production.

## Never hand-edit `docs/data/`

Use the CLIs. They maintain the invariants that `validate.py` enforces
(contiguous ranks, one primary value per dimension, symmetric influence edges,
a coordinate row in every map file):

```bash
# Categories (the controlled vocabulary)
python scripts/manage_dimensions.py list primary_topic
python scripts/manage_dimensions.py add primary_topic --name "..." --description "..."
python scripts/manage_dimensions.py rename primary_topic --id PT7 --name "..."
python scripts/manage_dimensions.py merge primary_topic --from PT16 --into PT7
python scripts/manage_dimensions.py remove primary_topic --id PT16 [--force]

# Philosophers (dimension values given by name, resolved against the vocabulary)
python scripts/manage_philosophers.py add --spec new_philosopher.json
python scripts/manage_philosophers.py edit --id P042 --spec patch.json
python scripts/manage_philosophers.py remove --id P042 [--force]
```

Adding a philosopher with a category name that doesn't exist is **rejected by
default**. That rejection is the feature: it's what stops the free-text drift
this data model was built to eliminate. Add the category deliberately with
`manage_dimensions.py` first, with a real description. `--allow-new-categories`
exists as an escape hatch but leaves a `TODO` description you must then edit.

## The data model in one paragraph

A small star schema under `docs/data/`, all plain CSV/JSON so GitHub Pages can
serve it with no build step. `philosophers.csv` is the fact table.
`dimensions/manifest.json` declares the ten dimensions; each has a vocabulary
table (`dimensions/<key>.csv`: `ID, Name, Description`) and a link table
(`links/<key>_links.csv`: `PhilosopherID, DimensionID, Rank`, where `Rank=1` is
the primary value used for map colouring). `relations.csv` holds the influence
graph, with both directions kept symmetric. The `coords_*.csv` files hold 2D
positions for the three map views (`ID, x, y` only), and `embeddings/*.csv`
holds the source vectors those positions were reduced from. All I/O goes through
[`scripts/lib/data_model.py`](scripts/lib/data_model.py) -- don't hand-roll CSV
paths.

The manifest is the contract: adding a dimension there is enough for the
frontend to pick it up as a new "Color by" option, with no JS change.

## Writing tests

Tests must never touch the real `docs/data/`. Use the `data_root` fixture from
[`tests/conftest.py`](tests/conftest.py), which builds a small synthetic dataset
in a `tmp_path` and points the data model at it:

```python
def test_something(data_root):
    ...
```

A session-scoped autouse fixture content-hashes `docs/data/` before and after
the run and fails the suite if anything changed, so a test that writes to the
real data will be caught rather than quietly corrupting the dataset and
producing confusing git diffs.

## Things that will surprise you

- **Map coordinates for new philosophers are placeholders.** `add` copies the
  position of the most dimensionally-similar existing philosopher and jitters
  it. It is not a real embedding. Rerun `notebooks/semantics2vec.ipynb` and
  `notebooks/node2vec.ipynb` to regenerate real positions.
- **Removing a philosopher who has any influence edges requires `--force`.**
  Because edges are mirrored onto the other philosopher's row, anyone with a
  relation counts as "referenced elsewhere". `--force` is safe here; it strips
  those mirrored references.
- **Dimension IDs are permanent.** `next_dimension_id` fills past the highest
  existing number rather than reusing gaps, so a deleted `RG2` is never
  reissued to a different category.
- **Coords files are `ID,x,y` and nothing else.** The vectors they were reduced
  from live in `docs/data/embeddings/`. `validate.py` fails on any extra column
  and `save_coords()` drops one, because carrying vectors in the coords is how
  the map's initial download became 3.1MB to draw 101 points. If you regenerate
  coordinates from a frame that still has embeddings attached, the split is
  preserved for you rather than silently undone.
- **A new philosopher gets no embedding.** `add` copies a neighbour's *position*
  but not their vector; sharing one would make the two identical to anything
  measuring similarity. Missing vectors are a valid state and validation allows
  them -- rerun the notebooks to fill them in.
- **Search is built in the browser, from data already loaded.** `docs/search.js`
  indexes names, works, tags, dimension values, and teaching prose at startup;
  there is no index file to regenerate and no build step. Queries are folded to
  ASCII, so adding a philosopher with diacritics needs nothing extra. If you add
  a searchable field, add it to `buildSearchIndex` with a `kind` that exists in
  `FIELD_SCORES`, and remember prose ranks last on purpose.
- **The phone breakpoints are declared twice, on purpose.** `SMALL_SCREEN_QUERY`
  and `DETAIL_SHEET_QUERY` in `docs/main.js` mirror `@media` rules in
  `docs/index.html`: the stylesheet decides how things look, the script decides
  where the map is drawn and where a selected node parks. Change one and you
  must change the other, or the map is laid out for a phone while the chrome is
  styled for a desktop. `tests/test_responsive_layout.py` fails loudly if they
  drift, which is the only reason the duplication is safe.
- **On phones the controls are moved into the sheet, not cloned.** There is one
  map toggle, one colour select and one legend in the document at any time;
  `placeControls()` relocates the live elements so their handlers and state come
  with them. If you add a control to the bar, decide whether it belongs in the
  sheet and add it there too -- otherwise it silently vanishes below 640px,
  where the stylesheet hides bar children.
- **Anything hover-only needs a touch answer.** Legend spotlighting is a hover
  effect with no touch equivalent, so the hint text is chosen from
  `(hover: hover)` rather than hard-coded. Tooltips (`<title>`, `title=`) are
  invisible on a phone; if a feature only exists on hover, a touch reader
  cannot reach it at all.
- **`ShortName` is data, not a derived value.** It's the label on the map. When
  `add` omits `short_name`, it's seeded from `derive_short_name()` and the
  chosen value is printed -- check it. The heuristic handles parentheticals
  (`Avicenna (Ibn Sina)` -> `Avicenna`) and `X of Place` (`Augustine of Hippo`
  -> `Augustine`), but it cannot know that `Zhu Xi` shortens to `Zhu Xi` rather
  than `Xi`, or that Ockham is known by the place and Augustine isn't. If the
  philosopher's common short form isn't just their last name, set `short_name`
  explicitly. `validate.py` will reject an empty one, and rejects labels
  containing brackets since those indicate a name truncated mid-parenthetical.
