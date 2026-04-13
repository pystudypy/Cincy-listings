"""
Feature extraction from listing description text.

Two-pass approach:
  Pass 1 — Keyword lookup table  (instant, zero cost, catches ~80% of features)
  Pass 2 — Qwen LLM via Ollama   (free, local, catches nuanced language)

Stores results on the listing as:
  listing["features"]    — list of tag strings, e.g. ["updated_kitchen", "pool"]
  listing["keywords"]    — list of plain-English phrases from Qwen, e.g. ["quartz waterfall island", "new 50-year roof"]

Usage:
    from utils.feature_tagger import tag_listings
    listings = tag_listings(listings)
"""

import json
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

OLLAMA_HOST  = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5vl:7b"   # VL model works fine for text-only — already pulled

REQUEST_DELAY = 0.1   # text inference is fast, small delay is enough


# ── keyword lookup table ─────────────────────────────────────────────────────
# Each entry: tag_name → list of phrases to search for (case-insensitive)

FEATURE_RULES: dict[str, list[str]] = {
    # Kitchen
    "updated_kitchen":   ["updated kitchen", "renovated kitchen", "kitchen remodel",
                          "kitchen renovation", "new kitchen", "kitchen update",
                          "chef's kitchen", "chef kitchen", "gourmet kitchen"],
    "quartz_counters":   ["quartz counter", "quartz island", "quartz top", "quartzite"],
    "granite_counters":  ["granite counter", "granite island", "granite top"],
    "kitchen_island":    ["kitchen island", "center island", "large island", "oversized island"],
    "new_appliances":    ["new appliances", "updated appliances", "stainless appliances",
                          "stainless steel appliance", "brand new appliance"],

    # Floors
    "hardwood_floors":   ["hardwood floor", "hardwood throughout", "wood floor",
                          "original hardwood", "refinished hardwood", "engineered hardwood"],
    "new_flooring":      ["new floor", "new flooring", "new carpet", "luxury vinyl plank",
                          "lvp flooring", "tile throughout"],

    # Layout
    "open_floor_plan":   ["open floor plan", "open concept", "open-concept", "open layout",
                          "open living", "great room", "open floorplan"],

    # Outdoor
    "pool":              ["in-ground pool", "inground pool", "swimming pool",
                          "heated pool", "saltwater pool", "pool and spa", "pool/spa"],
    "fenced_yard":       ["fenced yard", "fenced backyard", "fenced back yard",
                          "privacy fence", "fenced-in yard", "fully fenced"],
    "deck_patio":        ["deck", "patio", "screened porch", "covered porch",
                          "outdoor entertainment", "outdoor living"],
    "large_lot":         ["acre lot", "acres of land", "large lot", "half acre",
                          "oversized lot", "corner lot", "cul-de-sac"],

    # Structural / systems
    "new_roof":          ["new roof", "roof replaced", "new shingles", "roof 202",
                          "roof 201", "new roof 2", "replaced roof", "updated roof"],
    "new_hvac":          ["new hvac", "new furnace", "new ac", "new air condition",
                          "hvac replaced", "new boiler", "new heat pump",
                          "replaced furnace", "new heating"],
    "new_windows":       ["new windows", "replacement windows", "updated windows",
                          "energy efficient windows", "new window"],
    "finished_basement": ["finished basement", "finished lower level",
                          "finished rec room", "walkout basement", "walk-out basement",
                          "fully finished basement"],

    # Rooms / features
    "fireplace":         ["fireplace", "gas fireplace", "wood-burning fireplace",
                          "wood burning fireplace", "electric fireplace"],
    "master_suite":      ["master suite", "primary suite", "en suite", "ensuite",
                          "owner's suite", "owners suite", "primary bedroom suite"],
    "walk_in_closet":    ["walk-in closet", "walk in closet", "walkin closet",
                          "large closet", "his and her closet", "his/her closet"],
    "bonus_room":        ["bonus room", "loft", "flex room", "flex space",
                          "home office", "study", "den", "sunroom", "sun room"],
    "in_law_suite":      ["in-law suite", "in law suite", "mother-in-law",
                          "multigenerational", "accessory dwelling", "guest suite",
                          "separate entrance", "second kitchen"],

    # Garage / parking
    "two_car_garage":    ["2-car garage", "two-car garage", "2 car garage",
                          "double garage", "2 car attached", "two car attached"],
    "three_car_garage":  ["3-car garage", "three-car garage", "3 car garage",
                          "triple garage"],

    # Condition / move-in
    "move_in_ready":     ["move-in ready", "move in ready", "turnkey", "turn key",
                          "completely updated", "fully updated", "fully renovated",
                          "totally renovated"],
    "new_construction":  ["new construction", "newly built", "new build",
                          "custom built", "brand new home", "just built"],
    "needs_work":        ["sold as-is", "as-is", "sold as is", "investor special",
                          "fixer upper", "fixer-upper", "tlc needed", "needs work",
                          "needs updating", "needs renovation", "handyman special"],

    # Style
    "smart_home":        ["smart home", "smart thermostat", "nest thermostat",
                          "ring doorbell", "smart lighting", "home automation"],
    "solar":             ["solar panel", "solar energy", "solar power", "solar system"],
    "ev_charger":        ["ev charger", "electric vehicle charger", "ev charging"],

    # Bathrooms
    "updated_bathrooms": ["updated bath", "renovated bath", "new bath",
                          "updated master bath", "updated master bathroom",
                          "bathroom remodel", "bath remodel"],
    "soaking_tub":       ["soaking tub", "freestanding tub", "clawfoot tub",
                          "jetted tub", "jacuzzi tub", "garden tub"],
    "walk_in_shower":    ["walk-in shower", "walk in shower", "glass shower",
                          "tiled shower", "oversized shower", "rain shower"],
}

# Build compiled regex for each rule — match whole-word style
_COMPILED: dict[str, re.Pattern] = {
    tag: re.compile(
        "|".join(re.escape(phrase) for phrase in phrases),
        re.IGNORECASE,
    )
    for tag, phrases in FEATURE_RULES.items()
}


def _keyword_tag(description: str) -> list[str]:
    """Return list of matched feature tags from keyword rules."""
    if not description:
        return []
    return [tag for tag, pat in _COMPILED.items() if pat.search(description)]


# ── Qwen LLM tagging ─────────────────────────────────────────────────────────

LLM_PROMPT = """You are helping home buyers search for properties online. Read the listing description below and extract the most useful search keywords — things a buyer would actually type into a search box.

Focus on:
- Renovations and updates: "updated kitchen", "new roof 2023", "renovated bathrooms"
- Materials and finishes: "quartz countertops", "hardwood floors", "marble tile"
- Special features: "heated pool", "finished walkout basement", "3-car garage", "in-law suite"
- Outdoor spaces: "half acre lot", "screened porch", "fenced yard"
- Condition and style: "move-in ready", "original craftsman details", "mid-century modern"
- Systems: "new HVAC 2022", "new windows", "smart thermostat"

Rules:
- Use plain buyer language, not agent jargon
- Only extract features clearly stated in the description
- Include specific details when mentioned (e.g. "new roof 2023" not just "new roof")
- Max 15 keywords

Description:
{description}

Respond ONLY with a JSON array of keyword strings, no explanation:
["updated kitchen", "quartz countertops", ...]"""


def _ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(OLLAMA_MODEL.split(":")[0] in m for m in models)
    except Exception:
        return False


def _llm_tag(description: str) -> list[str]:
    """Send description to Qwen and return extracted keyword phrases."""
    if not description or len(description) < 80:
        return []
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512},
                "messages": [{
                    "role": "user",
                    "content": LLM_PROMPT.format(description=description[:2000]),
                }],
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]

        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start != -1 and end > start:
            raw = raw[start:end]

        keywords = json.loads(raw)
        if isinstance(keywords, list):
            return [str(k).strip().lower() for k in keywords if k and len(str(k)) > 2]
    except Exception as e:
        logger.debug(f"LLM tag failed: {e}")
    return []


# ── public API ───────────────────────────────────────────────────────────────

def tag_listings(
    listings: list[dict],
    use_llm: bool = True,
    force: bool = False,
    checkpoint_every: int = 100,
    checkpoint_fn=None,
) -> list[dict]:
    """
    Tag each listing with features (keyword pass) and keywords (LLM pass).

    Args:
        listings:         Full listing list (modified in place).
        use_llm:          Whether to run Qwen LLM pass (needs Ollama running).
        force:            Re-tag listings that already have features.
        checkpoint_every: Call checkpoint_fn every N listings processed.
        checkpoint_fn:    Optional callback(listings) for incremental saves.
    """
    to_tag = [
        l for l in listings
        if l.get("description") and (force or not l.get("features") or (use_llm and not l.get("keywords")))
    ]

    if not to_tag:
        logger.info("Feature tagging: nothing to tag (no descriptions or all already tagged)")
        return listings

    total = len(to_tag)

    llm_available = False
    if use_llm:
        llm_available = _ollama_available()
        if llm_available:
            logger.info(f"Feature tagging: running keyword + Qwen LLM on {total} listings…")
        else:
            logger.info(f"Feature tagging: Ollama not available — keyword-only on {total} listings")
    else:
        logger.info(f"Feature tagging: keyword-only on {total} listings…")

    done = 0
    for listing in to_tag:
        desc = listing.get("description", "")

        # Pass 1: keyword rules
        features = _keyword_tag(desc)
        listing["features"] = features

        # Pass 2: LLM keywords
        if llm_available:
            keywords = _llm_tag(desc)
            listing["keywords"] = keywords
            time.sleep(REQUEST_DELAY)

        done += 1
        if done % checkpoint_every == 0:
            logger.info(f"Feature tagging: {done}/{total} done…")
            if checkpoint_fn:
                checkpoint_fn(listings)

    logger.info(f"Feature tagging complete: {done} listings tagged")
    return listings
