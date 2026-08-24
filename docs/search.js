// search.js -- lexical search across the whole corpus, not just names.
//
// The index is built in memory at startup from data main.js has already
// fetched, so this adds no download and no build step. The corpus is small
// (101 philosophers, ~300 works, ~300 tags, ~120 dimension values), which is
// why a linear scan over pre-folded strings is fast enough and no inverted
// index or scoring library is warranted.
//
// A result is a *set* of philosophers rather than a single point: "Stoicism"
// and "free will" are answered by several people, and main.js spotlights them
// on the map instead of zooming to one.

const SEARCH_RESULT_LIMIT = 8;

// Characters shown either side of a prose match in the snippet.
const SNIPPET_RADIUS = 44;

// Scores are per field and per how well the query fits it, best-field-wins.
// The gaps matter more than the absolute values, and two orderings are
// deliberate:
//
//   prose sits far below everything, so searching "Plato" returns Plato rather
//   than the dozen philosophers whose teachings discuss him;
//
//   an exact category beats an exact tag, so "Stoicism" returns the school and
//   its whole membership rather than one philosopher who happens to be tagged
//   with it. Categories are a curated vocabulary; tags are free text.
const FIELD_SCORES = {
  name: { exact: 100, prefix: 80, contains: 65 },
  category: { exact: 75, prefix: 60, contains: 40 },
  work: { exact: 70, prefix: 58, contains: 55 },
  tag: { exact: 50, prefix: 45, contains: 42 },
  identifier: { exact: 35, prefix: 35, contains: 35 },
  categoryDescription: { exact: 20, prefix: 20, contains: 20 },
  prose: { exact: 10, prefix: 10, contains: 10 },
};

// Letters that survive Unicode decomposition because they are distinct letters
// rather than a base plus a combining accent. Without these, "Søren" folds to
// "Sren" and stays unfindable no matter what the user types.
const LETTER_FOLDINGS = {
  "ø": "o", "Ø": "O",
  "æ": "ae", "Æ": "AE",
  "œ": "oe", "Œ": "OE",
  "ß": "ss",
  "ł": "l", "Ł": "L",
  "đ": "d", "Đ": "D",
  "ð": "d", "Ð": "D",
  "þ": "th", "Þ": "Th",
  "ħ": "h", "ı": "i",
};

const COMBINING_MARKS = /[\u0300-\u036f]/g;

// Folds to lowercase ASCII and returns, alongside the folded text, a map from
// each folded character back to its index in the original. Folding can change
// length ("æ" becomes two characters), so without the map a match offset found
// in folded text would slice the original string in the wrong place.
function foldWithMap(text) {
  const folded = [];
  const indexMap = [];
  const source = text || "";

  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    const replacement = Object.prototype.hasOwnProperty.call(LETTER_FOLDINGS, char)
      ? LETTER_FOLDINGS[char]
      : char.normalize("NFD").replace(COMBINING_MARKS, "");

    for (const foldedChar of replacement.toLowerCase()) {
      folded.push(foldedChar);
      indexMap.push(i);
    }
  }

  return { folded: folded.join(""), indexMap };
}

function fold(text) {
  return foldWithMap(text).folded;
}

function splitList(value) {
  return (value || "").split(";").map(s => s.trim()).filter(Boolean);
}

// -------- Index --------

// Each entry is one thing a user might search for. `philosopherIDs` is what
// the map does with it: one ID zooms, several spotlight.
function makeEntry(type, label, detail, philosopherIDs, fields) {
  return {
    type,
    label,
    detail,
    philosopherIDs,
    fields: fields.map(f => ({
      scores: FIELD_SCORES[f.kind],
      isProse: Boolean(f.isProse),
      original: f.text || "",
      ...foldWithMap(f.text || ""),
    })),
  };
}

// philosophers:  array of rows from philosophers.csv
// manifest:      dimension manifest entries [{key, label, ...}]
// tables:        key -> Map(DimensionID -> {ID, Name, Description})
// linksByPhil:   key -> Map(PhilosopherID -> [{DimensionID, Rank}, ...])
function buildSearchIndex(philosophers, manifest, tables, linksByPhil) {
  const entries = [];

  philosophers.forEach(p => {
    const fields = [
      { text: p.Name, kind: "name" },
      { text: p.ShortName, kind: "name" },
      { text: p.ID, kind: "identifier" },
      ...splitList(p.Tags).map(tag => ({ text: tag, kind: "tag" })),
      { text: p.CoreTeachings, kind: "prose", isProse: true },
      { text: p.HistoricalContext, kind: "prose", isProse: true },
    ];
    entries.push(makeEntry("philosopher", p.Name, "philosopher", [p.ID], fields));

    // Works are indexed as their own results so "Republic" is answerable, and
    // the result says whose work it is rather than silently jumping to Plato.
    splitList(p.KeyWorks).forEach(work => {
      entries.push(makeEntry("work", work, `work by ${p.ShortName || p.Name}`, [p.ID], [
        { text: work, kind: "work" },
      ]));
    });
  });

  // Dimension values resolve to everyone linked to them, which is what makes
  // "Stoicism" or "Existentialism" a meaningful thing to search for.
  (manifest || []).forEach(entry => {
    const table = tables[entry.key];
    const links = linksByPhil[entry.key];
    if (!table || !links) return;

    const membersByDimension = new Map();
    links.forEach((linkList, philosopherID) => {
      linkList.forEach(link => {
        const members = membersByDimension.get(link.DimensionID) || [];
        members.push(philosopherID);
        membersByDimension.set(link.DimensionID, members);
      });
    });

    table.forEach(row => {
      const members = membersByDimension.get(row.ID) || [];
      if (members.length === 0) return;
      const plural = members.length === 1 ? "philosopher" : "philosophers";
      entries.push(makeEntry(
        "category",
        row.Name,
        `${entry.label}, ${members.length} ${plural}`,
        members,
        [
          { text: row.Name, kind: "category" },
          { text: row.Description, kind: "categoryDescription", isProse: true },
        ]
      ));
    });
  });

  return entries;
}

// -------- Matching --------

// Pulls a readable window around a prose match, snapped to word boundaries so
// the snippet doesn't start mid-word. Offsets refer to the original text.
function buildSnippet(field, foldedIndex, foldedLength) {
  const start = field.indexMap[foldedIndex];
  const endFolded = Math.min(foldedIndex + foldedLength, field.indexMap.length) - 1;
  const end = field.indexMap[endFolded] + 1;

  let from = Math.max(0, start - SNIPPET_RADIUS);
  let to = Math.min(field.original.length, end + SNIPPET_RADIUS);

  if (from > 0) {
    const space = field.original.indexOf(" ", from);
    if (space !== -1 && space < start) from = space + 1;
  }
  if (to < field.original.length) {
    const space = field.original.lastIndexOf(" ", to);
    if (space !== -1 && space > end) to = space;
  }

  return {
    text: (from > 0 ? "\u2026" : "") + field.original.slice(from, to) + (to < field.original.length ? "\u2026" : ""),
    matchStart: start - from + (from > 0 ? 1 : 0),
    matchLength: end - start,
  };
}

function scoreEntry(entry, foldedQuery, queryTokens) {
  let best = null;

  for (const field of entry.fields) {
    if (!field.folded) continue;

    const at = field.folded.indexOf(foldedQuery);
    if (at === -1) continue;

    // How well the query fills the field is what makes "Kant" rank above
    // everyone whose teachings merely mention Kant.
    let score;
    if (field.folded === foldedQuery) score = field.scores.exact;
    else if (at === 0) score = field.scores.prefix;
    else score = field.scores.contains;

    if (!best || score > best.score) {
      best = {
        score,
        snippet: field.isProse ? buildSnippet(field, at, foldedQuery.length) : null,
      };
    }
  }

  if (best) return best;

  // No field contains the phrase, so fall back to requiring every token
  // somewhere in the entry. This is what answers "greek virtue", where the two
  // words live in different sentences.
  if (queryTokens.length < 2) return null;
  const haystack = entry.fields.map(f => f.folded).join(" ");
  if (!queryTokens.every(token => haystack.includes(token))) return null;

  const proseField = entry.fields.find(f => f.isProse && f.folded.includes(queryTokens[0]));
  return {
    score: FIELD_SCORES.prose.contains,
    snippet: proseField
      ? buildSnippet(proseField, proseField.folded.indexOf(queryTokens[0]), queryTokens[0].length)
      : null,
  };
}

function runSearch(index, query, limit = SEARCH_RESULT_LIMIT) {
  const foldedQuery = fold(query).trim();
  if (!foldedQuery) return [];
  const queryTokens = foldedQuery.split(/\s+/).filter(Boolean);

  const results = [];
  for (const entry of index) {
    const match = scoreEntry(entry, foldedQuery, queryTokens);
    if (!match) continue;
    results.push({
      type: entry.type,
      label: entry.label,
      detail: entry.detail,
      philosopherIDs: entry.philosopherIDs,
      score: match.score,
      snippet: match.snippet,
    });
  }

  results.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    // Prefer the result that commits to fewer philosophers: a specific person
    // is more useful than a 20-member category when both score the same.
    if (a.philosopherIDs.length !== b.philosopherIDs.length) {
      return a.philosopherIDs.length - b.philosopherIDs.length;
    }
    return a.label.localeCompare(b.label);
  });

  // One philosopher can match as themselves and through several of their
  // works; showing all of those crowds out everyone else.
  const seen = new Set();
  const deduped = [];
  for (const result of results) {
    const key = `${result.type}:${result.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(result);
    if (deduped.length >= limit) break;
  }

  return deduped;
}
