// main.js

// Live viewport size. These follow the window rather than being captured once,
// so rotating a phone or resizing a window re-lays out the map instead of
// leaving it in a box the wrong shape.
let width = window.innerWidth;
let height = window.innerHeight;

const NODE_RADIUS = 10;
// The touch target around each node; roughly a fingertip, and well above the
// 22px gap between the closest pair of points at default zoom.
const NODE_HIT_RADIUS = 22;
const ZOOM_MIN = 0.2;
const ZOOM_MAX = 10;
const LABEL_ZOOM_THRESHOLD = 2.2;
// Phones start further from the map and can't hover for a tooltip, so labels
// have to appear sooner or the map reads as anonymous dots.
const LABEL_ZOOM_THRESHOLD_SMALL = 1.3;
const MODAL_DESIRED_SCALE = 3;
// These two must stay in step with the stylesheet's media queries, which is
// why they are written once here and used for every layout decision.
// Compact chrome covers narrow screens and short ones (a phone in landscape).
const SMALL_SCREEN_QUERY = "(max-width: 640px), (max-height: 480px)";
// The detail panel is a bottom sheet only where there is height for one.
const DETAIL_SHEET_QUERY = "(max-width: 900px) and (min-height: 481px)";
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

// Phone layout is driven by the same breakpoint the stylesheet uses, so the
// two can't disagree about when the sheet is in play.
function isSmallScreen() {
  return window.matchMedia(SMALL_SCREEN_QUERY).matches;
}

function detailPanelIsBottomSheet() {
  return window.matchMedia(DETAIL_SHEET_QUERY).matches;
}

function labelZoomThreshold() {
  return isSmallScreen() ? LABEL_ZOOM_THRESHOLD_SMALL : LABEL_ZOOM_THRESHOLD;
}

// Space the map layout keeps clear at the top for the control bar, which is
// full-width on phones and would otherwise sit on top of the points.
function topInset() {
  return isSmallScreen() ? 96 : 50;
}

function edgeInset() {
  return isSmallScreen() ? 28 : 50;
}

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

  // Spotlighting is a hover effect, so on touch it simply isn't available and
  // advertising it would be a lie.
  legend.append("div")
    .attr("class", "legend-hint")
    .text(window.matchMedia("(hover: hover)").matches
      ? "Hover to spotlight, click to filter"
      : "Tap a category to filter");

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

  d3.selectAll(".node circle.dot")
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

// Labels appear in bulk once zoomed in, but the selected node and any search
// matches stay labelled at every zoom level: those are exactly the points the
// reader has just asked to identify, and on a phone there is no hover tooltip
// to fall back on.
function updateLabelVisibility(zoomScale = 1) {
  const showLabels = zoomScale >= labelZoomThreshold();
  d3.selectAll(".node-label")
    .style("opacity", d => {
      if (showLabels) return 1;
      if (d.ID === selectedID) return 1;
      if (searchMatchIDs && searchMatchIDs.has(d.ID)) return 1;
      return 0;
    });
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
      updateHitRadius();
    });

  svg.call(zoomBehavior);
}

// The hit circles live inside the zoomed layer, so their radius is divided by
// the zoom scale to keep them a constant size on screen. Without this they
// would shrink as the reader zooms out -- precisely when the dots are smallest
// and a tap is least precise.
function updateHitRadius() {
  if (!g) return;
  g.selectAll(".node-hit").attr("r", NODE_HIT_RADIUS / (currentTransform.k || 1));
}

// The projection from source coordinates into the current viewport. Kept on
// hand so a resize can both re-run it and translate the reader's position
// through it.
let layoutXScale = null;
let layoutYScale = null;

// Project the source coordinates into the current viewport. Kept separate from
// createViz so a resize can re-run it without rebuilding every node.
function applyLayoutTargets(nodes) {
  if (!nodes.length) return;

  const edge = edgeInset();
  layoutXScale = d3.scaleLinear()
    .domain(d3.extent(nodes, d => d.x0))
    .range([edge, width - edge]);

  layoutYScale = d3.scaleLinear()
    .domain(d3.extent(nodes, d => d.y0))
    .range([topInset(), height - edge]);

  nodes.forEach(d => {
    d.targetX = layoutXScale(d.x0);
    d.targetY = layoutYScale(d.y0);
  });
}

// Rotating a phone fires resize repeatedly, so the work is coalesced into the
// next frame.
//
// A resize re-projects the whole layout, which would leave a zoomed-in reader
// staring at empty space: their pan was computed against the old projection.
// So the point at the centre of the screen is converted back into source
// coordinates first, and the view is re-centred on that same point afterwards.
// Zoom level is preserved throughout.
let resizeFrame = null;

function handleViewportResize() {
  if (resizeFrame) cancelAnimationFrame(resizeFrame);

  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null;

    let anchor = null;
    if (layoutXScale && layoutYScale && currentNodes.length) {
      const [centreX, centreY] = currentTransform.invert([width / 2, height / 2]);
      anchor = {
        x0: layoutXScale.invert(centreX),
        y0: layoutYScale.invert(centreY)
      };
    }

    width = window.innerWidth;
    height = window.innerHeight;

    if (!svg) return;
    svg.attr("width", width).attr("height", height);

    if (!currentNodes.length) return;
    applyLayoutTargets(currentNodes);
    if (simulation) simulation.alpha(0.35).restart();

    if (anchor && zoomBehavior) {
      const k = currentTransform.k || 1;
      svg.call(
        zoomBehavior.transform,
        d3.zoomIdentity
          .translate(width / 2 - k * layoutXScale(anchor.x0), height / 2 - k * layoutYScale(anchor.y0))
          .scale(k)
      );
    }

    updateLabelVisibility(currentTransform.k);
    updateHitRadius();
  });
}

window.addEventListener("resize", handleViewportResize);
window.addEventListener("orientationchange", handleViewportResize);

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

  // The node has to end up in whatever strip of map the detail panel leaves:
  // above it when it's a bottom sheet, beside it when it's a side panel.
  const sheet = detailPanelIsBottomSheet();
  const targetScreenX = sheet
    ? width / 2
    : Math.max(140, Math.min(width * 0.33, width - 140));
  const targetScreenY = sheet
    ? Math.max(topInset() + NODE_RADIUS * 3, height * 0.22)
    : height / 2;

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

  // 1) RANDOM INITIAL POSITIONS (for animation)
  nodes.forEach(d => {
    d.x = width * (0.2 + 0.6 * Math.random());   // random in central band
    d.y = height * (0.2 + 0.6 * Math.random());
  });
  // 2) SET TARGETS to the projected map layout (but don't overwrite x,y)
  applyLayoutTargets(nodes);

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

  // Sits under the visible dot and only takes pointer events on touch (see
  // .node-hit in the stylesheet), so tapping is forgiving without making
  // neighbouring points harder to click with a mouse.
  node.append("circle")
    .attr("class", "node-hit")
    .attr("r", NODE_HIT_RADIUS / (currentTransform.k || 1));

  node.append("circle")
    .attr("class", "dot")
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
  d3.selectAll(".node circle.dot")
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

  // -------- View sheet (phones) --------
  //
  // A phone screen can't spare the 153px the desktop control bar takes, so at
  // the narrow breakpoint everything except search moves into a bottom sheet.
  // The controls are moved, not cloned: one map toggle, one colour select and
  // one legend exist at any time, so their handlers and state survive the trip
  // and there is no second copy to keep in sync.
  const sheetOverlay = document.getElementById("sheet-overlay");
  const sheetClose = document.getElementById("sheet-close");
  const viewButton = document.getElementById("view-button");
  const controlRow = document.getElementById("control-row");
  const searchContainer = document.getElementById("search-container");
  const legendEl = document.getElementById("legend");
  const colorLabel = colorSelect ? colorSelect.closest(".control-label") : null;
  const smallScreen = window.matchMedia(SMALL_SCREEN_QUERY);

  function openSheet() {
    if (!sheetOverlay) return;
    sheetOverlay.classList.add("is-open");
    sheetOverlay.setAttribute("aria-hidden", "false");
    if (viewButton) viewButton.setAttribute("aria-expanded", "true");
  }

  function closeSheet() {
    if (!sheetOverlay) return;
    sheetOverlay.classList.remove("is-open");
    sheetOverlay.setAttribute("aria-hidden", "true");
    if (viewButton) viewButton.setAttribute("aria-expanded", "false");
  }

  function sheetIsOpen() {
    return !!sheetOverlay && sheetOverlay.classList.contains("is-open");
  }

  function placeControls() {
    if (smallScreen.matches) {
      document.getElementById("sheet-map").appendChild(mapSelect);
      if (colorLabel) document.getElementById("sheet-color").appendChild(colorLabel);
      if (legendEl) document.getElementById("sheet-legend").appendChild(legendEl);

      const actions = document.getElementById("sheet-actions");
      if (themeButton) actions.appendChild(themeButton);
      if (aboutButton) actions.appendChild(aboutButton);
      return;
    }

    // Back to the desktop bar in its original order.
    controlRow.insertBefore(mapSelect, controlRow.firstChild);
    if (colorLabel) controlRow.insertBefore(colorLabel, searchContainer);
    if (themeButton) controlRow.appendChild(themeButton);
    if (aboutButton) controlRow.appendChild(aboutButton);
    if (legendEl) document.body.appendChild(legendEl);
    closeSheet();
  }

  placeControls();
  smallScreen.addEventListener("change", placeControls);

  if (viewButton) {
    viewButton.addEventListener("click", () => {
      if (sheetIsOpen()) closeSheet();
      else openSheet();
    });
  }
  if (sheetClose) sheetClose.addEventListener("click", closeSheet);
  if (sheetOverlay) {
    sheetOverlay.addEventListener("click", (e) => {
      if (e.target.id === "sheet-overlay") closeSheet();
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
    if (sheetIsOpen()) {
      closeSheet();
    } else if (aboutOverlay && aboutOverlay.style.display === "flex") {
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
