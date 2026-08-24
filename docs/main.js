// main.js

const width = window.innerWidth;
const height = window.innerHeight;
const NODE_RADIUS = 10;
const ZOOM_MIN = 0.2;
const ZOOM_MAX = 10;
const LABEL_ZOOM_THRESHOLD = 2.2;
const MODAL_DESIRED_SCALE = 3;
// Each dimension is a curated, described vocabulary of ~8-20 categories (see
// docs/data/dimensions/manifest.json), so allow enough legend slots to show
// them all without falling back to an "Other" bucket. Colours are generated to
// fit this count -- see categoricalPalette().
const LEGEND_MAX_MAIN_CATEGORIES = 20;
const DEFAULT_COLOR_BY_KEY = "era";
const THEME_STORAGE_KEY = "mop-theme";

// Opacity for points filtered out via the legend, and for the rest of the map
// while hovering a single legend category.
const DIMMED_OPACITY = 0.08;
const SPOTLIGHT_OTHERS_OPACITY = 0.14;

// Global references to current state
let currentNodes = [];
let svg, g, simulation;
let currentTransform = d3.zoomIdentity;  // track current zoom/pan
let zoomBehavior = null;

let selectedID = null;           // current selected philosopher
let globalColorByField = null;   // dimension key of current color field, e.g. "era"
let globalColorScale = null;     // current D3 scale
let globalColorValueMapper = null;
let globalColorDescByName = new Map(); // category Name -> Description, for the active color-by dimension

let legendDomain = [];             // categories shown in the legend, in display order

// Legend interaction state.
let hiddenCategories = new Set();  // categories toggled off by clicking the legend
let hoveredCategory = null;        // category currently hovered in the legend

// Search state. An idea matches a set of philosophers rather than one point,
// so the result is a spotlight rather than a camera move.
let searchIndex = [];
let searchMatchIDs = null;         // Set of IDs, or null when no search is active

// -------- Colour --------

function isDarkTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

// Categorical colours generated in HCL so every swatch shares a chroma and
// lightness family, which keeps the map coherent instead of looking like two
// palettes stitched together. Hues are spread evenly to maximise the smallest
// distance between any two categories, and lightness alternates to give a
// second axis of separation -- necessary because some dimensions carry 20
// categories, where hue alone leaves neighbours only 18 degrees apart.
function categoricalPalette(count) {
  const dark = isDarkTheme();
  const colors = d3.range(count).map(i => {
    const even = i % 2 === 0;
    return d3.hcl(
      ((i * 360) / count + 15) % 360,
      even ? 58 : 70,
      dark ? (even ? 74 : 61) : (even ? 65 : 50)
    ).formatHex();
  });

  // Legend order follows category frequency, so hand out hues from opposite
  // sides of the wheel alternately -- otherwise the most common categories,
  // which sit next to each other in the legend, get adjacent hues.
  const half = Math.ceil(count / 2);
  const interleaved = [];
  for (let i = 0; i < half; i++) {
    interleaved.push(colors[i]);
    if (i + half < count) interleaved.push(colors[i + half]);
  }
  return interleaved;
}

// Absent or bucketed data shouldn't compete with real categories for attention.
function neutralColor(category) {
  const dark = isDarkTheme();
  if (category === "Unknown") return dark ? "#475569" : "#cbd5e1";
  return dark ? "#64748b" : "#94a3b8";
}

function colorForCategory(category) {
  if (category === "Unknown" || category === "Other") return neutralColor(category);
  return globalColorScale ? globalColorScale(category) : neutralColor("Other");
}

function accentColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#4f46e5";
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (err) {
    // Storage can be unavailable (private browsing); the theme still applies.
  }
  // Palette lightness is chosen per theme, so the scale has to be rebuilt.
  if (globalColorByField) {
    rebuildColorScale(globalColorByField);
    recolorExistingNodes();
  }
}

// -------- Dimensional data model (docs/data/dimensions/manifest.json) --------
// Populated once at startup by loadStaticData(); everything else reads from
// these in-memory lookups instead of re-fetching CSVs.
let dimensionsManifest = [];                  // [{key, label, file, linksFile}, ...]
let philosophersById = new Map();             // ID -> philosophers.csv row
let dimensionTables = {};                     // key -> Map(DimensionID -> {ID, Name, Description})
let dimensionLinksByPhilosopher = {};         // key -> Map(PhilosopherID -> [{DimensionID, Rank}, ...] sorted by Rank)

function labelForDimensionKey(key) {
  const entry = dimensionsManifest.find(e => e.key === key);
  return entry ? entry.label : key;
}

// The philosopher's Rank=1 (primary) value for a dimension, or null if they
// have no linked value at all for that dimension.
function primaryValue(philosopherId, key) {
  const links = dimensionLinksByPhilosopher[key] && dimensionLinksByPhilosopher[key].get(philosopherId);
  if (!links || links.length === 0) return null;
  const table = dimensionTables[key];
  return (table && table.get(links[0].DimensionID)) || null;
}

// All of the philosopher's linked values for a dimension, in Rank order.
function allValues(philosopherId, key) {
  const links = dimensionLinksByPhilosopher[key] && dimensionLinksByPhilosopher[key].get(philosopherId);
  if (!links) return [];
  const table = dimensionTables[key];
  if (!table) return [];
  return links.map(l => table.get(l.DimensionID)).filter(Boolean);
}

function loadStaticData() {
  return d3.json("data/dimensions/manifest.json").then(manifest => {
    dimensionsManifest = manifest;

    const filePromises = [];
    manifest.forEach(entry => {
      filePromises.push(d3.csv("data/" + entry.file));
      filePromises.push(d3.csv("data/" + entry.linksFile));
    });
    filePromises.push(d3.csv("data/philosophers.csv"));

    return Promise.all(filePromises).then(results => {
      const philosophers = results[results.length - 1];
      philosophersById = new Map(philosophers.map(d => [d.ID, d]));

      manifest.forEach((entry, i) => {
        const dimRows = results[i * 2];
        const linkRows = results[i * 2 + 1];

        dimensionTables[entry.key] = new Map(dimRows.map(r => [r.ID, r]));

        const byPhilosopher = new Map();
        linkRows.forEach(r => {
          const list = byPhilosopher.get(r.PhilosopherID) || [];
          list.push({ DimensionID: r.DimensionID, Rank: +r.Rank });
          byPhilosopher.set(r.PhilosopherID, list);
        });
        byPhilosopher.forEach(list => list.sort((a, b) => a.Rank - b.Rank));
        dimensionLinksByPhilosopher[entry.key] = byPhilosopher;
      });
    });
  });
}

function rebuildColorScale(colorByField) {
  globalColorByField = colorByField;

  globalColorDescByName = new Map();
  const table = dimensionTables[colorByField];
  if (table) {
    table.forEach(row => globalColorDescByName.set(row.Name, row.Description));
  }

  const counts = new Map();
  currentNodes.forEach(d => {
    const rawValue = rawColorValueForNode(d, colorByField);
    counts.set(rawValue, (counts.get(rawValue) || 0) + 1);
  });

  const knownValues = Array.from(counts.keys())
    .filter(v => v !== "Unknown")
    .sort((a, b) => {
      const countDiff = (counts.get(b) || 0) - (counts.get(a) || 0);
      return countDiff !== 0 ? countDiff : a.localeCompare(b);
    });

  const keptValues = new Set(knownValues.slice(0, LEGEND_MAX_MAIN_CATEGORIES));
  const hasLongTail = knownValues.length > LEGEND_MAX_MAIN_CATEGORIES;

  globalColorValueMapper = (rawValue) => {
    if (rawValue === "Unknown") return "Unknown";
    if (keptValues.has(rawValue)) return rawValue;
    return hasLongTail ? "Other" : rawValue;
  };

  // Only real categories consume palette slots; "Other"/"Unknown" are rendered
  // in neutral grey by colorForCategory().
  const realCategories = knownValues.slice(0, LEGEND_MAX_MAIN_CATEGORIES);

  globalColorScale = d3.scaleOrdinal()
    .domain(realCategories)
    .range(categoricalPalette(Math.max(realCategories.length, 1)));

  legendDomain = realCategories.slice();
  if (hasLongTail) legendDomain.push("Other");
  if (counts.has("Unknown")) legendDomain.push("Unknown");

  // A category that no longer exists in this dimension shouldn't stay filtered.
  hiddenCategories = new Set([...hiddenCategories].filter(c => legendDomain.includes(c)));
  hoveredCategory = null;

  renderLegend();
}

function colorCategoryForNode(d) {
  const field = globalColorByField || DEFAULT_COLOR_BY_KEY;
  const rawValue = rawColorValueForNode(d, field);
  if (!globalColorValueMapper) return rawValue;
  return globalColorValueMapper(rawValue);
}

function renderLegend() {
  const legend = d3.select("#legend");
  if (legend.empty() || !globalColorScale || !globalColorByField) return;

  const groupedCounts = new Map();
  currentNodes.forEach(d => {
    const key = colorCategoryForNode(d);
    groupedCounts.set(key, (groupedCounts.get(key) || 0) + 1);
  });

  legend.html("");

  legend.append("div")
    .attr("class", "legend-title")
    .text(labelForDimensionKey(globalColorByField));

  legend.append("div")
    .attr("class", "legend-hint")
    .text("Hover to spotlight, click to filter");

  const rows = legend.selectAll(".legend-row")
    .data(legendDomain, d => d)
    .enter()
    .append("div")
    .attr("class", "legend-row")
    .classed("is-muted", d => hiddenCategories.has(d))
    .attr("title", d => globalColorDescByName.get(d) || "")
    .on("mouseenter", (_, d) => {
      hoveredCategory = hiddenCategories.has(d) ? null : d;
      updateNodeVisibility();
    })
    .on("mouseleave", () => {
      hoveredCategory = null;
      updateNodeVisibility();
    })
    .on("click", (_, d) => {
      if (hiddenCategories.has(d)) {
        hiddenCategories.delete(d);
        hoveredCategory = d;
      } else {
        hiddenCategories.add(d);
        hoveredCategory = null;
      }
      renderLegend();
      updateNodeVisibility();
    });

  rows.append("span")
    .attr("class", "legend-swatch")
    .style("background", d => colorForCategory(d));

  rows.append("span")
    .attr("class", "legend-label")
    .text(d => d);

  rows.append("span")
    .attr("class", "legend-count")
    .text(d => groupedCounts.get(d) || 0);
}

// Opacity for a single node given the current filter/spotlight state. Legend
// filtering and search spotlighting compose: a search result that a legend
// filter has hidden stays hidden.
function nodeOpacity(d) {
  const category = colorCategoryForNode(d);
  if (hiddenCategories.has(category)) return DIMMED_OPACITY;
  if (searchMatchIDs && !searchMatchIDs.has(d.ID)) return SPOTLIGHT_OTHERS_OPACITY;
  if (hoveredCategory && category !== hoveredCategory) return SPOTLIGHT_OTHERS_OPACITY;
  return 1;
}

function updateNodeVisibility() {
  d3.selectAll(".node")
    .style("opacity", d => nodeOpacity(d))
    // Filtered-out points shouldn't swallow clicks meant for visible ones.
    .style("pointer-events", d => hiddenCategories.has(colorCategoryForNode(d)) ? "none" : null);
}

function recolorExistingNodes() {
  if (!globalColorScale || !globalColorByField) return;

  d3.selectAll(".node circle")
    .attr("fill", d => colorForCategory(colorCategoryForNode(d)));

  // Re-apply stroke logic so selected node stays highlighted.
  updateSelectionHighlight();
  updateNodeVisibility();
}

function selectNode(node) {
  if (!node) return;
  selectedID = node.ID;
  updateSelectionHighlight();
}

function updateLabelVisibility(zoomScale = 1) {
  const showLabels = zoomScale >= LABEL_ZOOM_THRESHOLD;
  d3.selectAll(".node-label")
    .style("opacity", showLabels ? 1 : 0);
}

// Utility: clear and recreate SVG
function initSvg() {
  d3.select("#viz").selectAll("*").remove();

  svg = d3.select("#viz")
    .append("svg")
    .attr("width", width)
    .attr("height", height);

  g = svg.append("g");

  zoomBehavior = d3.zoom()
    .scaleExtent([ZOOM_MIN, ZOOM_MAX])
    .on("zoom", (event) => {
      currentTransform = event.transform;
      g.attr("transform", currentTransform);
      updateLabelVisibility(currentTransform.k);
    });

  svg.call(zoomBehavior);
}

// -------- Search + zoom to philosopher --------

function nodeById(id) {
  return currentNodes.find(d => d.ID === id) || null;
}

// Applying a result is the one place that decides between the map's two
// gestures: a single philosopher is worth flying to, a group is not.
function applySearchResult(result) {
  if (!result) return;

  const ids = result.philosopherIDs.filter(id => nodeById(id));
  if (ids.length === 0) return;

  if (ids.length === 1) {
    clearSearchSpotlight();
    const node = nodeById(ids[0]);
    selectNode(node);
    zoomToNode(node);
    return;
  }

  searchMatchIDs = new Set(ids);
  updateNodeVisibility();
  renderSearchStatus(`${ids.length} philosophers matching “${result.label}”`);
}

function clearSearchSpotlight() {
  if (!searchMatchIDs) {
    renderSearchStatus(null);
    return;
  }
  searchMatchIDs = null;
  updateNodeVisibility();
  renderSearchStatus(null);
}

function renderSearchStatus(text) {
  const status = document.getElementById("search-status");
  const label = document.getElementById("search-status-text");
  if (!status || !label) return;
  status.style.display = text ? "flex" : "none";
  label.textContent = text || "";
}

function zoomToNode(node) {
  if (!node || !svg || !zoomBehavior) return;

  const desiredScale = 3;
  const x = node.x;
  const y = node.y;

  const tx = width / 2 - desiredScale * x;
  const ty = height / 2 - desiredScale * y;

  svg.transition()
    .duration(750)
    .call(
      zoomBehavior.transform,
      d3.zoomIdentity.translate(tx, ty).scale(desiredScale)
    );
}

function focusNodeForModal(node) {
  if (!node || !svg || !zoomBehavior) return;

  const desiredScale = Math.max(currentTransform.k || 1, MODAL_DESIRED_SCALE);
  const targetScreenX = Math.max(140, Math.min(width * 0.33, width - 140));
  const targetScreenY = height / 2;

  const tx = targetScreenX - desiredScale * node.x;
  const ty = targetScreenY - desiredScale * node.y;

  svg.transition()
    .duration(550)
    .call(
      zoomBehavior.transform,
      d3.zoomIdentity.translate(tx, ty).scale(desiredScale)
    );
}

// -------- Data loading --------

function loadAndRender(coordsPath, colorBy) {
  d3.csv(coordsPath).then(coords => {
    const nodes = coords.map(d => {
      const id = d.ID;
      const philosopher = philosophersById.get(id) || {};
      const x0 = +d.x;
      const y0 = +d.y;
      return {
        ID: id,
        Name: philosopher.Name || id,
        x: x0,
        y: y0,
        x0,
        y0,
        targetX: null,
        targetY: null,
        philosopher
      };
    });

    currentNodes = nodes;
    createViz(nodes, colorBy);
  }).catch(err => {
    console.error("Error loading data:", err);
  });
}

// -------- Visualization --------

function createViz(nodes, colorByField) {
  initSvg();

  // Compute extents of original coordinates
  const xExtent = d3.extent(nodes, d => d.x0);
  const yExtent = d3.extent(nodes, d => d.y0);

  const xScale = d3.scaleLinear()
    .domain(xExtent)
    .range([50, width - 50]);

  const yScale = d3.scaleLinear()
    .domain(yExtent)
    .range([50, height - 50]);

  // 1) RANDOM INITIAL POSITIONS (for animation)
  nodes.forEach(d => {
    d.x = width * (0.2 + 0.6 * Math.random());   // random in central band
    d.y = height * (0.2 + 0.6 * Math.random());
  });
  // 2) SET TARGETS to the projected map layout (but don't overwrite x,y)
  nodes.forEach(d => {
    const sx = xScale(d.x0);
    const sy = yScale(d.y0);
    d.targetX = sx;
    d.targetY = sy;
  });

  // Build and store color scale for this render.
  rebuildColorScale(colorByField);

  function getColor(d) {
    return colorForCategory(colorCategoryForNode(d));
  }

  // One shared layer so the drop shadow is rasterised once rather than per node.
  const nodesLayer = g.append("g").attr("class", "nodes-layer");

  const node = nodesLayer.selectAll(".node")
    .data(nodes)
    .enter()
    .append("g")
    .attr("class", "node")
    .on("click", (_, d) => {
      selectNode(d);
      showModal(d);
    });

  node.append("circle")
    .attr("r", NODE_RADIUS)
    .attr("stroke-width", 1.5)
    .attr("fill", d => getColor(d));

  node.append("text")
    .attr("class", "node-label")
    .attr("text-anchor", "middle")
    .attr("dy", 3)
    .style("fill", "white")
    .style("font-size", "6px")
    .style("font-weight", 600)
    .style("paint-order", "stroke")
    .style("stroke", "rgba(0,0,0,0.45)")
    .style("stroke-width", "1px")
    .style("pointer-events", "none")
    .style("opacity", 0.0)    // hide labels by default; can be changed later
    .text(d => shortName(d.philosopher, d.Name));

  node.append("title")
    .text(d => d.Name || d.ID);

// Stronger target force so nodes snap closer to their targets
function forceToTargets(alpha) {
  for (const d of nodes) {
    // smaller coefficient makes pull gentler; larger makes them snap harder
    const k = 0.3;   // try 0.3–0.5 for stronger convergence
    d.vx += (d.targetX - d.x) * k * alpha;
    d.vy += (d.targetY - d.y) * k * alpha;
  }
}

simulation = d3.forceSimulation(nodes)
  .alpha(1.0)          // start hotter for more early motion
  .alphaDecay(0.03)    // slower decay: animation lasts longer
  .velocityDecay(0.4)  // less friction: nodes travel further per tick
  .force("collision", d3.forceCollide(NODE_RADIUS + 1))
  .force("targets", forceToTargets)
  .on("tick", () => {
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  updateSelectionHighlight();  // draw initial strokes (no selection yet)
  updateLabelVisibility(currentTransform.k);
  // Switching maps rebuilds every node, so any active legend filter or search
  // spotlight has to be re-applied or it silently disappears.
  updateNodeVisibility();
}

// -------- Helpers --------

// Map labels come from the authored ShortName column, because deriving them
// here can't be made correct: "Augustine of Hippo" would label as "Hippo" and
// "Zhu Xi" as "Xi". This fallback only covers a philosopher added without one.
function shortName(philosopher, fullName) {
  const authored = philosopher && philosopher.ShortName;
  if (authored && authored.trim()) return authored.trim();

  const base = (fullName || "").replace(/\s*[([][^)\]]*[)\]]/g, "").trim();
  if (!base) return fullName || "";
  const ofMatch = base.match(/^(.*?)\s+of\s+\S/i);
  if (ofMatch && ofMatch[1]) return ofMatch[1].trim();
  const parts = base.split(/\s+/);
  return parts[parts.length - 1];
}

function rawColorValueForNode(d, field) {
  const value = primaryValue(d.ID, field);
  return value ? value.Name : "Unknown";
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateSelectionHighlight() {
  // Unselected nodes get their ring from CSS (--node-ring), which is what keeps
  // overlapping points readable; only the selection overrides it.
  d3.selectAll(".node circle")
    .attr("stroke-width", d => d.ID === selectedID ? 3.5 : 1.5)
    .attr("stroke", d => d.ID === selectedID ? accentColor() : null);
}

function renderModalDimensionRows(philosopherId) {
  return dimensionsManifest.map(entry => {
    const values = allValues(philosopherId, entry.key);
    const valueHtml = values.length
      ? values.map(v => `<span class="chip" title="${escapeHtml(v.Description)}">${escapeHtml(v.Name)}</span>`).join(" ")
      : `<span class="chip-empty">—</span>`;
    return `<div class="dim-row"><span class="dim-label">${escapeHtml(entry.label)}</span>${valueHtml}</div>`;
  }).join("\n");
}

// Modal
function showModal(d) {
  const overlay = document.getElementById("modal-overlay");
  const titleEl = document.getElementById("modal-title");
  const contentEl = document.getElementById("modal-content");

  const phil = d.philosopher || {};

  titleEl.textContent = d.Name;

  const birth = escapeHtml(phil["BirthYear"]);
  const death = escapeHtml(phil["DeathYear"]);

  contentEl.innerHTML = `
    <p class="modal-dates">${birth} – ${death}</p>
    ${renderModalDimensionRows(d.ID)}
    <h3>Core Teachings</h3>
    <p>${escapeHtml(phil["CoreTeachings"])}</p>
    <h3>Historical Context</h3>
    <p>${escapeHtml(phil["HistoricalContext"])}</p>
    <h3>Key Works</h3>
    <p>${escapeHtml(phil["KeyWorks"])}</p>
  `;

  focusNodeForModal(d);
  overlay.style.display = "flex";
}

// DOM Elements e.g. Modal close handlers and initial load
document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("modal-overlay");
  const closeBtn = document.getElementById("modal-close");
  const mapSelect = document.getElementById("map-select");
  const colorSelect = document.getElementById("color-select");

  const searchInput = document.getElementById("search-input");
  const suggestionsBox = document.getElementById("search-suggestions");
  const themeButton = document.getElementById("theme-button");

  const aboutButton = document.getElementById("about-button");
  const aboutOverlay = document.getElementById("about-overlay");
  const aboutClose = document.getElementById("about-close");

  if (aboutButton && aboutOverlay && aboutClose) {
    aboutButton.addEventListener("click", () => {
      aboutOverlay.style.display = "flex";
    });

    aboutClose.addEventListener("click", () => {
      aboutOverlay.style.display = "none";
    });

    aboutOverlay.addEventListener("click", (e) => {
      if (e.target.id === "about-overlay") {
        aboutOverlay.style.display = "none";
      }
    });
  }
  
  // Results currently shown in the dropdown, and which one the arrow keys have
  // landed on (-1 means the input itself, before any result).
  let activeResults = [];
  let activeIndex = -1;

  // Snippets are built from data, so they go in as text nodes with a <mark>
  // element around the match rather than as an HTML string.
  function appendSnippet(container, snippet) {
    const el = document.createElement("div");
    el.className = "suggestion-snippet";
    const { text, matchStart, matchLength } = snippet;

    el.appendChild(document.createTextNode(text.slice(0, matchStart)));
    const mark = document.createElement("mark");
    mark.textContent = text.slice(matchStart, matchStart + matchLength);
    el.appendChild(mark);
    el.appendChild(document.createTextNode(text.slice(matchStart + matchLength)));

    container.appendChild(el);
  }

  function highlightActive() {
    const items = suggestionsBox.querySelectorAll(".suggestion");
    items.forEach((item, i) => item.classList.toggle("is-active", i === activeIndex));
    if (activeIndex >= 0 && items[activeIndex]) {
      items[activeIndex].scrollIntoView({ block: "nearest" });
    }
  }

  function chooseResult(result) {
    if (!result) return;
    searchInput.value = result.label;
    suggestionsBox.style.display = "none";
    activeIndex = -1;
    applySearchResult(result);
  }

  function renderSuggestions(query) {
    if (!suggestionsBox) return;

    activeResults = query.trim() ? runSearch(searchIndex, query) : [];
    activeIndex = -1;
    suggestionsBox.innerHTML = "";

    if (!query.trim()) {
      suggestionsBox.style.display = "none";
      return;
    }

    suggestionsBox.style.display = "block";

    if (activeResults.length === 0) {
      const empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = `Nothing matches “${query.trim()}”`;
      suggestionsBox.appendChild(empty);
      return;
    }

    activeResults.forEach((result, i) => {
      const item = document.createElement("div");
      item.className = "suggestion";

      const line = document.createElement("div");
      line.className = "suggestion-line";

      const label = document.createElement("span");
      label.className = "suggestion-label";
      label.textContent = result.label;
      line.appendChild(label);

      const detail = document.createElement("span");
      detail.className = "suggestion-detail";
      detail.textContent = result.detail;
      line.appendChild(detail);

      item.appendChild(line);
      if (result.snippet) appendSnippet(item, result.snippet);

      item.addEventListener("mouseenter", () => {
        activeIndex = i;
        highlightActive();
      });
      // mousedown fires before the input's blur handler hides the dropdown.
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();
        chooseResult(result);
      });

      suggestionsBox.appendChild(item);
    });
  }

  function handleSearch() {
    // With nothing highlighted, Enter takes the top result, which is the
    // ranking's job to have gotten right.
    const result = activeResults[activeIndex >= 0 ? activeIndex : 0];
    if (result) {
      chooseResult(result);
    } else {
      suggestionsBox.style.display = "none";
    }
  }

  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      const isOpen = suggestionsBox && suggestionsBox.style.display === "block";

      if (e.key === "ArrowDown" && isOpen && activeResults.length) {
        e.preventDefault();
        activeIndex = (activeIndex + 1) % activeResults.length;
        highlightActive();
        return;
      }
      if (e.key === "ArrowUp" && isOpen && activeResults.length) {
        e.preventDefault();
        activeIndex = activeIndex <= 0 ? activeResults.length - 1 : activeIndex - 1;
        highlightActive();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        handleSearch();
        return;
      }
      if (e.key === "Escape" && suggestionsBox) {
        suggestionsBox.style.display = "none";
        activeIndex = -1;
      }
    });

    searchInput.addEventListener("input", () => {
      renderSuggestions(searchInput.value);
      // Emptying the box is the natural way to ask for the whole map back.
      if (!searchInput.value.trim()) clearSearchSpotlight();
    });

    searchInput.addEventListener("blur", () => {
      // Small delay so a click on a suggestion still registers.
      setTimeout(() => {
        if (suggestionsBox) suggestionsBox.style.display = "none";
      }, 200);
    });
  }

  const searchClear = document.getElementById("search-clear");
  if (searchClear) {
    searchClear.addEventListener("click", () => {
      searchInput.value = "";
      suggestionsBox.style.display = "none";
      clearSearchSpotlight();
      searchInput.focus();
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      overlay.style.display = "none";
    });
  }
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target.id === "modal-overlay") {
        overlay.style.display = "none";
      }
    });
  }

  // Populate the "Color by" dropdown from the dimension manifest, then do the
  // initial render once philosophers + dimension data are cached in memory.
  loadStaticData().then(() => {
    // Everything the index needs is already in memory, so this costs no
    // additional request.
    searchIndex = buildSearchIndex(
      Array.from(philosophersById.values()),
      dimensionsManifest,
      dimensionTables,
      dimensionLinksByPhilosopher
    );

    if (colorSelect) {
      colorSelect.innerHTML = "";
      dimensionsManifest.forEach(entry => {
        const option = document.createElement("option");
        option.value = entry.key;
        option.textContent = entry.label;
        colorSelect.appendChild(option);
      });
      if (dimensionsManifest.some(e => e.key === DEFAULT_COLOR_BY_KEY)) {
        colorSelect.value = DEFAULT_COLOR_BY_KEY;
      }
    }

    loadAndRender(currentMapValue(), colorSelect.value);
  }).catch(err => {
    console.error("Error loading dimensional data:", err);
  });

  // Map view is a segmented toggle rather than a <select>, since there are only
  // two options and the choice is the primary thing to communicate.
  function currentMapValue() {
    const active = mapSelect.querySelector(".seg-btn.is-active");
    return active ? active.dataset.value : "data/coords_semantic_tsne.csv";
  }

  mapSelect.addEventListener("click", (e) => {
    const button = e.target.closest(".seg-btn");
    if (!button || button.classList.contains("is-active")) return;
    mapSelect.querySelectorAll(".seg-btn").forEach(b => b.classList.toggle("is-active", b === button));
    loadAndRender(currentMapValue(), colorSelect.value);
  });

  if (themeButton) {
    themeButton.addEventListener("click", () => {
      setTheme(isDarkTheme() ? "light" : "dark");
    });
  }

  // Escape closes whichever layer is open, innermost first, and finally
  // releases a search spotlight.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (aboutOverlay && aboutOverlay.style.display === "flex") {
      aboutOverlay.style.display = "none";
    } else if (overlay && overlay.style.display === "flex") {
      overlay.style.display = "none";
    } else if (searchMatchIDs) {
      searchInput.value = "";
      clearSearchSpotlight();
    }
  });

  // When color scheme changes
  colorSelect.addEventListener("change", () => {
    const colorBy = colorSelect.value;
    rebuildColorScale(colorBy);
    recolorExistingNodes();
  });
});
