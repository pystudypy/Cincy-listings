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

// ── AI Deep Dive ──────────────────────────────────────
// Point to local server for testing; swap to Cloudflare Worker URL for production
const DEEP_DIVE_API = "/analyze";
const DEEP_DIVE_CACHE_PREFIX = "ai-deep-dive-v2-";
const DEEP_DIVE_CHUNK_SIZE = 15;   // images per parallel request
const DEEP_DIVE_MAX_CHUNKS = 3;    // max concurrent requests → up to 45 images

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
    dom: "",
    search: "",
    features: [],   // multi-select array
    sort: "price_asc",
    luxuryOnly: true,  // default ON — show only luxury-tier listings
  },
  quiz: {
    budgetMin: "",
    budgetMax: "",
    lifestyle: "",    // "entertainer"|"retreat"|"estate"|"urban"|"outdoor"|""
    features: [],     // must-have feature tags
    neighborhood: "", // "OH" | "KY" | ""
    completed: false,
    // v2 fields
    bedsMin: "",      // "2"|"3"|"4"|"5"
    bathsMin: "",     // "1"|"2"|"3"
    buyerType: "",    // "first_timer"|"family"|"investor"|"downsizer"
    condition: "",    // "move_in_ready"|"light_work"|"project"
    propertyType: "", // "SINGLE_FAMILY"|"CONDO"|"TOWNHOUSE"|"MULTI_FAMILY"
    _v: 2,
  },
  saved: new Set(),   // listing IDs saved to localStorage
  compare: [],        // ordered array of listing IDs, max 3
  modal_nav: { list: [], idx: 0 }, // current modal navigation context
};

// ── Leaflet map instance
let map = null;
let markers = [];


// ── Helpers ───────────────────────────────────────────
const $ = (id) => document.getElementById(id);

// Route hotlink-protected CDN images through our server proxy.
// Add more domains here as needed — server.py IMG_PROXY_RULES must match.
const IMG_PROXY_DOMAINS = ["cdn-redfin.com", "redfin.com"];
function proxy_img(url) {
  if (!url) return url;
  const clean = url.replace(/&amp;/g, "&");
  if (IMG_PROXY_DOMAINS.some(d => clean.includes(d))) {
    return "/img-proxy?url=" + encodeURIComponent(clean);
  }
  return clean;
}

function debounce(fn, delay) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

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
    state.all = data.listings || (Array.isArray(data) ? data : []);

    // New listings badge
    const newCount = state.all.filter(l => l.days_on_market != null && l.days_on_market <= 1).length;
    const newBadge = $("new-count");
    if (newBadge && newCount > 0) newBadge.textContent = newCount;

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
// ── Description-based feature detection ──────────────
const FEATURE_DESC_KEYWORDS = {
  pool:              ["pool", "swimming pool", "in-ground pool"],
  master_suite:      ["master suite", "primary suite", "owner's suite", "owners suite"],
  walk_in_shower:    ["walk-in shower", "walk in shower", "frameless shower", "tile shower"],
  soaking_tub:       ["soaking tub", "jacuzzi", "jetted tub", "freestanding tub", "clawfoot"],
  updated_kitchen:   ["chef's kitchen", "gourmet kitchen", "updated kitchen", "quartz counters", "kitchen island", "granite counters", "quartzite"],
  smart_home:        ["smart home", "home automation", "smart thermostat", "nest", "lutron"],
  three_car_garage:  ["3-car garage", "3 car garage", "three car garage", "triple car"],
  in_law_suite:      ["in-law suite", "in law suite", "guest suite", "au pair", "accessory unit", "adu"],
  ev_charger:        ["ev charger", "electric vehicle", "charging station", "tesla charger"],
  solar:             ["solar panel", "solar system", "photovoltaic", "solar energy"],
  fireplace:         ["fireplace", "fire place", "wood burning"],
  hardwood_floors:   ["hardwood floors", "hardwood flooring", "hardwood", "wood floor", "oak floor"],
  finished_basement: ["finished basement", "finished lower level", "lower level", "rec room"],
  walk_in_closet:    ["walk-in closet", "walk in closet", "oversized closet", "custom closet"],
  deck_patio:        ["deck", "patio", "outdoor entertaining", "covered porch", "pergola"],
  open_floor_plan:   ["open floor plan", "open concept", "great room", "open layout"],
  updated_bathrooms: ["updated bathroom", "renovated bathroom", "spa bath", "marble bath", "spa-like"],
};

function _desc_has_feature(desc, featureKey) {
  const lower = (desc || "").toLowerCase();
  return (FEATURE_DESC_KEYWORDS[featureKey] || []).some(kw => lower.includes(kw));
}

// Vision-backed feature check: checks structured tags from image analysis first,
// falls back to description keyword scan if not yet vision-analyzed.
function _has_feature(listing, featureKey) {
  if (listing.features && listing.features.includes(featureKey)) return true;
  return _desc_has_feature(listing.description, featureKey);
}

// Returns "photos" if matched via vision tags, "description" if matched via text, null if no match.
function _feature_source(listing, featureKey) {
  if (listing.features && listing.features.includes(featureKey)) return "photos";
  if (_desc_has_feature(listing.description, featureKey)) return "description";
  return null;
}

const LIFESTYLE_SIGNALS = {
  entertainer: ["pool", "deck_patio", "updated_kitchen", "open_floor_plan", "outdoor kitchen", "bar", "wet bar", "theater", "home theater"],
  retreat:     ["walk_in_shower", "soaking_tub", "master_suite", "updated_bathrooms", "spa", "sauna", "steam"],
  estate:      ["fireplace", "hardwood_floors", "finished_basement", "walk_in_closet", "wine cellar", "library", "study"],
  urban:       ["walkable", "walk score", "downtown", "urban", "light rail", "transit", "city view", "rooftop", "loft"],
  outdoor:     ["hiking", "trail", "acreage", "pond", "lake", "wooded", "privacy", "nature", "creek", "horse"],
};

// ── Match scoring ─────────────────────────────────────
function _compute_match_score_v1(listing, quiz) {
  let score = 0;

  // ── Budget (25 pts) ──────────────────────────────────
  const price = listing.price;
  const pMin  = quiz.budgetMin ? +quiz.budgetMin : null;
  const pMax  = quiz.budgetMax ? +quiz.budgetMax : null;
  if (price == null) {
    score += 12; // neutral
  } else if (pMin != null && pMax != null) {
    if (price >= pMin && price <= pMax) score += 25;
    else if (price > pMax && price <= pMax * 1.2) score += 10;
    else if (price < pMin && price >= pMin * 0.8) score += 10;
  } else if (pMax != null) {
    if (price <= pMax) score += 25;
    else if (price <= pMax * 1.2) score += 10;
  } else if (pMin != null) {
    if (price >= pMin) score += 25;
  } else {
    score += 25; // no budget set
  }

  // ── Neighborhood (10 pts) ────────────────────────────
  const nbhd = quiz.neighborhood || "";
  if (!nbhd) {
    score += 10;
  } else {
    const listingState = (listing.state || "").toUpperCase();
    if (nbhd === "OH" && listingState === "OH") score += 10;
    else if (nbhd === "KY" && listingState === "KY") score += 10;
    else score += 2; // wrong area, small partial
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

function _compute_match_score_v2(listing, quiz) {
  let score = 0;
  const desc = (listing.description || "").toLowerCase();
  const price = listing.price;

  // ── Budget (25 pts) ─────────────────────────────────
  const pMin = quiz.budgetMin ? +quiz.budgetMin : null;
  const pMax = quiz.budgetMax ? +quiz.budgetMax : null;
  if (price == null) {
    score += 12;
  } else if (pMin != null && pMax != null) {
    if (price >= pMin && price <= pMax) score += 25;
    else if (price > pMax && price <= pMax * 1.2) score += 10;
    else if (price < pMin && price >= pMin * 0.8) score += 10;
  } else if (pMax != null) {
    if (price <= pMax) score += 25;
    else if (price <= pMax * 1.2) score += 10;
  } else if (pMin != null) {
    if (price >= pMin) score += 25;
  } else {
    score += 25;
  }

  // ── Beds (12 pts) ────────────────────────────────────
  const bedsMin = quiz.bedsMin ? +quiz.bedsMin : null;
  if (!bedsMin) {
    score += 12;
  } else {
    const beds = listing.beds != null ? +listing.beds : null;
    if (beds == null) score += 6;
    else if (beds >= bedsMin) score += 12;
    else if (beds >= bedsMin - 1) score += 6;
  }

  // ── Baths (8 pts) ────────────────────────────────────
  const bathsMin = quiz.bathsMin ? +quiz.bathsMin : null;
  if (!bathsMin) {
    score += 8;
  } else {
    const baths = listing.baths != null ? +listing.baths : null;
    if (baths == null) score += 4;
    else if (baths >= bathsMin) score += 8;
    else if (baths >= bathsMin - 0.5) score += 4;
  }

  // ── Neighborhood (8 pts) ────────────────────────────
  const nbhd = quiz.neighborhood || "";
  if (!nbhd) {
    score += 8;
  } else {
    const listingState = (listing.state || "").toUpperCase();
    if ((nbhd === "OH" && listingState === "OH") || (nbhd === "KY" && listingState === "KY")) score += 8;
    else score += 2;
  }

  // ── Lifestyle (17 pts) — description-based ──────────
  const lifestyle = quiz.lifestyle || quiz.style || "";
  if (!lifestyle) {
    score += 17;
  } else {
    const signals = LIFESTYLE_SIGNALS[lifestyle] || [];
    const hits = signals.filter(kw => {
      if (FEATURE_DESC_KEYWORDS[kw]) return _has_feature(listing, kw);
      return desc.includes(kw);
    }).length;
    if      (hits >= 3) score += 17;
    else if (hits >= 2) score += 12;
    else if (hits >= 1) score += 7;
    else                score += 2;
  }

  // ── Must-haves (15 pts) — description-based ─────────
  if (!quiz.features.length) {
    score += 15;
  } else {
    const matched = quiz.features.filter(f => _has_feature(listing, f)).length;
    score += Math.round((matched / quiz.features.length) * 15);
  }

  // ── Buyer type (8 pts) ───────────────────────────────
  const buyerType = quiz.buyerType || "";
  if (!buyerType) {
    score += 8;
  } else if (buyerType === "first_timer") {
    let hits = 0;
    if (price && price < 400000) hits++;
    if (desc.includes("move-in ready") || desc.includes("move in ready") || desc.includes("turnkey")) hits++;
    if (listing.beds && +listing.beds <= 3) hits++;
    score += hits >= 2 ? 8 : hits >= 1 ? 5 : 3;
  } else if (buyerType === "family") {
    let hits = 0;
    if (listing.beds && +listing.beds >= 3) hits++;
    if (listing.sqft && +listing.sqft >= 2000) hits++;
    if (desc.includes("school") || desc.includes("district")) hits++;
    if (desc.includes("yard") || desc.includes("backyard") || desc.includes("fenced")) hits++;
    score += hits >= 3 ? 8 : hits >= 2 ? 5 : hits >= 1 ? 3 : 1;
  } else if (buyerType === "investor") {
    let hits = 0;
    if (["MULTI_FAMILY", "DUPLEX", "TRIPLEX"].some(t => (listing.type || "").toUpperCase().includes(t))) hits += 2;
    if (desc.includes("rental") || desc.includes("tenant") || desc.includes("income")) hits++;
    if (_has_feature(listing, "in_law_suite")) hits++;
    score += hits >= 2 ? 8 : hits >= 1 ? 5 : 2;
  } else if (buyerType === "downsizer") {
    let hits = 0;
    if (listing.beds && +listing.beds <= 3) hits++;
    if (desc.includes("ranch") || desc.includes("one-story") || desc.includes("single story") || desc.includes("main floor")) hits++;
    if (desc.includes("condo") || desc.includes("townhome") || (listing.type || "").toUpperCase().includes("CONDO")) hits++;
    if (desc.includes("low maintenance") || desc.includes("maintenance-free")) hits++;
    score += hits >= 2 ? 8 : hits >= 1 ? 5 : 3;
  }

  // ── Property type (4 pts) ────────────────────────────
  const propType = quiz.propertyType || "";
  if (!propType) {
    score += 4;
  } else {
    const lType = (listing.type || "").toUpperCase().replace(/[\s\-]/g, "_");
    if (lType === propType || lType.includes(propType.replace(/_/g, ""))) score += 4;
    else if (propType === "SINGLE_FAMILY" && lType.includes("FAMILY")) score += 4;
    else score += 1;
  }

  // ── Condition tolerance (3 pts) ──────────────────────
  const condition = quiz.condition || "";
  if (!condition) {
    score += 3;
  } else if (condition === "move_in_ready") {
    if (desc.includes("move-in ready") || desc.includes("move in ready") || desc.includes("turnkey") ||
        desc.includes("updated") || desc.includes("renovated") || desc.includes("new construction")) score += 3;
    else score += 1;
  } else if (condition === "light_work") {
    score += 2;
  } else if (condition === "project") {
    if (desc.includes("as-is") || desc.includes("fixer") || desc.includes("potential") || desc.includes("opportunity")) score += 3;
    else score += 2;
  }

  return Math.min(100, Math.round(score));
}

function compute_match_score(listing, quiz) {
  if (!quiz.completed) return null;
  if (quiz._v >= 2) return _compute_match_score_v2(listing, quiz);
  return _compute_match_score_v1(listing, quiz);
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

  // Lifestyle — description-based
  const lifestyle = quiz.lifestyle || quiz.style || "";
  if (lifestyle) {
    const signals = LIFESTYLE_SIGNALS[lifestyle] || [];
    const desc = (listing.description || "").toLowerCase();
    const hits = signals.filter(kw => FEATURE_DESC_KEYWORDS[kw] ? _has_feature(listing, kw) : desc.includes(kw)).length;
    const labels = { entertainer: "Great for entertaining", retreat: "Retreat features found", estate: "Classic estate feel", urban: "Urban professional vibe", outdoor: "Outdoor living appeal" };
    const label = labels[lifestyle] || "Lifestyle match";
    if (hits >= 3) result.style = { status: "match", label };
    else if (hits >= 1) result.style = { status: "partial", label: `${hits} ${lifestyle} signal${hits > 1 ? "s" : ""} found` };
    else result.style = { status: "miss", label: `Few ${lifestyle} signals` };
  }

  // Must-have features — description-based
  if (quiz.features.length) {
    const desc = (listing.description || "").toLowerCase();
    result.features = quiz.features.map(f => ({
      tag: f,
      label: feature_label(f),
      matched: _has_feature(listing, f),
      source: _feature_source(listing, f),
    }));
  }

  return result;
}

function generate_why_sentences(listing, quiz) {
  if (!quiz.completed) return [];
  const out = [];
  const desc = (listing.description || "").toLowerCase();
  const price = listing.price;

  // Budget sentence
  if (price && quiz.budgetMax && price <= +quiz.budgetMax) {
    const under = Math.round((+quiz.budgetMax - price) / 1000);
    if (under >= 20) out.push(`$${under}K under your maximum budget.`);
    else out.push("Fits within your budget.");
  } else if (price && quiz.budgetMin && price >= +quiz.budgetMin && !quiz.budgetMax) {
    out.push("Priced within your stated range.");
  }

  // Beds sentence
  if (quiz.bedsMin && listing.beds && +listing.beds >= +quiz.bedsMin) {
    out.push(`${listing.beds} bedrooms — meets your ${quiz.bedsMin}+ requirement.`);
  }

  // Lifestyle sentence
  const lifestyle = quiz.lifestyle || quiz.style || "";
  if (lifestyle === "entertainer") {
    const found = ["inground_pool","updated_kitchen","deck_patio","open_floor_plan","outdoor_kitchen"].filter(f => _has_feature(listing, f));
    if (found.length) out.push(`Built for entertaining — ${found.slice(0,2).map(f => feature_label(f)).join(" & ")}.`);
  } else if (lifestyle === "retreat") {
    const found = ["walk_in_shower","soaking_tub","master_suite","updated_bathrooms","spa_bathroom"].filter(f => _has_feature(listing, f));
    if (found.length) out.push(`Spa-like retreat features — ${found.slice(0,2).map(f => feature_label(f)).join(" & ")}.`);
  } else if (lifestyle === "estate") {
    const found = ["fireplace","hardwood_floors","walk_in_closet","finished_basement","built_ins","coffered_ceiling"].filter(f => _has_feature(listing, f));
    if (found.length) out.push(`Classic estate touches — ${found.slice(0,2).map(f => feature_label(f)).join(" & ")}.`);
  } else if (lifestyle === "urban") {
    if (desc.includes("downtown") || desc.includes("walkable") || desc.includes("urban")) out.push("Walkable urban location.");
  } else if (lifestyle === "outdoor") {
    if (desc.includes("acre") || desc.includes("wooded") || desc.includes("trail") || desc.includes("pond")) out.push("Outdoor living and natural privacy.");
  }

  // Must-have feature sentence
  if (quiz.features.length) {
    const matched = quiz.features.filter(f => _has_feature(listing, f));
    if (matched.length) {
      const fromPhotos = matched.filter(f => _feature_source(listing, f) === "photos");
      const prefix = fromPhotos.length > 0 ? "Confirmed in listing photos:" : "Has your must-haves:";
      out.push(`${prefix} ${matched.slice(0,3).map(f => feature_label(f)).join(", ")}.`);
    }
  }

  // Buyer type fallback sentences
  if (out.length < 2 && quiz.buyerType === "family" && listing.beds && +listing.beds >= 3) {
    out.push(`${listing.beds}-bedroom home suited for a growing family.`);
  }
  if (out.length < 2 && quiz.buyerType === "investor" && desc.includes("rental")) {
    out.push("Rental income potential noted in the listing.");
  }
  if (out.length < 2 && quiz.buyerType === "downsizer") {
    if (desc.includes("ranch") || desc.includes("one-story") || desc.includes("main floor"))
      out.push("Single-level living — low-maintenance lifestyle.");
  }

  return out.slice(0, 3);
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

  // Days on market filter (only applies to listings that have DOM data)
  if (f.dom) {
    list = list.filter((l) => {
      const d = l.days_on_market;
      if (d == null) return true; // no DOM data — always show
      if (f.dom === "7")   return d <= 7;
      if (f.dom === "14")  return d <= 14;
      if (f.dom === "30")  return d <= 30;
      if (f.dom === "90")  return d <= 90;
      return true;
    });
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
  const apply_count = $("sidebar-apply-count");
  if (apply_count) apply_count.textContent = `(${list.length.toLocaleString()})`;
  update_filter_badge();
  _update_more_filters_badge();
  render_list();
  if ($("tab-new")?.classList.contains("active")) render_new();
  if (map) render_map_markers();
}

// ── Mobile sidebar close ──────────────────────────────
function close_sidebar() {
  $("sidebar").classList.remove("open");
  const bd = $("sidebar-backdrop");
  if (bd) bd.style.display = "none";
  const fab = $("mobile-filter-fab");
  if (fab) fab.style.display = "";
}

// ── More filters accordion ────────────────────────────
function toggle_sidebar_collapse() {
  const sidebar = $("sidebar");
  const layout  = document.querySelector(".layout");
  const collapsed = sidebar.classList.toggle("collapsed");
  layout?.classList.toggle("sidebar-collapsed", collapsed);
  try { localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0"); } catch (_) {}
}

function toggle_more_filters() {
  const section = $("more-filters-section");
  const btn     = $("more-filters-toggle");
  if (!section) return;
  section.classList.toggle("open");
  btn.classList.toggle("more-filters-open");
}

function _update_more_filters_badge() {
  const f = state.filters;
  const n = [f.dom, f.type, f.area, f.source, f.zip, f.features.length > 0]
    .filter(Boolean).length;
  const badge = $("more-filters-badge");
  if (!badge) return;
  if (n > 0) { badge.textContent = n; badge.classList.add("visible"); }
  else        { badge.textContent = ""; badge.classList.remove("visible"); }
}

function count_active_filters() {
  const f = state.filters;
  let n = 0;
  if (f.priceMin)       n++;
  if (f.priceMax)       n++;
  if (f.beds)           n++;
  if (f.baths)          n++;
  if (f.type)           n++;
  if (f.zip)            n++;
  if (f.source)         n++;
  if (f.area)           n++;
  if (f.status)         n++;
  if (f.dom)            n++;
  if (f.search)         n++;
  if (f.features.length) n++;
  if (!f.luxuryOnly)    n++; // luxury toggle OFF is non-default
  return n;
}

function update_filter_badge() {
  const cnt = count_active_filters();
  // Desktop badge (now hidden but kept for JS compat)
  const badge = $("filter-badge");
  if (badge) {
    badge.textContent = cnt || "";
    badge.style.display = cnt > 0 ? "inline-block" : "none";
  }
  // Mobile FAB badge
  const fabBadge = $("mobile-fab-badge");
  if (fabBadge) {
    fabBadge.textContent = cnt || "";
    fabBadge.style.display = cnt > 0 ? "inline-block" : "none";
  }
}

// ── Favorites ─────────────────────────────────────────
function toggle_save(id) {
  if (state.saved.has(id)) {
    state.saved.delete(id);
  } else {
    state.saved.add(id);
  }
  try {
    localStorage.setItem("saved-listings", JSON.stringify([...state.saved]));
  } catch (_) {}
  // Update all heart buttons for this listing (card may appear in multiple views)
  document.querySelectorAll(`.save-btn[data-id="${id}"]`).forEach(btn => {
    const isSaved = state.saved.has(id);
    btn.classList.toggle("saved", isSaved);
    btn.textContent = isSaved ? "♥" : "♡";
    btn.title = isSaved ? "Remove from saved" : "Save listing";
  });
  const badge = $("saved-count");
  if (badge) badge.textContent = state.saved.size || "";
}

function render_saved() {
  const grid = $("saved-grid");
  if (!grid) return;

  const savedListings = state.all.filter(l => state.saved.has(l.id));

  if (!savedListings.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <h3>No saved listings yet</h3>
        <p>Click the ♡ on any listing card to save it here.</p>
      </div>`;
    return;
  }

  grid.innerHTML = savedListings.map((l, i) => card_html(l, i)).join("");

  grid.querySelectorAll(".listing-card").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = +el.dataset.idx;
      open_modal(savedListings[idx], savedListings, idx);
    });
    const card_img_wrap = el.querySelector(".card-image");
    if (card_img_wrap) _wire_card_touch(card_img_wrap);
  });
}

// ── Compare ────────────────────────────────────────────

function toggle_compare(id) {
  const idx = state.compare.indexOf(id);
  if (idx !== -1) {
    state.compare.splice(idx, 1);
  } else {
    if (state.compare.length >= 3) state.compare.shift(); // drop oldest
    state.compare.push(id);
  }
  _update_compare_ui();
}

function _update_compare_ui() {
  const n = state.compare.length;
  const badge = $("compare-count");
  if (badge) badge.textContent = n || "";
  $("tab-compare")?.classList.toggle("has-items", n > 0);

  // Sync all ⇄ buttons across all rendered cards
  document.querySelectorAll("[data-compare-id]").forEach(btn => {
    const active = state.compare.includes(btn.dataset.compareId);
    btn.classList.toggle("compare-active", active);
    if (btn.classList.contains("btn-compare-modal")) {
      btn.textContent = active ? "⇄ Added" : "⇄ Compare";
    }
  });

  // Show/hide sticky tray
  const tray = $("compare-tray");
  if (tray) tray.style.display = n > 0 ? "flex" : "none";
  _render_compare_tray();
}

function _render_compare_tray() {
  const el = $("compare-tray-homes");
  if (!el) return;
  el.innerHTML = state.compare.map(id => {
    const l = state.all.find(x => x.id === id);
    if (!l) return "";
    const img = l.images?.[0]
      ? `<img src="${proxy_img(l.images[0])}" referrerpolicy="no-referrer">`
      : `<div class="tray-no-img">🏠</div>`;
    return `<div class="compare-tray-chip">
      ${img}
      <span>${l.address?.split(",")[0] || "Home"}</span>
      <button onclick="toggle_compare('${id}')" title="Remove">✕</button>
    </div>`;
  }).join("");
}

function _get_cached_analysis(id) {
  try {
    const raw = localStorage.getItem(DEEP_DIVE_CACHE_PREFIX + id);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return null;
}

function render_compare() {
  const el = $("compare-content");
  if (!el) return;

  if (state.compare.length === 0) {
    el.innerHTML = `<div class="compare-empty">
      <div class="compare-empty-icon">⇄</div>
      <h3>No homes selected</h3>
      <p>Click the <strong>⇄</strong> button on any listing card to add it here.</p>
    </div>`;
    return;
  }

  if (state.compare.length === 1) {
    el.innerHTML = `<div class="compare-empty">
      <div class="compare-empty-icon">⇄</div>
      <h3>Add one more home</h3>
      <p>Select at least 2 homes to compare side by side.</p>
    </div>`;
    return;
  }

  const homes = state.compare.map(id => state.all.find(l => l.id === id)).filter(Boolean);
  const n = homes.length;

  // Check if we have a cached verdict to show winner badges immediately
  const cache_key = "ai-compare-" + [...state.compare].sort().join("-");
  let cached_verdict = null;
  try { const cv = localStorage.getItem(cache_key); if (cv) cached_verdict = JSON.parse(cv); } catch (_) {}
  const winner_idx = cached_verdict?.winner ? cached_verdict.winner - 1 : -1; // 0-based
  const winner_reason = cached_verdict?.winner_reason || "";

  // ── Home cards ──
  const home_cards = homes.map((l, i) => {
    const imgs = l.images || [];
    const first_img = imgs[0]
      ? `<img class="card-nav-img" src="${proxy_img(imgs[0])}" referrerpolicy="no-referrer" onerror="this.style.display='none'">`
      : `<div class="cmp-no-img">🏠</div>`;
    const imgs_json = JSON.stringify(imgs).replace(/"/g, "&quot;");
    const stats = [
      l.beds  ? `${l.beds} bd` : "",
      l.baths ? `${l.baths} ba` : "",
      l.sqft  ? `${l.sqft.toLocaleString()} sqft` : "",
      l.days_on_market != null ? `${l.days_on_market}d on market` : "",
    ].filter(Boolean).join(" · ");
    const ppsf = l.price && l.sqft ? `$${Math.round(l.price/l.sqft)}/sqft` : "";
    const is_winner = i === winner_idx;
    const winner_badge = is_winner
      ? `<div class="cmp-winner-banner">✦ Best Pick${winner_reason ? ` · ${winner_reason}` : ""}</div>`
      : "";
    return `<div class="cmp-home-card${is_winner ? " cmp-home-card--winner" : ""}">
      <div class="cmp-thumb-strip" data-images="${imgs_json}" data-img-idx="0">
        ${first_img}
        ${_img_nav_html(imgs)}
      </div>
      ${winner_badge}
      <div class="cmp-home-info">
        <div class="cmp-home-price">${fmt_price(l.price)}${ppsf ? `<span class="cmp-ppsf">${ppsf}</span>` : ""}</div>
        <div class="cmp-home-addr">${l.address || ""}${l.city ? ", " + l.city : ""}</div>
        <div class="cmp-home-stats">${stats}</div>
        <div class="cmp-home-meta">
          <span class="source-badge source-${l.source}" style="position:static;display:inline-flex">${source_label(l.source)}</span>
          ${l.url ? `<a class="cmp-view-link" href="${l.url}" target="_blank" rel="noopener">View listing ↗</a>` : ""}
        </div>
        <button class="cmp-remove-btn" onclick="toggle_compare('${l.id}')">✕ Remove</button>
      </div>
    </div>`;
  }).join("");

  el.innerHTML = `
    <div class="compare-page">
      <div class="compare-page-title">⇄ Compare Homes</div>
      <div class="cmp-homes-row" id="cmp-homes-row">${home_cards}</div>
      <div class="cmp-verdict-section" id="cmp-verdict">
        ${_render_verdict_placeholder()}
      </div>
    </div>`;

  // Auto-trigger comparison
  load_ai_verdict();
}

function _render_verdict_placeholder() {
  return `<div class="cmp-verdict-loading">
    <button class="btn-deep-dive" onclick="load_ai_verdict()">✦ Get AI Verdict</button>
    <div class="cmp-verdict-sub">Which home is the best fit? Our AI compares them head-to-head.</div>
  </div>`;
}

async function load_ai_verdict() {
  const verdictEl = $("cmp-verdict");
  if (!verdictEl) return;

  const homes = state.compare.map(id => state.all.find(l => l.id === id)).filter(Boolean);
  const analyses = homes.map(l => _get_cached_analysis(l.id) || l.image_analysis || null);

  // Check cache
  const cache_key = "ai-compare-" + [...state.compare].sort().join("-");
  try {
    const cached = localStorage.getItem(cache_key);
    if (cached) { _render_verdict(JSON.parse(cached), homes); return; }
  } catch (_) {}

  verdictEl.innerHTML = `<div class="deep-dive-loading" style="padding:20px 0">
    <div class="deep-dive-spinner"></div>
    <div class="deep-dive-loading-text">
      <strong>Generating AI verdict…</strong>
      <span>Comparing all ${homes.length} homes head-to-head</span>
    </div>
  </div>`;

  const payload = {
    homes: homes.map(l => ({
      address: [l.address, l.city, l.state].filter(Boolean).join(", "),
      price: l.price,
      beds: l.beds,
      baths: l.baths,
      sqft: l.sqft,
      images: (l.images || []).slice(0, 8),   // send up to 8 photos per home
    })),
  };

  try {
    const res = await fetch("/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const verdict = await res.json();
    try { localStorage.setItem(cache_key, JSON.stringify(verdict)); } catch (_) {}
    _render_verdict(verdict, homes);
  } catch (err) {
    verdictEl.innerHTML = `<div class="deep-dive-error">
      Verdict failed — <button class="btn-link" onclick="load_ai_verdict()">Try again</button>
      <span class="deep-dive-error-msg">${err.message}</span>
    </div>`;
  }
}

const ROOM_COMPARE_ICONS = { Kitchen: "🍳", Bathroom: "🚿", "Living Room": "🛋️" };

function _render_verdict(verdict, homes) {
  const verdictEl = $("cmp-verdict");
  if (!verdictEl) return;

  const cache_key = "ai-compare-" + [...state.compare].sort().join("-");

  // Update home cards to show winner badge (if cards already rendered)
  const winner_idx = verdict.winner ? verdict.winner - 1 : -1;
  const homes_row = $("cmp-homes-row");
  if (homes_row) {
    homes_row.querySelectorAll(".cmp-home-card").forEach((card, i) => {
      const is_winner = i === winner_idx;
      card.classList.toggle("cmp-home-card--winner", is_winner);
      // inject winner banner if not already there
      if (is_winner && !card.querySelector(".cmp-winner-banner")) {
        const banner = document.createElement("div");
        banner.className = "cmp-winner-banner";
        banner.textContent = `✦ Best Pick${verdict.winner_reason ? ` · ${verdict.winner_reason}` : ""}`;
        const strip = card.querySelector(".cmp-thumb-strip");
        if (strip) strip.after(banner);
      }
      // remove stale banner from non-winners
      if (!is_winner) {
        const old = card.querySelector(".cmp-winner-banner");
        if (old) old.remove();
      }
    });
  }

  const cmp = verdict.comparisons || {};
  const room_rows = [
    ["Kitchen",     cmp.kitchen],
    ["Bathroom",    cmp.bathroom],
    ["Living Room", cmp.living_room],
  ].filter(([, v]) => v).map(([label, text]) => {
    const icon = ROOM_COMPARE_ICONS[label] || "";
    return `<div class="cmp-room-row">
      <span class="cmp-room-row-label">${icon} ${label}</span>
      <span class="cmp-room-row-text">${text}</span>
    </div>`;
  }).join("");

  const confidence_html = verdict.confidence_note
    ? `<div class="cmp-confidence-note">ℹ ${verdict.confidence_note}</div>` : "";

  const winner_home = winner_idx >= 0 ? homes[winner_idx] : null;
  const winner_label = winner_home
    ? `Home ${verdict.winner} · ${winner_home.address || ""}`.trim().replace(/·\s*$/, "")
    : "";

  verdictEl.innerHTML = `<div class="cmp-verdict-card">
    <div class="cmp-verdict-header">
      <span>✦ Visual Comparison</span>
      ${winner_label ? `<span class="cmp-verdict-winner-chip">Best Pick: ${winner_label}</span>` : ""}
    </div>
    <blockquote class="cmp-verdict-overall">${verdict.overall_take || ""}</blockquote>
    ${room_rows ? `<div class="cmp-room-rows">${room_rows}</div>` : ""}
    ${verdict.market_read ? `<p class="cmp-market-read">📊 ${verdict.market_read}</p>` : ""}
    ${confidence_html}
    <div class="dd-footer">
      <button class="btn-link" onclick="localStorage.removeItem('${cache_key}');load_ai_verdict()">Re-analyze</button>
    </div>
  </div>`;
}

async function run_compare_dives() {
  const missing = state.compare
    .map(id => state.all.find(l => l.id === id))
    .filter(l => l && !(_get_cached_analysis(l.id)?.rooms?.length));

  await Promise.all(missing.map(l => run_deep_dive(l.id)));
  render_compare(); // re-render with new data
}

async function run_compare_dive(id) {
  await run_deep_dive(id);
  render_compare();
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

  grid.innerHTML = page_listings.map((l, i) => card_html(l, i)).join("");

  // Attach click + touch-swipe handlers
  grid.querySelectorAll(".listing-card").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = +el.dataset.idx;
      open_modal(state.filtered[idx], state.filtered, idx);
    });
    // Touch swipe on card image
    const card_img_wrap = el.querySelector(".card-image");
    if (card_img_wrap) _wire_card_touch(card_img_wrap);
  });

  wrap.style.display = page_listings.length < state.filtered.length ? "block" : "none";
}


// ── Image nav (listing cards + compare cards) ─────────
// State: card image index stored on the DOM element as dataset.imgIdx
function _nav_img(el, dir) {
  // el = the .card-image or .cmp-thumb-nav wrapper
  const imgs = JSON.parse(el.dataset.images || "[]");
  if (imgs.length < 2) return;
  let idx = parseInt(el.dataset.imgIdx || "0") + dir;
  if (idx < 0) idx = imgs.length - 1;
  if (idx >= imgs.length) idx = 0;
  el.dataset.imgIdx = idx;
  const img = el.querySelector("img.card-nav-img");
  if (img) {
    img.src = proxy_img(imgs[idx]);
    const dot_wrap = el.querySelector(".card-nav-dots");
    if (dot_wrap) {
      dot_wrap.querySelectorAll(".card-nav-dot").forEach((d, i) =>
        d.classList.toggle("active", i === idx)
      );
    }
  }
}

function _wire_card_touch(el) {
  let _tx = null;
  el.addEventListener("touchstart", (e) => { _tx = e.touches[0].clientX; }, { passive: true });
  el.addEventListener("touchend", (e) => {
    if (_tx === null) return;
    const dx = e.changedTouches[0].clientX - _tx;
    _tx = null;
    if (Math.abs(dx) < 30) return; // not a swipe
    e.stopPropagation(); // don't open modal on swipe
    _nav_img(el, dx < 0 ? 1 : -1);
  });
}

function _img_nav_html(images) {
  if (!images || images.length < 2) return "";
  return `<button class="card-nav-btn card-nav-prev" onclick="event.stopPropagation();_nav_img(this.closest('[data-images]'),-1)">&#8249;</button>
          <button class="card-nav-btn card-nav-next" onclick="event.stopPropagation();_nav_img(this.closest('[data-images]'),1)">&#8250;</button>
          <div class="card-nav-dots">${images.map((_, i) =>
            `<span class="card-nav-dot${i === 0 ? " active" : ""}"></span>`
          ).join("")}</div>`;
}

function card_html(listing, idx) {
  const imgs = listing.images || [];
  const img_html = imgs.length
    ? `<img class="card-nav-img" src="${proxy_img(imgs[0] || '')}" alt="Property photo" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.innerHTML='<div class=no-photo>🏠</div>'">`
    : `<div class="no-photo">🏠</div>`;

  const is_saved = state.saved.has(listing.id);
  const save_btn = `<button class="save-btn${is_saved ? " saved" : ""}" data-id="${listing.id}" onclick="event.stopPropagation();toggle_save('${listing.id}')" title="${is_saved ? "Remove from saved" : "Save listing"}">${is_saved ? "♥" : "♡"}</button>`;
  const is_comparing = state.compare.includes(listing.id);
  const compare_btn = `<button class="btn-compare-card${is_comparing ? " compare-active" : ""}" data-compare-id="${listing.id}" onclick="event.stopPropagation();toggle_compare('${listing.id}')" title="${is_comparing ? "Remove from compare" : "Add to compare"}">${is_comparing ? "⇄ Added" : "⇄ Compare"}</button>`;

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

  const match_inline = (match_score != null && match_score >= 40)
    ? `<span class="card-match-inline${match_score >= 70 ? "" : match_score >= 40 ? " amber" : " gray"}">✨ ${match_score}%</span>`
    : "";

  const imgs_json = JSON.stringify(imgs).replace(/"/g, "&quot;");
  return `
    <div class="listing-card" data-idx="${idx}">
      <div class="card-image" data-images="${imgs_json}" data-img-idx="0">
        ${img_html}
        ${_img_nav_html(imgs)}
        <span class="source-badge source-${listing.source}">${source_label(listing.source)}</span>
        ${lux_badge}
        ${match_badge_html}
        ${save_btn}
        ${compare_btn}
      </div>
      <div class="card-body">
        <div class="card-price-row">
          <div class="card-price">${fmt_price(listing.price)}${match_inline}</div>
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
    ? `<img src="${proxy_img(l.images[0]||'')}" style="width:100%;height:100px;object-fit:cover;border-radius:6px;margin-bottom:8px" loading="lazy" referrerpolicy="no-referrer">`
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


// ── Carousel state ────────────────────────────────────
let _carousel_photos = [];
let _carousel_idx    = 0;
let _carousel_touch_x = null;

function carousel_html(photos, idx) {
  if (!photos.length) return `<div class="modal-no-img">🏠</div>`;
  const total = photos.length;
  const src   = photos[idx];
  // Dots: show up to 15; beyond that just show counter
  const show_dots = total <= 15;
  const dots = show_dots
    ? `<div class="carousel-dots">${photos.map((_, i) =>
        `<button class="carousel-dot${i === idx ? " active" : ""}" onclick="event.stopPropagation();go_to_photo(${i})"></button>`
      ).join("")}</div>`
    : "";
  const arrows = total > 1 ? `
    <button class="carousel-btn carousel-prev" onclick="event.stopPropagation();prev_photo()" aria-label="Previous photo">&#8249;</button>
    <button class="carousel-btn carousel-next" onclick="event.stopPropagation();next_photo()" aria-label="Next photo">&#8250;</button>` : "";
  const counter = total > 1
    ? `<div class="carousel-counter">${idx + 1} / ${total}</div>` : "";
  const clean_src = proxy_img(src);
  return `
    <div class="carousel-wrap" id="modal-carousel" onclick="next_photo()">
      <img class="carousel-img" id="carousel-img"
           src="${clean_src}"
           alt="Photo ${idx + 1} of ${total}"
           referrerpolicy="no-referrer"
           onerror="this.style.display='none';document.getElementById('carousel-fallback')?.style.removeProperty('display')">
      <div id="carousel-fallback" class="no-photo" style="display:none;height:100%;font-size:64px;background:#1e293b">🏠</div>
      ${arrows}
      ${counter}
      ${dots}
    </div>`;
}

function update_carousel() {
  const wrap = $("modal-carousel");
  if (!wrap) return;
  wrap.outerHTML = carousel_html(_carousel_photos, _carousel_idx);
  // Re-wire touch events after replacing DOM
  wire_carousel_touch();
}

function next_photo() {
  if (!_carousel_photos.length) return;
  _carousel_idx = (_carousel_idx + 1) % _carousel_photos.length;
  update_carousel();
}

function prev_photo() {
  if (!_carousel_photos.length) return;
  _carousel_idx = (_carousel_idx - 1 + _carousel_photos.length) % _carousel_photos.length;
  update_carousel();
}

function go_to_photo(i) {
  _carousel_idx = i;
  update_carousel();
}

function wire_carousel_touch() {
  const wrap = $("modal-carousel");
  if (!wrap) return;
  wrap.addEventListener("touchstart", (e) => {
    _carousel_touch_x = e.touches[0].clientX;
  }, { passive: true });
  wrap.addEventListener("touchend", (e) => {
    if (_carousel_touch_x === null) return;
    const dx = e.changedTouches[0].clientX - _carousel_touch_x;
    _carousel_touch_x = null;
    if (dx < -40) next_photo();
    else if (dx > 40) prev_photo();
  });
}

// ── AI Deep Dive ─────────────────────────────────────

const ROOM_ICONS = {
  kitchen: "🍳", living_room: "🛋", master_bedroom: "🛏", bedroom: "🛏",
  master_bathroom: "🚿", bathroom: "🚿", dining_room: "🍽", backyard: "🌿",
  garage: "🚗", basement: "⬇", exterior: "🏠", other: "📷"
};

function _score_bar(label, value, color) {
  if (value == null) return "";
  const pct = Math.round((value / 10) * 100);
  return `<div class="dd-score-row">
    <span class="dd-score-label">${label}</span>
    <div class="dd-score-track"><div class="dd-score-fill" style="width:${pct}%;background:${color}"></div></div>
    <span class="dd-score-val">${value}</span>
  </div>`;
}

function _toggle_coll(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle("coll-collapsed");
  try { localStorage.setItem("coll-" + id, el.classList.contains("coll-collapsed") ? "1" : "0"); } catch (_) {}
}

function _init_coll(id, default_collapsed) {
  let saved = null;
  try { saved = localStorage.getItem("coll-" + id); } catch (_) {}
  const should_collapse = saved !== null ? saved === "1" : default_collapsed;
  if (should_collapse) document.getElementById(id)?.classList.add("coll-collapsed");
}

function _toggle_dd_summary(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const btn = el.nextElementSibling;
  if (el.dataset.exp) {
    el.textContent = el.dataset.short;
    btn.textContent = "Read more";
    delete el.dataset.exp;
  } else {
    el.textContent = el.dataset.full;
    btn.textContent = "Show less";
    el.dataset.exp = "1";
  }
}

function _render_room_cards(analysis, listing_images) {
  return analysis.rooms.map(r => {
    const label = (r.room_type || "room").replace(/_/g, " ");
    const icon  = ROOM_ICONS[r.room_type] || "📷";
    const idx = (r.image_index || 1) - 1;
    const img_src = r.image_url || (listing_images && listing_images[idx]) || "";

    // Composite score: average of available sub-scores
    const raw_scores = [r.modernity_score, r.luxury_score, r.condition_score].filter(s => s != null);
    const composite = raw_scores.length
      ? Math.round((raw_scores.reduce((a, b) => a + b, 0) / raw_scores.length) * 10) / 10
      : null;
    const score_color = composite >= 7 ? "#10b981" : composite >= 5 ? "#f59e0b" : "#ef4444";
    const score_badge = composite != null
      ? `<span class="dd-room-score" style="background:${score_color}">${composite}</span>`
      : "";

    const img_html = img_src
      ? `<div class="dd-room-img-wrap">
           <img src="${proxy_img(img_src)}" alt="${label}" loading="lazy" referrerpolicy="no-referrer"
             onerror="this.closest('.dd-room-img-wrap').style.display='none'">
           <span class="dd-room-badge">${icon} ${label}</span>
           ${score_badge}
         </div>`
      : `<div class="dd-room-no-img"><span>${icon} ${label}</span></div>`;

    const insight_html = r.insight
      ? `<p class="dd-room-insight">${r.insight}</p>`
      : "";

    return `<div class="dd-room-card">
      ${img_html}
      ${insight_html ? `<div class="dd-room-body">${insight_html}</div>` : ""}
    </div>`;
  }).join("");
}

// ── Offer Strategy ───────────────────────────────────────────────────────────

function build_offer_strategy_section(listing) {
  const analysis = _get_cached_analysis(listing.id);
  if (!analysis?.rooms?.length) return "";

  const section_id = "offer-strategy-section-" + listing.id;
  let cached = null;
  try { cached = JSON.parse(localStorage.getItem("ai-offer-strategy-v1-" + listing.id)); } catch (_) {}

  const inner = cached
    ? "" // filled by _render_offer_strategy after DOM is ready
    : `<div class="os-cta">
        <button class="btn-offer-strategy" onclick="run_offer_strategy('${listing.id}')">✦ Get Offer Strategy</button>
        <div class="os-cta-sub">AI-powered negotiation guidance based on this home's photos, condition scores, and local market data.</div>
      </div>`;

  return `<div class="detail-section" id="${section_id}">${inner}</div>`;
}

function _render_offer_strategy(result, listing, section) {
  if (!section) return;
  const low = result.range_low || 0;
  const high = result.range_high || 0;
  const range_html = low && high
    ? `<div class="os-range">
        <span class="os-range-label">Suggested Range</span>
        <span class="os-range-values">${fmt_price(low)} – ${fmt_price(high)}</span>
        ${result.pct_below_low != null ? `<span class="os-range-pct">${result.pct_below_low}–${result.pct_below_high}% below ask</span>` : ""}
      </div>`
    : "";

  const bullets = (result.why_bullets || []).map(b =>
    `<li class="os-bullet">${b}</li>`
  ).join("");

  const confidence_html = result.confidence !== "high" && result.confidence_note
    ? `<div class="cmp-confidence-note">ℹ ${result.confidence_note}</div>` : "";

  const cache_key = "ai-offer-strategy-v1-" + listing.id;
  const os_coll_id = "coll-os-" + listing.id;

  section.innerHTML = `<div class="os-card coll-section" id="${os_coll_id}">
    <div class="os-header coll-trigger" onclick="_toggle_coll('${os_coll_id}')">
      ✦ Offer Strategy <span class="coll-chevron">⌄</span>
    </div>
    <div class="coll-body"><div class="coll-body-inner">
      ${range_html}
      ${bullets ? `<ul class="os-bullets">${bullets}</ul>` : ""}
      ${result.tactic ? `<p class="os-tactic">${result.tactic}</p>` : ""}
      ${result.one_risk ? `<div class="os-risk">⚠ ${result.one_risk}</div>` : ""}
      ${confidence_html}
      <div class="os-footer">
        <span class="os-disclaimer">AI analysis only — verify comps with your agent.</span>
        <button class="btn-link" onclick="localStorage.removeItem('${cache_key}');run_offer_strategy('${listing.id}')">Re-analyze ↺</button>
      </div>
    </div></div>
  </div>`;
  _init_coll(os_coll_id, false);
}

async function run_offer_strategy(listingId) {
  const listing = state.all.find(l => l.id === listingId);
  if (!listing) return;

  const analysis = _get_cached_analysis(listingId);
  if (!analysis?.rooms?.length) return;

  const section = document.getElementById("offer-strategy-section-" + listingId);
  if (!section) return;

  section.innerHTML = `<div class="deep-dive-loading">
    <div class="deep-dive-spinner"></div>
    <div class="deep-dive-loading-text">
      <strong>Generating offer strategy…</strong>
      <span>Analyzing condition scores, price position, and local market data</span>
    </div>
  </div>`;

  // Pre-compute ZIP stats client-side so server gets live market context
  const zip = listing.zip;
  const peers = state.all.filter(l => l.zip === zip && l.price > 50000 && l.sqft > 0 && l.id !== listingId);
  const ppsf_vals = peers.map(l => l.price / l.sqft).sort((a, b) => a - b);
  const median_ppsf = ppsf_vals.length ? ppsf_vals[Math.floor(ppsf_vals.length / 2)] : null;
  const dom_vals = peers.filter(l => l.days_on_market != null).map(l => l.days_on_market);
  const avg_dom = dom_vals.length ? Math.round(dom_vals.reduce((s, v) => s + v, 0) / dom_vals.length) : null;

  const payload = {
    listing_id: listingId,
    analysis: {
      overall_score: analysis.overall_score,
      rooms: analysis.rooms,
      red_flags: analysis.red_flags || [],
      hidden_value: analysis.hidden_value || [],
    },
    listing: {
      price: listing.price,
      address: listing.address,
      city: listing.city,
      state: listing.state,
      zip: listing.zip,
      beds: listing.beds,
      baths: listing.baths,
      sqft: listing.sqft,
      days_on_market: listing.days_on_market,
      description: (listing.description || "").slice(0, 600),
      features: listing.features || [],
    },
    zip_stats: { median_ppsf, avg_dom, peer_count: peers.length },
    buyer_profile: state.quiz.completed ? state.quiz : null,
  };

  try {
    const res = await fetch("/offer-strategy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();
    try { localStorage.setItem("ai-offer-strategy-v1-" + listingId, JSON.stringify(result)); } catch (_) {}
    _render_offer_strategy(result, listing, section);
  } catch (err) {
    section.innerHTML = `<div class="deep-dive-error">
      Strategy failed — <button class="btn-link" onclick="run_offer_strategy('${listingId}')">Try again</button>
      <span class="deep-dive-error-msg">${err.message}</span>
    </div>`;
  }
}

function build_ai_section(listing) {
  // Prefer cached deep-dive result (has red_flags / hidden_value)
  let analysis = null;
  try {
    const raw = localStorage.getItem(DEEP_DIVE_CACHE_PREFIX + listing.id);
    if (raw) analysis = JSON.parse(raw);
  } catch (_) {}
  analysis = analysis || listing.image_analysis || null;

  const has_images = (listing.images?.length || 0) > 0;

  // No analysis — show CTA
  if (!analysis?.rooms?.length) {
    if (!has_images) return "";
    return `<div class="dd-section" id="ai-section-${listing.id}">
      <div class="dd-cta-wrap">
        <div class="dd-cta-icon">✦</div>
        <div class="dd-cta-text">
          <strong>Deep Insight</strong>
          <span>Analyze every photo + listing description for red flags, hidden value &amp; room-by-room scores</span>
        </div>
        <button class="btn-deep-dive" onclick="run_deep_dive('${listing.id}')">Analyze</button>
      </div>
    </div>`;
  }

  const is_deep_dive = analysis.backend === "claude-realtime";
  const score = analysis.overall_score;

  // Score badge color
  const score_color = score >= 8 ? "#10b981" : score >= 6 ? "#f59e0b" : "#ef4444";

  // Summary — bullet format (new) or prose fallback (legacy cache)
  let summary_html = "";
  if (analysis.summary) {
    const full = analysis.summary;
    if (full.includes("• ")) {
      // New bullet format
      const bullets = full.split(/\n/).map(s => s.replace(/^•\s*/, "").trim()).filter(Boolean);
      summary_html = `<div class="dd-summary-wrap">
        <ul class="dd-summary-bullets">
          ${bullets.map(b => `<li>${b}</li>`).join("")}
        </ul>
      </div>`;
    } else {
      // Legacy prose: show first 2 sentences with "Read more"
      const sentences = full.match(/[^.!?]+[.!?]+/g) || [full];
      const short = sentences.slice(0, 2).join(" ").trim();
      const sum_id = "dd-sum-" + listing.id;
      if (sentences.length > 2 && short.length < full.length - 15) {
        summary_html = `<div class="dd-summary-wrap">
          <p class="dd-summary-text" id="${sum_id}"
             data-short="${short.replace(/"/g,'&quot;')}"
             data-full="${full.replace(/"/g,'&quot;')}">${short}</p>
          <button class="dd-summary-toggle" onclick="_toggle_dd_summary('${sum_id}')">Read more</button>
        </div>`;
      } else {
        summary_html = `<div class="dd-summary-wrap"><p class="dd-summary-text">${full}</p></div>`;
      }
    }
  }

  // Room cards
  const room_cards = _render_room_cards(analysis, listing.images || []);

  // Red flags
  let flags_html = "";
  if (analysis.red_flags?.length) {
    const items = analysis.red_flags.map(f =>
      `<div class="dd-flag-item"><span class="dd-flag-icon">⚠</span><span>${f}</span></div>`
    ).join("");
    flags_html = `<div class="dd-alert dd-alert-red">
      <div class="dd-alert-title">Things to Ask About</div>
      <div class="dd-alert-items">${items}</div>
    </div>`;
  }

  // Hidden value
  let value_html = "";
  if (analysis.hidden_value?.length) {
    const items = analysis.hidden_value.map(v =>
      `<div class="dd-value-item"><span class="dd-value-icon">✦</span><span>${v}</span></div>`
    ).join("");
    value_html = `<div class="dd-alert dd-alert-green">
      <div class="dd-alert-title">Hidden Value</div>
      <div class="dd-alert-items">${items}</div>
    </div>`;
  }

  // Footer
  let footer_html = "";
  if (is_deep_dive && analysis.analyzed_at) {
    const ago = _time_ago(analysis.analyzed_at);
    footer_html = `<div class="dd-footer">Analyzed ${ago} · <button class="btn-link" onclick="run_deep_dive('${listing.id}', true)">Re-analyze</button></div>`;
  } else if (!is_deep_dive && has_images) {
    footer_html = `<div class="dd-upgrade-cta">
      <button class="btn-deep-dive btn-deep-dive-sm" onclick="run_deep_dive('${listing.id}')">
        ✦ Deep Insight — Red Flags &amp; Hidden Value
      </button>
    </div>`;
  }

  const coll_id = "ai-section-" + listing.id;
  return `<div class="dd-section coll-section" id="${coll_id}">
    <div class="dd-header coll-trigger" onclick="_toggle_coll('${coll_id}')">
      <div class="dd-header-title">✦ Deep Insight</div>
      <div style="display:flex;align-items:center;gap:8px">
        ${score != null ? `<div class="dd-overall-score" style="background:${score_color}">${score}<span>/10</span></div>` : ""}
        <span class="coll-chevron">⌄</span>
      </div>
    </div>
    <div class="coll-body"><div class="coll-body-inner">
      ${summary_html}
      <div class="dd-rooms-scroll">${room_cards}</div>
      <div class="dd-alerts-row">${flags_html}${value_html}</div>
      ${footer_html}
    </div></div>
  </div>`;
}

function _merge_deep_dive_results(results) {
  const valid = results.filter(r => r?.rooms?.length);
  if (!valid.length) throw new Error("All batches returned no rooms");

  // Combine rooms from all batches (image_url already correct per-batch)
  const rooms = valid.flatMap(r => r.rooms || []);

  // Average overall score across batches
  const scores = valid.map(r => r.overall_score).filter(s => s != null);
  const overall_score = scores.length
    ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10
    : null;

  // Merge summaries (one sentence per batch, joined)
  const summary = valid.map(r => r.summary).filter(Boolean).join(" ");

  // Combine red_flags and hidden_value, dedupe, cap at 5 each
  const red_flags   = [...new Set(valid.flatMap(r => r.red_flags   || []))].slice(0, 5);
  const hidden_value = [...new Set(valid.flatMap(r => r.hidden_value || []))].slice(0, 5);

  return {
    rooms,
    overall_score,
    summary,
    red_flags,
    hidden_value,
    analyzed_at: new Date().toISOString(),
    backend: "claude-realtime",
  };
}

async function run_deep_dive(listingId, force = false) {
  const listing = state.all.find(l => l.id === listingId);
  if (!listing) return;

  const section = document.getElementById(`ai-section-${listingId}`);
  if (!section) return;

  // Serve from cache unless force refresh
  if (!force) {
    try {
      const raw = localStorage.getItem(DEEP_DIVE_CACHE_PREFIX + listingId);
      if (raw) {
        const tmp = document.createElement("div");
        tmp.innerHTML = build_ai_section(listing);
        section.replaceWith(tmp.firstElementChild || section);
        return;
      }
    } catch (_) {}
  }

  // Build image chunks (15 per batch, up to 3 parallel calls)
  const all_images = listing.images || [];
  const chunks = [];
  for (let i = 0; i < all_images.length && chunks.length < DEEP_DIVE_MAX_CHUNKS; i += DEEP_DIVE_CHUNK_SIZE) {
    chunks.push(all_images.slice(i, i + DEEP_DIVE_CHUNK_SIZE));
  }
  const total_images = chunks.reduce((s, c) => s + c.length, 0);

  // Show animated progress bar loading state
  section.innerHTML = `
    <div class="di-progress-wrap" id="di-progress-${listingId}">
      <div class="di-progress-header">
        <span class="di-progress-icon">✦</span>
        <span class="di-progress-title">Deep Insight</span>
        <span class="di-progress-count">${total_images} photos</span>
      </div>
      <div class="di-progress-bar-track">
        <div class="di-progress-bar-fill" id="di-bar-${listingId}"></div>
      </div>
      <div class="di-progress-msg" id="di-msg-${listingId}">Scanning every room for finish quality…</div>
    </div>`;

  // Animate the progress bar with cycling messages
  const _di_messages = [
    "Scanning every room for finish quality…",
    "Identifying appliances, fixtures & materials…",
    "Looking for hidden value opportunities…",
    "Checking for red flags & condition issues…",
    "Evaluating luxury features & craftsmanship…",
    "Comparing against Cincinnati market standards…",
    "Building your personalized home report…",
  ];
  let _di_pct = 0;
  let _di_msg_idx = 0;
  const _di_bar = document.getElementById(`di-bar-${listingId}`);
  const _di_msg_el = document.getElementById(`di-msg-${listingId}`);
  const _di_interval = setInterval(() => {
    _di_pct = Math.min(_di_pct + (Math.random() * 4 + 2), 90); // never reaches 100 on its own
    if (_di_bar) _di_bar.style.width = _di_pct + "%";
    _di_msg_idx = Math.floor(_di_pct / (90 / _di_messages.length));
    if (_di_msg_el) _di_msg_el.textContent = _di_messages[Math.min(_di_msg_idx, _di_messages.length - 1)];
  }, 1200);

  const base_payload = {
    listing_id: listing.id,
    description: listing.description || "",
    features: listing.features || [],
    price: listing.price,
    address: [listing.address, listing.city, listing.state, listing.zip].filter(Boolean).join(", "),
    beds: listing.beds,
    baths: listing.baths,
    sqft: listing.sqft,
  };

  try {
    // Fire all chunks in parallel
    const results = await Promise.all(chunks.map(imgs =>
      fetch(DEEP_DIVE_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...base_payload, images: imgs }),
      }).then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.error || `HTTP ${r.status}`); }))
    ));

    // Complete the bar
    clearInterval(_di_interval);
    if (_di_bar) _di_bar.style.width = "100%";
    if (_di_msg_el) _di_msg_el.textContent = "Analysis complete!";

    // Small pause so user sees the 100% state
    await new Promise(r => setTimeout(r, 400));

    // Merge all results into one analysis object
    const analysis = _merge_deep_dive_results(results);

    // Cache and render
    try { localStorage.setItem(DEEP_DIVE_CACHE_PREFIX + listingId, JSON.stringify(analysis)); } catch (_) {}

    const tmp = document.createElement("div");
    tmp.innerHTML = build_ai_section(listing);
    const new_ai_section = tmp.firstElementChild;
    section.replaceWith(new_ai_section);

    // Inject / refresh the Offer Strategy section immediately after Deep Insight
    const existing_os = document.getElementById("offer-strategy-section-" + listingId);
    const os_html = build_offer_strategy_section(listing);
    if (os_html) {
      if (existing_os) {
        // Already in DOM — replace with fresh CTA (clears any stale cached render)
        const os_tmp = document.createElement("div");
        os_tmp.innerHTML = os_html;
        existing_os.replaceWith(os_tmp.firstElementChild);
      } else {
        // Not in DOM yet — insert right after the AI section
        new_ai_section.insertAdjacentHTML("afterend", os_html);
      }
    }

  } catch (err) {
    clearInterval(_di_interval);
    section.innerHTML = `
      <div class="deep-dive-error">
        Analysis failed — <button class="btn-link" onclick="run_deep_dive('${listingId}')">Try again</button>
        <span class="deep-dive-error-msg">${err.message}</span>
      </div>`;
  }
}

function _time_ago(iso) {
  const diff = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// ── Modal ─────────────────────────────────────────────
function open_modal(listing, navList, navIdx) {
  // Store navigation context
  state.modal_nav = {
    list: navList || state.filtered,
    idx:  navIdx  ?? (navList || state.filtered).findIndex(l => l.id === listing.id),
  };

  const content = $("modal-content");

  // ── Photo carousel ──
  _carousel_photos = listing.images?.length ? listing.images : [];
  _carousel_idx    = 0;
  const photo_strip = carousel_html(_carousel_photos, 0);

  // ── Stats ──
  const stat_items = [
    listing.beds  != null && `<span class="detail-stat-item">🛏 <strong>${fmt_num(listing.beds)}</strong> bd</span>`,
    listing.baths != null && `<span class="detail-stat-item">🛁 <strong>${fmt_num(listing.baths)}</strong> ba</span>`,
    listing.sqft  != null && `<span class="detail-stat-item">📐 <strong>${fmt_num(listing.sqft)}</strong> sqft</span>`,
    listing.lot_size != null && `<span class="detail-stat-item">🌿 <strong>${fmt_num(listing.lot_size)}</strong> sqft lot</span>`,
    listing.days_on_market != null && `<span class="detail-stat-item">📅 <strong>${listing.days_on_market}d</strong> on market</span>`,
  ].filter(Boolean).join("");

  // ── Match section ──
  const match_score = compute_match_score(listing, state.quiz);
  const breakdown   = compute_match_breakdown(listing, state.quiz);
  let match_section = "";
  if (match_score != null && breakdown) {
    const score_cls = match_score >= 70 ? "green" : match_score >= 40 ? "amber" : "gray";
    const bd_rows = [];
    if (breakdown.budget) {
      const icon = breakdown.budget.status === "match" ? "✓" : breakdown.budget.status === "miss" ? "✗" : "~";
      bd_rows.push(`<div class="bd-row bd-${breakdown.budget.status}"><span class="bd-icon">${icon}</span><span class="bd-cat">Budget</span><span class="bd-note">${breakdown.budget.label}</span></div>`);
    }
    if (breakdown.style) {
      const icon = breakdown.style.status === "match" ? "✓" : breakdown.style.status === "miss" ? "✗" : "~";
      bd_rows.push(`<div class="bd-row bd-${breakdown.style.status}"><span class="bd-icon">${icon}</span><span class="bd-cat">Style</span><span class="bd-note">${breakdown.style.label}</span></div>`);
    }
    breakdown.features.forEach(f => {
      bd_rows.push(`<div class="bd-row bd-${f.matched ? "match" : "miss"}"><span class="bd-icon">${f.matched ? "✓" : "✗"}</span><span class="bd-note">${f.label}</span></div>`);
    });
    match_section = `
      <div class="detail-section">
        <div class="detail-section-label">Match Score</div>
        <div class="detail-match-row">
          <div class="detail-match-score ${score_cls}">${match_score}%</div>
          <div class="detail-match-bd" style="background:rgba(15,23,42,.88);border-radius:10px;padding:8px 12px">
            ${bd_rows.join("")}
          </div>
        </div>
      </div>`;
  }

  // ── Features ──
  const all_features = listing.features || [];
  const all_keywords = listing.keywords || [];
  const features_section = (all_features.length || all_keywords.length)
    ? `<div class="detail-section">
         <div class="detail-section-label">Features</div>
         <div class="detail-features-grid">
           ${all_features.map(f => `<span class="detail-feature-tag">${feature_label(f)}</span>`).join("")}
           ${all_keywords.map(k => `<span class="modal-keyword-tag">${k}</span>`).join("")}
         </div>
       </div>`
    : "";

  // ── Description ──
  const desc_coll_id = "coll-desc-" + listing.id;
  const desc_section = listing.description
    ? `<div class="detail-section coll-section" id="${desc_coll_id}">
         <button class="detail-section-label coll-trigger-plain" onclick="_toggle_coll('${desc_coll_id}')">
           About this home <span class="coll-chevron coll-chevron-dark">⌄</span>
         </button>
         <div class="coll-body"><div class="coll-body-inner">
           <p class="detail-desc">${listing.description}</p>
         </div></div>
       </div>`
    : "";

  // ── AI Deep Dive section ──
  const ai_section = build_ai_section(listing);
  const offer_strategy_section = build_offer_strategy_section(listing);

  // ── Meta info row ──
  const meta_parts = [
    listing.property_type && `<strong>Type:</strong> ${listing.property_type}`,
    listing.zip && `<strong>ZIP:</strong> ${listing.zip}`,
    `<strong>Source:</strong> <span class="source-badge source-${listing.source}" style="position:static;display:inline">${source_label(listing.source)}</span>`,
  ].filter(Boolean).join("  ·  ");

  // ── Action buttons ──
  const save_active = state.saved.has(listing.id);
  const actions = `
    <div class="detail-actions">
      ${listing.url ? `<a class="btn-primary" href="${listing.url}" target="_blank" rel="noopener">View on ${source_label(listing.source)} ↗</a>` : ""}
      <button class="btn-secondary save-btn-modal${save_active ? " saved" : ""}" onclick="toggle_save('${listing.id}');this.textContent=state.saved.has('${listing.id}') ? '♥ Saved' : '♡ Save';this.classList.toggle('saved',state.saved.has('${listing.id}'))">${save_active ? "♥ Saved" : "♡ Save"}</button>
      <button class="btn-secondary btn-compare-modal${state.compare.includes(listing.id) ? " compare-active" : ""}" data-compare-id="${listing.id}" onclick="toggle_compare('${listing.id}');this.textContent=state.compare.includes('${listing.id}') ? '⇄ Added' : '⇄ Compare';this.classList.toggle('compare-active',state.compare.includes('${listing.id}'))">${state.compare.includes(listing.id) ? "⇄ Added" : "⇄ Compare"}</button>
      <button class="btn-secondary" onclick="if(navigator.clipboard)navigator.clipboard.writeText(window.location.href).then(()=>{this.textContent='✓ Copied';setTimeout(()=>this.textContent='⎘ Share',2000)})">⎘ Share</button>
    </div>`;

  const mortgage_section = _mortgage_calc_html(listing);

  content.innerHTML = `
    ${photo_strip}
    <div class="modal-body">
      <div class="detail-section">
        <div class="detail-header-row">
          <div class="detail-price">${fmt_price(listing.price)}</div>
          ${(() => { const s = status_label(listing.status); return s ? `<span class="status-badge ${s.cls}">${s.text}</span>` : ""; })()}
        </div>
        <div class="detail-address">${listing.address || ""}${listing.city ? ", " + listing.city : ""}${listing.state ? ", " + listing.state : ""}${listing.zip ? " " + listing.zip : ""}</div>
        <div class="detail-stats-row">${stat_items || '<span style="color:#9ca3af">Details unavailable</span>'}</div>
        ${meta_parts ? `<div class="modal-desc" style="margin-top:10px;font-size:13px">${meta_parts}</div>` : ""}
      </div>
      ${mortgage_section}
      ${match_section}
      ${features_section}
      ${desc_section}
      ${ai_section}
      ${offer_strategy_section}
      <div class="detail-section">${actions}</div>
    </div>`;

  // Render cached offer strategy immediately if available
  const _os_el = document.getElementById("offer-strategy-section-" + listing.id);
  if (_os_el) {
    let _os_cached = null;
    try { _os_cached = JSON.parse(localStorage.getItem("ai-offer-strategy-v1-" + listing.id)); } catch (_) {}
    if (_os_cached) _render_offer_strategy(_os_cached, listing, _os_el);
  }

  // Restore collapsible states (description starts collapsed by default)
  _init_coll("coll-desc-" + listing.id, true);
  _init_coll("ai-section-" + listing.id, false);

  // Update prev/next nav bar
  const { idx: _nIdx, list: _nList } = state.modal_nav;
  const _prevBtn = $("modal-prev"), _nextBtn = $("modal-next"), _counter = $("modal-nav-counter");
  if (_counter) _counter.textContent = `${_nIdx + 1} / ${_nList.length}`;
  if (_prevBtn) _prevBtn.disabled = _nIdx === 0;
  if (_nextBtn) _nextBtn.disabled = _nIdx === _nList.length - 1;

  // Initialize mortgage calculator
  update_mortgage(listing.id, listing.price);

  $("modal-overlay").style.display = "flex";
  document.body.style.overflow = "hidden";
  // Wire touch + keyboard for carousel
  wire_carousel_touch();
}

function open_lightbox(src) {
  const el = document.createElement("div");
  el.className = "lightbox-overlay";
  el.innerHTML = `<img src="${src}" alt="Photo">`;
  el.addEventListener("click", () => el.remove());
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { el.remove(); document.removeEventListener("keydown", esc); }
  });
  document.body.appendChild(el);
}

function close_modal() {
  $("modal-overlay").style.display = "none";
  document.body.style.overflow = "";
}

// ── Modal listing navigation ──────────────────────────
function modal_nav(dir) {
  const { list, idx } = state.modal_nav;
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= list.length) return;
  open_modal(list[newIdx], list, newIdx);
}

// ── Mortgage Calculator ───────────────────────────────
function _mortgage_calc_html(listing) {
  const price = listing.price || 0;
  if (!price || price < 50000) return ""; // skip commercial/land
  const down = +(localStorage.getItem("mtg-down") || 20);
  const rate = +(localStorage.getItem("mtg-rate") || 7.0);
  const term = +(localStorage.getItem("mtg-term") || 30);
  return `<div class="detail-section">
    <div class="detail-section-label">Mortgage Estimator</div>
    <div class="mtg-calc">
      <div class="mtg-result" id="mtg-result-${listing.id}"></div>
      <div class="mtg-inputs">
        <label class="mtg-input-group">
          <span>Down</span>
          <input class="mtg-input" type="number" min="0" max="100" step="1"
            value="${down}" oninput="update_mortgage('${listing.id}',${price})"
            id="mtg-down-${listing.id}">
          <span>%</span>
        </label>
        <label class="mtg-input-group">
          <span>Rate</span>
          <input class="mtg-input" type="number" min="0.1" max="20" step="0.1"
            value="${rate}" oninput="update_mortgage('${listing.id}',${price})"
            id="mtg-rate-${listing.id}">
          <span>%</span>
        </label>
        <label class="mtg-input-group">
          <span>Term</span>
          <select class="mtg-input" onchange="update_mortgage('${listing.id}',${price})"
            id="mtg-term-${listing.id}">
            <option value="30" ${term===30?"selected":""}>30 yr</option>
            <option value="15" ${term===15?"selected":""}>15 yr</option>
            <option value="20" ${term===20?"selected":""}>20 yr</option>
          </select>
        </label>
      </div>
    </div>
  </div>`;
}

function update_mortgage(listingId, price) {
  const down = +($(`mtg-down-${listingId}`)?.value ?? 20);
  const rate = +($(`mtg-rate-${listingId}`)?.value ?? 7);
  const term = +($(`mtg-term-${listingId}`)?.value ?? 30);
  try { localStorage.setItem("mtg-down", down); localStorage.setItem("mtg-rate", rate); localStorage.setItem("mtg-term", term); } catch (_) {}

  const principal = price * (1 - down / 100);
  const r = rate / 100 / 12;
  const n = term * 12;
  const monthly = r === 0 ? principal / n : principal * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
  const result = $(`mtg-result-${listingId}`);
  if (!result) return;

  if (!isFinite(monthly) || monthly <= 0) {
    result.innerHTML = `<span class="mtg-na">—</span>`;
    return;
  }
  result.innerHTML = `
    <span class="mtg-monthly">${fmt_price(Math.round(monthly))}<span class="mtg-mo">/mo</span></span>
    <span class="mtg-details">${fmt_price(Math.round(price * down / 100))} down · ${fmt_price(Math.round(principal))} loan</span>
  `;
}

// ── Quiz ──────────────────────────────────────────────
// ── Quiz wizard ──────────────────────────────────────
let _quiz_step = 1;
const QUIZ_TOTAL_STEPS = 7;

const QZ_THEMES = [
  "linear-gradient(160deg,#0a1628 0%,#1e3a8a 100%)",   // 1 Budget — deep navy
  "linear-gradient(160deg,#150d30 0%,#4c1d95 100%)",   // 2 Beds/Baths — violet
  "linear-gradient(160deg,#032620 0%,#065f46 100%)",   // 3 Buyer Type — emerald
  "linear-gradient(160deg,#1c0800 0%,#92400e 100%)",   // 4 Lifestyle — amber
  "linear-gradient(160deg,#0c0a26 0%,#3730a3 100%)",   // 5 Property Type — indigo
  "linear-gradient(160deg,#031c14 0%,#047857 100%)",   // 6 Condition — teal
  "linear-gradient(160deg,#120a30 0%,#1e3a8a 100%)",   // 7 Location — dark blue
];

function quiz_go_step(n) {
  // Hide old slide
  const oldSlide = $(`qstep-${_quiz_step}`);
  if (oldSlide) oldSlide.style.display = "none";

  _quiz_step = n;

  // Show new slide with animation re-trigger
  const newSlide = $(`qstep-${_quiz_step}`);
  if (newSlide) {
    newSlide.style.display = "flex";
    // Re-trigger the slide-in animation
    newSlide.style.animation = "none";
    newSlide.offsetHeight; // reflow
    newSlide.style.animation = "";
  }

  // Update overlay background gradient per step
  const overlay = $("quiz-modal-overlay");
  if (overlay) overlay.style.background = QZ_THEMES[_quiz_step - 1] || QZ_THEMES[0];

  // Update dots
  for (let i = 1; i <= QUIZ_TOTAL_STEPS; i++) {
    const dot = $(`qdot-${i}`);
    if (!dot) continue;
    dot.classList.remove("active", "done");
    if (i < _quiz_step) dot.classList.add("done");
    else if (i === _quiz_step) dot.classList.add("active");
  }

  // Update step counter
  if ($("quiz-step-counter")) $("quiz-step-counter").textContent = `${_quiz_step} / ${QUIZ_TOTAL_STEPS}`;

  // Show/hide nav buttons
  if ($("quiz-back")) $("quiz-back").style.display = _quiz_step > 1 ? "inline-flex" : "none";
  if ($("quiz-next")) $("quiz-next").style.display = _quiz_step < QUIZ_TOTAL_STEPS ? "inline-flex" : "none";
  if ($("quiz-save")) $("quiz-save").style.display = _quiz_step === QUIZ_TOTAL_STEPS ? "inline-flex" : "none";

  // Scroll slides container to top
  const slides = document.querySelector(".qz-slides");
  if (slides) slides.scrollTop = 0;
}

function open_quiz() {
  const q = state.quiz;

  // Pre-fill budget button groups
  ["quiz-budget-min-group", "quiz-budget-max-group"].forEach(gid => {
    const grp = $(gid); if (!grp) return;
    const val = gid === "quiz-budget-min-group" ? q.budgetMin : q.budgetMax;
    grp.querySelectorAll(".qz-price-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.val === (val || ""));
    });
  });

  // Beds/baths chips
  ["quiz-beds-group","quiz-baths-group"].forEach(gid => {
    const grp = $(gid); if (!grp) return;
    const val = gid === "quiz-beds-group" ? q.bedsMin : q.bathsMin;
    grp.querySelectorAll(".chip").forEach(c => c.classList.toggle("active", c.dataset.val === val));
  });

  // Buyer type
  $("quiz-buyer-grid")?.querySelectorAll(".quiz-buyer-card").forEach(c => {
    c.classList.toggle("active", c.dataset.val === q.buyerType);
  });

  // Lifestyle
  const lifestyle = q.lifestyle || q.style || "";
  $("quiz-modal-overlay").querySelectorAll(".quiz-style-chip").forEach(c => {
    c.classList.toggle("active", c.dataset.val === lifestyle);
  });

  // Property type
  $("quiz-proptype-group")?.querySelectorAll(".chip").forEach(c => {
    c.classList.toggle("active", c.dataset.val === q.propertyType);
  });

  // Condition
  $("quiz-condition-grid")?.querySelectorAll(".quiz-condition-card").forEach(c => {
    c.classList.toggle("active", c.dataset.val === q.condition);
  });

  // Neighborhood & features
  const neighborhood = q.neighborhood || "";
  $("quiz-neighborhood")?.querySelectorAll(".chip").forEach(c => {
    c.classList.toggle("active", c.dataset.val === neighborhood);
  });
  $("quiz-features-group")?.querySelectorAll(".chip").forEach(c => {
    c.classList.toggle("active", q.features.includes(c.dataset.val));
  });

  quiz_go_step(1);
  $("quiz-modal-overlay").style.display = "flex";
  document.body.style.overflow = "hidden";
}

function close_quiz() {
  $("quiz-modal-overlay").style.display = "none";
  document.body.style.overflow = "";
}

function save_quiz() {
  const lifestyle = $("quiz-modal-overlay").querySelector(".quiz-style-chip.active")?.dataset.val || "";
  const features = [...($("quiz-features-group")?.querySelectorAll(".chip.active") || [])]
    .map(c => c.dataset.val).filter(Boolean);
  const neighborhood = $("quiz-neighborhood")?.querySelector(".chip.active")?.dataset.val || "";
  const bedsMin = $("quiz-beds-group")?.querySelector(".chip.active")?.dataset.val || "";
  const bathsMin = $("quiz-baths-group")?.querySelector(".chip.active")?.dataset.val || "";
  const buyerType = $("quiz-buyer-grid")?.querySelector(".quiz-buyer-card.active")?.dataset.val || "";
  const condition = $("quiz-condition-grid")?.querySelector(".quiz-condition-card.active")?.dataset.val || "";
  const propertyType = $("quiz-proptype-group")?.querySelector(".chip.active")?.dataset.val || "";

  const budgetMin = $("quiz-budget-min-group")?.querySelector(".qz-price-btn.active")?.dataset.val || "";
  const budgetMax = $("quiz-budget-max-group")?.querySelector(".qz-price-btn.active")?.dataset.val || "";

  state.quiz = {
    budgetMin, budgetMax,
    lifestyle, features, neighborhood,
    bedsMin, bathsMin, buyerType, condition, propertyType,
    completed: true, _v: 2,
  };

  try { localStorage.setItem("buyer-quiz", JSON.stringify(state.quiz)); } catch (_) {}

  // Auto-switch sort to Best Match
  state.filters.sort = "match_desc";
  $("filter-sort").value = "match_desc";

  $("btn-clear-quiz").style.display = "inline-block";

  // Show My Matches tab and switch to it
  if ($("tab-matches")) $("tab-matches").style.display = "inline-flex";
  close_quiz();
  apply_filters();
  set_tab("matches");
}

function load_quiz_from_storage() {
  try {
    const saved = localStorage.getItem("buyer-quiz");
    if (saved) {
      const q = JSON.parse(saved);
      if (q.completed) {
        // Migrate v1 quiz — new fields default to blank (neutral scoring)
        if (!q._v || q._v < 2) {
          q.bedsMin = ""; q.bathsMin = ""; q.buyerType = "";
          q.condition = ""; q.propertyType = ""; q._v = 2;
        }
        state.quiz = q;
      }
    }
  } catch (_) {}
}

function clear_quiz() {
  state.quiz = {
    budgetMin: "", budgetMax: "", lifestyle: "", features: [], neighborhood: "",
    bedsMin: "", bathsMin: "", buyerType: "", condition: "", propertyType: "",
    completed: false, _v: 2,
  };
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
  wire_chips("filter-beds",   "beds");
  wire_chips("filter-baths",  "baths");
  wire_chips("filter-type",   "type");
  wire_chips("filter-area",   "area");
  wire_chips("filter-status", "status");
  wire_chips("filter-dom",    "dom");

  // Source: now a <select> instead of chips
  $("filter-source-select").addEventListener("change", (e) => {
    state.filters.source = e.target.value;
    apply_filters();
    _update_more_filters_badge();
  });

  // Search (debounced 250ms)
  $("filter-search").addEventListener("input", debounce((e) => {
    state.filters.search = e.target.value.trim();
    apply_filters();
  }, 250));

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
      dom: "", search: "", features: [], sort: "price_asc",
      luxuryOnly: true,
    };
    $("luxury-toggle").checked = true;
    // Reset UI
    $("filter-price-min").value = "";
    $("filter-price-max").value = "";
    $("filter-zip").value = "";
    $("filter-search").value = "";
    $("filter-sort").value = "price_asc";
    if ($("filter-source-select")) $("filter-source-select").value = "";
    document.querySelectorAll(".chip-group .chip").forEach((c) => {
      c.classList.toggle("active", c.dataset.val === "");
    });
    _update_more_filters_badge();
    apply_filters();
  });

  // Load more
  $("load-more").addEventListener("click", () => {
    state.page++;
    render_list();
  });

  // Tabs — set_tab is defined globally below wire_events
  $("tab-new"    ).addEventListener("click", () => set_tab("new"));
  $("tab-list"   ).addEventListener("click", () => set_tab("list"));
  $("tab-map"    ).addEventListener("click", () => set_tab("map"));
  $("tab-saved"  ).addEventListener("click", () => set_tab("saved"));
  $("tab-compare").addEventListener("click", () => set_tab("compare"));
  $("tab-matches")?.addEventListener("click", () => set_tab("matches"));

  // Modal close
  $("modal-close").addEventListener("click", close_modal);
  $("modal-overlay").addEventListener("click", (e) => {
    if (e.target === $("modal-overlay")) close_modal();
  });
  document.addEventListener("keydown", (e) => {
    const modalOpen = $("modal-overlay")?.style.display !== "none";
    if (e.key === "Escape") { close_modal(); return; }
    if (modalOpen && e.key === "ArrowRight") next_photo();
    if (modalOpen && e.key === "ArrowLeft")  prev_photo();
    if (modalOpen && e.key === "]") { modal_nav(1);  return; }
    if (modalOpen && e.key === "[") { modal_nav(-1); return; }
  });

  // Mobile sidebar + backdrop
  const _toggle_mobile_sidebar = () => {
    const sidebar = $("sidebar");
    const backdrop = $("sidebar-backdrop");
    const fab = $("mobile-filter-fab");
    sidebar.classList.toggle("open");
    const isOpen = sidebar.classList.contains("open");
    backdrop.style.display = isOpen ? "block" : "none";
    if (fab) fab.style.display = isOpen ? "none" : "";
  };
  $("mobile-filter-btn").addEventListener("click", _toggle_mobile_sidebar);
  $("sidebar-backdrop").addEventListener("click", () => {
    $("sidebar").classList.remove("open");
    $("sidebar-backdrop").style.display = "none";
    const fab = $("mobile-filter-fab");
    if (fab) fab.style.display = "";
  });

  // Luxury toggle
  $("luxury-toggle").addEventListener("change", (e) => {
    state.filters.luxuryOnly = e.target.checked;
    apply_filters();
  });

  // Quiz — both sidebar button and tab-bar button
  $("btn-find-match").addEventListener("click", open_quiz);
  $("tab-quiz-btn")?.addEventListener("click", open_quiz);
  $("btn-clear-quiz").addEventListener("click", clear_quiz);
  $("quiz-modal-overlay").addEventListener("click", (e) => {
    if (e.target === $("quiz-modal-overlay")) close_quiz();
  });
  $("quiz-close").addEventListener("click", close_quiz);
  $("quiz-save").addEventListener("click", save_quiz);
  $("quiz-next")?.addEventListener("click", () => quiz_go_step(_quiz_step + 1));
  $("quiz-back")?.addEventListener("click", () => quiz_go_step(_quiz_step - 1));

  // Quiz budget button groups (single-select)
  ["quiz-budget-min-group", "quiz-budget-max-group"].forEach(gid => {
    $(gid)?.addEventListener("click", (e) => {
      const btn = e.target.closest(".qz-price-btn");
      if (!btn) return;
      $(gid).querySelectorAll(".qz-price-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
    });
  });

  // Quiz style chips (single-select)
  $("quiz-modal-overlay").querySelectorAll(".quiz-style-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      $("quiz-modal-overlay").querySelectorAll(".quiz-style-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
    });
  });

  // Quiz beds/baths/proptype chips (single-select)
  ["quiz-beds-group","quiz-baths-group","quiz-proptype-group"].forEach(gid => {
    $(gid)?.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      $(gid).querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
    });
  });

  // Quiz buyer type cards (single-select + auto-advance)
  $("quiz-buyer-grid")?.addEventListener("click", (e) => {
    const card = e.target.closest(".quiz-buyer-card");
    if (!card) return;
    $("quiz-buyer-grid").querySelectorAll(".quiz-buyer-card").forEach(c => c.classList.remove("active"));
    card.classList.add("active");
    setTimeout(() => quiz_go_step(4), 350);
  });

  // Quiz condition cards (single-select + auto-advance)
  $("quiz-condition-grid")?.addEventListener("click", (e) => {
    const card = e.target.closest(".quiz-condition-card");
    if (!card) return;
    $("quiz-condition-grid").querySelectorAll(".quiz-condition-card").forEach(c => c.classList.remove("active"));
    card.classList.add("active");
    setTimeout(() => quiz_go_step(7), 350);
  });

  // Quiz feature chips (multi-select)
  $("quiz-features-group")?.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    chip.classList.toggle("active");
  });

  // Quiz neighborhood chips (single-select)
  $("quiz-neighborhood")?.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    $("quiz-neighborhood").querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
  });
}

// ── New listings tab ────────────────────────────────────────────────────────
function render_new() {
  const grid  = $("new-listings-grid");
  const empty = $("new-listings-empty");
  if (!grid) return;

  const fresh = (state.filtered || state.all)
    .filter(l => l.days_on_market != null && l.days_on_market <= 1)
    .sort((a, b) => (a.days_on_market ?? 9) - (b.days_on_market ?? 9));

  // Keep badge in sync with filtered count
  const badge = $("new-count");
  if (badge) badge.textContent = fresh.length || "";

  grid.innerHTML = "";
  if (fresh.length === 0) {
    empty && (empty.style.display = "block");
    return;
  }
  empty && (empty.style.display = "none");
  grid.innerHTML = fresh.map((l, i) => card_html(l, i)).join("");
  grid.querySelectorAll(".listing-card").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = +el.dataset.idx;
      open_modal(fresh[idx], fresh, idx);
    });
    const card_img_wrap = el.querySelector(".card-image");
    if (card_img_wrap) _wire_card_touch(card_img_wrap);
  });
}

// ── Tab switching (global so inline onclicks in tray can call it) ─────────────
function render_matches() {
  const grid = $("matches-grid");
  if (!grid) return;
  if (!state.quiz.completed) {
    grid.innerHTML = `<div class="matches-empty">Complete the quiz to see your top matches.</div>`;
    return;
  }
  const scored = state.filtered
    .map(l => ({ l, score: compute_match_score(l, state.quiz) ?? 0 }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 10);
  if (!scored.length) {
    grid.innerHTML = `<div class="matches-empty">No matches found — try adjusting your quiz or filters.</div>`;
    return;
  }
  grid.innerHTML = scored.map(({ l, score }, i) => {
    const why = generate_why_sentences(l, state.quiz);
    const ring_color = score >= 70 ? "#16a34a" : score >= 40 ? "#d97706" : "#9ca3af";
    const ring_deg = Math.round(score / 100 * 360);
    const stats = [l.beds && l.beds + " bd", l.baths && l.baths + " ba", l.sqft && Number(l.sqft).toLocaleString() + " sqft"].filter(Boolean).join(" · ");
    return `<div class="match-card" data-id="${l.id}" data-rank="${i}">
      <div class="match-rank-ring" style="background:conic-gradient(${ring_color} ${ring_deg}deg,#e5e7eb ${ring_deg}deg)">
        <div class="match-ring-inner">${score}<span class="match-ring-pct">%</span></div>
      </div>
      <div class="match-card-body">
        <div class="match-card-addr">${l.address || ""}${l.city ? ", " + l.city : ""}</div>
        <div class="match-card-price">${fmt_price(l.price)}</div>
        ${stats ? `<div class="match-card-stats">${stats}</div>` : ""}
        ${why.length ? `<ul class="match-why">${why.map(s => `<li>${s}</li>`).join("")}</ul>` : ""}
      </div>
    </div>`;
  }).join("");
  grid.querySelectorAll(".match-card").forEach(el => {
    el.addEventListener("click", () => {
      const listing = state.filtered.find(l => l.id === el.dataset.id);
      if (listing) open_modal(listing, state.filtered, state.filtered.indexOf(listing));
    });
  });
}

function set_tab(tab) {
  ["tab-new","tab-list","tab-map","tab-saved","tab-compare","tab-matches"].forEach(id => $(id)?.classList.remove("active"));
  ["view-new","view-list","view-map","view-saved","view-compare","view-matches"].forEach(id => { if ($(id)) $(id).style.display = "none"; });
  $("tab-" + tab)?.classList.add("active");
  if ($("view-" + tab)) $("view-" + tab).style.display = "block";
  if (tab === "map")     { init_map(); setTimeout(() => map && map.invalidateSize(), 100); }
  if (tab === "saved")   { render_saved(); }
  if (tab === "compare") { render_compare(); }
  if (tab === "new")     { render_new(); }
  if (tab === "matches") { render_matches(); }
}

// ── Bootstrap ─────────────────────────────────────────
// Restore saved listings from localStorage
try {
  const ids = JSON.parse(localStorage.getItem("saved-listings") || "[]");
  ids.forEach(id => state.saved.add(id));
  const badge = $("saved-count");
  if (badge && state.saved.size) badge.textContent = state.saved.size;
} catch (_) {}

// Restore sidebar collapsed state
try {
  if (localStorage.getItem("sidebar-collapsed") === "1") {
    $("sidebar")?.classList.add("collapsed");
    document.querySelector(".layout")?.classList.add("sidebar-collapsed");
  }
} catch (_) {}

wire_events();
load_data();

// Show My Matches tab if quiz was already completed
if (state.quiz.completed && $("tab-matches")) {
  $("tab-matches").style.display = "inline-flex";
}

// ── PWA service worker registration ───────────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
