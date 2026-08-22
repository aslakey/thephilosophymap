"""
Migration 0001: split docs/data/details.csv into the star-schema data model.

Before this migration, `details.csv` held both narrative fields (CoreTeachings,
HistoricalContext, ...) and 10 categorical "dimensional" fields as free text --
either raw (Region, Civilization/Tradition, Era) or as this repo's previous
`*Group` columns produced by the now-retired regex classifiers
(SchoolMovementGroup, PrimaryTopicsGroup, etc.).

This migration is a one-time, re-readable record of that transformation. It:
  1. Writes the new `docs/data/philosophers.csv` fact table (narrative + scalar
     fields only -- the categorical columns move out).
  2. For each of the 10 dimensions, writes `docs/data/dimensions/<key>.csv`
     (ID, Name, Description) using the hand-written descriptions below, and
     `docs/data/links/<key>_links.csv` (PhilosopherID, DimensionID, Rank)
     preserving every value each philosopher had (Rank=1 is the first/primary
     value, matching the frontend's previous "color by first value" behavior).
  3. Writes `docs/data/dimensions/manifest.json`, the formal contract listing
     every dimension.
  4. Deletes the now-superseded `details.csv`.

Run once:
    python scripts/migrations/0001_split_into_dimension_tables.py

It's safe to re-run: if `details.csv` is already gone, it does nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.data_model import (  # noqa: E402
    PHILOSOPHER_COLUMNS,
    data_dir,
    dimensions_dir,
    links_dir,
    manifest_path,
    philosophers_path,
    write_manifest,
)

DETAILS_PATH = data_dir() / "details.csv"
OLD_PHILOSOPHERS_PATH = data_dir() / "philosophers.csv"  # old ID,Name-only file; overwritten in place

# (key, label, id prefix, source column in details.csv)
DIMENSION_SPECS = [
    ("region", "Region", "RG", "Region"),
    ("civilization", "Civilization / Tradition", "CV", "Civilization/Tradition"),
    ("era", "Era", "ER", "Era"),
    ("school_movement", "School / Movement", "SM", "SchoolMovementGroup"),
    ("primary_topic", "Primary Topics", "PT", "PrimaryTopicsGroup"),
    ("metaphysical_stance", "Metaphysical Stance", "MS", "MetaphysicalStanceGroup"),
    ("epistemological_stance", "Epistemological Stance", "ES", "EpistemologicalStanceGroup"),
    ("ethical_orientation", "Ethical Orientation", "EO", "EthicalOrientationGroup"),
    ("political_orientation", "Political Orientation", "PO", "PoliticalOrientationGroup"),
    ("religious_orientation", "Religious Orientation", "RO", "ReligiousOrientationGroup"),
]

# Hand-written descriptions for every category, keyed by dimension key.
# Dict order = the dimension table's row order (most-to-least common).
DESCRIPTIONS: dict[str, dict[str, str]] = {
    "region": {
        "Europe": "Continental and British Europe from the medieval period onward -- the historical center of gravity for Scholastic, Rationalist, Empiricist, Idealist, and 19th-20th century Continental and Analytic philosophy.",
        "North America": "The United States and Canada, home to Pragmatism, mid-20th-century Analytic philosophy, and a wide range of contemporary academic and public philosophy.",
        "India": "The Indian subcontinent, source of the Hindu, Buddhist, and Jain philosophical traditions and their many schools of metaphysics, logic, and liberation.",
        "China": "China, home to the Confucian, Daoist, Mohist, and Legalist traditions and their many later revivals such as Neo-Confucianism.",
        "Greece": "Classical and Hellenistic Greece -- the birthplace of Socratic, Platonic, Aristotelian, Stoic, Epicurean, and Skeptical philosophy.",
        "Middle East": "The Islamic and Jewish philosophical centers of the medieval Middle East, where Greek philosophy was preserved, translated, and extended.",
        "Africa": "Sub-Saharan and continental African philosophical traditions and 20th-century thinkers writing from and about the African experience.",
        "Japan": "Japan, home to Zen Buddhist philosophy and its distinctive fusion of meditative practice and metaphysics.",
        "North Africa": "The Mediterranean coast of North Africa, a crossroads of Roman, Christian, and Islamic philosophical influence.",
        "South America": "South America, home to 20th-century Latin American philosophy engaging liberation, identity, and postcolonial thought.",
        "Australia": "Australia, representing contemporary Anglophone academic philosophy based in Oceania.",
    },
    "civilization": {
        "Modern European": "The broad current of European philosophy from the Renaissance through the 20th century, spanning Rationalism, Empiricism, Idealism, and Continental and Analytic traditions.",
        "American": "The philosophical tradition of the United States, from early Pragmatism through 20th-century Analytic and public philosophy.",
        "Latin Christian": "The Latin-speaking Christian intellectual world of medieval and early modern Europe, centered on Scholasticism and the Church.",
        "Classical Chinese": "The foundational period of Chinese philosophy, including Confucianism, Daoism, Mohism, and Legalism.",
        "Ancient Greek": "The philosophy of the Greek city-states from the Presocratics through Aristotle.",
        "Indian Buddhist": "The Buddhist philosophical schools that developed on the Indian subcontinent, from early Buddhism through Madhyamaka and Yogācāra.",
        "Islamic": "The philosophical tradition of the medieval Islamic world, synthesizing Greek philosophy with Islamic theology and law.",
        "Indian Hindu": "The Hindu philosophical schools of the Indian subcontinent, including Vedānta, Yoga, Sāṃkhya, and Nyāya.",
        "Ancient Roman": "The Latin philosophical culture of the Roman Republic and Empire, especially its adaptations of Greek Stoicism and Epicureanism.",
        "Neo-Confucian": "The medieval and early-modern Chinese revival and metaphysical elaboration of classical Confucian ethics.",
        "African": "Continental African philosophical traditions and movements, including African Socialism and Pan-Africanism.",
        "Latin American": "20th-century Latin American philosophy, often engaging liberation theology, indigenous thought, and postcolonial critique.",
        "Ancient Greek (Hellenistic)": "The Greek philosophical culture of the Hellenistic period following Alexander's conquests, including Stoicism, Epicureanism, and Skepticism.",
        "Jewish": "The philosophical tradition growing out of Jewish religious and intellectual life, from medieval rationalism to modern Jewish thought.",
        "Italian": "The philosophical culture of Renaissance and early modern Italy, especially civic and political humanism.",
        "Buddhist (Zen)": "The Zen Buddhist tradition, especially as it developed in medieval and modern Japan.",
        "Indian Jain": "The Jain philosophical tradition of the Indian subcontinent, centered on non-violence and its distinctive pluralist metaphysics.",
        "Caribbean/African": "The philosophical and political thought of the African diaspora in the Caribbean, especially Pan-African and anti-colonial thought.",
        "Canadian": "The philosophical tradition of English and French Canada within the broader North American academic context.",
        "Western": "A general label for philosophers working within the broad modern Western tradition without a more specific national or civilizational tag.",
    },
    "era": {
        "20th Century": "Roughly 1900-1999: the century of Analytic philosophy, phenomenology, existentialism, critical theory, and post-structuralism.",
        "Ancient": "Roughly the 6th century BCE through the death of Alexander the Great: the founding period of Greek and early Chinese and Indian philosophy.",
        "Medieval": "Roughly 500-1400 CE: the age of Scholasticism, Islamic and Jewish philosophy, and the synthesis of classical philosophy with religious tradition.",
        "Early Modern": "Roughly 1500-1780: the age of the Scientific Revolution, Rationalism, Empiricism, and the Enlightenment.",
        "Contemporary": "Roughly 2000-present: living or very recently active philosophers and the newest currents in the field.",
        "19th Century": "Roughly 1800-1899: the age of German Idealism, Romanticism, Utilitarianism, Marxism, and early Existentialism.",
        "Hellenistic": "Roughly 323-31 BCE, from Alexander's death to the rise of the Roman Empire: the age of Stoicism, Epicureanism, and Skepticism.",
        "Renaissance": "Roughly 1400-1500: the revival of classical learning and civic humanism in early modern Europe.",
    },
    "school_movement": {
        "Liberal / Political Theory": "Philosophers primarily known for theories of individual rights, the social contract, constitutional government, and the proper limits and justification of state power.",
        "Analytic Philosophy": "The 20th-century tradition emphasizing logical rigor, careful conceptual analysis, and close engagement with language, science, and formal logic.",
        "Ancient Greek & Roman": "The classical schools of Greek and Roman antiquity, including Platonism, Aristotelianism, Stoicism, Epicureanism, and Skepticism.",
        "Existentialism / Phenomenology": "20th-century movements centered on lived experience, consciousness, freedom, and the concrete situation of the individual human being.",
        "Confucian / Daoist / East Asian": "The classical and later Chinese schools -- Confucianism, Daoism, Mohism, and Legalism -- and their East Asian successors.",
        "Buddhist / Hindu / Jain": "The major philosophical schools of the Indian subcontinent built around liberation from suffering, including Buddhist, Hindu, and Jain traditions.",
        "Medieval / Scholastic Christian": "The Latin Christian philosophical tradition of the Middle Ages, synthesizing faith and reason through figures like Aquinas and Scotus.",
        "Marxism / Critical Theory": "Traditions analyzing society through material and economic structures, ideology, and power, from classical Marxism through the Frankfurt School.",
        "Post-structuralism / Postmodern Critique": "Late-20th-century movements questioning fixed structures of meaning, identity, and truth through genealogy, deconstruction, and discourse analysis.",
        "Empiricism": "The early modern and later tradition holding that knowledge derives primarily from sense experience rather than innate ideas or pure reason.",
        "German Idealism / Kantian": "The tradition following Kant that grounds reality and knowledge in the structuring activity of mind or spirit.",
        "Anti-colonial / Africana / Latin American": "20th-century movements of political and cultural thought confronting colonialism, race, and identity in Africa, its diaspora, and Latin America.",
        "Islamic Philosophy": "The medieval Islamic philosophical tradition (falsafa), integrating Greek philosophy, Islamic theology, and mysticism.",
        "Rationalism (Early Modern)": "The 17th-century tradition holding that reason alone, rather than sense experience, is the primary source of certain knowledge.",
        "Feminism / Gender Theory": "Philosophical traditions analyzing gender, patriarchy, and the situation of women, from early feminist ethics to later gender theory.",
        "Pragmatism": "The American philosophical tradition holding that the meaning and truth of ideas are tied to their practical consequences.",
        "Renaissance Humanism": "The revival of classical learning, rhetoric, and civic virtue in Renaissance Europe.",
    },
    "primary_topic": {
        "Ethics": "Questions about right action, virtue, the good life, and how one ought to live.",
        "Political Philosophy": "Questions about the state, justice, power, law, and the legitimate organization of society.",
        "Metaphysics": "Questions about the fundamental nature of reality, being, substance, causation, and existence.",
        "Philosophy of Religion": "Questions about God, the divine, faith, religious experience, and the relationship between reason and revelation.",
        "Epistemology": "Questions about the nature, sources, and limits of knowledge and justified belief.",
        "Social & Cultural Theory": "Analysis of society, culture, ideology, race, and power beyond the narrower confines of formal political theory.",
        "Logic & Language": "The formal study of valid reasoning, meaning, and how language relates to thought and the world.",
        "Philosophy of Mind": "Questions about consciousness, mental states, personal identity, and the relationship between mind and body.",
        "Aesthetics": "Questions about beauty, art, taste, and aesthetic experience and judgment.",
        "Philosophy of History": "Questions about the meaning, direction, and intelligibility of historical change.",
        "Philosophy of Science": "Questions about scientific method, explanation, evidence, and the structure of scientific theories.",
        "Education": "Questions about the aims, methods, and value of teaching and the formation of character and mind.",
        "Economics & Philosophy of Life": "Questions about material life, work, and the broader practical conduct and meaning of a human life.",
        "Existentialism": "Questions about freedom, authenticity, anxiety, and the meaning of individual existence.",
        "Philosophy of Law": "Questions about the nature of law, legal obligation, and the relationship between law and morality.",
    },
    "metaphysical_stance": {
        "Theism": "The view that a personal or providential God (or gods) exists and is metaphysically fundamental to reality.",
        "Materialism / Naturalism / Physicalism": "The view that reality is ultimately physical or natural, without appeal to immaterial souls, forms, or supernatural causes.",
        "Nominalism / Anti-essentialism": "The view that general categories, universals, and essences are human constructs or labels rather than mind-independent realities.",
        "Platonism / Realism about Forms": "The view that abstract Forms, universals, or ideal realities exist independently of and more fundamentally than the physical world.",
        "Existentialist / Phenomenological Ontology": "Accounts of being grounded in lived experience, consciousness, and the concrete structures of existing in the world.",
        "Hindu / Daoist / East-South Asian Metaphysics": "Metaphysical frameworks from Hindu and Daoist traditions, including non-dualism, the Dao, and cosmic or processual views of reality.",
        "Moral Realism / Value Theory": "The view that moral or evaluative facts and values are objectively real features of the world.",
        "Idealism": "The view that reality is fundamentally mental or spiritual in nature, with matter dependent on or constituted by mind.",
        "Skepticism / Anti-metaphysics": "Doubt about the possibility of secure metaphysical knowledge, or rejection of traditional metaphysical questions as confused or meaningless.",
        "Dualism": "The view that reality (or the human person) is composed of two fundamentally distinct kinds of substance, typically mind and matter.",
        "Aristotelian Realism / Hylomorphism": "The Aristotelian view that things are composites of form and matter, with substances as the basic units of reality.",
        "Social / Political Metaphysics": "Accounts of reality centered on social structures, historical forces, or the material conditions of collective life.",
        "Pluralism": "The view that reality is composed of many distinct, irreducible kinds of things rather than one unified substance or principle.",
        "Buddhist Non-dualism / Emptiness": "The Buddhist view that phenomena lack fixed, independent essence (emptiness) and arise through dependent origination.",
        "Pantheism / Process Philosophy": "The view that God is identical with or immanent in nature, or that reality is best understood as ongoing process rather than fixed substance.",
    },
    "epistemological_stance": {
        "Rationalism": "The view that reason and a priori argument, rather than sense experience, are the primary route to certain knowledge.",
        "Logical / Analytic Method": "Knowledge pursued through formal logic, precise conceptual analysis, and careful attention to language and argument structure.",
        "Faith / Scripture / Contemplative Insight": "Knowledge grounded in religious faith, scripture, revelation, or direct contemplative or meditative insight.",
        "Empiricism": "The view that knowledge derives primarily from sense experience and observation rather than innate ideas.",
        "Critical / Social Theory Method": "Knowledge pursued through critical analysis of ideology, power, and social structure, often with an emancipatory aim.",
        "Hermeneutics / Textual Interpretation": "Knowledge pursued through careful interpretation of texts, traditions, and their historical and cultural context.",
        "Pragmatism": "The view that beliefs are justified by their practical workability and consequences rather than correspondence to fixed truth.",
        "Skepticism": "Systematic doubt about the possibility of certain knowledge, used as a method of inquiry or a philosophical conclusion.",
        "Intuitionism": "The view that some truths, especially moral truths, are known directly through rational or moral intuition rather than argument.",
        "Genealogical / Deconstructive Method": "Knowledge pursued by tracing the historical origins of concepts or by unsettling the fixed oppositions within a text or tradition.",
        "Phenomenology": "Knowledge pursued through careful first-person description of conscious experience as it presents itself.",
        "Dialectical Method": "Knowledge pursued through the back-and-forth of question, contradiction, and synthesis between opposing positions.",
        "Foundationalism / Constructivism": "The view that justified belief rests on secure foundational premises, or alternatively is actively constructed through reasoned agreement.",
        "Thought Experiments": "Knowledge pursued through imagined scenarios designed to test and clarify our concepts and intuitions.",
        "Scientific Method": "Knowledge pursued through empirical observation, hypothesis, and experimental testing modeled on the natural sciences.",
    },
    "ethical_orientation": {
        "Virtue Ethics / Eudaimonism": "Ethics centered on the cultivation of good character and the virtues needed for human flourishing (eudaimonia).",
        "Civic / Communitarian Ethics": "Ethics centered on civic duty, the common good, and the individual's obligations to community and polity.",
        "No Systematic Ethics": "Philosophers who did not develop, or are not primarily known for, a systematic ethical theory.",
        "Existentialist Ethics": "Ethics centered on individual freedom, authenticity, and the self-creation of one's own values.",
        "Christian / Divine Command Ethics": "Ethics grounded in Christian revelation, divine command, grace, and the imitation of Christ.",
        "Buddhist / Hindu / Jain Ethics": "Ethics centered on compassion, non-violence, and liberation from suffering as developed in Buddhist, Hindu, and Jain traditions.",
        "Deontology / Rights-based Ethics": "Ethics centered on duty, moral rules, and individual rights rather than consequences or character.",
        "Socialist / Emancipatory Ethics": "Ethics centered on class emancipation, liberation from oppression, and the critique of exploitative social structures.",
        "Consequentialism / Utilitarianism": "Ethics that judges actions by their outcomes, especially the overall balance of happiness or well-being they produce.",
        "Discourse / Recognition Ethics": "Ethics grounded in mutual recognition, communicative rationality, and norms justified through open discourse.",
        "Confucian / Daoist Ethics": "Ethics centered on ritual propriety, role-based relationships, or natural spontaneity as developed in Confucian and Daoist thought.",
        "Stoic / Contemplative Ethics": "Ethics centered on inner tranquility, self-mastery, and living in accordance with nature or reason.",
        "Anti-colonial / Solidarity Ethics": "Ethics centered on liberation from colonial and racial oppression and solidarity among the oppressed.",
        "Feminist / Care Ethics": "Ethics centered on care, relationality, and the critique of gender inequality in traditional moral theory.",
        "Islamic Ethics": "Ethics grounded in Islamic revelation, law, and the cultivation of virtue within an Islamic framework.",
    },
    "political_orientation": {
        "Apolitical / Not Systematically Political": "Philosophers who did not develop a systematic political theory or were primarily focused outside of politics.",
        "Liberal": "Political thought centered on individual rights, limited government, and freedom of thought, speech, and commerce.",
        "Monarchist / Elitist / Advises Rulers": "Political thought favoring rule by a monarch or qualified elite, often taking the form of advice offered to rulers.",
        "Democratic / Republican": "Political thought favoring self-government, popular sovereignty, and constitutional or republican forms of rule.",
        "Religious / Theocratic": "Political thought grounding legitimate authority in religious law, doctrine, or ecclesiastical institutions.",
        "Radical Left / Revolutionary": "Political thought favoring fundamental, often revolutionary transformation of existing social and economic structures.",
        "Socialist / Social Democratic": "Political thought favoring collective ownership, economic redistribution, and a strong social welfare state.",
        "Anti-authoritarian / Anti-totalitarian": "Political thought centrally concerned with resisting authoritarian, fascist, or totalitarian concentrations of power.",
        "Reformist / Moderate": "Political thought favoring gradual, incremental improvement of existing institutions rather than revolution or radical change.",
        "Cosmopolitan / Globalist": "Political thought favoring international or global forms of community, justice, and obligation beyond the nation-state.",
        "Authoritarian / Strong State": "Political thought favoring a strong, centralized state with extensive power over social and individual life.",
        "Communist / Marxist": "Political thought favoring the abolition of private property and class society along Marxist lines.",
        "Anti-colonial / Pan-African": "Political thought centered on resisting colonialism and imperialism and on African political unity and self-determination.",
        "Feminist / Queer Politics": "Political thought centered on gender equality and the critique of patriarchal and heteronormative power structures.",
        "Communitarian / Critical of Liberalism": "Political thought emphasizing community, tradition, and shared goods against what it sees as excessive liberal individualism.",
        "Political Realism": "Political thought emphasizing the practical realities of power over idealized moral or institutional theorizing.",
        "Libertarian": "Political thought favoring minimal government and maximal individual liberty, especially in economic life.",
        "Cultural Nationalist": "Political thought centered on the cultural distinctiveness and self-determination of a particular nation or people.",
    },
    "religious_orientation": {
        "Secular / Atheist / Agnostic": "Philosophers who are non-religious, atheist, agnostic, or otherwise skeptical of or critical toward religious belief.",
        "Christian (Protestant)": "Philosophers working within, or shaped by, the Protestant Christian tradition.",
        "Christian (Catholic)": "Philosophers working within, or shaped by, the Roman Catholic Christian tradition.",
        "Jewish": "Philosophers working within, or shaped by, Jewish religious tradition and identity.",
        "Deist / Liberal Theist / Eclectic": "Philosophers holding an unorthodox, rationalist, or eclectic religious outlook that doesn't fit neatly into a single confessional tradition.",
        "Pagan / Ancient Polytheist": "Philosophers working within the polytheistic religious world of pre-Christian Greek and Roman antiquity.",
        "Christian (Other/Generic)": "Philosophers identified with Christianity in a general sense, without a specific confessional affiliation given.",
        "Buddhist": "Philosophers working within, or shaped by, Buddhist religious tradition.",
        "Confucian / East Asian Traditional": "Philosophers working within Confucian ritual and ancestral traditions of East Asia.",
        "Muslim": "Philosophers working within, or shaped by, Islamic religious tradition.",
        "Hindu": "Philosophers working within, or shaped by, Hindu religious tradition.",
        "Daoist / East Asian Traditional": "Philosophers working within Daoist religious and cosmological tradition.",
        "Jain": "Philosophers working within, or shaped by, Jain religious tradition.",
    },
}


def split_multi(raw) -> list[str]:
    if pd.isna(raw) or not str(raw).strip():
        return []
    return [p.strip() for p in str(raw).split(";") if p.strip()]


def build_philosophers_table(details: pd.DataFrame) -> pd.DataFrame:
    names = pd.read_csv(OLD_PHILOSOPHERS_PATH, dtype=str)[["ID", "Name"]]
    narrative = details[["ID", "BirthYear", "DeathYear", "CoreTeachings", "HistoricalContext", "KeyWorks", "Tags"]]
    philosophers = names.merge(narrative, on="ID", how="left")
    return philosophers[PHILOSOPHER_COLUMNS]


def build_dimension_and_links(details: pd.DataFrame, key: str, prefix: str, source_column: str):
    descriptions = DESCRIPTIONS[key]

    # Curated order first (already most-to-least common), then anything new
    # found in the data that isn't in DESCRIPTIONS yet (shouldn't happen, but
    # fail loudly rather than silently dropping a category).
    ordered_names: list[str] = list(descriptions.keys())
    seen = set(ordered_names)
    for raw in details[source_column]:
        for name in split_multi(raw):
            if name not in seen:
                ordered_names.append(name)
                seen.add(name)

    missing_descriptions = [n for n in ordered_names if n not in descriptions]
    if missing_descriptions:
        raise ValueError(f"[{key}] missing hand-written description(s) for: {missing_descriptions}")

    name_to_id = {name: f"{prefix}{i + 1}" for i, name in enumerate(ordered_names)}

    dim_df = pd.DataFrame(
        [{"ID": name_to_id[n], "Name": n, "Description": descriptions[n]} for n in ordered_names],
        columns=["ID", "Name", "Description"],
    )

    link_rows = []
    for _, row in details.iterrows():
        for rank, name in enumerate(split_multi(row[source_column]), start=1):
            link_rows.append({"PhilosopherID": row["ID"], "DimensionID": name_to_id[name], "Rank": rank})
    links_df = pd.DataFrame(link_rows, columns=["PhilosopherID", "DimensionID", "Rank"])

    return dim_df, links_df


def main():
    if not DETAILS_PATH.exists():
        print(f"{DETAILS_PATH} not found -- migration already applied. Nothing to do.")
        return

    details = pd.read_csv(DETAILS_PATH, dtype=str)

    dimensions_dir().mkdir(parents=True, exist_ok=True)
    links_dir().mkdir(parents=True, exist_ok=True)

    manifest = []
    for key, label, prefix, source_column in DIMENSION_SPECS:
        dim_df, links_df = build_dimension_and_links(details, key, prefix, source_column)

        dim_path = dimensions_dir() / f"{key}.csv"
        links_path = links_dir() / f"{key}_links.csv"
        dim_df.to_csv(dim_path, index=False)
        links_df.to_csv(links_path, index=False)

        manifest.append({
            "key": key,
            "label": label,
            "file": f"dimensions/{key}.csv",
            "linksFile": f"links/{key}_links.csv",
        })

        print(f"{key:25s} {len(dim_df):3d} categories, {len(links_df):4d} links")

    write_manifest(manifest)
    print(f"\nWrote {manifest_path()}")

    philosophers = build_philosophers_table(details)
    philosophers.to_csv(philosophers_path(), index=False)
    print(f"Wrote {philosophers_path()} ({len(philosophers)} philosophers)")

    DETAILS_PATH.unlink()
    print(f"Removed {DETAILS_PATH} (superseded by dimensions/ + links/ + philosophers.csv)")


if __name__ == "__main__":
    main()
