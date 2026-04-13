/**
 * CincyListings — frontend app
 *
 * Loads data/listings.json (relative path), applies filters/sort,
 * renders listing cards and a Leaflet map.
 *
 * Zero dependencies beyond Leaflet (loaded via CDN in index.html).
 */

"use strict";

// ── Config ────────────────────────────────────────────
const DATA_URL = "data/listings.json";
const PAGE_SIZE = 24;

// ── State ─────────────────────────────────────────────
const state = {
  all: [],          // all listings from JSON
  filtered: [],     // after applying filters
  page: 1,          // current pagination page
  filters: {
    priceMin: "",
    priceMax: "",
    beds: "",
    baths: "",
    type: "",
    zip: "",
    source: "",
    aiScore: "",
    aiModernity: "",
    aiLuxury: "",
    aiCondition: "",
    area: "",
    sort: "price_asc",
  },
};

// ── Leaflet map instance
let map = null;
let markers = [];

// ── Helpers ───────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function fmt_price(n) {
  if (n == null) return "Price N/A";
  return "$" + Number(n).toLocaleString();
}

function fmt_num(n, unit = "") {
  if (n == null || n === "" || n === 0) return null;
  return Number(n).toLocaleString() + (unit ? " " + unit : "");
}

function source_label(src) {
  const map = {
    zillow: "Zillow",
    redfin: "Redfin",
    sibcy_cline: "Sibcy Cline",
    huff: "Huff",
    comey: "Comey",
    listings_cincinnati: "CincyMLS",
    cincinky: "CincinKY",
    coldwell_banker: "Coldwell Banker",
    cabr: "CABR",
  };
  return map[src] || src;
}

function normalize_type(raw) {
  const r = (raw || "").toUpperCase().replace(/[\s-]/g, "_");
  if (r.includes("SINGLE") || r.includes("HOUSE") || r.includes("RESIDENTIAL")) return "SINGLE_FAMILY";
  if (r.includes("CONDO")) return "CONDO";
  if (r.includes("TOWN")) return "TOWNHOUSE";
  if (r.includes("MULTI") || r.includes("DUPLEX") || r.includes("TRIPLEX")) return "MULTI_FAMILY";
  return r;
}

// ── Data loading ──────────────────────────────────────
async function load_data() {
  const grid = $("listings-grid");
  grid.innerHTML = `<div class="spinner-wrap"><div class="spinner"></div></div>`;

  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.all = data.listings || [];

    const meta = $("header-meta");
    const updated = data.last_updated
      ? new Date(data.last_updated).toLocaleDateString("en-US", {
          month: "short", day: "numeric", year: "numeric",
        })
      : "unknown";
    meta.textContent = `${state.all.length.toLocaleString()} listings · updated ${updated}`;

    apply_filters();
  } catch (err) {
    console.error("Failed to load listings:", err);
    grid.innerHTML = `
      <div class="empty-state">
        <h3>Couldn't load listings</h3>
        <p>Run <code>python run_scrapers.py</code> to fetch listings,
        or check that <code>data/listings.json</code> exists.</p>
        <p style="margin-top:8px;font-size:12px;color:#9ca3af">${err.message}</p>
      </div>`;
    $("header-meta").textContent = "No data loaded";
  }
}

// ── Helpers ───────────────────────────────────────────
function avg_room_score(listing, field) {
  const rooms = listing.image_analysis?.rooms;
  if (!rooms?.length) return 0;
  const vals = rooms.map((r) => r[field] ?? 0).filter((v) => v > 0);
  if (!vals.length) return 0;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// ── Filtering & sorting ───────────────────────────────
function apply_filters() {
  const f = state.filters;
  let list = state.all;

  if (f.priceMin) list = list.filter((l) => l.price != null && l.price >= +f.priceMin);
  if (f.priceMax) list = list.filter((l) => l.price != null && l.price <= +f.priceMax);
  if (f.beds)     list = list.filter((l) => l.beds != null && l.beds >= +f.beds);
  if (f.baths)    list = list.filter((l) => l.baths != null && l.baths >= +f.baths);
  if (f.zip)      list = list.filter((l) => (l.zip || "").startsWith(f.zip));
  if (f.source)   list = list.filter((l) => l.source === f.source);
  if (f.area === "OH") list = list.filter((l) => (l.state || "").toUpperCase() === "OH");
  if (f.area === "KY") list = list.filter((l) => (l.state || "").toUpperCase() === "KY");
  if (f.aiScore)     list = list.filter((l) => (l.image_analysis?.overall_score ?? 0) >= +f.aiScore);
  if (f.aiModernity) list = list.filter((l) => avg_room_score(l, "modernity_score") >= +f.aiModernity);
  if (f.aiLuxury)    list = list.filter((l) => avg_room_score(l, "luxury_score")    >= +f.aiLuxury);
  if (f.aiCondition) list = list.filter((l) => avg_room_score(l, "condition_score") >= +f.aiCondition);
  if (f.type) {
    list = list.filter((l) => normalize_type(l.property_type) === f.type);
  }

  // Sort
  list = [...list];
  switch (f.sort) {
    case "price_asc":
      list.sort((a, b) => (a.price ?? Infinity) - (b.price ?? Infinity));
      break;
    case "price_desc":
      list.sort((a, b) => (b.price ?? -Infinity) - (a.price ?? -Infinity));
      break;
    case "beds_desc":
      list.sort((a, b) => (b.beds ?? 0) - (a.beds ?? 0));
      break;
    case "sqft_desc":
      list.sort((a, b) => (b.sqft ?? 0) - (a.sqft ?? 0));
      break;
    case "dom_asc":
      list.sort((a, b) => (a.days_on_market ?? 999) - (b.days_on_market ?? 999));
      break;
    case "ai_score_desc":
      list.sort((a, b) => (b.image_analysis?.overall_score ?? 0) - (a.image_analysis?.overall_score ?? 0));
      break;
  }

  state.filtered = list;
  state.page = 1;
  $("result-count").textContent = `${list.length.toLocaleString()} listing${list.length !== 1 ? "s" : ""}`;
  render_list();
  if (map) render_map_markers();
}

// ── Rendering: List ───────────────────────────────────
function render_list() {
  const grid = $("listings-grid");
  const wrap = $("load-more-wrap");
  const page_listings = state.filtered.slice(0, state.page * PAGE_SIZE);

  if (state.filtered.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <h3>No listings match your filters</h3>
        <p>Try broadening your search or clearing some filters.</p>
      </div>`;
    wrap.style.display = "none";
    return;
  }

  grid.innerHTML = page_listings.map(card_html).join("");

  // Attach click handlers
  grid.querySelectorAll(".listing-card").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = +el.dataset.idx;
      open_modal(state.filtered[idx]);
    });
  });

  wrap.style.display = page_listings.length < state.filtered.length ? "block" : "none";
}

function card_html(listing, idx) {
  const img_html = listing.images?.length
    ? `<img src="${listing.images[0]}" alt="Property photo" loading="lazy" onerror="this.parentNode.innerHTML='<div class=no-photo>🏠</div>'">`
    : `<div class="no-photo">🏠</div>`;

  const beds  = fmt_num(listing.beds);
  const baths = fmt_num(listing.baths);
  const sqft  = fmt_num(listing.sqft, "sqft");

  const stats = [
    beds  ? `<span>🛏 ${beds} bd</span>` : "",
    baths ? `<span>🛁 ${baths} ba</span>` : "",
    sqft  ? `<span>📐 ${sqft}</span>` : "",
  ].filter(Boolean).join("");

  const dom = listing.days_on_market != null
    ? `${listing.days_on_market}d on market`
    : listing.property_type || "";

  return `
    <div class="listing-card" data-idx="${idx}">
      <div class="card-image">
        ${img_html}
        <span class="source-badge source-${listing.source}">${source_label(listing.source)}</span>
      </div>
      <div class="card-body">
        <div class="card-price">${fmt_price(listing.price)}</div>
        <div class="card-address">${listing.address}${listing.city ? ", " + listing.city : ""}${listing.zip ? " " + listing.zip : ""}</div>
        <div class="card-stats">${stats || '<span style="color:#9ca3af">Details unavailable</span>'}</div>
      </div>
      <div class="card-footer">
        <span>${dom}</span>
        ${listing.url ? `<a href="${listing.url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">View →</a>` : ""}
      </div>
    </div>`;
}

// ── Rendering: Map ────────────────────────────────────
function init_map() {
  if (map) return;
  map = L.map("map").setView([39.103, -84.512], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);
  render_map_markers();
}

function render_map_markers() {
  // Clear existing
  markers.forEach((m) => map.removeLayer(m));
  markers = [];

  const with_coords = state.filtered.filter((l) => l.lat && l.lng);
  const shown = with_coords.slice(0, 1000); // cap to avoid browser freeze

  shown.forEach((listing) => {
    const color = source_color(listing.source);
    const icon = L.divIcon({
      className: "",
      html: `<div style="
        background:${color};color:#fff;
        padding:2px 6px;border-radius:12px;
        font-size:11px;font-weight:700;
        white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.3);
        border:2px solid #fff;
      ">${fmt_price_short(listing.price)}</div>`,
      iconAnchor: [0, 0],
    });

    const marker = L.marker([listing.lat, listing.lng], { icon })
      .addTo(map)
      .bindPopup(popup_html(listing), { maxWidth: 260 });
    markers.push(marker);
  });
}

function fmt_price_short(n) {
  if (n == null) return "?";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `$${Math.round(n / 1_000)}k`;
  return `$${n}`;
}

function source_color(src) {
  const map = {
    zillow: "#006aff",
    redfin: "#cc0000",
    sibcy_cline: "#5b21b6",
    huff: "#b45309",
    comey: "#0f766e",
    listings_cincinnati: "#be185d",
    cincinky: "#7c3aed",
    coldwell_banker: "#1a56db",
    cabr: "#374151",
  };
  return map[src] || "#374151";
}

function popup_html(l) {
  const img = l.images?.[0]
    ? `<img src="${l.images[0]}" style="width:100%;height:100px;object-fit:cover;border-radius:6px;margin-bottom:8px" loading="lazy">`
    : "";
  return `
    <div style="min-width:200px">
      ${img}
      <strong style="font-size:15px">${fmt_price(l.price)}</strong><br>
      <span style="font-size:12px;color:#6b7280">${l.address || ""}</span><br>
      <span style="font-size:12px">${[fmt_num(l.beds, "bd"), fmt_num(l.baths, "ba"), fmt_num(l.sqft, "sqft")].filter(Boolean).join(" · ")}</span><br>
      ${l.url ? `<a href="${l.url}" target="_blank" rel="noopener" style="font-size:12px;color:#1d4ed8">View on ${source_label(l.source)} →</a>` : ""}
    </div>`;
}

// ── AI Analysis panel ─────────────────────────────────
function score_bar(score, max = 10) {
  const pct = Math.round((score / max) * 100);
  const color = score >= 8 ? "#16a34a" : score >= 6 ? "#d97706" : "#dc2626";
  return `<div style="display:flex;align-items:center;gap:8px">
    <div style="flex:1;height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden">
      <div style="width:${pct}%;height:100%;background:${color};border-radius:3px"></div>
    </div>
    <span style="font-size:12px;font-weight:700;color:${color};min-width:24px">${score}</span>
  </div>`;
}

function room_type_label(rt) {
  const map = {
    kitchen: "Kitchen", living_room: "Living Room", master_bedroom: "Master Bedroom",
    bedroom: "Bedroom", bathroom: "Bathroom", master_bathroom: "Master Bathroom",
    dining_room: "Dining Room", backyard: "Backyard / Outdoor", garage: "Garage",
    basement: "Basement", exterior: "Exterior", other: "Other",
  };
  return map[rt] || rt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function analysis_html(analysis) {
  const score = analysis.overall_score ?? 0;
  const score_color = score >= 8 ? "#16a34a" : score >= 6 ? "#d97706" : "#dc2626";

  const rooms_html = (analysis.rooms || []).map((room) => `
    <div class="ai-room-card">
      ${room.image_url
        ? `<img src="${room.image_url}" alt="${room_type_label(room.room_type)}"
             style="width:100%;height:120px;object-fit:cover;border-radius:8px;margin-bottom:10px"
             loading="lazy" onerror="this.style.display='none'">`
        : ""}
      <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;
                  color:#6b7280;margin-bottom:6px">${room_type_label(room.room_type)}</div>
      <div style="display:grid;grid-template-columns:80px 1fr;gap:4px 8px;font-size:12px;margin-bottom:8px">
        <span style="color:#6b7280">Modernity</span>${score_bar(room.modernity_score)}
        <span style="color:#6b7280">Luxury</span>${score_bar(room.luxury_score)}
        <span style="color:#6b7280">Condition</span>${score_bar(room.condition_score)}
      </div>
      ${room.features?.length
        ? `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px">
             ${room.features.map((f) =>
               `<span style="font-size:11px;background:#f3f4f6;color:#374151;
                             padding:2px 8px;border-radius:12px">${f}</span>`
             ).join("")}
           </div>`
        : ""}
      ${room.insight
        ? `<div style="font-size:12px;color:#4b5563;line-height:1.5;font-style:italic">"${room.insight}"</div>`
        : ""}
    </div>`).join("");

  return `
    <div class="ai-analysis-section">
      <div class="ai-analysis-header">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:18px">✨</span>
          <div>
            <div style="font-weight:700;font-size:15px">Cincinnatus AI</div>
          </div>
        </div>
        <div style="text-align:right">
          <div style="font-size:28px;font-weight:800;color:${score_color}">${score.toFixed(1)}</div>
          <div style="font-size:11px;color:#6b7280">Overall Score</div>
        </div>
      </div>
      ${analysis.summary
        ? `<div style="font-size:13px;color:#374151;line-height:1.6;padding:12px;
                       background:#f9fafb;border-radius:8px;margin-bottom:14px">
             ${analysis.summary}
           </div>`
        : ""}
      <div class="ai-rooms-grid">${rooms_html}</div>
    </div>`;
}

// ── Modal ─────────────────────────────────────────────
function open_modal(listing) {
  const content = $("modal-content");

  const img_section = listing.images?.length
    ? `<img class="modal-img" src="${listing.images[0]}" alt="Property" onerror="this.outerHTML='<div class=modal-no-img>🏠</div>'">`
    : `<div class="modal-no-img">🏠</div>`;

  const stats = [
    { val: fmt_num(listing.beds) ?? "—",  lbl: "Beds" },
    { val: fmt_num(listing.baths) ?? "—", lbl: "Baths" },
    { val: fmt_num(listing.sqft) ?? "—",  lbl: "Sq Ft" },
  ];

  const extra = [
    listing.property_type && `<strong>Type:</strong> ${listing.property_type}`,
    listing.days_on_market != null && `<strong>Days on market:</strong> ${listing.days_on_market}`,
    listing.zip && `<strong>ZIP:</strong> ${listing.zip}`,
    `<strong>Source:</strong> <span class="source-badge source-${listing.source}" style="position:static;display:inline">${source_label(listing.source)}</span>`,
  ].filter(Boolean).join("  ·  ");

  const ai_section = listing.image_analysis
    ? analysis_html(listing.image_analysis)
    : "";

  content.innerHTML = `
    ${img_section}
    <div class="modal-body">
      <div class="modal-price">${fmt_price(listing.price)}</div>
      <div class="modal-address">
        ${listing.address || ""}${listing.city ? ", " + listing.city : ""}${listing.state ? ", " + listing.state : ""}${listing.zip ? " " + listing.zip : ""}
      </div>
      <div class="modal-stats">
        ${stats.map((s) => `
          <div class="modal-stat">
            <div class="modal-stat-val">${s.val}</div>
            <div class="modal-stat-lbl">${s.lbl}</div>
          </div>`).join("")}
      </div>
      ${extra ? `<div class="modal-desc" style="font-size:13px">${extra}</div>` : ""}
      <div class="modal-actions">
        ${listing.url
          ? `<a class="btn-primary" href="${listing.url}" target="_blank" rel="noopener">View on ${source_label(listing.source)} ↗</a>`
          : ""}
      </div>
      ${ai_section}
    </div>`;

  $("modal-overlay").style.display = "flex";
  document.body.style.overflow = "hidden";
}

function close_modal() {
  $("modal-overlay").style.display = "none";
  document.body.style.overflow = "";
}

// ── Event wiring ──────────────────────────────────────
function wire_events() {
  // Price selects
  $("filter-price-min").addEventListener("change", (e) => {
    state.filters.priceMin = e.target.value;
    apply_filters();
  });
  $("filter-price-max").addEventListener("change", (e) => {
    state.filters.priceMax = e.target.value;
    apply_filters();
  });

  // Chip groups
  function wire_chips(group_id, key) {
    const group = $(group_id);
    group.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      group.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.filters[key] = chip.dataset.val;
      apply_filters();
    });
  }
  wire_chips("filter-beds",     "beds");
  wire_chips("filter-baths",    "baths");
  wire_chips("filter-type",     "type");
  wire_chips("filter-source",   "source");
  wire_chips("filter-area",          "area");
  wire_chips("filter-ai-score",     "aiScore");
  wire_chips("filter-ai-modernity", "aiModernity");
  wire_chips("filter-ai-luxury",    "aiLuxury");
  wire_chips("filter-ai-condition", "aiCondition");

  // Zip
  $("filter-zip").addEventListener("input", (e) => {
    state.filters.zip = e.target.value.trim();
    apply_filters();
  });

  // Sort
  $("filter-sort").addEventListener("change", (e) => {
    state.filters.sort = e.target.value;
    apply_filters();
  });

  // Clear filters
  $("clear-filters").addEventListener("click", () => {
    state.filters = {
      priceMin: "", priceMax: "", beds: "", baths: "",
      type: "", zip: "", source: "", area: "", aiScore: "", aiModernity: "", aiLuxury: "", aiCondition: "", sort: "price_asc",
    };
    // Reset UI
    $("filter-price-min").value = "";
    $("filter-price-max").value = "";
    $("filter-zip").value = "";
    $("filter-sort").value = "price_asc";
    document.querySelectorAll(".chip-group .chip").forEach((c) => {
      c.classList.toggle("active", c.dataset.val === "");
    });
    apply_filters();
  });

  // Load more
  $("load-more").addEventListener("click", () => {
    state.page++;
    render_list();
  });

  // Tabs
  $("tab-list").addEventListener("click", () => {
    $("tab-list").classList.add("active");
    $("tab-map").classList.remove("active");
    $("view-list").style.display = "block";
    $("view-map").style.display = "none";
  });
  $("tab-map").addEventListener("click", () => {
    $("tab-map").classList.add("active");
    $("tab-list").classList.remove("active");
    $("view-list").style.display = "none";
    $("view-map").style.display = "block";
    init_map();
    setTimeout(() => map && map.invalidateSize(), 100);
  });

  // Modal close
  $("modal-close").addEventListener("click", close_modal);
  $("modal-overlay").addEventListener("click", (e) => {
    if (e.target === $("modal-overlay")) close_modal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close_modal();
  });

  // Mobile sidebar
  $("mobile-filter-btn").addEventListener("click", () => {
    $("sidebar").classList.toggle("open");
  });
}

// ── Bootstrap ─────────────────────────────────────────
wire_events();
load_data();
