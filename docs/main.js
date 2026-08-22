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
// them without an extra "Other" bucket.
// d3.schemeTableau10 + d3.schemeSet3 provides 22 distinct colors.
const LEGEND_MAX_MAIN_CATEGORIES = 20;
const DEFAULT_COLOR_BY_KEY = "era";

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

  const mappedDomain = [];
  knownValues.slice(0, LEGEND_MAX_MAIN_CATEGORIES).forEach(v => mappedDomain.push(v));
  if (hasLongTail) mappedDomain.push("Other");
  if (counts.has("Unknown")) mappedDomain.push("Unknown");

  globalColorScale = d3.scaleOrdinal()
    .domain(mappedDomain)
    .range(d3.schemeTableau10.concat(d3.schemeSet3));

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

  const domain = globalColorScale.domain();
  legend.html("");

  legend.append("div")
    .attr("class", "legend-title")
    .text(`Color by: ${labelForDimensionKey(globalColorByField)}`);

  const rows = legend.selectAll(".legend-row")
    .data(domain, d => d)
    .enter()
    .append("div")
    .attr("class", "legend-row")
    .attr("title", d => globalColorDescByName.get(d) || "");

  rows.append("span")
    .attr("class", "legend-swatch")
    .style("background", d => globalColorScale(d));

  rows.append("span")
    .attr("class", "legend-label")
    .text(d => `${d} (${groupedCounts.get(d) || 0})`);
}

function recolorExistingNodes() {
  if (!globalColorScale || !globalColorByField) return;

  d3.selectAll(".node circle")
    .attr("fill", d => {
      return globalColorScale(colorCategoryForNode(d));
    });

  // Re-apply stroke logic so selected node stays highlighted.
  updateSelectionHighlight();
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

function findNodeByQuery(query) {
  if (!query) return null;
  const q = query.toLowerCase().trim();
  // Try exact ID match first
  let node = currentNodes.find(d => d.ID.toLowerCase() === q);
  if (node) return node;
  // Then name contains query
  node = currentNodes.find(d => (d.Name || "").toLowerCase().includes(q));
  return node || null;
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
    return globalColorScale(colorCategoryForNode(d));
  }

  // Node group
  const node = g.selectAll(".node")
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
    .attr("stroke", d => getColor(d))
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
    .text(d => shortName(d.Name));

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
}

// -------- Helpers --------

function shortName(name) {
  if (!name) return "";
  const parts = name.split(/\s+/);
  if (parts.length === 1) return name;
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
  d3.selectAll(".node circle")
    .attr("stroke-width", d => d.ID === selectedID ? 3 : 1.5)
    .attr("stroke", function(d) {
      if (d.ID === selectedID) {
        return "#4a6cf7";  // highlight color (match your Go button)
      }
      if (globalColorScale && globalColorByField) {
        return globalColorScale(colorCategoryForNode(d));
      }
      return d3.select(this).attr("stroke");
    });
}

function renderModalDimensionRows(philosopherId) {
  return dimensionsManifest.map(entry => {
    const values = allValues(philosopherId, entry.key);
    const valueHtml = values.length
      ? values.map(v => `<span title="${escapeHtml(v.Description)}">${escapeHtml(v.Name)}</span>`).join(", ")
      : "—";
    return `<p><strong>${escapeHtml(entry.label)}:</strong> ${valueHtml}</p>`;
  }).join("\n");
}

// Modal
function showModal(d) {
  const overlay = document.getElementById("modal-overlay");
  const titleEl = document.getElementById("modal-title");
  const contentEl = document.getElementById("modal-content");

  const phil = d.philosopher || {};

  titleEl.textContent = d.Name;

  contentEl.innerHTML = `
    ${renderModalDimensionRows(d.ID)}
    <p><strong>Birth – Death:</strong> ${escapeHtml(phil["BirthYear"])} – ${escapeHtml(phil["DeathYear"])}</p>
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
  const searchButton = document.getElementById("search-button");
  const suggestionsBox = document.getElementById("search-suggestions");

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
  
  function getSearchSuggestions(query, maxResults = 8) {
    if (!query) return [];
    const q = query.toLowerCase().trim();
    if (!q) return [];
  
    // Simple strategy: filter by name containing the query
    const matches = currentNodes.filter(d =>
      (d.Name || "").toLowerCase().includes(q) ||
      d.ID.toLowerCase().includes(q)
    );
  
    // Sort by: starts-with first, then contains
    matches.sort((a, b) => {
      const aName = (a.Name || "").toLowerCase();
      const bName = (b.Name || "").toLowerCase();
      const aStarts = aName.startsWith(q);
      const bStarts = bName.startsWith(q);
      if (aStarts && !bStarts) return -1;
      if (!aStarts && bStarts) return 1;
      return aName.localeCompare(bName);
    });
  
    return matches.slice(0, maxResults);
  }
  
  function renderSuggestions(query) {
    if (!suggestionsBox) return;
  
    const suggestions = getSearchSuggestions(query);
  
    if (!query || suggestions.length === 0) {
      suggestionsBox.style.display = "none";
      suggestionsBox.innerHTML = "";
      return;
    }
  
    suggestionsBox.innerHTML = "";
    suggestionsBox.style.display = "block";
  
    suggestions.forEach(d => {
      const item = document.createElement("div");
      item.textContent = `${d.Name}`;
      item.style.padding = "4px 8px";
      item.style.cursor = "pointer";
      item.addEventListener("mouseenter", () => {
        item.style.backgroundColor = "#eef2ff";
      });
      item.addEventListener("mouseleave", () => {
        item.style.backgroundColor = "white";
      });
      item.addEventListener("click", () => {
        // When a suggestion is clicked:
        searchInput.value = d.Name;
        suggestionsBox.style.display = "none";
        selectNode(d);
        zoomToNode(d);
        // Optional: open modal
        // showModal(d);
      });
      suggestionsBox.appendChild(item);
    });
  }

  function handleSearch() {
    const query = searchInput.value;
    const node = findNodeByQuery(query);
    suggestionsBox.style.display = "none";
    if (node) {
      selectNode(node);
      zoomToNode(node);
    } else {
      console.log("No philosopher found for query:", query);
    }
  }
  
  if (searchButton) {
    searchButton.addEventListener("click", handleSearch);
  }
  
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") handleSearch();
      if (e.key === "Escape" && suggestionsBox) {
        suggestionsBox.style.display = "none";
      }
    });
  
    searchInput.addEventListener("input", () => {
      const query = searchInput.value;
      renderSuggestions(query);
    });
  
    // Optional: hide suggestions when input loses focus
    searchInput.addEventListener("blur", () => {
      // small delay so a click on a suggestion still registers
      setTimeout(() => {
        if (suggestionsBox) suggestionsBox.style.display = "none";
      }, 200);
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

    const initialMap = mapSelect.value;
    const initialColor = colorSelect.value;
    loadAndRender(initialMap, initialColor);
  }).catch(err => {
    console.error("Error loading dimensional data:", err);
  });

  // When map changes
  mapSelect.addEventListener("change", () => {
    const coordsPath = mapSelect.value;
    const colorBy = colorSelect.value;
    loadAndRender(coordsPath, colorBy);
  });

  // When color scheme changes
  colorSelect.addEventListener("change", () => {
    const colorBy = colorSelect.value;
    rebuildColorScale(colorBy);
    recolorExistingNodes();
  });
});
