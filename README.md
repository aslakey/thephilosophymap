```markdown
# Map of Philosophy: Reader Overview

This project is a guided map of philosophical thought across time, place, and tradition. It is designed to help readers see the big picture first, then move into specific thinkers, ideas, and debates.

## What This Map Covers

The map brings together philosophers from different eras and cultures so the reader can compare how they approached similar questions:

- Who are we, and what is reality?  
- How do we know what is true?  
- What makes an action good or just?  
- How should people and societies be governed?  
- What is the role of religion, reason, and human freedom?

## How to Read It

Each philosopher is presented as a short profile that describes, among other things:

- **Historical setting** – when and where they lived.  
- **Core ideas** – the main teachings they are known for.  
- **Major themes** – the topics they focused on most.  
- **Intellectual connections** – who influenced them and whom they influenced (within this map).

By highlighting different themes and connections, the map lets readers follow both continuity and change, from ancient schools to contemporary thought. These categories are not rigid labels; they are guideposts to navigate a very diverse intellectual landscape.

## Why This Is Useful

The map is meant to support different reading and study goals:

- Fast orientation for beginners  
- Cross‑tradition comparison for students  
- Idea‑tracking for deeper study  
- A reference point for discussion, writing, and teaching  

Instead of treating philosophers as isolated figures, it highlights philosophy as an ongoing conversation shaped by history, argument, and influence.

---

## How the Maps Are Made

The web app currently shows two complementary map types, each built from a different signal:

1. **Influence Map (Graph-Based)**
- Source data: the `Relations` table (`InfluencedByIDs` and `InfluencedIDs`).
- Method: build a directed graph where each philosopher is a node and each influence relationship is an edge.
- Embedding: run `node2vec` on that graph to learn a vector for each philosopher from network structure (who connects to whom).
- Projection: reduce those vectors to 2D (for plotting) and export coordinates used by the frontend.

2. **Semantic Map (Text-Based)**
- Source data: each philosopher's teaching summary (the `CoreTeachings` overview in `details.csv`).
- Method: generate OpenAI sentence embeddings for each teaching summary.
- Embedding: each philosopher gets a vector based on semantic similarity of ideas, language, and themes.
- Projection: reduce vectors to 2D (for example with t-SNE or UMAP) and export coordinates for visualization.

In short: the influence map groups thinkers by **historical/intellectual linkage**, while the semantic map groups them by **conceptual similarity in their teachings**.

Generated coordinate files are stored under `web/data/` (for example `coords_node2vec_tsne.csv`, `coords_semantic_tsne.csv`, and `coords_semantic_umap.csv`), and are consumed by `web/main.js` for rendering.

---

## Hosting Locally
With simple python server:
`python3 -m http.server 8000`


## Developer Env

### Python
Use `uv` (installed with homebrew for mac). Env setup:

`$ uv python install 3.12`
`$uv venv`
`source .venv/bin/activate`
`uv pip install networkx node2vec umap-learn pandas matplotlib scikit-learn jupyter`

I had to do this for older mac:
`uv pip install umap-learn numba --only-binary=numba,llvmlite`

Freeze requirements:
`uv pip freeze > requirements.txt`



## Data Structure Overview

The project uses three main tables:

1. **Philosophers** – identity only (for stable IDs)  
2. **PhilosopherDetails** – descriptive fields for each philosopher  
3. **Relations** – influence graph between philosophers  

This separation makes it easier to maintain IDs, update descriptions, and build visualizations.

---

## 1. Philosophers Table

**Purpose:** a minimal lookup of all philosophers with stable IDs.

**Columns**

1. `ID`  
2. `Name`

**Examples**

- `P003,Aristotle`  
- `P029,Immanuel Kant`  
- `P074,Nāgārjuna`  
- `P101,Siddhārtha Gautama (the Buddha)`

---

## 2. PhilosopherDetails Table

**Purpose:** the main descriptive schema for profiles, used for reading, search, and filtering.

**Columns**

1. `ID`  
2. `BirthYear`  
3. `DeathYear`  
4. `Region`  
5. `Civilization/Tradition`  
6. `Era`  
7. `School/Movement`  
8. `CoreTeachings`  
9. `HistoricalContext`  
10. `PrimaryTopics`  
11. `MetaphysicalStance`  
12. `EpistemologicalStance`  
13. `EthicalOrientation`  
14. `PoliticalOrientation`  
15. `ReligiousOrientation`  
16. `KeyWorks`  
17. `Tags`

### Column Explanations

**1. ID**  
- Short unique ID (e.g. `P001`, `P002`).  
- Used as the primary key and to link with other tables.  
- Join this to the `ID` in the **Philosophers** table to recover the name.

**2–3. BirthYear / DeathYear**  
- Integer years; use negative for BCE (e.g. `-384` for 384 BCE).  
- Can be left blank or approximate if dates are uncertain.

**4. Region**  
- Broad geographic category, useful for map‑based views:  
  - `Greece`, `China`, `India`, `Europe`, `Middle East`, `Africa`, `Latin America`, `North America`, `Japan`, etc.

**5. Civilization/Tradition**  
- Cultural‑intellectual tradition, e.g.:  
  - `Ancient Greek`, `Classical Chinese`, `Indian Buddhist`, `Indian Hindu`, `Islamic`, `Jewish`, `Scholastic`, `Modern European`, `Analytic`, `Continental`, `African`, `Latin American`, etc.  
- Good for color‑coding traditions.

**6. Era**  
- Coarse time period for filtering:  
  - `Ancient`, `Classical`, `Medieval`, `Renaissance`, `Early Modern`, `19th Century`, `20th Century`, `Contemporary`.

**7. School/Movement**  
- More specific philosophical affiliation, e.g.:  
  - `Platonism`, `Aristotelianism`, `Stoicism`, `Epicureanism`, `Neoplatonism`  
  - `Confucianism`, `Daoism`, `Legalism`, `Neo‑Confucianism`, `Zen`  
  - `Vedānta`, `Madhyamaka`, `Nyāya`, `Jain`  
  - `Rationalism`, `Empiricism`, `Kantian`, `Utilitarianism`, `Marxism`, `Existentialism`  
  - `Phenomenology`, `Pragmatism`, `Analytic Philosophy`, `Critical Theory`, `Post‑structuralism`, `Feminist Philosophy`, etc.  
- Allow multiple values separated by `;` (e.g. `Existentialism; Phenomenology`).

**8. CoreTeachings**  
- 3–4 sentences in plain text.  
- Concise but content‑rich summary of what the philosopher is known for:
  - Key doctrines, questions, and characteristic methods.  
- This is the “core description” a reader sees first.

**9. HistoricalContext**  
- 2–3 sentences on:  
  - When and where they lived.  
  - Major historical events and social background.  
  - Roles they played (e.g. tutor to Alexander the Great, monk, civil servant, activist).  
- Focus on how context shaped their thought (wars, empires, religious conflict, industrialization, decolonization, etc.).

**10. PrimaryTopics**  
- Controlled vocabulary; 3–7 items, separated by `;`. For example:  
  - `Metaphysics; Epistemology; Ethics; Political Philosophy; Philosophy of Mind; Aesthetics; Philosophy of Religion; Logic; Philosophy of Language; Social Theory; Feminist Theory; Critical Race Theory; Philosophy of Science; Philosophy of History`.  
- Ideal for topic‑based filtering and color‑coding.

**11. MetaphysicalStance**  
- Short label for their general metaphysical orientation, e.g.:  
  - `Materialism`, `Idealism`, `Dualism`, `Monism`, `Platonism`, `Aristotelian Realism`, `Phenomenology`, `Skepticism`, `Nondualism`, `Theism`, `Atheism`, `Agnostic`, `Process Philosophy`, `Emptiness (Śūnyavāda)`.  
- Multiple values can be separated by `;` when needed.

**12. EpistemologicalStance**  
- High‑level categories, such as:  
  - `Rationalism`, `Empiricism`, `Skepticism`, `Pragmatism`, `Phenomenology`, `Intuitionism`, `Mystical Insight`, `Critical Theory (knowledge/power)`.  
- Multiple values allowed (e.g. `Empiricism; Skepticism`).

**13. EthicalOrientation**  
- Short descriptors for their ethics, for comparison and clustering, e.g.:  
  - `Virtue Ethics`, `Deontology`, `Consequentialism`, `Utilitarianism`, `Care Ethics`, `Eudaimonism`, `Asceticism`, `Perfectionism`, `Existential Ethics`, `Bodhisattva Ethics`, `Divine Command`, `Natural Law`, `No Systematic Ethics`.

**14. PoliticalOrientation**  
- Captures broad political leanings or models, e.g.:  
  - `Authoritarian`, `Liberal`, `Libertarian`, `Socialist`, `Communist`, `Republican (classical)`, `Democrat (broad)`, `Conservative`, `Anarchist`, `Revolutionary`, `Reformist`, `Anti‑colonial`, `Monarchist`, `Theocratic`, `Not Primarily Political`.

**15. ReligiousOrientation**  
- Short tags for religious background or outlook, such as:  
  - `Christian`, `Catholic`, `Protestant`, `Jewish`, `Muslim`, `Hindu`, `Buddhist`, `Jain`, `Daoist`, `Confucian`, `Skeptical of Religion`, `Atheist`, `Agnostic`, `Mystic`, `Syncretic`.

**16. KeyWorks**  
- 2–5 titles, separated by `;`.  
- Use standard English titles where possible (original titles can be added later).  
  - Example: `Nicomachean Ethics; Metaphysics; Politics`.

**17. Tags**  
- Free‑form keywords for anything that doesn’t neatly fit elsewhere; `;`‑separated.  
- For example: `Tutor of Alexander the Great; Lyceum; Peripatetic`, or `Decolonial; Race; Psychoanalysis`.

---

## 3. Relations Table (Influence Graph)

**Purpose:** represent the influence network between philosophers using IDs from the **Philosophers** table.

**Columns**

1. `ID`  
2. `InfluencedByIDs`  
3. `InfluencedIDs`

### Column Explanations

**1. ID**  
- Philosopher ID (e.g. `P029` for Kant).  
- This is the same ID used in the **Philosophers** and **PhilosopherDetails** tables.

**2. InfluencedByIDs**  
- A `;`‑separated list of IDs of earlier or foundational figures who clearly influenced this philosopher’s thought **within this dataset**.  
  - Example: for Kant, something like: `P023;P025;P027;P028`.

**3. InfluencedIDs**  
- A `;`‑separated list of IDs of later philosophers in the dataset who were significantly influenced by this thinker.  
  - Example: for Plato, `P003;P009;P010;P011;...`.

You can either:

- Maintain both directions manually, or  
- Treat `InfluencedByIDs` as primary and generate `InfluencedIDs` programmatically as the reverse edges.

---

## 4. Using the Tables for Filtering and Visualization

For search, filtering, and visual exploration, the most useful fields are:

- **From PhilosopherDetails**  
  - `Civilization/Tradition` – color by tradition or lineage.  
  - `Era` – timeline placement or time‑slider filters.  
  - `PrimaryTopics` – topic filters (e.g. “show everyone focused on ethics and political philosophy”).  
  - `School/Movement` – cluster by school (e.g. Stoics, Marxists, Neo‑Confucians).  
  - `MetaphysicalStance`, `EpistemologicalStance`, `EthicalOrientation`, `PoliticalOrientation`, `ReligiousOrientation` – for more advanced filtering or faceted search.  
  - `Region` – map views (geographical origin).

- **From Relations**  
  - `InfluencedByIDs` / `InfluencedIDs` – building influence graphs, network diagrams, or “intellectual family trees.”

Together, these tables define the structure behind the “map of philosophy” and support both a readable guide and rich visualizations.
