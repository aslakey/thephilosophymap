// main.js

const width = window.innerWidth;
const height = window.innerHeight;
const NODE_RADIUS = 10;
const ZOOM_MIN = 0.2;
const ZOOM_MAX = 10;
const LABEL_ZOOM_THRESHOLD = 2.2;
const MODAL_DESIRED_SCALE = 3;
const LEGEND_MAX_MAIN_CATEGORIES = 10;

// Global references to current state
let currentNodes = [];
let svg, g, simulation;
let currentTransform = d3.zoomIdentity;  // track current zoom/pan
let zoomBehavior = null;

let selectedID = null;           // current selected philosopher
let globalColorByField = null;   // name of current color field
let globalColorScale = null;     // current D3 scale
let globalColorValueMapper = null;

function rebuildColorScale(colorByField) {
  globalColorByField = colorByField;

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
  const field = globalColorByField || "PrimaryTopics"; // or any default
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
    .text(`Color by: ${globalColorByField}`);

  const rows = legend.selectAll(".legend-row")
    .data(domain, d => d)
    .enter()
    .append("div")
    .attr("class", "legend-row");

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
  Promise.all([
    d3.csv(coordsPath),
    d3.csv("data/philosophers.csv"),
    d3.csv("data/details.csv")
  ]).then(([coords, philosophers, details]) => {
    const nameById = new Map(philosophers.map(d => [d.ID, d.Name]));
    const detailsById = new Map(details.map(d => [d.ID, d]));

    const nodes = coords.map(d => {
      const id = d.ID;
      const detail = detailsById.get(id) || {};
      const x0 = +d.x;
      const y0 = +d.y;
      return {
        ID: id,
        Name: nameById.get(id) || id,
        x: x0,
        y: y0,
        x0,
        y0,
        targetX: null,
        targetY: null,
        detail
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
  const raw = d.detail[field] || "Unknown";
  if (raw === "Unknown") return raw;

  // Special handling for PrimaryTopics: take just the first topic
  if (field === "PrimaryTopics") {
    const parts = raw.split(";")
      .map(s => s.trim())
      .filter(s => s.length > 0);
    return parts.length > 0 ? parts[0] : "Unknown";
  }

  // Default: use the raw field as-is
  return raw;
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

// Modal
function showModal(d) {
  const overlay = document.getElementById("modal-overlay");
  const titleEl = document.getElementById("modal-title");
  const contentEl = document.getElementById("modal-content");

  const det = d.detail || {};

  titleEl.textContent = d.Name;

  contentEl.innerHTML = `
    <p><strong>Era:</strong> ${det["Era"] || ""}</p>
    <p><strong>Civilization/Tradition:</strong> ${det["Civilization/Tradition"] || ""}</p>
    <p><strong>Region:</strong> ${det["Region"] || ""}</p>
    <p><strong>School/Movement:</strong> ${det["School/Movement"] || ""}</p>
    <p><strong>Primary Topics:</strong> ${det["PrimaryTopics"] || ""}</p>
    <p><strong>Birth – Death:</strong> ${det["BirthYear"] || ""} – ${det["DeathYear"] || ""}</p>
    <h3>Core Teachings</h3>
    <p>${det["CoreTeachings"] || ""}</p>
    <h3>Historical Context</h3>
    <p>${det["HistoricalContext"] || ""}</p>
    <h3>Key Works</h3>
    <p>${det["KeyWorks"] || ""}</p>
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

  // Initial render
  const initialMap = mapSelect.value;
  const initialColor = colorSelect.value;
  loadAndRender(initialMap, initialColor);

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
