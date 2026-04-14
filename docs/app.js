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
    area: "",
    status: "",
    search: "",
    features: [],   // multi-select array
    sort: "price_asc",
    luxuryOnly: true,  // default ON — show only luxury-tier listings
  },
  quiz: {
    budgetMin: "",
    budgetMax: "",
    lifestyle: "",    // "entertainer" | "retreat" | "estate" | ""
    features: [],     // must-have feature tags
    completed: false,
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

function status_label(raw) {
  const s = (raw || "").toUpperCase().replace(/[\s-]/g, "_");
  if (s.includes("PENDING"))    return { text: "Pending",    cls: "status-pending" };
  if (s.includes("CONTINGENT")) return { text: "Contingent", cls: "status-contingent" };
  if (s.includes("ACTIVE") || s.includes("FOR_SALE") || s.includes("SALE"))
                                 return { text: "For Sale",   cls: "status-forsale" };
  if (s.includes("SOLD"))        return { text: "Sold",       cls: "status-sold" };
  return null;
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

    load_quiz_from_storage();
    if (state.quiz.completed) $("btn-clear-quiz").style.display = "inline-block";
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

// ── Luxury scoring ────────────────────────────────────
const LUXURY_FEATURES = [
  "pool", "master_suite", "walk_in_shower", "soaking_tub", "kitchen_island",
  "updated_kitchen", "quartz_counters", "updated_bathrooms", "smart_home",
  "three_car_garage", "in_law_suite", "ev_charger", "solar", "new_construction",
];

function compute_luxury_score(listing) {
  let score = 0;

  // Price (50 pts)
  const p = listing.price || 0;
  if      (p >= 1_000_000) score += 50;
  else if (p >= 800_000)   score += 40;
  else if (p >= 600_000)   score += 27;
  else if (p >= 400_000)   score += 13;

  // Luxury feature signals (50 pts)
  const luxHits = (listing.features || []).filter(f => LUXURY_FEATURES.includes(f)).length;
  if      (luxHits >= 4) score += 50;
  else if (luxHits === 3) score += 38;
  else if (luxHits === 2) score += 25;
  else if (luxHits === 1) score += 12;

  return Math.min(100, Math.round(score));
}

// ── Match scoring ─────────────────────────────────────
function compute_match_score(listing, quiz) {
  if (!quiz.completed) return null;
  let score = 0;

  // ── Budget (35 pts) ──────────────────────────────────
  const price = listing.price;
  const pMin  = quiz.budgetMin ? +quiz.budgetMin : null;
  const pMax  = quiz.budgetMax ? +quiz.budgetMax : null;
  if (price == null) {
    score += 17; // neutral
  } else if (pMin != null && pMax != null) {
    if (price >= pMin && price <= pMax) score += 35;
    else if (price > pMax && price <= pMax * 1.2) score += 15;
    else if (price < pMin && price >= pMin * 0.8) score += 15;
  } else if (pMax != null) {
    if (price <= pMax) score += 35;
    else if (price <= pMax * 1.2) score += 15;
  } else if (pMin != null) {
    if (price >= pMin) score += 35;
  } else {
    score += 35; // no budget set
  }

  // ── Lifestyle (30 pts) ───────────────────────────────
  const lifestyle = quiz.lifestyle || quiz.style || "";  // fallback for old saved quizzes
  if (!lifestyle) {
    score += 30;
  } else if (lifestyle === "entertainer") {
    const signals = ["pool", "kitchen_island", "open_floor_plan", "deck_patio", "updated_kitchen"];
    const hits = (listing.features || []).filter(f => signals.includes(f)).length;
    if      (hits >= 3) score += 30;
    else if (hits >= 2) score += 20;
    else if (hits >= 1) score += 10;
    else                score += 5;
  } else if (lifestyle === "retreat") {
    const signals = ["walk_in_shower", "soaking_tub", "master_suite", "smart_home", "updated_bathrooms"];
    const hits = (listing.features || []).filter(f => signals.includes(f)).length;
    if      (hits >= 3) score += 30;
    else if (hits >= 2) score += 20;
    else if (hits >= 1) score += 10;
    else                score += 5;
  } else if (lifestyle === "estate") {
    const signals = ["fireplace", "large_lot", "hardwood_floors", "finished_basement", "walk_in_closet"];
    const hits = (listing.features || []).filter(f => signals.includes(f)).length;
    if      (hits >= 3) score += 30;
    else if (hits >= 2) score += 20;
    else if (hits >= 1) score += 10;
    else                score += 5;
  }

  // ── Must-have features (35 pts) ──────────────────────
  if (!quiz.features.length) {
    score += 35;
  } else {
    const listingFeatures = listing.features || [];
    const matched = quiz.features.filter(f => listingFeatures.includes(f)).length;
    score += Math.round((matched / quiz.features.length) * 35);
  }

  return Math.min(100, Math.round(score));
}

function compute_match_breakdown(listing, quiz) {
  if (!quiz.completed) return null;
  const result = { budget: null, style: null, features: [] };

  // Budget
  const price = listing.price;
  const pMin  = quiz.budgetMin ? +quiz.budgetMin : null;
  const pMax  = quiz.budgetMax ? +quiz.budgetMax : null;
  if (price == null) {
    result.budget = { status: "unknown", label: "Price not listed" };
  } else if (pMin != null || pMax != null) {
    const inRange = (pMin == null || price >= pMin) && (pMax == null || price <= pMax);
    if (inRange) {
      result.budget = { status: "match", label: "In your budget" };
    } else if (pMax != null && price > pMax) {
      const over = Math.round((price - pMax) / 1000);
      result.budget = { status: "partial", label: `$${over}K over budget` };
    } else {
      const under = Math.round((pMin - price) / 1000);
      result.budget = { status: "miss", label: `$${under}K below min` };
    }
  }

  // Lifestyle
  const lifestyle = quiz.lifestyle || quiz.style || "";
  if (lifestyle) {
    if (lifestyle === "entertainer") {
      const signals = ["pool", "kitchen_island", "open_floor_plan", "deck_patio", "updated_kitchen"];
      const hits = (listing.features || []).filter(f => signals.includes(f)).length;
      if (hits >= 3) result.style = { status: "match", label: "Great for entertaining" };
      else if (hits >= 1) result.style = { status: "partial", label: `${hits} entertainer feature${hits > 1 ? "s" : ""} found` };
      else result.style = { status: "miss", label: "Few entertainer signals" };
    } else if (lifestyle === "retreat") {
      const signals = ["walk_in_shower", "soaking_tub", "master_suite", "smart_home", "updated_bathrooms"];
      const hits = (listing.features || []).filter(f => signals.includes(f)).length;
      if (hits >= 3) result.style = { status: "match", label: "Retreat features found" };
      else if (hits >= 1) result.style = { status: "partial", label: `${hits} retreat feature${hits > 1 ? "s" : ""} found` };
      else result.style = { status: "miss", label: "Few retreat signals" };
    } else if (lifestyle === "estate") {
      const signals = ["fireplace", "large_lot", "hardwood_floors", "finished_basement", "walk_in_closet"];
      const hits = (listing.features || []).filter(f => signals.includes(f)).length;
      if (hits >= 3) result.style = { status: "match", label: "Classic estate feel" };
      else if (hits >= 1) result.style = { status: "partial", label: `${hits} estate feature${hits > 1 ? "s" : ""} found` };
      else result.style = { status: "miss", label: "Few estate signals" };
    }
  }

  // Must-have features
  if (quiz.features.length) {
    const listingFeatures = listing.features || [];
    result.features = quiz.features.map(f => ({
      tag: f,
      label: feature_label(f),
      matched: listingFeatures.includes(f),
    }));
  }

  return result;
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
  if (f.status) {
    list = list.filter((l) => {
      const s = (l.status || "").toUpperCase().replace(/[\s-]/g, "_");
      if (f.status === "for_sale")    return s.includes("SALE") || s.includes("ACTIVE");
      if (f.status === "pending")     return s.includes("PENDING");
      if (f.status === "contingent")  return s.includes("CONTINGENT");
      return true;
    });
  }

  // Free-text search (description + address + ai keywords)
  if (f.search) {
    const q = f.search.toLowerCase();
    list = list.filter((l) => {
      const haystack = [
        l.description || "",
        l.address || "",
        (l.keywords || []).join(" "),
        (l.features || []).join(" ").replace(/_/g, " "),
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }

  // Feature tag filter (multi-select — keyword regex only, no LLM to avoid hallucinations)
  if (f.features.length) {
    list = list.filter((l) => {
      const tags = l.features || [];
      return f.features.every((feat) => tags.includes(feat));
    });
  }

  if (f.type) {
    list = list.filter((l) => normalize_type(l.property_type) === f.type);
  }

  // Luxury-only filter
  if (f.luxuryOnly) {
    list = list.filter((l) => compute_luxury_score(l) >= 40);
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
    case "match_desc":
      list.sort((a, b) => (compute_match_score(b, state.quiz) ?? 0) - (compute_match_score(a, state.quiz) ?? 0));
      break;
    case "luxury_desc":
      list.sort((a, b) => compute_luxury_score(b) - compute_luxury_score(a));
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

  const match_score = compute_match_score(listing, state.quiz);
  const breakdown   = compute_match_breakdown(listing, state.quiz);
  let breakdown_html = "";
  if (breakdown) {
    const rows = [];
    if (breakdown.budget) {
      const icon = breakdown.budget.status === "match" ? "✓" : breakdown.budget.status === "miss" ? "✗" : "~";
      rows.push(`<div class="bd-row bd-${breakdown.budget.status}"><span class="bd-icon">${icon}</span><span class="bd-cat">Budget</span><span class="bd-note">${breakdown.budget.label}</span></div>`);
    }
    if (breakdown.style) {
      const icon = breakdown.style.status === "match" ? "✓" : breakdown.style.status === "miss" ? "✗" : "~";
      rows.push(`<div class="bd-row bd-${breakdown.style.status}"><span class="bd-icon">${icon}</span><span class="bd-cat">Style</span><span class="bd-note">${breakdown.style.label}</span></div>`);
    }
    if (breakdown.features.length) {
      breakdown.features.forEach(f => {
        rows.push(`<div class="bd-row bd-${f.matched ? "match" : "miss"}"><span class="bd-icon">${f.matched ? "✓" : "✗"}</span><span class="bd-note">${f.label}</span></div>`);
      });
    }
    breakdown_html = `<div class="match-breakdown" id="bd-${idx}">${rows.join("")}</div>`;
  }
  const match_badge_html = match_score != null
    ? `<span class="match-badge match-badge-${match_score >= 70 ? "green" : match_score >= 40 ? "amber" : "gray"}" onclick="event.stopPropagation();document.getElementById('bd-${idx}')?.classList.toggle('bd-open')">${match_score}% match ▾</span>${breakdown_html}`
    : "";

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

  const lux_score = compute_luxury_score(listing);
  const lux_tier  = lux_score >= 80 ? "platinum" : lux_score >= 60 ? "gold" : lux_score >= 40 ? "silver" : null;
  const lux_badge = lux_tier
    ? `<span class="luxury-badge luxury-${lux_tier}">✦ ${lux_tier.charAt(0).toUpperCase() + lux_tier.slice(1)}</span>`
    : "";

  return `
    <div class="listing-card" data-idx="${idx}">
      <div class="card-image">
        ${img_html}
        <span class="source-badge source-${listing.source}">${source_label(listing.source)}</span>
        ${lux_badge}
        ${match_badge_html}
      </div>
      <div class="card-body">
        <div class="card-price-row">
          <div class="card-price">${fmt_price(listing.price)}</div>
          ${(() => { const s = status_label(listing.status); return s ? `<span class="status-badge ${s.cls}">${s.text}</span>` : ""; })()}
        </div>
        <div class="card-address">${listing.address}${listing.city ? ", " + listing.city : ""}${listing.zip ? " " + listing.zip : ""}</div>
        <div class="card-stats">${stats || '<span style="color:#9ca3af">Details unavailable</span>'}</div>
      </div>
      ${listing.features?.length
        ? `<div class="card-features">${listing.features.slice(0, 4).map(f => `<span class="card-feature-tag">${feature_label(f)}</span>`).join("")}</div>`
        : ""}
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


const FEATURE_LABELS = {
  updated_kitchen:   "Updated Kitchen",
  quartz_counters:   "Quartz Counters",
  granite_counters:  "Granite Counters",
  kitchen_island:    "Kitchen Island",
  new_appliances:    "New Appliances",
  hardwood_floors:   "Hardwood Floors",
  new_flooring:      "New Flooring",
  open_floor_plan:   "Open Floor Plan",
  pool:              "Pool",
  fenced_yard:       "Fenced Yard",
  deck_patio:        "Deck / Patio",
  large_lot:         "Large Lot",
  new_roof:          "New Roof",
  new_hvac:          "New HVAC",
  new_windows:       "New Windows",
  finished_basement: "Finished Basement",
  fireplace:         "Fireplace",
  master_suite:      "Master Suite",
  walk_in_closet:    "Walk-in Closet",
  bonus_room:        "Bonus Room",
  in_law_suite:      "In-Law Suite",
  two_car_garage:    "2-Car Garage",
  three_car_garage:  "3-Car Garage",
  move_in_ready:     "Move-in Ready",
  new_construction:  "New Construction",
  needs_work:        "Needs Work",
  smart_home:        "Smart Home",
  solar:             "Solar Panels",
  ev_charger:        "EV Charger",
  updated_bathrooms: "Updated Bathrooms",
  soaking_tub:       "Soaking Tub",
  walk_in_shower:    "Walk-in Shower",
};

function feature_label(tag) {
  return FEATURE_LABELS[tag] || tag.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
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
      ${listing.features?.length || listing.keywords?.length ? `
        <div class="modal-features">
          ${(listing.features || []).map(f => `<span class="modal-feature-tag">${feature_label(f)}</span>`).join("")}
          ${(listing.keywords || []).map(k => `<span class="modal-keyword-tag">${k}</span>`).join("")}
        </div>` : ""}
      ${listing.description ? `
        <div class="modal-description">
          <div class="modal-description-label">About this home</div>
          <p>${listing.description}</p>
        </div>` : ""}
      <div class="modal-actions">
        ${listing.url
          ? `<a class="btn-primary" href="${listing.url}" target="_blank" rel="noopener">View on ${source_label(listing.source)} ↗</a>`
          : ""}
      </div>
    </div>`;

  $("modal-overlay").style.display = "flex";
  document.body.style.overflow = "hidden";
}

function close_modal() {
  $("modal-overlay").style.display = "none";
  document.body.style.overflow = "";
}

// ── Quiz ──────────────────────────────────────────────
function open_quiz() {
  const q = state.quiz;
  // Pre-fill from saved state
  $("quiz-budget-min").value = q.budgetMin;
  $("quiz-budget-max").value = q.budgetMax;
  const lifestyle = q.lifestyle || q.style || "";
  $("quiz-modal-overlay").querySelectorAll(".quiz-style-chip").forEach(c => {
    c.classList.toggle("active", c.dataset.val === lifestyle);
  });
  $("quiz-features-group").querySelectorAll(".chip").forEach(c => {
    c.classList.toggle("active", q.features.includes(c.dataset.val));
  });
  $("quiz-modal-overlay").style.display = "flex";
  document.body.style.overflow = "hidden";
}

function close_quiz() {
  $("quiz-modal-overlay").style.display = "none";
  document.body.style.overflow = "";
}

function save_quiz() {
  const lifestyle = $("quiz-modal-overlay").querySelector(".quiz-style-chip.active")?.dataset.val || "";
  const features = [...$("quiz-features-group").querySelectorAll(".chip.active")]
    .map(c => c.dataset.val).filter(Boolean);

  state.quiz = {
    budgetMin: $("quiz-budget-min").value,
    budgetMax: $("quiz-budget-max").value,
    lifestyle,
    features,
    completed: true,
  };

  try {
    localStorage.setItem("buyer-quiz", JSON.stringify(state.quiz));
  } catch (_) {}

  // Auto-switch sort to Best Match
  state.filters.sort = "match_desc";
  $("filter-sort").value = "match_desc";

  $("btn-clear-quiz").style.display = "inline-block";
  close_quiz();
  apply_filters();
}

function load_quiz_from_storage() {
  try {
    const saved = localStorage.getItem("buyer-quiz");
    if (saved) {
      const q = JSON.parse(saved);
      if (q.completed) state.quiz = q;
    }
  } catch (_) {}
}

function clear_quiz() {
  state.quiz = { budgetMin: "", budgetMax: "", lifestyle: "", features: [], completed: false };
  try { localStorage.removeItem("buyer-quiz"); } catch (_) {}
  $("btn-clear-quiz").style.display = "none";
  apply_filters();
  // Reset sort if it was on match
  if (state.filters.sort === "match_desc") {
    state.filters.sort = "price_asc";
    $("filter-sort").value = "price_asc";
  }
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
  wire_chips("filter-area",   "area");
  wire_chips("filter-status", "status");

  // Search
  $("filter-search").addEventListener("input", (e) => {
    state.filters.search = e.target.value.trim();
    apply_filters();
  });

  // Feature chips — multi-select
  $("filter-features").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const val = chip.dataset.val;
    if (val === "") {
      // "Any" clears all
      state.filters.features = [];
      $("filter-features").querySelectorAll(".chip").forEach((c) => {
        c.classList.toggle("active", c.dataset.val === "");
      });
    } else {
      // Toggle this feature on/off
      const idx = state.filters.features.indexOf(val);
      if (idx === -1) {
        state.filters.features.push(val);
      } else {
        state.filters.features.splice(idx, 1);
      }
      // Update chip active states
      const anyChip = $("filter-features").querySelector(".chip[data-val='']");
      const hasAny = state.filters.features.length === 0;
      anyChip.classList.toggle("active", hasAny);
      $("filter-features").querySelectorAll(".chip:not([data-val=''])").forEach((c) => {
        c.classList.toggle("active", state.filters.features.includes(c.dataset.val));
      });
    }
    apply_filters();
  });

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
      type: "", zip: "", source: "", area: "", status: "",
      search: "", features: [], sort: "price_asc",
    };
    // Reset UI
    $("filter-price-min").value = "";
    $("filter-price-max").value = "";
    $("filter-zip").value = "";
    $("filter-search").value = "";
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
  function set_tab(tab) {
    ["tab-list","tab-map"].forEach(id => $(id).classList.remove("active"));
    ["view-list","view-map"].forEach(id => $(id).style.display = "none");
    $("tab-" + tab).classList.add("active");
    $("view-" + tab).style.display = "block";
    if (tab === "map") { init_map(); setTimeout(() => map && map.invalidateSize(), 100); }
  }
  $("tab-list").addEventListener("click", () => set_tab("list"));
  $("tab-map" ).addEventListener("click", () => set_tab("map"));

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

  // Luxury toggle
  $("luxury-toggle").addEventListener("change", (e) => {
    state.filters.luxuryOnly = e.target.checked;
    apply_filters();
  });

  // Quiz
  $("btn-find-match").addEventListener("click", open_quiz);
  $("btn-clear-quiz").addEventListener("click", clear_quiz);
  $("quiz-modal-overlay").addEventListener("click", (e) => {
    if (e.target === $("quiz-modal-overlay")) close_quiz();
  });
  $("quiz-close").addEventListener("click", close_quiz);
  $("quiz-save").addEventListener("click", save_quiz);

  // Quiz style chips (single-select)
  $("quiz-modal-overlay").querySelectorAll(".quiz-style-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      $("quiz-modal-overlay").querySelectorAll(".quiz-style-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
    });
  });

  // Quiz feature chips (multi-select)
  $("quiz-features-group").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    chip.classList.toggle("active");
  });
}

// ── Bootstrap ─────────────────────────────────────────
wire_events();
load_data();
